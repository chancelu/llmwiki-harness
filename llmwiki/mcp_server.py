"""MCP server for LLMWiki — expose the wiki as memory tools for any MCP host.

Works with any MCP-compatible client (Claude Desktop, Cursor, Codex, ...).
Transport is stdio (the MCP default for local servers).

Run it via the CLI:

    llmwiki mcp                       # stdio server, vault from config/env
    llmwiki -v ~/Documents/selfwiki mcp

or via the dedicated entry point (handy for uvx):

    uvx --from "llmwiki-harness[mcp]" llmwiki-mcp

Tools exposed to the host:
  - memory_search(query, top_k)        → raw ranked results (JSON)
  - memory_recall(query, token_budget) → assembled context block, ready to inject
  - memory_capture(user, assistant)    → append a conversation turn to the chronicle
  - memory_curate()                    → chronicle → compiled wiki notes
  - memory_stats()                     → vault/index/cache statistics

Prompts exposed to the host:
  - memory-protocol                    → host-side behavior template: when to
                                         recall, capture, and curate

`memory_curate` uses the host's own LLM via MCP **sampling** when the client
supports it (zero configuration — no API key or endpoint needed). Fallback
chain: sampling → LLMWIKI_LLM_ENDPOINT → regex extraction.

The plain tool functions in this module work without the `mcp` package
installed; only `create_server()`/`main()` require the `mcp` extra.

Note: this module deliberately avoids `from __future__ import annotations`
so the `ctx: Context` tool annotation survives introspection by the SDK.
"""

import asyncio
import json
import logging
import sys
from typing import Any, Callable, Dict, Optional

from llmwiki import __version__
from llmwiki.core.config import load_config
from llmwiki.core.harness import ContextMemoryHarness

logger = logging.getLogger(__name__)

_harness: Optional[ContextMemoryHarness] = None


def _get_harness() -> ContextMemoryHarness:
    """Lazily build the harness from config file / env vars."""
    global _harness
    if _harness is None:
        config = load_config()
        _harness = ContextMemoryHarness(config=config)
        _harness.build_index()
    return _harness


def set_harness(harness: ContextMemoryHarness) -> None:
    """Inject a preconfigured harness (used by the CLI and tests)."""
    global _harness
    _harness = harness


# ---------------------------------------------------------------------------
# Memory protocol prompt (exposed as an MCP prompt)
# ---------------------------------------------------------------------------

_MEMORY_PROTOCOL = """You are connected to LLMWiki, the user's persistent local memory wiki.
Follow this protocol to make the memory layer actually work:

BEFORE answering:
- If the user's message might relate to anything from past sessions —
  projects, people, preferences, decisions, earlier problems — call
  memory_recall(query=<the user's message>) first and weave the returned
  context into your answer. When in doubt, recall.
- Use memory_search when you need raw ranked notes rather than an
  assembled context block.

AFTER answering:
- If the exchange produced durable knowledge — a decision, a new fact about
  the user, project state changes, a solution to a problem — call
  memory_capture with a faithful summary of both sides. Skip small talk and
  one-off lookups. When in doubt, capture.

PERIODICALLY:
- After a long working session, or when the user asks to consolidate, call
  memory_curate to distill the raw chronicle into atomic wiki notes.

RULES:
- Memory only helps if you use it: recall first, capture after.
- Never fabricate memories. If recall returns empty, say you have no prior
  notes on the topic.
- The vault is the user's plain-Markdown data. Write only through the
  provided tools; never modify vault files directly."""


# ---------------------------------------------------------------------------
# Tool implementations (no mcp dependency — plain functions)
# ---------------------------------------------------------------------------


def memory_search(query: str, top_k: int = 5) -> str:
    """Search the local wiki memory for notes relevant to a query.

    Use this before answering when the user might have relevant long-term
    knowledge stored from previous sessions.

    Args:
        query: Search query, typically the user's message or a topic.
        top_k: Maximum number of notes to return.

    Returns:
        JSON array of results with path, title, snippet, and score.
    """
    results = _get_harness().retrieve(query, top_k=top_k)
    return json.dumps(results, ensure_ascii=False, indent=2)


def memory_recall(query: str, token_budget: int = 2000) -> str:
    """Recall wiki knowledge as a ready-to-inject context block.

    Like memory_search, but the results are assembled and formatted within
    the given token budget — paste the output directly into a system prompt.

    Args:
        query: Search query, typically the user's message.
        token_budget: Maximum tokens for the returned context block.

    Returns:
        Formatted context string, or an empty string when nothing relevant
        is found in the wiki.
    """
    return _get_harness().retrieve_and_assemble(query, token_budget=token_budget)


def memory_capture(
    user_message: str,
    assistant_message: str,
    session_id: str = "",
) -> str:
    """Capture a conversation turn into the wiki chronicle (long-term memory).

    Call this after meaningful exchanges so future sessions can recall them.
    Skip trivial small talk.

    Args:
        user_message: The user's message.
        assistant_message: The assistant's response.
        session_id: Optional session identifier for grouping turns.

    Returns:
        Confirmation message with the chronicle note path.
    """
    harness = _get_harness()
    path = harness.capture_engine.append(user_message, assistant_message, session_id=session_id)
    harness.clear_cache()  # new knowledge may change recall results
    return f"Captured to {path}"


def memory_curate() -> str:
    """Run the curation pipeline: distill recent chronicle notes into
    compiled atomic wiki notes (entities, concepts, projects).

    When the MCP client supports sampling, the host's own LLM performs the
    extraction (zero configuration). Otherwise falls back to the endpoint
    configured via LLMWIKI_LLM_ENDPOINT, then to regex-based extraction.

    Returns:
        JSON summary with processed/created/archived counts.
    """
    llm_generate = None
    try:
        from llmwiki.cli import _make_llm_generate

        llm_generate = _make_llm_generate()
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("LLM callback unavailable: %s", e)

    stats = _get_harness().curate(llm_generate=llm_generate)
    return json.dumps(stats, ensure_ascii=False, indent=2)


def memory_stats() -> str:
    """Get statistics about the wiki memory: note counts per layer,
    active search engines, and cache state.

    Returns:
        JSON object with vault statistics.
    """
    return json.dumps(_get_harness().stats(), ensure_ascii=False, indent=2)


_TOOLS = [memory_search, memory_recall, memory_capture, memory_curate, memory_stats]


# ---------------------------------------------------------------------------
# Sampling bridge (host LLM → sync curation callback)
# ---------------------------------------------------------------------------


def _make_sampling_generate(ctx: Any, loop: asyncio.AbstractEventLoop) -> Optional[Callable]:
    """Build a sync llm_generate callback backed by MCP sampling.

    The curation engine is synchronous and calls ``llm_generate(prompt)`` per
    note. Sampling is async and must run on the server's event loop, so we
    bridge with ``run_coroutine_threadsafe`` while the curation itself runs
    in an executor thread (the event loop stays free to process the client's
    sampling responses — no deadlock).

    Returns None when the client does not support sampling (probed with one
    cheap round-trip), so callers can fall back to the next LLM source.
    """

    async def _sample(prompt: str) -> str:
        from mcp import types

        result = await ctx.session.create_message(
            messages=[
                types.SamplingMessage(
                    role="user",
                    content=types.TextContent(type="text", text=prompt),
                )
            ],
            max_tokens=2000,
            temperature=0.2,
        )
        content = result.content
        return getattr(content, "text", str(content))

    def generate(prompt: str) -> str:
        future = asyncio.run_coroutine_threadsafe(_sample(prompt), loop)
        return future.result(timeout=180)

    # Probe once with a tiny request — clients without sampling support
    # raise here (method not found / capability missing).
    try:
        generate("Reply with exactly: OK")
    except Exception as e:
        logger.info("MCP sampling unavailable (%s); curation falls back", e)
        return None
    return generate


async def _curate_via_sampling(ctx: Any) -> str:
    """memory_curate variant that prefers the host's LLM via sampling."""
    harness = _get_harness()
    loop = asyncio.get_running_loop()

    # The probe and all sampling calls must happen OFF the event-loop thread:
    # they bridge back onto the loop via run_coroutine_threadsafe, which would
    # deadlock if the loop thread itself were the one blocking on the result.
    llm_generate = await loop.run_in_executor(None, _make_sampling_generate, ctx, loop)
    if llm_generate is None:
        try:
            from llmwiki.cli import _make_llm_generate

            llm_generate = _make_llm_generate()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("LLM callback unavailable: %s", e)

    stats = await loop.run_in_executor(None, lambda: harness.curate(llm_generate=llm_generate))
    return json.dumps(stats, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Server wiring (requires the `mcp` package)
# ---------------------------------------------------------------------------


def create_server():
    """Build the MCP server. Requires `pip install llmwiki-harness[mcp]`.

    Compatible with both mcp 1.x (`FastMCP`) and mcp 2.x (`MCPServer`).
    """
    try:
        try:
            # mcp 1.x
            from mcp.server.fastmcp import Context as _Context
            from mcp.server.fastmcp import FastMCP as _Server
        except ImportError:
            # mcp 2.x renamed FastMCP to MCPServer
            from mcp.server.mcpserver import Context as _Context
            from mcp.server.mcpserver import MCPServer as _Server
    except ImportError as e:
        raise RuntimeError(
            "The MCP server requires the 'mcp' package. "
            "Install it with: pip install 'llmwiki-harness[mcp]'"
        ) from e

    server = _Server(
        "llmwiki",
        version=__version__,
        instructions=(
            "LLMWiki long-term memory: a local Markdown wiki acting as the "
            "agent's persistent disk. Use memory_recall/memory_search before "
            "answering to retrieve prior knowledge, memory_capture after "
            "meaningful turns to store new knowledge, and memory_curate "
            "periodically to distill the chronicle into atomic notes. Load "
            "the 'memory-protocol' prompt for the full operating protocol."
        ),
    )

    for tool_fn in _TOOLS:
        if tool_fn.__name__ == "memory_curate":
            continue  # registered below with sampling support
        server.tool()(tool_fn)

    @server.tool()
    async def memory_curate(ctx: _Context) -> str:  # noqa: F811
        """Run the curation pipeline: distill recent chronicle notes into
        compiled atomic wiki notes (entities, concepts, projects).

        Uses your own model via MCP sampling when available (zero
        configuration); otherwise falls back to a configured LLM endpoint,
        then regex-based extraction.

        Returns:
            JSON summary with processed/created/archived counts.
        """
        return await _curate_via_sampling(ctx)

    @server.prompt(
        name="memory-protocol",
        description="How to use LLMWiki memory: when to recall, capture, and curate",
    )
    def memory_protocol() -> str:
        return _MEMORY_PROTOCOL

    return server


def main(config: Optional[Dict[str, Any]] = None) -> None:
    """Entry point for `llmwiki mcp` and the `llmwiki-mcp` script.

    All logging goes to stderr — stdout is reserved for the MCP protocol.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    if config is not None:
        harness = ContextMemoryHarness(config=config)
        harness.build_index()
        set_harness(harness)

    server = create_server()
    server.run()


if __name__ == "__main__":
    main()

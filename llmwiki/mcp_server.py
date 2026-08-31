"""MCP server for LLMWiki — expose the wiki as memory tools for any MCP host.

Works with Claude Desktop, Claude Code, Cursor, Codex, and any other
MCP-compatible client. Transport is stdio (the MCP default for local servers).

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

The plain tool functions in this module work without the `mcp` package
installed; only `create_server()`/`main()` require the `mcp` extra.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, Optional

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
    path = harness.capture_engine.append(
        user_message, assistant_message, session_id=session_id
    )
    harness.clear_cache()  # new knowledge may change recall results
    return f"Captured to {path}"


def memory_curate() -> str:
    """Run the curation pipeline: distill recent chronicle notes into
    compiled atomic wiki notes (entities, concepts, projects).

    Uses LLM-driven extraction when LLMWIKI_LLM_ENDPOINT is configured,
    otherwise falls back to regex-based extraction.

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
# Server wiring (requires the `mcp` package)
# ---------------------------------------------------------------------------


def create_server():
    """Build the MCP server. Requires `pip install llmwiki-harness[mcp]`.

    Compatible with both mcp 1.x (`FastMCP`) and mcp 2.x (`MCPServer`).
    """
    try:
        try:
            # mcp 1.x
            from mcp.server.fastmcp import FastMCP as _Server
        except ImportError:
            # mcp 2.x renamed FastMCP to MCPServer
            from mcp.server.mcpserver import MCPServer as _Server
    except ImportError as e:
        raise RuntimeError(
            "The MCP server requires the 'mcp' package. "
            "Install it with: pip install 'llmwiki-harness[mcp]'"
        ) from e

    server = _Server(
        "llmwiki",
        instructions=(
            "LLMWiki long-term memory: a local Markdown wiki acting as the "
            "agent's persistent disk. Use memory_recall/memory_search before "
            "answering to retrieve prior knowledge, memory_capture after "
            "meaningful turns to store new knowledge, and memory_curate "
            "periodically to distill the chronicle into atomic notes."
        ),
    )

    for tool_fn in _TOOLS:
        server.tool()(tool_fn)

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

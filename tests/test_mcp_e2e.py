"""End-to-end MCP test: spawn the real stdio server subprocess and speak
the MCP protocol (initialize → list_tools → call_tool).

Skipped automatically when the `mcp` package is not installed.
"""

import asyncio
import copy
import os
import socket
import sys
import threading
import time

import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def test_mcp_stdio_end_to_end(tmp_path):
    vault = tmp_path / "vault"
    env = dict(os.environ, LLMWIKI_VAULT_PATH=str(vault))
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "llmwiki.mcp_server"],
        env=env,
    )

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                assert names == [
                    "memory_capture",
                    "memory_curate",
                    "memory_recall",
                    "memory_search",
                    "memory_stats",
                ]

                r = await session.call_tool(
                    "memory_capture",
                    {
                        "user_message": "What is the Zorblax protocol?",
                        "assistant_message": "The Zorblax protocol is a test handshake.",
                    },
                )
                assert "Captured to" in r.content[0].text

                r = await session.call_tool(
                    "memory_search", {"query": "Zorblax protocol", "top_k": 3}
                )
                assert "Zorblax" in r.content[0].text

                r = await session.call_tool(
                    "memory_recall", {"query": "Zorblax", "token_budget": 500}
                )
                assert "Zorblax" in r.content[0].text

                r = await session.call_tool("memory_stats", {})
                assert "vault_path" in r.content[0].text

    asyncio.run(run())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"server did not open port {port}")


def test_mcp_http_end_to_end(tmp_path):
    """Streamable-HTTP transport: in-process server + real MCP client."""
    try:
        # mcp 1.x
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        # mcp 2.x renamed the helper
        from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

    from llmwiki import mcp_server
    from llmwiki.core.config import DEFAULT_CONFIG
    from llmwiki.core.harness import ContextMemoryHarness

    config = copy.deepcopy(DEFAULT_CONFIG)
    config["vault"]["path"] = str(tmp_path / "vault")
    harness = ContextMemoryHarness(config=config)
    harness.build_index()
    mcp_server.set_harness(harness)

    server = mcp_server.create_server()
    port = _free_port()
    thread = threading.Thread(
        target=server.run,
        kwargs={"transport": "streamable-http", "host": "127.0.0.1", "port": port},
        daemon=True,
    )
    thread.start()
    try:
        _wait_port(port)

        async def run():
            url = f"http://127.0.0.1:{port}/mcp"
            async with streamablehttp_client(url) as streams:
                read, write = streams[0], streams[1]  # 1.x yields 3, 2.x yields 2
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    tools = await session.list_tools()
                    names = sorted(t.name for t in tools.tools)
                    assert "memory_search" in names
                    assert "memory_capture" in names

                    r = await session.call_tool(
                        "memory_capture",
                        {
                            "user_message": "deploy the http transport",
                            "assistant_message": "Streamable HTTP is now wired up.",
                        },
                    )
                    assert "Captured to" in r.content[0].text

                    r = await session.call_tool(
                        "memory_search", {"query": "http transport", "top_k": 3}
                    )
                    assert "transport" in r.content[0].text.lower()

        asyncio.run(run())
    finally:
        harness.close()

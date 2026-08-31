"""End-to-end MCP test: spawn the real stdio server subprocess and speak
the MCP protocol (initialize → list_tools → call_tool).

Skipped automatically when the `mcp` package is not installed.
"""

import asyncio
import os
import sys

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

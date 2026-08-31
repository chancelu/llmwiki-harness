"""Tests for the MCP server module.

The plain tool functions (memory_search, memory_capture, ...) are tested
directly without the `mcp` package. Server wiring is tested when `mcp`
is installed, and its absence is tested for a clean RuntimeError.
"""

import copy
import importlib.util
import json

import pytest

from llmwiki import mcp_server
from llmwiki.core.config import DEFAULT_CONFIG
from llmwiki.core.harness import ContextMemoryHarness


@pytest.fixture
def harness(tmp_path):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["vault"]["path"] = str(tmp_path / "vault")
    config["cache"]["enabled"] = False  # keep tests deterministic
    h = ContextMemoryHarness(config=config)
    mcp_server.set_harness(h)
    yield h
    mcp_server.set_harness(None)


def test_memory_capture_writes_chronicle(harness):
    msg = mcp_server.memory_capture(
        "What is the Zorblax protocol?",
        "The Zorblax protocol is a fictional handshake for testing.",
    )
    assert "Captured to" in msg

    daily_dir = harness.vault_path / "chronicle" / "daily"
    notes = list(daily_dir.glob("*.md"))
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "Zorblax protocol" in text


def test_memory_search_finds_captured_turn(harness):
    mcp_server.memory_capture(
        "Tell me about Project Nightingale",
        "Project Nightingale is a secret initiative about async memory.",
    )
    out = mcp_server.memory_search("Project Nightingale", top_k=3)
    results = json.loads(out)
    assert isinstance(results, list)
    assert results, "expected at least one result"
    assert any("Nightingale" in (r["snippet"] + r["title"]) for r in results)


def test_memory_search_no_match_returns_empty_list(harness):
    out = mcp_server.memory_search("qqqunlikelytokenzzz", top_k=3)
    assert json.loads(out) == []


def test_memory_recall_assembles_context(harness):
    mcp_server.memory_capture(
        "Explain flux capacitors",
        "A flux capacitor enables time travel at 88 mph.",
    )
    context = mcp_server.memory_recall("flux capacitor", token_budget=1000)
    assert "Wiki Context" in context
    assert "flux capacitor" in context.lower()


def test_memory_recall_no_match_returns_empty(harness):
    assert mcp_server.memory_recall("qqqunlikelytokenzzz") == ""


def test_memory_curate_regex_fallback(harness, monkeypatch):
    # Ensure no LLM endpoint is configured → regex fallback path
    monkeypatch.delenv("LLMWIKI_LLM_ENDPOINT", raising=False)

    harness.capture_engine.append_insight(
        "Entity",
        "Ada Lovelace",
        "Ada Lovelace wrote the first algorithm intended for a machine. "
        "She worked with Charles Babbage on the Analytical Engine design. "
        "Her notes on the engine include what is recognized today as the "
        "first computer program, a method for computing Bernoulli numbers.",
    )
    out = json.loads(mcp_server.memory_curate())
    assert out["status"] == "ok"
    assert out["processed"] >= 1
    assert out["created"] >= 1

    note = harness.vault_path / "entities" / "Ada Lovelace.md"
    assert note.exists()
    assert "Analytical Engine" in note.read_text(encoding="utf-8")


def test_memory_stats_shape(harness):
    stats = json.loads(mcp_server.memory_stats())
    assert "vault_path" in stats
    assert "index_engines" in stats
    assert "vault" in stats


def test_mcp_server_wiring():
    """create_server requires the mcp package; verify both paths."""
    if importlib.util.find_spec("mcp") is None:
        with pytest.raises(RuntimeError, match="mcp"):
            mcp_server.create_server()
    else:
        server = mcp_server.create_server()
        assert server is not None

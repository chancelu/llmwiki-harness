"""Tests for the Retriever strategies.

Covers the token-based temporal search (the old whole-string containment
missed almost every natural-language query) and wikilink resolution beyond
the compiled layer.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from llmwiki.core.indexer import IndexRegistry
from llmwiki.core.retriever import Retriever, _query_tokens

SCHEMA_DIRS = ["entities", "concepts", "chronicle/daily"]


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    for d in SCHEMA_DIRS:
        (v / d).mkdir(parents=True)
    return v


@pytest.fixture
def retriever(vault):
    registry = IndexRegistry(vault, SCHEMA_DIRS, engine_names=["python"])
    r = Retriever(registry, vault)
    yield r
    # Release SQLite handles (Windows file locking)
    if r.graph is not None:
        r.graph.close()
    registry.close()


def _daily(vault, days_ago: int, text: str) -> Path:
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    p = vault / "chronicle" / "daily" / f"{date}.md"
    p.write_text(f"# Daily Chronicle: {date}\n\n{text}\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Query tokenization
# ---------------------------------------------------------------------------


def test_query_tokens_english():
    assert _query_tokens("What is the Zorblax protocol?") == [
        "what",
        "is",
        "the",
        "zorblax",
        "protocol",
    ]


def test_query_tokens_cjk_bigrams():
    tokens = _query_tokens("知识图谱怎么用")
    assert "知识" in tokens
    assert "图谱" in tokens
    assert "怎么" in tokens
    assert len(tokens) == 6  # overlapping bigrams of a 6-char run


def test_query_tokens_mixed():
    tokens = _query_tokens("LLM 的记忆")
    assert "llm" in tokens
    assert "记忆" in tokens  # 2-char CJK token kept as-is


# ---------------------------------------------------------------------------
# Temporal strategy
# ---------------------------------------------------------------------------


def test_temporal_matches_multiword_query(retriever, vault):
    """Old code required the whole query string in the note — this missed."""
    _daily(vault, 0, "**User:** tell me about the Zorblax handshake design\n")
    results = retriever._temporal_search("Zorblax handshake", days_back=7, top_k=5)
    assert results
    assert "Zorblax" in results[0]["snippet"]


def test_temporal_matches_cjk_query(retriever, vault):
    _daily(vault, 0, "今天讨论了知识图谱作为结构化长期记忆的方案。\n")
    results = retriever._temporal_search("知识图谱怎么用", days_back=7, top_k=5)
    assert results, "CJK bigram matching should hit"


def test_temporal_recency_breaks_ties(retriever, vault):
    _daily(vault, 5, "notes about zorblax\n")
    _daily(vault, 0, "notes about zorblax\n")
    results = retriever._temporal_search("zorblax", days_back=30, top_k=5)
    assert len(results) == 2
    assert results[0]["score"] > results[1]["score"]
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in results[0]["path"]


def test_temporal_respects_days_back(retriever, vault):
    _daily(vault, 30, "old notes about zorblax\n")
    results = retriever._temporal_search("zorblax", days_back=7, top_k=5)
    assert results == []


def test_temporal_no_token_match(retriever, vault):
    _daily(vault, 0, "completely unrelated content\n")
    assert retriever._temporal_search("zorblax", days_back=7, top_k=5) == []


# ---------------------------------------------------------------------------
# Graph strategy: wikilink resolution
# ---------------------------------------------------------------------------


def test_graph_resolves_links_into_chronicle(retriever, vault):
    # daily note deliberately does NOT contain the query token, so it can
    # only be found by traversing the wikilink from the entity note
    daily = _daily(vault, 0, "session about the handshake design\n")
    date_stem = daily.stem
    (vault / "entities" / "zorblax.md").write_text(
        f"# Zorblax\n\nSee [[{date_stem}]] for the discussion.\n",
        encoding="utf-8",
    )

    results = retriever._graph_search("zorblax", top_k=5)
    paths = [r["path"] for r in results]
    assert any("chronicle/daily" in p and date_stem in p for p in paths)


def test_graph_resolves_via_vault_wide_fallback(retriever, vault):
    """Links into directories outside the known schema dirs still resolve."""
    nested = vault / "misc" / "deep"
    nested.mkdir(parents=True)
    (nested / "Hidden Note.md").write_text("# Hidden\n\ndeep content\n", encoding="utf-8")
    (vault / "entities" / "zorblax.md").write_text(
        "# Zorblax\n\nRelated: [[Hidden Note]].\n",
        encoding="utf-8",
    )

    results = retriever._graph_search("zorblax", top_k=5)
    paths = [r["path"] for r in results]
    assert any("Hidden Note" in p for p in paths)


def test_graph_ignores_unresolvable_links(retriever, vault):
    (vault / "entities" / "zorblax.md").write_text(
        "# Zorblax\n\nSee [[Nowhere Land]].\n",
        encoding="utf-8",
    )
    results = retriever._graph_search("zorblax", top_k=5)
    assert all("Nowhere" not in r["path"] for r in results)

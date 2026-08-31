"""Tests for the SQLite FTS5 search engine.

Covers the query sanitizer (special characters must not break MATCH),
trigram tokenizer CJK support, the LIKE fallback for short tokens,
snippet extraction, and schema migration from pre-trigram databases.
"""

import sqlite3

import pytest

from llmwiki.search.sqlite_engine import SQLiteEngine, _extract_snippet

SCHEMA_DIRS = ["entities", "concepts", "chronicle/daily"]


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    for d in SCHEMA_DIRS:
        (v / d).mkdir(parents=True)
    return v


@pytest.fixture
def engine(vault):
    e = SQLiteEngine()
    yield e
    if e._conn is not None:
        e._conn.close()


def _write(vault, rel: str, text: str):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _index(engine, vault):
    engine.index(vault, SCHEMA_DIRS)


# ---------------------------------------------------------------------------
# CJK / trigram
# ---------------------------------------------------------------------------


def test_cjk_phrase_search(engine, vault):
    _write(vault, "concepts/memory.md", "# 记忆\n\n知识图谱是结构化长期记忆的关键技术。\n")
    _index(engine, vault)

    results = engine.search("知识图谱", vault, SCHEMA_DIRS)
    assert results, "CJK query should match with trigram tokenizer"
    assert results[0].path == "concepts/memory.md"


def test_cjk_substring_search(engine, vault):
    """A CJK substring (not a whitespace-delimited word) must still match."""
    _write(vault, "concepts/memory.md", "# 记忆\n\n知识图谱是结构化长期记忆的关键技术。\n")
    _index(engine, vault)

    results = engine.search("结构化", vault, SCHEMA_DIRS)
    assert results
    assert "结构化" in results[0].snippet


def test_cjk_short_token_uses_like_fallback(engine, vault):
    """Tokens shorter than the trigram minimum fall back to LIKE matching."""
    _write(vault, "concepts/memory.md", "# 记忆\n\n知识图谱是结构化记忆的关键。\n")
    _index(engine, vault)

    if engine._trigram:
        # "图谱" is 2 chars < trigram minimum → served via LIKE fallback
        results = engine.search("图谱", vault, SCHEMA_DIRS)
        assert results
        assert results[0].path == "concepts/memory.md"


# ---------------------------------------------------------------------------
# Query sanitization
# ---------------------------------------------------------------------------


def test_query_with_fts5_special_characters(engine, vault):
    _write(
        vault,
        "entities/security.md",
        "# Security\n\nPrompt injection is an attack on LLM agents.\n",
    )
    _index(engine, vault)

    # Quotes, AND, parentheses — would all crash or mis-parse as raw FTS5 syntax
    matching_queries = [
        'what is "prompt injection" AND why?',
        "prompt (injection)",
        "injection OR NOT agent",
    ]
    for q in matching_queries:
        results = engine.search(q, vault, SCHEMA_DIRS)
        assert results, f"query should not crash and should match: {q!r}"
        assert results[0].path == "entities/security.md"

    # Tokens absent from the vault: must not crash, empty result is correct
    assert engine.search('"unclosed quote', vault, SCHEMA_DIRS) == []


def test_multiword_query_or_semantics(engine, vault):
    """Multi-word queries match documents containing ANY token (OR)."""
    _write(vault, "concepts/fruit.md", "# Fruit\n\nA banana is a berry.\n")
    _index(engine, vault)

    # "apple" appears nowhere; the query must still match via "banana"
    results = engine.search("apple banana", vault, SCHEMA_DIRS)
    assert results
    assert results[0].path == "concepts/fruit.md"


def test_no_usable_token_returns_empty(engine, vault):
    _write(vault, "concepts/x.md", "# X\n\ncontent here\n")
    _index(engine, vault)
    assert engine.search("?!@#$", vault, SCHEMA_DIRS) == []


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------


def test_snippet_includes_context_above_match():
    body = "\n".join(f"line-{i}" for i in range(10))
    body = body.replace("line-5", "line-5 needle here")
    snippet = _extract_snippet(body, "needle", context_lines=2)
    # match is on line index 5; window must include 2 lines above and below
    assert "line-3" in snippet
    assert "line-5 needle here" in snippet
    assert "line-7" in snippet


def test_snippet_finds_token_in_multiword_query():
    body = "intro\nThe banana ripened.\noutro"
    snippet = _extract_snippet(body, "apple banana", context_lines=1)
    assert "banana" in snippet


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------


def test_migrates_old_non_trigram_schema(engine, vault):
    """A pre-existing FTS5 table without trigram is rebuilt with trigram,
    and the next search re-indexes automatically."""
    _write(vault, "concepts/memory.md", "# 记忆\n\n知识图谱是结构化记忆的关键技术。\n")

    # Simulate a database created by an older version
    conn = sqlite3.connect(str(vault / ".llmwiki.sqlite"))
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(path, title, body)")
    conn.commit()
    conn.close()

    results = engine.search("知识图谱", vault, SCHEMA_DIRS)
    assert results, "after migration, CJK search must work"
    assert results[0].path == "concepts/memory.md"
    assert engine._trigram or not engine._fts5  # migrated to trigram (or plain)

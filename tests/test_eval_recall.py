"""Recall regression benchmark — a fixed vault with fixed queries.

This is a *guardrail*, not a precision report: it pins down end-to-end
retrieval behavior (keyword + graph + temporal + RRF fusion) so refactors
can't silently degrade recall. Each query asserts that the expected note
lands inside top_k — not an exact rank, which would be too brittle.

If you intentionally change retrieval behavior, update the expectations
here in the same commit and say why in the commit message.
"""

from datetime import datetime, timedelta

import pytest

from llmwiki.core.indexer import IndexRegistry
from llmwiki.core.retriever import Retriever

SCHEMA_DIRS = ["entities", "concepts", "chronicle/daily"]

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Fixed vault contents — do not edit casually; queries below depend on them.
VAULT_NOTES = {
    "entities/zorblax.md": (
        "# Zorblax\n\n"
        "The Zorblax protocol handles handshake design for distributed agents. "
        "See [[Knowledge Graph]] for the memory model.\n"
    ),
    "concepts/knowledge-graph.md": (
        "# Knowledge Graph\n\n"
        "A knowledge graph structures long-term memory with [[wikilinks]] "
        "between atomic notes.\n"
    ),
    "concepts/forgetting-curve.md": (
        "# Forgetting Curve\n\n"
        "Memory decays over time unless recalled; spaced repetition stretches "
        "the decay horizon. Related: [[Knowledge Graph]].\n"
    ),
    "concepts/long-term-memory.md": (
        "# 长期记忆\n\n通过知识图谱和遗忘曲线组织长期记忆，跨会话召回。\n"
    ),
    f"chronicle/daily/{TODAY}.md": (
        f"# Daily Chronicle: {TODAY}\n\n" "**User:** let's tune the zorblax handshake timeout\n"
    ),
    f"chronicle/daily/{YESTERDAY}.md": (
        f"# Daily Chronicle: {YESTERDAY}\n\n"
        "**User:** explained how the forgetting curve affects recall ranking\n"
    ),
}

# (query, expected vault-relative path). Each must land in top_k.
CASES = [
    ("zorblax protocol", "entities/zorblax.md"),
    ("knowledge graph", "concepts/knowledge-graph.md"),
    ("wikilinks between notes", "concepts/knowledge-graph.md"),
    ("handshake timeout", "entities/zorblax.md"),
    ("memory decay", "concepts/forgetting-curve.md"),
    ("长期记忆", "concepts/long-term-memory.md"),
    # Temporal: today's chronicle mention of the handshake tuning session.
    ("zorblax handshake tuning", f"chronicle/daily/{TODAY}.md"),
]

# Graph traversal: the seed (zorblax) links to the knowledge graph note,
# which does NOT contain the query token — only reachable via the edge.
GRAPH_CASES = [
    ("zorblax protocol", "concepts/knowledge-graph.md"),
]


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    for rel, text in VAULT_NOTES.items():
        p = v / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return v


@pytest.fixture
def retriever(vault):
    registry = IndexRegistry(vault, SCHEMA_DIRS, engine_names=["python"])
    registry.build(force=True)
    r = Retriever(registry, vault)
    yield r
    if r.graph is not None:
        r.graph.close()
    registry.close()


@pytest.mark.parametrize("query,expected", CASES)
def test_recall_benchmark(retriever, query, expected):
    results = retriever.retrieve(query, top_k=5, strategies=["keyword", "graph", "temporal"])
    paths = [r["path"] for r in results]
    assert expected in paths, f"{query!r} missed {expected}; got {paths}"


@pytest.mark.parametrize("query,expected", GRAPH_CASES)
def test_recall_via_graph_traversal(retriever, query, expected):
    results = retriever.retrieve(query, top_k=5, strategies=["keyword", "graph"])
    hit = next((r for r in results if r["path"] == expected), None)
    assert hit is not None, f"{query!r} did not reach {expected} via graph"
    assert "graph" in hit["via"]

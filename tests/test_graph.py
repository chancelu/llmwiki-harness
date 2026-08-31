"""Tests for LinkGraph — the persistent wikilink edge table."""

import time

import pytest

from llmwiki.core.graph import LinkGraph


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    for d in ["entities", "concepts", "chronicle/daily"]:
        (v / d).mkdir(parents=True)
    return v


@pytest.fixture
def graph(vault):
    g = LinkGraph(vault)
    yield g
    g.close()


def _write(vault, rel: str, text: str):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Build & basic queries
# ---------------------------------------------------------------------------


def test_rebuild_extracts_edges(graph, vault):
    _write(vault, "entities/a.md", "# A\n\nSee [[B]] and [[C|the alias]].\n")
    _write(vault, "concepts/b.md", "# B\n\nAbout B.\n")
    _write(vault, "concepts/c.md", "# C\n\nAbout C.\n")

    stats = graph.rebuild()
    assert stats["notes"] == 3

    assert sorted(graph.neighbors("entities/a.md")) == [
        "concepts/b.md",
        "concepts/c.md",
    ]
    assert graph.backlinks("concepts/b.md") == ["entities/a.md"]
    assert graph.backlinks("entities/a.md") == []


def test_alias_and_heading_syntax(graph, vault):
    _write(vault, "entities/a.md", "# A\n\n[[B|alias]] [[B#section]]\n")
    _write(vault, "concepts/b.md", "# B\n")
    graph.rebuild()
    assert graph.neighbors("entities/a.md") == ["concepts/b.md"]


def test_dead_links_recorded(graph, vault):
    _write(vault, "entities/a.md", "# A\n\nSee [[Nowhere Land]].\n")
    graph.rebuild()
    dead = graph.dead_links()
    assert dead == [("entities/a.md", "Nowhere Land")]
    assert graph.stats()["dead_links"] == 1


def test_self_links_skipped(graph, vault):
    _write(vault, "entities/a.md", "# A\n\nSee [[A]].\n")
    graph.rebuild()
    assert graph.neighbors("entities/a.md") == []


def test_orphans(graph, vault):
    _write(vault, "entities/a.md", "# A\n\nSee [[B]].\n")
    _write(vault, "concepts/b.md", "# B\n")
    _write(vault, "concepts/lonely.md", "# Lonely\n")
    _write(vault, "chronicle/daily/2026-01-01.md", "# Daily\n")  # unlinked by design

    graph.rebuild()
    compiled_orphans = graph.orphans(dirs=["entities", "concepts"])
    assert "concepts/lonely.md" in compiled_orphans
    assert "concepts/b.md" not in compiled_orphans
    assert "entities/a.md" in compiled_orphans  # nothing links to A


def test_resolve_normalization(graph, vault):
    _write(vault, "concepts/knowledge-graph.md", "# KG\n")
    graph.rebuild()
    assert graph.resolve("knowledge graph") == "concepts/knowledge-graph.md"
    assert graph.resolve("Knowledge Graph") == "concepts/knowledge-graph.md"
    assert graph.resolve("nonexistent") is None


# ---------------------------------------------------------------------------
# Neighborhood weights
# ---------------------------------------------------------------------------


def test_neighborhood_weights(graph, vault):
    _write(vault, "entities/seed.md", "# S\n\n[[Hop1]]\n")
    _write(vault, "concepts/hop1.md", "# H1\n\n[[Hop2]]\n")
    _write(vault, "concepts/hop2.md", "# H2\n")
    _write(vault, "concepts/ref.md", "# R\n\nreferencing [[Seed]]\n")
    graph.rebuild()

    hood = graph.neighborhood("entities/seed.md", hops=2)
    assert hood["concepts/hop1.md"] == 1.0   # forward hop-1
    assert hood["concepts/hop2.md"] == 0.5   # forward hop-2
    assert hood["concepts/ref.md"] == 0.8    # backlink
    assert "entities/seed.md" not in hood


# ---------------------------------------------------------------------------
# Incremental updates
# ---------------------------------------------------------------------------


def test_incremental_new_file(graph, vault):
    _write(vault, "entities/a.md", "# A\n\nno links\n")
    graph.rebuild()

    _write(vault, "concepts/b.md", "# B\n")
    _write(vault, "entities/a.md", "# A\n\nnow links to [[B]]\n")
    # ensure mtime actually changes on filesystems with coarse granularity
    time.sleep(0.01)
    import os
    os.utime(vault / "entities" / "a.md")

    assert graph.update_incremental() >= 1
    assert graph.neighbors("entities/a.md") == ["concepts/b.md"]
    assert graph.backlinks("concepts/b.md") == ["entities/a.md"]


def test_incremental_delete_marks_inbound_dead(graph, vault):
    _write(vault, "entities/a.md", "# A\n\n[[B]]\n")
    target = vault / "concepts" / "b.md"
    _write(vault, "concepts/b.md", "# B\n")
    graph.rebuild()

    target.unlink()
    graph.update_incremental()

    dead = graph.dead_links()
    assert ("entities/a.md", "concepts/b.md") in dead


def test_incremental_dead_link_revived(graph, vault):
    _write(vault, "entities/a.md", "# A\n\n[[Future Note]]\n")
    graph.rebuild()
    assert graph.dead_links() == [("entities/a.md", "Future Note")]

    _write(vault, "concepts/future-note.md", "# Future\n")
    graph.update_incremental()

    assert graph.dead_links() == []
    assert graph.neighbors("entities/a.md") == ["concepts/future-note.md"]


def test_update_incremental_noop(graph, vault):
    _write(vault, "entities/a.md", "# A\n")
    graph.rebuild()
    assert graph.update_incremental() == 0


# ---------------------------------------------------------------------------
# Hidden dirs excluded
# ---------------------------------------------------------------------------


def test_hidden_dirs_excluded(graph, vault):
    _write(vault, "entities/a.md", "# A\n")
    _write(vault, ".obsidian/plugins/x.md", "# plugin doc with [[A]]\n")
    graph.rebuild()
    assert graph.stats()["notes"] == 1

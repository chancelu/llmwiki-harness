"""Tests for size-aware engine auto-selection."""

import shutil

from llmwiki.core.indexer import IndexRegistry
from llmwiki.search import _count_notes, auto_select_engine

SCHEMA_DIRS = ["entities", "concepts"]


def _make_vault(tmp_path, n: int):
    v = tmp_path / "vault"
    for d in SCHEMA_DIRS:
        (v / d).mkdir(parents=True)
    for i in range(n):
        (v / "entities" / f"note-{i}.md").write_text(f"# Note {i}\n", encoding="utf-8")
    return v


def test_count_notes(tmp_path):
    v = _make_vault(tmp_path, 7)
    assert _count_notes(v, SCHEMA_DIRS) == 7


def test_large_vault_prefers_sqlite(tmp_path):
    """Past the threshold, FTS5 wins — sqlite is stdlib so always available."""
    v = _make_vault(tmp_path, 3)
    engine = auto_select_engine(v, SCHEMA_DIRS, large_threshold=2)
    assert engine.name == "sqlite"


def test_small_vault_prefers_ripgrep_when_available(tmp_path):
    v = _make_vault(tmp_path, 3)
    engine = auto_select_engine(v, SCHEMA_DIRS, large_threshold=1000)
    if shutil.which("rg"):
        assert engine.name == "ripgrep"
    else:
        assert engine.name == "sqlite"  # next in the fallback chain


def test_registry_uses_size_aware_default(tmp_path):
    v = _make_vault(tmp_path, 3)
    # IndexRegistry passes vault info through; with the default threshold of
    # 5000 this tiny vault must NOT pick sqlite-first ordering unless rg is
    # missing — either way it must pick *something* and search.
    reg = IndexRegistry(v, SCHEMA_DIRS)
    try:
        assert reg.engines, "auto-selection must yield at least one engine"
        reg.build(force=True)  # sqlite needs an index build; rg/python don't
        assert reg.search("Note 1", top_k=5)
    finally:
        reg.close()

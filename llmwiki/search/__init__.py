"""Search engines for LLMWiki."""

from pathlib import Path
from typing import List, Optional

from llmwiki.search.base import SearchEngine, SearchResult
from llmwiki.search.python_engine import PythonEngine
from llmwiki.search.ripgrep import RipgrepEngine
from llmwiki.search.sqlite_engine import SQLiteEngine

__all__ = [
    "SearchEngine",
    "SearchResult",
    "RipgrepEngine",
    "PythonEngine",
    "SQLiteEngine",
]

ENGINE_REGISTRY = {
    "ripgrep": RipgrepEngine,
    "python": PythonEngine,
    "sqlite": SQLiteEngine,
}

# Above this many notes, full-scan engines (ripgrep/python) fall behind the
# FTS5 index — benchmarks show sqlite ~400x faster at 10k notes, ~800x at
# 100k, and CJK queries degrade worst on full scans.
LARGE_VAULT_THRESHOLD = 5000


def get_engine(name: str) -> SearchEngine:
    """Get a search engine by name."""
    if name not in ENGINE_REGISTRY:
        raise ValueError(
            f"Unknown search engine: {name}. Available: {list(ENGINE_REGISTRY.keys())}"
        )
    return ENGINE_REGISTRY[name]()


def _count_notes(vault_path: Path, schema_dirs: List[str]) -> int:
    """Fast note count across the schema dirs (names only, no reads)."""
    n = 0
    for d in schema_dirs:
        p = Path(vault_path) / d
        if p.is_dir():
            n += sum(1 for _ in p.rglob("*.md"))
    return n


def auto_select_engine(
    vault_path: Optional[Path] = None,
    schema_dirs: Optional[List[str]] = None,
    large_threshold: int = LARGE_VAULT_THRESHOLD,
) -> SearchEngine:
    """Automatically select the best available search engine.

    Small vaults prefer ripgrep (no index to build). Once the vault grows
    past `large_threshold` notes, sqlite's FTS5 index wins by orders of
    magnitude, so the preference flips to sqlite first.
    """
    order = ("ripgrep", "sqlite", "python")
    if vault_path is not None and schema_dirs:
        try:
            if _count_notes(vault_path, schema_dirs) > large_threshold:
                order = ("sqlite", "ripgrep", "python")
        except OSError:
            pass
    for name in order:
        engine = ENGINE_REGISTRY[name]()
        if engine.is_available():
            return engine
    return PythonEngine()  # Guaranteed to work

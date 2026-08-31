"""Search engines for LLMWiki."""

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


def get_engine(name: str) -> SearchEngine:
    """Get a search engine by name."""
    if name not in ENGINE_REGISTRY:
        raise ValueError(
            f"Unknown search engine: {name}. Available: {list(ENGINE_REGISTRY.keys())}"
        )
    return ENGINE_REGISTRY[name]()


def auto_select_engine() -> SearchEngine:
    """Automatically select the best available search engine."""
    for name in ("ripgrep", "sqlite", "python"):
        engine = ENGINE_REGISTRY[name]()
        if engine.is_available():
            return engine
    return PythonEngine()  # Guaranteed to work

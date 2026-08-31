"""Pure-Python search engine — zero external dependencies, always works."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

from llmwiki.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)


class PythonEngine(SearchEngine):
    """Pure-Python keyword search engine.

    No external dependencies required. Slower than ripgrep for large vaults
    but guaranteed to work everywhere.
    """

    name = "python"

    def is_available(self) -> bool:
        return True  # Always available

    def index(self, vault_path: Path, schema_dirs: List[str]) -> None:
        """No explicit index needed — searches files on demand."""
        pass

    def search(
        self,
        query: str,
        vault_path: Path,
        schema_dirs: List[str],
        top_k: int = 10,
        context_lines: int = 3,
    ) -> List[SearchResult]:
        search_roots = _resolve_search_roots(vault_path, schema_dirs)
        if not search_roots:
            return []

        results: List[SearchResult] = []
        query_lower = query.lower()
        pattern = re.compile(re.escape(query), re.IGNORECASE)

        for root in search_roots:
            for md_file in root.rglob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue

                if query_lower not in text.lower():
                    continue

                # Extract snippets around matches
                snippets = []
                for m in pattern.finditer(text):
                    start = max(0, m.start() - 200)
                    end = min(len(text), m.end() + 200)
                    snippet = text[start:end].replace("\n", " ").strip()
                    snippets.append(snippet)
                    if len(snippets) >= 3:
                        break

                rel_path = md_file.relative_to(vault_path).as_posix()
                results.append(
                    SearchResult(
                        path=rel_path,
                        title=_extract_title(md_file),
                        snippet=" ... ".join(snippets) if snippets else "",
                        score=_score_result(rel_path, query, snippets),
                        engine="python",
                    )
                )

                if len(results) >= top_k * 2:
                    break

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def update(self, changed_files: List[Path]) -> None:
        pass


def _resolve_search_roots(vault_path: Path, schema_dirs: List[str]) -> List[Path]:
    roots: List[Path] = []
    for d in schema_dirs:
        p = vault_path / d
        if p.is_dir():
            roots.append(p)
    return roots


def _extract_title(md_path: Path) -> str:
    try:
        text = md_path.read_text(encoding="utf-8")[:2048]
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return md_path.stem.replace("-", " ").replace("_", " ")


def _score_result(path: str, query: str, snippets: List[str]) -> float:
    score = 0.0
    query_lower = query.lower()

    if query_lower in path.lower():
        score += 10.0

    if "entities/" in path:
        score += 5.0
    elif "concepts/" in path:
        score += 4.0
    elif "comparisons/" in path:
        score += 3.0
    elif "projects/" in path:
        score += 2.0

    for snippet in snippets:
        score += snippet.lower().count(query_lower) * 0.5

    return score

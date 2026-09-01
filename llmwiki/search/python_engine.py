"""Pure-Python search engine — zero external dependencies, always works."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

from llmwiki.search.base import SearchEngine, SearchResult, query_tokens

logger = logging.getLogger(__name__)


class PythonEngine(SearchEngine):
    """Pure-Python keyword search engine.

    No external dependencies required. Slower than ripgrep for large vaults
    but guaranteed to work everywhere.

    Matching is token-based (any token hits, ranked by coverage), not
    whole-query substring containment — natural-language queries almost
    never appear verbatim in a note.
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

        unique_tokens = list(dict.fromkeys(query_tokens(query)))
        if not unique_tokens:
            return []

        results: List[SearchResult] = []
        query_lower = query.lower()

        for root in search_roots:
            for md_file in root.rglob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue

                text_lower = text.lower()
                matched = [t for t in unique_tokens if t in text_lower]
                if not matched:
                    continue

                # Snippets around the first occurrence of up to 3 tokens
                snippets = []
                seen_pos = set()
                for tok in matched:
                    idx = text_lower.find(tok)
                    if idx in seen_pos:
                        continue
                    seen_pos.add(idx)
                    start = max(0, idx - 200)
                    end = min(len(text), idx + len(tok) + 200)
                    snippets.append(text[start:end].replace("\n", " ").strip())
                    if len(snippets) >= 3:
                        break

                rel_path = md_file.relative_to(vault_path).as_posix()
                results.append(
                    SearchResult(
                        path=rel_path,
                        title=_extract_title(md_file),
                        snippet=" ... ".join(snippets),
                        score=_score_result(
                            rel_path, query_lower, unique_tokens, matched, text_lower
                        ),
                        engine="python",
                    )
                )

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


def _score_result(
    path: str,
    query_lower: str,
    unique_tokens: List[str],
    matched: List[str],
    text_lower: str,
) -> float:
    """Coverage-first ranking: how much of the query does the note cover?"""
    score = 0.0

    # Token coverage dominates (0..10)
    score += len(matched) / len(unique_tokens) * 10.0

    # Exact whole-phrase match bonus
    if query_lower in text_lower:
        score += 5.0

    # Title/filename match
    path_lower = path.lower()
    if query_lower in path_lower:
        score += 10.0
    elif any(t in path_lower for t in matched):
        score += 3.0

    # Directory type boost
    if "entities/" in path:
        score += 5.0
    elif "concepts/" in path:
        score += 4.0
    elif "comparisons/" in path:
        score += 3.0
    elif "projects/" in path:
        score += 2.0

    # Raw frequency, capped so spammy notes can't dominate
    hits = sum(text_lower.count(t) for t in matched)
    score += min(hits, 20) * 0.5

    return score

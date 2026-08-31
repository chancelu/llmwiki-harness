"""Ripgrep-based search engine — fast, zero-dependency on Python packages."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import List

from llmwiki.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)


class RipgrepEngine(SearchEngine):
    """Search engine powered by ripgrep (rg).

    Requires `rg` to be installed and on PATH.
    Falls back gracefully if not available.
    """

    name = "ripgrep"

    def is_available(self) -> bool:
        return shutil.which("rg") is not None

    def index(self, vault_path: Path, schema_dirs: List[str]) -> None:
        """Ripgrep does not need an explicit index build."""
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

        cmd = [
            "rg",
            "--json",
            "--smart-case",
            "--context",
            str(context_lines),
            "--max-count",
            str(top_k * 3),  # overfetch for ranking
            "-e",
            query,
        ] + [str(r) for r in search_roots]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, encoding="utf-8")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("ripgrep search failed: %s", e)
            return []

        return _parse_ripgrep_output(proc.stdout, query, vault_path, top_k)

    def update(self, changed_files: List[Path]) -> None:
        """No-op: ripgrep searches files directly."""
        pass


def _resolve_search_roots(vault_path: Path, schema_dirs: List[str]) -> List[Path]:
    """Build list of directories to search."""
    roots: List[Path] = []
    for d in schema_dirs:
        p = vault_path / d
        if p.is_dir():
            roots.append(p)
    return roots


def _parse_ripgrep_output(
    stdout: str, query: str, vault_path: Path, top_k: int
) -> List[SearchResult]:
    """Parse ripgrep --json output into SearchResult objects."""
    results: List[SearchResult] = []
    current_file: str = ""
    current_snippets: List[str] = []

    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type")
        if msg_type == "begin":
            current_file = obj.get("data", {}).get("path", {}).get("text", "")
            current_snippets = []
        elif msg_type == "match":
            lines_data = obj.get("data", {}).get("lines", {})
            text = lines_data.get("text", "")
            if text:
                current_snippets.append(text.strip())
        elif msg_type == "end" and current_file:
            if current_snippets:
                rel = _make_relative(current_file, vault_path)
                results.append(
                    SearchResult(
                        path=rel,
                        title=_extract_title(Path(current_file)),
                        snippet="\n".join(current_snippets[:3]),
                        score=_score_result(rel, query, current_snippets),
                        engine="ripgrep",
                    )
                )
            current_file = ""

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def _make_relative(file_path: str, vault_path: Path) -> str:
    """Make path relative to vault root if possible."""
    try:
        return str(Path(file_path).relative_to(vault_path))
    except ValueError:
        return file_path


def _extract_title(md_path: Path) -> str:
    """Extract title from H1 or filename."""
    try:
        text = md_path.read_text(encoding="utf-8")[:2048]
        import re

        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return md_path.stem.replace("-", " ").replace("_", " ")


def _score_result(path: str, query: str, snippets: List[str]) -> float:
    """Rough relevance scoring. Higher = better."""
    score = 0.0
    query_lower = query.lower()

    # Title/filename match
    if query_lower in path.lower():
        score += 10.0

    # Directory type boost
    if "entities/" in path:
        score += 5.0
    elif "concepts/" in path:
        score += 4.0
    elif "comparisons/" in path:
        score += 3.0
    elif "projects/" in path:
        score += 2.0

    # Snippet match density
    for snippet in snippets:
        score += snippet.lower().count(query_lower) * 0.5

    return score

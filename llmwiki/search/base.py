"""Search engine base class and shared types."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")


def query_tokens(query: str) -> List[str]:
    """Split a natural-language query into matchable tokens.

    Whitespace/punctuation-separated words are used as-is. CJK runs longer
    than 2 characters are split into overlapping bigrams — CJK text has no
    word boundaries, and bigrams give reliable partial matching without a
    segmenter (e.g. "知识图谱怎么用" → 知识 / 识图 / 图谱 / 谱怎 / 怎么 / 么用).

    Shared by the search engines and the retriever's temporal strategy so
    matching semantics stay consistent across the whole recall path.
    """
    tokens: List[str] = []
    for tok in re.findall(r"\w+", query.lower()):
        if len(tok) > 2 and _CJK_RE.search(tok):
            tokens.extend(tok[i : i + 2] for i in range(len(tok) - 1))
        else:
            tokens.append(tok)
    return tokens


@dataclass
class SearchResult:
    """A single search result from any engine."""

    path: str  # Relative path from vault root
    title: str
    snippet: str
    score: float = 0.0
    engine: str = ""  # Which engine produced this result
    metadata: Optional[dict] = None


class SearchEngine(ABC):
    """Abstract base class for wiki search engines."""

    name: str = ""

    @abstractmethod
    def index(self, vault_path: Path, schema_dirs: List[str]) -> None:
        """Build or update the search index for the given vault."""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        vault_path: Path,
        schema_dirs: List[str],
        top_k: int = 10,
        context_lines: int = 3,
    ) -> List[SearchResult]:
        """Search the indexed vault and return ranked results."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine's dependencies are available."""
        ...

    def update(self, changed_files: List[Path]) -> None:
        """Incrementally update the index for changed files.

        Default implementation does nothing (engines that don't support
        incremental updates can override or ignore).
        """
        pass

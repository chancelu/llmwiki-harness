"""Retriever — multi-strategy knowledge recall from the wiki.

Supports:
  - Keyword search (via registered search engines)
  - Graph traversal (follow wikilinks from hit nodes)
  - Temporal search (recent chronicle entries)
  - Fusion: RRF (Reciprocal Rank Fusion)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from llmwiki.core.indexer import IndexRegistry

if TYPE_CHECKING:
    from llmwiki.core.graph import LinkGraph

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")


def _query_tokens(query: str) -> List[str]:
    """Split a natural-language query into matchable tokens.

    Whitespace/punctuation-separated words are used as-is. CJK runs longer
    than 2 characters are split into overlapping bigrams — CJK text has no
    word boundaries, and bigrams give reliable partial matching without a
    segmenter (e.g. "知识图谱怎么用" → 知识 / 识图 / 图谱 / 谱怎 / 怎么 / 么用).
    """
    tokens: List[str] = []
    for tok in re.findall(r"\w+", query.lower()):
        if len(tok) > 2 and _CJK_RE.search(tok):
            tokens.extend(tok[i : i + 2] for i in range(len(tok) - 1))
        else:
            tokens.append(tok)
    return tokens


def rrf_fusion(results_lists: List[List[Dict]], k: int = 60) -> List[Dict]:
    """Reciprocal Rank Fusion: combine multiple ranked lists into one.

    score = sum(1 / (k + rank)) for each list where the item appears.
    Higher score = better.
    """
    scores: Dict[str, float] = {}
    items: Dict[str, Dict] = {}

    for results in results_lists:
        for rank, item in enumerate(results, start=1):
            key = item["path"]
            items[key] = item
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    # Sort by fused score descending
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [{**items[key], "score": score, "fusion": "rrf"} for key, score in fused]


class Retriever:
    """Multi-strategy retriever for the wiki vault."""

    def __init__(
        self,
        registry: IndexRegistry,
        vault_path: Path,
        daily_dir: str = "chronicle/daily/",
        graph: Optional["LinkGraph"] = None,
    ):
        self.registry = registry
        self.vault_path = Path(vault_path)
        self._daily_dir = daily_dir
        self.graph = graph

    def _get_graph(self) -> "LinkGraph":
        """Lazily create the link graph if none was injected."""
        if self.graph is None:
            from llmwiki.core.graph import LinkGraph

            self.graph = LinkGraph(self.vault_path)
        return self.graph

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        strategies: Optional[List[str]] = None,
        fusion: str = "rrf",
        days_back: int = 7,
    ) -> List[Dict]:
        """Retrieve relevant knowledge chunks using multiple strategies.

        Args:
            query: The search query (user message or topic).
            top_k: Number of results to return.
            strategies: List of strategies to use. Defaults to ["keyword"].
            fusion: How to merge results from multiple strategies (rrf | concat).
            days_back: For temporal strategy, how many days of chronicle to include.

        Returns:
            List of result dicts with path, title, snippet, score.
        """
        if strategies is None:
            strategies = ["keyword"]

        results_by_strategy: List[List[Dict]] = []

        if "keyword" in strategies:
            try:
                keyword_results = self._keyword_search(query, top_k * 2)
                if keyword_results:
                    results_by_strategy.append(keyword_results)
            except Exception as e:
                logger.warning("Keyword search failed: %s", e)

        if "graph" in strategies:
            try:
                graph_results = self._graph_search(query, top_k)
                if graph_results:
                    results_by_strategy.append(graph_results)
            except Exception as e:
                logger.warning("Graph search failed: %s", e)

        if "temporal" in strategies:
            try:
                temporal_results = self._temporal_search(query, days_back, top_k)
                if temporal_results:
                    results_by_strategy.append(temporal_results)
            except Exception as e:
                logger.warning("Temporal search failed: %s", e)

        if not results_by_strategy:
            return []

        if len(results_by_strategy) == 1 or fusion == "concat":
            # Simple concatenation and dedup
            seen = set()
            merged = []
            for results in results_by_strategy:
                for r in results:
                    if r["path"] not in seen:
                        seen.add(r["path"])
                        merged.append(r)
            return merged[:top_k]

        # RRF fusion
        fused = rrf_fusion(results_by_strategy)
        return fused[:top_k]

    def _keyword_search(self, query: str, top_k: int) -> List[Dict]:
        """Standard keyword search via the index registry."""
        return self.registry.search(query, top_k=top_k)

    def _graph_search(self, query: str, top_k: int) -> List[Dict]:
        """Graph traversal over the persistent link edge table.

        Seeds come from keyword search; each seed's neighborhood is expanded
        with hop-1 forward links (weight 1.0), backlinks (0.8), and hop-2
        forward links (0.5). See llmwiki.core.graph.LinkGraph.
        """
        seeds = self.registry.search(query, top_k=top_k)
        if not seeds:
            return []

        graph = self._get_graph()
        graph.update_incremental()

        seed_paths = {s["path"] for s in seeds}
        weighted: Dict[str, float] = {}
        for seed in seeds:
            for path, weight in graph.neighborhood(seed["path"], hops=2).items():
                if path in seed_paths:
                    continue
                weighted[path] = max(weighted.get(path, 0.0), weight)

        graph_results = []
        for path, weight in sorted(weighted.items(), key=lambda kv: -kv[1]):
            full_path = self.vault_path / path
            if not full_path.exists():
                continue
            try:
                text = full_path.read_text(encoding="utf-8")
                title = self._extract_title(text, full_path)
                snippet = text[:500].replace("\n", " ").strip()
                graph_results.append(
                    {
                        "path": path,
                        "title": title,
                        "snippet": snippet,
                        "score": 3.0 * weight,
                        "engine": "graph",
                    }
                )
            except Exception:
                continue

        return graph_results[: top_k * 2]

    def _temporal_search(self, query: str, days_back: int, top_k: int) -> List[Dict]:
        """Search recent chronicle entries (daily notes).

        Token-based matching (with CJK bigram splitting) instead of
        whole-string containment — natural-language queries almost never
        appear verbatim in a note, which made the old check miss nearly
        everything. Results are ranked by token coverage, then recency.
        """
        daily_dir = self.vault_path / self._daily_dir
        if not daily_dir.is_dir():
            return []

        tokens = _query_tokens(query)
        if not tokens:
            return []

        cutoff = datetime.now() - timedelta(days=days_back)
        now = datetime.now()
        results = []

        for md_file in sorted(daily_dir.glob("*.md"), reverse=True):
            try:
                # Parse date from filename
                note_date = datetime.strptime(md_file.stem, "%Y-%m-%d")
            except ValueError:
                continue

            if note_date < cutoff:
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            text_lower = text.lower()
            matched = [t for t in set(tokens) if t in text_lower]
            if not matched:
                continue

            coverage = len(matched) / len(set(tokens))
            hits = sum(text_lower.count(t) for t in matched)
            days_ago = (now - note_date).days
            recency_score = max(0.5, 5.0 - days_ago * 0.5)
            # Relevance dominates; recency and raw frequency break ties.
            score = coverage * 10.0 + recency_score + min(hits, 20) * 0.1

            # Snippet around the first matched token
            idx = min(text_lower.find(t) for t in matched)
            start = max(0, idx - 200)
            end = min(len(text), idx + 300)
            snippet = text[start:end].replace("\n", " ").strip()

            results.append(
                {
                    "path": str(md_file.relative_to(self.vault_path)),
                    "title": f"Daily Chronicle: {md_file.stem}",
                    "snippet": snippet,
                    "score": score,
                    "engine": "temporal",
                }
            )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _extract_title(text: str, md_path: Path) -> str:
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
        return md_path.stem.replace("-", " ").replace("_", " ")

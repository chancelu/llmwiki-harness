"""Context Assembler — assembles retrieved knowledge into injectable context.

Handles token budget management, deduplication, and formatting.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles search results into a context block suitable for injection
    into an LLM system prompt or conversation.
    """

    def __init__(
        self,
        token_budget: int = 4000,
        format: str = "markdown",
        include_metadata: bool = True,
        deduplicate: bool = True,
        priority: str = "relevance",
    ):
        self.token_budget = token_budget
        self.format = format
        self.include_metadata = include_metadata
        self.deduplicate = deduplicate
        self.priority = priority

    def assemble(self, results: List[Dict]) -> str:
        """Assemble results into a context string within token budget.

        Args:
            results: List of result dicts from Retriever.

        Returns:
            Formatted context string ready for prompt injection.
        """
        if not results:
            return ""

        # Sort by priority strategy
        sorted_results = self._sort_results(results)

        # Deduplicate if enabled
        if self.deduplicate:
            sorted_results = self._deduplicate(sorted_results)

        # Build context block within token budget
        lines = []
        tokens_used = 0
        header_tokens = estimate_tokens(self._header())
        footer_tokens = estimate_tokens(self._footer())
        available = self.token_budget - header_tokens - footer_tokens

        for result in sorted_results:
            chunk = self._format_result(result)
            chunk_tokens = estimate_tokens(chunk)

            if tokens_used + chunk_tokens > available:
                # Try to truncate snippet to fit
                remaining = available - tokens_used
                if remaining > 100:
                    truncated = self._truncate_result(result, remaining)
                    if truncated:
                        lines.append(truncated)
                break

            lines.append(chunk)
            tokens_used += chunk_tokens

        if not lines:
            return ""

        parts = [self._header()]
        parts.extend(lines)
        parts.append(self._footer(tokens_used))
        return "\n".join(parts)

    def _sort_results(self, results: List[Dict]) -> List[Dict]:
        """Sort results according to the configured priority strategy."""
        if self.priority == "relevance":
            return sorted(results, key=lambda r: r.get("score", 0), reverse=True)
        elif self.priority == "recency":
            # Temporal results have implicit recency; for compiled notes,
            # use frontmatter date if available (not implemented here).
            return sorted(
                results,
                key=lambda r: (r.get("engine") == "temporal", r.get("score", 0)),
                reverse=True,
            )
        elif self.priority == "diversity":
            # Deduplicate by title similarity and interleave sources
            return self._diversify(results)
        elif self.priority == "structured":
            # Group by directory type
            order = {"entities": 0, "concepts": 1, "comparisons": 2, "projects": 3}
            return sorted(
                results,
                key=lambda r: (
                    order.get(r.get("path", "").split("/")[0], 99),
                    -r.get("score", 0),
                ),
            )
        return results

    def _deduplicate(self, results: List[Dict]) -> List[Dict]:
        """Remove duplicate results by path."""
        seen = set()
        unique = []
        for r in results:
            path = r.get("path", "")
            if path not in seen:
                seen.add(path)
                unique.append(r)
        return unique

    def _diversify(self, results: List[Dict]) -> List[Dict]:
        """Interleave results from different sources for diversity."""
        by_source: Dict[str, List[Dict]] = {}
        for r in results:
            engine = r.get("engine", "unknown")
            by_source.setdefault(engine, []).append(r)

        diversified = []
        idx = 0
        while True:
            added = False
            for source in sorted(by_source.keys()):
                if idx < len(by_source[source]):
                    diversified.append(by_source[source][idx])
                    added = True
            if not added:
                break
            idx += 1

        return diversified

    def _format_result(self, result: Dict) -> str:
        """Format a single result based on output format."""
        path = result.get("path", "")
        title = result.get("title", "Untitled")
        snippet = result.get("snippet", "").strip()

        if self.format == "markdown":
            lines = [f"### {title}"]
            if self.include_metadata:
                score = result.get("score", 0)
                engine = result.get("engine", "")
                meta = f"*{path}"
                if score:
                    meta += f" | score: {score:.1f}"
                if engine:
                    meta += f" | engine: {engine}"
                meta += "*"
                lines.append(meta)
            if snippet:
                lines.append(snippet)
            lines.append("")
            return "\n".join(lines)

        elif self.format == "xml":
            lines = [f'<note path="{path}" title="{title}">']
            if snippet:
                lines.append(f"  <snippet>{snippet}</snippet>")
            lines.append("</note>")
            return "\n".join(lines)

        elif self.format == "json":
            import json

            return json.dumps(result, ensure_ascii=False)

        # Default fallback
        return f"{title}: {snippet[:200]}"

    def _truncate_result(self, result: Dict, max_tokens: int) -> Optional[str]:
        """Try to fit a truncated version of a result within remaining tokens."""
        chars = max_tokens * 3  # rough char estimate
        title = result.get("title", "")
        snippet = result.get("snippet", "")[:chars]
        truncated = f"### {title}\n{snippet}...\n"
        if estimate_tokens(truncated) <= max_tokens:
            return truncated
        return None

    def _header(self) -> str:
        if self.format == "markdown":
            return "## Wiki Context\n"
        elif self.format == "xml":
            return "<wiki_context>"
        return ""

    def _footer(self, tokens_used: int = 0) -> str:
        if self.format == "markdown":
            return f"\n---\n*Retrieved from local wiki. ~{tokens_used} tokens used.*"
        elif self.format == "xml":
            return "</wiki_context>"
        return ""


def estimate_tokens(text: str) -> int:
    """Rough token estimation.

    Uses a simple heuristic: ~3 chars per token for mixed content.
    For more accurate counts, tiktoken can be used if available.
    """
    if not text:
        return 0

    # Try tiktoken for accuracy
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        pass

    # Fallback heuristic
    return max(1, len(text) // 3)


def available_token_budget(
    total_budget: int,
    system_prompt_tokens: int,
    conversation_tokens: int,
    safety_margin: int = 2000,
) -> int:
    """Calculate how many tokens are available for wiki context injection.

    Args:
        total_budget: Model's total context window size.
        system_prompt_tokens: Tokens used by the base system prompt.
        conversation_tokens: Tokens used by the conversation so far.
        safety_margin: Tokens to reserve for the assistant's response.

    Returns:
        Available token budget for wiki context.
    """
    available = total_budget - system_prompt_tokens - conversation_tokens - safety_margin
    return max(0, available)

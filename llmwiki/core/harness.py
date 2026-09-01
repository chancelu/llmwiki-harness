"""ContextMemoryHarness — main entry point for LLMWiki.

Orchestrates indexing, retrieval, assembly, and caching.
Agent adapters interact with this class.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from llmwiki.core.assembler import ContextAssembler
from llmwiki.core.cache import InMemoryCache
from llmwiki.core.config import load_config
from llmwiki.core.graph import LinkGraph
from llmwiki.core.indexer import IndexRegistry
from llmwiki.core.retriever import Retriever
from llmwiki.vault.capture import TurnCapture
from llmwiki.vault.curate import CurationEngine
from llmwiki.vault.schema import VaultSchema

logger = logging.getLogger(__name__)


def _package_version() -> str:
    """Read the installed package version, falling back for source checkouts."""
    try:
        from importlib.metadata import version

        return version("llmwiki-harness")
    except Exception:
        return "unknown"


class ContextMemoryHarness:
    """Main harness: connects the wiki (Disk) to the agent context (RAM).

    Typical usage:
        harness = ContextMemoryHarness("~/Documents/selfwiki")
        harness.index.build()

        # Before each turn:
        context = harness.retrieve_and_assemble("user query here", token_budget=2000)

        # After each turn:
        harness.capture_turn(user_msg, assistant_msg)

        # Periodically (e.g., daily cron):
        harness.curate()
    """

    def __init__(
        self,
        vault_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the harness.

        Args:
            vault_path: Path to the Markdown vault. If None, uses config default.
            config: Optional configuration dict. If None, loads from file/env.
        """
        self.config = config or load_config()
        if vault_path:
            self.config["vault"]["path"] = vault_path

        self.vault_path = Path(self.config["vault"]["path"]).expanduser()
        self.schema = VaultSchema(self.vault_path, self.config["vault"]["schema"])

        # Ensure vault structure exists (also writes SCHEMA.md on first run)
        self.schema.init_vault()

        # Core components
        schema_dirs = list(self.config["vault"]["schema"].values())
        engine_names = None
        if self.config["index"]["engine"] == "hybrid":
            engine_names = [e["type"] for e in self.config["index"].get("engines", [])]

        self.index = IndexRegistry(
            vault_path=self.vault_path,
            schema_dirs=schema_dirs,
            engine_names=engine_names,
        )

        self.graph = LinkGraph(self.vault_path)

        self.retriever = Retriever(
            self.index,
            self.vault_path,
            daily_dir=self.config["vault"]["schema"].get("daily", "chronicle/daily/"),
            graph=self.graph,
            strength_weight=self.config["retrieve"].get("strength_weight", 0.5),
        )
        self.assembler = ContextAssembler(
            token_budget=self.config["context"]["token_budget"],
            format=self.config["context"]["format"],
            include_metadata=self.config["context"]["include_metadata"],
            deduplicate=self.config["context"]["deduplicate"],
            priority=self.config["context"]["priority"],
        )

        # L1 Cache
        cache_cfg = self.config.get("cache", {})
        self.cache = (
            InMemoryCache(
                maxsize=cache_cfg.get("maxsize", 100),
                ttl=cache_cfg.get("ttl", 300),
            )
            if cache_cfg.get("enabled", True)
            else None
        )

        # Vault operations
        self.capture_engine = TurnCapture(self.vault_path, self.config["vault"]["schema"])
        self.curation_engine = CurationEngine(self.vault_path, self.config)

    # ------------------------------------------------------------------
    # High-level API
    # ------------------------------------------------------------------

    def retrieve_and_assemble(
        self,
        query: str,
        token_budget: Optional[int] = None,
        top_k: Optional[int] = None,
        strategies: Optional[List[str]] = None,
    ) -> str:
        """Retrieve knowledge from the wiki and assemble it into context.

        This is the main API for injecting wiki knowledge into agent prompts.

        Args:
            query: The search query (typically the user's message).
            token_budget: Max tokens for the context block. Defaults to config.
            top_k: Number of results to retrieve. Defaults to config.
            strategies: Retrieval strategies. Defaults to config.

        Returns:
            Formatted context string ready for prompt injection.
            Empty string if no relevant knowledge found.
        """
        # Check cache first (L1 RAM hit)
        if self.cache:
            cached = self.cache.get(query)
            if cached is not None:
                logger.debug("Cache hit for query: %s", query[:50])
                return cached

        # Ensure index is up to date
        if self.config["index"].get("incremental", True):
            self.index.update_incremental()
            self.graph.update_incremental()

        # Retrieve
        budget = token_budget or self.config["context"]["token_budget"]
        k = top_k or self.config["retrieve"]["default_top_k"]
        strat = strategies or self.config["retrieve"].get("strategies", ["keyword"])

        results = self.retriever.retrieve(
            query=query,
            top_k=k,
            strategies=strat,
            fusion=self.config["retrieve"].get("fusion", "rrf"),
        )

        if not results:
            return ""

        # Memory-strength bookkeeping: these notes were actually recalled
        # into context, so their forgetting curve restarts (see LinkGraph).
        try:
            self.graph.record_recall([r["path"] for r in results])
        except Exception as e:
            logger.debug("record_recall failed (non-fatal): %s", e)

        # Assemble with token budget
        assembler = ContextAssembler(
            token_budget=budget,
            format=self.assembler.format,
            include_metadata=self.assembler.include_metadata,
            deduplicate=self.assembler.deduplicate,
            priority=self.assembler.priority,
        )
        context = assembler.assemble(results)

        # Cache the result
        if self.cache and context:
            self.cache.set(query, context)

        return context

    def retrieve(self, query: str, **kwargs) -> List[Dict]:
        """Raw retrieve API — returns result dicts without assembly.

        Useful when the agent wants to process results itself.
        """
        if self.config["index"].get("incremental", True):
            self.index.update_incremental()
            self.graph.update_incremental()

        top_k = kwargs.get("top_k", self.config["retrieve"]["default_top_k"])
        strategies = kwargs.get(
            "strategies", self.config["retrieve"].get("strategies", ["keyword"])
        )

        results = self.retriever.retrieve(
            query=query,
            top_k=top_k,
            strategies=strategies,
            fusion=self.config["retrieve"].get("fusion", "rrf"),
        )

        if results:
            try:
                self.graph.record_recall([r["path"] for r in results])
            except Exception as e:
                logger.debug("record_recall failed (non-fatal): %s", e)

        return results

    # ------------------------------------------------------------------
    # Vault operations
    # ------------------------------------------------------------------

    def capture_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        context: str = "primary",
        session_id: str = "",
    ) -> None:
        """Capture a conversation turn to the chronicle.

        Args:
            user_content: User's message.
            assistant_content: Assistant's response.
            context: Agent context. Non-primary contexts are skipped.
            session_id: Optional session identifier.
        """
        if context != "primary":
            return  # Skip non-primary contexts
        self.capture_engine.append(user_content, assistant_content, session_id=session_id)

    def curate(
        self,
        llm_generate: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run the curation pipeline: chronicle → compiled wiki.

        Args:
            llm_generate: Optional LLM callback for AI-driven extraction.

        Returns:
            Curation statistics dict.
        """
        return self.curation_engine.run(llm_generate=llm_generate)

    def search_wiki(
        self,
        query: str,
        top_k: int = 10,
        engine_name: Optional[str] = None,
    ) -> List[Dict]:
        """Direct search API — bypass retriever strategies, use raw index."""
        return self.index.search(query, engine_name=engine_name, top_k=top_k)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def build_index(self, force: bool = False) -> None:
        """Build or rebuild the search index and the link graph."""
        self.index.build(force=force)
        if force:
            self.graph.rebuild()
        else:
            self.graph.update_incremental()

    def clear_cache(self) -> None:
        """Clear the in-memory cache."""
        if self.cache:
            self.cache.clear()

    def close(self) -> None:
        """Release open resources (SQLite connections for graph and index).

        On Windows, an open SQLite connection locks the database file, so
        call this when the harness is no longer needed (tests, short-lived
        scripts). The harness can also be used as a context manager:

            with ContextMemoryHarness("~/vault") as h:
                ...
        """
        self.graph.close()
        self.index.close()

    def __enter__(self) -> "ContextMemoryHarness":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def stats(self) -> Dict[str, Any]:
        """Return harness statistics."""
        result = {
            "vault_path": str(self.vault_path),
            "version": _package_version(),
            "cache": self.cache.stats() if self.cache else None,
            "index_engines": list(self.index.engines.keys()),
            "graph": self.graph.stats(),
        }

        # Vault stats
        compiled_dirs = ["entities", "concepts", "comparisons", "projects", "queries"]
        result["vault"] = {"compiled": {}, "daily": 0, "raw": 0}
        for d in compiled_dirs:
            p = self.vault_path / d
            if p.is_dir():
                result["vault"]["compiled"][d] = len(list(p.rglob("*.md")))

        daily_dir = self.vault_path / "chronicle" / "daily"
        if daily_dir.is_dir():
            result["vault"]["daily"] = len(list(daily_dir.glob("*.md")))

        raw_dir = self.vault_path / "raw"
        if raw_dir.is_dir():
            result["vault"]["raw"] = len(list(raw_dir.glob("*.md")))

        return result

    def system_prompt_block(self) -> str:
        """Return a system prompt block describing wiki access to the agent."""
        return (
            f"You have access to a local Markdown wiki at {self.vault_path}.\n"
            "Use [[wikilinks]] to reference related concepts. "
            "When you learn something new, create atomic notes in the compiled layer.\n"
            "Use the wiki for long-term memory retrieval across sessions."
        )

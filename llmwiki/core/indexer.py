"""Index registry — manages search indices and incremental updates."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from llmwiki.search import SearchEngine, auto_select_engine, get_engine

logger = logging.getLogger(__name__)


class IndexRegistry:
    """Manages one or more search indices for a vault.

    Supports multiple engines simultaneously (e.g., ripgrep for speed + sqlite
    for structured queries). Tracks file modification times for incremental
    updates.
    """

    def __init__(
        self,
        vault_path: Path,
        schema_dirs: List[str],
        engine_names: Optional[List[str]] = None,
    ):
        self.vault_path = Path(vault_path)
        self.schema_dirs = schema_dirs
        self.engines: Dict[str, SearchEngine] = {}

        if engine_names:
            for name in engine_names:
                try:
                    engine = get_engine(name)
                    if engine.is_available():
                        self.engines[name] = engine
                    else:
                        logger.warning("Engine %s is not available, skipping", name)
                except ValueError as e:
                    logger.warning(str(e))
        else:
            # Default: best single engine
            engine = auto_select_engine()
            self.engines[engine.name] = engine

        self._state_path = self.vault_path / ".llmwiki" / "index_state.json"
        self._index_state: Dict[str, float] = {}

    def build(self, force: bool = False) -> None:
        """Build or rebuild all registered indices.

        Args:
            force: If True, rebuild even if index is up to date.
        """
        if not force and self._is_up_to_date():
            logger.info("Index is up to date, skipping build")
            return

        for name, engine in self.engines.items():
            logger.info("Building index with engine: %s", name)
            engine.index(self.vault_path, self.schema_dirs)

        self._save_index_state()

    def update_incremental(self) -> None:
        """Incrementally update indices based on file modification times."""
        changed = self._detect_changes()
        if not changed:
            logger.debug("No file changes detected")
            return

        logger.info("Detected %d changed files, updating indices...", len(changed))
        for engine in self.engines.values():
            engine.update(changed)

        self._save_index_state()

    def search(
        self,
        query: str,
        engine_name: Optional[str] = None,
        top_k: int = 10,
        context_lines: int = 3,
    ) -> List[dict]:
        """Search using the specified engine or all engines.

        Returns unified SearchResult objects.
        """
        if engine_name:
            if engine_name not in self.engines:
                raise ValueError(f"Engine not registered: {engine_name}")
            engine = self.engines[engine_name]
            results = engine.search(query, self.vault_path, self.schema_dirs, top_k, context_lines)
        else:
            # Search with all engines and merge
            all_results = []
            for engine in self.engines.values():
                try:
                    results = engine.search(
                        query, self.vault_path, self.schema_dirs, top_k, context_lines
                    )
                    all_results.extend(results)
                except Exception as e:
                    logger.warning("Engine %s search failed: %s", engine.name, e)
            # Deduplicate by path
            seen = set()
            results = []
            for r in all_results:
                if r.path not in seen:
                    seen.add(r.path)
                    results.append(r)

        # Convert to dict for compatibility
        return [
            {
                "path": r.path,
                "title": r.title,
                "snippet": r.snippet,
                "score": r.score,
                "engine": r.engine,
            }
            for r in results
        ]

    def close(self) -> None:
        """Release resources held by the registered engines.

        Calls ``close()`` on every engine that provides it (e.g. the SQLite
        engine, whose open connection locks its database file on Windows).
        """
        for engine in self.engines.values():
            close = getattr(engine, "close", None)
            if callable(close):
                close()

    def _is_up_to_date(self) -> bool:
        """Check if the index is up to date with the vault files."""
        self._load_index_state()
        if not self._index_state:
            return False

        # Check if any file is newer than the last index time
        last_index = max(self._index_state.values()) if self._index_state else 0
        for d in self.schema_dirs:
            root = self.vault_path / d
            if not root.is_dir():
                continue
            for md_file in root.rglob("*.md"):
                try:
                    mtime = md_file.stat().st_mtime
                    if mtime > last_index:
                        return False
                except OSError:
                    continue
        return True

    def _detect_changes(self) -> List[Path]:
        """Detect files that have changed since last index."""
        self._load_index_state()
        changed: List[Path] = []

        for d in self.schema_dirs:
            root = self.vault_path / d
            if not root.is_dir():
                continue
            for md_file in root.rglob("*.md"):
                try:
                    mtime = md_file.stat().st_mtime
                    rel = md_file.relative_to(self.vault_path).as_posix()
                    last = self._index_state.get(rel, 0)
                    if mtime > last:
                        changed.append(md_file)
                        self._index_state[rel] = mtime
                except OSError:
                    continue

        return changed

    def _load_index_state(self) -> None:
        """Load the index state from disk."""
        if self._state_path.exists():
            try:
                self._index_state = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._index_state = {}
        else:
            self._index_state = {}

    def _save_index_state(self) -> None:
        """Save the index state to disk."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        # Update all known file mtimes
        for d in self.schema_dirs:
            root = self.vault_path / d
            if not root.is_dir():
                continue
            for md_file in root.rglob("*.md"):
                try:
                    rel = md_file.relative_to(self.vault_path).as_posix()
                    self._index_state[rel] = md_file.stat().st_mtime
                except OSError:
                    continue

        self._state_path.write_text(json.dumps(self._index_state, indent=2), encoding="utf-8")

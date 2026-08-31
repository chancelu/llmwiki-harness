"""SQLite FTS5 search engine — structured queries with incremental updates.

Query handling notes:
  - User queries are sanitized before being passed to FTS5 `MATCH`: the raw
    string is split into word tokens, each token is double-quoted, and tokens
    are OR-joined. This prevents FTS5 syntax errors from characters like
    quotes, hyphens, AND/OR/NOT, or parentheses in natural-language input.
  - The index prefers the `trigram` tokenizer (SQLite >= 3.34), which gives
    substring matching and proper CJK (Chinese/Japanese/Korean) support —
    the default `unicode61` tokenizer treats CJK text as one long token and
    makes keyword search useless for CJK vaults.
  - Fallback chain: trigram FTS5 → unicode61 FTS5 → plain table + LIKE.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import List, Optional

from llmwiki.search.base import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\w+")

# Minimum token length the trigram tokenizer can match (shorter tokens
# are served by the LIKE fallback instead).
_TRIGRAM_MIN = 3


class SQLiteEngine(SearchEngine):
    """Search engine powered by SQLite FTS5.

    Provides substring/CJK matching (via the trigram tokenizer), structured
    queries, and fast incremental updates. The index is stored as a
    `.llmwiki.sqlite` file inside the vault root.
    """

    name = "sqlite"

    def __init__(self, db_name: str = ".llmwiki.sqlite"):
        self.db_name = db_name
        self._conn: sqlite3.Connection | None = None
        self._fts5 = False
        self._trigram = False
        self._needs_reindex = False

    def is_available(self) -> bool:
        """SQLite is built into Python since 2.5."""
        return True

    def _db_path(self, vault_path: Path) -> Path:
        return vault_path / self.db_name

    def _connect(self, vault_path: Path) -> sqlite3.Connection:
        if self._conn is None:
            db_path = self._db_path(vault_path)
            self._conn = sqlite3.connect(str(db_path))
            self._conn.row_factory = sqlite3.Row
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._conn
        if conn is None:
            return

        # Inspect existing table — migrate old non-trigram FTS5 schemas.
        existing = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'docs' AND type = 'table'"
        ).fetchone()
        if existing:
            sql = (existing[0] or "").lower()
            if "fts5" in sql and "trigram" not in sql:
                logger.info("Migrating docs table to trigram tokenizer (CJK support)")
                conn.execute("DROP TABLE docs")
                self._needs_reindex = True
                existing = None

        if not existing:
            self._create_docs_table(conn)
        else:
            sql = (existing[0] or "").lower()
            self._fts5 = "fts5" in sql
            self._trigram = "trigram" in sql

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS index_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.commit()

    def _create_docs_table(self, conn: sqlite3.Connection) -> None:
        """Create the docs table, degrading gracefully by capability."""
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE docs USING fts5("
                "path, title, body, tokenize='trigram')"
            )
            self._fts5 = True
            self._trigram = True
            return
        except sqlite3.OperationalError as e:
            logger.debug("trigram tokenizer unavailable: %s", e)

        try:
            conn.execute("CREATE VIRTUAL TABLE docs USING fts5(path, title, body)")
            self._fts5 = True
            self._trigram = False
            return
        except sqlite3.OperationalError as e:
            logger.debug("FTS5 unavailable: %s", e)

        logger.warning("SQLite FTS5 not available, falling back to plain tables")
        conn.execute(
            "CREATE TABLE docs (path TEXT PRIMARY KEY, title TEXT, body TEXT)"
        )
        self._fts5 = False
        self._trigram = False

    def _build_fts_query(self, query: str) -> Optional[str]:
        """Sanitize a raw user query into a safe FTS5 MATCH expression.

        Splits into word tokens, double-quotes each (neutralizing FTS5
        operators and special characters), and OR-joins them. Returns None
        when no usable token remains (caller should use LIKE instead).
        """
        tokens = _TOKEN_RE.findall(query)
        if self._trigram:
            tokens = [t for t in tokens if len(t) >= _TRIGRAM_MIN]
        if not tokens:
            return None
        return " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)

    def index(self, vault_path: Path, schema_dirs: List[str]) -> None:
        """Full rebuild of the SQLite index."""
        conn = self._connect(vault_path)

        # Clear existing
        conn.execute("DELETE FROM docs")

        # Index all markdown files
        count = 0
        for d in schema_dirs:
            root = vault_path / d
            if not root.is_dir():
                continue
            for md_file in root.rglob("*.md"):
                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue

                rel_path = str(md_file.relative_to(vault_path))
                title = _extract_title(text, md_file)
                body = _strip_frontmatter(text)

                conn.execute(
                    "INSERT OR REPLACE INTO docs (path, title, body) VALUES (?, ?, ?)",
                    (rel_path, title, body),
                )
                count += 1

        conn.execute(
            "INSERT OR REPLACE INTO index_state (key, value) VALUES (?, ?)",
            ("last_full_index", str(Path(__file__).stat().st_mtime)),
        )
        conn.commit()
        self._needs_reindex = False
        logger.info("SQLite index rebuilt: %d documents", count)

    def update(self, changed_files: List[Path]) -> None:
        """Incrementally update index for changed files."""
        if not self._conn or not changed_files:
            return

        for md_file in changed_files:
            if not md_file.suffix.lower() == ".md":
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                # Need vault_path to compute relative path — skip if can't determine
                vault_path = _infer_vault_path(md_file)
                if vault_path is None:
                    continue
                rel_path = str(md_file.relative_to(vault_path))
                title = _extract_title(text, md_file)
                body = _strip_frontmatter(text)

                self._conn.execute(
                    "INSERT OR REPLACE INTO docs (path, title, body) VALUES (?, ?, ?)",
                    (rel_path, title, body),
                )
            except Exception as e:
                logger.warning("Failed to index %s: %s", md_file, e)

        self._conn.commit()

    def search(
        self,
        query: str,
        vault_path: Path,
        schema_dirs: List[str],
        top_k: int = 10,
        context_lines: int = 3,
    ) -> List[SearchResult]:
        conn = self._connect(vault_path)

        if self._needs_reindex:
            logger.info("Index schema migrated, rebuilding before search")
            self.index(vault_path, schema_dirs)

        rows = None
        fts_query = self._build_fts_query(query) if self._fts5 else None
        if fts_query:
            try:
                rows = conn.execute(
                    """
                    SELECT path, title, body, rank
                    FROM docs
                    WHERE docs MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, top_k * 2),
                ).fetchall()
            except sqlite3.OperationalError as e:
                logger.warning("FTS5 query failed, using LIKE fallback: %s", e)
                rows = None

        if rows is None:
            rows = self._like_search(conn, query, top_k * 2)

        results = []
        for row in rows:
            body = row["body"]
            snippet = _extract_snippet(body, query, context_lines)
            score = 10.0 + (1.0 / (abs(row["rank"]) + 1.0)) if row["rank"] else 5.0

            results.append(
                SearchResult(
                    path=row["path"],
                    title=row["title"],
                    snippet=snippet,
                    score=score,
                    engine="sqlite",
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _like_search(conn: sqlite3.Connection, query: str, limit: int):
        """LIKE fallback — matches any token, not just the whole raw query."""
        tokens = _TOKEN_RE.findall(query)
        if not tokens:
            return []
        where = " OR ".join("body LIKE ? OR title LIKE ?" for _ in tokens)
        params = [f"%{t}%" for t in tokens for _ in range(2)]
        return conn.execute(
            f"SELECT path, title, body, 0 as rank FROM docs WHERE {where} LIMIT ?",
            (*params, limit),
        ).fetchall()


def _extract_title(text: str, md_path: Path) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return md_path.stem.replace("-", " ").replace("_", " ")


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown text."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def _extract_snippet(body: str, query: str, context_lines: int) -> str:
    """Extract a snippet around the first matching query token.

    Searches for individual tokens (not just the whole raw query), so
    multi-word queries still produce a useful snippet.
    """
    tokens = _TOKEN_RE.findall(query)
    idx = -1
    for t in tokens or [query]:
        idx = body.lower().find(t.lower())
        if idx != -1:
            break
    if idx == -1:
        return body[:300]

    all_lines = body.split("\n")
    match_line = len(body[:idx].split("\n")) - 1  # 0-based line of the match
    start_line = max(0, match_line - context_lines)
    end_line = min(match_line + context_lines + 1, len(all_lines))

    snippet_lines = all_lines[start_line:end_line]
    return "\n".join(snippet_lines).strip()[:500]


def _infer_vault_path(md_file: Path) -> Path | None:
    """Try to infer the vault root from a markdown file path."""
    # Walk up looking for entities/ or chronicle/ or SCHEMA.md
    for parent in md_file.parents:
        if any((parent / d).is_dir() for d in ["entities", "concepts", "chronicle"]):
            return parent
    return None

"""Vault schema — directory structure and initialization."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

DEFAULT_SCHEMA = {
    "raw": "raw/",
    "daily": "chronicle/daily/",
    "entities": "entities/",
    "concepts": "concepts/",
    "comparisons": "comparisons/",
    "projects": "projects/",
    "queries": "queries/",
}

SCHEMA_MD_TEMPLATE = """# Vault Schema

This vault follows the Karpathy LLM Wiki pattern (3-layer architecture).

## Layer 1: Raw
`raw/` — Session dumps, temporary captures, pre-compression snapshots.
Disposable. Regenerated on demand.

## Layer 2: Chronicle
`chronicle/daily/` — Daily timeline notes, append-only.
Human-readable conversation log. Auto-captured by the agent.

## Layer 3: Compiled
- `entities/` — People, companies, tools, concrete things
- `concepts/` — Ideas, methods, patterns, decisions
- `comparisons/` — A vs B analyses, trade-off tables
- `projects/` — Active and completed projects
- `queries/` — Standing questions, research threads

Each compiled note should be AI-First: self-contained, frontmatter-rich,
with `## For future assistant` preamble and cross-references via `[[wikilinks]]`.
"""


class VaultSchema:
    """Manages the vault directory structure."""

    def __init__(self, vault_path: Path, schema: Optional[Dict[str, str]] = None):
        self.vault_path = Path(vault_path)
        self.schema = {**DEFAULT_SCHEMA, **(schema or {})}

    def ensure_dirs(self) -> None:
        """Create all vault directories if they don't exist."""
        for dir_path in self.schema.values():
            (self.vault_path / dir_path).mkdir(parents=True, exist_ok=True)

        # Also ensure .llmwiki metadata dir exists
        (self.vault_path / ".llmwiki").mkdir(exist_ok=True)

    def get_path(self, key: str) -> Path:
        """Get the full path for a schema key."""
        return self.vault_path / self.schema.get(key, key)

    def init_vault(self) -> None:
        """Initialize a new vault with schema directories and SCHEMA.md."""
        self.ensure_dirs()

        schema_md = self.vault_path / "SCHEMA.md"
        if not schema_md.exists():
            schema_md.write_text(SCHEMA_MD_TEMPLATE, encoding="utf-8")

    def validate(self) -> list:
        """Validate vault structure. Returns list of issues."""
        issues = []
        for key, dir_path in self.schema.items():
            full = self.vault_path / dir_path
            if not full.is_dir():
                issues.append(f"Missing directory: {key} -> {dir_path}")
        return issues

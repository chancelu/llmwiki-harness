"""Curation engine: chronicle/daily/ → compiled wiki (Layer 2 → Layer 3).

Supports two extraction modes:
  1. LLM-driven (recommended): Analyzes daily notes and extracts structured
     entities, concepts, decisions, projects using a text-generation callback.
  2. Regex fallback: Matches explicit markers like `### Entity: Name`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from llmwiki.vault.writer import atomic_write_text

logger = logging.getLogger(__name__)

_CURATION_PROMPT = """You are a knowledge curation assistant. Analyze the following daily note and extract structured knowledge items.

Rules:
- Extract ONLY high-signal items (facts, concepts, decisions, entities, projects). Skip trivial chat.
- Each item must have: type, name, content (1-3 sentences), tags (optional).
- Supported types: entity, concept, comparison, project, decision, finding.
- Output as a JSON array. No markdown, no explanations.

Example output:
[
  {"type": "entity", "name": "Bitcoin", "content": "A decentralized digital currency using proof-of-work consensus.", "tags": ["cryptocurrency", "finance"]},
  {"type": "concept", "name": "Zettelkasten", "content": "A note-taking method using atomic notes with unique IDs and cross-references.", "tags": ["knowledge-management"]}
]

Daily note:
---
{note_text}
---

JSON output:"""


class CurationEngine:
    """Runs the curation pipeline: daily notes → compiled atomic notes."""

    def __init__(self, vault_path: Path, config: Dict[str, Any]):
        self.vault_path = Path(vault_path)
        self.config = config
        schema = config.get("vault", {}).get("schema", {})
        self.daily_dir = self.vault_path / schema.get("daily", "chronicle/daily/")
        self.compiled_dirs = {
            "entities": self.vault_path / schema.get("entities", "entities/"),
            "concepts": self.vault_path / schema.get("concepts", "concepts/"),
            "comparisons": self.vault_path / schema.get("comparisons", "comparisons/"),
            "projects": self.vault_path / schema.get("projects", "projects/"),
        }
        self.archive_after_days = config.get("curate", {}).get("archive_after_days", 30)
        self.llm_driven = config.get("curate", {}).get("llm_driven", True)
        # Notes shorter than this are skipped as trivial. Kept low on purpose:
        # a single captured turn is often ~150 chars and still worth distilling.
        self.min_note_chars = config.get("curate", {}).get("min_note_chars", 80)

    def run(self, llm_generate: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
        """Run the full curation pipeline.

        Args:
            llm_generate: Optional callback(text) -> response_text.

        Returns:
            Summary dict with processed, created, updated, archived counts.
        """
        for d in self.compiled_dirs.values():
            d.mkdir(parents=True, exist_ok=True)

        daily_notes = self._list_daily_notes()
        if not daily_notes:
            return {"status": "no_notes", "processed": 0}

        stats = {
            "status": "ok",
            "processed": 0,
            "created": 0,
            "updated": 0,
            "archived": 0,
            "llm_mode": bool(llm_generate) and self.llm_driven,
        }

        for note_path in daily_notes:
            try:
                text = note_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read %s: %s", note_path, e)
                continue

            if len(text.strip()) < self.min_note_chars:
                logger.debug("Skipping trivial note: %s", note_path.name)
                continue

            items = self._extract_items(text, llm_generate)
            for item in items:
                self._write_compiled_note(item)
                stats["created"] += 1

            stats["processed"] += 1

        # Archive old notes
        stats["archived"] = self._archive_old_notes()

        return stats

    def _list_daily_notes(self) -> List[Path]:
        """List unarchived daily notes, sorted by date (newest first)."""
        if not self.daily_dir.is_dir():
            return []

        notes = []
        for f in self.daily_dir.glob("*.md"):
            if f.name.startswith(".") or f.name.startswith("_"):
                continue
            try:
                rel = f.relative_to(self.daily_dir)
                if rel.parts and rel.parts[0] == "archive":
                    continue
            except ValueError:
                pass
            notes.append(f)

        notes.sort(key=lambda p: p.name, reverse=True)
        return notes

    def _extract_items(
        self, text: str, llm_generate: Optional[Callable[[str], str]] = None
    ) -> List[Dict]:
        """Extract structured items from a daily note."""
        if self.llm_driven and llm_generate:
            items = self._extract_with_llm(text, llm_generate)
            if items:
                return items
            logger.debug("LLM extraction returned empty, falling back to regex")

        return self._extract_with_regex(text)

    def _extract_with_llm(self, text: str, llm_generate: Callable[[str], str]) -> List[Dict]:
        """Use LLM to extract structured items."""
        truncated = text[:6000] if len(text) > 6000 else text
        prompt = _CURATION_PROMPT.replace("{note_text}", truncated)

        try:
            response = llm_generate(prompt)
        except Exception as e:
            logger.warning("LLM extraction failed: %s", e)
            return []

        items = self._parse_json_from_response(response)
        return self._validate_items(items)

    def _parse_json_from_response(self, response: str) -> List[Dict]:
        """Extract JSON array from LLM response."""
        response = response.strip()

        # Try direct parse
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "items" in data:
                return data["items"]
        except json.JSONDecodeError:
            pass

        # Try markdown code block
        code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if code_block:
            try:
                data = json.loads(code_block.group(1).strip())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # Try first [ ... ] array
        array_match = re.search(r"(\[.*\])", response, re.DOTALL)
        if array_match:
            try:
                data = json.loads(array_match.group(1))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return []

    def _validate_items(self, items: List[Any]) -> List[Dict]:
        """Validate and clean extracted items."""
        valid = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            content = str(item.get("content", "")).strip()
            item_type = str(item.get("type", "note")).lower().strip()

            if not name or not content or len(content) < 20:
                continue

            if item_type not in (
                "entity",
                "concept",
                "comparison",
                "project",
                "decision",
                "finding",
            ):
                item_type = "note"

            valid.append(
                {
                    "type": item_type,
                    "name": name,
                    "content": content,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "tags": item.get("tags", []),
                }
            )

        return valid

    def _extract_with_regex(self, text: str) -> List[Dict]:
        """Fallback regex-based extraction."""
        items = []
        pattern = re.compile(
            r"^###\s+(Entity|Concept|Comparison|Project|Decision|Finding):\s*(.+?)\r?\n"
            r"(.*?)(?=^###\s|\Z)",
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )

        for m in pattern.finditer(text):
            item_type = m.group(1).lower()
            name = m.group(2).strip()
            content = m.group(3).strip()

            if not name or not content:
                continue

            items.append(
                {
                    "type": item_type,
                    "name": name,
                    "content": content,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "tags": [],
                }
            )

        # If no structured markers but note has substance, create summary
        if not items and len(text.strip()) > 300:
            title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()
            else:
                first_sentence = text.split(".")[0].strip()
                title = (
                    (first_sentence[:60] + "...") if len(first_sentence) > 60 else first_sentence
                )

            items.append(
                {
                    "type": "note",
                    "name": title or "Daily Summary",
                    "content": text[:2000],
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "tags": [],
                }
            )

        return items

    def _write_compiled_note(self, item: Dict) -> None:
        """Write or update a compiled note with AI-First format."""
        note_type = item["type"]
        name = item["name"]

        type_to_dir = {
            "entity": "entities",
            "concept": "concepts",
            "comparison": "comparisons",
            "project": "projects",
            "decision": "concepts",
            "finding": "entities",
            "note": "concepts",
        }

        target_dir = self.compiled_dirs.get(type_to_dir.get(note_type, "concepts"))
        safe_name = re.sub(r"[<>\":/\\|?*]", "_", name).strip(". ")
        if not safe_name:
            safe_name = "untitled"

        note_path = target_dir / f"{safe_name}.md"

        # Build frontmatter
        fm = {
            "type": note_type,
            "name": name,
            "date": item["date"],
            "ai-first": True,
            "confidence": "medium",
        }
        tags = item.get("tags", [])
        if tags:
            fm["tags"] = tags

        fm_lines = ["---"]
        for k, v in fm.items():
            if isinstance(v, bool):
                fm_lines.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, list):
                fm_lines.append(f"{k}: {json.dumps(v)}")
            else:
                fm_lines.append(f'{k}: "{v}"')
        fm_lines.append("---")

        body = f"\n## For future assistant\n{item['content']}\n\n## Sources\n- Daily note {item['date']}\n"
        content = "\n".join(fm_lines) + "\n" + body + "\n"

        if note_path.exists():
            existing = note_path.read_text(encoding="utf-8")
            if item["content"] in existing:
                logger.debug("Note %s already contains this content, skipping", note_path)
                return
            content = existing.rstrip() + "\n\n## Update\n" + item["content"] + "\n"

        atomic_write_text(note_path, content)
        logger.info("Wrote compiled note: %s", note_path)

    def _archive_old_notes(self) -> int:
        """Move daily notes older than N days to archive/."""
        if self.archive_after_days <= 0:
            return 0

        cutoff = datetime.now() - timedelta(days=self.archive_after_days)
        archive_dir = self.daily_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        archived = 0
        for note in self.daily_dir.glob("*.md"):
            try:
                note_date = datetime.strptime(note.stem, "%Y-%m-%d")
            except ValueError:
                continue

            if note_date < cutoff:
                dest = archive_dir / note.name
                counter = 1
                original_dest = dest
                while dest.exists():
                    dest = archive_dir / f"{original_dest.stem}_{counter}{original_dest.suffix}"
                    counter += 1
                try:
                    note.rename(dest)
                    archived += 1
                except Exception as e:
                    logger.warning("Failed to archive %s: %s", note, e)

        return archived

"""Configuration management for LLMWiki.

Merges defaults < file config < environment variables.
Supports both YAML and JSON formats.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    "vault": {
        "path": "~/Documents/selfwiki",
        "schema": {
            "raw": "raw/",
            "daily": "chronicle/daily/",
            "entities": "entities/",
            "concepts": "concepts/",
            "comparisons": "comparisons/",
            "projects": "projects/",
            "queries": "queries/",
        },
    },
    "index": {
        "engine": "ripgrep",  # ripgrep | sqlite | bm25 | vector | hybrid
        "engines": [
            {"name": "keyword", "type": "ripgrep"},
        ],
        "rebuild_interval": 3600,  # seconds
        "incremental": True,
    },
    "retrieve": {
        "default_top_k": 5,
        "strategies": ["keyword", "graph", "temporal"],
        "fusion_method": "rrf",  # reciprocal rank fusion
        "rerank": False,
        "context_lines": 3,
    },
    "context": {
        "token_budget": 4000,
        "format": "markdown",  # markdown | xml | json
        "include_metadata": True,
        "deduplicate": True,
        "priority": "relevance",  # relevance | recency | diversity | structured
    },
    "cache": {
        "enabled": True,
        "maxsize": 100,
        "ttl": 300,  # seconds
    },
    "curate": {
        "enabled": True,
        "schedule": "0 2 * * *",  # cron expression
        "archive_after_days": 30,
        "llm_driven": True,
    },
}


def load_config(
    path: Optional[Path] = None,
    vault_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load and merge configuration.

    Priority: defaults < config file < env vars < explicit args.

    Args:
        path: Explicit config file path (llmwiki.yaml or llmwiki.json).
        vault_path: Explicit vault path override.

    Returns:
        Merged configuration dictionary.
    """
    config = dict(DEFAULT_CONFIG)

    # 1. Load from config file
    file_config = _load_config_file(path)
    config = _deep_merge(config, file_config)

    # 2. Override from environment variables
    env_config = _load_env_config()
    config = _deep_merge(config, env_config)

    # 3. Override vault path if explicitly provided
    if vault_path:
        config["vault"]["path"] = str(vault_path)

    # 4. Expand ~ in vault path
    config["vault"]["path"] = os.path.expanduser(config["vault"]["path"])

    return config


def _load_config_file(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load config from file, or auto-discover."""
    if path:
        return _parse_config_file(path)

    # Auto-discover: current dir -> home -> ~/.config
    candidates = [
        Path("llmwiki.yaml"),
        Path("llmwiki.json"),
        Path.home() / "llmwiki.yaml",
        Path.home() / "llmwiki.json",
        Path.home() / ".config" / "llmwiki" / "config.yaml",
        Path.home() / ".config" / "llmwiki" / "config.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return _parse_config_file(candidate)

    return {}


def _parse_config_file(path: Path) -> Dict[str, Any]:
    """Parse a YAML or JSON config file."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        try:
            import yaml

            return yaml.safe_load(text) or {}
        except ImportError:
            # Fallback: try JSON if yaml not available
            pass

    if suffix == ".json":
        return json.loads(text)

    # Try YAML first, then JSON
    try:
        import yaml

        return yaml.safe_load(text) or {}
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return {}


def _load_env_config() -> Dict[str, Any]:
    """Load configuration overrides from environment variables.

    Supported env vars:
      - LLMWIKI_VAULT_PATH
      - LLMWIKI_INDEX_ENGINE
      - LLMWIKI_RETRIEVE_TOP_K
      - LLMWIKI_CONTEXT_TOKEN_BUDGET
      - LLMWIKI_CACHE_ENABLED
    """
    env: Dict[str, Any] = {}

    if "LLMWIKI_VAULT_PATH" in os.environ:
        env.setdefault("vault", {})["path"] = os.environ["LLMWIKI_VAULT_PATH"]

    if "LLMWIKI_INDEX_ENGINE" in os.environ:
        env.setdefault("index", {})["engine"] = os.environ["LLMWIKI_INDEX_ENGINE"]

    if "LLMWIKI_RETRIEVE_TOP_K" in os.environ:
        env.setdefault("retrieve", {})["default_top_k"] = int(os.environ["LLMWIKI_RETRIEVE_TOP_K"])

    if "LLMWIKI_CONTEXT_TOKEN_BUDGET" in os.environ:
        env.setdefault("context", {})["token_budget"] = int(
            os.environ["LLMWIKI_CONTEXT_TOKEN_BUDGET"]
        )

    if "LLMWIKI_CACHE_ENABLED" in os.environ:
        env.setdefault("cache", {})["enabled"] = os.environ["LLMWIKI_CACHE_ENABLED"].lower() in (
            "true",
            "1",
            "yes",
        )

    return env


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries. Override values take precedence.

    For dict values, recursively merge. For other types, override wins.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def save_config(config: Dict[str, Any], path: Path) -> None:
    """Save configuration to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        try:
            import yaml

            path.write_text(yaml.dump(config, default_flow_style=False, allow_unicode=True))
            return
        except ImportError:
            pass

    # Default to JSON
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")

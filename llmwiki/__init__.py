"""LLMWiki: Context-Memory Harness for AI Agents.

Core metaphor: Context Window = RAM, Local Wiki = Disk.
This package provides a zero-dependency framework for indexing,
retrieving, and injecting local Markdown knowledge into agent prompts.
"""

from llmwiki.core.config import load_config
from llmwiki.core.harness import ContextMemoryHarness
from llmwiki.vault.schema import VaultSchema

__version__ = "0.4.0"
__all__ = ["ContextMemoryHarness", "load_config", "VaultSchema"]

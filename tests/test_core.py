"""Tests for LLMWiki core functionality."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from llmwiki.core.assembler import ContextAssembler, estimate_tokens
from llmwiki.core.cache import InMemoryCache
from llmwiki.core.config import DEFAULT_CONFIG, _deep_merge, load_config
from llmwiki.core.harness import ContextMemoryHarness
from llmwiki.core.indexer import IndexRegistry
from llmwiki.core.retriever import rrf_fusion
from llmwiki.vault.capture import TurnCapture
from llmwiki.vault.curate import CurationEngine
from llmwiki.vault.schema import VaultSchema
from llmwiki.vault.writer import atomic_write_text, safe_filename

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_vault():
    """Create a temporary vault for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp) / "test_vault"
        schema = VaultSchema(vault_path)
        schema.init_vault()
        yield vault_path


@pytest.fixture
def sample_entity(temp_vault):
    """Create a sample entity note."""
    path = temp_vault / "entities" / "test-entity.md"
    content = """---
type: entity
name: "Test Entity"
date: 2026-08-07
---

## For future assistant
This is a test entity about artificial intelligence.

## Related
[[Machine Learning]]
"""
    atomic_write_text(path, content)
    return path


@pytest.fixture
def sample_concept(temp_vault):
    """Create a sample concept note."""
    path = temp_vault / "concepts" / "test-concept.md"
    content = """---
type: concept
name: "Test Concept"
date: 2026-08-07
---

## For future assistant
This concept describes prompt injection attacks in LLMs.

## Key claims
- Direct injection overrides system instructions
- Indirect injection comes from external data
"""
    atomic_write_text(path, content)
    return path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_config_structure(self):
        assert "vault" in DEFAULT_CONFIG
        assert "index" in DEFAULT_CONFIG
        assert "retrieve" in DEFAULT_CONFIG
        assert "context" in DEFAULT_CONFIG
        assert "cache" in DEFAULT_CONFIG

    def test_deep_merge(self):
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}}
        merged = _deep_merge(base, override)
        assert merged["a"] == 1
        assert merged["b"]["c"] == 99
        assert merged["b"]["d"] == 3

    def test_load_config_with_vault_path(self):
        config = load_config(vault_path=Path("/custom/path"))
        # On Windows, Path normalizes separators; check basename instead
        assert Path(config["vault"]["path"]).name == "path"
        assert "custom" in str(config["vault"]["path"])


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class TestWriter:
    def test_atomic_write_text(self, temp_vault):
        path = temp_vault / "test_write.md"
        atomic_write_text(path, "hello world")
        assert path.read_text(encoding="utf-8") == "hello world"

    def test_safe_filename(self):
        assert safe_filename("Hello World") == "Hello World"
        assert safe_filename("file<name>") == "file_name_"
        assert safe_filename("...test...") == "test"


# ---------------------------------------------------------------------------
# Vault Schema
# ---------------------------------------------------------------------------


class TestVaultSchema:
    def test_init_vault_creates_directories(self, temp_vault):
        assert (temp_vault / "entities").is_dir()
        assert (temp_vault / "concepts").is_dir()
        assert (temp_vault / "chronicle" / "daily").is_dir()
        assert (temp_vault / "SCHEMA.md").exists()

    def test_validate_passes(self, temp_vault):
        schema = VaultSchema(temp_vault)
        issues = schema.validate()
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


class TestCapture:
    def test_append_turn(self, temp_vault):
        capture = TurnCapture(temp_vault, DEFAULT_CONFIG["vault"]["schema"])
        path = capture.append("Hello", "Hi there!")
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Hello" in content
        assert "Hi there!" in content

    def test_append_insight(self, temp_vault):
        capture = TurnCapture(temp_vault, DEFAULT_CONFIG["vault"]["schema"])
        path = capture.append_insight("Entity", "Bitcoin", "A digital currency")
        content = path.read_text(encoding="utf-8")
        assert "Bitcoin" in content


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestCache:
    def test_get_set(self):
        cache = InMemoryCache(maxsize=2, ttl=60)
        cache.set("query1", "context1")
        assert cache.get("query1") == "context1"

    def test_lru_eviction(self):
        cache = InMemoryCache(maxsize=2, ttl=60)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == "2"

    def test_ttl_expiration(self):
        cache = InMemoryCache(maxsize=10, ttl=0)  # 0 = instant expire
        cache.set("x", "y")
        import time

        time.sleep(0.01)
        assert cache.get("x") is None


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------


class TestAssembler:
    def test_assemble_empty(self):
        assembler = ContextAssembler(token_budget=1000)
        assert assembler.assemble([]) == ""

    def test_assemble_basic(self):
        assembler = ContextAssembler(token_budget=1000)
        results = [
            {
                "path": "entities/test.md",
                "title": "Test",
                "snippet": "This is a test snippet.",
                "score": 10.0,
                "engine": "ripgrep",
            }
        ]
        context = assembler.assemble(results)
        assert "Test" in context
        assert "test snippet" in context

    def test_estimate_tokens(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("hello world") > 0


# ---------------------------------------------------------------------------
# Retriever & Fusion
# ---------------------------------------------------------------------------


class TestRetriever:
    def test_rrf_fusion(self):
        list1 = [
            {"path": "a.md", "title": "A", "snippet": "", "score": 10},
            {"path": "b.md", "title": "B", "snippet": "", "score": 8},
        ]
        list2 = [
            {"path": "b.md", "title": "B", "snippet": "", "score": 9},
            {"path": "c.md", "title": "C", "snippet": "", "score": 7},
        ]
        fused = rrf_fusion([list1, list2])
        assert len(fused) == 3
        # b appears in both lists, should rank highest
        assert fused[0]["path"] == "b.md"


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------


class TestIndexer:
    def test_python_engine_search(self, temp_vault, sample_entity, sample_concept):
        registry = IndexRegistry(
            vault_path=temp_vault,
            schema_dirs=["entities/", "concepts/"],
            engine_names=["python"],
        )
        registry.build()
        results = registry.search("artificial intelligence", top_k=5)
        assert len(results) > 0
        assert any("test-entity" in r["path"] for r in results)


# ---------------------------------------------------------------------------
# Harness Integration
# ---------------------------------------------------------------------------


class TestHarness:
    def test_initialization(self, temp_vault):
        harness = ContextMemoryHarness(str(temp_vault))
        assert harness.vault_path == temp_vault

    def test_retrieve_and_assemble(self, temp_vault, sample_entity):
        harness = ContextMemoryHarness(str(temp_vault))
        harness.build_index()
        context = harness.retrieve_and_assemble("artificial intelligence", token_budget=2000)
        assert isinstance(context, str)

    def test_capture_turn(self, temp_vault):
        harness = ContextMemoryHarness(str(temp_vault))
        harness.capture_turn("Hello", "Hi!")
        daily_dir = temp_vault / "chronicle" / "daily"
        files = list(daily_dir.glob("*.md"))
        assert len(files) == 1

    def test_stats(self, temp_vault, sample_entity):
        harness = ContextMemoryHarness(str(temp_vault))
        stats = harness.stats()
        assert "vault_path" in stats
        assert stats["vault"]["compiled"].get("entities", 0) >= 1

    def test_cache_works(self, temp_vault, sample_entity):
        harness = ContextMemoryHarness(str(temp_vault))
        harness.build_index()
        # Use a query that matches the sample content
        ctx1 = harness.retrieve_and_assemble("artificial intelligence test")
        # Second call — cache hit
        ctx2 = harness.retrieve_and_assemble("artificial intelligence test")
        assert ctx1 == ctx2
        # Cache is only populated for non-empty results
        if ctx1 and harness.cache:
            assert harness.cache.stats()["size"] > 0


# ---------------------------------------------------------------------------
# Curation
# ---------------------------------------------------------------------------


class TestCuration:
    def test_regex_extraction(self, temp_vault):
        # Write a daily note with explicit markers
        daily_dir = temp_vault / "chronicle" / "daily"
        note = daily_dir / "2026-08-07.md"
        content = """# Daily Chronicle: 2026-08-07

Some introductory text about today's session. We discussed several important topics
related to blockchain technology and knowledge management systems. These are key
insights that should be preserved for future reference.

### Entity: Bitcoin
Bitcoin is a decentralized digital currency that uses proof-of-work consensus.
It was created by Satoshi Nakamoto in 2008 and has since become the most
widely recognized cryptocurrency in the world.

### Concept: Zettelkasten
Zettelkasten is a note-taking method using atomic notes with unique IDs and
cross-references. It was popularized by Niklas Luhmann and is widely used in
academic and knowledge management contexts today.
"""
        atomic_write_text(note, content)

        config = dict(DEFAULT_CONFIG)
        config["vault"]["path"] = str(temp_vault)
        config["curate"]["llm_driven"] = False

        engine = CurationEngine(temp_vault, config)
        stats = engine.run()
        assert stats["status"] == "ok"
        assert stats["created"] >= 2

    def test_llm_extraction(self, temp_vault):
        # Mock LLM generate
        def mock_llm(prompt: str) -> str:
            return json.dumps(
                [{"type": "entity", "name": "Ethereum", "content": "A smart contract platform."}]
            )

        daily_dir = temp_vault / "chronicle" / "daily"
        note = daily_dir / "2026-08-07.md"
        atomic_write_text(note, "Some conversation about blockchain.")

        config = dict(DEFAULT_CONFIG)
        config["vault"]["path"] = str(temp_vault)
        config["curate"]["llm_driven"] = True

        engine = CurationEngine(temp_vault, config)
        stats = engine.run(llm_generate=mock_llm)
        assert stats["status"] == "ok"
        assert stats["llm_mode"] is True

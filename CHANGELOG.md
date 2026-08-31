# Changelog

## 0.3.0 — MCP Server

### New Features
- **MCP server**: `llmwiki mcp` / `llmwiki-mcp` exposes the vault as five memory tools
  (`memory_search`, `memory_recall`, `memory_capture`, `memory_curate`, `memory_stats`)
  over stdio — works with Claude Desktop, Claude Code, Cursor, Codex, and any MCP host
- **New optional extra**: `pip install llmwiki-harness[mcp]` (compatible with both
  `mcp` 1.x `FastMCP` and 2.x `MCPServer` APIs)
- **New tests**: unit tests for all MCP tools plus a real stdio end-to-end test
  (`tests/test_mcp.py`, `tests/test_mcp_e2e.py`)
- **Knowledge graph edge table** (`llmwiki/core/graph.py`): wikilinks are
  resolved and persisted in SQLite at index time, enabling backlinks,
  weighted 2-hop neighborhood traversal, and data-backed dead-link/orphan
  detection. Supports Obsidian syntax (`[[Note|alias]]`, `[[Note#section]]`);
  dead links are recorded (and auto-revived when the target note appears)
  instead of silently dropped
- **New CLI command**: `llmwiki graph <name>` shows a note's outgoing links,
  backlinks, and 2-hop neighbors; `llmwiki health` is now backed by the edge
  table (with the source of each dead link)

### Fixes
- `harness.stats()` now reports the installed package version instead of a
  hardcoded string
- **FTS5 query sanitization**: raw user queries are tokenized, quoted, and
  OR-joined before `MATCH` — quotes, parentheses, and `AND`/`OR`/`NOT` in
  natural-language input no longer crash the query or silently degrade to
  whole-string LIKE
- **CJK search**: the index now prefers the `trigram` tokenizer (SQLite ≥ 3.34),
  enabling proper Chinese/Japanese/Korean substring matching; existing
  non-trigram databases are migrated and re-indexed automatically. Fallback
  chain: trigram FTS5 → unicode61 FTS5 → plain table + LIKE
- **LIKE fallback** now matches any query token instead of the whole raw string
- **Snippet extraction**: fixed off-by-one that dropped one context line above
  the match, and multi-word queries now locate snippets by individual tokens
- **Temporal strategy rewritten**: replaced whole-string containment (which
  missed nearly every natural-language query) with token-coverage matching —
  CJK queries are split into overlapping bigrams, results ranked by token
  coverage then recency
- **Wikilink resolution**: graph strategy now resolves `[[links]]` into the
  chronicle/raw layers too, with a vault-wide filename fallback for nested or
  custom directories
- **`llmwiki init` now honors `-v/--vault`** when no path argument is given
  (previously it always wrote to the default `~/Documents/selfwiki`)

## 0.2.0 — Framework-Agnostic Rewrite

### Breaking Changes
- **Renamed package**: `hermes-llmwiki` → `llmwiki`
- **Removed Hermes dependency**: No longer a Hermes plugin. Now a standalone framework.
- **Entry point changed**: `hermes_llmwiki` → `llmwiki`

### New Features
- **Multi-engine search**: ripgrep, SQLite FTS5, pure Python fallback
- **Multi-strategy retrieval**: keyword + graph (wikilink traversal) + temporal
- **RRF fusion**: Reciprocal Rank Fusion for combining retrieval strategies
- **Token budget management**: ContextAssembler never overflows context window
- **In-memory LRU cache**: L1 RAM layer for frequent queries
- **OpenClaw adapter**: First-class `OpenClawMemoryHook` for OpenClaw agents
- **YAML-driven configuration**: `llmwiki.yaml` or `~/.config/llmwiki/config.yaml`
- **Environment variable overrides**: `LLMWIKI_VAULT_PATH`, `LLMWIKI_INDEX_ENGINE`, etc.
- **Incremental indexing**: Only re-index changed files via mtime tracking

### Architecture
- **New module structure**:
  - `llmwiki/core/` — Harness, Indexer, Retriever, Assembler, Cache, Config
  - `llmwiki/search/` — Pluggable search engines (ripgrep, sqlite, python)
  - `llmwiki/vault/` — Capture, Curate, Schema, Writer
  - `llmwiki/adapters/` — Framework adapters (OpenClaw first)
  - `llmwiki/cli.py` — Standalone CLI

### Retained from 0.1.x
- Karpathy 3-layer vault architecture (raw → chronicle → compiled)
- AI-First note format with frontmatter
- Atomic file writes
- LLM-driven + regex fallback curation
- Daily chronicle capture
- Wikilink support

## 0.1.x — hermes-llmwiki

- Initial release as Hermes Agent memory plugin
- ripgrep-based search
- 3-layer vault architecture
- Basic curation pipeline

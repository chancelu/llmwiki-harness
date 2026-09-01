# Changelog

## 0.5.0 — Memory Strength & Explainable Recall

### New Features
- **Forgetting-curve memory strength**: the link graph now records every
  recall (`note_meta` table) and scores each note with an Ebbinghaus-style
  decay — `strength = exp(-days / (7 · (1 + ln(recalls))))`. Frequently
  recalled notes fade slower (spaced repetition); never-recalled notes are
  neutral, never penalized. Retrieval re-ranks with
  `score × (1 + retrieve.strength_weight · strength)` (default weight 0.5,
  set 0 to disable)
- **Explainable recall**: every result now carries `via` (which strategies
  surfaced it, e.g. `["keyword", "graph"]`) and `strength` (0–1 or null),
  visible in `memory_search` JSON output

### Fixes
- **Token-based keyword search** — both the Python and ripgrep engines
  matched the *whole query string* verbatim, so "handshake timeout" missed a
  note saying "handshake design". Queries are now tokenized (words + CJK
  bigrams, shared `query_tokens` helper), matched per-token, and ranked by
  coverage with an exact-phrase bonus. The new regression benchmark caught
  this
- **Config defaults are deep-copied** — `load_config()` no longer shares
  nested dicts with `DEFAULT_CONFIG`

### Improvements
- **Size-aware engine auto-selection** — vaults above 5,000 notes now
  default to the sqlite FTS5 index instead of full-scan engines. Benchmarks
  (`bench/bench_engines.py`): at 100k notes sqlite answers in ~17 ms vs
  ~8 s (ripgrep) / ~15 s (python); CJK queries degrade worst on full scans

### Tests
- 98 tests: memory-strength decay/rehearsal, via annotation, strength
  re-ranking, engine auto-selection, plus `tests/test_eval_recall.py` — a
  fixed-vault recall regression benchmark (7 keyword/temporal/CJK cases +
  graph traversal)

## 0.4.1 — Obsidian Compatibility Fixes

### Fixes
- **`![[embed]]` no longer parsed as wikilinks** — image/file embeds stopped
  producing phantom dead links in `llmwiki health`
- **Attachment links skipped** — `[[doc.pdf]]`-style links to non-Markdown
  files are not note links; `[[note.md]]` with an explicit suffix resolves
- **Frontmatter aliases resolve** — Obsidian `aliases:` (inline list and
  block list forms) are registered in the link index, so `[[Alias]]` links
  now resolve instead of dying
- **Short daily notes are curated** — the 200-char minimum dropped light-use
  days entirely; now configurable via `curate.min_note_chars` (default 80)

### Tests
- 76 tests (7 new graph tests for embeds/attachments/aliases, 2 new curation
  threshold tests); fixed a latent test-pollution bug (shallow copy of
  DEFAULT_CONFIG leaking `llm_driven=False` across test files)

## 0.4.0 — Self-Sustaining Memory Loop

### New Features
- **MCP sampling curation**: `memory_curate` now runs extraction through the
  *host's own LLM* via MCP sampling — zero configuration (no API key, no
  endpoint). Fallback chain: sampling → `LLMWIKI_LLM_ENDPOINT` → regex
- **`memory-protocol` MCP prompt**: a host-loadable behavior template
  encoding when to recall (before answering), capture (after meaningful
  turns), and curate (periodically) — makes the memory loop self-sustaining
- **First-run auto-init**: the harness now initializes the full vault
  skeleton (including `SCHEMA.md`) when pointed at an empty directory

### Fixes
- serverInfo now reports the real package version in the MCP handshake
- Temporal-search snippets no longer leak the `# Daily Chronicle:` header

### Tests
- 68 tests, including sampling-bridge unit tests (success + fallback paths)
  and server metadata (version, prompt registration)

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

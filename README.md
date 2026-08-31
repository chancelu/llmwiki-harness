# LLMWiki

[![CI](https://github.com/chancelu/llmwiki-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/chancelu/llmwiki-harness/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/llmwiki-harness.svg)](https://pypi.org/project/llmwiki-harness/)
[![Python](https://img.shields.io/pypi/pyversions/llmwiki-harness.svg)](https://pypi.org/project/llmwiki-harness/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Context Window = RAM, Local Wiki = Disk**
>
> A zero-dependency, agent-agnostic long-term memory layer. Your memories live as plain Markdown files on your machine — any AI agent can read them, write them, and carry them across sessions.

> PyPI note: the distribution is published as **`llmwiki-harness`** (`pip install llmwiki-harness`). The bare `llmwiki` name on PyPI belongs to an unrelated third-party project — do not `pip install llmwiki`. The Python import package and CLI are still called `llmwiki`.

## What This Is

Every serious agent user hits the same wall: the agent forgets everything between sessions. LLMWiki solves this by treating:

- **Your context window** as volatile RAM (fast, limited, per-session)
- **Your local Markdown wiki** as persistent Disk (slow, unlimited, cross-session)

LLMWiki is **not tied to any agent product**. It speaks MCP (the open Model Context Protocol), so it plugs into any MCP-compatible host — and its vault is plain Markdown, so even agents without MCP can read it directly. Your memories outlive any single agent, model, or vendor.

```
┌─────────────────────────────────────────────┐
│  Any agent (via MCP or direct file access)  │
│  ┌───────────────────────────────────────┐  │
│  │  L1: Context Window (RAM)             │  │
│  │  ├── Current conversation             │  │
│  │  └── ← Injected wiki knowledge        │  │
│  └───────────────────────────────────────┘  │
│              ↑ ↓ LLMWiki Harness            │
│  ┌───────────────────────────────────────┐  │
│  │  L3: Local Markdown Wiki (Disk)       │  │
│  │  ├── entities/  concepts/  projects/  │  │
│  │  ├── chronicle/daily/  (conversation) │  │
│  │  └── raw/  (session dumps)            │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

## Install It Through Your Agent (easiest)

LLMWiki ships an [AGENTS.md](AGENTS.md) machine-readable install guide. Paste this into any agent (Claude, Cursor, Codex, Kimi, …):

> **Read <https://github.com/chancelu/llmwiki-harness/blob/main/AGENTS.md> and set up LLMWiki as my long-term memory. My notes should live at `~/Documents/selfwiki`.**

The agent will install the package, initialize the vault, register the MCP server with your host, and verify it works — no manual steps.

## Install It Yourself

### 1. Install + initialize a vault

```bash
pip install "llmwiki-harness[mcp]"   # core + MCP server
llmwiki init ~/Documents/selfwiki    # creates the vault skeleton
```

The vault structure:

```
~/Documents/selfwiki/
├── raw/              # Layer 1: session dumps
├── chronicle/daily/  # Layer 2: daily conversation logs
├── entities/         # Layer 3: atomic knowledge
├── concepts/
├── comparisons/
├── projects/
├── queries/
└── SCHEMA.md
```

Already have an Obsidian vault? Point LLMWiki at it instead — the Markdown is read as-is, wikilinks included.

### 2. Register with your MCP host

Generic stdio config (works with any MCP client):

```json
{
  "mcpServers": {
    "llmwiki": {
      "command": "llmwiki-mcp",
      "env": { "LLMWIKI_VAULT_PATH": "/absolute/path/to/selfwiki" }
    }
  }
}
```

Where to put it:

| Host | Config location |
|------|-----------------|
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) · `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |
| Cursor | `~/.cursor/mcp.json` |
| Claude Code | `claude mcp add llmwiki --env LLMWIKI_VAULT_PATH=/path -- llmwiki-mcp` |
| Codex CLI | `~/.codex/config.toml` |
| Any other MCP host | standard stdio server registration |

Notes: use absolute paths (some hosts don't expand `~`). If `llmwiki-mcp` isn't on the host's PATH, use the absolute path from `which llmwiki-mcp`, or `"command": "uvx", "args": ["--from", "llmwiki-harness[mcp]", "llmwiki-mcp"]` (slower cold start). The server speaks stdio and is compatible with both `mcp` 1.x and 2.x Python SDKs.

### 3. What your agent gets

Five memory tools:

| Tool | Purpose |
|------|---------|
| `memory_search(query, top_k)` | Raw ranked search over the wiki |
| `memory_recall(query, token_budget)` | Assembled context block, ready to inject into a prompt |
| `memory_capture(user_message, assistant_message)` | Store a conversation turn in the chronicle |
| `memory_curate()` | Distill the chronicle into compiled atomic notes — uses **your host's own LLM via MCP sampling** when available (no API key or endpoint to configure), falling back to a configured endpoint, then regex |
| `memory_stats()` | Vault / index / cache statistics |

Plus one MCP **prompt**: `memory-protocol` — a host-loadable behavior template that tells the agent when to recall (before answering), when to capture (after meaningful exchanges), and when to curate. Load it in your host to make the memory loop self-sustaining.

## Features

| Feature | Status |
|---------|--------|
| **Multi-engine search** — ripgrep, SQLite FTS, pure Python fallback | ✅ |
| **CJK-aware full-text search** — SQLite FTS5 trigram tokenizer + bigram query splitting; Chinese/Japanese/Korean vaults just work | ✅ |
| **Multi-strategy retrieval** — keyword, graph (wikilink traversal), temporal | ✅ |
| **Knowledge graph edge table** — index-time wikilink graph with backlinks, 2-hop weighted traversal, dead-link/orphan detection | ✅ |
| **RRF fusion** — combine multiple retrieval strategies | ✅ |
| **Token budget management** — never overflow the context window | ✅ |
| **In-memory cache** — avoid repeated disk reads | ✅ |
| **MCP server** — any MCP-compatible host, stdio transport | ✅ |
| **3-layer vault architecture** (Karpathy-native) | ✅ |
| **Zero dependencies** for core (optional enhancements via extras) | ✅ |

## Use as a Python Library

For custom agent frameworks, skip MCP and use the harness directly:

```python
from llmwiki import ContextMemoryHarness

harness = ContextMemoryHarness("~/Documents/selfwiki")
harness.build_index()

# Before each turn — retrieve relevant knowledge
context = harness.retrieve_and_assemble(
    query=user_message,
    token_budget=2000,
)

# Inject into your prompt
messages = [
    {"role": "system", "content": f"{system_prompt}\n\n{context}"},
    {"role": "user", "content": user_message},
]

# After each turn — capture to chronicle
harness.capture_turn(user_message, assistant_response)

# Periodically — curate chronicle into compiled notes
harness.curate()
```

## CLI

```bash
llmwiki init <path>              # Initialize vault
llmwiki index [--force]          # Build search index
llmwiki search "prompt injection" # Search wiki
llmwiki curate [--llm]           # Run curation pipeline
llmwiki stats                    # Vault statistics
llmwiki health                   # Check for dead links, orphans
llmwiki graph "Zettelkasten"     # Show a note's links, backlinks, 2-hop neighbors
llmwiki config                   # Show configuration
llmwiki mcp                      # Start MCP server (stdio) for any MCP host
```

## Configuration

Create `llmwiki.yaml` in your vault root or `~/.config/llmwiki/config.yaml`:

```yaml
vault:
  path: ~/Documents/selfwiki

index:
  engine: ripgrep  # ripgrep | sqlite | hybrid
  incremental: true

retrieve:
  default_top_k: 5
  strategies: [keyword, graph, temporal]
  fusion_method: rrf

context:
  token_budget: 4000
  format: markdown
  priority: relevance  # relevance | recency | diversity | structured

cache:
  enabled: true
  maxsize: 100
  ttl: 300

curate:
  enabled: true
  archive_after_days: 30
```

## Architecture

### Core Components

| Module | Purpose |
|--------|---------|
| `Indexer` | Manages search indices (ripgrep, SQLite, etc.) |
| `LinkGraph` | Persistent wikilink edge table (SQLite): neighbors, backlinks, dead links, orphans |
| `Retriever` | Multi-strategy recall (keyword, graph, temporal) |
| `Assembler` | Token-budget-aware context assembly |
| `Cache` | In-memory LRU cache |
| `MCP Server` | Exposes memory tools to any MCP host over stdio |

### Data Flow

```
User Message → Retriever → [Keyword | Graph | Temporal] → RRF Fusion
                                                        ↓
                              Assembler ←── Token Budget Check
                                                        ↓
                                              System Prompt Injection

Turn End → Capture → chronicle/daily/YYYY-MM-DD.md
                              ↓ (scheduled curation)
                     compiled/entities/ | concepts/ | projects/
```

### Vault Schema (Karpathy 3-Layer)

```
┌─────────────────────────────────────────┐
│ Layer 3: Compiled Wiki (Query)          │
│ entities/ concepts/ comparisons/        │
│ projects/ queries/                      │
│ ↑ LLM curation (nightly)                │
├─────────────────────────────────────────┤
│ Layer 2: Chronicle (Daily Notes)        │
│ chronicle/daily/YYYY-MM-DD.md           │
│ ↑ auto-capture from agent turns         │
├─────────────────────────────────────────┤
│ Layer 1: Raw (Session Exports)          │
│ raw/session-{id}.md                     │
│ ↑ on_session_end / on_pre_compress      │
└─────────────────────────────────────────┘
```

## Legacy Adapters

`llmwiki/adapters/openclaw.py` predates MCP and is kept for existing
OpenClaw users. For anything new, use the MCP server — it is the
framework-neutral integration path and the only one under active
development.

## Ecosystem

- **TypeScript port for DeepSeek Harness**: [`dsh-llmwiki`](https://github.com/chancelu/dsh-llmwiki) — same vault format, native dsh plugin, on npm.

## What's New in 0.4.0

- **Zero-config LLM curation via MCP sampling** — `memory_curate` now asks the *host's own model* to distill the chronicle (no API key, no endpoint, nothing to configure). Fallback chain: sampling → `LLMWIKI_LLM_ENDPOINT` → regex.
- **`memory-protocol` MCP prompt** — a host-loadable operating protocol telling the agent when to recall, capture, and curate, so the memory loop sustains itself instead of depending on the host guessing.
- **First-run auto-init** — pointing the server at an empty directory now creates the full vault skeleton (including `SCHEMA.md`) automatically.
- **Polish** — serverInfo now reports the real package version; temporal snippets no longer leak the `# Daily Chronicle:` header line.

## What's New in 0.3.0

- **MCP server** — `llmwiki mcp` / `llmwiki-mcp` exposes five memory tools (`memory_search`, `memory_recall`, `memory_capture`, `memory_curate`, `memory_stats`) to any MCP-compatible host. Compatible with both mcp 1.x (`FastMCP`) and 2.x (`MCPServer`).
- **Persistent knowledge graph** — wikilinks are extracted at index time into a SQLite edge table (`.llmwiki/graph.db`). The graph retrieval strategy now does weighted 2-hop traversal (forward links 1.0, backlinks 0.8, hop-2 0.5) instead of re-parsing files on every query.
- **`llmwiki graph` / improved `llmwiki health`** — inspect any note's links, backlinks, and 2-hop neighborhood; health checks report dead links and orphan notes from the edge table.
- **CJK search fixed** — SQLite engine now prefers the FTS5 `trigram` tokenizer (with graceful fallback), and temporal/keyword matching splits CJK queries into bigrams. Chinese vaults are first-class.
- **FTS5 query sanitization** — natural-language queries no longer crash `MATCH` on quotes, hyphens, or AND/OR/NOT.
- **Tooling** — repo-wide black + ruff clean, CI now actually runs on `main` (it was misconfigured to `master`).

## From hermes-llmwiki

This project evolved from [`hermes-llmwiki`](https://github.com/chancelu/hermes-llmwiki). Key changes in 0.2.0:

- **Framework-agnostic**: No longer Hermes-only — works with any agent
- **Multi-engine search**: ripgrep + SQLite FTS + Python fallback
- **Multi-strategy retrieval**: keyword + graph + temporal + RRF fusion
- **Token budget management**: Dynamic context assembly
- **In-memory cache**: L1 RAM layer for frequent queries

## Development

```bash
git clone https://github.com/chancelu/llmwiki-harness
cd llmwiki-harness
pip install -e ".[dev,mcp]"

pytest tests/          # 68 tests
black llmwiki/ tests/  # formatting (line-length 100)
ruff check llmwiki/ tests/
```

CI runs the test matrix (Linux / Windows / macOS × Python 3.10–3.13) plus black and ruff on every push to `main`.

Releases are published to PyPI via trusted publishing: pushing a `v*` tag triggers the `publish` workflow.

## License

MIT

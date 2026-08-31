# LLMWiki

> **Context Window = RAM, Local Wiki = Disk**
>
> A zero-dependency framework that turns your local Markdown vault (Obsidian, selfwiki, etc.) into long-term memory for any AI agent.

> PyPI note: the distribution is published as **`llmwiki-harness`** (`pip install llmwiki-harness`). The bare `llmwiki` name on PyPI belongs to an unrelated third-party project — do not `pip install llmwiki`. The Python import package and CLI are still called `llmwiki`.

## What This Is

Every serious agent user hits the same wall: the agent forgets everything between sessions. LLMWiki solves this by treating:

- **Your context window** as volatile RAM (fast, limited, per-session)
- **Your local Markdown wiki** as persistent Disk (slow, unlimited, cross-session)

It provides a universal **harness** that any agent framework can plug into — no Docker, no cloud, no vector DB required.

```
┌─────────────────────────────────────────────┐
│  Agent (OpenClaw / LangChain / AutoGen ...) │
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

## Features

| Feature | Status |
|---------|--------|
| **Multi-engine search** — ripgrep, SQLite FTS, pure Python fallback | ✅ |
| **Multi-strategy retrieval** — keyword, graph (wikilink traversal), temporal | ✅ |
| **Knowledge graph edge table** — index-time wikilink graph with backlinks, 2-hop weighted traversal, dead-link/orphan detection | ✅ |
| **RRF fusion** — combine multiple retrieval strategies | ✅ |
| **Token budget management** — never overflow the context window | ✅ |
| **In-memory cache** — avoid repeated disk reads | ✅ |
| **OpenClaw adapter** — drop-in memory hook | ✅ |
| **MCP server** — works with Claude Desktop / Claude Code / Cursor / any MCP host | ✅ |
| **3-layer vault architecture** (Karpathy-native) | ✅ |
| **Zero dependencies** for core (optional enhancements via extras) | ✅ |

## Install

```bash
# Core (zero dependencies)
pip install llmwiki-harness

# With semantic search support
pip install llmwiki-harness[semantic]

# With MCP server support (Claude Desktop / Cursor / any MCP host)
pip install llmwiki-harness[mcp]

# Dev
pip install llmwiki-harness[dev]
```

## Quick Start

### 1. Initialize a vault

```bash
llmwiki init ~/Documents/selfwiki
```

This creates the directory structure:
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

### 2. Use in your agent

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

### 3. OpenClaw adapter

```python
from llmwiki.adapters import OpenClawMemoryHook

hook = OpenClawMemoryHook("~/Documents/selfwiki")

# On each turn:
wiki_context = hook.on_turn_start(user_message)
# → inject into system prompt

hook.on_turn_end(user_message, assistant_response)
# → auto-captures to chronicle
```

## MCP Server

The fastest way to use LLMWiki: run it as an [MCP](https://modelcontextprotocol.io) server and plug it into Claude Desktop, Claude Code, Cursor, Codex, or any MCP-compatible host. The agent gets five memory tools:

| Tool | Purpose |
|------|---------|
| `memory_search(query, top_k)` | Raw ranked search over the wiki |
| `memory_recall(query, token_budget)` | Assembled context block, ready to inject into a prompt |
| `memory_capture(user_message, assistant_message)` | Store a conversation turn in the chronicle |
| `memory_curate()` | Distill the chronicle into compiled atomic notes |
| `memory_stats()` | Vault / index / cache statistics |

### Claude Desktop / Cursor (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "llmwiki": {
      "command": "uvx",
      "args": ["--from", "llmwiki-harness[mcp]", "llmwiki-mcp"],
      "env": {
        "LLMWIKI_VAULT_PATH": "~/Documents/selfwiki"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add llmwiki -- uvx --from "llmwiki-harness[mcp]" llmwiki-mcp
# then set the vault:  export LLMWIKI_VAULT_PATH=~/Documents/selfwiki
```

### Already installed via pip?

```bash
pip install llmwiki-harness[mcp]
llmwiki mcp                          # stdio server, vault from config/env
llmwiki -v ~/Documents/selfwiki mcp  # explicit vault path
```

The server speaks stdio (the MCP default for local servers). Compatible with both `mcp` 1.x and 2.x Python SDKs.

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
| `Retriever` | Multi-strategy recall (keyword, graph, temporal) |
| `Assembler` | Token-budget-aware context assembly |
| `Cache` | In-memory LRU cache |

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

## Vault Schema (Karpathy 3-Layer)

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

## Ecosystem

- **TypeScript port for DeepSeek Harness**: [`dsh-llmwiki`](https://github.com/chancelu/dsh-llmwiki) — same vault format, native dsh plugin, on npm.

## From hermes-llmwiki

This project evolved from [`hermes-llmwiki`](https://github.com/chancelu/hermes-llmwiki). Key changes in 0.2.0:

- **Framework-agnostic**: No longer Hermes-only — works with any agent
- **Multi-engine search**: ripgrep + SQLite FTS + Python fallback
- **Multi-strategy retrieval**: keyword + graph + temporal + RRF fusion
- **Token budget management**: Dynamic context assembly
- **In-memory cache**: L1 RAM layer for frequent queries
- **OpenClaw adapter**: First-class adapter for OpenClaw agents

## License

MIT

# AGENTS.md — How to install and operate LLMWiki for your user

This file is written for AI agents, not humans. If a user pasted this
repository's URL into your conversation and asked you to "install this",
"set this up", or "give me long-term memory", follow this file.

## What this is

LLMWiki is a local long-term memory layer for any AI agent. It stores
memories as plain Markdown files (an Obsidian-compatible "vault") on the
user's machine and exposes them to you over MCP as five tools. Zero cloud,
zero database servers, zero dependencies beyond Python ≥ 3.10 for the core.

- PyPI package: `llmwiki-harness` (import package / CLI: `llmwiki`)
- MCP server entry points: `llmwiki mcp` or the `llmwiki-mcp` script
- Transport: stdio (standard local MCP)
- Compatible with both `mcp` 1.x (`FastMCP`) and 2.x (`MCPServer`) SDKs
- Exposes 5 tools + 1 prompt (`memory-protocol` — load it if your host
  supports MCP prompts; it encodes the operating rules below)

## Install procedure (do this autonomously)

1. **Check Python**: `python3 --version` — must be ≥ 3.10. If missing,
   install Python first or use `uv`/`pipx`.
2. **Install the package with MCP support**:
   ```bash
   pip install "llmwiki-harness[mcp]"
   # or, isolated: pipx install "llmwiki-harness[mcp]"
   # or, zero-install via uvx (slower cold start): uvx --from "llmwiki-harness[mcp]" llmwiki-mcp
   ```
3. **Pick a vault path.** Default: `~/Documents/selfwiki`. If the user
   already has an Obsidian vault or notes folder, ask whether to reuse it —
   LLMWiki reads existing Markdown happily. Reusing an existing vault is
   often the better experience.
4. **Initialize the vault**:
   ```bash
   llmwiki init <vault-path>
   ```
   This creates `entities/ concepts/ comparisons/ projects/ queries/
   chronicle/daily/ raw/` plus `SCHEMA.md`. Never delete existing files;
   init only creates missing scaffolding. (Since 0.4.0 the server also
   auto-initializes an empty directory on first run, so this step is a
   safety net rather than a hard requirement.)
5. **Register the MCP server with your host.** Generic stdio config:
   ```json
   {
     "mcpServers": {
       "llmwiki": {
         "command": "llmwiki-mcp",
         "env": { "LLMWIKI_VAULT_PATH": "<absolute vault path>" }
       }
     }
   }
   ```
   If `llmwiki-mcp` is not on the host's PATH, use the absolute path from
   `which llmwiki-mcp`, or fall back to `"command": "uvx", "args":
   ["--from", "llmwiki-harness[mcp]", "llmwiki-mcp"]`.
   Config file locations for common hosts:
   | Host | Config file |
   |------|-------------|
   | Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |
   | Cursor | `~/.cursor/mcp.json` |
   | Claude Code | `claude mcp add llmwiki --env LLMWIKI_VAULT_PATH=<path> -- llmwiki-mcp` |
   | Codex CLI | `~/.codex/config.toml` (`[mcp_servers.llmwiki]`) |
   | Others | any MCP client that supports stdio servers |
   Prefer absolute paths over `~` in host config files — some hosts do not
   expand it.
6. **Verify** (run these yourself before declaring success):
   ```bash
   llmwiki -v <vault-path> stats     # should print vault/index stats JSON
   ```
   Then restart the host and call `memory_stats` through the host's MCP
   tooling; it should return the same vault path.

## Operating contract (how to use the tools well)

| Tool | When to call |
|------|--------------|
| `memory_recall(query, token_budget)` | **Before answering**, whenever the user's question might relate to past sessions: projects, preferences, decisions, people, prior debugging. Returns a ready-to-inject context block. |
| `memory_search(query, top_k)` | When you need raw ranked hits instead of an assembled block. |
| `memory_capture(user_message, assistant_message)` | **After meaningful exchanges** — decisions, facts learned about the user, project state changes, solutions to problems. Skip small talk. Err on the side of capturing. |
| `memory_curate()` | Periodically (every few days of active use, or when the user asks): distills the raw chronicle into atomic wiki notes. Uses **your own model via MCP sampling** automatically — no separate LLM configuration needed. |
| `memory_stats()` | Diagnostics; shows note counts per layer and index state. |

Behavioral rules:

- **Recall first, answer second.** A memory layer that is never queried is
  worthless. When in doubt, call `memory_recall`.
- **Capture is the only way memory grows.** After any exchange that produced
  durable knowledge, call `memory_capture` with a faithful summary.
- The vault is the user's data. Never delete vault files; curation only
  appends or archives.
- All memories live in local Markdown files the user can read, edit, and
  git-version. If the user asks "what do you remember about X", you can
  also just read the vault files directly.

## Repository layout (for contributors)

- `llmwiki/core/` — harness, retriever (keyword/graph/temporal + RRF),
  assembler (token budget), link graph (SQLite edge table), cache
- `llmwiki/search/` — pluggable engines: ripgrep, SQLite FTS5 (trigram,
  CJK-safe), pure-Python fallback
- `llmwiki/vault/` — schema init, turn capture, curation pipeline
- `llmwiki/mcp_server.py` — MCP tool wiring (plain functions work without
  the `mcp` package; only `create_server()` requires it)
- `llmwiki/adapters/` — legacy framework hooks (superseded by MCP)

## Development

```bash
git clone https://github.com/chancelu/llmwiki-harness
cd llmwiki-harness
pip install -e ".[dev,mcp]"
pytest tests/            # 98 tests
black llmwiki/ tests/    # line-length 100
ruff check llmwiki/ tests/
```

CI: Linux / Windows / macOS × Python 3.10–3.13, plus black and ruff.
Releases: push a `v*` tag → trusted publishing to PyPI → GitHub Release
with wheel + sdist attached. Version lives in `pyproject.toml` only.

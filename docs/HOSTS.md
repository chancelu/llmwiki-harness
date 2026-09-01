# Host Compatibility Matrix

LLMWiki is an ordinary MCP server — any host that speaks MCP can use it.
This page collects per-host setup snippets and what is verified how.

Legend:

- **e2e** — covered by an automated protocol-level test in `tests/test_mcp_e2e.py`
  (real server, real MCP client, initialize → list_tools → call_tool)
- **manual** — setup is known to work from user reports; not covered by CI.
  If you use one of these, please report back (issue or PR) so we can keep
  this matrix honest.

## Transports

| Transport | Command | Verified |
|---|---|---|
| stdio (default, local hosts) | `llmwiki mcp` | e2e |
| streamable HTTP (remote hosts, containers, one shared memory server) | `llmwiki mcp --transport http --port 8000` | e2e |
| SSE (legacy clients) | `llmwiki mcp --transport sse --port 8000` | manual |

## Hosts

| Host | Transport | Sampling curation (`memory_curate` via host LLM) | Status |
|---|---|---|---|
| Kimi Work (desktop) | stdio (uvx) | not yet exercised | **verified** 2026-09-01 — real mount, full handshake + capture/search round-trip |
| Claude Desktop | stdio | supported | manual |
| Cursor | stdio / http | not supported → falls back to endpoint/regex | manual |
| Kimi CLI / Kimi Code | stdio / http | supported | manual |
| Codex | stdio | not supported → fallback | manual |
| Any MCP host with streamable HTTP | http | depends on client | e2e (protocol) |

Sampling support is probed at runtime: if the host can't sample, curation
falls back automatically (`LLMWIKI_LLM_ENDPOINT` → regex), so a "not
supported" cell means "curation uses the fallback chain", not breakage.

## Setup snippets

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "llmwiki": {
      "command": "uvx",
      "args": ["--from", "llmwiki-harness[mcp]", "llmwiki-mcp"],
      "env": { "LLMWIKI_VAULT_PATH": "~/Documents/selfwiki" }
    }
  }
}
```

### Cursor (`.cursor/mcp.json`) / other stdio hosts

Same shape as above. Cursor also supports remote servers:

```json
{
  "mcpServers": {
    "llmwiki": { "url": "http://127.0.0.1:8000/mcp" }
  }
}
```

with the server running as `llmwiki mcp --transport http --port 8000`.

### Kimi Work / Kimi CLI

Kimi Work desktop reads `mcp.json` from its runtime home
(`daimon/runtime/kimi-code/home/mcp.json` under the app's shared-data
directory); Kimi CLI reads `~/.kimi/mcp.json`. Both take the standard shape:

```json
{
  "mcpServers": {
    "llmwiki": {
      "command": "uv",
      "args": ["tool", "run", "--python", "3.12", "--from",
               "llmwiki-harness[mcp]", "llmwiki-mcp"],
      "env": { "LLMWIKI_VAULT_PATH": "/absolute/path/to/selfwiki" }
    }
  }
}
```

Notes: use an absolute `uv` path if the host's PATH doesn't include it, and
pin `--python 3.12` on systems whose default Python is < 3.10. Restart the
host (or start a new session) after editing `mcp.json`.

### Generic agent (no MCP)

Point the agent at this repo — `AGENTS.md` is a self-serve install
guide. Any agent that can run shell commands can use the CLI
(`llmwiki search`, `llmwiki curate`, ...) without MCP at all.

## Multiple vaults

One server can serve several vaults (e.g. personal + work). Configure:

```yaml
# llmwiki.yaml
vault:
  path: ~/Documents/selfwiki
vaults:
  work: ~/Documents/workwiki
  research: ~/Documents/research
```

or via env: `LLMWIKI_VAULTS="work=~/Documents/workwiki,research=~/Documents/research"`.

Every tool takes an optional `vault` parameter (empty = default vault);
`memory_stats` lists the configured vaults.

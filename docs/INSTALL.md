# Installing recall as an MCP server

`recall` exposes two tools — `search_history` and `get_session` — over stdio MCP, so any MCP
client can search your conversation history. Embeddings warm-load once at startup; queries are
sub-second after that.

**Requirements:** the embeddings index must exist (`history.db` with the `emb` table — run
`src/index.py` then `src/embed.py`). `OPENAI_API_KEY` is read from the environment, or falls
back to `~/.zshrc`. With no key, search degrades gracefully to keyword-only (no crash).

## Claude Code  (already registered, user scope)
```bash
claude mcp add recall --scope user -- \
  ~/Projects/recall/.venv/bin/python ~/Projects/recall/src/mcp_server.py
claude mcp list          # → recall: … ✔ Connected
```
Tools appear as `mcp__recall__search_history` / `mcp__recall__get_session` in any project.

## Claude Desktop  ·  `~/Library/Application Support/Claude/claude_desktop_config.json`
```json
{
  "mcpServers": {
    "recall": {
      "command": "/Users/robertnowell/Projects/recall/.venv/bin/python",
      "args": ["/Users/robertnowell/Projects/recall/src/mcp_server.py"]
    }
  }
}
```

## Cursor  ·  `~/.cursor/mcp.json`   (and Windsurf · `~/.codeium/windsurf/mcp_config.json`)
Same shape as the Claude Desktop block above (`mcpServers` → `recall`).

## Notes
- **Env passthrough:** if a client doesn't forward `OPENAI_API_KEY`, the server self-loads it
  from `~/.zshrc`. To pin it explicitly instead, add an `"env": {"OPENAI_API_KEY": "..."}` block
  to the server config (writes the secret into that config file — your call).
- **Freshness:** the index is a point-in-time snapshot until the incremental indexer ships.
  Re-run `python src/index.py && python src/embed.py` to pick up new sessions (embed is
  content-hash cached, so it only embeds what's new).
- **ChatGPT / Gemini consumer apps** do not accept third-party MCP memory servers — coverage is
  the MCP-speaking tool ecosystem (Claude Code/Desktop, Cursor, Windsurf, VS Code).

#!/usr/bin/env python3
"""recall MCP server — exposes your conversation-history search to any MCP client
(Claude Code, Claude Desktop, Cursor, Windsurf, VS Code).

Tools:
  search_history(query, k, mode)     — hybrid semantic+keyword search; one row per session
  get_session(sess, max_chars)       — pull the full text of a session you found

Runs over stdio. Embeddings are warm-loaded once at startup so queries stay sub-second.
"""
import os, sqlite3, re, json, datetime
from mcp.server.fastmcp import FastMCP
import search as core   # src/search.py — shared retrieval core

mcp = FastMCP("recall")
USAGE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "usage.jsonl")

def _log(event):
    """Append a usage event for the Layer-B utility eval (tool-call rate, result counts)."""
    try:
        event["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(USAGE_LOG, "a") as fh:
            fh.write(json.dumps(event) + "\n")
    except Exception:
        pass


@mcp.tool()
def search_history(query: str, k: int = 8, mode: str = "hybrid") -> str:
    """Search the user's own past AI conversation history by meaning AND keyword.

    Use this whenever the user refers to something they worked on before ("that thing we
    discussed", "the report from a few weeks ago", "how did we handle X"), or when relevant
    prior context would help and you're not sure it's in the current thread. Returns the most
    relevant past sessions, one row each, with a snippet and a session id you can pass to
    get_session for the full thread.

    Args:
        query: natural-language description of what to find (paraphrase is fine — semantic search handles vocabulary mismatch).
        k: number of sessions to return (default 8).
        mode: "hybrid" (default, best), "dense" (pure semantic), or "bm25" (pure keyword).
    """
    hits = core.search(query, k=k, mode=mode)
    _log({"tool": "search_history", "query": query, "k": k, "mode": mode, "n_results": len(hits)})
    if not hits:
        return f"No matching past conversations found for: {query!r}"
    lines = [f"Found {len(hits)} relevant past session(s) for {query!r}:\n"]
    for i, h in enumerate(hits, 1):
        proj = h["project"].replace("-Users-robertnowell-Projects-", "").replace("-Users-robertnowell", "(home)")
        lines.append(f"{i}. [{h['ts'][:10]}] {proj}")
        lines.append(f"   {h['snippet']}")
        lines.append(f"   → get_session(sess=\"{h['sess']}\")\n")
    return "\n".join(lines)


@mcp.tool()
def get_session(sess: str, max_chars: int = 8000) -> str:
    """Retrieve the full conversation text of a past session by its id (from search_history).

    Use after search_history when you need the actual content of a thread, not just the snippet.

    Args:
        sess: the session id returned by search_history.
        max_chars: cap the returned transcript at this many characters (default 8000).
    """
    con = sqlite3.connect(core.DB)
    rows = con.execute(
        "SELECT role, ts, content FROM messages WHERE sess=? ORDER BY ts", (sess,)
    ).fetchall()
    _log({"tool": "get_session", "sess": sess, "n_turns": len(rows)})
    if not rows:
        return f"No session found with id {sess!r}"
    parts = []
    for role, ts, content in rows:
        body = re.sub(r"\n{3,}", "\n\n", content).strip()
        parts.append(f"\n[{role} · {ts[:16]}]\n{body}")
    full = "".join(parts)
    # truncate the assembled text (never drop a whole turn just because it's big)
    if len(full) > max_chars:
        full = full[:max_chars] + f"\n…(truncated at {max_chars} chars; {len(rows)} turns total — raise max_chars for more)"
    return f"Session {sess} ({len(rows)} turns):\n{full}"


if __name__ == "__main__":
    core._load()   # warm the embedding matrix before accepting requests
    mcp.run()

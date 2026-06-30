#!/usr/bin/env python3
"""Index Claude Code's per-session auto-titles (the 'ai-title' events) into a `titles` table.
These give the 'topic_match' modality — a human-readable label of what each whole session was
about. Safe to re-run; last title per session wins. Run standalone or from refresh."""
import os, sys, json, sqlite3, glob

ROOT = os.path.expanduser("~/.claude/projects")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.db")

def build(con):
    con.execute("CREATE TABLE IF NOT EXISTS titles(sess TEXT PRIMARY KEY, title TEXT)")
    found = {}
    for fp in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
        try:
            with open(fp, "r", errors="ignore") as fh:
                for line in fh:
                    if '"ai-title"' not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if o.get("type") == "ai-title" and o.get("sessionId") and o.get("aiTitle"):
                        found[o["sessionId"]] = o["aiTitle"]   # last wins
        except Exception:
            pass
    con.executemany("INSERT OR REPLACE INTO titles(sess, title) VALUES(?,?)", list(found.items()))
    con.commit()
    return len(found)

if __name__ == "__main__":
    con = sqlite3.connect(DB)
    n = build(con)
    total = con.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
    print(f"indexed {n} session titles (table now {total})")
    # quick peek
    for sess, title in con.execute("SELECT sess, title FROM titles LIMIT 5"):
        print(f"  {sess[:12]}…  {title!r}")
    con.close()

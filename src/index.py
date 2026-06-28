#!/usr/bin/env python3
"""Step 1: parse all Claude Code session JSONL into a per-message SQLite store + FTS5 lexical index.
Stdlib only. Indexes user/assistant prose; discards tool_use/tool_result payloads."""
import os, sys, json, sqlite3, glob, hashlib, re

ROOT = os.path.expanduser("~/.claude/projects")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.db")

NOISE_PREFIXES = ("<task-notification", "[image", "[request interrupted", "<system-reminder",
                  "<local-command", "caveat: the messages below", "this session is being continued",
                  "<command-", "[tool ")
def is_noise(t):
    tl = t.lstrip().lower()
    return any(tl.startswith(p) for p in NOISE_PREFIXES)

def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "\n".join(parts)
    return ""

def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE messages(
        id INTEGER PRIMARY KEY,
        sess TEXT, project TEXT, role TEXT, ts TEXT, ym TEXT,
        chash TEXT, nchars INTEGER, content TEXT)""")
    con.execute("CREATE VIRTUAL TABLE fts USING fts5(content, content='messages', content_rowid='id')")

    files = glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True)
    rows = []
    seen = set()  # dedupe identical (sess,chash) — subagent/duplicate noise
    n_files = 0
    for fp in files:
        n_files += 1
        project = os.path.relpath(fp, ROOT).split(os.sep)[0]
        sess = os.path.basename(fp).replace(".jsonl", "")
        try:
            with open(fp, "r", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if o.get("type") not in ("user", "assistant"):
                        continue
                    msg = o.get("message") or {}
                    role = msg.get("role") or o.get("type")
                    txt = extract_text(msg.get("content"))
                    txt = txt.strip()
                    if len(txt) < 12:           # drop trivial / empty
                        continue
                    if txt.startswith("<") and "command-name" in txt[:60]:
                        continue                # skip slash-command echoes
                    if is_noise(txt):
                        continue                # skip tool/system/notification noise
                    ts = o.get("timestamp", "") or ""
                    ym = ts[:7] if len(ts) >= 7 else "unknown"
                    chash = hashlib.sha1(txt.encode("utf-8", "ignore")).hexdigest()
                    key = (sess, chash)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append((sess, project, role, ts, ym, chash, len(txt), txt))
                    if len(rows) >= 5000:
                        con.executemany("INSERT INTO messages(sess,project,role,ts,ym,chash,nchars,content) VALUES(?,?,?,?,?,?,?,?)", rows)
                        rows = []
        except Exception as e:
            print("skip", fp, e, file=sys.stderr)
    if rows:
        con.executemany("INSERT INTO messages(sess,project,role,ts,ym,chash,nchars,content) VALUES(?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.execute("INSERT INTO fts(rowid, content) SELECT id, content FROM messages")
    con.commit()

    # ---- stats ----
    cur = con.cursor()
    tot, chars = cur.execute("SELECT COUNT(*), SUM(nchars) FROM messages").fetchone()
    nsess = cur.execute("SELECT COUNT(DISTINCT sess) FROM messages").fetchone()[0]
    print(f"files scanned:        {n_files:,}")
    print(f"distinct sessions:    {nsess:,}")
    print(f"indexed messages:     {tot:,}  (deduped)")
    print(f"prose chars:          {chars:,}  (~{chars//4:,} tokens)")
    print()
    print("messages by month + role:")
    print(f"  {'month':<9}{'user':>8}{'asst':>8}{'total':>9}")
    for ym, in cur.execute("SELECT DISTINCT ym FROM messages ORDER BY ym").fetchall():
        u = cur.execute("SELECT COUNT(*) FROM messages WHERE ym=? AND role='user'", (ym,)).fetchone()[0]
        a = cur.execute("SELECT COUNT(*) FROM messages WHERE ym=? AND role='assistant'", (ym,)).fetchone()[0]
        print(f"  {ym:<9}{u:>8,}{a:>8,}{u+a:>9,}")
    print(f"\nDB written: {DB}  ({os.path.getsize(DB)/1e6:.0f} MB)")
    con.close()

if __name__ == "__main__":
    main()

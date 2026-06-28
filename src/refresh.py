#!/usr/bin/env python3
"""Incremental refresh — scan session JSONL, add only NEW messages to the index, then embed
the new content (content-hash cached). Safe to run repeatedly (nightly cron / launchd).
Unlike index.py (which rebuilds from scratch), this preserves existing rows + embeddings."""
import os, sys, json, sqlite3, glob, hashlib, subprocess

ROOT = os.path.expanduser("~/.claude/projects")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "history.db")

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
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""

def main():
    if not os.path.exists(DB):
        print("no history.db — run index.py first for the initial build", file=sys.stderr)
        sys.exit(1)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    existing = set(con.execute("SELECT sess || '|' || chash FROM messages"))
    existing = {r[0] for r in existing}
    before = len(existing)

    files = glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True)
    new_rows = []
    for fp in files:
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
                    txt = extract_text(msg.get("content")).strip()
                    if len(txt) < 12 or (txt.startswith("<") and "command-name" in txt[:60]):
                        continue
                    if is_noise(txt):
                        continue
                    chash = hashlib.sha1(txt.encode("utf-8", "ignore")).hexdigest()
                    key = f"{sess}|{chash}"
                    if key in existing:
                        continue
                    existing.add(key)
                    ts = o.get("timestamp", "") or ""
                    ym = ts[:7] if len(ts) >= 7 else "unknown"
                    new_rows.append((sess, project, role, ts, ym, chash, len(txt), txt))
        except Exception as e:
            print("skip", fp, e, file=sys.stderr)

    if new_rows:
        cur = con.cursor()
        cur.executemany("INSERT INTO messages(sess,project,role,ts,ym,chash,nchars,content) VALUES(?,?,?,?,?,?,?,?)", new_rows)
        # incrementally extend the FTS index with just the new rowids
        start_id = cur.execute("SELECT COUNT(*) FROM messages").fetchone()[0] - len(new_rows) + 1
        con.execute("INSERT INTO fts(rowid, content) SELECT id, content FROM messages WHERE id >= ?", (start_id,))
        con.commit()
    con.close()
    print(f"new messages indexed: {len(new_rows):,}  (corpus {before:,} → {before + len(new_rows):,})")

    # embed the new content (embed.py is content-hash cached → only embeds what's missing)
    if new_rows:
        print("embedding new content…")
        subprocess.run([sys.executable, os.path.join(HERE, "embed.py")], check=False)
    else:
        print("nothing new to embed.")

if __name__ == "__main__":
    main()

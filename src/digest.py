#!/usr/bin/env python3
"""Precompute a compact per-project 'recent threads' digest (the SessionStart push payload).
Write-time precompute: runs in the nightly refresh, so the hook just reads a string — no work
on the turn's critical path. No LLM needed for v0 (first substantive user line = the gist).

  digest.py --all                 rebuild digests for every project with history
  digest.py --cwd /path/to/proj   print the digest for the project matching a working dir
  digest.py --project <key>       print the digest for an encoded project key
"""
import os, sys, sqlite3, re

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "history.db")
N_RECENT = 6          # sessions per digest
MIN_SESSIONS = 3      # only build a digest if the project has at least this much history

def cwd_to_key(path):
    """/Users/me/Projects/kopi -> -Users-me-Projects-kopi  (matches ~/.claude/projects encoding)."""
    return os.path.abspath(path).replace("/", "-")

def _gist(con, sess):
    for (content,) in con.execute(
        "SELECT content FROM messages WHERE sess=? AND role='user' ORDER BY ts LIMIT 5", (sess,)):
        c = re.sub(r"\s+", " ", content).strip()
        if len(c) >= 40:
            return c[:140]
    return "(no clear opening prompt)"

def build_for(con, project):
    sessions = con.execute(
        "SELECT sess, MAX(ts) mx FROM messages WHERE project=? GROUP BY sess ORDER BY mx DESC LIMIT ?",
        (project, N_RECENT)).fetchall()
    if len(sessions) < MIN_SESSIONS:
        return None
    nice = project.replace("-Users-robertnowell-Projects-", "").replace("-Users-robertnowell", "(home)")
    lines = [f"## recall — recent threads in {nice}",
             "Relevant past work may exist below. Use the `recall` tool "
             "(search_history / get_session) to pull full context when useful.\n"]
    for sess, mx in sessions:
        lines.append(f"- [{mx[:10]}] {_gist(con, sess)}")
    return "\n".join(lines)

def main():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS digests(project TEXT PRIMARY KEY, md TEXT, updated TEXT)")
    args = sys.argv[1:]
    if not args or args[0] == "--all":
        projects = [r[0] for r in con.execute("SELECT project, COUNT(DISTINCT sess) c FROM messages GROUP BY project HAVING c >= ?", (MIN_SESSIONS,))]
        n = 0
        for p in projects:
            md = build_for(con, p)
            if md:
                con.execute("INSERT OR REPLACE INTO digests(project, md, updated) VALUES(?,?,datetime('now'))", (p, md))
                n += 1
        con.commit()
        print(f"digests rebuilt for {n} projects")
    elif args[0] == "--cwd" and len(args) > 1:
        key = cwd_to_key(args[1])
        row = con.execute("SELECT md FROM digests WHERE project=?", (key,)).fetchone()
        if row: print(row[0])
    elif args[0] == "--project" and len(args) > 1:
        row = con.execute("SELECT md FROM digests WHERE project=?", (args[1],)).fetchone()
        if row: print(row[0])
    con.close()

if __name__ == "__main__":
    main()

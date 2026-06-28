#!/usr/bin/env python3
"""recall SessionStart hook — inject the precomputed 'recent threads' digest for the current
project so a fresh session starts warm. Reads a precomputed string from the DB (no embedding,
no search) → fast, never blocks. Silent if the project has no digest. Never errors out.
"""
import os, sys, json, sqlite3

DB = os.path.expanduser("~/Projects/recall/history.db")

def key_for(path):
    return os.path.abspath(path).replace("/", "-")

def main():
    try:
        # consume stdin payload (cwd may be in it) but we mainly use the env / cwd
        try:
            payload = json.load(sys.stdin)
        except Exception:
            payload = {}
        cwd = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        con = sqlite3.connect(DB)
        row = con.execute("SELECT md FROM digests WHERE project=?", (key_for(cwd),)).fetchone()
        con.close()
        if not row:
            sys.exit(0)
        try:
            import datetime
            with open(os.path.expanduser("~/Projects/recall/usage.jsonl"), "a") as fh:
                fh.write(json.dumps({"tool": "digest_injected", "project": key_for(cwd),
                                     "ts": datetime.datetime.now().isoformat(timespec="seconds")}) + "\n")
        except Exception:
            pass
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": row[0],
        }}))
    except Exception:
        # a memory hook must never break session startup
        sys.exit(0)

if __name__ == "__main__":
    main()

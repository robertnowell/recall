#!/usr/bin/env python3
"""recall UserPromptSubmit hook — eager per-message surfacing.
On each prompt: skip trivial ones, else ask the warm daemon for the top relevant PAST threads
and (only if the match clears a threshold) inject a short "you discussed this before" note.

Designed to be silent and cheap: trivial prompts cost ~0ms (no network); real prompts cost one
daemon round-trip (~0.5s). Fails OPEN — if the daemon is down/slow, it injects nothing and never
blocks the turn. Tune with RECALL_THRESHOLD (default 0.55) and RECALL_PORT.
"""
import os, sys, json, urllib.parse, urllib.request

PORT = os.environ.get("RECALL_PORT", "8787")
THRESHOLD = float(os.environ.get("RECALL_THRESHOLD", "0.55"))
HIT_FLOOR = THRESHOLD - 0.05
TIMEOUT = 0.8
ACK = {"thanks","thank you","ok","okay","yes","yep","no","nope","go","sure","do it","cool",
       "nice","great","got it","continue","next","y","n","k","yeah","status","done"}

def trivial(p):
    s = p.strip().lower()
    return (len(s) < 20 or s in ACK or s.startswith("/")
            or s.startswith("<command-") or s.startswith("[image"))

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    prompt = (data.get("prompt") or "").strip()
    if not prompt or trivial(prompt):
        sys.exit(0)
    sess = data.get("session_id", "")
    url = (f"http://127.0.0.1:{PORT}/search?q={urllib.parse.quote(prompt[:500])}"
           f"&k=3&exclude={urllib.parse.quote(sess)}")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            res = json.load(r)
    except Exception:
        sys.exit(0)                      # fail open: daemon down → no inject, no delay beyond timeout
    if res.get("top_score", 0) < THRESHOLD:
        sys.exit(0)                      # nothing relevant enough → stay silent
    hits = [h for h in res.get("hits", []) if h.get("score", 0) >= HIT_FLOOR][:3]
    if not hits:
        sys.exit(0)
    lines = ["🧠 recall — you may have relevant past context (use the `recall` tool for full threads):"]
    for h in hits:
        proj = h["project"].replace("-Users-robertnowell-Projects-", "").replace("-Users-robertnowell", "(home)")
        lines.append(f"- [{h['ts'][:10]}] {proj}: {h['snippet'][:160]}  (sess={h['sess']})")
    # log what fired, ON WHICH PROMPT, and WHAT it surfaced — so fires are reconstructable
    # (both for your visible `recall log` review and for downstream did-it-help analysis)
    try:
        import datetime
        with open(os.path.expanduser("~/Projects/recall/usage.jsonl"), "a") as fh:
            fh.write(json.dumps({
                "tool": "eager_inject",
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "session_id": sess,
                "prompt": prompt[:300],
                "top_score": res["top_score"],
                "surfaced": [{"sess": h["sess"], "score": h.get("score"),
                              "project": h["project"], "snippet": h["snippet"][:160]} for h in hits],
            }) + "\n")
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "\n".join(lines),
    }}))

if __name__ == "__main__":
    main()

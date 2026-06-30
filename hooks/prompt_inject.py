#!/usr/bin/env python3
"""recall UserPromptSubmit hook — eager per-message surfacing with labeled provenance.
Skips trivial prompts; else asks the warm daemon for relevant PAST sessions across three
modalities (semantic / grep / topic) and, if anything clears the bar, injects a self-describing
note tagged by match type. Fails OPEN (daemon down -> nothing, no block). Tune RECALL_THRESHOLD.
"""
import os, sys, json, urllib.parse, urllib.request

PORT = os.environ.get("RECALL_PORT", "8787")
THRESHOLD = float(os.environ.get("RECALL_THRESHOLD", "0.55"))
TIMEOUT = 1.5
ACK = {"thanks","thank you","ok","okay","yes","yep","no","nope","go","sure","do it","cool",
       "nice","great","got it","continue","next","y","n","k","yeah","status","done","stop"}
# system/tool messages that are NOT real user prompts — never fire on these
NOISE_PREFIXES = ("<task-notification", "[image", "[request interrupted", "<system-reminder",
                  "<local-command", "caveat:", "[tool ", "<command-")

def trivial(p):
    s = p.strip().lower()
    return (len(s) < 20 or s in ACK or s.startswith("/")
            or any(s.startswith(pfx) for pfx in NOISE_PREFIXES))

MAX_LINES = 4

def line(m):
    proj = m["project"].replace("-Users-robertnowell-Projects-", "").replace("-Users-robertnowell", "(home)")
    when = m["ts"][:10]
    text = (m.get("text") or "").replace("\n", " ").strip()
    types = m["types"]
    # topic title is legible as-is; passages get ellipsis
    body = f'"{text}"' if "topic_match" in types else f'"…{text[:140]}…"'
    return f'- {body}  — {proj} · {when} · sess={m["sess"]}  type="{",".join(types)}"'

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
           f"&exclude={urllib.parse.quote(sess)}")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            res = json.load(r)
    except Exception:
        sys.exit(0)

    matches = res.get("matches", [])
    topic_present = any("topic_match" in m["types"] for m in matches)
    # fire if a strong semantic match OR any session-title (topic) match exists
    if res.get("sem_top", 0) < THRESHOLD and not topic_present:
        sys.exit(0)

    # matches arrive RRF-ordered (combined strength); drop weak semantic-only marginals
    picked = []
    for m in matches:
        types = m["types"]
        sem = m["scores"].get("semantic_match")
        # a semantic-only hit must clear the bar; topic/grep hits earn their place
        if types == ["semantic_match"] and (sem is None or sem < THRESHOLD):
            continue
        picked.append(m)
        if len(picked) >= MAX_LINES:
            break
    if not picked:
        sys.exit(0)
    lines = [line(m) for m in picked]

    ctx = ("the user's previous sessions may be relevant to this inquiry. Here are a few potential matches:\n"
           + "\n".join(lines)
           + '\nyou can retrieve context for a session with the recall tool: get_session("<sess id>")')

    try:
        import datetime
        with open(os.path.expanduser("~/Projects/recall/usage.jsonl"), "a") as fh:
            fh.write(json.dumps({"tool": "eager_inject", "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "session_id": sess, "prompt": prompt[:300], "sem_top": res.get("sem_top"),
                                 "n_lines": len(lines), "types": [m["types"] for m in picked],
                                 "injected": "\n".join(lines)}) + "\n")
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))

if __name__ == "__main__":
    main()

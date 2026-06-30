#!/usr/bin/env python3
"""recall UserPromptSubmit hook — eager per-message surfacing with labeled provenance.
Skips trivial prompts; else asks the warm daemon for relevant PAST sessions across three
modalities (semantic / grep / topic) and, if anything clears the bar, injects a self-describing
note tagged by match type. Fails OPEN (daemon down -> nothing, no block). Tune RECALL_THRESHOLD.
"""
import os, sys, json, urllib.parse, urllib.request

PORT = os.environ.get("RECALL_PORT", "8787")
THRESHOLD = float(os.environ.get("RECALL_THRESHOLD", "0.55"))
TIMEOUT = 1.0
ACK = {"thanks","thank you","ok","okay","yes","yep","no","nope","go","sure","do it","cool",
       "nice","great","got it","continue","next","y","n","k","yeah","status","done","stop"}

def trivial(p):
    s = p.strip().lower()
    return (len(s) < 20 or s in ACK or s.startswith("/")
            or s.startswith("<command-") or s.startswith("[image"))

def line(item, mtype):
    proj = item["project"].replace("-Users-robertnowell-Projects-", "").replace("-Users-robertnowell", "(home)")
    when = item["ts"][:10]
    text = item.get("text", "").replace("\n", " ").strip()
    if mtype == "topic_match":
        body = f'"{text}"'
    else:
        body = f'"…{text[:140]}…"'
    return f'- {body}  — {proj} · {when} · sess={item["sess"]}  type="{mtype}"'

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

    topic = res.get("topic", [])
    # fire if a strong semantic match OR a session-title (topic) match exists
    if res.get("sem_top", 0) < THRESHOLD and not topic:
        sys.exit(0)

    lines, used = [], set()
    for it in topic:                                   # topic first (most legible)
        k = it["sess"] + it.get("text","")[:30]
        if k in used: continue
        used.add(k); lines.append(line(it, "topic_match"))
    for it in res.get("semantic", []):
        if it["score"] < THRESHOLD: continue
        k = it["sess"] + it.get("text","")[:30]
        if k in used: continue
        used.add(k); lines.append(line(it, "semantic_match"))
    for it in res.get("grep", []):
        k = it["sess"] + it.get("text","")[:30]
        if k in used: continue
        used.add(k); lines.append(line(it, "grep_match"))
    if not lines:
        sys.exit(0)

    ctx = ("the user's previous sessions may be relevant to this inquiry. Here are a few potential matches:\n"
           + "\n".join(lines)
           + '\nyou can retrieve context for a session with the recall tool: get_session("<sess id>")')

    try:
        import datetime
        with open(os.path.expanduser("~/Projects/recall/usage.jsonl"), "a") as fh:
            fh.write(json.dumps({"tool": "eager_inject", "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "session_id": sess, "prompt": prompt[:300], "sem_top": res.get("sem_top"),
                                 "n_topic": len(topic), "n_lines": len(lines),
                                 "injected": "\n".join(lines)}) + "\n")
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))

if __name__ == "__main__":
    main()

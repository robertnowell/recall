#!/usr/bin/env python3
"""recall log — your visibility surface. Shows what the eager hook actually surfaced, on which
prompts. This is the 'YOU judge it' eval: read the fires, decide if it surfaced useful stuff.

  python src/showlog.py [N]      show the last N eager fires (default 15)
"""
import os, sys, json, collections, datetime

USAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "usage.jsonl")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 15

ev = []
if os.path.exists(USAGE):
    for line in open(USAGE):
        try: ev.append(json.loads(line))
        except Exception: pass

eager  = [e for e in ev if e.get("tool") == "eager_inject"]
pulls  = [e for e in ev if e.get("tool") == "search_history"]
digest = [e for e in ev if e.get("tool") == "digest_injected"]

print(f"=== recall activity: {len(eager)} eager fires · {len(digest)} digests · {len(pulls)} tool pulls ===")
if eager:
    span = f"{eager[0]['ts'][:16]} → {eager[-1]['ts'][:16]}"
    print(f"span: {span}\n")

rich = [e for e in eager if "prompt" in e]
thin = len(eager) - len(rich)
if thin:
    print(f"(note: {thin} older fires were logged before rich logging — no prompt/snippet captured)\n")

print(f"--- last {min(N, len(rich))} fires (newest first) ---")
for e in reversed(rich[-N:]):
    print(f"\n[{e['ts'][:16]}]  top_score={e.get('top_score'):.2f}")
    print(f"  your prompt: {e.get('prompt','')[:120]!r}")
    print(f"  surfaced:")
    for h in e.get("surfaced", []):
        proj = h["project"].replace("-Users-robertnowell-Projects-", "").replace("-Users-robertnowell", "(home)")
        print(f"    · {h.get('score'):.2f} [{proj}] {h['snippet'][:90]}")

if rich:
    print("\n--- read it: for each fire, was the surfaced context actually relevant + the snippet useful?")
    print("    if mostly 'topically right but junk snippet' → snippet-selection bug, not a retrieval bug.")
    print("    if mostly 'wrong topic' → raise RECALL_THRESHOLD. if 'great' → keep.")

#!/usr/bin/env python3
"""Eval the eager per-message inject. Its failure mode isn't 'miss' — it's NOISE: firing with
irrelevant context on every message (context rot + annoyance). So we measure, over a threshold
sweep: FIRE-RATE (how often it injects) and PRECISION (when it fires, is the top hit actually
relevant, LLM-judged) — plus end-to-end LATENCY. Goal: a threshold with high precision at a
fire-rate that's useful but not spammy.

Requires the daemon running (launchctl load com.recall.daemon). Uses gpt-4o-mini as judge.
"""
import os, sys, json, time, urllib.parse, urllib.request, sqlite3, random, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from openai import OpenAI
DB = os.path.join(HERE, "..", "history.db")
PORT = os.environ.get("RECALL_PORT", "8787")
N = int(os.environ.get("EAGER_N", "50"))
THRESHOLDS = [0.50, 0.55, 0.58, 0.60, 0.65]
random.seed(17)
client = OpenAI()

con = sqlite3.connect(DB)
# real substantive prompts (the kind that should sometimes fire) + trivials (must NOT fire)
subs = [r for r in con.execute(
    "SELECT sess, content FROM messages WHERE role='user' AND nchars BETWEEN 50 AND 400 AND ts!=''")]
random.shuffle(subs); subs = subs[:N]
trivials = ["thanks", "go", "ok do it", "yes", "looks good", "next", "perfect thanks"]

def query(q, sess=""):
    url = f"http://127.0.0.1:{PORT}/search?q={urllib.parse.quote(q[:500])}&k=1&exclude={urllib.parse.quote(sess)}"
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=3) as r:
        res = json.load(r)
    return res, (time.time() - t0)

def judge(prompt, snippet):
    m = [{"role": "system", "content": "You decide if a snippet from a PAST conversation is "
          "plausibly relevant/useful context for the user's NEW message. Answer only YES or NO."},
         {"role": "user", "content": f"NEW message:\n{prompt}\n\nPAST snippet:\n{snippet}\n\nRelevant?"}]
    try:
        a = client.chat.completions.create(model="gpt-4o-mini", temperature=0, max_tokens=3, messages=m)
        return a.choices[0].message.content.strip().upper().startswith("Y")
    except Exception:
        return None

# gather scores + judgments for substantive prompts
rows, lats = [], []
for sess, content in subs:
    try:
        res, lat = query(content, sess)
    except Exception:
        continue
    lats.append(lat)
    top = res.get("top_score", 0.0)
    hit = res["hits"][0]["snippet"] if res.get("hits") else ""
    rel = judge(content, hit) if hit else False
    rows.append((top, rel, content[:60], hit[:60]))

# trivial guard check (does the hook's triviality gate hold? these should never fire)
triv_scores = []
for t in trivials:
    try: triv_scores.append(query(t)[0].get("top_score", 0.0))
    except Exception: pass

print(f"evaluated {len(rows)} real prompts · daemon latency p50 {statistics.median(lats):.3f}s "
      f"p90 {sorted(lats)[int(len(lats)*0.9)]:.3f}s\n")
print(f"{'threshold':>9} {'fire-rate':>10} {'precision':>10}  (precision = of fired, % judged relevant)")
for T in THRESHOLDS:
    fired = [r for r in rows if r[0] >= T]
    judged = [r for r in fired if r[1] is not None]
    prec = (sum(1 for r in judged if r[1]) / len(judged)) if judged else 0.0
    print(f"{T:>9.2f} {len(fired)/len(rows):>9.0%} {prec:>10.0%}")

print(f"\ntrivial prompts (gate should keep these silent regardless of score): "
      f"max top_score={max(triv_scores):.3f} — but the hook's word/length gate blocks them pre-query")
# show a few false positives at the current default to make noise concrete
DEF = float(os.environ.get("RECALL_THRESHOLD", "0.55"))
fps = [r for r in rows if r[0] >= DEF and r[1] is False][:4]
if fps:
    print(f"\nexample FALSE FIRES at threshold {DEF} (injected but judged irrelevant):")
    for top, rel, q, h in fps:
        print(f"  score {top:.2f} · Q: {q!r}\n            ↳ {h!r}")
print("\nREAD: pick the threshold at the precision/fire-rate knee. High precision matters more than"
      "\ncoverage here — a noisy eager inject trains you to ignore it. Set via RECALL_THRESHOLD.")
con.close()

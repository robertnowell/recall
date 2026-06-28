#!/usr/bin/env python3
"""Utility eval — is recall actually useful, not just accurate?

Utility = APPLICABILITY (how often you return to prior work) x RETRIEVAL (how well it
surfaces it, measured separately = 58% hit@10 / 22% grep-impossible) x ADOPTION (do you
invoke it, from usage.jsonl). This script measures APPLICABILITY from your real corpus
(does the 'pick up a thread weeks later' situation actually occur, and how often) and
summarizes ADOPTION from the usage log.
"""
import os, sys, sqlite3, json, datetime, statistics, collections, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import search as core
DB = os.path.join(HERE, "..", "history.db")
USAGE = os.path.join(HERE, "..", "usage.jsonl")
random.seed(13)

def d(ts):
    try: return datetime.date.fromisoformat(ts[:10])
    except Exception: return None

con = sqlite3.connect(DB)

# one row per session: project + first/last activity
sess = {}
for s, p, mn, mx in con.execute(
    "SELECT sess, project, MIN(ts), MAX(ts) FROM messages GROUP BY sess"):
    sess[s] = (p, mn, mx)
total = len(sess)

# group sessions by project, ordered by start
byproj = collections.defaultdict(list)
for s,(p,mn,mx) in sess.items():
    if mn: byproj[p].append((mn, mx, s))
for p in byproj: byproj[p].sort()

# --- APPLICABILITY: reach-back ---
# For real questions you've actually asked, how OLD is the most-relevant prior conversation
# recall surfaces (searching only the past, excluding the question's own session)? Old hits =
# recovering genuinely-lost context = the value. Age 0 = just scrollback.
N = int(os.environ.get("RB_N", "40"))
cand = con.execute(
    "SELECT sess, ts, content FROM messages WHERE role='user' AND nchars BETWEEN 60 AND 400 AND ts!=''").fetchall()
random.shuffle(cand)
ages, found, samples = [], 0, []
tried = 0
for s, ts, content in cand:
    if found >= N: break
    tried += 1
    if tried > N*8: break
    hits = core.search(content, k=6, before_ts=ts)
    hits = [h for h in hits if h["sess"] != s]   # exclude self
    if not hits: continue
    qd, hd = d(ts), d(hits[0]["ts"])
    if not (qd and hd): continue
    age = (qd - hd).days
    ages.append(age); found += 1
    if len(samples) < 4 and age >= 5:
        samples.append((age, content[:70], hits[0]["snippet"][:70]))

multi = sum(1 for p,l in byproj.items() if len(l)>=3)
print("=== APPLICABILITY: reach-back on your real questions ===")
print(f"total sessions: {total:,} · projects with >=3 sessions (compounding history): {multi}")
if ages:
    a = sorted(ages)
    d7  = sum(1 for x in ages if x>=7)
    d3  = sum(1 for x in ages if x>=3)
    d0  = sum(1 for x in ages if x==0)
    print(f"\nfor {len(ages)} real past questions, age of the top relevant PRIOR conversation recall found:")
    print(f"   median {statistics.median(a)}d · p90 {a[int(len(a)*0.9)]}d · max {a[-1]}d")
    print(f"   same-day (≈scrollback):   {d0:,} ({d0/len(ages):.0%})")
    print(f"   reached back >=3 days:    {d3:,} ({d3/len(ages):.0%})")
    print(f"   reached back >=7 days:    {d7:,} ({d7/len(ages):.0%})   <- recovered genuinely-aged context")
    print("   (corpus is only ~2 months old, so >=7d is already a meaningful reach)")
    for age, q, h in samples:
        print(f"   · {age}d back · Q: {q!r}\n              ↳ {h!r}")

# --- ADOPTION (usage.jsonl) ---
print("\n=== ADOPTION (usage.jsonl — grows as you use it) ===")
ev = []
if os.path.exists(USAGE):
    for line in open(USAGE):
        try: ev.append(json.loads(line))
        except Exception: pass
searches = [e for e in ev if e.get("tool")=="search_history"]
getses   = [e for e in ev if e.get("tool")=="get_session"]
digests  = [e for e in ev if e.get("tool")=="digest_injected"]
if not ev:
    print("no usage yet — tools activate next session. Re-run after a week of real use.")
else:
    zero = sum(1 for s in searches if s.get("n_results",0)==0)
    print(f"searches: {len(searches)}   zero-result: {zero} ({(zero/len(searches) if searches else 0):.0%})")
    print(f"get_session follow-through: {len(getses)}  ({(len(getses)/len(searches) if searches else 0):.0%} of searches → opened a thread)")
    print(f"digest injections: {len(digests)}")

print("\n=== READ ===")
print("Useful IF: you return to prior work often (applicability above) AND retrieval finds it")
print("(measured 58% hit@10 / 22% grep-impossible) AND you actually invoke it (adoption above).")
print("Decision gate (from PRODUCT_PLAN): durable adoption + a get_session follow-through rate")
print(">0 + self-reported 'saved me a re-explain'. Re-run weekly; if adoption stays ~0, it's a")
print("feature you don't reach for — kill or fold into the SessionStart digest only.")
con.close()

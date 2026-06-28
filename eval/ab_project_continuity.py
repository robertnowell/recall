#!/usr/bin/env python3
"""A/B retrieval harness on your own corpus.
PUSH eval: for a sampled session in a multi-session project, take its opening user turn
as the query, retrieve as-of that timestamp, and ask: does retrieval surface EARLIER
sessions from the same project? Compares BM25 (FTS5) vs dense (OpenAI emb) vs hybrid (RRF).
Headline metric: how many relevant prior sessions dense finds that BM25 ranks nowhere.
"""
import os, sqlite3, re, random, collections
import numpy as np
from openai import OpenAI

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.db")
K = 10
RRF_K = 60
N_QUERIES = 80
MIN_SESS_PER_PROJECT = 5     # only projects with real multi-session history
random.seed(7)

con = sqlite3.connect(DB)
cur = con.cursor()
client = OpenAI()

# ---- load all embeddings into memory (brute force) ----
ids, vecs, meta = [], [], {}
rows = cur.execute("""SELECT m.id, m.sess, m.project, m.ts, m.content, e.vec
                      FROM messages m JOIN emb e ON e.chash=m.chash""").fetchall()
for mid, sess, project, ts, content, vec in rows:
    ids.append(mid)
    vecs.append(np.frombuffer(vec, dtype=np.float32))
    meta[mid] = (sess, project, ts, content)
ids = np.array(ids)
M = np.vstack(vecs)
M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
print(f"loaded {len(ids):,} embedded docs, dim={M.shape[1]}")

def embed_query(q):
    v = client.embeddings.create(model="text-embedding-3-small", input=[q[:8000] or " "]).data[0].embedding
    v = np.asarray(v, dtype=np.float32); return v/(np.linalg.norm(v)+1e-9)

def fts_query(text):
    toks = [t for t in re.findall(r"[a-zA-Z0-9_]{4,}", text.lower())]
    stop = {"that","this","with","from","have","what","your","just","like","they","them",
            "okay","please","should","would","could","there","their","about","which","when",
            "then","also","want","need","make","does","done","here","were","been","into"}
    toks = [t for t in toks if t not in stop][:25]
    return " OR ".join(dict.fromkeys(toks)) if toks else None

def bm25_search(qtext, before_ts, k):
    q = fts_query(qtext)
    if not q: return []
    try:
        r = cur.execute("""SELECT m.id FROM fts JOIN messages m ON m.id=fts.rowid
                           WHERE fts MATCH ? AND m.ts < ? ORDER BY bm25(fts) LIMIT ?""",
                        (q, before_ts, k)).fetchall()
        return [x[0] for x in r]
    except Exception:
        return []

def dense_search(qvec, before_ts, k):
    mask = np.array([meta[i][2] < before_ts for i in ids])
    sims = M @ qvec
    sims = np.where(mask, sims, -1e9)
    top = np.argpartition(-sims, range(min(k, len(sims))))[:k]
    top = top[np.argsort(-sims[top])]
    return [int(ids[t]) for t in top if sims[t] > -1e8]

def rrf(lists, k):
    score = collections.defaultdict(float)
    for lst in lists:
        for rank, mid in enumerate(lst):
            score[mid] += 1.0 / (RRF_K + rank + 1)
    return [mid for mid, _ in sorted(score.items(), key=lambda x: -x[1])[:k]]

# ---- build push queries: opening user turn of a session, gold = earlier same-project sessions ----
proj_sessions = collections.defaultdict(set)
for mid in ids:
    sess, project, ts, _ = meta[mid]
    proj_sessions[project].add(sess)
big = [p for p, s in proj_sessions.items() if len(s) >= MIN_SESS_PER_PROJECT]

# opening user turn per session (earliest user message)
opening = {}
for sess, ts, content, mid, project, role in cur.execute(
        "SELECT sess, ts, content, id, project, role FROM messages WHERE role='user' ORDER BY ts"):
    if sess not in opening and len(content) > 30:
        opening[sess] = (ts, content, project)

cands = [(s, *opening[s]) for s in opening if opening[s][2] in big]
random.shuffle(cands)

results = {"bm25": [], "dense": [], "hybrid": []}
dense_only_finds = 0
bm25_only_finds = 0
evaluated = 0
for sess, ts, qtext, project in cands:
    if evaluated >= N_QUERIES: break
    # gold = sessions in same project with activity before ts (excluding self)
    gold = set()
    for mid in ids:
        s2, p2, ts2, _ = meta[mid]
        if p2 == project and s2 != sess and ts2 < ts:
            gold.add(s2)
    if not gold:    # nothing earlier to find; skip
        continue
    evaluated += 1
    qvec = embed_query(qtext)
    b = bm25_search(qtext, ts, 50)
    d = dense_search(qvec, ts, 50)
    h = rrf([b, d], 50)
    def sess_hits(idlist):
        seen=[];
        for mid in idlist:
            s=meta[mid][0]
            if s not in seen: seen.append(s)
        return seen
    bs, ds, hs = sess_hits(b)[:K], sess_hits(d)[:K], sess_hits(h)[:K]
    def recall(hits): return len(set(hits) & gold) / len(gold)
    def mrr(hits):
        for r,s in enumerate(hits):
            if s in gold: return 1.0/(r+1)
        return 0.0
    results["bm25"].append((recall(bs), mrr(bs)))
    results["dense"].append((recall(ds), mrr(ds)))
    results["hybrid"].append((recall(hs), mrr(hs)))
    dense_only_finds += len((set(ds) & gold) - set(bs))
    bm25_only_finds  += len((set(bs) & gold) - set(ds))

print(f"\nevaluated {evaluated} push queries (projects w/ >={MIN_SESS_PER_PROJECT} sessions)\n")
print(f"{'method':<8}{'recall@'+str(K):>12}{'MRR@'+str(K):>10}")
for m in ("bm25","dense","hybrid"):
    arr = np.array(results[m]);
    print(f"{m:<8}{arr[:,0].mean():>12.3f}{arr[:,1].mean():>10.3f}")
print(f"\nrelevant prior sessions found by DENSE but missed by BM25 (top-10): {dense_only_finds}")
print(f"relevant prior sessions found by BM25 but missed by DENSE (top-10): {bm25_only_finds}")
print("\n^ the first number is the eager-surfacing value proposition; the second is what you'd lose going dense-only.")
con.close()

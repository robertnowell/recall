#!/usr/bin/env python3
"""HARD eval — paraphrased known-item search (the real 'I forgot the keywords' case).
For N sampled sessions: an LLM writes a fuzzy 'weeks later' recall query that AVOIDS the
session's distinctive nouns/filenames/code. Gold = that one session. Retrieve over the whole
corpus; does the gold session land in top-10? Single gold => clean recall/MRR.
Headline: queries where DENSE finds the session but BM25 returns it nowhere (grep-impossible)."""
import os, sqlite3, re, random, collections, json
import numpy as np
from openai import OpenAI

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.db")
K = 10
RRF_K = 60
N = 50
random.seed(11)
con = sqlite3.connect(DB); cur = con.cursor()
client = OpenAI()

# load embeddings
ids, vecs, meta = [], [], {}
for mid, sess, project, ts, content, vec in cur.execute(
        "SELECT m.id,m.sess,m.project,m.ts,m.content,e.vec FROM messages m JOIN emb e ON e.chash=m.chash"):
    ids.append(mid); vecs.append(np.frombuffer(vec, dtype=np.float32)); meta[mid]=(sess,project,ts,content)
ids=np.array(ids); M=np.vstack(vecs); M/= (np.linalg.norm(M,axis=1,keepdims=True)+1e-9)
sess_of = {int(i):meta[int(i)][0] for i in ids}

# pick sessions with enough substance (>=3 user turns, decent length)
sess_user = collections.defaultdict(list)
for sess, content in cur.execute("SELECT sess, content FROM messages WHERE role='user'"):
    sess_user[sess].append(content)
good = [s for s,c in sess_user.items() if len(c)>=3 and sum(len(x) for x in c)>400]
random.shuffle(good)

def embed_q(q):
    v=client.embeddings.create(model="text-embedding-3-small",input=[q[:8000] or " "]).data[0].embedding
    v=np.asarray(v,dtype=np.float32); return v/(np.linalg.norm(v)+1e-9)
def fts_q(text):
    stop={"that","this","with","from","have","what","your","just","like","they","them","find",
          "okay","please","should","would","could","there","their","about","which","when","where",
          "then","also","want","need","make","does","done","here","were","been","into","conversation","session","discuss","talked"}
    toks=[t for t in re.findall(r"[a-zA-Z0-9_]{4,}",text.lower()) if t not in stop][:20]
    return " OR ".join(dict.fromkeys(toks)) if toks else None
def bm25(qtext,k):
    q=fts_q(qtext)
    if not q: return []
    try:
        r=cur.execute("SELECT m.id FROM fts JOIN messages m ON m.id=fts.rowid WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",(q,k*8)).fetchall()
        return [x[0] for x in r]
    except Exception: return []
def dense(qv,k):
    sims=M@qv; top=np.argpartition(-sims,range(k*8))[:k*8]; top=top[np.argsort(-sims[top])]
    return [int(ids[t]) for t in top]
def to_sessions(idlist,k):
    seen=[]
    for mid in idlist:
        s=sess_of[mid]
        if s not in seen: seen.append(s)
        if len(seen)>=k: break
    return seen
def rrf(a,b,k):
    sc=collections.defaultdict(float)
    for lst in (a,b):
        for r,mid in enumerate(lst): sc[mid]+=1.0/(RRF_K+r+1)
    return [m for m,_ in sorted(sc.items(),key=lambda x:-x[1])]

GEN = ("You are given an excerpt from a past chat conversation. Write ONE natural question the "
       "user might ask WEEKS LATER to re-find this conversation from memory — capturing the gist/topic, "
       "but DELIBERATELY AVOID any distinctive proper nouns, product names, file names, code identifiers, "
       "or jargon that appear verbatim in the excerpt. Use everyday paraphrase. Output only the question.")

hit={"bm25":0,"dense":0,"hybrid":0}; mrr={"bm25":0.0,"dense":0.0,"hybrid":0.0}
dense_only=0; bm25_only=0; both_miss=0; evald=0; examples=[]
for sess in good:
    if evald>=N: break
    excerpt=" \n".join(sess_user[sess])[:2500]
    try:
        q=client.chat.completions.create(model="gpt-4o-mini",temperature=0.4,
            messages=[{"role":"system","content":GEN},{"role":"user","content":excerpt}]).choices[0].message.content.strip()
    except Exception as e:
        continue
    evald+=1
    qv=embed_q(q)
    bs=to_sessions(bm25(q,50),K); ds=to_sessions(dense(qv,50),K); hs=to_sessions(rrf(bm25(q,50),dense(qv,50),K),K)
    def score(hits,name):
        if sess in hits:
            hit[name]+=1; mrr[name]+=1.0/(hits.index(sess)+1)
    score(bs,"bm25"); score(ds,"dense"); score(hs,"hybrid")
    d_in=sess in ds; b_in=sess in bs
    if d_in and not b_in: dense_only+=1
    if b_in and not d_in: bm25_only+=1
    if not d_in and not b_in: both_miss+=1
    if len(examples)<6 and (d_in!=b_in):
        examples.append((q[:120], "DENSE✓ bm25✗" if d_in else "bm25✓ dense✗"))

print(f"\nevaluated {evald} paraphrased known-item queries (single gold session each)\n")
print(f"{'method':<8}{'hit@'+str(K):>10}{'MRR@'+str(K):>10}")
for m in ("bm25","dense","hybrid"):
    print(f"{m:<8}{hit[m]/evald:>10.2%}{mrr[m]/evald:>10.3f}")
print(f"\ngold session found by DENSE but NOT BM25 (grep-impossible recoveries): {dense_only}/{evald}")
print(f"gold session found by BM25 but NOT DENSE:                              {bm25_only}/{evald}")
print(f"missed by BOTH:                                                        {both_miss}/{evald}")
print("\nexample divergences:")
for q,who in examples: print(f"  [{who}] {q}")
con.close()

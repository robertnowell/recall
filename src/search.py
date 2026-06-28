#!/usr/bin/env python3
"""recall — hybrid search core (BM25 + dense + RRF) over indexed conversation history.
This is the single retrieval function the MCP server and the SessionStart hook both call.
CLI: python src/search.py "how did we handle klaviyo rate limits"
"""
import os, sys, re, sqlite3, collections, functools
import numpy as np
from openai import OpenAI

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.db")
EMB_MODEL = "text-embedding-3-small"
RRF_K = 60
STOP = {"that","this","with","from","have","what","your","just","like","they","them","find",
        "okay","please","should","would","could","there","their","about","which","when","where",
        "then","also","want","need","make","does","done","here","were","been","into","conversation",
        "session","discuss","talked","the","and","for","was","how","did","␄"}

@functools.lru_cache(maxsize=1)
def _load():
    con = sqlite3.connect(DB)
    ids, vecs, meta = [], [], {}
    for mid, sess, project, ts, content, vec in con.execute(
        "SELECT m.id,m.sess,m.project,m.ts,m.content,e.vec FROM messages m JOIN emb e ON e.chash=m.chash"):
        ids.append(mid); vecs.append(np.frombuffer(vec, dtype=np.float32))
        meta[mid] = (sess, project, ts, content)
    M = np.vstack(vecs); M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    return con, np.array(ids), M, meta

def _ensure_key():
    """Use OPENAI_API_KEY from env; if absent (e.g. host didn't pass env to the MCP server),
    fall back to reading it from ~/.zshrc so the secret stays in one place."""
    if os.environ.get("OPENAI_API_KEY"):
        return True
    try:
        with open(os.path.expanduser("~/.zshrc")) as fh:
            m = re.search(r'export\s+OPENAI_API_KEY=["\']?([^"\'\s]+)', fh.read())
        if m:
            os.environ["OPENAI_API_KEY"] = m.group(1); return True
    except Exception:
        pass
    return False

def _embed(q):
    _ensure_key()
    v = OpenAI().embeddings.create(model=EMB_MODEL, input=[q[:8000] or " "]).data[0].embedding
    v = np.asarray(v, dtype=np.float32); return v / (np.linalg.norm(v) + 1e-9)

def _fts_query(text):
    toks = [t for t in re.findall(r"[a-zA-Z0-9_]{3,}", text.lower()) if t not in STOP][:20]
    return " OR ".join(dict.fromkeys(toks)) if toks else None

def _bm25(con, qtext, before_ts, k):
    q = _fts_query(qtext)
    if not q: return []
    clause = " AND m.ts < ?" if before_ts else ""
    args = (q, before_ts, k) if before_ts else (q, k)
    try:
        return [r[0] for r in con.execute(
            f"SELECT m.id FROM fts JOIN messages m ON m.id=fts.rowid WHERE fts MATCH ?{clause} ORDER BY bm25(fts) LIMIT ?", args)]
    except Exception:
        return []

def _dense(ids, M, meta, qvec, before_ts, k):
    sims = M @ qvec
    if before_ts:
        mask = np.array([meta[int(i)][2] < before_ts for i in ids])
        sims = np.where(mask, sims, -1e9)
    top = np.argpartition(-sims, range(min(k, len(sims))))[:k]
    top = top[np.argsort(-sims[top])]
    return [int(ids[t]) for t in top if sims[t] > -1e8]

def search(query, k=8, mode="hybrid", before_ts=None, per_session=1):
    """Return ranked hits grouped to one row per session: [{sess,project,ts,score,snippet}]."""
    con, ids, M, meta = _load()
    pool = max(k * 6, 50)
    bm = _bm25(con, query, before_ts, pool) if mode in ("hybrid", "bm25") else []
    dn = []
    if mode in ("hybrid", "dense"):
        try:
            dn = _dense(ids, M, meta, _embed(query), before_ts, pool)
        except Exception:
            # no API key / embedding failure → degrade to keyword-only rather than erroring
            if mode == "dense":
                bm = _bm25(con, query, before_ts, pool)
            mode = "bm25"
    if mode == "hybrid":
        sc = collections.defaultdict(float)
        for lst in (bm, dn):
            for r, mid in enumerate(lst): sc[mid] += 1.0 / (RRF_K + r + 1)
        ranked = [m for m, _ in sorted(sc.items(), key=lambda x: -x[1])]
    else:
        ranked = bm or dn
    out, seen = [], collections.Counter()
    for mid in ranked:
        sess, project, ts, content = meta[mid]
        if seen[sess] >= per_session: continue
        seen[sess] += 1
        snippet = re.sub(r"\s+", " ", content).strip()[:240]
        out.append({"sess": sess, "project": project, "ts": ts, "snippet": snippet})
        if len(out) >= k: break
    return out

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "what did we decide about evals"
    for i, h in enumerate(search(q), 1):
        print(f"{i}. [{h['ts'][:10]}] {h['project']}\n   {h['snippet']}\n   sess={h['sess']}")

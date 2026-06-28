#!/usr/bin/env python3
"""recall daemon — always-warm local HTTP search so the per-message hook is sub-second.
Holds the embedding matrix in memory; the UserPromptSubmit hook hits /search instead of
cold-loading 363MB every turn. Binds 127.0.0.1 only (never exposed off-box).

  GET /search?q=<text>&k=3&exclude=<sess>   -> {"top_score":float,"hits":[{sess,project,ts,snippet,score}]}
  GET /health                               -> {"ok":true,"docs":N}
"""
import os, sys, json, re, collections
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import search as core

HOST, PORT = "127.0.0.1", int(os.environ.get("RECALL_PORT", "8787"))
RRF_K = 60
print("loading embeddings…", flush=True)
_con, _ids, _M, _meta = core._load()
print(f"ready: {_M.shape[0]:,} docs, dim {_M.shape[1]}", flush=True)

def _search(q, k, exclude):
    qv = core._embed(q)
    sims = _M @ qv                         # cosine (rows are L2-normalized)
    pool = max(k * 8, 60)
    dtop = np.argpartition(-sims, range(min(pool, len(sims))))[:pool]
    dtop = dtop[np.argsort(-sims[dtop])]
    dense = [int(_ids[t]) for t in dtop]
    bm = core._bm25(_con, q, None, pool)
    sc = collections.defaultdict(float)
    for lst in (bm, dense):
        for r, mid in enumerate(lst):
            sc[mid] += 1.0 / (RRF_K + r + 1)
    ranked = sorted(sc, key=lambda m: -sc[m])
    cos = {int(_ids[i]): float(sims[i]) for i in dtop}
    out, seen = [], set()
    for mid in ranked:
        s, p, ts, content = _meta[mid]
        if s == exclude or s in seen:
            continue
        seen.add(s)
        out.append({"sess": s, "project": p, "ts": ts,
                    "snippet": re.sub(r"\s+", " ", content).strip()[:200],
                    "score": round(cos.get(mid, 0.0), 4)})
        if len(out) >= k:
            break
    return {"top_score": out[0]["score"] if out else 0.0, "hits": out}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass          # quiet
    def do_GET(self):
        u = urlparse(self.path); qs = parse_qs(u.query)
        try:
            if u.path == "/health":
                body = {"ok": True, "docs": int(_M.shape[0])}
            elif u.path == "/search":
                q = (qs.get("q", [""])[0]).strip()
                k = int(qs.get("k", ["3"])[0])
                exclude = qs.get("exclude", [""])[0]
                body = _search(q, k, exclude) if q else {"top_score": 0.0, "hits": []}
            else:
                self.send_response(404); self.end_headers(); return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
        except Exception as e:
            self.send_response(500); self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()

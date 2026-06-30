#!/usr/bin/env python3
"""recall daemon — always-warm local HTTP search so the per-message hook is sub-second.
Returns THREE labeled match modalities so the injection can show provenance:
  semantic_match (embedding cosine) · grep_match (exact keyword) · topic_match (session title)
Binds 127.0.0.1 only.

  GET /search?q=<text>&exclude=<sess>  -> {"sem_top":float,
        "semantic":[{sess,project,ts,text,score}], "grep":[...], "topic":[{...,title}]}
  GET /health -> {"ok":true,"docs":N,"titles":M}
"""
import os, sys, json, re, collections
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import search as core

HOST, PORT = "127.0.0.1", int(os.environ.get("RECALL_PORT", "8787"))
STOP = core.STOP
print("loading…", flush=True)
_con, _ids, _M, _meta = core._load()
# per-session: project + latest ts (for labeling topic/grep hits)
_sess = {}
for mid, (s, p, ts, _c) in _meta.items():
    if s not in _sess or ts > _sess[s][1]:
        _sess[s] = (p, ts)
# titles (topic modality)
_titles = {}
try:
    for s, t in _con.execute("SELECT sess, title FROM titles"):
        _titles[s] = t
except Exception:
    pass
print(f"ready: {_M.shape[0]:,} docs, {len(_titles)} titles", flush=True)

def _toks(s):
    return {t for t in re.findall(r"[a-z0-9]{3,}", s.lower()) if t not in STOP}

def _snip(mid):
    return re.sub(r"\s+", " ", _meta[mid][3]).strip()[:200]

def _search(q, exclude, per=2):
    qv = core._embed(q)
    sims = _M @ qv
    pool = 80
    dtop = np.argpartition(-sims, range(min(pool, len(sims))))[:pool]
    dtop = dtop[np.argsort(-sims[dtop])]
    cos = {int(_ids[i]): float(sims[i]) for i in dtop}
    # semantic
    semantic, seen = [], set()
    for i in dtop:
        mid = int(_ids[i]); s = _meta[mid][0]
        if s == exclude or s in seen: continue
        seen.add(s)
        semantic.append({"sess": s, "project": _meta[mid][1], "ts": _meta[mid][2],
                         "text": _snip(mid), "score": round(cos[mid], 4)})
        if len(semantic) >= per: break
    sem_top = semantic[0]["score"] if semantic else 0.0
    # grep (BM25 exact-term)
    grep, seen = [], set()
    for mid in core._bm25(_con, q, None, pool):
        s = _meta[mid][0]
        if s == exclude or s in seen: continue
        seen.add(s)
        grep.append({"sess": s, "project": _meta[mid][1], "ts": _meta[mid][2],
                     "text": _snip(mid), "score": round(cos.get(mid, 0.0), 4)})
        if len(grep) >= per: break
    # topic (session-title overlap)
    qt = _toks(q)
    scored = []
    if qt:
        for s, title in _titles.items():
            if s == exclude or s not in _sess: continue
            ov = qt & _toks(title)
            if ov:
                scored.append((len(ov), s, title))
        scored.sort(reverse=True)
    topic = [{"sess": s, "project": _sess[s][0], "ts": _sess[s][1], "title": title,
              "text": title, "score": n} for n, s, title in scored[:per]]

    # ---- RRF fusion across all three modalities (shared strength metric) ----
    K = 60
    agg = {}
    def fuse(items, tname):
        for rank, it in enumerate(items):
            s = it["sess"]
            a = agg.setdefault(s, {"sess": s, "project": it["project"], "ts": it["ts"],
                                   "types": [], "rrf": 0.0, "scores": {}, "texts": {}})
            a["rrf"] += 1.0 / (K + rank + 1)
            if tname not in a["types"]: a["types"].append(tname)
            a["scores"][tname] = it.get("score")
            a["texts"][tname] = it.get("text")
    fuse(topic, "topic_match"); fuse(semantic, "semantic_match"); fuse(grep, "grep_match")
    matches = []
    for a in agg.values():
        # display text: prefer the legible title, else the semantic passage, else the grep passage
        txt = a["texts"].get("topic_match") or a["texts"].get("semantic_match") or a["texts"].get("grep_match")
        matches.append({"sess": a["sess"], "project": a["project"], "ts": a["ts"],
                        "types": a["types"], "rrf": round(a["rrf"], 5),
                        "scores": a["scores"], "text": txt})
    matches.sort(key=lambda x: -x["rrf"])
    return {"sem_top": sem_top, "top_score": sem_top, "matches": matches,
            "semantic": semantic, "grep": grep, "topic": topic}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urlparse(self.path); qs = parse_qs(u.query)
        try:
            if u.path == "/health":
                body = {"ok": True, "docs": int(_M.shape[0]), "titles": len(_titles)}
            elif u.path == "/search":
                q = (qs.get("q", [""])[0]).strip()
                body = _search(q, qs.get("exclude", [""])[0]) if q else {"sem_top": 0.0, "semantic": [], "grep": [], "topic": []}
            else:
                self.send_response(404); self.end_headers(); return
            data = json.dumps(body).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500); self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()

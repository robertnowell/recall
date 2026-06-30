#!/usr/bin/env python3
"""Render recall activity (usage.jsonl) as a self-contained HTML report and open it.
The visible 'you judge it' eval surface, but readable. Writes usage_report.html (gitignored:
contains your prompts) and opens it in the browser.
"""
import os, sys, json, collections, html, subprocess, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
USAGE = os.path.join(ROOT, "..", "usage.jsonl")
OUT = os.path.join(ROOT, "..", "usage_report.html")

ev = []
if os.path.exists(USAGE):
    for line in open(USAGE):
        try: ev.append(json.loads(line))
        except Exception: pass

eager  = [e for e in ev if e.get("tool") == "eager_inject"]
pulls  = [e for e in ev if e.get("tool") == "search_history"]
digest = [e for e in ev if e.get("tool") == "digest_injected"]
rich   = [e for e in eager if "prompt" in e]
thin   = len(eager) - len(rich)

byday = collections.defaultdict(lambda: collections.Counter())
for e in ev:
    byday[e.get("ts","")[:10]][e.get("tool")] += 1

def score_color(s):
    if s is None: return "#7a7a72"
    if s >= 0.70: return "#3a7afe"     # strong (IKB-ish)
    if s >= 0.60: return "#5bc0a8"     # decent
    return "#d8a13a"                   # marginal (amber)

def esc(t): return html.escape(t or "")

rows = []
for e in reversed(rich):
    sc = e.get("top_score")
    surfaced = "".join(
        f'<li><span class="sc" style="color:{score_color(h.get("score"))}">{(h.get("score") or 0):.2f}</span>'
        f'<span class="proj">{esc(h["project"].replace("-Users-robertnowell-Projects-","").replace("-Users-robertnowell","(home)"))}</span>'
        f'<span class="snip">{esc(h.get("snippet",""))}</span></li>'
        for h in e.get("surfaced", []))
    rows.append(f'''<div class="fire">
      <div class="meta"><span class="ts">{esc(e.get("ts","")[:16])}</span>
      <span class="top" style="color:{score_color(sc)}">top {sc:.2f}</span></div>
      <div class="prompt">{esc(e.get("prompt",""))}</div>
      <ul class="surf">{surfaced}</ul></div>''')

daygrid = "".join(
    f'<tr><td>{esc(d)}</td><td>{byday[d]["eager_inject"]}</td><td>{byday[d]["digest_injected"]}</td><td>{byday[d]["search_history"]}</td></tr>'
    for d in sorted(byday) if d)

span = f'{eager[0]["ts"][:16]} → {eager[-1]["ts"][:16]}' if eager else "—"
note = f'<p class="note">{thin} older fires logged before rich logging (no prompt/snippet captured) — not shown.</p>' if thin else ""

doc = f'''<!doctype html><html><head><meta charset="utf-8"><title>recall · activity</title>
<style>
:root{{--bg:#16161a;--panel:#1e1e24;--ink:#e8e4d8;--dim:#8a8a82;--line:#2c2c34;--ikb:#3a7afe}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 "Berkeley Mono","SF Mono",ui-monospace,Menlo,monospace;padding:40px;max-width:1000px;margin:auto}}
h1{{font-size:18px;letter-spacing:.04em;margin:0 0 4px}} .sub{{color:var(--dim);margin:0 0 24px}}
.stats{{display:flex;gap:28px;margin:0 0 24px;flex-wrap:wrap}}
.stat .n{{font-size:26px;color:var(--ikb)}} .stat .l{{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.08em}}
.ratio{{color:#d8a13a}}
table{{border-collapse:collapse;margin:0 0 28px;width:100%;max-width:420px}}
td,th{{border:1px solid var(--line);padding:5px 12px;text-align:left}} th{{color:var(--dim);font-weight:400;font-size:12px}}
.fire{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:0 0 12px}}
.meta{{display:flex;justify-content:space-between;font-size:12px;color:var(--dim);margin-bottom:6px}}
.prompt{{color:var(--ink);margin:0 0 10px;font-weight:500}}
.prompt:before{{content:"› ";color:var(--ikb)}}
.surf{{list-style:none;margin:0;padding:0}}
.surf li{{display:flex;gap:10px;padding:3px 0;border-top:1px solid var(--line);font-size:13px;align-items:baseline}}
.sc{{flex:0 0 38px;font-weight:600}} .proj{{flex:0 0 64px;color:var(--dim)}} .snip{{color:#cfcabb}}
.note{{color:var(--dim);font-size:12px}} .legend{{color:var(--dim);font-size:12px;margin:18px 0 0}}
.legend b{{color:#3a7afe}} .legend i{{color:#d8a13a;font-style:normal}}
</style></head><body>
<h1>recall · activity</h1>
<p class="sub">{span}</p>
<div class="stats">
  <div class="stat"><div class="n">{len(eager)}</div><div class="l">eager fires</div></div>
  <div class="stat"><div class="n">{len(digest)}</div><div class="l">digests</div></div>
  <div class="stat"><div class="n">{len(pulls)}</div><div class="l">tool pulls</div></div>
  <div class="stat"><div class="n ratio">{len(eager)}→{len(pulls)}</div><div class="l">fire→pull</div></div>
</div>
<table><tr><th>day</th><th>eager</th><th>digest</th><th>pull</th></tr>{daygrid}</table>
{note}
<h1>recent fires <span style="color:var(--dim);font-weight:400">— what it surfaced, you judge</span></h1>
<p class="legend">score: <b>≥0.70 strong</b> · <span style="color:#5bc0a8">≥0.60 decent</span> · <i>0.55–0.60 marginal</i></p>
{''.join(rows) or '<p class="note">no rich fires logged yet — use it in a fresh session and refresh.</p>'}
</body></html>'''

open(OUT, "w").write(doc)
print(f"wrote {OUT}")
subprocess.run(["open", OUT], check=False)

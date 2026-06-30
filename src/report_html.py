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
shown   = [e for e in eager if e.get("injected")]   # only the labeled-provenance format
omitted = len(eager) - len(shown)                   # legacy pre-redesign fires (unlabeled)

byday = collections.defaultdict(lambda: collections.Counter())
for e in ev:
    byday[e.get("ts","")[:10]][e.get("tool")] += 1

def score_color(s):
    if s is None: return "#7a7a72"
    if s >= 0.70: return "#3a7afe"     # strong (IKB-ish)
    if s >= 0.60: return "#5bc0a8"     # decent
    return "#d8a13a"                   # marginal (amber)

def esc(t): return html.escape(t or "")

def type_color(line):
    if 'type="topic_match"' in line: return "#3a7afe"
    if 'type="semantic_match"' in line: return "#5bc0a8"
    if 'type="grep_match"' in line: return "#d8a13a"
    return "#cfcabb"

rows = []
for e in reversed(shown):
    sc = e.get("sem_top", e.get("top_score"))
    surfaced = "".join(
        f'<li><span class="snip" style="color:{type_color(ln)}">{esc(ln)}</span></li>'
        for ln in e["injected"].splitlines())
    topline = f'<span class="top" style="color:{score_color(sc)}">top semantic {sc:.2f}</span>' if sc else ''
    rows.append(f'''<div class="fire">
      <div class="meta"><span class="ts">{esc(e.get("ts","")[:16])}</span>{topline}</div>
      <div class="q-label">your prompt</div>
      <div class="prompt">{esc(e.get("prompt",""))}</div>
      <div class="s-label">surfaced past sessions (tagged by how each matched)</div>
      <ul class="surf">{surfaced}</ul></div>''')

daygrid = "".join(
    f'<tr><td>{esc(d)}</td><td>{byday[d]["eager_inject"]}</td><td>{byday[d]["digest_injected"]}</td><td>{byday[d]["search_history"]}</td></tr>'
    for d in sorted(byday) if d)

span = f'{eager[0]["ts"][:16]} → {eager[-1]["ts"][:16]}' if eager else "—"
note = f'<p class="note">{omitted} earlier fires hidden — they were logged before the labeled-provenance redesign (bare fragments, no match types). Shown below: the {len(shown)} fires logged in the new format.</p>' if omitted else ""

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
.q-label,.s-label{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--dim);margin:0 0 2px}}
.s-label{{margin-top:8px}}
.surf{{list-style:none;margin:2px 0 0;padding:0}}
.surf li{{padding:3px 0;border-top:1px solid var(--line);font-size:13px}}
.snip{{color:#cfcabb}}
.intro{{color:var(--dim);font-size:13px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:0 0 20px}}
.note{{color:var(--dim);font-size:12px}} .legend{{color:var(--dim);font-size:12px;margin:14px 0 16px}}
.legend b{{color:#3a7afe}} .legend i{{color:#d8a13a;font-style:normal}} .legend em{{color:#5bc0a8;font-style:normal}}
</style></head><body>
<h1>recall · activity</h1>
<p class="sub">{span}</p>
<div class="intro"><b>What this shows:</b> every time you sent a prompt and recall auto-injected
relevant past sessions into Claude's context (a "fire"). Each fire = your prompt + the past
sessions it surfaced, tagged by <b>how</b> each one matched.</div>
<div class="stats">
  <div class="stat"><div class="n">{len(eager)}</div><div class="l">eager fires</div></div>
  <div class="stat"><div class="n">{len(digest)}</div><div class="l">digests</div></div>
  <div class="stat"><div class="n">{len(pulls)}</div><div class="l">tool pulls</div></div>
  <div class="stat"><div class="n ratio">{len(eager)}→{len(pulls)}</div><div class="l">fire→pull</div></div>
</div>
<table><tr><th>day</th><th>eager</th><th>digest</th><th>pull</th></tr>{daygrid}</table>
{note}
<h1>recent fires <span style="color:var(--dim);font-weight:400">— what it surfaced, you judge</span></h1>
<p class="legend">match type: <b>topic_match</b> = session's title · <em>semantic_match</em> = meaning/embedding · <i>grep_match</i> = exact keyword</p>
{''.join(rows) or '<p class="note">no fires in the new labeled format yet — use recall in a fresh session, then re-run this report.</p>'}
</body></html>'''

open(OUT, "w").write(doc)
print(f"wrote {OUT}")
subprocess.run(["open", OUT], check=False)

#!/usr/bin/env python3
"""Mine 'push' ground-truth candidates: user messages that reference prior context
('that report', 'we discussed', 'last time'...). Each is a labeled instance of
needed-but-not-surfaced context — the answer being whichever earlier session it refers to."""
import os, sqlite3, re, collections

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.db")
con = sqlite3.connect(DB)
cur = con.cursor()

# back-reference cue phrases (lowercased substring match on user turns)
CUES = [
    "that report", "the report you", "we discussed", "we talked about", "last time",
    "earlier you", "previously", "remember when", "remember that", "the doc you",
    "that session", "we built", "the thing we", "the thing i", "as we discussed",
    "you found", "you mentioned", "from before", "a while ago", "few weeks ago",
    "couple weeks ago", "last week we", "the research you", "that analysis",
    "back to the", "pick up where", "continue the", "the plan we", "we were working on",
]

rows = cur.execute("SELECT id, sess, ts, content FROM messages WHERE role='user'").fetchall()
hits = []
cue_counts = collections.Counter()
for mid, sess, ts, content in rows:
    low = content.lower()
    matched = [c for c in CUES if c in low]
    if matched:
        # heuristic: short-ish prompts are likely genuine resumption asks, not pasted docs
        if len(content) <= 600:
            for c in matched:
                cue_counts[c] += 1
            hits.append((ts, sess, matched, content.strip().replace("\n", " ")))

print(f"user turns scanned:            {len(rows):,}")
print(f"turns with >=1 back-ref cue:   {len(hits):,}  (<=600 chars)")
print()
print("top cues:")
for c, n in cue_counts.most_common(15):
    print(f"  {n:>4}  {c}")
print()
print("=== 12 sample candidate 'push' queries ===")
for ts, sess, matched, content in hits[:12]:
    snippet = content[:160] + ("…" if len(content) > 160 else "")
    print(f"\n[{ts[:10]}] cues={matched}\n  {snippet}")
con.close()

#!/usr/bin/env python3
"""Dense-embed distinct message content with OpenAI text-embedding-3-small.
Content-hash cached: re-running only embeds new/changed content."""
import os, sqlite3, time, sys
import numpy as np
from openai import OpenAI

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.db")
MODEL = "text-embedding-3-small"   # 1536 dims, $0.02/1M tokens
DIM = 1536
MAXCHARS = 8000                    # truncate long turns (~2k tokens) before embed
BATCH = 64

con = sqlite3.connect(DB)
con.execute("CREATE TABLE IF NOT EXISTS emb(chash TEXT PRIMARY KEY, vec BLOB)")
con.commit()
client = OpenAI()

# distinct content not yet embedded
todo = con.execute("""SELECT DISTINCT m.chash, m.content FROM messages m
                      LEFT JOIN emb e ON e.chash=m.chash
                      WHERE e.chash IS NULL""").fetchall()
print(f"to embed: {len(todo):,} distinct messages")
if not todo:
    print("nothing to do."); sys.exit(0)

done = 0
t0 = time.time()
for i in range(0, len(todo), BATCH):
    chunk = todo[i:i+BATCH]
    inputs = [(c[:MAXCHARS] if len(c) > MAXCHARS else c) or " " for _, c in chunk]
    for attempt in range(5):
        try:
            resp = client.embeddings.create(model=MODEL, input=inputs)
            break
        except Exception as e:
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))
    rows = [(chash, np.asarray(d.embedding, dtype=np.float32).tobytes())
            for (chash, _), d in zip(chunk, resp.data)]
    con.executemany("INSERT OR REPLACE INTO emb(chash, vec) VALUES(?,?)", rows)
    con.commit()
    done += len(chunk)
    if done % 2048 < BATCH:
        rate = done / (time.time() - t0)
        eta = (len(todo) - done) / rate
        print(f"  {done:,}/{len(todo):,}  ({rate:.0f}/s, eta {eta:.0f}s)", flush=True)

n = con.execute("SELECT COUNT(*) FROM emb").fetchone()[0]
print(f"done. {n:,} embeddings stored. {time.time()-t0:.0f}s total.")
con.close()

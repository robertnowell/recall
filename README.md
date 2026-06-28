# recall

Hybrid semantic search over your own AI conversation history — find past threads by *meaning*, surface relevant ones before you ask, cross-tool via MCP, local-first.

**Why:** on a 62.5k-message personal corpus, semantic recall found the right past conversation **58% vs 40%** for keyword search, and recovered **22% of conversations keyword search structurally could not find**. Native AI memory is siloed and ephemeral (~2-month window observed); recall is durable and tool-agnostic.

See [`docs/PRODUCT_PLAN.md`](docs/PRODUCT_PLAN.md) for the full plan, architecture, and eval strategy.

## Layout
```
src/index.py      build/refresh the FTS5 lexical index from ~/.claude/projects JSONL
src/embed.py      dense-embed new content (OpenAI text-embedding-3-small), content-hash cached
src/search.py     hybrid search core (BM25 + dense + RRF) — CLI + the function MCP/hooks call
eval/             retrieval-quality A/B harnesses (the regression gate)
history.db        SQLite: messages + FTS5 + embeddings (gitignored)
```

## Quickstart
```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
export OPENAI_API_KEY=...                       # for embeddings
./.venv/bin/python src/index.py                 # build lexical index (~17s)
./.venv/bin/python src/embed.py                 # embed (one-time ~$0.47, cached after)
./.venv/bin/python src/search.py "that thing about klaviyo rate limits"
```

## Eval
```bash
./.venv/bin/python eval/ab_paraphrase_knownitem.py   # headline: hit@10, dense-only recoveries
./.venv/bin/python eval/ab_project_continuity.py     # complementarity sanity check
```

## Status — v0 complete
- ✅ index + embed + hybrid search core + eval gate (measured: dense 58% vs bm25 40%, 22% grep-impossible)
- ✅ MCP server (`src/mcp_server.py`) — registered in Claude Code, `search_history` + `get_session`, usage-logged
- ✅ incremental refresh (`src/refresh.py`) + nightly launchd (`com.recall.refresh`, 3:30am) + key-loading wrapper (`bin/refresh.sh`)
- ✅ per-project digests (`src/digest.py`) + SessionStart push hook (`hooks/session_start.py`, registered)
- ✅ usage logging → `usage.jsonl` (feeds the Layer-B utility eval)

**Next (post-v0, gated on usage data):** analyze `usage.jsonl` proxies (re-work-avoided, tool-usefulness); turn-type weighting + chunking quality pass; on/off + holdback eval; then — only on durable-utility + WTP signal — founder-pair shared index with a sensitive-data exclude list. See [`docs/PRODUCT_PLAN.md`](docs/PRODUCT_PLAN.md).

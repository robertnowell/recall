# recall — first product plan

*Status: draft v0 · 2026-06-28 · grounded in two deep-research passes (`~/Documents/deep-research/2026-06-28-rag-conversation-history-eval.md`, `…-cross-tool-team-ai-memory.md`) + a measured A/B on the author's own corpus.*

---

## 0. The one-sentence thesis

**recall makes your past AI conversations findable by meaning, surfaces the relevant ones before you have to ask, and works across every tool that speaks MCP — and you own the data.**

The measured justification (not borrowed from a vendor deck): on the author's own 62.5k-message history, semantic recall found the right past conversation **58% vs 40%** for keyword search, and recovered **22% of conversations that keyword search structurally could not find** (vocabulary mismatch — you remember the idea, not the words). That gap *is* the product.

---

## 1. Who it's for / the job

- **Primary user (v0):** a single power user with months of agent history (you), then a **founder pair** wanting shared context.
- **The job-to-be-done:** *"I worked through this before — with an AI — and I can't find it, or my AI doesn't know to look."* Two modes of that job:
  - **Pull:** "find the conversation where we decided X." (explicit)
  - **Push:** I open a fresh thread weeks later and the assistant *doesn't know* relevant prior context exists. (the high-value mode)
- **Why now / why it's defensible:** native memory is siloed per platform and ephemeral (the author's own history is effectively a ~2-month rolling window). recall is cross-tool (MCP) and durable (you keep the archive).

---

## 2. v0 scope — optimally simple

**In:**
1. **Local index** of your own session history — SQLite FTS5 (lexical) + brute-force dense vectors (numpy). No vector DB. (built)
2. **Hybrid search core** — BM25 + dense + RRF, one function. (built: `src/search.py`)
3. **Incremental indexing** — content-hash cached; re-index only new/changed sessions. (built into `index.py`/`embed.py`; needs a scheduler)
4. **Pull surface: an MCP server** exposing one tool — `search_history(query, k)` — so it works in Claude Code, Claude Desktop, Cursor, Windsurf, VS Code. This is the cross-tool story.
5. **Push surface: a SessionStart digest** — a *cheap, precomputed* injection of "recent threads + most-relevant-to-cwd" so the assistant starts warm.

**Deliberately OUT of v0 (do later, only if eval justifies):**
- No reranker (58% is the floor; add a local cross-encoder only if eval shows headroom).
- No vector DB / no server infra (brute force is fine <100k chunks).
- No team/multi-user, no ACLs, no cloud sync.
- No knowledge-graph / fact-distillation (Mem0/Zep territory — unproven ROI for this job).
- No ChatGPT/Gemini consumer support (they don't accept third-party MCP memory servers).

**The discipline:** every feature past v0 must be pulled forward by a measured gap, not a hunch. The research's clearest finding is that the whole industry ships memory without proving it's useful — recall's edge is that it won't.

---

## 3. Architecture — the proven pattern

The flagship pattern (ChatGPT, Claude) is **write-time precompute → cheap read-time injection**, *not* read-time vector RAG on the critical path. recall copies it:

```
                WRITE TIME (async, off critical path)          READ TIME (cheap)
  sessions  →  index.py (FTS5) + embed.py (vectors)  →  history.db
   JSONL         + digest.py (per-project summaries)        │
                 [cron / SessionEnd hook, nightly]          ├─ MCP server: search_history()   ← PULL
                                                            │     (server stays warm; sub-second)
                                                            └─ SessionStart hook: inject digest ← PUSH
                                                                  (reads precomputed text; no ANN)
```

**Latency rules (from the research):**
- **Never embed/ANN inside `UserPromptSubmit`** — it's synchronous, blocks the turn, 30s timeout. (Claude Code docs.)
- The MCP `search_history` tool is *pull* — the model calls it when it wants, latency is acceptable and the server is warm (embeddings preloaded once).
- The *push* digest is precomputed text injected at `SessionStart` — zero ANN at turn time. Vector search itself is <10ms even at scale; the thing to avoid is the cold-load (9s for 363MB) and the per-query embedding call on the critical path.

**Quality levers identified (v0.x):**
- Weight **user turns + main-thread assistant conclusions** above subagent boilerplate (current results over-surface "I'll research…" agent turns).
- Per-turn chunking is the floor; try per-decision / per-section chunking for better hit rate.

---

## 4. How it's useful, concretely

| Surface | Trigger | What the user feels |
|---|---|---|
| `search_history` MCP tool | model or user asks to recall something | "it found the thread I half-remembered, in any tool" |
| SessionStart digest | opening a project | "it already knows what we were doing here" |
| durable archive | history ages off the ~2-month native window | "my context didn't evaporate" |
| (later) shared founder index | co-founder opens same project | "I didn't have to re-explain what you already figured out" |

---

## 5. How we eval — two layers (this is the moat)

### Layer A — Offline retrieval quality (regression gate, already built)
Run on every index change; gate releases.
- **`eval/ab_paraphrase_knownitem.py`** — the headline test: LLM writes a jargon-stripped "weeks later" query, measure hit@10 / MRR and **dense-only recoveries** (what grep can't find). Current baseline: **bm25 40% / dense 58% / hybrid 58%; dense recovers 22% grep-impossible.**
- **`eval/ab_project_continuity.py`** — easy/topical-continuity sanity check (complementarity: ~404 vs ~395 unique finds → keep hybrid, never go dense-only).
- **Pass bar:** hybrid hit@10 ≥ current baseline; dense-only-recovery ≥ 15%. A change that regresses either is rejected.

### Layer B — Online end-user utility (the "why would anyone care" test)
The research is blunt: the field has **no standardized utility eval** and short-term wow decays (GenAI gains → control in 3 weeks). So measure utility, not vibes:
- **Sensitive proxy metrics** (move fast, gate the experiment):
  - *re-work-avoided*: rate of "as I said before / let me re-explain" prompts (should fall).
  - *session-resumption*: % of new sessions that build on a surfaced prior thread.
  - *recall-tool usefulness*: % of `search_history` calls whose result is then referenced in the answer.
- **North Star (slow, confirming):** successful task-resolutions per active week; retention of the habit.
- **The on/off test:** alternate **digest-on / digest-off weeks** (single user) or split across the founder pair; compare proxies.
- **The "would you miss it" test:** a **holdback** — after it's habitual, silently disable for a week and measure complaint/▼proxy. If nothing changes, it's a feature, not a product.
- **Skeptic's gate before any productization:** durable (>3-week) lift on a proxy **+** a willingness-to-pay signal from 2–3 design-partner teams. No signal → it stays a personal tool.

---

## 6. Build sequence

1. **MCP server** wrapping `search_history` (warm-load embeddings once). → cross-tool pull works today.
2. **Scheduler** for incremental index+embed (launchd nightly, or a SessionEnd hook). → archive stays fresh, beats the retention window.
3. **`digest.py`** — precompute per-project "recent + salient" summaries; **SessionStart hook** injects them. → push mode.
4. **Instrument** the proxy metrics (log tool calls, digest hits) → Layer B starts collecting from day one.
5. **Quality pass** — turn-type weighting + chunking experiment; re-run Layer A.
6. **Only then**, if proxies hold: founder-pair shared index (with an explicit *sensitive-data exclude list* — see §7) and the productization eval gate.

---

## 7. Risks & boundaries (build these in before scaling past one user)

- **The sensitive-data boundary must be built, not assumed.** Before any sharing: an exclude list (paths/projects/keywords) so cap-table, HR, legal, secrets never enter a shared index. Scoping is "hard to restructure later" (Mem0) — decide `personal` vs `shared` at write time.
- **Oversharing** is the dominant team-scale failure (80% of audited Copilot tenants leaked). A shared index inherits whatever sloppy access already exists.
- **Memory poisoning / stale context**: a wrong distilled "fact" propagates to everyone. v0 mitigations: store *raw retrievable turns*, not asserted facts; show provenance (which session, when); no auto-distillation in v0.
- **Context rot**: more injected context can *lower* answer quality. Keep the digest small and selective; never dump.
- **Privacy posture is the differentiator** — local-first, you own the files. Don't repeat Rewind→Limitless's cloud/hardware pivot that betrayed its own privacy pitch.

---

## 8. Productization read (honest)

The personal/cross-tool memory layer is **crowded** (OpenMemory, Supermemory, Mem0, Zep, Letta, Cognee) and platform-native memory keeps absorbing it. The **one defensible white space is proactive team-context propagation** ("your co-founder already solved this") — a real gap, but also the hardest and riskiest (governance, poisoning). Recommendation: **build recall for yourselves, prove durable utility with §5, and let measured re-work-avoided + a design-partner WTP signal decide whether it becomes a product.** Don't invest ahead of that signal.

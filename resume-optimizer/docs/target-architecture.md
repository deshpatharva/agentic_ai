# Target Architecture — In-House Agentic Pipeline, Memory, Context Caching & Tiering

**Status:** Design decision record. Forward-looking (what we are building), distinct from `architecture-review.md` (audit of current state).
**Date:** 2026-06-15 · **Context:** pre-beta, mid-July beta target, single builder.
**Supersedes:** §5a of `architecture-review.md` (which recommended a *deterministic* loop — see "Decision summary" for why this evolved to a *native agentic* loop).

---

## Decision summary

| Decision | Choice |
|---|---|
| Agent framework | **None** — build agents in-house on `llm.py` + LiteLLM. No CrewAI/LangChain/LangGraph/AutoGen *yet*. |
| Standard tier (cheaper) | **A+C**: async-native single-agent tool-calling loop **+ reflection** (re-score + fabrication guard fed back in). |
| Pro tier (premium) | **Native 2-agent debate**: optimizer ↔ skeptical reviewer, bounded rounds. |
| Memory | First-class: **working memory** (in-run) + **long-term memory** (per-user, in Postgres). No vector DB yet. |
| Context caching | Use Gemini context caching via the existing `llm.complete(cached_prefix=...)` for the large stable prefixes (rubric, JD, résumé). |
| Web server | **Keep FastAPI on uvicorn/gunicorn.** Make Phase 2 async-native (remove the thread + `asyncio.run` workaround). |
| Observability | **Everything routes through `llm.py`** so per-tier cost is measurable (prerequisite for tiered pricing). |
| Scale | Move session + rate-limit state to a shared store; Delta writes off the request path. |

**Why "native agentic loop", not the review's "deterministic loop":** the review was correct that *today's* CrewAI agent doesn't reason (its decision is pre-computed in `_build_task_description`). But the goal is genuine reasoning over unknowns, so the fix is to *restore* agency with an observable, affordable loop — not to remove it. The deterministic loop was optimizing for how the agent is (mis)used today, not for the product we want.

---

## 1. Why in-house, not a framework

**"Multi-agent" is an architecture; a framework is an implementation of it.** A *framework* (CrewAI/LangGraph/AutoGen) earns its overhead only when **coordination complexity** is high: 3+ agents, a manager delegating to workers, dynamic topologies, group-chat routing. Our cases are below that line:

- Standard = **1 agent**, 4 tools.
- Pro = **2 agents**, one fixed hand-off (optimizer → reviewer → back), bounded turns.

For these, a framework adds cost without buying coordination we need, and CrewAI specifically *hid our Phase 2 cost* (its agent bypassed `llm.py`). **Rule:** multi-agent triggers the *architecture*; coordination complexity triggers a *framework*. Revisit a framework only if Pro grows into a real crew (manager + ≥3 specialists).

**Removed by dropping CrewAI:** `crewai`, `chromadb`, the `pysqlite3-binary` shim (`main.py:22-29`), the `HF_HUB`/tokenizers suppression (`main.py:31-34`), and the `asyncio.to_thread()` + `asyncio.run()` Phase 2 workaround. **Kept (unrelated):** uvicorn/gunicorn, FastAPI, LiteLLM, Postgres, Delta.

---

## 2. Shared substrate + pluggable driver (DRY across tiers)

Both tiers reuse the **same** building blocks; only the orchestration "driver" on top differs.

```
                ┌──────────────────────── shared substrate ────────────────────────┐
                │  Tools: keyword_inject · bullet_strengthen · skills_rewrite ·     │
                │         section_humanize        (async, route via llm.py)         │
                │  State: ResumeState (sections + token/cost accounting)            │
                │  Guard: claims ledger + fabrication_guard (+ verifier pass)       │
                │  Memory: working (in-run) + long-term (per-user, Postgres)        │
                └───────────────────────────────┬──────────────────────────────────┘
                                                 │
                      ┌──────────────────────────┴──────────────────────────┐
                      ▼                                                      ▼
        Standard driver: A+C loop                         Pro driver: 2-agent debate
        (1 reasoning agent + reflection)                  (optimizer ↔ skeptical reviewer)
```

This keeps one set of tools/state/guard; adding the Pro driver later is cheap and can't fork the pipeline.

---

## 3. Standard tier — A+C native loop

A perceive → reason → act loop (Option A) wrapped in a reflection loop (Option C). The **model** decides which tools to call, in what order, and when it is done; reflection re-scores and runs the fabrication guard, then feeds the deltas + flagged claims back into the agent's context so it can self-correct.

```
Phase 1 ─► scores, jd_keywords, claims_ledger, user memory
              │
  ┌─ REFLECTION LOOP (max N, budget-gated) ◄──────────────────────┐
  │   ┌─ TOOL-CALLING LOOP ──────────────────────────────────┐    │
  │   │  complete_with_tools(msgs) → model reasons →          │    │
  │   │  returns tool_calls (structured, validated args)      │    │
  │   │  no tool_calls? ─► break                              │    │
  │   │  else: run tools → mutate ResumeState → append obs    │    │
  │   └───────────────────────────────────────────────────────┘    │
  │   REFLECTION: re-score + fabrication_guard on reassembled draft │
  │   target met AND no guard flags? ── yes ─► DONE                 │
  │   else: feed deltas + flagged claims back as a message ─────────┘
```

Key properties: structured tool arguments (no text-parsing crashes), every call through `llm.py` (logged + cost-tracked + budget-enforced), fully async on the event loop. See `architecture-review.md` §5a code sketch for the implementation skeleton.

---

## 4. Pro tier — native 2-agent debate

A second reasoning role with its **own context** critiques the optimizer's draft. Separate context is the point: a reviewer not primed by the optimizer's reasoning catches over-claims the optimizer rationalized.

```
  optimizer agent ──► draft ──► skeptical-reviewer agent
        ▲                              │  "I don't believe 'led migration' —
        │                              │   the original says 'assisted'. Drop it."
        └──── revise (bounded rounds) ◄┘
                     │
        converged OR max_rounds OR no reviewer objections ─► finalize
```

- Reviewer persona: an adversarial hiring-manager/fact-checker that challenges claims against the **claims ledger** and quality bar.
- Bounded rounds + an explicit termination condition (no new objections, or `max_rounds`) to prevent infinite debate.
- Both agents run through `llm.py` → the **Pro-tier cost is measurable by construction** (required for pricing).
- **Safety is a floor, not a Pro feature:** the deterministic guard + a single verifier pass run in **every** tier. Pro adds *depth* (adversarial review), never *whether* the user is protected.

---

## 5. Memory design

Two layers. Keep it structured (Postgres) — **no vector DB / embeddings yet** (that would re-introduce the ChromaDB weight we just removed; add it only if memory grows large and unstructured).

### 5.1 Working memory (within a run)
- The accumulating `messages` list in the A+C loop (and the debate transcript in Pro).
- `ResumeState` (section text + token/cost) — already exists.
- Lifetime: the pipeline run. Ephemeral.

### 5.2 Long-term memory (per user, across runs)
Stored in Postgres, keyed by `user_id` / `profile_id`. Three kinds:

| Memory kind | What it is | Source / store |
|---|---|---|
| **Fact memory** | The user's verified claims (companies, metrics, titles, degrees, dates) | Persist the **claims ledger** per profile. Strengthens anti-fabrication across runs and avoids re-deriving facts. |
| **Preference / style memory** | Tone, target industries, formatting choices, what they accepted/rejected | Derived from edits + `Profile`/`ChatSession` history |
| **Outcome memory** | Past optimizations, scores, JDs targeted | `Resume`, `PipelineJob`, JD cache (already exist) |

**Insight:** the fabrication guard's claims ledger is already an in-run *fact memory*. Persisting it per user turns it into durable fact memory — the agent can verify against the user's whole history, not just the current résumé.

### 5.3 Memory as a tier lever (optional)
- Standard: **session/run memory** (remembers within the current optimization).
- Pro: **persistent career memory** — "remembers your whole history and learns your voice across runs." A clean, honest upgrade reason that reuses the same store.

Retrieval = keyed lookups by user/profile. Simple, debuggable, cheap.

---

## 6. Context caching

Directly attacks the token waste in the review (the rubric + JD re-sent up to 5×, the résumé fanned to 8–10 calls).

- **Mechanism (already in the codebase):** `llm.complete(prompt, model, cached_prefix=<large stable block>)` sends the prefix with `cache_control: ephemeral` (`llm.py:101-108`). Gemini 2.5 supports both **implicit** caching (automatic on repeated prefixes) and **explicit** cached content (longer TTL).
- **What to cache:** the large, stable blocks reused across calls in one run — the **scoring rubric**, the **JD**, and the **résumé body**. These are exactly the payloads re-transmitted across scorer (×N), tools, and humanizer.
- **Estimated win:** removes the ~6,750 redundant rubric+JD input tokens/run plus most of the résumé re-sends; cached input tokens bill at a fraction of normal on Gemini.
- **Caveats:** caching has a minimum-token threshold and a small cache-write cost — cache the *large* blocks, not tiny prompts. Measure hit rate via `LlmCallLog`.
- **Distinct from `utils/cache.py`:** that dead module is *result* caching (identical input → cached output) and is worth wiring for identical re-scores. Context caching is *prefix-token* caching. Different layers; use both.

---

## 7. Observability & cost (pricing prerequisite)

- **Every** agent/tool/reviewer call goes through `llm.py` → one `LlmCallLog` row each, tagged with a `call_kind` per phase/role/tier.
- Fixes the review P0s: the strategist no longer bypasses `llm.py`; tool-call logs are `await`-ed (no `asyncio.run` cancellation).
- Result: **per-tier, per-run cost is real** — the data the Standard/Pro pricing model depends on. Alert when `cost_source = "zero"` exceeds a threshold.

---

## 8. Scalability & deployment

- **Keep uvicorn/gunicorn.** It's the ASGI server; it has nothing to do with CrewAI and is the right host for an I/O-bound LLM app.
- **Async-native Phase 2:** remove the per-job thread + `asyncio.run`. The agent loop runs on the event loop with `await` → more concurrent jobs per instance, less memory, no loop thrash (also fixes the dropped-log bug).
- **Horizontal scale blockers to fix** (from the review): in-memory `_sessions` dict → shared store (Postgres/Redis); per-process slowapi limiter → shared store + per-user keys; Delta writes → off the request path (background task/queue).
- Net: lighter, faster instances (no ChromaDB/CrewAI) **and** the ability to add instances freely (shared state).

---

## 9. Tier summary

| | **Standard** (land / funnel) | **Pro** (expand / margin) |
|---|---|---|
| Agent | A+C single agent + reflection | + skeptical-reviewer **debate** (2 agents) |
| Anti-fabrication | Guard + verifier — **same floor** | Same + adversarial deep-check |
| Memory | Session/run | Persistent career + style memory |
| Context caching | Yes | Yes |
| Models | Flash-Lite | Flash-Lite + Flash (reviewer) |
| Deliverables | Optimized résumé + change report | + JD-tailored variants, streamed review report, cover letter |
| Cost-to-serve | low | higher — covered by price |

---

## 10. Sequencing

1. **Beta (July):** ship **one** driver (Standard A+C), free, all safety included, with memory + context caching and full cost instrumentation. Beta generates the cost + quality data.
2. **Paid GA:** add the Pro debate driver, priced against the now-measured cost delta and observed quality lift. A/B Pro vs. Standard on catch-rate and outcomes before committing.

---

## 11. Non-goals (for now) & revisit triggers

- **No agent framework** → revisit (CrewAI/LangGraph) only at a 3+-agent crew with dynamic delegation.
- **No vector DB / embeddings** → revisit only when long-term memory is large and unstructured enough that keyed lookups stop being enough.
- **No 3rd+ agent** → the 2-agent debate is the ceiling until data shows it isn't enough.
- Principle throughout: **buy value at the cheapest layer first; measure before multiplying cost.**

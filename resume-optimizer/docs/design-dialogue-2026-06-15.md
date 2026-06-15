# Design Dialogue — Agentic Architecture & Productization (2026-06-15)

A faithful, curated record of the working session that produced `target-architecture.md`.
Preserved because the *reasoning* — not just the conclusions — was the valuable part.
(This is a structured record of the discussion, organized by question; it captures the
frameworks, diagrams, tables, and decisions as they were worked out.)

**Participants:** product owner/builder ↔ engineering/product advisor.
**Starting point:** the deep architecture review (`architecture-review.md`) had just recommended replacing CrewAI with a deterministic loop. The owner pushed back. Everything below flows from that.

---

## Q1. "I want the agentic approach for unknowns — why replace CrewAI? Plain LLM orchestration hallucinates and just follows our instructions."

**Key reframe:** "Replace CrewAI" ≠ "remove the agent." CrewAI is one *runtime* for an agent; a native tool-calling loop is another, equally agentic runtime.

**The honest problem with today's agent is too *little* autonomy, not too much.** `_build_task_description` (`orchestration/optimizer.py:36-81`) pre-computes the decision ("ATS NEEDS WORK", exact params) and tells the agent to *"copy the parameter values exactly"* and *"call the tool once."* So today you pay the agentic tax but the agent transcribes a plan the code already made. To get reasoning over unknowns you **loosen** that, not remove it.

**On hallucination — two different risks:**
- *Decision* hallucination (wrong tool/args): native tool-calling is **safer** than CrewAI — it returns structured, validated arguments (`llm.py:170-172`), whereas CrewAI parses args from free text (the em-dash/quote crashes that forced the shared-state workaround, `optimizer_agent.py:9-14`).
- *Content* hallucination (invented metric/title): identical across all runtimes, because the LLM tools write the text either way. The defense is the **fabrication guard + claims ledger + section-bounded tools**, not the choice of runtime.

**Menu:** (A) native tool-calling loop; (B) keep CrewAI but un-neuter + make observable; (C) add a reflection loop (re-score + guard fed back). Recommendation: **A + C**.

---

## Q2. "Show me A+C vs B as flowcharts/examples."

**A+C — native loop + reflection** (the model owns the loop; reflection feeds the guard back in):

```
Phase 1 ─► scores, jd_keywords, ledger
  ┌─ REFLECTION LOOP (budget-gated) ◄───────────────────────────┐
  │   ┌─ TOOL-CALLING LOOP ───────────────────────────────┐     │
  │   │ complete_with_tools(msgs) → model reasons →         │     │
  │   │ tool_calls (validated args); none ⇒ break           │     │
  │   │ else run tools → mutate ResumeState → append obs    │     │
  │   └─────────────────────────────────────────────────────┘     │
  │   REFLECTION: re-score + fabrication_guard                     │
  │   target met AND no flags? ─ yes ─► DONE                       │
  │   else feed deltas + flagged claims back ─────────────────────┘
```

**B — CrewAI, un-neutered + observable** (framework owns the inner loop; reflection stays outside in `main.py`, and a fresh crew each iteration means no recall unless `memory=True`):

```
task = RAW scores + context (NOT "copy these params")
Agent(llm = TrackedLLM → routes via llm.py)     ← fixes cost/log bypass
   └─ CrewAI ReAct loop: Thought → Action → Observation → repeat
OUTER loop in main.py: re-score; else re-run a FRESH crew (memory=False → forgets)
```

**Comparison:**

| | A+C (native + reflection) | B (CrewAI, fixed) |
|---|---|---|
| Who owns the loop | you (explicit) | framework |
| Tool-call args | structured/validated | parsed from text (em-dash crashes) |
| Cost/logging | every call via `llm.py` ✅ | needs a wrapper or it bypasses `llm.py` |
| Reflection | first-class, inside agent context | outside, in `main.py` |
| "Reason with itself" across attempts | native (messages accumulate) | only with `memory=True` or re-injection |
| Deps | `llm.py` + LiteLLM | + CrewAI + ChromaDB + `pysqlite3` shim |
| Best when | single agent, 4 tools (our case) | multi-agent collaboration later |

---

## Q3. "Why are BOTH agentic, not just LLM orchestration?"

**The test: who decides the control flow at runtime?**
- **Orchestration / workflow:** *your code* fixes the sequence; the LLM fills content inside fixed steps.
- **Agent:** *the model* chooses the next action, loops, observes results, re-plans, and decides when it's done.

```
ORCHESTRATION:  code: A ─► B ─► C        (you draw the arrows)
AGENT:          loop: model reads state → PICKS action → act → observe → repeat → "done"
                                          (the model draws the arrows)
```

| Question | Deterministic `if/else` | A+C | B (CrewAI) |
|---|---|---|---|
| Which tool runs next? | code | **model** | **model** |
| Order? | code | **model** | **model** |
| When to stop? | code | **model** | **model** |
| Observes results & re-plans? | no | **yes** | **yes** |
| Classification | **Orchestration** | **Agent** | **Agent** |

**Crucial nuance:** *a code `while` loop is not orchestration; coded branches are.* In A+C the loop body is "ask the model what to do next" — the model picks the branch each turn. Every agent runtime (CrewAI included) is ultimately a `while` loop around model→tool→observe; CrewAI hides it, A+C makes it explicit. Hiding it doesn't add agency; exposing it doesn't remove it.

**Twist:** the *current* CrewAI is the **least** agentic of the three, because the plan is pre-baked into the task description. Un-neutering it is what restores agency.

**On the hallucination worry:** "it just follows our instructions" *is* the orchestration boundary — the cure is to pass a *goal*, not a plan (= agency). "It hallucinates" is solved by *guardrails*, which are orthogonal to agency.

---

## Q4. "When you say 'multi-agent → CrewAI', what do you mean?"

**Single-agent (today):** one reasoning loop + N dumb tools. **Multi-agent:** several *independent reasoning loops*, each with its own role/persona/memory, that talk to / delegate to / critique each other.

```
SINGLE-AGENT:               MULTI-AGENT:
  Strategist                  Manager ─delegates─► ATS agent, Impact agent
  └ kw/bullet/skills/humanize          └────────► Skeptical Reviewer (debates, can reject)
```

**Lens — tool or sub-agent?** If a sub-task is "do X to this text" → **tool**. If it needs its own judgment, multi-step reasoning, and especially an *independent perspective* → **agent**. The canonical example for us: a **skeptical hiring-manager agent** that debates the optimizer to catch over-claims — separate context catches what self-grading misses.

**What a framework buys (only once coordination is complex):** per-agent roles/memory, delegation/routing, inter-agent messaging, debate termination, scoped memory, parallelism. For *one* agent it's overhead.

**Honest read:** you probably don't need multi-agent yet. Triggers to adopt it: adversarial debate for quality/trust; different models per role; genuinely separable responsibilities needing isolated context; parallelism. Costs: more tokens, latency, debugging, coordination failure modes. "go CrewAI" really meant "*reach for a framework when coordination gets complex* — and since you already run CrewAI, it's the cheapest path then."

---

## Q5. "Why not add the skeptical-reviewer/debate agent today — benefit or just overhead? What would you do?"

**Reframe: it's not 'add agent vs no benefit' — there's a cheap version of the same value (anti-fabrication), bought in layers:**

| Layer | Catches | Marginal cost | When |
|---|---|---|---|
| Deterministic guard (fixed) | invented metrics/companies/titles/degrees/dates | ~free | now |
| Single verifier / reflection (1 call) | unsupported/exaggerated claims regex misses | 1 cheap call | now |
| Multi-agent debate | subtle over-claims via adversarial pressure | multiplies Phase 2 cost+latency | only if data proves the above isn't enough |

**Principle: buy value at the cheapest layer first; fix floors before ceilings; measure before multiplying cost.** A single *reviewer* (one call) gets most of the trust benefit; a *debate* (two agents) buys the last slice at many times the cost — and users perceive "caught 3 unsupported claims" identically regardless of implementation, so the marketing value doesn't require the expensive build.

---

## Q6. New context: "Not in production. Beta mid-July. No one's harmed yet — I'm figuring out the product and how to stand out. Agentic may be oversold, but the market buys what's advertised."

**Conceded the market point — agentic *sells*; lean into it.** Then the reconciliation:

**Your bug-fix list and your differentiator list are the same list:**

| The "fix" | The product story |
|---|---|
| Remove tech-keyword bias | **"Works for every profession"** (TAM expansion vs tech-only competitors) |
| Elevate guard + visible reviewer | **"The optimizer that won't let you lie"** (trust moat) |
| Make Phase 2 observable + stream reasoning | **"Watch the agent think"** (architecture → experience) |

**Make agency *visible* to convert architecture into marketing.** Invisible agents = cost with no marketing value; visible agents (stream the reasoning + rejected claims over the existing SSE) = the product *and* the ad. The "it caught me inflating 25%→40% and explained why" moment is a screenshot/testimonial.

**Recommended headline:** *"The agentic résumé optimizer for every profession that never fabricates — and shows you its reasoning."*

**Beta caution:** a beta is where hype and reality collide in public; testers are your marketing department. Advertise hard, but make the beta *deliver the wow that matches the ad*. Hype + substance compounds; hype alone dies at beta.

---

## Q7. "Tier it: multi-agent on the premium plan, single-agent on the cheap plan, to make both profitable."

**Endorsed — cost-to-serve aligns with price — with three guardrails:**

1. **Differentiate on quality/depth, never on safety.** Anti-fabrication is a **floor in every tier**; you can't sell "won't let you lie" as premium-only. Pro is *more thorough*, not Standard *crippled*.
2. **You can't price what you can't measure.** Phase 2 cost is invisible today (strategist bypass + dropped logs) → fixing observability is a *business* prerequisite for this pricing model.
3. **Don't build two pipelines — one substrate, pluggable driver.** Same tools + `ResumeState` + guard; Standard runs the 1-agent driver, Pro the 2-agent driver. Adding Pro later becomes cheap.

| | Standard (land) | Pro (expand) |
|---|---|---|
| AI | A+C single agent | + skeptical-reviewer debate |
| Anti-fabrication | guard + verifier — same | + adversarial deep-check |
| Deliverables | résumé + change report | + variants, streamed review report, cover letter |
| Cost-to-serve | low | higher — covered by price |

**Land/expand framing:** the cheap tier's job is to be cheap-to-serve, safe, good enough to convert and retain — *not* to be a profit center. Premium carries the margin. Name tiers by outcome ("Standard / Pro — Deep Expert Review"), not by implementation.

---

## Q8. "So multi-agent = CrewAI?"

**No — multi-agent is the architecture; CrewAI is one implementation.** A 2-agent debate is the *simplest* multi-agent topology (two fixed roles, one hand-off, bounded turns) — below the line where a framework pays off.

**Rule:** *multi-agent triggers the architecture; coordination complexity triggers the framework.*

**Build the Pro debate natively through `llm.py`** because: only two fixed roles; it makes Pro-tier cost **measurable by construction** (the clincher for pricing); same observability/debuggability as the single agent. Keep CrewAI/LangGraph for a future *complex* crew (manager + ≥3 specialists). You can still truthfully market a native build as "multi-agent" — the architecture makes the claim true, not the dependency.

---

## Q9. "Building our own also removes the uvicorn dependency and makes scaling easier/faster."

**Correction: dropping CrewAI does NOT remove uvicorn.** Uvicorn is the ASGI web server running FastAPI — kept regardless of agent approach.

- **Removed by dropping CrewAI:** `crewai`, `chromadb`, the `pysqlite3` shim (`main.py:22-29`), the HF suppression (`main.py:31-34`), and the `to_thread` + `asyncio.run` Phase 2 workaround.
- **The real "faster/simpler/scalable" win is async-native Phase 2** (run on the event loop, not per-job threads) + smaller image (no ChromaDB) + no sqlite shim + less ReAct latency.
- **True horizontal-scale blockers are elsewhere** (from the review): in-memory `_sessions` dict, per-process slowapi limiter, Delta writes on the request path. Fix those → scale out freely. Removing CrewAI makes each instance lighter; fixing shared state lets you add instances.

**Target:** FastAPI **on uvicorn** → async-native A+C (Standard) / async 2-agent debate (Pro), all via `llm.py`, with shared session + rate-limit state.

---

## Final decisions (→ `target-architecture.md`)

1. Build agents **in-house** on `llm.py` (no CrewAI/LangChain/LangGraph/AutoGen yet).
2. **Standard = A+C**, **Pro = native 2-agent debate**; one shared substrate, pluggable driver.
3. **Memory** first-class: working (in-run) + long-term per-user in Postgres; persist the claims ledger as durable *fact memory*; no vector DB yet. Persistent memory can be a Pro lever.
4. **Context caching** via `llm.complete(cached_prefix=...)` for the rubric/JD/résumé; distinct from (and complementary to) the dead `utils/cache.py` result cache.
5. **Safety (anti-fabrication) is a floor in every tier.**
6. Keep **uvicorn**; go **async-native**; move session + rate-limit state to a shared store; Delta off the request path.
7. **Everything through `llm.py`** so per-tier cost is measurable — the prerequisite for the tiered pricing.
8. Sequencing: beta = one driver (Standard), free, instrumented; GA = add Pro driver, priced on measured cost + observed lift; A/B before committing.

**Through-line principle:** *buy value at the cheapest layer first; make agency visible; measure before multiplying cost.*

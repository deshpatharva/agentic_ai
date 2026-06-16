# Resume Optimizer — Deep Architecture Review

**Scope:** `backend/agents/`, `backend/orchestration/`, `backend/config.py`, `backend/llm.py`, and the cross-cutting LLM routing/cost/reliability layers that touch them (`utils/cost.py`, `utils/llm_json.py`, `limiter.py`, `delta/writer.py`, plus the live call graph in `main.py`, `chat/`, `profiles/`, `jd/`).
**Stack:** FastAPI + PostgreSQL + CrewAI + LiteLLM on Azure (gunicorn, 2 × UvicornWorker per `backend/Dockerfile`).
**Constraint honored:** No Anthropic models recommended (per product unit economics).
**Date:** 2026-06-15.

This review is ruthless by request. Things that work fine are not discussed. Every finding cites the file/lines, the concrete problem, quantified impact, the exact change, and a priority.

**Priority key:** **P0** = breaks, corrupts output, or actively harms real users / loses money silently. **P1** = should fix before launch. **P2** = improve post-launch.

---

## Executive Summary

The pipeline is well-structured (clean phase separation, shared-state token discipline in Phase 2, fire-and-forget logging, a real fabrication guard). But it has **three categories of serious problems**:

1. **It is hard-coded to tech résumés and will actively sabotage non-tech users.** Two prompts *instruct the model to reject* keywords for HR, sales, legal, finance, and recruiting roles (`optimizer_agent.py:249-251`, `rewriter.py:47-48`). A recruiter, nurse, or accountant optimizing against their own field's JD will have their most important keywords stripped. This is a **P0 correctness bug for ~half the addressable market**, not a "bias nuance."

2. **JSON is parsed by best-effort regex when every model in the stack supports enforced structured output.** The scorer even *defines a 47-line JSON schema and then never passes it* (`scorer.py:19,160`). When parsing fails, the scorer silently returns all-zero scores, which then drive the Phase 2 agent's tool decisions — garbage in, garbage out. Gemini supports full `json_schema` enforcement through LiteLLM today; switching is a few lines per call site and deletes ~80 lines of dead fallback code.

3. **Phase 2 cost and tokens are largely invisible, and the agent's value is unproven.** The CrewAI strategist (the single most expensive Phase 2 model, `gemini-2.5-flash`) **bypasses `llm.py`**, so its tokens are never logged and never counted against `AGENT_TOKEN_BUDGET`. The tool-call logs are *also* likely dropped (`asyncio.run()` cancels the fire-and-forget log task). For a 4-tool, score-gated agent, a deterministic `if score < threshold: call_tool()` loop would be cheaper, fully observable, and more reliable.

**Severity counts:** 6 × P0, 18 × P1, 14 × P2 (detailed below).

### Top 8 issues by severity

| # | Finding | File | Pri |
|---|---------|------|-----|
| 1 | Prompts reject non-tech keywords → sabotage HR/sales/finance/nursing/legal résumés | `optimizer_agent.py:249-251`, `rewriter.py:47-48` | P0 |
| 2 | Scorer defines a JSON schema but never enforces it; silent all-zero fallback feeds Phase 2 | `scorer.py:19,28-30,160` | P0 |
| 3 | CrewAI strategist bypasses `llm.py` → cost/tokens unlogged, escapes token budget | `optimizer_agent.py:491-511`, `llm.py` | P0 |
| 4 | Phase 2 tool-call logs dropped: `asyncio.run()` cancels fire-and-forget `_record_call` | `optimizer_agent.py:178-188`, `llm.py:138` | P1 |
| 5 | `_PERSONA_TERMS` blocklist is 18 tech-adjacent terms; useless for healthcare/trades/gov | `fabrication_guard.py:30-37` | P1 |
| 6 | Rewriter told to inject `[XX%]` placeholders while every other prompt forbids them | `rewriter.py:53-54` | P0 |
| 7 | In-memory `_sessions` + slowapi limiter under 2 gunicorn workers → state split, 2× rate | `optimizer_agent.py:135`, `limiter.py:4` | P1 |
| 8 | Company attest threshold 0.75 misses MSFT→Microsoft, AWS→Amazon Web Services | `fabrication_guard.py:77-83` | P1 |

---

## Recommended Model Matrix

Constraints applied: no Anthropic; minimize provider sprawl (Gemini + Groq already wired; adding DeepSeek-direct is called out where it earns its keep); enforce structured output where JSON is parsed; tier model power to task difficulty instead of defaulting everything to Flash-Lite.

Current prices (mid-2026, per 1M tokens, from sources at end): Gemini 2.5 Flash-Lite **$0.10/$0.40**; Gemini 2.5 Flash ~**$0.30/$2.50**; Gemini 3.5 Flash **$1.50/$9.00**; Gemini 3.1 Pro **$2.00/$12.00**; Groq Llama-3.1-8B **$0.05/$0.08**; Groq Llama-3.3-70B **$0.59/$0.79**; Groq GPT-OSS-120B **$0.15/$0.60**; Groq GPT-OSS-20B **$0.075/$0.30**; DeepSeek V3 **$0.14/$0.28** (now V4 Flash/Pro).

| Slot | Current | Recommended (primary) | Fallback | Reasoning |
|------|---------|-----------------------|----------|-----------|
| **Scorer** | flash-lite | **Hybrid:** deterministic ATS keyword match (local, free) + `gemini-2.5-flash-lite` **with `json_schema`** for the 3 subjective dims | `gemini-2.5-flash` + `json_schema` | Schema enforcement eliminates the malformed-JSON failures that currently zero out scores. Local ATS is exact and free, and the scorer runs up to **5×/résumé** so cost discipline matters. Bumping to full Flash for *reasoning* is the fallback if subjective scores stay noisy. |
| **JD Analyzer** | flash-lite | `gemini-2.5-flash-lite` **+ `json_schema`** | flash-lite + `json_object` | Extraction is easy; the only defect is unenforced structure. |
| **Rewriter** (fallback path only) | flash-lite | `gemini-2.5-flash` | flash-lite | Better instruction-adherence to the claims ledger; runs rarely (fallback), so the price step-up is negligible. |
| **Phase 2 Strategist** | `gemini-2.5-flash` | **Eliminate** (deterministic loop, see 5a). If kept: `groq/llama-4-scout` or `gemini-2.5-flash` | `gemini-2.5-flash` | Removing the agent removes the priciest, least-observable Phase 2 cost. Llama-4-Scout on Groq (460+ tok/s) is the cheap/fast option if an agent is retained. |
| **Phase 2 tools** (×4) | flash-lite | flash-lite (keep) | — | Surgical single-section edits; Flash-Lite is correctly sized. |
| **Humanizer** (polish/refine) | flash-lite | flash-lite (keep) | — | Adequate. The problem is pipeline placement (3c), not the model. |
| **Humanizer Critic** | groq llama-3.1-8b | **Merge into Step 1** (see 3a) or `gemini-2.5-flash-lite` + `json_object` | groq gpt-oss-20b + `json_object` | The critic's JSON fails silently and its output is 90% discarded. If kept, enforce JSON — but Groq `json_schema` is flaky in LiteLLM, so use `json_object` or move to Gemini. |
| **Chat co-pilot** | groq llama-3.3-70b | `groq/openai/gpt-oss-120b` ($0.15/$0.60) | groq llama-3.3-70b | Cheaper and strong native tool-use; the config already lists it as a candidate (`config.py:81`). Keep 70B as fallback. |
| **Profile parser / JD match / Interview** | flash-lite | flash-lite **+ `json_schema`** | flash-lite + `json_object` | Out of the stated scope but same parse-failure exposure (`profiles/router.py:168`, `jd/router.py:148`). |

---

## Pipeline Token / Cost Map (single optimization, ~1.5-page résumé ≈ 1,100 tok; JD ≈ 800 tok)

| # | Call | Model | Phase | Est. in | Est. out | Logged? | Necessary? |
|---|------|-------|-------|--------:|---------:|---------|------------|
| 1 | `extract_claims` | — (spaCy) | 1 | 0 | 0 | n/a | Yes |
| 2 | `analyze_jd` | flash-lite | 1 | ~1,250 | ~300 | ✅ | Yes — **parallelize with #1** |
| 3 | `score_combined` (baseline) | flash-lite | 1 | ~2,970 | ~350 | ✅ | Yes |
| 4 | CrewAI strategist reasoning | flash | 2 | ~6,000–10,000 | ~600–1,000 | ❌ **never logged** | **No** — replaceable by deterministic loop |
| 5 | 4 × tool calls | flash-lite | 2 | ~2,400 | ~1,400 | ⚠️ likely dropped | Conditionally |
| 6 | `score_combined` (re-score) | flash-lite | 2 | ~2,970 | ~350 | ✅ | Partly — repeats rubric+JD |
| 4–6 | **× up to MAX_ITERATIONS=4** | | 2 | up to ~60k | up to ~11k | | loop multiplies the CrewAI tax |
| 7 | `fabrication_guard` | — (spaCy) | 3 | 0 | 0 | n/a | Yes |
| 8 | humanize Step 1 (polish) | flash-lite | 3 | ~1,420 | ~1,100 | ✅ | Yes |
| 9 | humanize Step 2 (critic) | groq 8b | 3 | ~1,320 | ~400–900 | ✅ | **No** — mergeable |
| 10 | humanize Step 3 (refine) | flash-lite | 3 | ~1,350 | ~1,100 | ✅ | Marginal |

**Quantified waste:**
- **Rubric + JD re-sent up to 5×:** the ~600-token scorer rubric + ~750-token JD slice are re-transmitted on the baseline score and every re-score → **~6,750 redundant input tokens/run** before any optimization value.
- **Résumé re-transmitted 8–10×:** scorer (×1–5), each Phase-2 tool (per-section), humanizer (×3). The résumé body is the single most-duplicated payload.
- **CrewAI tax (~6–10k input tok/iteration) is pure orchestration overhead** for a decision a deterministic loop makes with **zero** LLM tokens, and the outer loop can run it 4×.
- **Critic output is ~90% discarded:** the prompt says "no limit on feedback items" (`humanizer.py:73`) then only the **first 3** of each list are used (`humanizer.py:103-107`).
- **The fix already exists but is dead:** `utils/cache.py` (an LRU result cache) is imported nowhere — exactly the tool that would deduplicate repeated scorer calls.

---

## 1. Model Selection Audit

### Finding 1.1: Scorer is under-powered for a 4-dimension reasoning+JSON task, and its schema is decorative
- **File(s):** `agents/scorer.py:19-30, 160` (the unused `schema` param + free-text parse), `:111-158` (the dead schema)
- **Problem:** `score_combined` asks one Flash-Lite call to reason across 4 rubrics *and* emit strict JSON. `_llm_complete(prompt, system, schema)` accepts a `schema` argument **and never uses it** — line 21 calls `complete(full_prompt, MODEL_SCORER)` with no `response_format`. On parse failure it returns `{}` (`:28-30`), then `defaults` backfills **all scores to 0** (`:176-189`). Those zeros become the Phase 2 agent's tool-selection input.
- **Impact:** Reliability + quality. A single malformed response silently produces a 0/0/0/0 scorecard → the agent "optimizes" against noise, or the pipeline reports a wrong baseline. Flash-Lite is the cheapest tier and the most prone to this on multi-objective JSON.
- **Recommendation:** Enforce `response_format` `json_schema` (the schema already exists at `:111-158`) and move ATS to a local keyword match (see 5b). Keep Flash-Lite for the 3 subjective dims under schema; escalate to `gemini-2.5-flash` only if subjective scores remain noisy.
- **Priority:** P0 (the zero-score fallback corrupts downstream decisions).

### Finding 1.2: Phase 2 strategist is the priciest Phase 2 model and the least accountable
- **File(s):** `agents/optimizer_agent.py:491-511` (`Agent(llm=MODEL_OPTIMIZER)`), `config.py:68`
- **Problem:** The strategist runs `gemini-2.5-flash` (~8× the output price of Flash-Lite) and its reasoning calls go through CrewAI's own LiteLLM path, **not** `llm.py` — so they are absent from `LlmCallLog` and from `ResumeState`'s token counter.
- **Impact:** Cost (untracked spend on the most expensive Phase 2 slot) + the agent's decision value is unproven (5a). The token budget (`AGENT_TOKEN_BUDGET = 20_000`) only governs tool tokens, so real Phase 2 spend exceeds the "budget" by the entire strategist cost.
- **Recommendation:** Replace the agent with a deterministic loop (5a) and delete this slot. If retained, route its calls through `llm.py` and switch to `groq/llama-4-scout` for speed/cost.
- **Priority:** P1 (P0 for the cost-tracking aspect — see 7.2).

### Finding 1.3: Critic model choice is fine; the integration around it is not
- **File(s):** `config.py:56`, `agents/humanizer.py:70-98`
- **Problem:** `groq/llama-3.1-8b-instant` is cheap and fast, but its JSON is parsed by the weak private `_clean_json` (`:13-20`) and on any failure Step 3 is silently skipped. Groq's `json_schema` support via LiteLLM is unreliable (returns `BadRequestError: unsupported tool_choice 'json_tool_call'`), so you can't simply bolt schema enforcement on here.
- **Impact:** Quality (the whole critic→refine loop no-ops whenever the 8B model fences its JSON or adds prose) at near-zero token savings.
- **Recommendation:** Either merge the critic into Step 1 (3a) or, if kept, use Groq **`json_object`** mode (not `json_schema`) or move the critic to `gemini-2.5-flash-lite` for true schema enforcement.
- **Priority:** P2.

### Finding 1.4: Chat co-pilot can move to a cheaper, equally tool-capable model
- **File(s):** `config.py:84`, `chat/router.py:414`
- **Problem:** `groq/llama-3.3-70b-versatile` ($0.59/$0.79) is reliable for native tool-calling but `groq/openai/gpt-oss-120b` ($0.15/$0.60) is cheaper with strong tool-use, and runs every chat turn.
- **Impact:** Cost — chat is a per-turn recurring spend; ~3–4× cheaper input.
- **Recommendation:** Promote `gpt-oss-120b` to primary, keep 70B as the `complete_with_tools` fallback (which already degrades gracefully, `llm.py:194-204`).
- **Priority:** P2.

---

## 2. Prompt Engineering Overhaul

### 2a. Industry Bias Elimination

### Finding 2.1: Keyword-injection tool literally rejects non-tech keywords
- **File(s):** `agents/optimizer_agent.py:249-251`
- **Problem:** The tool prompt states: *"Keywords must describe the candidate's actual technical work (tools, languages, frameworks, platforms)"* and *"REJECT any keyword that describes a job function the candidate does not hold (e.g. recruiting, talent acquisition, HR, sales, legal, finance) — skip it entirely."* For a recruiter, salesperson, paralegal, or accountant, **their own field's ATS keywords are exactly what gets rejected.**
- **Impact:** Quality/scope — the ATS-fix tool is a no-op or actively harmful for a large share of users. This single instruction caps the product at tech résumés.
- **Recommendation:** Replace with field-agnostic guidance: *"Inject only keywords that match the candidate's actual profession and the target role's domain. Skip keywords that imply a job function the candidate has never performed, regardless of field."* Drop the hard-coded tech vocabulary and the HR/sales/finance exclusion list.
- **Priority:** P0.

### Finding 2.2: Rewriter repeats the same exclusion
- **File(s):** `agents/rewriter.py:44-49` (PRIORITY 1 — KEYWORD SATURATION)
- **Problem:** Same pattern: *"ONLY inject keywords that match the candidate's actual technical discipline (tools, languages, frameworks, platforms). SKIP any keyword that belongs to a different job function (e.g. recruiting … HR, sales, legal, finance)."* The fallback rewriter inherits the tech-only ceiling.
- **Impact:** Quality/scope (same as 2.1, on the fallback path).
- **Recommendation:** Same field-agnostic rewrite. Define "discipline" by the candidate's résumé + the JD's domain, not by a tech vocabulary.
- **Priority:** P0.

### Finding 2.3: `_PERSONA_TERMS` blocklist is tiny and tech-world-centric
- **File(s):** `agents/fabrication_guard.py:30-37`
- **Problem:** The fabrication guard's cross-domain term filter is 18 frozen strings, all HR/sales/finance ("talent acquisition", "payroll", "loan origination", "cold calling", …). A nurse whose résumé gets "EHR implementation", "HL7", "revenue cycle" injected from a healthcare-IT JD, or a teacher who gets "curriculum analytics platform", sails straight through. The list is a tech-company allow-by-omission.
- **Impact:** Reliability — the guard only catches fabrication *into* the few domains someone hard-coded; it's blind everywhere else.
- **Recommendation:** Replace the static blocklist with a **JD-relative** check: derive the candidate's domain from the claims ledger and flag injected terminology that belongs to a *different* domain than both the résumé and the JD. If a static fallback is kept, generalize it per top-level industry (healthcare, education, legal, trades, public sector, creative, …), ideally data-driven rather than in code.
- **Priority:** P1.

### Finding 2.4: Seniority rubric assumes a tech corporate ladder
- **File(s):** `agents/scorer.py:50-56`, `agents/humanizer.py:36-41`, `agents/jd_analyzer.py:46`
- **Problem:** Seniority is mapped to "0-2/3-6/7+/10+ years" with cues like *"architecture mentions"*, *"team-building language, org-level impact"*, *"visionary, team multiplier."* These don't describe a charge nurse, a tenured teacher, a master electrician, a partner-track attorney, or a GS-13 civil servant.
- **Impact:** Quality — scoring and tone are miscalibrated for non-corporate ladders, penalizing valid senior résumés that lack "architecture" or "org-level" language.
- **Recommendation:** Reframe seniority by *scope of responsibility and autonomy* (individual contributor → supervises others → sets direction for a unit → leads an organization) instead of tech-leadership keywords. Keep year bands as a hint, not a gate.
- **Priority:** P1.

### Finding 2.5: Humanizer critic defaults the industry to "technology"
- **File(s):** `agents/humanizer.py:70`
- **Problem:** `f"...reviewing a resume for a {seniority_level}-level {industry or \"technology\"} role."` When `analyze_jd` fails to extract an industry (its own silent-default path), the critic literally assumes tech.
- **Impact:** Quality — non-tech résumés get critiqued against a tech hiring-manager persona.
- **Recommendation:** Default to a neutral "professional" persona; only specialize when `industry` is non-empty.
- **Priority:** P2.

### 2b. Prompt Quality

### Finding 2.6: Rewriter is told to fabricate placeholder metrics, contradicting every other prompt and itself
- **File(s):** `agents/rewriter.py:53-55`
- **Problem:** PRIORITY 2 says *"If a bullet has no metric, add a realistic placeholder using the format `[XX%]`"* — then the very next line says *"Use ONLY numbers and metrics that appear verbatim in the CLAIMS LEDGER."* Meanwhile `optimizer_agent.py` (every tool) and `humanizer.py:51` explicitly say **"NEVER insert a placeholder like `[XX%]`."** The pipeline contradicts itself, and `[XX%]` artifacts are then cleaned up downstream by `utils/text_sanitizer.py` — i.e., you spend tokens generating them and more code deleting them.
- **Impact:** Quality + reliability + wasted tokens. Inconsistent guidance is exactly why models "ignore" instructions.
- **Recommendation:** Delete the `[XX%]` instruction from the rewriter. Align on one rule everywhere: never invent numbers; strengthen verbs/impact without fabricating metrics.
- **Priority:** P1 (P0-adjacent — it directly causes fabricated-looking output).

### Finding 2.7: "Needs work" threshold is inconsistent across the agent surface
- **File(s):** `orchestration/optimizer.py:33` (`_WORK_THRESHOLD = max(75, SCORE_TARGET-10) = 80`), vs every tool docstring ("Call this when the … score is below 75", `optimizer_agent.py:213, 289, 359, 425`)
- **Problem:** The task description flags dimensions as NEEDS WORK at `<80`, but the tools tell the model to act at `<75`. The agent gets two thresholds.
- **Impact:** Quality — borderline dimensions (75–79) are flagged but the tool guidance says skip, producing inconsistent behavior.
- **Recommendation:** Single source of truth: pass the threshold into the task description and the tool docstrings from one constant.
- **Priority:** P2.

### 2c. Prompt Compression

### Finding 2.8: Repeated boilerplate across the four tool prompts and the scorer rubric
- **File(s):** `agents/optimizer_agent.py:245-265, 317-340, 385-401, 455-471`; `agents/scorer.py:58-97`
- **Problem:** Each tool prompt re-states the same "plain text only / no markdown / no LaTeX / no `$` wrappers / never insert `[XX%]`" block (~40–60 tokens each). The scorer ships the full 4-band rubric (~600 tokens) on every call including the up-to-4 re-scores.
- **Impact:** Cost — modest per call but multiplied by tool-count × iterations. Estimated ~150–250 redundant input tokens/Phase-2 iteration from the repeated formatting block alone; ~600 tokens × (N-1) re-scores from the rubric.
- **Recommendation:** Once `json_schema` is enforced (Area 6), the formatting prohibitions and rubric prose can be trimmed hard — the schema guarantees structure, so the prompt only needs the scoring *criteria*, not the output-shape lecture. Estimated 30–40% input-token reduction on the scorer system prompt.
- **Priority:** P2.

---

## 3. Token Optimization

### 3a. Pipeline-Level Waste

### Finding 3.1: The scorer re-sends the rubric + JD on every iteration
- **File(s):** `main.py:847, 902`; `agents/scorer.py:58-109`
- **Problem:** `score_combined` is called once for baseline and once per Phase 2 iteration (up to 4), each time re-sending the ~600-token rubric, the `resume[:6000]`, and `jd[:3000]`.
- **Impact:** Cost — up to ~6,750 redundant rubric+JD tokens/run, plus the résumé re-sent each time.
- **Recommendation:** (a) Use `cached_prefix` (already supported in `llm.py:78-108`, and Gemini 2.5 supports implicit/explicit caching) for the static rubric+JD block. (b) Better: with a local ATS score and an enforced-schema subjective scorer, only re-score the *changed* sections rather than the whole résumé.
- **Priority:** P1.

### Finding 3.2: The résumé is fanned out to 8–10 model calls per run
- **File(s):** `main.py:829-954`
- **Problem:** The full (or near-full) résumé reaches the scorer (×1–5), each Phase-2 tool (per section), and the humanizer (×3). This is the "does the full resume get sent to 6+ models?" concern — answer: yes, effectively 8–10×.
- **Impact:** Cost + latency.
- **Recommendation:** The shared-state section pattern already minimizes this in Phase 2; extend it to the humanizer (humanize per changed section, not the whole document) and to re-scoring (3.1).
- **Priority:** P1.

### Finding 3.3: Critic generates unbounded feedback, 90% discarded
- **File(s):** `agents/humanizer.py:73, 103-107`
- **Problem:** Prompt: "no limit on feedback items"; consumer: first 3 of each of 3 lists.
- **Impact:** Cost (wasted output tokens on the critic) + latency.
- **Recommendation:** Cap the critic to "the 3 most important issues per category" in the prompt, or eliminate the separate call (3a/1.3).
- **Priority:** P2.

### 3b. CrewAI Tax

### Finding 3.4: CrewAI overhead is unjustified for a 4-tool, score-gated agent
- **File(s):** `orchestration/optimizer.py:84-135`, `agents/optimizer_agent.py:483-511`
- **Problem:** CrewAI wraps each run in a ReAct system preamble + role/goal/backstory + 4 tool schemas + thought/action/observation scaffolding, re-sent each reasoning step. For a deterministic decision ("for each dimension below threshold, call its one tool"), this is ~6–10k input tokens/iteration of pure orchestration. The outer loop (`main.py:879`) re-runs the *entire* crew up to 4×, multiplying it. CrewAI also pulls in ChromaDB/HF and forces the `pysqlite3` shim (`main.py:22-29`) — operational weight for no agentic payoff.
- **Impact:** Cost + reliability (more moving parts, more failure modes; the code already has three separate fallbacks to `_deterministic_fallback`).
- **Recommendation:** Replace with a direct loop using the existing `llm.complete` (sketch in 5a). Estimated elimination of the entire strategist token cost and ~6–10k orchestration tokens/iteration.
- **Priority:** P1.

### 3c. Context Window Management

### Finding 3.5: Truncation boundaries are crude and inconsistent
- **File(s):** `agents/scorer.py:104` (`resume_text[:6000]`), `:107` (`jd_text[:3000]`), `agents/jd_analyzer.py:58` (`jd_text[:4000]`)
- **Problem:** Truncation is a hard character slice mid-section/mid-word. The JD is cut at 3,000 chars for scoring but 4,000 for analysis — so the scorer evaluates against *less* JD than was analyzed for keywords, guaranteeing some "missing keywords" come from JD text the scorer never saw. None of these approach model context limits (1M tokens on current Gemini), so the truncation is over-aggressive.
- **Impact:** Quality — silent loss of résumé/JD signal; internal inconsistency between analyzer and scorer views of the JD.
- **Recommendation:** Raise/remove the scorer slices (the real cap is `MAX_RESUME_CHARS`/`MAX_JD_CHARS` upstream), and at minimum align the JD slice across analyzer and scorer. If truncation is ever needed, cut on section boundaries via the existing `detect_sections`.
- **Priority:** P2.

---

## 4. Reliability & Error Handling

### 4a. JSON Parsing Fragility

### Finding 4.1: Every JSON-returning call best-effort-parses free text; failures are silent
- **File(s):** `agents/scorer.py:26-30`, `agents/jd_analyzer.py` (silent `{}` on failure), `agents/humanizer.py:91-98`, `utils/llm_json.py:27-33`
- **Problem:** `parse_llm_json` strips fences/thinking tags then greedily regex-matches `\{.*\}` (`llm_json.py:31`) — which over-matches on any braces in prose and silently truncates on partial output. The scorer logs and returns `{}`; `jd_analyzer` returns `{}` with no log; the humanizer's private `_clean_json` (weaker — no thinking-tag strip, no regex extract) fails closed and skips Step 3. Markdown-fenced JSON is handled inconsistently across the two cleaners.
- **Impact:** Reliability — three different failure behaviors, all silent, across the JSON surface.
- **Recommendation:** Adopt enforced structured output (Area 6) everywhere it's available, deleting most of this path. Where a model can't enforce (Groq), standardize on `parse_llm_json` (delete `_clean_json`) and log every fallback with `cost_source`-style audit tags.
- **Priority:** P1.

### Finding 4.2: Two JSON cleaners diverge
- **File(s):** `agents/humanizer.py:13-20` vs `utils/llm_json.py`
- **Problem:** `humanizer._clean_json` duplicates and under-implements `parse_llm_json`.
- **Impact:** Reliability/maintainability.
- **Recommendation:** Delete `_clean_json`; use `parse_llm_json(raw, "object")`.
- **Priority:** P2.

### 4b. Fabrication Guard Gaps

### Finding 4.3: `_metric_attested` ±10% tolerance is too loose and uniform
- **File(s):** `agents/fabrication_guard.py:65-74`
- **Problem:** A generated metric passes if any source number is within **10%**. "Reduced costs by 30%" → "by 33%" passes if a ~33 exists anywhere; worse, the match is against *any* number in the whole source, not the same claim. Unparseable metrics get a free pass (`:69`).
- **Impact:** Reliability — the guard permits quiet metric inflation, the exact failure it exists to prevent.
- **Recommendation:** Tighten to exact match (or ≤2%) for percentages and require the match to come from the *same bullet/claim*, not the global text. Make tolerance configurable per metric type.
- **Priority:** P1.

### Finding 4.4: `_company_attested` 0.75 ratio misses common aliases
- **File(s):** `agents/fabrication_guard.py:77-83`
- **Problem:** `SequenceMatcher` at 0.75 won't match "MSFT"→"Microsoft", "AWS"→"Amazon Web Services", "Google"→"Alphabet", or "JPM"→"JPMorgan". It will also *false-positive* on similar-spelled unrelated firms.
- **Impact:** Reliability — legitimate companies get flagged `[VERIFY]`; aliases of fabricated ones can slip.
- **Recommendation:** Normalize via an alias/acronym map + token-set matching before fuzzy ratio; lower reliance on raw `SequenceMatcher`.
- **Priority:** P1.

### Finding 4.5: spaCy `en_core_web_sm` is weak for ORG NER
- **File(s):** `agents/fact_extractor.py:18`, `agents/fabrication_guard.py:138`
- **Problem:** The small model misses many ORG entities (acronyms, non-US firms, product-as-company), so the claims ledger's company set is incomplete — which then makes `_company_attested` flag real companies as fabricated.
- **Impact:** Reliability/quality.
- **Recommendation:** Move to `en_core_web_lg` (or a transformer NER) for extraction, or supplement NER with the résumé's experience-section company lines parsed structurally.
- **Priority:** P2.

### Finding 4.6: Titles, degrees, and date ranges are extracted but never guarded
- **File(s):** `agents/fact_extractor.py:88-107` (extracts `job_titles`, `degrees`, `date_ranges`), `agents/fabrication_guard.py:126-189` (checks only metrics + companies)
- **Problem:** The ledger captures titles/degrees/dates, but the guard only validates metrics and ORGs. A model can fabricate a "Master's in Data Science", promote "Engineer" to "Senior Staff Engineer", or stretch "2019-2021" to "2018-2022" and the guard won't notice.
- **Impact:** Reliability — title/degree/date fabrication is among the most damaging résumé lies and is currently unchecked.
- **Recommendation:** Extend the guard to attest titles (no promotion beyond ledger), degrees (exact match to ledger), and date ranges (no widening) using the data already in the ledger.
- **Priority:** P1.

### 4c. Session & State Management

### Finding 4.7: In-memory `_sessions` + slowapi under 2 gunicorn workers
- **File(s):** `agents/optimizer_agent.py:135-173`, `limiter.py:1-4`, `backend/Dockerfile` (2 × UvicornWorker)
- **Problem:** `_sessions` is a module-level dict. With 2 workers, each has its own copy. A single Phase 2 job is self-consistent (registered, read, and cleaned in the same worker/thread), but `cleanup_stale_sessions` only reaps the worker it runs in, so leaked sessions in the other worker persist for the 4-hour TTL. Separately, the slowapi limiter (`get_remote_address`) keeps counters in-process, so the effective rate limit is **2× the configured value**, and `get_remote_address` sees the Azure load-balancer IP unless `X-Forwarded-For` is honored.
- **Impact:** Reliability (memory leak under worker imbalance) + security (rate limits ineffective; per-user limiting absent).
- **Recommendation:** Move session state and rate-limit counters to a shared store (the app already has Postgres; `DailyUsageCounter` exists for per-user quotas). Configure slowapi with a Redis/DB backend and trust the proxy header. Key rate limits per authenticated user, not just IP.
- **Priority:** P1.

### Finding 4.8: `asyncio.run()` inside the tool thread cancels the fire-and-forget log task
- **File(s):** `agents/optimizer_agent.py:178-188`, `llm.py:138-149`
- **Problem:** Tools call `asyncio.run(complete(...))`. Inside `complete`, the `LlmCallLog` write is scheduled via `asyncio.create_task(_record_call(...))` and returned immediately. `asyncio.run()` then tears down the loop, cancelling that pending task before it commits. So Phase 2 **tool-call logs are likely never written.**
- **Impact:** Reliability/observability + cost-tracking — Phase 2 LLM calls vanish from the ledger.
- **Recommendation:** In the tool path, `await` the log write before returning (e.g., have `complete` accept a flag to await `_record_call`, or run the record synchronously within the same `asyncio.run`). Verify with a unit test that a Phase 2 tool call produces an `LlmCallLog` row.
- **Priority:** P1.

### Finding 4.9: CrewAI strategist calls never enter `llm.py`
- **File(s):** `agents/optimizer_agent.py:491-511`
- **Problem:** `Agent(llm=MODEL_OPTIMIZER)` hands CrewAI a bare model string; CrewAI calls Gemini via its own LiteLLM, bypassing `llm.py` entirely. No `LlmCallLog`, no `resolve_cost`, no token accounting, no trace_id.
- **Impact:** P0 for cost/observability — the most expensive Phase 2 model is financially invisible and undebuggable.
- **Recommendation:** Eliminate the agent (5a), or wrap CrewAI's LLM in a custom callback that routes through `llm.py`.
- **Priority:** P1 (P0 for the cost dimension).

---

## 5. Architecture Improvements

### 5a. Phase 2 Redesign — keep an agentic loop, but build it in-house

> **Note (updated 2026-06-15):** the original recommendation here was a *deterministic* loop. After a design discussion (see `design-dialogue-2026-06-15.md`), this evolved to a **native, in-house agentic loop (A+C)** — preserving genuine reasoning over unknowns while removing CrewAI's overhead and observability gaps. The target design is in **`target-architecture.md`**; the deterministic sketch below remains only as the lower bound the redesign must beat.

- **File(s):** `orchestration/optimizer.py`, `agents/optimizer_agent.py`
- **Problem:** The agent's only decision is "which of 4 tools to call for which below-threshold dimension" — and that decision is *already computed* deterministically in `_build_task_description` (which flags each dimension NEEDS WORK). The LLM strategist re-derives, in expensive natural language, a mapping the code already knows. Tellingly, there are **three** fallbacks to `_deterministic_fallback` (no sections, exception, no-change), suggesting the agent frequently produces nothing.
- **Impact:** Cost (entire strategist + CrewAI tax), reliability (fewer failure modes), observability (all calls back through `llm.py`).
- **Recommendation:** Direct loop, no CrewAI:
  ```python
  async def run_optimization(state, scores, jd_keywords):
      if scores["ats"]["score"] < THRESHOLD:
          await keyword_inject(state, scores["ats"]["missing_keywords"])
      if scores["impact"]["score"] < THRESHOLD:
          await bullet_strengthen(state, scores["impact"]["weak_bullets"])
      if scores["skills_gap"]["score"] < THRESHOLD:
          await skills_rewrite(state, scores["skills_gap"]["missing_skills"])
      if scores["readability"]["score"] < THRESHOLD:
          await section_humanize(state, scores["readability"]["worst_section"])
      return state.reassemble()
  ```
  Same tools, same shared state, same token budget check — minus the strategist, the ReAct tax, ChromaDB/HF, and the `pysqlite3` shim. Keep the tools `async` and route through `llm.complete` (no `asyncio.run`).
- **Priority:** P1.

### Finding 5.2: `AGENT_MAX_ITER` is defined twice with different values
- **File(s):** `config.py:75` (`= 10`), `agents/optimizer_agent.py:54` (`= 6`)
- **Problem:** The agent factory uses the local `6`; `config.py`'s `10` is dead and misleading. Anyone tuning the documented config knob changes nothing.
- **Impact:** Maintainability/correctness of tuning.
- **Recommendation:** Delete the local shadow; import the single value from `config.py`. (Moot if 5a lands.)
- **Priority:** P2.

### Finding 5.3: The outer iteration loop re-runs the whole crew
- **File(s):** `main.py:879-922`, `orchestration/optimizer.py:226-233` (returns `iterations: 1` always)
- **Problem:** `run_optimization_async` always reports `iterations: 1`, while `main.py` wraps it in `for _iter in range(1, MAX_ITERATIONS+1)`, re-registering a session and re-running CrewAI from scratch each time — multiplying the CrewAI tax up to 4×. Exit is `current_avg >= _WORK_THRESHOLD (80)` though `SCORE_TARGET` is 90, so the loop targets 80 while the entry gate is 90.
- **Impact:** Cost + confusing convergence semantics.
- **Recommendation:** With the deterministic loop (5a), do all needed tools in one pass and re-score once; drop the outer multi-run loop or cap it at 2 with a clear, single threshold.
- **Priority:** P1.

### 5b. Scoring Consolidation — hybrid local ATS + schema-enforced subjective scorer
- **File(s):** `agents/scorer.py`
- **Problem:** ATS "keyword coverage" is a deterministic set-overlap computation being delegated to an LLM that then returns it as unenforced JSON. The note at `scorer.py:4` ("moved from local to LLM prompt") shows this was *deliberately* de-localized — the wrong direction.
- **Impact:** Reliability + cost — ATS is exactly computable locally; paying an LLM to approximate it (and sometimes return 0) is worse and pricier.
- **Recommendation:** Compute ATS locally (keyword set vs résumé, the JD keywords already exist from `analyze_jd`), and keep one schema-enforced LLM call for Impact/Skills/Readability. This is cheaper, exact for ATS, and removes a quarter of the JSON the model must get right.
- **Priority:** P1.

### 5c. Pipeline Parallelism
- **File(s):** `main.py:829-832`
- **Problem:** `extract_claims` (CPU/spaCy, in a thread) and `analyze_jd` (network LLM) run sequentially though they're independent.
- **Impact:** Latency — the spaCy pass (hundreds of ms) and the JD LLM call (seconds) serialize for no reason.
- **Recommendation:** `await asyncio.gather(asyncio.to_thread(extract_claims, ...), analyze_jd(...))`. (Scoring depends on `analyze_jd` output, so it can't move earlier; humanization depends on the final résumé, so it can't parallelize with scoring — those two are correctly sequential.)
- **Priority:** P2.

---

## 6. JSON Schema Enforcement

### 6a. Provider Support Audit (mid-2026, via LiteLLM)

| Model (slot) | `json_object` | `json_schema` (full) | Native mechanism | LiteLLM pass-through |
|--------------|:-------------:|:--------------------:|------------------|----------------------|
| Gemini 2.5 Flash-Lite (scorer, jd, humanizer, tools, profiles, jd-match) | ✅ | ✅ | `responseSchema` / `responseJsonSchema` (2.5+) | ✅ LiteLLM v1.81.3+ auto-converts `response_format`→`responseJsonSchema` for Gemini 2.0+ |
| Gemini 2.5 Flash (strategist) | ✅ | ✅ | same | ✅ |
| Groq Llama-3.1-8B (critic) | ✅ | ⚠️ flaky | JSON mode | ⚠️ `json_schema` raises `BadRequestError: unsupported tool_choice 'json_tool_call'` in LiteLLM; **use `json_object`** |
| Groq Llama-3.3-70B / GPT-OSS-120B (chat) | ✅ | ⚠️ | JSON mode | Chat uses native tool-calling already — structured args, no parsing risk |

**Takeaway:** Every JSON-parsing slot in scope runs on **Gemini**, which supports full `json_schema` enforcement through LiteLLM. The only Groq JSON slot (the critic) should use `json_object`, or move to Gemini.

### 6b. Migration Plan

**Scorer** (`agents/scorer.py`):
- Add at the call site (`_llm_complete`/`complete`): `response_format={"type": "json_schema", "json_schema": {"name": "resume_scores", "schema": <the schema at :111-158>, "strict": True}}`. The schema is already written and already imported into the function — just pass it.
- **Dead after enforcement:** the `_aliases` block (`:162-174`), the `defaults` backfill (`:176-189`), the `int/float`-to-object coercion (`:184-185`), and the `except ValueError → {}` path (`:28-30`). ~50 lines deleted.
- **Schema change:** make `overall` required (it already is at `:157`); the per-section `required` arrays are already complete.

**JD Analyzer** (`agents/jd_analyzer.py`):
- Same `response_format` with its schema (`:62-83`). **Dead after:** the silent `{}` fallback and the legacy backfills (`keywords`/`requirements`/`skills`). Make `seniority_level` an enum in the schema so invalid values are rejected at the provider instead of silently defaulting to `"mid"`.

**Humanizer critic** (`agents/humanizer.py:76-98`):
- This is Groq → use `response_format={"type": "json_object"}` (not schema). **Dead after:** `_clean_json` (`:13-20`). Keep a minimal `json.loads` with one log-and-continue. (Better: eliminate the call per 1.3/3a.)

### 6c. Reliability Impact

The current silent fallbacks mean failures are unmeasured, but the exposure is structural: the scorer's `except ValueError → {} → all-zero` path runs on *any* malformed response, and those zeros directly choose Phase 2 tools. With schema enforcement, malformed JSON becomes impossible for the Gemini slots, eliminating:
- the all-zero scorecard failure mode (the single highest-leverage reliability fix),
- the `jd_analyzer` "empty analysis → default seniority/empty keywords" failure,
- the humanizer's "critic JSON failed → skip refinement" no-op.

Recommend adding `litellm.enable_json_schema_validation = True` as a client-side belt-and-suspenders, plus a counter on any residual fallback so the failure rate becomes observable instead of silent.

### 6d. Edge Cases

- **Structure ≠ quality:** schema enforcement guarantees the *shape*, not that `missing_keywords` is non-empty or `score` is sane. Keep light validation: clamp scores to 0–100, and treat an all-zero schema-valid response as suspicious (retry once). So the `defaults` logic isn't fully deleted — it shrinks to *range validation*, not *structure backfill*.
- **Output token cost:** schema enforcement adds negligible output tokens on Gemini (it constrains, not expands). No measurable cost increase for the matrix.
- **Degradation:** if a future fallback model lacks schema support, `llm.py` should detect the provider and downgrade `json_schema`→`json_object`→best-effort `parse_llm_json`, logging which tier was used (mirrors the existing `cost_source` audit pattern). This belongs in `llm.py`, centralized, not per agent.

---

## 7. Production Readiness Gaps

### Finding 7.1: Rate limiting is per-process and IP-based
- **File(s):** `limiter.py:1-4`, `config.py:122` (`RATE_LIMIT_AUTH = "5/minute"`)
- **Problem:** slowapi counters live in-process → 2 workers = 2× the limit. `get_remote_address` sees the Azure ingress IP without trusted `X-Forwarded-For`, so either everyone shares one bucket or limiting is bypassed. No per-user limiting on the expensive `/run-pipeline`.
- **Impact:** Security/cost — a single user can exceed intended LLM spend; auth endpoints under-protected.
- **Recommendation:** Shared-store limiter (Redis/DB), trust the proxy header, and add per-user limits on pipeline runs (the `check_plan_limit`/`DailyUsageCounter` machinery already exists).
- **Priority:** P1.

### Finding 7.2: Cost tracking has three holes
- **File(s):** `agents/optimizer_agent.py:491-511` (strategist bypass), `:178-188` + `llm.py:138` (dropped tool logs), `:343, 404, 474` (tools omit `cost_usd`), `utils/cost.py:32` (`"zero"` source)
- **Problem:** (a) Strategist cost never recorded (4.9); (b) tool-call logs likely cancelled (4.8); (c) three of four tools call `state.add_tokens(in, out)` without the `cost_usd` arg that `keyword_inject_tool` passes (`:268`), so `ResumeState.cost_usd` undercounts; (d) when `litellm.completion_cost` fails and no provider rate is loaded, cost silently resolves to `0.0` with source `"zero"`. Net: reported `PipelineJob.cost_usd` understates true Phase 2 spend, possibly by the majority.
- **Impact:** P0 for the business — you cannot trust unit economics or per-user cost from this data.
- **Recommendation:** Fix 4.8/4.9, add `cost_usd` to all three tool `add_tokens` calls, and alert when `cost_source = "zero"` exceeds a threshold (the audit column already exists; `admin/analytics/cost-audit` already surfaces it).
- **Priority:** P0.

### Finding 7.3: No provider-failover; one same-model retry; no circuit breaker
- **File(s):** `llm.py:114-127, 184-204`
- **Problem:** `complete` retries once on the *same* model on transient errors, then raises. There's no fallback to a second provider when Gemini quota is exhausted or Groq is down, and no circuit breaker to stop hammering a failing provider. The model matrix in `config.py` has no `fallback_model` concept.
- **Impact:** Reliability — a Gemini quota event takes down the entire pipeline (every Phase 1/2/3 LLM step is Gemini).
- **Recommendation:** Introduce a `(primary, fallback)` per slot and have `llm.py` try the fallback on hard failure (LiteLLM has `litellm.acompletion` router/fallbacks support). Add a simple breaker per provider. This pairs naturally with the fallback column in the model matrix above.
- **Priority:** P1.

### Finding 7.4: Delta Lake is correctly *not* the rate-limit store — but verify
- **File(s):** `delta/writer.py`, `db/models.py` (`DailyUsageCounter`)
- **Problem:** Prior reviews flagged "Delta Lake misuse for rate limiting." In the current code, per-user quota is enforced via the transactional Postgres `DailyUsageCounter`, and Delta holds only analytics (daily usage rollups, scraped job matches). That separation is correct. The residual risk: Delta writes are synchronous-with-locks (`delta/writer.py:28-29`) on the request path for analytics, which can stall under load, and `vacuum_old_matches` hard-deletes on a 90-day window from a request-triggered path.
- **Impact:** Latency — analytics writes shouldn't block user-facing requests.
- **Recommendation:** Confirm no rate-limit decision reads Delta; move Delta writes fully off the request path (background task/queue). Keep Postgres authoritative for quotas.
- **Priority:** P2.

### Finding 7.5: Timeouts exist; retries/breakers are thin
- **File(s):** `llm.py:32` (`_CALL_TIMEOUT_S = 120`)
- **Problem:** 120s per call is long for a pipeline with up to ~12 sequential calls — worst-case wall-clock is minutes, and the stuck-job reaper only fires at 30 min. One retry doubles a hung call's cost in time.
- **Impact:** Latency/UX under provider slowness.
- **Recommendation:** Lower per-call timeout to ~30–45s for the cheap fast slots, keep the one retry but on the fallback model (7.3), and surface partial progress via the existing SSE events.
- **Priority:** P1.

### Finding 7.6: Dead code that would have helped is shipped unused
- **File(s):** `utils/cache.py`, `utils/token_utils.py`
- **Problem:** An LRU result cache and a token-budget truncator exist but are imported nowhere. The cache is exactly what would deduplicate the repeated scorer calls (3.1); the truncator is what would replace the crude `[:6000]` slices (3.5).
- **Impact:** Maintainability + missed optimization.
- **Recommendation:** Either wire them in (cache keyed on résumé+JD hash for scoring; truncator for boundary-aware cuts) or delete them so the codebase reflects reality.
- **Priority:** P2.

### Finding 7.7: Repo hygiene
- **File(s):** `rv/` (committed Windows virtualenv), `test_admin.db`, `test_analytics.db` (110 KB SQLite each, committed at repo root)
- **Problem:** A virtualenv and test databases are checked into version control.
- **Impact:** Repo bloat, potential secrets/path leakage, noisy diffs.
- **Recommendation:** Remove and add to `.gitignore`.
- **Priority:** P2.

### Finding 7.8: Phase 2 is undebuggable from logs
- **File(s):** `observability/trace.py`, `agents/optimizer_agent.py`
- **Problem:** The trace/`call_kind` plumbing is good for `llm.py` calls, but Phase 2's strategist never hits `llm.py` (4.9) and tool logs are dropped (4.8). A failed Phase 2 run leaves almost no trace — only `verbose=True` CrewAI stdout, which is not structured.
- **Impact:** Observability — you cannot reconstruct what the agent decided or spent from logs alone.
- **Recommendation:** Route all Phase 2 calls through `llm.py` (follows from 5a), tag them with a Phase 2 `call_kind`, and emit a structured per-iteration summary.
- **Priority:** P1.

---

## Prioritized Action List

### P0 — blocking / actively harmful
1. **De-tech the keyword prompts** so non-tech users aren't sabotaged — `optimizer_agent.py:249-251`, `rewriter.py:44-49` (2.1, 2.2).
2. **Enforce `json_schema` on the scorer** and kill the all-zero fallback — `scorer.py` (1.1, 6b).
3. **Make Phase 2 cost real:** route the strategist through `llm.py` (or remove it), fix the dropped tool logs, add `cost_usd` to all tools — `optimizer_agent.py`, `llm.py` (4.8, 4.9, 7.2).
4. **Delete the `[XX%]` placeholder instruction** from the rewriter (2.6).

### P1 — fix before launch
5. Replace CrewAI with the deterministic loop (5a, 3.4, 5.3) and route all calls through `llm.py`.
6. Hybrid scorer: local ATS + schema-enforced subjective scoring (5b, 3.1).
7. Enforce `json_schema` on `jd_analyzer` (and `profiles`/`jd` slots) (6b).
8. Generalize the fabrication guard: JD-relative persona check (2.3), tighten metric tolerance (4.3), alias-aware company match (4.4), guard titles/degrees/dates (4.6).
9. Shared-store, per-user rate limiting; trust proxy header (4.7, 7.1).
10. Provider failover + lower timeouts + breaker in `llm.py` (7.3, 7.5).
11. Reframe seniority rubrics off the tech ladder (2.4).
12. Cost-audit alerting on `cost_source="zero"` (7.2).

### P2 — post-launch
13. Prompt compression once schemas are enforced (2.8); cap critic feedback or merge it (3.3, 1.3).
14. Align JD truncation; boundary-aware truncation; wire or delete `cache.py`/`token_utils.py` (3.5, 7.6).
15. Single-source the `AGENT_MAX_ITER` and the NEEDS-WORK threshold (5.2, 2.7).
16. `en_core_web_lg` NER (4.5); delete `_clean_json` (4.2); chat → `gpt-oss-120b` (1.4); Delta off request path (7.4); repo hygiene (7.7).

---

## Sources (model landscape & schema support, mid-2026)

- Google Gemini API pricing — https://ai.google.dev/gemini-api/docs/pricing
- Gemini pricing overview (3.5 Flash / 3.1 Pro / 2.5 Lite, Jun 2026) — https://www.metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration
- Groq models & pricing 2026 (Llama 4 Scout, GPT-OSS 120B/20B, Llama 3.x) — https://www.cloudzero.com/blog/groq-pricing/ , https://artificialanalysis.ai/providers/groq
- DeepSeek pricing 2026 (V3/R1 → V4 Flash/Pro) — https://www.cloudzero.com/blog/deepseek-pricing/
- LiteLLM structured output / JSON mode — https://docs.litellm.ai/docs/completion/json_mode
- Gemini structured output (`responseSchema`/`responseJsonSchema`) — https://firebase.google.com/docs/ai-logic/generate-structured-output
- LiteLLM Gemini `responseJsonSchema` conversion (v1.81.3+) — https://github.com/google/adk-python/issues/4367

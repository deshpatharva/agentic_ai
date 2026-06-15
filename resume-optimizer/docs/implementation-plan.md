# Implementation Plan — In-House Agentic Pipeline

**Implementer:** Claude Sonnet 4.6, high reasoning effort.
**Goal:** execute the target design in `target-architecture.md` and the P0/P1 fixes in `architecture-review.md`, in dependency order, keeping the test suite green at every step.
**Context decisions:** see `design-dialogue-2026-06-15.md`.

---

## 0. Why we ARCHIVE dead code instead of deleting it (read first)

Dead/unused modules are **moved to `backend/_archive/`**, not deleted. Reasoning:

1. **Reversibility (pre-beta).** The product shape is still moving. Archiving is a one-line `git mv` to undo; deletion invites "where did that go" churn.
2. **They are reference implementations we intend to adapt.** `utils/cache.py` (result cache) and `utils/token_utils.py` (token truncation) are exactly the prior art for the **context-caching** (Phase 3) and **boundary-aware truncation** (Phase 6) tasks. Keep them readable, not buried in history.
3. **Keep the *live* tree honest.** After the CrewAI→native migration, several modules become dead. Moving them out makes the live surface (what the app actually runs) unambiguous, which matters most precisely when the architecture is changing.
4. **Git history is not discoverable enough** for a solo builder — an `_archive/` folder is.

**Archive policy:**
- Location: `backend/_archive/` with a `README.md` stating "Retired code, not imported by the live app. Kept for reference/reversibility."
- **Nothing in the live app may import from `_archive/`.**
- Exclude it from test collection: add `--ignore=_archive` (or `norecursedirs = _archive`) in `pytest.ini`. Do **not** add an `__init__.py` that makes it an importable package.
- **Every archive move must be verification-gated** (see T0.x) — confirm zero live references before moving, because the orphan analysis has at least one ambiguity (`result_cache` usage, see T0.2).

---

## 1. Ground rules for the implementer

- **All LLM calls route through `llm.py`** (`complete` / `complete_with_tools` / `stream_chat`). No agent/tool call may bypass it. No new agent-framework dependency (no CrewAI/LangChain/LangGraph/AutoGen).
- **Keep `pytest` green.** Run the full suite (`cd backend && pytest -q`) before and after each task. Add targeted tests with each task; never reduce coverage.
- **Small, atomic commits**, one per task ID, message prefixed with the task ID (e.g. `T1.2: enforce scorer JSON schema`).
- **Do not change public HTTP response shapes** (the React frontend consumes ~30 endpoints) unless a task explicitly says so. The pipeline's `score_combined`/`analyze_jd`/`humanize_resume` return dicts must keep their existing keys.
- **The fabrication guard stays a hard gate in every code path and every tier.** Never gate safety behind a plan.
- When a task says "delete dead code," that means **archive per §0**, not `rm`.
- Prefer **feature flags / config constants** for anything that changes runtime behavior so it can be toggled during beta.

## 2. Reference docs (read before starting)
- `docs/target-architecture.md` — the target design.
- `docs/architecture-review.md` — the audit + exact file:line findings (P0/P1/P2).
- `docs/design-dialogue-2026-06-15.md` — why these decisions were made.

---

## 3. Phased plan

> Ordering rationale: Phase 1 makes the system **measurable and correct** before we change its shape (you cannot safely refactor Phase 2 while its cost is invisible and the scorer silently returns zeros). Phase 2 is the architecture change. Phases 3–6 build on the native, observable base.

### Phase 0 — Archive dead code (verification-gated)

**T0.1 — Create the archive.** Create `backend/_archive/README.md` (policy from §0). Add `--ignore=_archive` to `pytest.ini`. Acceptance: `pytest -q` still collects/passes; `_archive` not traversed.

**T0.2 — Verify & archive `utils/token_utils.py` and `utils/cache.py`.**
- For EACH module, grep the whole `backend/` (excluding `tests/`) for: the module path (`utils.token_utils`, `utils.cache`), a bare `import`, AND every exported symbol name (e.g. `result_cache`, `ResultCache`, truncation fn names).
- **Ambiguity to resolve:** `agents/jd_analyzer.py` references a `result_cache` — confirm whether that resolves to `utils/cache.py` or something else. If `utils/cache.py` is in fact imported/used, it is **NOT dead** — do not archive it; instead carry it into T3.1 (context/result caching).
- Archive only modules with **zero** live references. Move with `git mv backend/utils/<mod>.py backend/_archive/<mod>.py`.
- Acceptance: full `pytest -q` green; `grep -rn "<mod>" backend --include=*.py | grep -v _archive | grep -v tests` returns nothing for archived modules.

**T0.3 — (deferred) Archive CrewAI modules** — performed in T2.6 after the native driver replaces them. Listed here so the archive set is complete: `agents/optimizer_agent.py` (CrewAI version) and any crew-only helpers in `orchestration/optimizer.py`.

---

### Phase 1 — Foundations & P0 correctness

**T1.1 — Add structured-output support to `llm.py`.**
- Add optional param to `complete()`: `response_format: dict | None = None`; pass it to `litellm.acompletion(...)`.
- Provider-aware degradation (centralize here, not per-agent):
  - Gemini → pass `json_schema` through (LiteLLM converts to `responseJsonSchema` for 2.x).
  - Groq → if a `json_schema` is requested, **coerce to `{"type":"json_object"}`** (Groq `json_schema` via LiteLLM errors with `unsupported tool_choice 'json_tool_call'`).
  - Unknown/unsupported → drop the param (already `drop_params=True`) and rely on `parse_llm_json`. Log which tier (schema/object/best-effort) was used via a new field.
- Optionally set `litellm.enable_json_schema_validation = True`.
- Acceptance: unit tests mocking each provider assert the correct `response_format` is forwarded/coerced/dropped. `tests/test_llm.py`, `tests/test_llm_json.py` extended.

**T1.2 — Enforce the scorer schema; delete dead fallback.** (`agents/scorer.py`)
- Thread the existing schema (`scorer.py:111-158`) through `_llm_complete` → `complete(..., response_format={"type":"json_schema","json_schema":{"name":"resume_scores","schema":<schema>,"strict":True}})`.
- After enforcement, **archive/remove** the now-dead `_aliases` block (`:162-174`), the structure-backfill in `defaults` (`:176-189`), and the int/float coercion. **Keep range validation** (clamp scores 0–100; treat an all-zero schema-valid response as suspect → one retry).
- Acceptance: new test feeds a malformed-but-now-impossible case is moot; add a test that a valid schema response with empty arrays still passes range validation; assert no `{}`/all-zero silent path remains. Update `tests/test_scorer_improvements.py`.

**T1.3 — Enforce the JD-analyzer schema; enum seniority.** (`agents/jd_analyzer.py`)
- Same pattern; make `seniority_level` an enum in the schema (`entry|mid|senior|lead`). Remove the silent `{}` fallback and legacy backfills once enforced (keep a single logged degradation path).
- Acceptance: `tests/test_jd_analyzer_improvements.py` extended; invalid seniority can no longer silently become `"mid"`.

**T1.4 — Field-agnostic keyword prompts (P0 bias fix).**
- `agents/optimizer_agent.py:245-265` (keyword_inject) and `agents/rewriter.py:44-49`: remove the tech-vocabulary requirement and the "REJECT recruiting/HR/sales/legal/finance" exclusion. Replace with: *"Inject only keywords that match the candidate's actual profession and the target role's domain. Skip any keyword implying a job function the candidate has never performed, regardless of field."*
- **Note:** these prompt strings move into the new tool module in Phase 2 — implement the fix now and carry it forward.
- Acceptance: add a test using a non-tech résumé+JD (e.g. nursing) asserting domain keywords are not stripped. New `tests/test_field_agnostic.py`.

**T1.5 — Remove the `[XX%]` placeholder instruction (P0).** (`agents/rewriter.py:53-54`)
- Delete the "add a realistic placeholder `[XX%]`" instruction; align with the rest of the pipeline (never fabricate numbers). Keep `utils/text_sanitizer.py` as defense-in-depth.
- Acceptance: test asserts rewriter output contains no `[XX%]`/`[N]` placeholders given a metric-less bullet. Update `tests/test_rewriter_improvements.py`.

**T1.6 — Phase-2 cost completeness (interim).** (`agents/optimizer_agent.py`)
- Add the missing `cost_usd` arg to `state.add_tokens(...)` in `bullet_strengthen_tool` (`:343`), `skills_rewrite_tool` (`:404`), `section_humanize_tool` (`:474`).
- Note the dropped-log root cause (`asyncio.run` cancelling `_record_call`) — **fully fixed in T2.4** when Phase 2 goes async. If T2 is not done in the same pass, add an interim `await` of the record in the tool path.
- Acceptance: `tests/test_cost_tracking.py` / `tests/test_cost_flow.py` assert all four tools contribute cost.

---

### Phase 2 — Native A+C agent (replace CrewAI)

**T2.1 — Extract tools into async functions.** New `agents/tools.py` (or `orchestration/tools.py`).
- Port the 4 tool bodies from `optimizer_agent.py` into **plain `async def`** functions over `ResumeState`, calling `await llm.complete(...)` directly (no `@tool`, no `asyncio.run`). Signatures mirror today's CSV params. Carry the T1.4 prompt fixes.
- Keep `ResumeState` (move it here or to a small `state.py`); keep the budget check.
- Acceptance: unit tests call each tool against a fixture `ResumeState` and assert section mutation + token accounting. New `tests/test_agent_tools.py`.

**T2.2 — Build the A+C driver.** New `orchestration/agent_loop.py`.
- Implement the tool-calling loop with `llm.complete_with_tools(messages, MODEL_OPTIMIZER, TOOLS)` + the reflection loop (re-score via `score_combined` + `fabrication_guard`, feed deltas/flags back). Follow the sketch in `architecture-review.md` §5a and `target-architecture.md` §3.
- Budget-gated (`AGENT_TOKEN_BUDGET`), bounded turns and reflections (single source the constants from `config.py`; remove the `AGENT_MAX_ITER` shadow at `optimizer_agent.py:54`).
- Tag calls with a Phase-2 `call_kind` (observability).
- Acceptance: integration test with a mocked LLM that returns scripted tool_calls then stops; assert the loop executes tools, reflects, and terminates on target/guard. New `tests/test_agent_loop.py`.

**T2.3 — Wire the driver into orchestration.** (`orchestration/optimizer.py`)
- Replace `_run_crew_sync`/CrewAI `Crew` with a call to the A+C driver. Keep `_deterministic_fallback` (rewriter) for the no-sections/empty case.
- Preserve the existing `run_optimization_async` signature and return dict so `main.py` is unchanged.
- Acceptance: `tests/test_pipeline_integration.py`, `tests/test_optimizer_improvements.py`, `tests/test_agent_improvements.py` pass against the new driver.

**T2.4 — Make Phase 2 fully async.** (`main.py`, `orchestration/optimizer.py`)
- Remove `asyncio.to_thread(_run_crew_sync, ...)` and all `asyncio.run(...)` in the Phase-2 path; the driver runs on the event loop with `await`. This also fixes the dropped `_record_call` logs (review 4.8).
- Acceptance: a test asserts a Phase-2 tool call produces an `LlmCallLog` row (the bug it fixes). No `asyncio.run` remains under `agents/`/`orchestration/`.

**T2.5 — Remove CrewAI.**
- Delete CrewAI imports; remove `crewai` and `pysqlite3-binary` from `requirements.txt`; remove the `pysqlite3` shim (`main.py:22-29`) and the HF suppression (`main.py:31-34`) if nothing else needs them (verify).
- Acceptance: app imports and boots without `crewai`/`chromadb` installed; full suite green.

**T2.6 — Archive the retired modules (executes T0.3).**
- `git mv agents/optimizer_agent.py backend/_archive/`. Move any crew-only helpers. Confirm no live import remains.
- Acceptance: `grep -rn "optimizer_agent" backend --include=*.py | grep -v _archive` returns only comments/none; suite green.

---

### Phase 3 — Memory & context caching

**T3.1 — Context caching for stable prefixes.** (`agents/scorer.py`, `agents/humanizer.py`, the new tools)
- Use `llm.complete(prompt, model, cached_prefix=<stable block>)` for the **scoring rubric**, the **JD**, and the **résumé body** where they repeat across calls in a run (scorer re-scores, tools, humanizer). Mechanism already exists (`llm.py:101-108`).
- If `utils/cache.py` was retained (T0.2), also wire **result caching** for identical re-scores (same résumé+JD hash → cached scorecard).
- Acceptance: a test asserts `cached_prefix` is passed for the rubric/JD; measure input-token reduction in an integration test (assert fewer billed input tokens on the 2nd identical score call). Respect the min-token threshold (don't cache tiny prompts).

**T3.2 — Long-term memory (fact memory first).** (`db/models.py`, pipeline)
- Persist the **claims ledger per `Profile`** (new column/table) at pipeline completion; load it at pipeline start and pass to the guard/agent so verification spans the user's history, not just the current résumé.
- Keep retrieval as **keyed lookups** (by `user_id`/`profile_id`). **No vector DB.** Add an Alembic migration.
- Acceptance: migration test (`tests/test_migrations.py`) passes; a test asserts a fact verified in run N is available in run N+1.
- (Style/outcome memory: optional follow-up, not required for beta.)

---

### Phase 4 — Pro-tier debate (flag/plan-gated)

**T4.1 — Verifier pass in BOTH tiers (safety floor).** Add a single `complete(...)` verifier that checks the final draft against the claims ledger and flags unsupported claims; runs for every tier. Acceptance: test asserts flagged claims surface in the result for a planted over-claim.

**T4.2 — Two-agent debate driver.** New `orchestration/debate_loop.py`: optimizer ↔ skeptical-reviewer (separate system prompts/contexts), bounded rounds + explicit termination (no new objections / `max_rounds`). All calls via `llm.py`; reviewer on `MODEL_OPTIMIZER` (or a Flash model). Reuses the Phase-2 tools/state/guard (shared substrate). Acceptance: integration test with mocked agents asserts bounded rounds and that a reviewer objection triggers a revision.

**T4.3 — Tier gating.** Select driver (`agent_loop` vs `debate_loop`) by the user's plan/tier via a config/flag; default everyone to `agent_loop` for beta. Acceptance: test asserts plan→driver mapping; no plan can disable the guard/verifier.

---

### Phase 5 — Scalability

**T5.1 — Shared session state.** Replace the in-memory `_sessions` dict with a shared store (Postgres table or Redis) OR document that Phase 2 is single-process-bounded and pin sessions accordingly. Acceptance: a test simulates two workers and asserts session visibility/cleanup semantics.

**T5.2 — Shared, per-user rate limiting.** Configure slowapi with a shared backend; key limits per authenticated user on `/run-pipeline`; trust `X-Forwarded-For` behind Azure. Acceptance: `tests/test_ratelimit.py` extended to assert per-user keying and that N workers don't multiply the limit.

**T5.3 — Delta writes off the request path.** Move `write_daily_usage`/`write_job_matches` to a background task/queue. Acceptance: `tests/test_delta_writer.py` / `tests/test_analytics.py` green; request handlers no longer block on Delta locks.

---

### Phase 6 — Fabrication-guard hardening (review §4b)

**T6.1** Tighten `_metric_attested` (`fabrication_guard.py:65-74`): exact/≤2% for percentages, match within the **same claim/bullet**, not global text.
**T6.2** Alias-aware `_company_attested` (`:77-83`): normalize acronyms/aliases (MSFT↔Microsoft, AWS↔Amazon Web Services) before fuzzy match.
**T6.3** Extend the guard to attest **titles, degrees, dates** (already in the ledger, `fact_extractor.py:88-107`): no promotion beyond ledger, exact degree match, no date-range widening.
**T6.4** Generalize `_PERSONA_TERMS` (`:30-37`) to a **JD-relative** domain check (flag terminology from a domain that's neither the résumé's nor the JD's). If keeping a static list, make it data-driven per top-level industry.
**T6.5** (optional) Adapt the archived `utils/token_utils.py` for boundary-aware truncation; align the JD slice across `scorer.py:107` (`[:3000]`) and `jd_analyzer.py:58` (`[:4000]`).
- Acceptance: `tests/test_claims_improvements.py` extended with planted title/degree/date/metric/company fabrications, each caught.

---

## 4. Definition of done

- Full `pytest -q` green; new tests added per task.
- No live module imports from `_archive/`; CrewAI/`chromadb`/`pysqlite3` no longer required to boot.
- Every LLM call (Phase 1/2/3, both drivers) produces an `LlmCallLog` row; Phase-2 cost is non-zero and attributable per `call_kind`.
- Scorer/JD-analyzer use enforced schemas; no silent `{}`/all-zero path remains.
- Non-tech résumé test passes (no domain keywords stripped); no `[XX%]` placeholders emitted.
- Fabrication guard runs in every path/tier and catches planted metric/company/title/degree/date fabrications.
- App boots on uvicorn, Phase 2 fully async (no `asyncio.run`/`to_thread` in the agent path).

## 5. Suggested commit / PR sequence

1. PR-1 — Phase 0 + Phase 1 (archive + foundations + P0 fixes). Low risk, high value, independently shippable.
2. PR-2 — Phase 2 (native A+C, remove CrewAI). The architecture change; largest review surface.
3. PR-3 — Phase 3 (memory + context caching).
4. PR-4 — Phase 4 (Pro debate, flag-gated, default off).
5. PR-5 — Phase 5 (scalability) + Phase 6 (guard hardening), can split.

Implement in this order; each PR must leave `main` releasable and the suite green.

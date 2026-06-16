# Agentic Pipeline — PR-3..5: Memory, Context Caching, Pro Tier, Scalability, Guard Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
>
> **⚠️ EXPAND BEFORE EXECUTING:** These tasks are specified at task + acceptance level only. Their exact RED-first tests depend on the native driver's final API from **PR-2** (`agent_loop.py`, `agents/tools.py`, `ResumeState`). After PR-2 merges, expand each task into Step-1 failing tests in the PR-1/PR-2 style before implementing. Do not implement these from this file as-is.

**Goal:** Build on the native, observable base: per-run + per-user memory, Gemini context caching, the flag-gated Pro debate tier, horizontal-scale fixes, and fabrication-guard hardening.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL + Alembic, LiteLLM, Redis (optional, for shared state), pytest-asyncio.
**Run tests from:** `resume-optimizer/` · **Test command:** `python -m pytest backend/tests/<file> -v`

**Reference:** `docs/target-architecture.md` §§5-9, `docs/architecture-review.md` §§3,4b,4c,6,7.

---

## PR-3 — Memory & context caching

### Task 3.1: Context caching for stable prefixes
- [ ] Expand to RED-first, then: use `complete(prompt, model, cached_prefix=<stable block>)` for the **rubric**, **JD**, and **résumé body** where reused within a run (scorer re-scores, tools, humanizer). Mechanism exists at `llm.py:101-108`.
- [ ] If `utils/cache.py` was retained (PR-1 T0.2), wire **result caching** for identical re-scores (résumé+JD hash → cached scorecard).
- [ ] Respect the provider min-token threshold; don't cache tiny prompts.
- **Acceptance:** a test asserts `cached_prefix` is passed for rubric/JD; an integration test shows reduced billed input tokens on a 2nd identical score call.

### Task 3.2: Long-term fact memory (claims ledger per user)
- [ ] New Alembic migration: persist the **claims ledger per `Profile`** (column/table). Load at pipeline start; pass to guard + agent so verification spans the user's history.
- [ ] Retrieval = keyed lookups by `user_id`/`profile_id`. **No vector DB.**
- **Acceptance:** `tests/test_migrations.py` green; a test asserts a fact verified in run N is available in run N+1.
- (Style/outcome memory: optional follow-up; not required for beta.)

---

## PR-4 — Pro tier (flag-gated, default OFF)

### Task 4.1: Verifier pass in BOTH tiers (safety floor)
- [ ] A single `complete(...)` verifier checks the final draft against the claims ledger and flags unsupported claims; runs in **every** tier.
- **Acceptance:** a planted over-claim is flagged in the result for both Standard and Pro.

### Task 4.2: Two-agent debate driver
- [ ] New `orchestration/debate_loop.py`: optimizer ↔ skeptical-reviewer (separate system prompts/contexts), bounded rounds + explicit termination (no new objections / `max_rounds`). All calls via `llm.py`. Reuse PR-2 tools/state/guard (shared substrate).
- **Acceptance:** integration test asserts bounded rounds and that a reviewer objection triggers a revision; both agents log to `LlmCallLog`.

### Task 4.3: Tier gating
- [ ] Select driver (`agent_loop` vs `debate_loop`) by user plan via a config flag; default everyone to `agent_loop` for beta. A plan can never disable the guard/verifier.
- **Acceptance:** test asserts plan→driver mapping and that safety runs regardless of plan.

---

## PR-5 — Scalability + guard hardening (split if large)

### Task 5.1: Shared session state
- [ ] Replace in-memory `_sessions` (`optimizer_agent.py:135`, or its PR-2 successor) with a shared store (Postgres/Redis), OR document single-process pinning. **Acceptance:** a two-worker test asserts session visibility/cleanup semantics.

### Task 5.2: Shared, per-user rate limiting
- [ ] slowapi with a shared backend; per-user keys on `/run-pipeline`; trust `X-Forwarded-For` behind Azure. **Acceptance:** `tests/test_ratelimit.py` asserts per-user keying and that N workers don't multiply the limit.

### Task 5.3: Delta writes off the request path
- [ ] Move `write_daily_usage`/`write_job_matches` to a background task/queue. **Acceptance:** `tests/test_delta_writer.py`/`test_analytics.py` green; handlers no longer block on Delta locks.

### Task 6.1-6.4: Fabrication-guard hardening (`agents/fabrication_guard.py`)
- [ ] **6.1** Tighten `_metric_attested` (`:65-74`): exact/≤2% for percentages, match within the **same claim/bullet**, not global text.
- [ ] **6.2** Alias-aware `_company_attested` (`:77-83`): normalize acronyms/aliases (MSFT↔Microsoft, AWS↔Amazon Web Services) before fuzzy match.
- [ ] **6.3** Extend the guard to attest **titles, degrees, dates** (already in the ledger, `fact_extractor.py:88-107`): no promotion beyond ledger, exact degree match, no date-range widening.
- [ ] **6.4** Generalize `_PERSONA_TERMS` (`:30-37`) to a **JD-relative** domain check (flag terminology from a domain that is neither the résumé's nor the JD's).
- [ ] **6.5 (optional)** Adapt archived `utils/token_utils.py` for boundary-aware truncation; align the JD slice across `scorer.py:107` (`[:3000]`) and `jd_analyzer.py:58` (`[:4000]`).
- **Acceptance:** `tests/test_claims_improvements.py` extended with planted title/degree/date/metric/company fabrications, each caught.

---

## Done when
- Context caching + per-user fact memory live; no vector DB introduced.
- Pro debate driver exists behind a flag (default off), with the verifier + guard running in every tier.
- Session + rate-limit state shared; Delta off the request path.
- Guard catches planted title/degree/date/metric/company fabrications.

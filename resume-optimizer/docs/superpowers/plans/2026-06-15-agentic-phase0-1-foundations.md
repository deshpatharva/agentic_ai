# Agentic Pipeline — PR-1: Archive + Foundations & P0 Correctness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pipeline measurable and correct before changing its shape — archive confirmed-dead code, enforce JSON schemas (kill the silent all-zero scorer), remove the tech-industry bias and the `[XX%]` fabrication instruction, and complete Phase-2 cost accounting. This is PR-1 of 5 (see `docs/implementation-plan.md`).

**Architecture:** Ordered lowest→highest blast radius: archive (structural) → `llm.py` structured-output primitive → per-agent schema enforcement → prompt fixes → cost completeness. Each task is independently shippable. No behavior change to HTTP response shapes. No new dependencies.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, LiteLLM, pytest-asyncio.
**Run tests from:** `resume-optimizer/`
**Test command (portable):** `python -m pytest backend/tests/<file> -v` (owner's Windows box: `C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/<file> -v`)
**Before opening the PR:** run the full suite — `python -m pytest backend -q`.

**Reference:** `docs/target-architecture.md` (design), `docs/architecture-review.md` (findings w/ file:line), `docs/design-dialogue-2026-06-15.md` (rationale).

---

## File Map

```
New files:
  backend/_archive/README.md             — archive policy (see §0 of implementation-plan.md)
  backend/tests/test_structured_output.py — llm.py response_format behavior
  backend/tests/test_field_agnostic.py    — non-tech résumé keyword retention

Modified files:
  resume-optimizer/pytest.ini             — exclude _archive from collection
  backend/llm.py                          — add response_format param + provider-aware degradation
  backend/agents/scorer.py                — enforce schema; delete alias/structure-backfill; keep range validation
  backend/agents/jd_analyzer.py           — enforce schema; seniority enum; drop silent {} fallback
  backend/agents/optimizer_agent.py       — field-agnostic keyword prompt; cost_usd on all tools
  backend/agents/rewriter.py              — field-agnostic prompt; remove [XX%] instruction
  backend/tests/test_scorer_improvements.py     — extend
  backend/tests/test_jd_analyzer_improvements.py — extend
  backend/tests/test_rewriter_improvements.py    — extend
  backend/tests/test_cost_tracking.py            — extend

Archived (git mv, verification-gated):
  backend/utils/token_utils.py  -> backend/_archive/token_utils.py   (if confirmed dead)
  backend/utils/cache.py        -> backend/_archive/cache.py         (ONLY if confirmed dead — see T0.2)
```

---

## Task 0.1: Create the archive + exclude from tests

**Files:** new `backend/_archive/README.md`; modify `resume-optimizer/pytest.ini`

- [ ] **Step 1: Create `backend/_archive/README.md`** with: "Retired code — NOT imported by the live app. Kept for reference and reversibility (pre-beta). Nothing in the live app may import from `_archive/`."
- [ ] **Step 2: Exclude from pytest.** Add to `resume-optimizer/pytest.ini`:
  ```ini
  [pytest]
  norecursedirs = _archive
  ```
  (preserve existing keys). Do **not** add `backend/_archive/__init__.py`.
- [ ] **Step 3: Verify** — `python -m pytest backend -q` still collects and passes; confirm `_archive` is not traversed.

## Task 0.2: Verify & archive dead utils

**Files:** `backend/utils/token_utils.py`, `backend/utils/cache.py`

- [ ] **Step 1: Prove dead (RED = grep returns nothing live).** For each module, grep the live tree for the path AND every exported symbol:
  ```
  grep -rn "token_utils" backend --include=*.py | grep -v _archive | grep -v /tests/
  grep -rn "from utils.cache\|import cache\|result_cache\|ResultCache" backend --include=*.py | grep -v _archive | grep -v /tests/
  ```
- [ ] **Step 2: Resolve the `cache.py` ambiguity.** `agents/jd_analyzer.py` references a `result_cache`. If it resolves to `utils/cache.py`, **cache.py is NOT dead** — skip archiving it and instead carry it into PR-3 (context/result caching). Only archive what Step 1 proves unreferenced.
- [ ] **Step 3: Archive** confirmed-dead modules: `git mv backend/utils/<mod>.py backend/_archive/<mod>.py`.
- [ ] **Step 4: Verify** — full suite green; the grep from Step 1 returns nothing for archived modules.

## Task 1.1: Structured-output primitive in `llm.py`

**Files:** Modify `backend/llm.py`; new `backend/tests/test_structured_output.py`

- [ ] **Step 1: Write failing tests** — `backend/tests/test_structured_output.py`:
  ```python
  """response_format is forwarded/coerced/dropped per provider."""
  import sys, os
  from pathlib import Path
  from unittest.mock import AsyncMock, patch
  import pytest
  sys.path.insert(0, str(Path(__file__).parent.parent))
  os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
  os.environ.setdefault("BOOTSTRAP_SECRET", "x" * 32)
  import llm

  def _fake_response():
      class M: ...
      r = M(); r.choices = [M()]; r.choices[0].message = M()
      r.choices[0].message.content = '{"ok": true}'
      r.usage = M(); r.usage.prompt_tokens = 10; r.usage.completion_tokens = 5
      return r

  @pytest.mark.asyncio
  async def test_gemini_gets_json_schema():
      schema = {"type": "json_schema", "json_schema": {"name": "s", "schema": {"type": "object"}}}
      with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_response())) as m:
          await llm.complete("p", "gemini/gemini-2.5-flash-lite", response_format=schema)
      assert m.call_args.kwargs["response_format"] == schema

  @pytest.mark.asyncio
  async def test_groq_schema_coerced_to_json_object():
      schema = {"type": "json_schema", "json_schema": {"name": "s", "schema": {"type": "object"}}}
      with patch("litellm.acompletion", new=AsyncMock(return_value=_fake_response())) as m:
          await llm.complete("p", "groq/llama-3.1-8b-instant", response_format=schema)
      assert m.call_args.kwargs["response_format"] == {"type": "json_object"}
  ```
- [ ] **Step 2: Implement.** Add `response_format: dict | None = None` to `complete()` (and thread through where useful). Before `litellm.acompletion`, apply provider-aware handling:
  - provider `gemini`/`vertex_ai` → pass `json_schema` through unchanged.
  - provider `groq` → if `response_format["type"] == "json_schema"`, replace with `{"type": "json_object"}`.
  - else → omit it (rely on `drop_params`).
  Record which mode was used (add a `response_mode` field to the `LlmCallLog` kwargs if cheap; otherwise log at debug). Optionally set `litellm.enable_json_schema_validation = True` at module load.
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_structured_output.py backend/tests/test_llm.py backend/tests/test_llm_json.py -v`.

## Task 1.2: Enforce the scorer schema; delete dead fallback

**Files:** Modify `backend/agents/scorer.py`, `backend/tests/test_scorer_improvements.py`

- [ ] **Step 1: Write failing tests** — assert (a) `complete` receives a `response_format` carrying the scorer schema; (b) a valid response with empty arrays + zero scores passes through range-validation without being silently rewritten; (c) no `_aliases`/structure-backfill path remains (e.g. patch `complete` to return a flat-int payload and assert it is now rejected/retried, not coerced):
  ```python
  @pytest.mark.asyncio
  async def test_scorer_passes_response_format():
      from unittest.mock import AsyncMock, patch
      from agents import scorer
      payload = '{"ats":{"score":80,"missing_keywords":[],"matched_keywords":[],"keyword_coverage_pct":0.0},' \
                '"impact":{"score":75,"weak_bullets":[],"strong_bullets":[],"has_quantified_achievements":true},' \
                '"skills_gap":{"score":70,"missing_skills":[],"matched_skills":[],"critical_missing":[]},' \
                '"readability":{"score":85,"issues":[],"worst_section":"experience","has_summary":true,"tense_consistent":true},' \
                '"overall":78}'
      async def fake(prompt, model, **kw):
          fake.kw = kw
          return {"text": payload, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}
      with patch.object(scorer, "complete", new=fake):
          out = await scorer.score_combined("résumé", "jd")
      assert "response_format" in fake.kw
      assert out["text"]["ats"]["score"] == 80
  ```
- [ ] **Step 2: Implement.** Thread the existing schema (`scorer.py:111-158`) into `_llm_complete` → `complete(..., response_format={"type":"json_schema","json_schema":{"name":"resume_scores","schema":<schema>,"strict":True}})`. Archive/remove `_aliases` (`:162-174`) and the structure-backfill/coercion in `defaults` (`:176-189`). **Keep** range validation: clamp scores to 0–100; if all four scores are 0 on a schema-valid response, retry once, then accept. Remove the `except ValueError → {}` silent path (a parse failure under enforcement is now a real error → log + single retry).
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_scorer_improvements.py -v`.

## Task 1.3: Enforce the JD-analyzer schema; seniority enum

**Files:** Modify `backend/agents/jd_analyzer.py`, `backend/tests/test_jd_analyzer_improvements.py`

- [ ] **Step 1: Write failing tests** — assert `response_format` is passed with the schema; assert an out-of-enum `seniority_level` can no longer be silently returned as `"mid"` (it's constrained at the schema).
- [ ] **Step 2: Implement.** Pass the schema (`jd_analyzer.py:62-83`) via `response_format`; declare `seniority_level` as an enum (`entry|mid|senior|lead`). Remove the silent `{}` fallback and legacy backfills (`keywords`/`requirements`/`skills`) — keep one logged degradation path. Preserve the result-cache behavior.
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_jd_analyzer_improvements.py -v`.

## Task 1.4: Field-agnostic keyword prompts (P0 bias fix)

**Files:** Modify `backend/agents/optimizer_agent.py`, `backend/agents/rewriter.py`; new `backend/tests/test_field_agnostic.py`

- [ ] **Step 1: Write failing test** — assert the keyword-inject prompt no longer contains the tech-vocabulary requirement or the HR/sales/legal/finance rejection, and that a non-tech keyword set survives:
  ```python
  def test_keyword_prompt_is_field_agnostic():
      import agents.optimizer_agent as oa, inspect
      src = inspect.getsource(oa)
      assert "tools, languages, frameworks, platforms" not in src
      assert "recruiting, talent acquisition" not in src
  ```
- [ ] **Step 2: Implement.** In `optimizer_agent.py:245-265` and `rewriter.py:44-49`, replace the tech-only rules with: *"Inject only keywords that match the candidate's actual profession and the target role's domain. Skip any keyword implying a job function the candidate has never performed, regardless of field."* (These strings move into the new tool module in PR-2 — keep the fix.)
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_field_agnostic.py -v`.

## Task 1.5: Remove the `[XX%]` placeholder instruction (P0)

**Files:** Modify `backend/agents/rewriter.py`, `backend/tests/test_rewriter_improvements.py`

- [ ] **Step 1: Write failing test** — assert the rewriter system prompt no longer instructs adding `[XX%]`, and that output of a metric-less bullet contains no `[XX%]`/`[N]` placeholder (mock the LLM to passthrough; rely on prompt content assertion + `text_sanitizer`).
- [ ] **Step 2: Implement.** Delete the "add a realistic placeholder `[XX%]`" instruction at `rewriter.py:53-54`; align with "never fabricate numbers." Keep `utils/text_sanitizer.py` as defense-in-depth.
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_rewriter_improvements.py -v`.

## Task 1.6: Phase-2 cost completeness

**Files:** Modify `backend/agents/optimizer_agent.py`, `backend/tests/test_cost_tracking.py`

- [ ] **Step 1: Write failing test** — call each of the four tools with `_call_llm` mocked to return a non-zero `cost_usd`; assert `ResumeState.cost_usd` accumulates from **all four** (today only `keyword_inject` passes cost).
- [ ] **Step 2: Implement.** Add the `cost_usd` arg to `state.add_tokens(...)` in `bullet_strengthen_tool` (`:343`), `skills_rewrite_tool` (`:404`), `section_humanize_tool` (`:474`). (The dropped-log root cause — `asyncio.run` cancelling `_record_call` — is fixed in PR-2/T2.4 when Phase 2 goes async; if PR-2 is not in the same pass, `await` the record in the tool path as an interim.)
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_cost_tracking.py backend/tests/test_cost_flow.py -v`.

---

## Done when
- Full suite green; new tests added.
- `_archive/` exists, excluded from collection, imported by nothing live.
- Scorer + JD-analyzer use enforced schemas; no silent `{}`/all-zero path remains.
- Keyword prompts are field-agnostic (non-tech test passes); no `[XX%]` emitted.
- All four Phase-2 tools contribute `cost_usd`.

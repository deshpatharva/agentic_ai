# Agentic Pipeline — PR-2: Native A+C Agent (replace CrewAI)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the CrewAI Phase-2 agent with an in-house, async, observable **A+C loop** (tool-calling reasoning + reflection), routed entirely through `llm.py`. Preserve genuine agency (the model chooses tools/order/termination) while removing CrewAI's overhead, its `llm.py` bypass, and the thread/`asyncio.run` workaround.

**Architecture:** Build the new pieces alongside the old (substrate → driver → wire-in → async → remove CrewAI → archive), so the suite stays green at each step. The public `run_optimization_async(...)` signature and its return dict are **unchanged** — `main.py` is not modified except for the async cleanup in T2.4. Prerequisite: PR-1 merged (schema enforcement + cost completeness).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, LiteLLM (native tool-calling via `complete_with_tools`), pytest-asyncio.
**Run tests from:** `resume-optimizer/`
**Test command (portable):** `python -m pytest backend/tests/<file> -v`
**Before opening the PR:** full suite — `python -m pytest backend -q` — and confirm the app boots without `crewai`/`chromadb` installed.

**Reference:** `docs/target-architecture.md` §§2-4, `docs/architecture-review.md` §5a (code sketch), §4.8/4.9 (the bugs this fixes).

---

## File Map

```
New files:
  backend/agents/tools.py              — 4 tools as plain async fns over ResumeState (+ ResumeState if moved)
  backend/orchestration/agent_loop.py  — the A+C driver (tool-calling loop + reflection)
  backend/tests/test_agent_tools.py    — tool unit tests
  backend/tests/test_agent_loop.py     — driver integration tests

Modified files:
  backend/orchestration/optimizer.py   — call agent_loop instead of CrewAI Crew; keep _deterministic_fallback
  backend/main.py                      — remove to_thread/asyncio.run for Phase 2; drop pysqlite3 shim + HF suppression if unused
  backend/requirements.txt             — remove crewai, pysqlite3-binary
  backend/config.py                    — single-source AGENT_MAX_ITER (remove the shadow)
  backend/tests/test_pipeline_integration.py / test_optimizer_improvements.py / test_agent_improvements.py — adapt

Archived (git mv):
  backend/agents/optimizer_agent.py -> backend/_archive/optimizer_agent.py
```

---

## Task 2.1: Tools as async functions over shared state

**Files:** new `backend/agents/tools.py`; new `backend/tests/test_agent_tools.py`

- [ ] **Step 1: Write failing tests** — for each tool, build a fixture `ResumeState`, mock `llm.complete` to return edited section text + tokens/cost, call the tool, assert: the target section is updated, tokens+cost accumulate, the budget guard short-circuits when over `AGENT_TOKEN_BUDGET`:
  ```python
  @pytest.mark.asyncio
  async def test_keyword_inject_updates_section_and_cost():
      from agents import tools
      st = tools.ResumeState(sections={"summary": "Built things.", "experience": "Did work."})
      async def fake(prompt, model, **kw):
          return {"text": "Built scalable things.", "input_tokens": 20, "output_tokens": 10, "cost_usd": 0.001}
      with patch.object(tools, "complete", new=fake):
          msg = await tools.keyword_inject(st, missing_keywords_csv="scalable", target_sections_csv="summary")
      assert "scalable" in st.get_section("summary")
      assert st.cost_usd > 0
  ```
- [ ] **Step 2: Implement.** Port the 4 tool bodies from `agents/optimizer_agent.py` into plain `async def keyword_inject / bullet_strengthen / skills_rewrite / section_humanize` over `ResumeState`, calling `await complete(...)` (no `@tool`, no `asyncio.run`). Move `ResumeState` here (or to `agents/state.py`). Carry PR-1's field-agnostic prompt fix and the cost accounting. Keep the budget check and the "no section found" fallbacks.
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_agent_tools.py -v`.

## Task 2.2: The A+C driver

**Files:** new `backend/orchestration/agent_loop.py`; new `backend/tests/test_agent_loop.py`

- [ ] **Step 1: Write failing test** — drive the loop with a fake `complete_with_tools` that returns scripted `tool_calls` on turn 1 then an empty `tool_calls` (done) on turn 2; mock `score_combined` to return below-target then at-target, and `fabrication_guard` to return no gaps; assert tools executed, reflection ran, and the loop terminated on target:
  ```python
  @pytest.mark.asyncio
  async def test_loop_runs_tools_then_reflects_then_stops():
      from orchestration import agent_loop
      # fake message objects with .tool_calls / .content; see complete_with_tools contract
      ...
      result = await agent_loop.run_agent(state, scores, jd_text="jd", jd_keywords=[], ledger=ledger,
                                          original_resume="orig")
      assert called_tools and reflected and result  # terminated cleanly
  ```
- [ ] **Step 2: Implement.** Per `target-architecture.md` §3 / review §5a: a tool-calling loop using `complete_with_tools(messages, MODEL_OPTIMIZER, TOOLS)` (dispatch via a name→async-fn map, append tool observations), wrapped in a reflection loop (re-score via `score_combined` + `fabrication_guard`; feed deltas + flagged claims back; exit on target+no-flags / budget / max-reflections). Budget-gated by `AGENT_TOKEN_BUDGET`. Single-source the iteration constants from `config.py` (remove the `AGENT_MAX_ITER` shadow at `optimizer_agent.py:54`). Tag calls with a Phase-2 `call_kind`.
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_agent_loop.py -v`.

## Task 2.3: Wire the driver into orchestration

**Files:** Modify `backend/orchestration/optimizer.py`

- [ ] **Step 1: RED** — adapt `test_optimizer_improvements.py`/`test_agent_improvements.py` to target the new driver (mock the loop, assert `run_optimization_async` returns the same dict shape `{text,input_tokens,output_tokens,cost_usd,iterations,fallback}`).
- [ ] **Step 2: Implement.** Replace `_run_crew_sync` + CrewAI `Crew` with a call to `agent_loop.run_agent(...)`. Keep `_deterministic_fallback` (rewriter) for the no-sections / exception / no-change cases. Keep `register_session`/`cleanup_session` semantics (or inline state — your call) but **do not** reintroduce `asyncio.run`.
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_pipeline_integration.py backend/tests/test_optimizer_improvements.py backend/tests/test_agent_improvements.py -v`.

## Task 2.4: Make Phase 2 fully async (fixes dropped logs)

**Files:** Modify `backend/main.py`, `backend/orchestration/optimizer.py`

- [ ] **Step 1: Write failing test** — assert a Phase-2 tool call produces an `LlmCallLog` row (today it's dropped because `asyncio.run` cancels the fire-and-forget `_record_call`). Use a test DB session and assert a row with the Phase-2 `call_kind` exists after a run.
- [ ] **Step 2: Implement.** Remove `asyncio.to_thread(_run_crew_sync, ...)` and every `asyncio.run(...)` in the Phase-2 path; the driver/tools run on the event loop with `await`. Ensure `_record_call` is awaited or scheduled on the live loop so it commits.
- [ ] **Step 3: Verify** — `python -m pytest backend/tests/test_cost_flow.py backend/tests/test_logging.py -v`; grep confirms no `asyncio.run` remains under `agents/` or `orchestration/`.

## Task 2.5: Remove CrewAI

**Files:** Modify `backend/requirements.txt`, `backend/main.py`

- [ ] **Step 1: RED** — add a test asserting no live module imports `crewai` (grep-based or import-based, skipping `_archive`).
- [ ] **Step 2: Implement.** Remove `crewai` and `pysqlite3-binary` from `requirements.txt`. Remove the `pysqlite3` shim (`main.py:22-29`) and HF suppression (`main.py:31-34`) **after** verifying nothing else needs them.
- [ ] **Step 3: Verify** — in a clean env without `crewai`/`chromadb`, `python -c "import main"` succeeds; full suite green.

## Task 2.6: Archive the retired CrewAI module

**Files:** `backend/agents/optimizer_agent.py`

- [ ] **Step 1: Verify dead** — `grep -rn "optimizer_agent" backend --include=*.py | grep -v _archive` returns only the soon-to-move file / none.
- [ ] **Step 2: Archive** — `git mv backend/agents/optimizer_agent.py backend/_archive/optimizer_agent.py`. Move any crew-only helper left in `orchestration/optimizer.py`.
- [ ] **Step 3: Verify** — full suite green; no live import of the archived module.

---

## Done when
- Phase 2 runs the native A+C loop; the model still chooses tools/order/termination (agency preserved).
- Every Phase-2 call routes through `llm.py`, produces an `LlmCallLog` row, and is attributable by `call_kind`.
- No `asyncio.run`/`to_thread` in the agent path; app boots without `crewai`/`chromadb`/`pysqlite3`.
- `run_optimization_async` return shape unchanged; `main.py` pipeline behavior preserved.
- `optimizer_agent.py` archived; full suite green.

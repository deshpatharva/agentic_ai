# Pro-Tier Quality Reviewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the Pro debate loop's reviewer from an inert presentation-only critic into a holistic quality reviewer that raises the single biggest *truthful* improvement (reorder / emphasize / sharpen / summary of already-evidenced content).

**Architecture:** One file changes — `orchestration/debate_loop.py`. The reviewer prompt (lines 240–257) is reframed; the round-1 objection→tool guidance (lines 112–124) is updated to map the four action tags to the existing tools. Inputs (`_build_scores_context`, `state.honest_gaps()`) and control flow (`No objections.` → break at line 289; `DEBATE_MAX_ROUNDS = 2`) are unchanged. Round 1 executes through the existing evidence-gated tools, so the reviewer can redirect attention but can never inject unevidenced content.

**Tech Stack:** Python 3.12, pytest / pytest-asyncio, LiteLLM. Backend at `resume-optimizer/backend/`. Tests run from `resume-optimizer/backend/` via the Windows venv: `../.venv/Scripts/python.exe -m pytest ...`.

## Global Constraints

- **Truthful by construction (do not weaken):** the reviewer prompt must forbid proposing any skill/tool/metric/achievement not already in the resume, and must keep the existing `HONEST GAPS ... do NOT raise these` off-limits block. Round 1 keeps using the evidence-gated tools; the guard + verifier in `main.py` remain the backstop.
- **No scope creep:** change **only** `orchestration/debate_loop.py` and `tests/test_debate_loop.py`. Do not touch the agent loop, tools, guard, humanizer, `main.py`, DB, or API. Keep `DEBATE_MAX_ROUNDS = 2`, `set_call_kind("pro_debate")`, the budget gates, and the honest-gaps sweep.
- **Preserve existing blocks verbatim:** the reviewer prompt keeps `f"{_build_scores_context(current_scores, state.capabilities)}\n\n"` and `f"{', '.join(state.honest_gaps()) or 'none'}\n\n"` exactly — only the surrounding framing and the response contract change.
- **Hard regression gate (Task 2):** on the QA harness, pro-path inflation markers must be **≤** standard-path markers for every case. If any case regresses, the reviewer is raising fabrication — stop and fix the prompt before proceeding.
- Plain-text prompt strings only; match the surrounding `(...)`-concatenated string style already in the file.

---

### Task 1: Reframe the debate reviewer into a quality reviewer

**Files:**
- Modify: `resume-optimizer/backend/orchestration/debate_loop.py` (reviewer prompt at 240–257; round-1 objection guidance at 112–124)
- Test: `resume-optimizer/backend/tests/test_debate_loop.py` (rewrite `test_reviewer_prompt_is_presentation_only` at 385–447; add one round-1 mapping test)

**Interfaces:**
- Consumes (unchanged, already in scope inside `run_debate`): `_build_scores_context(current_scores, state.capabilities) -> str`; `state.honest_gaps() -> list[str]`; `draft: str`; `last_objection: str | None`.
- Produces: no new symbols. Reviewer output contract becomes `No objections.` or `OBJECTION: <reorder|emphasize|sharpen|summary>: <change>`; parsing is unchanged (`startswith("no objections")` → break, else store as `last_objection`).

- [ ] **Step 1: Rewrite the reviewer-prompt test to assert the quality mandate**

In `tests/test_debate_loop.py`, replace the whole `test_reviewer_prompt_is_presentation_only` function (lines 385–447) with the version below. The setup (state, `add_gaps(["Kubernetes"])`, prompt capture) is unchanged; only the name and the final assertions change.

```python
async def test_reviewer_prompt_is_quality_mandate(monkeypatch):
    """The reviewer must hunt for the single biggest TRUTHFUL quality improvement via the four
    content-preserving actions -- NOT presentation-only nitpicks, and never by adding new content.
    Guards against a regression to the old inert presentation-only mandate."""
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import debate_loop

    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "python work"},
                        capabilities=ledger.capabilities)
    state.add_gaps(["Kubernetes"])
    captured = {}

    class _ToolCall:
        id = "t1"
        class function:  # noqa: N801
            name = "bullet_strengthen"
            arguments = '{"weak_bullets_csv": "python work"}'

    class _MsgTools:
        content = ""
        tool_calls = [_ToolCall()]

    class _MsgDone:
        content = "done"
        tool_calls = None

    msgs = [_MsgTools(), _MsgDone()]

    async def fake_cwt(messages, model, tools, **kw):
        return {"message": msgs.pop(0), "input_tokens": 5, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    async def fake_reviewer(prompt, model, **kw):
        captured["prompt"] = prompt
        return {"text": "No objections.", "input_tokens": 1, "output_tokens": 1,
                "cost_usd": 0.0}

    async def fake_score(*a, **kw):
        return {"text": {"overall": 70, "ats": {"score": 70}},
                "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    async def fake_tool(state_, **kw):
        state_.update_section("experience", "stronger python work")
        return "ok"

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(debate_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(debate_loop, "complete", fake_reviewer)
    monkeypatch.setattr(debate_loop, "score_combined", fake_score)
    monkeypatch.setattr(debate_loop, "fabrication_guard", fake_guard)
    monkeypatch.setattr(debate_loop, "TOOL_MAP", {"bullet_strengthen": fake_tool})

    await debate_loop.run_debate(
        state=state, scores={"overall": 60}, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="python work",
    )
    p = captured["prompt"]
    # New quality mandate: four actions + truthful framing + strict response contract
    assert "TRUTHFUL case" in p
    assert "reorder" in p and "emphasize" in p and "sharpen" in p and "summary" in p
    assert "never by adding anything new" in p
    assert "OBJECTION: <reorder|emphasize|sharpen|summary>" in p
    # Off-limits honest-gaps block is retained (truthfulness guarantee, layer 1)
    assert "HONEST GAPS" in p and "Kubernetes" in p
    # The old inert presentation-only mandate is gone
    assert "PRESENTATION" not in p
    assert "Do NOT raise objections about: missing skills" not in p
```

- [ ] **Step 2: Run the rewritten test to verify it fails**

Run: `cd resume-optimizer/backend && ../.venv/Scripts/python.exe -m pytest tests/test_debate_loop.py::test_reviewer_prompt_is_quality_mandate -v`
Expected: FAIL — the current prompt still contains `"PRESENTATION"` and lacks `"TRUTHFUL case"` / the four action words.

- [ ] **Step 3: Reframe the reviewer prompt**

In `orchestration/debate_loop.py`, replace the `reviewer_prompt = ( ... )` assignment (lines 240–257) with:

```python
        reviewer_prompt = (
            "You are a senior resume reviewer. An optimizer has already tailored this resume to\n"
            "the target job using ONLY facts the candidate can support. Find the SINGLE change\n"
            "that would most strengthen how well the resume makes the candidate's TRUTHFUL case\n"
            "for THIS job.\n\n"
            "Your objection MUST be fixable by exactly ONE of these actions, using only content\n"
            "already in the resume -- never by adding anything new:\n"
            "  reorder   -- a highly relevant experience or bullet is buried; move it earlier\n"
            "  emphasize -- an evidenced skill the job prioritizes is underweighted; foreground it\n"
            "  sharpen   -- a bullet states evidenced work vaguely; make it concrete, with NO new\n"
            "               metrics, tools, outcomes, or scope\n"
            "  summary   -- the summary/headline doesn't foreground the target role; align it using\n"
            "               facts already in the resume\n\n"
            f"{_build_scores_context(current_scores, state.capabilities)}\n\n"
            "HONEST GAPS already identified (impossible to fix truthfully -- do NOT raise these):\n"
            f"{', '.join(state.honest_gaps()) or 'none'}\n\n"
            f"CURRENT RESUME DRAFT:\n{draft}\n\n"
            "If the resume already makes its strongest truthful case, respond EXACTLY:\n"
            "No objections.\n"
            "Otherwise respond EXACTLY (one line):\n"
            "OBJECTION: <reorder|emphasize|sharpen|summary>: <specific change naming the bullet "
            "or section, 25 words or less>"
        )
```

- [ ] **Step 4: Run the rewritten test to verify it passes**

Run: `cd resume-optimizer/backend && ../.venv/Scripts/python.exe -m pytest tests/test_debate_loop.py::test_reviewer_prompt_is_quality_mandate -v`
Expected: PASS.

- [ ] **Step 5: Add a test that round 1 maps the objection's action to a tool**

Append this test to `tests/test_debate_loop.py`. It captures the messages sent to the optimizer and asserts round 2 carries the objection plus the action→tool mapping.

```python
async def test_round1_objection_carries_action_to_tool_mapping(monkeypatch):
    """When the reviewer objects, round 2's optimizer messages must include the objection and
    the action->tool mapping, so a reorder/emphasize/sharpen/summary objection is actionable."""
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import debate_loop

    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "python work"},
                        capabilities=ledger.capabilities)
    captured_msgs = []

    class _ToolCall:
        id = "t1"
        class function:  # noqa: N801
            name = "bullet_strengthen"
            arguments = '{"weak_bullets_csv": "python work"}'

    class _MsgTools:
        content = ""
        tool_calls = [_ToolCall()]

    class _MsgDone:
        content = "done"
        tool_calls = None

    msgs = [_MsgTools(), _MsgDone(), _MsgTools(), _MsgDone()]

    async def fake_cwt(messages, model, tools, **kw):
        captured_msgs.append([dict(m) for m in messages])
        return {"message": msgs.pop(0), "input_tokens": 5, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    rc = [0]

    async def fake_reviewer(prompt, model, **kw):
        rc[0] += 1
        if rc[0] == 1:
            return {"text": "OBJECTION: sharpen: bullet 1 is vague",
                    "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}
        return {"text": "No objections.", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    async def fake_score(*a, **kw):
        return {"text": {"overall": 70, "ats": {"score": 70}},
                "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    async def fake_tool(state_, **kw):
        state_.update_section("experience", "stronger python work")
        return "ok"

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(debate_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(debate_loop, "complete", fake_reviewer)
    monkeypatch.setattr(debate_loop, "score_combined", fake_score)
    monkeypatch.setattr(debate_loop, "fabrication_guard", fake_guard)
    monkeypatch.setattr(debate_loop, "TOOL_MAP", {"bullet_strengthen": fake_tool})

    await debate_loop.run_debate(
        state=state, scores={"overall": 60}, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="python work",
    )

    user_texts = " ".join(
        m["content"] for round_msgs in captured_msgs for m in round_msgs if m["role"] == "user"
    )
    assert "The reviewer raised this objection" in user_texts
    # The round-1 guidance must map the reviewer's ACTION TAGS to tools. The action
    # words "sharpen"/"emphasize" are unique to the new mapping -- the old guidance
    # used "weak bullets"/"missing keywords" -- so this fails before Step 7.
    assert "sharpen" in user_texts and "emphasize" in user_texts
    assert "bullets_reorder" in user_texts and "bullet_strengthen" in user_texts
```

- [ ] **Step 6: Run the new mapping test to verify it fails**

Run: `cd resume-optimizer/backend && ../.venv/Scripts/python.exe -m pytest tests/test_debate_loop.py::test_round1_objection_carries_action_to_tool_mapping -v`
Expected: FAIL — the current round-1 guidance (lines 116–123) maps by issue type ("keyword_inject for missing keywords, bullet_strengthen for weak bullets, ...") and contains neither `"sharpen"` nor `"emphasize"`, so those two assertions fail.

- [ ] **Step 7: Update the round-1 objection→tool guidance to the action mapping**

In `orchestration/debate_loop.py`, replace the `content=( ... )` block inside the round-1 objection append (lines 116–123) with:

```python
                content=(
                    f"The reviewer raised this objection: {last_objection}\n\n"
                    "Address ONLY this objection with at most 1-2 tool calls, using only evidenced\n"
                    "content already in the resume. Map the objection's action to a tool:\n"
                    "  reorder   -> bullets_reorder\n"
                    "  emphasize -> keyword_inject or skills_rewrite (an evidenced keyword/skill only)\n"
                    "  sharpen   -> bullet_strengthen on the named bullet, adding NO metrics, tools,\n"
                    "               outcomes, or scope\n"
                    "  summary   -> keyword_inject or bullet_strengthen on the summary, using\n"
                    "               existing facts\n"
                    "Do NOT add any skill, tool, metric, or achievement not already in the resume. "
                    "When the targeted fix is applied, stop."
                ),
```

- [ ] **Step 8: Run the debate-loop test file to verify all pass**

Run: `cd resume-optimizer/backend && ../.venv/Scripts/python.exe -m pytest tests/test_debate_loop.py -v`
Expected: PASS — all tests, including the two changed/added ones and the unchanged behavioral tests (bounded rounds, objection triggers revision, no-objection early exit, pro_debate call kind, guard once, final-round skip, both gap sweeps).

- [ ] **Step 9: Run the full suite to confirm no regressions**

Run: `cd resume-optimizer/backend && ../.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS — full suite (was 509 passing; net +1 from the added mapping test → 510).

- [ ] **Step 10: Commit**

```bash
git add resume-optimizer/backend/orchestration/debate_loop.py resume-optimizer/backend/tests/test_debate_loop.py
git commit -m "feat(debate): repurpose reviewer into a truthful quality reviewer

Reframe the pro debate reviewer from presentation-only nitpicks to the
single biggest TRUTHFUL improvement via four content-preserving actions
(reorder/emphasize/sharpen/summary); map each action to an existing
evidence-gated tool in round 1. Inputs and control flow unchanged."
```

---

### Task 2: Verify the quality reviewer earns its cost without raising fabrication (live QA)

This is an empirical verification task, not a code task. It runs the real pipeline on four industries via the scratch harness `_qa_industries.py` (already supports `<case> <humanizer-model|-> <plan>`) and checks the spec's gates. No production code changes; the harness and `_qa_*.json` files are git-ignored scratch.

**Files:**
- Use: `resume-optimizer/backend/_qa_industries.py` (untracked scratch, pro mode: `_qa_industries.py <case> - pro`)
- Read baselines: `resume-optimizer/backend/_qa_{nurse,marketing,accounting,sales}.json` (standard-path runs already captured)

**Interfaces:**
- Consumes: the Task 1 change (the new quality reviewer must be committed and importable).

- [ ] **Step 1: Re-run the pro path on all four industries with the new reviewer**

Run (each ~2–3 min; a valid `.env` with GEMINI/GROQ/DEEPSEEK keys must be present):
```
cd resume-optimizer/backend
../.venv/Scripts/python.exe _qa_industries.py nurse - pro
../.venv/Scripts/python.exe _qa_industries.py marketing - pro
../.venv/Scripts/python.exe _qa_industries.py accounting - pro
../.venv/Scripts/python.exe _qa_industries.py sales - pro
```
Expected: four `_qa_{case}_pro.json` files written; each prints `plan/driver: pro (run_debate)`.

- [ ] **Step 2: Run the inflation-marker regression gate (pro ≤ standard, per case)**

Run this comparison (same marker set used in the humanizer A/B):
```
cd resume-optimizer/backend && ../.venv/Scripts/python.exe - <<'EOF'
import json
POWER = ["spearheaded","orchestrated","transformed","championed","pioneered","drove","driving",
         "architected","revolutionized","engineered","accelerated","optimized","optimizing",
         "streamlined","overhauled","negotiated","end-to-end","from conception","established and grew"]
OUTCOME = ["resulting in","generating","measurable","organic traffic","improved search",
           "expedited","recovery trajectories","faster patient","real-time","strategic overhaul",
           "conversions","conversion","enhanced clinical workflow","identify service gaps",
           "customer satisfaction metrics","reduced the month","reduced month-end"]
def markers(d):
    t,o = d["delivered_text"].lower(), d["original_text"].lower()
    return [m for m in POWER+OUTCOME if m in t and m not in o]
def guard_caught(d):
    return len(d.get("guard_stripped",[]))+sum(1 for g in d.get("guard_gaps",[]) if "dropped" in g or "replaced" in g)
fail = False
for c in ["nurse","marketing","accounting","sales"]:
    s = json.load(open(f"_qa_{c}.json"))          # standard baseline
    p = json.load(open(f"_qa_{c}_pro.json"))      # pro / quality reviewer
    ms, mp = len(markers(s)), len(markers(p))
    gate = "OK" if mp <= ms else "FAIL"
    if mp > ms: fail = True
    print(f"{c:<11} standard_infl={ms}  pro_infl={mp}  guard_caught_pro={guard_caught(p)}  gate={gate}")
print("REGRESSION GATE:", "FAIL -- reviewer is raising fabrication" if fail else "PASS")
EOF
```
Expected / **hard gate:** `REGRESSION GATE: PASS` — every case has `pro_infl <= standard_infl`. If FAIL, do not proceed: the reviewer is driving fabrication; return to Task 1 and tighten the reviewer prompt (Phase 1 of systematic-debugging).

- [ ] **Step 3: Confirm the quality win and the cost path**

For each `_qa_{case}_pro.json`, read the delivered text and the run log, and record:
- **Win:** at least one case where the reviewer fired an actionable objection that round 1 executed (a relevant evidenced bullet surfaced/reordered, an evidenced JD-skill foregrounded, or the summary aligned to the role) that the standard `_qa_{case}.json` draft did not have — with no new claims.
- **Cost:** at least one case where the reviewer returned `No objections.` and round 1 was skipped (pro cost ≈ standard cost for that case).

Expected: the repurposed reviewer produces a visible truthful improvement on ≥1 case and no fabrication on any. Write a 3–5 line summary of the per-case outcome (markers, guard, win/no-objection) into the PR notes.

- [ ] **Step 4: No commit (scratch only)**

The harness and `_qa_*.json` are git-ignored. If the gate passed, Task 1's commit stands as the feature; record the QA summary in the PR description. If the gate failed, no feature ships until Task 1 is fixed and Task 2 re-run.

---

## Notes for the executor

- Run tests from `resume-optimizer/backend/` using `../.venv/Scripts/python.exe -m pytest` (WSL→Windows venv; bash `VAR=x` prefixes do **not** cross into the Windows interpreter — the test files set their own env via `os.environ.setdefault`).
- "Full suite" means `pytest tests/ -q`, not a subset.
- Do not add tools, rubric scoring, or deterministic detectors (spec's rejected approaches B/C). The four actions all map to the four existing tools.

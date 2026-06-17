# edit_resume Tool Design

**Date:** 2026-06-17  
**Scope:** Chat co-pilot — new `edit_resume(instruction, profile_id?)` tool that lets users make targeted, freeform edits to their resume through natural language, backed by the existing optimizer agent.

---

## Overview

Users who have reviewed their optimized resume (or a saved profile) often want targeted changes: remove a bullet, shorten the summary, reorder skills, fix a tone issue. Currently there is no path from co-pilot conversation to resume text change — the user would have to start a full re-optimization.

`edit_resume` closes that gap. The co-pilot calls it when the user expresses dissatisfaction or asks for specific changes. It fires the optimizer agent with the user's instruction as high-priority feedback, runs the fabrication guard and re-scores, then writes the result back to the session — preserving the agentic, tool-driven approach rather than doing a raw text rewrite.

---

## Architecture

### New chat tool

`edit_resume(instruction, profile_id?)` is added to `chat/tools.py` alongside the existing `launch_optimizer`, `save_profile`, and `download_profile` tools.

Parameters:
- `instruction` (required, string) — plain-language description of what to change. May span multiple sections ("remove the Kafka bullet, shorten the summary, and delete the certification section").
- `profile_id` (optional, string) — which saved profile to edit. Only needed when no `last_result` exists in the session.

### Source resolution

When the handler runs, it resolves the resume to edit in this order:

1. If `session.context["last_result"]` exists → use `last_result["sections"]` and `last_result["optimized_text"]`. The `optimized_text` becomes the `original_source` for the fabrication guard (guard checks against the already-optimized resume, not the raw uploaded file).
2. If no `last_result` → resolve profile by `profile_id` from DB; use `Profile.sections` and `Profile.raw_text`.

After an edit the result always writes back to `session.context["last_result"]` — even when the source was a saved profile. The user reviews the result in the session and calls `save_profile` to persist it if happy.

### Agent execution

The handler calls `run_optimization_async(state, jd_text, jd_result, plan="standard", max_iterations=2, user_instruction=instruction)`.

Key differences from a full optimization run:
- `max_iterations=2` — targeted edits, not full re-optimization.
- Always `run_agent()` (standard plan), never `run_debate()` — edit passes are lightweight.
- `user_instruction` is injected at the top of the agent system prompt as a priority feedback block: *"The user reviewed their resume and flagged specific issues: {instruction}. Address ONLY what was flagged — do not re-run a full optimization."*
- JD context from `session.context["jd_text"]` is passed if present; agent still runs without it.
- `ResumeState` is seeded from the resolved sections (step above).

### Post-processing

After the agent loop completes:
1. `fabrication_guard(optimized_text, ledger, source_text=original_source)` — same contract as the optimizer.
2. `score_combined(optimized_text, jd_text)` — full re-score across all 5 dimensions.
3. `build_report(...)` — updated report with section diff (before = pre-edit sections, after = post-edit sections).

### Write-back

`session.context["last_result"]` is updated with:
- `sections` — post-edit sections dict
- `optimized_text` — post-edit full text
- `report` — updated report (new scores, section diff, gaps)
- `verifier_flagged` — list of flagged claims (may be empty)

The session row is committed to DB.

---

## SSE events

New event emitted from `chat/router.py`:

```json
{
  "event": "resume_edited",
  "data": {
    "sections_changed": ["summary", "experience"],
    "scores": { "ats": 82, "impact": 75, "skills_gap": 80, "readability": 88, "jd_tailoring": 71 },
    "scores_before": { "ats": 79, "impact": 71, "skills_gap": 80, "readability": 85, "jd_tailoring": 68 },
    "verifier_flagged": []
  }
}
```

Router dispatch block (new branch alongside `launch`, `save`, `download`):

```python
elif edit:
    try:
        result = await apply_edit(current_user, session, edit["arguments"])
        yield {"event": "resume_edited", "data": json.dumps(result)}
    except HTTPException as exc:
        yield {"event": "error", "data": json.dumps({"message": str(exc.detail)})}
```

---

## Co-pilot guidance (chat/agent.py)

New system prompt block:

> **WHEN THE USER ASKS FOR RESUME EDITS:**  
> Call `edit_resume(instruction)` with exactly what the user asked for — verbatim detail only, no interpretation or invention. If there is no `last_result` and multiple profiles exist, ask which profile to edit before calling.  
> After it completes, summarize: which sections changed, score delta (before → after), and any fabrication flags.  
> If fabrication was flagged: "The verifier flagged X — that detail wasn't in your original resume."  
> Do NOT call `edit_resume` for score discussions, explanations, or anything outside resume text changes.

Co-pilot calls `edit_resume` when:
- User expresses dissatisfaction with specific resume content ("that bullet isn't right", "remove the Kafka mention", "my summary is too generic")
- User asks for targeted changes to a saved profile before optimizing ("can you shorten my Data Engineer profile summary")

Co-pilot does NOT call it when:
- Request is out of scope (cover letters, interview prep, etc.)
- User wants to discuss or understand scores — only call it when they want the resume *text* changed

---

## Edit quota

Edit runs have a separate daily quota from pipeline runs (to guard against cost abuse).

- New `daily_edits` column on `PlanLimit` table (DB migration required).
- New `edits` column on `DailyUsageCounter` table (DB migration required).
- `_check_edit_quota(user, db)` guard runs before `apply_edit` — same pattern as `_check_quota()`.
- `DailyUsageCounter.edits` incremented after each successful edit.
- Quota values per plan are set in `PlanLimit` (e.g. free: 5/day, pro: 20/day — exact values are a product decision).
- Over-limit SSE error: "You've reached your daily edit limit. Upgrade to Pro for more edits."
- Edit runs do NOT count against `daily_uploads` (pipeline quota).

---

## Error handling

| Case | Behaviour |
|------|-----------|
| No `last_result` and no valid `profile_id` | HTTP 400: "Nothing to edit yet — run the optimizer first, or tell me which saved profile to update." |
| Agent produces empty output | Keep original sections unchanged. SSE error: "The edit produced no output — your resume is unchanged." |
| Fabrication flagged | Write edited resume to session. Flag in `verifier_flagged`. Co-pilot reports honestly. Not blocking. |
| No JD in session | Agent runs without JD. ATS/skills gap scores reflect absence of JD — acceptable. |
| `_optimizer_launched` is true and pipeline still running | Block edit. SSE error: "An optimization is in progress — wait for it to finish before making manual edits." |
| Daily edit quota exceeded | HTTP 429 SSE error with upgrade message. |

---

## Files changed

| File | Change |
|------|--------|
| `chat/tools.py` | Add `EDIT_TOOL = "edit_resume"` and its schema to `TOOLS` |
| `chat/handoff.py` | Add `apply_edit(user, session, arguments)` handler |
| `chat/router.py` | Import `apply_edit`; add `elif edit:` dispatch branch; add `_check_edit_quota()` |
| `chat/agent.py` | Add `WHEN THE USER ASKS FOR RESUME EDITS` block to system prompt |
| `orchestration/agent_loop.py` | Accept and inject `user_instruction` param; honour `max_iterations` override |
| `db/models.py` | Add `daily_edits` to `PlanLimit`; add `edits` to `DailyUsageCounter` |
| `alembic/` | Migration for new columns |
| `tests/test_pr7_edit_resume.py` | 11 new tests (see Testing section) |

---

## Testing

New file `tests/test_pr7_edit_resume.py`:

1. `edit_resume` appears in `TOOLS` list with correct schema (`instruction` required, `profile_id` optional)
2. Handler picks `last_result.sections` when present; falls back to `Profile.sections` when not
3. `user_instruction` is present in agent system prompt; `max_iterations=2`
4. After edit, `last_result.sections` and `optimized_text` updated in session context
5. `last_result.report.scores` reflects post-edit rescore, not pre-edit scores
6. `resume_edited` SSE event contains `sections_changed`, `scores`, `scores_before`, `verifier_flagged`
7. Fabrication guard runs; flagged claim appears in `verifier_flagged`; edit still writes back
8. Edit quota enforced — over-limit call returns HTTP 429; `DailyUsageCounter.edits` increments on success
9. Edit blocked when `_optimizer_launched=True` — returns error, no edit applied
10. No source → HTTP 400
11. Co-pilot system prompt contains `edit_resume` instructions block

# Pro-Tier Quality Reviewer — Design Spec

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation plan
**Branch:** `claude/effort-estimation-m4a4ep` (follows the truthful-optimizer work)

## Goal

Repurpose the Pro debate loop's reviewer from an inert presentation-only critic into a
**holistic quality reviewer** that raises the single biggest *truthful* improvement to make the
resume's strongest case for the target job. Round 1 executes it through the existing
evidence-gated tools. Net effect: the pro path becomes genuinely better than the standard path,
or cheaper (skips a wasted round) — **never worse, never less truthful.**

## Background / Motivation

The debate loop (`orchestration/debate_loop.py`, `run_debate`, Pro tier) was built to push scores
up through adversarial iteration. The truthful-optimizer redesign (spec `2026-07-07`) removed
score-chasing as the objective and, to prevent the reviewer from driving fabrication, constrained
it to *"raise ONE objection fixable purely by presentation changes to existing content."* That
constraint left it almost nothing to do.

Measured evidence (QA harness `_qa_industries.py`, pro vs standard, sharpest two industries):

| Case | Path | Cost | Wall | Final score | Truthfulness |
|---|---|---|---|---|---|
| accounting | standard | $0.0091 | 157s | 43 | clean |
| accounting | pro/debate | $0.0111 | 196s | 40 | identical |
| sales | standard | $0.0091 | 175s | 45 | clean |
| sales | pro/debate | $0.0098 | 167s | 48 | identical |

Pro output was truthfulness-identical to standard (same honest_gaps, same inflation markers,
same guard behavior) for 8–21% more cost. The reviewer's safety constraint had neutered its
mechanism. This spec gives it a mandate that improves quality **without** reintroducing
fabrication.

## Key insight — why this is safe

Round 1 executes the reviewer's objection through the **same evidence-gated tools** the agent
loop uses (`keyword_inject`, `skills_rewrite`, impact-strengthen, `reorder_bullets`), all of
which route missing items through `split_evidenced` and refuse anything unevidenced. Therefore
the reviewer can only *redirect attention* — it can never introduce unevidenced content,
whatever it says. This makes an ambitious "improve quality" mandate safe by construction.

## Design overview — data flow

The machinery already runs the reviewer once after round 0, already feeds it the evidenced/gap
scores context and the honest-gaps off-limits list, and already breaks on `No objections.`
(`debate_loop.py:289`). The substantive change is almost entirely the reviewer's
**prompt/mandate**; a secondary change broadens the round-1 objection→tool guidance.

1. **Round 0:** agent optimizer loop runs unchanged → `draft_0` + scores + `honest_gaps`.
2. **Re-score** `draft_0` (already happens) → `current_scores`.
3. **Quality reviewer call (reframed prompt).** Inputs already assembled today and reused as-is:
   `_build_scores_context(current_scores, state.capabilities)` (surfaces evidenced-addable
   keywords/skills and the off-limits gaps), `state.honest_gaps()`, and `draft`. Output:
   `No objections.` **or** `OBJECTION: <action>: <specific change>`.
4. **Branch (existing control flow):**
   - Objection stored as `last_objection` → **Round 1** addresses *only* it with ≤2
     evidence-gated tool calls, then the loop ends (final-round break).
   - `No objections.` → **break** (already at `debate_loop.py:289`); skip round 1. Delivered
     draft == `draft_0`.
5. **main.py tail unchanged:** humanize → normalize → sanitize → guard → verifier → final score.

`DEBATE_MAX_ROUNDS` stays `2` (round 0 = full optimize, round 1 = one targeted quality fix).

## The reviewer contract

### Mandate (reframed reviewer prompt)

Replaces `debate_loop.py:241-256`. Keeps the existing `_build_scores_context(...)` and
`state.honest_gaps()` blocks verbatim; only the framing and the response contract change.

```
You are a senior resume reviewer. An optimizer has already tailored the resume below to the
target job, using ONLY facts the candidate can support. Find the SINGLE change that would most
strengthen how well this resume makes the candidate's TRUTHFUL case for THIS job.

Your objection MUST be fixable by exactly ONE of these actions, using only content already in
the resume -- never by adding anything new:
  reorder   -- a highly relevant experience or bullet is buried; move it earlier (bullets_reorder)
  emphasize -- an evidenced skill the job prioritizes is underweighted; foreground it
               (keyword_inject / skills_rewrite)
  sharpen   -- a bullet states evidenced work vaguely; make it concrete with NO new metrics,
               tools, outcomes, or scope (bullet_strengthen)
  summary   -- the summary/headline doesn't foreground the target role; align it using existing facts

<existing _build_scores_context(current_scores, state.capabilities) block --
 surfaces the evidenced-addable keywords/skills and the section scores>

HONEST GAPS already identified (impossible to fix truthfully -- do NOT raise these):
<existing state.honest_gaps() list>

CURRENT RESUME DRAFT:
{draft}

If the resume already makes its strongest truthful case, respond EXACTLY:
No objections.
Otherwise respond EXACTLY (one line):
OBJECTION: <reorder|emphasize|sharpen|summary>: <specific change naming the bullet or section, <=25 words>
```

### Output parsing (existing behavior, unchanged)

- `reviewer_text.lower().startswith("no objections")` → break, skip round 1 (already at
  `debate_loop.py:289`).
- Otherwise the whole line is stored as `last_objection` and fed to round 1. The action tag
  (`reorder|emphasize|sharpen|summary`) is interpreted by the round-1 prompt, not parsed in code;
  an unrecognized tag is still safe because round 1's tools are evidence-gated. No new code-level
  parsing is required.

### Round 1 execution (broadened objection→tool guidance)

Replace today's keyword-only guidance with:

```
The reviewer raised this objection: {last_objection}

Address ONLY this objection with at most 1-2 tool calls, using only evidenced content:
- reorder / emphasize -> reorder_bullets (and keyword_inject for an evidenced keyword)
- sharpen             -> strengthen the named impact bullet, adding NO metrics, tools, or outcomes
- summary             -> revise the summary using facts already in the resume
Do not add any skill, tool, metric, or achievement not already in the resume.
```

## Truthfulness guarantee — defense in depth (three layers)

1. **Reviewer prompt:** forbids unevidenced suggestions; handed `honest_gaps` as the explicit
   off-limits list; restricted to the four content-preserving actions.
2. **Round 1 tools:** already evidence-gated via `split_evidenced` — refuse unevidenced items
   even if the reviewer errs.
3. **Guard + verifier:** still run on the delivered text in the main.py tail — final backstop.

## Components / files

- **`orchestration/debate_loop.py`**
  - **Primary:** replace the reviewer prompt at `241-256` (presentation-only → quality mandate
    above). Reuse the existing `_build_scores_context(current_scores, state.capabilities)` and
    `state.honest_gaps()` blocks; change only the framing and the response contract.
  - **Secondary:** broaden the round-1 objection→tool guidance (currently keyword-focused, at
    ~`113-125`) to map the four actions to `bullets_reorder` / `keyword_inject` / `skills_rewrite`
    / `bullet_strengthen`.
  - **Unchanged (already correct):** the `No objections.` → break at `289`; reviewer inputs;
    `DEBATE_MAX_ROUNDS = 2`; `set_call_kind("pro_debate")`; budget gates; gap sweep.
- **`tests/test_debate_loop.py`** — see Testing.
- **`_qa_industries.py`** (untracked scratch) — pro-mode verification, already supported.

No changes to the agent loop, tools, guard, humanizer, main.py tail, DB, or API.

## Testing

Unit (`tests/test_debate_loop.py`, mocked `complete`/tools):

1. **Reviewer mandate present:** reviewer prompt contains the four action verbs, the "TRUTHFUL
   case" framing, the off-limits/"may NOT propose adding" rule, and the interpolated
   `honest_gaps`. Replaces the old presentation-only assertions.
2. **No-objection skips round 1:** reviewer returns `No objections.` → the round-1 optimizer pass
   makes no tool calls (assert tool invocations count unchanged after round 0) and delivered text
   == `draft_0`.
3. **Objection drives one targeted round:** reviewer returns `OBJECTION: reorder: ...` → round 1
   runs, feeds the objection as context, makes ≤2 tool calls.
4. **honest_gaps handed to reviewer:** a gap in `state.honest_gaps` appears verbatim in the
   reviewer prompt's off-limits list.
5. Existing debate tests updated for the new prompt/flow; full suite stays green.

Verification (QA harness, not unit — real models, four industries + the tech resume, pro vs
standard):

- **Win condition:** on ≥1 case the pro draft is measurably better (relevant evidenced
  experience foregrounded / better JD emphasis) with **zero** increase in inflation markers,
  guard strips, or honest-gap leakage vs standard.
- **Hard regression gate:** inflation markers on the pro path stay ≤ standard-path levels.
  The reviewer must never raise fabrication. (Measured with the existing inflation-marker
  counter: ownership verbs + invented-outcome phrases in delivered-not-in-source.)
- **Cost condition:** cases with no truthful improvement return `No objections.` and skip
  round 1, pulling pro cost toward standard.

## Risks & edge cases

- **Unachievable objection** (reviewer asks for something round 1 can't do truthfully) → tools
  refuse → round 1 no-ops. Wasted cost, no harm. Mitigated by the action menu + requiring a
  named target + the off-limits gaps list.
- **Over-eager reviewer** (always finds a nitpick) → mild churn without quality gain. QA watches
  for churn; prompt says only if it *materially* strengthens the truthful case.
- **Latency/cost:** one reviewer call + at most one round-1 pass — same structure as today, no
  new round. No-objection path is strictly cheaper than the status quo.

## Out of scope (YAGNI)

- No new tools; round 1 uses the existing four.
- No rubric scoring, no deterministic coverage detectors (approaches B/C — rejected).
- No change to `DEBATE_MAX_ROUNDS` or a multi-round debate.
- No humanizer, guard, or standard-path changes.

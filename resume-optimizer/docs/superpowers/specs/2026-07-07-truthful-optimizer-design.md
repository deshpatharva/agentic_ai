# Truthful Optimizer — Design Spec

**Date:** 2026-07-07
**Status:** Approved (design review in chat, 2026-07-07)
**Owner:** Phase 2 agentic pipeline (`agents/`, `orchestration/`, `main.py`)

## Context

The optimizer's objective is currently "raise all scores above 90," and the scorer's
rubric defines high scores as JD-keyword/skill *presence*. For a candidate who honestly
lacks a required skill, the only path to target is to claim it — fabrication is the
optimum of the stated objective, and the downstream guard/verifier fight the objective
instead of the objective being truthful.

Empirical evidence (full-pipeline profiling runs, 2026-07-07, `_try_run_standard.json` /
`_try_run_pro.json`):

- `keyword_inject`/`skills_rewrite` added FastAPI, Docker, Kubernetes, Terraform, Kafka,
  Prometheus, Grafana to a resume that evidences none of them; the debate reviewer's
  objections actively pushed the round-2 skill fabrication.
- The scorer nominated "Senior" as a missing keyword → title inflation ("Senior Software
  Engineer") in the delivered text.
- The fabrication guard flagged lines with `[VERIFY]` markers; the humanizer (which runs
  after guard + verifier) erased every marker and, in the pro run, invented a new metric
  ("Maintained 99.9% uptime"). Nothing checks text after the humanizer.
- The persisted `final_score` is computed pre-humanize: 5–8 points below what the
  delivered text scores.
- Both runs burned the full 20K token budget without converging (target unreachable
  honestly) — the score treadmill is the default path, not the exception.
- `critique_resume` was never called in any run; its `TOOL_DEFS` entry costs tokens every
  strategist turn and its description promises tone feedback the prompt refuses to give.

## Goal

1. The pipeline never adds capabilities, titles, or metrics without evidence from the
   candidate's own material.
2. Honest gaps become a first-class output ("real gaps to close for this JD"), serving
   the actual product goal: a factual resume with better job-landing chances.
3. The delivered text is the text that gets guarded, verified, and scored.
4. The agent stops when no truthful work remains, not when an unreachable target says so.

## Non-goals (deferred, tracked separately)

- Diff-style tool returns (efficiency; separate change).
- The chat-launch `[USER INSTRUCTION: ...]`-embedded-in-`jd_text` bug (`chat/handoff.py`).
- Multi-worker LRU result cache; DeepSeek per-callsite thinking switch.
- Frontend UI for the gap report (this spec exposes the data in report/`last_result`).
- Verifier model upgrade (prompt hardening only; model stays `MODEL_VERIFIER`).
- agent_loop/debate_loop inner-loop dedup refactor.
- Per-dimension SCORE_TARGET calibration.

## Approach

**Constrain at the source, enforce at the exit.** A deterministic *capabilities
allowlist* (extension of the claims ledger) feeds the strategist and the writing tools;
tool inputs are filtered in Python so unevidenced items never reach an LLM prompt;
unfixable items accumulate as `honest_gaps`. The fabrication guard moves to the end of
the pipeline (after humanize) and gains a capability check, so the last line of defense
runs after the last LLM touch. Alternative "verify-and-strip only" was rejected: it keeps
paying tokens for content that gets deleted and leaves textual holes.

---

## 1. Capabilities ledger (`agents/fact_extractor.py`)

Extend `ClaimsLedger` with:

```python
capabilities: frozenset = field(default_factory=frozenset)  # evidenced skills/tools/tech
```

Extraction (deterministic, no LLM, same philosophy as the rest of the ledger):

- Tokens from the resume's skills section (parsed via `utils/skills_normalizer._parse_skills`).
- Plus taxonomy-term matches over the full resume text: case-insensitive whole-word
  matches against the curated tech taxonomy already maintained in
  `utils/skills_normalizer` (single source of truth; expose a `taxonomy_terms()` helper
  there if not already importable).
- Normalized to lowercase for membership checks; original casing kept for display.

`prompt_block()` gains: `Verified capabilities: {sorted capabilities}`.

`agents/memory.py` `_ledger_to_dict`/`_dict_to_ledger`/`merge_ledgers` gain the new field
(union on merge, consistent with the other sets). Stored ledgers without the key load as
empty frozenset (backward compatible).

## 2. Objective flip (`orchestration/agent_loop.py`)

### 2a. `_build_system_stable(available_sections, ledger, user_instruction=None)` — new text

```
{instruction_block}You are a Resume Optimization Strategist. Present this candidate's
VERIFIED experience as strongly and as relevantly to the target job as possible.

VERIFIED FACTS — the only claims this resume may make:
{ledger.prompt_block()}

AVAILABLE RESUME SECTIONS: {', '.join(available_sections)}

HARD RULES:
- Never add a skill, tool, technology, job title, seniority claim, or number that is not
  in the VERIFIED FACTS above or already present in the resume text.
- Tools refuse unevidenced items and record them as honest gaps for the user's gap
  report. Do not retry a refused item; move on.
- If a score cannot reach target truthfully, leave it — honest gaps are a product
  feature, not a failure.

Work only on items marked "addable" and on presentation fixes (bullet strength, bullet
ordering, JD tailoring of existing content). When no truthful work remains, output a
one-line summary and stop calling tools.
```

The ledger is per-job stable, so the system prompt remains cacheable across all turns and
reflections within a job (cross-job prefix reuse is lost; accepted — within-job reuse is
where the volume is; measured hit rates were 75–97% within-job).

`instruction_block` (user_instruction path used by `chat/handoff.apply_edit`) is kept
verbatim from the current implementation.

### 2b. `_build_scores_context(scores, ledger, reflection_idx=None)` — evidence split

Every "missing" list is split by the capabilities allowlist before rendering:

- `addable` = items whose normalized form is in `ledger.capabilities` (which already
  covers everything evidenced anywhere in the resume, per Section 1).
- `gaps` = the rest.

```
{"CURRENT SCORES (baseline)" | "UPDATED SCORES (reflection N)"}:
  ATS Match:    {s:>3}  [{flag}]
    addable keywords (evidenced): {...}
    gaps (no evidence — DO NOT add; reported to user): {...}
  Impact:       {s:>3}  [{flag}]
    weak_bullets: {...}
  Skills Gap:   {s:>3}  [{flag}]
    addable skills (evidenced): {...}
    gaps (no evidence — DO NOT add): {...}
  JD Tailoring: {s:>3}  [{flag}]
    issues: {...}

Do the addable and presentation work above. Items listed as gaps are off-limits.
```

`flag` semantics: `NEEDS WORK` when score < target AND the dimension has actionable
items; `capped (honest ceiling)` when score < target and nothing actionable remains;
`ok` when score >= target. Reflection feedback messages use the "UPDATED SCORES
(reflection N)" heading so stale blocks in the append-only history are self-labeled.

Seniority-word hygiene: `addable` keyword computation drops seniority/role adjectives
("senior", "lead", "principal", "staff", "expert") regardless of evidence — titles are
never keyword-injectable. The scorer prompt also gains one line (Section 6d).

### 2c. Stop condition

A dimension is **capped** when it is below target and its actionable set is empty
(all missing items are gaps; no weak bullets / issues remain). The reflection done-check
becomes:

```python
done = all(score >= SCORE_TARGET or capped for each agent dimension)
```

(readability stays excluded as today). `run_agent` returns `honest_gaps: list[str]`
(sorted, deduped, from `ResumeState`). This kills the budget treadmill: profiled runs
burned 100%+ of budget re-attempting unreachable dimensions.

### 2d. `TOOL_DEFS` cleanup

- Remove `critique_resume` entirely (entry, `TOOL_MAP`, function, and its tests).
- `bullets_reorder` description: "Reorder bullets in a section (experience, summary, or
  skills) so the most JD-relevant appear first."

## 3. Tool constraints (`agents/tools.py`, `agents/rewriter.py`)

### 3a. `ResumeState` gains gap tracking

```python
def add_gaps(self, items: Iterable[str]) -> None      # thread-safe set add
def honest_gaps(self) -> list[str]                    # sorted copy
```

### 3b. Python-side input filtering (both inject tools)

Before any LLM call, `keyword_inject` and `skills_rewrite` partition their input list
against `ledger.capabilities` (ledger threaded into `ResumeState` at construction:
`state.capabilities`). Unevidenced items are recorded via `state.add_gaps()` and never
reach the prompt. Return strings teach the strategist:

```
"Injected (evidenced): python, postgresql. Skipped (no evidence — recorded as gaps): kubernetes, terraform."
```

If everything is filtered out: `"All requested items lack evidence — recorded as honest gaps: ..."`.

### 3c. `keyword_inject` prompt — new text

```
Weave these keywords into the resume section below. Every keyword listed is already
evidenced by the candidate's own material — your job is presentation, not addition.

RULES — strictly follow all of them:
- Weave keywords into EXISTING sentences/bullets only. Do NOT add new sentences,
  clauses, or bullets.
- Rephrase what the candidate already does so it uses the keyword. Do NOT claim new
  duties, projects, tools, or role scope to host a keyword.
- Do NOT change any metrics, dates, company names, job titles, or seniority wording.
  NEVER insert placeholder metrics ("[XX%]").
- Do NOT copy job-description phrases verbatim, and do NOT repeat the same phrase across
  bullets — vary the wording so it reads naturally.
- If a keyword cannot be woven without inventing a new claim, skip it.
- Plain text only — no markdown bold, no LaTeX or "$" math wrappers.

Keywords to weave in: {evidenced_keywords}

Section:
"""
{section_text}
"""

Return ONLY the updated section text.
```

Cross-section duplication note (kept minor): the second section's prompt appends
`Already used in another section: {...} — do not repeat them here.`

### 3d. `skills_rewrite` prompt — new text ("sync with evidence")

```
Rewrite the Skills section so it accurately reflects the candidate's evidenced skills.

You may ONLY add skills from this list — each one already appears in the candidate's own
resume (experience, summary, or projects): {evidenced_missing_skills}

- Group added skills with related existing ones if the section is grouped.
- Keep every existing skill; deduplicate exact repeats.
- Do NOT add anything outside the list. Do NOT invent certifications or proficiency
  levels. STRIP parenthetical examples ("Data migration tools", not "(e.g., SnowConvert)").
- Plain text only — no LaTeX or "$" math.

Skills section:
"""
{skills_text}
"""

Return ONLY the complete updated skills section text.
```

### 3e. `bullet_strengthen`, `bullets_reorder`

Unchanged except: `bullet_strengthen` metrics note now reads from the ledger via state
(current behavior) — no text changes; both tools' empirical behavior was clean.

### 3f. Fallback rewriter (`agents/rewriter.py`)

`PRIORITY 1 — KEYWORD SATURATION` is replaced:

```
PRIORITY 1 — TRUTHFUL KEYWORD ALIGNMENT
  Weave the VERIFIED keywords below into existing bullets and summary. Every keyword
  listed is evidenced by the resume itself; skip any keyword that would require claiming
  a new duty, tool, or role. Never add content solely to host a keyword.
```

The keyword list passed in is pre-filtered by the same allowlist partition; skipped items
are returned in the result dict as `gaps` so the fallback path feeds the same gap report.
The claims-ledger block (which now includes capabilities) stays in the prompt.

## 4. Pipeline reorder + guard upgrade (`main.py`, `agents/fabrication_guard.py`)

### 4a. New stage order in `_run_pipeline_task`

```
Phase 2 optimize → humanize → skills-normalize → sanitize
  → fabrication_guard (capability-aware, final text)
  → verifier
  → final score  (scores the DELIVERED text)
  → docx / persist / report
```

The verifier moves out of `run_optimization_async` and into `main.py` after the guard,
so it sees the delivered text: `_with_verifier` is removed from `optimizer.py`, and
`main.py` calls `verify_final_draft` directly at the new position (with
`set_call_kind("verifier")`; `verifier_flagged` is produced by this call from now on).
`set_call_kind("humanize")` is set before the humanizer. `chat/handoff.apply_edit` adopts
the same tail for its path (it has no humanize stage): agent → guard → verifier →
re-score.

Cost impact: the final score is now always a real call (~$0.001/job, the LRU can no
longer pre-warm it because humanize changes the text). Bought with it: the persisted
score matches the delivered document (measured gap today: 5–8 points), and the guard/
verifier cover the humanizer for the first time. Net job cost change ≈ +8%, offset by
the treadmill stop (2c) and dead-call removals (2d, 5b).

### 4b. Guard: capability check + no more `[VERIFY]` markers

- New check per line (pure CPU): taxonomy terms (same `skills_normalizer` vocabulary)
  present in the generated line but absent from `ledger.capabilities` AND absent from the
  original resume text → the line carries an unevidenced capability claim.
- Unverified lines (metric, company, or capability) are handled as the docstring already
  promises: substitute the closest original bullet (existing difflib path, ratio > 0.35)
  or drop the line. **Never emit `[VERIFY]` into the text.** Flags go to
  `GuardResult.gaps`/`stripped` and ride into the report and `verifier_flagged`-style
  metadata. The docstring's "Nothing unverifiable is ever kept" becomes true.

### 4c. Gap report plumbing

`run_agent`/`run_debate` (and the deterministic fallback's `gaps` from Section 3f) →
`run_optimization_async` → `main.py`: `honest_gaps` merges tool-recorded gaps + guard
capability drops, deduped. `main.py` passes them into
`utils/optimization_report.build_report(...)` (new optional arg, rendered as a
"Real gaps for this JD" list) and stores them in the ChatSession `last_result` dict as
`honest_gaps`. No frontend work in this spec.

## 5. Judge prompts

### 5a. Humanizer (`agents/humanizer.py`)

Step-1 system, rule 2 replaced and one rule added:

```
2. Confident assertions — replace hedges ("helped with", "assisted in") with direct
   ownership ("led", "built", "delivered") ONLY where the surrounding text shows the
   candidate owned that work. If ownership is not evidenced, keep the honest scope
   ("contributed to", "supported") and strengthen the verb within that scope.
...
Do NOT add any new skill, tool, technology, metric, or achievement. Do NOT change job
titles or seniority wording anywhere, including the summary.
```

Step-2 critic call passes `response_format={"type": "json_object"}` (its free-form JSON
silently failed in both profiled prod runs). Step-3 prompt gains the same "Do NOT add any
new skill/tool/metric; do NOT change titles or seniority" line. The guard now running
after humanize is the structural backstop.

### 5b. Debate reviewer (`orchestration/debate_loop.py`)

- Reviewer prompt receives the per-dimension block (`_build_scores_context`) and the
  current gap list instead of `overall=NN` only.
- New text:

```
You are a skeptical resume reviewer. The optimizer revised this resume and can run more
tools, but it can only make PRESENTATION fixes to existing, verified content:
  - keyword_inject: weave pre-verified keywords into existing sentences
  - bullet_strengthen: stronger verbs on existing bullets
  - skills_rewrite: sync the skills section with skills evidenced elsewhere in the resume
  - bullets_reorder: reorder existing bullets by JD relevance

{scores_block}

HONEST GAPS already identified (impossible to fix truthfully — do NOT raise these):
{honest_gaps}

CURRENT RESUME DRAFT:
{draft}

Raise ONE objection that is fixable purely by presentation changes to existing content.
Do NOT raise objections about: missing skills, keywords, metrics, certifications, or
experience the resume does not contain; tone or wording (a humanize stage follows);
employment gaps or dates.
If you have no fixable objection, respond EXACTLY: No objections.
Otherwise respond EXACTLY: OBJECTION: <one presentation issue, 20 words or less>
```

- The final round skips the between-round re-score and the reviewer call entirely (its
  objection is discarded today; measured ≈11% of pro-job cost). The `debate_review` SSE
  event for the skipped round is dropped with it.

### 5c. Verifier (`agents/verifier.py`) — prompt hardening only

Add the original resume text to the prompt (it currently sees only ledger lists, which
caused a live false positive on the resume's own "40%" metric), and bound the output:

```
ORIGINAL RESUME (ground truth):
{original_resume}

VERIFIED FACTS: {ledger lists as today}

RESUME DRAFT: {draft}

Flag ONLY concrete claims — a skill, tool, title, company, degree, or number — that
appear in the draft but have no support in the original resume or verified facts above.
Do not flag rephrasings of supported claims. At most 10 flags.
Output format: one unsupported claim per line, or "VERIFIED" if clean. No prose.
```

`verify_final_draft` gains an `original_resume: str` parameter; callers updated
(`main.py`, `chat/handoff.py`).

### 5d. Scorer (`agents/scorer.py`) — one-line hygiene

System prompt addition: `missing_keywords must be concrete skills, tools, or domain
terms — never seniority words ("Senior", "Lead"), role adjectives, or soft phrases.`
JD analyzer addition: `required_hard_skills entries must be 1-3 word technologies or
competencies, not requirement sentences.` No rubric overhaul in this spec (deferred with
SCORE_TARGET calibration); the truth constraints live upstream of the scores.

## 6. Observability

- `set_call_kind("humanize")` and `set_call_kind("verifier")` at the new call sites
  (today humanizer bills as `final_scoring`, verifier as `phase2_optimizer`/`pro_debate`
  — measured ≈8% of job cost misattributed).
- No schema changes; `honest_gaps` count may be added to the pipeline `done` event
  payload for the UI later.

## Testing & verification

Unit (pytest, run via the Windows venv per project convention):
- `test_fact_extractor`: capabilities extraction — skills-section tokens, taxonomy hits
  in experience, casing, merge/serialize round-trip.
- `test_tools`: inject/skills filtering — evidenced pass through, unevidenced recorded as
  gaps and absent from the prompt (assert via mocked `complete`), refusal strings.
- `test_agent_loop`: capped-dimension stop condition (below-target + no actionable ⇒
  loop exits without extra turns); scores-context snapshot with addable/gap split;
  system-prompt snapshot includes ledger and excludes "above 90" phrasing.
- `test_fabrication_guard`: capability check drops/substitutes unevidenced-tech lines; no
  `[VERIFY]` in output text; gaps recorded.
- `test_pipeline_order` (main.py): guard/verifier/score run after humanize (call-order
  spy); persisted score computed on delivered text.
- Debate: final round makes no reviewer/re-score calls; reviewer prompt contains scores
  block + gaps.

Empirical regression eval: `_try_optimizer.py` gains assertions — delivered text contains
no taxonomy term absent from ledger+original, no `[VERIFY]`, `scores(delivered) ==
persisted final score` (same text), `honest_gaps` non-empty for the sample JD. Run
standard + pro before merge; compare cost/latency ledgers against the 2026-07-07
baselines ($0.0096 / $0.0085).

The existing suite (464 passing) must stay green; tests asserting the old system-prompt
text, `critique_resume`, `_with_verifier`, or the old stage order are updated as part of
the same change.

## Risks & mitigations

- **Allowlist misses a legitimate skill** (taxonomy gap) → it lands in `honest_gaps`
  instead of the resume. Failure mode is honest and user-visible; taxonomy is extendable
  in one place. Tools only *filter their inputs* — they never delete existing resume
  content, so nothing true is ever removed by this mechanism.
- **Guard capability check false positives** on generic words → vocabulary is the curated
  taxonomy only, whole-word matches, and lines get the substitution path before dropping.
- **Scores plateau below 90 for mismatched candidates** → intended behavior; the capped
  flag + gap report explain it. Watch conversion metrics after rollout.
- **Cross-job prompt-cache hits lost** (ledger in system prompt) → within-job hits
  (75–97% measured) dominate; accepted.

## Rollout

Direct change, no feature flag — the current behavior (fabrication) is the thing being
removed, and a flag would keep it reachable. The profiler eval gates the merge.

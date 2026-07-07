# Review-Findings Fixes — Design

**Date:** 2026-07-06
**Branch:** `claude/effort-estimation-m4a4ep`
**Source:** deep code review of `main...HEAD` (8 finder angles, per-candidate verification). 10 findings reported: 9 correctness (8 CONFIRMED, 1 PLAUSIBLE) + 1 costing (CONFIRMED).

## Scope

In scope — all 10 reported findings:

| # | File | Defect |
|---|------|--------|
| 1 | `backend/limiter.py:18` | Rightmost XFF entry used verbatim; Azure appends `IP:port`, so every connection gets a fresh rate-limit bucket |
| 2 | `backend/alembic/versions/0022_rename_metadata_to_meta.py:25` | `information_schema.columns` probe crashes `alembic upgrade head` on SQLite (CI smoke test, dev startup) |
| 3 | `backend/chat/state_machine.py:116` | Failed/reaped run bricks the session: phase stays OPTIMIZING forever, canned reply intercepts every message |
| 4 | `backend/chat/state_machine.py:106` | Bare "yes" in JD_CAPTURED launches a paid run with `instruction=""`, dropping gap context |
| 5 | `backend/chat/state_machine.py:89` | Fuzzy profile-label match (substring, ratio ≥ 0.6) auto-launches a run / auto-downloads a docx with no confirmation |
| 6 | `backend/main.py:130` | `_claim_job_for_run` allows error→running re-claims but never resets `quota_refunded`, so failed retries are never refunded |
| 7 | `backend/main.py:118` | Refund targets the `created_at` date; reservation increments `date.today()` at claim — cross-day mismatch makes the refund a no-op |
| 8 | `backend/chat/router.py:521` | LLM exceptions collapse into `fallback_response(phase)`: a canned reply is persisted with no error SSE event |
| 9 | `backend/chat/state_machine.py:41` | `edit_resume` exposed only in RESULTS_READY; pre-optimization profile edits (still implemented + tested) unreachable from chat |
| 10 | `backend/admin/router.py:1033` | `cache_efficiency` savings hardcode $0.30/1M × 75% across all providers |

Out of scope: the 12 confirmed cleanup findings (quota-SQL dedup, dead code, llm.py consolidation, eager history load, spaCy executor, `_URL_RE`/env-var duplication). They are a separate cleanup pass.

## Decisions (agreed during brainstorm)

1. One spec covering all 10 findings.
2. Launch UX: **confirm before acting** — picker clicks stay instant; bare labels and affirmations propose, never fire.
3. Pre-optimization edits: **restore** the capability.
4. Bricked-session recovery: **read-time job-status check**, not error-path context writes.
5. Refund dating: **stamp the reservation date on the job** (new column), reset `quota_refunded` on re-reservation.
6. Cache savings: **LiteLLM pricing map first**, `DEFAULT_PROVIDER_RATES` as fallback only; refresh the stale fallback numbers.

---

## A. Chat state machine (findings 3, 4, 5, 9)

### New session-context keys

- `_job_id` — set by `_launch_and_stream` alongside `_optimizer_launched`; lets the session find its `PipelineJob`.
- `_pending_confirm` — `{"action": "launch" | "download", "profile_id": <id>}`; written when a deterministic match proposes an action. Consumed by an affirmation; cleared by any other message.
- `last_error` — short string set by failure recovery (for prompt context and debugging).

### Confirm-before-acting (`try_deterministic`)

- **Picker clicks** (the exact quoted `Use my "X" profile` format the UI sends) keep acting instantly — they are button presses, not free text.
- **Bare / fuzzy label matches** return a deterministic *proposal* instead of an action, and set `_pending_confirm` — replacing the two auto-actions the current code fires:
  - JD_CAPTURED (with `jd_text`, not launched) → "Ready to optimize with your **{label}** profile? Say yes to launch, or tell me anything to add first (real experience, tools, context)."
  - AWAITING_JD → "Want me to export your **{label}** profile as a Word document? Say yes to download."
  - The 0.6 fuzzy ratio in `_find_profile_by_label` is retained unchanged: it now only gates a prompt, never an action.
- **Affirmations** (`_AFFIRM_RE`) act only when `_pending_confirm` exists, executing exactly the pending action, then clearing it.
  - Bare "yes" with no pending proposal falls through to the LLM (which sees history — fixes the gap-question misfire).
  - Longer replies ("yes — also mention my Kafka work at Acme") don't match the anchored regex and go to the LLM, whose `launch_optimizer` tool passes `added_context` — collected gap details are no longer dropped.
- Any non-affirmation message clears `_pending_confirm` and is processed normally.

### Failure recovery (read-time job check)

`resolve_phase` stays a pure function of context. The router adds one step when the resolved phase is OPTIMIZING (`_optimizer_launched` set, no `last_result`): query `PipelineJob` by `ctx["_job_id"]` — one indexed query per turn, only while optimizing.

- `running` / `pending` → stay OPTIMIZING; canned "still running" reply as today.
- `error` **or job missing** → write `last_error`, clear `_optimizer_launched` and `_job_id`, persist context, reply deterministically: "That run failed and your quota was refunded. Say yes to retry with your **{label}** profile." and set `_pending_confirm` for the retry — `profile_id` taken from the queried job row (`PipelineJob.profile_id`), falling back to the recommended profile if null. Phase falls back to JD_CAPTURED naturally (`jd_text` is still in context). The refund claim is safe because `_refund_job_quota` runs on all error paths and section B makes it reliable; a retry reserves fresh quota via the normal launch path.
- `done` but `last_result` absent from context (partial-write edge) → clear the flag and point the user to the dashboard; no result backfill attempted.
- Sessions already bricked in production self-heal on their next message. If `_job_id` is absent (sessions launched before this change), treat as "job missing" → recover.
- The relaunch guard ("Start a new chat to optimize again") and `apply_edit`'s 409 both key off `_optimizer_launched`; recovery clearing the flag unblocks them with no further changes.

### Pre-optimization edits restored

- `tools_for_phase`: add `EDIT_TOOL` to AWAITING_JD and JD_CAPTURED (OPTIMIZING stays empty; RESULTS_READY unchanged).
- `agent.py` AWAITING_JD/JD_CAPTURED phase prompts regain the edit guidance, including the "RESUME EDITS" heading (makes `test_system_prompt_has_edit_guidance` pass unmodified).
- `apply_edit`'s `profile_id` path needs no changes — it already works.

## B. Quota accounting (findings 6, 7)

- **Migration 0026**: add `pipeline_jobs.quota_reserved_on` (DATE, nullable). Written dialect-portably (inspector pattern, no `information_schema`).
- **Reservation stamps the job**: `run_pipeline` computes `today = date.today()` once and passes it to `reserve_run_quota` (new optional `on_date` parameter, default today). After a successful reservation it updates the job row: `quota_reserved_on = today`, `quota_refunded = False`. Resetting the flag at reservation re-arms the refund for every retry (finding 6); stamping the date the reservation actually used keeps refund and reservation on the same counter row even across midnight (finding 7).
- **Refund uses the stamp**: `_refund_job_quota` passes `run_date = job.quota_reserved_on or _counter_date_for(job.created_at)` — the fallback keeps pre-0026 rows refundable. The `WHERE quota_refunded IS FALSE` flip-guard is retained; it is now correct because every new reservation resets the flag.
- The reaper needs no special handling — it flows through the same `_refund_job_quota`.

## C. Chat error handling (finding 8)

- Exceptions and empty responses are distinct again in `event_generator`:
  - First LLM attempt raises → retry once; log accurately ("chat completion failed; retrying") — the false `temperature=0.7` log line is removed.
  - Second attempt raises → yield final "❌ Sorry — I hit an error. Please try again." **plus an `error` SSE event**, persist no assistant message, return. This restores main's contract; the existing frontend error handler works again.
  - `fallback_response(phase, ctx)` is reserved for its documented case — a successful call returning empty content. Only that path persists a fallback message.

## D. Mechanical fixes (findings 1, 2, 10)

### Limiter (finding 1)

After selecting the rightmost XFF entry, strip the port Azure App Service appends:

- starts with `[` → bracketed IPv6: return the content inside `[...]`.
- exactly one `:` → `IPv4:port`: strip the port.
- zero or ≥ 2 colons → bare IPv4 / bare IPv6: return as-is.

The rightmost-entry trust model itself is unchanged in this pass.

### Migration 0022 (finding 2)

Replace the `information_schema.columns` probe with the inspector pattern migration 0013 already uses (`sa.inspect(op.get_bind())`), and perform the rename inside `batch_alter_table` so it works on SQLite. Acceptance: CI's migration smoke test (`alembic upgrade head` on a fresh `sqlite+aiosqlite` DB) goes green.

### Cache savings — LiteLLM-first (finding 10)

`resolve_cost()` in `utils/cost.py` is already LiteLLM-native-first; `cache_efficiency` becomes consistent with that pattern instead of hardcoding rates:

- New helper in `utils/cost.py` — `cache_rates(model) -> (input_cost_per_token, cache_read_cost_per_token)`:
  1. LiteLLM pricing map first (`litellm.get_model_info(model)` / `litellm.model_cost`): `input_cost_per_token`, `cache_read_input_token_cost`.
  2. Fallback when LiteLLM has no mapping (or no cache-read rate): derive from `DEFAULT_PROVIDER_RATES` with a conservative cached rate of 25% of input.
- `cache_efficiency` groups `SUM(cached_input_tokens)` by `LlmCallLog.model` (indexed; stores the provider-prefixed name) and computes `estimated_savings_usd = Σ_model cached_tokens × (input_rate − cache_read_rate)`. The hardcoded `× 0.30 × 0.75` is deleted.
- Refresh the four `DEFAULT_PROVIDER_RATES` tuples to current published list prices, verified against provider docs at implementation time (not from memory). They remain fallback-only. No migration; historical `cost_usd`/`cost_source` values are untouched.

## E. Testing

- **State machine:** bare "yes" with no pending proposal reaches the LLM; label match produces a proposal (not an action); "yes" after a proposal executes it; any other message clears the proposal; exact picker clicks act instantly.
- **Recovery:** job `error`/missing → failure reply + flag cleared + retry proposal; `done` without `last_result` → dashboard pointer; `running` → unchanged; legacy session without `_job_id` recovers.
- **Quota:** retrying a failed job refunds again (flag reset at reservation); refund decrements the `quota_reserved_on` row across a midnight boundary; legacy row (null stamp) falls back to `created_at`.
- **Limiter:** Azure `IP:port`, `[IPv6]:port`, bare IPv6, plus the existing spoofing cases in `test_ratelimit_key.py`.
- **Cache savings:** mixed-provider fixtures with `litellm.get_model_info` mocked, covering both the LiteLLM-priced and table-fallback paths.
- **Edits:** `tools_for_phase` includes `EDIT_TOOL` in AWAITING_JD/JD_CAPTURED; `test_pr7_edit_resume.py` and `test_system_prompt_has_edit_guidance` pass unmodified.
- Full backend suite via the Windows `.venv` (the 24 known pre-existing failures are the tolerated baseline). CI green, including the migration smoke test.

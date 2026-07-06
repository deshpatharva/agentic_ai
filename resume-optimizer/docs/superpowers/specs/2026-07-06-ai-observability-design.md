# AI Observability for Admin — Design

**Date:** 2026-07-06
**Branch context:** builds on `claude/effort-estimation-m4a4ep` (post deep-review fixes, PR #58)

## Problem

The admin dashboard has solid cost/usage accounting (`llm_call_log` ledger; `/admin/analytics/*` endpoints; Analytics page charts for spend, tokens, by-model, cost audit, cache efficiency) but lacks the failure-and-latency half of industry-standard LLM observability:

- **Failed LLM calls are never recorded.** `llm.py`'s exception paths log a traceback to stdout and re-raise — nothing reaches the ledger, so error rates are unknowable in-product.
- **No latency percentiles.** `latency_ms`/`ttft_ms` are captured per row but never aggregated; no p50/p95/p99 anywhere.
- **No trace visibility.** `trace_id` and `job_id` exist on every row but no endpoint or UI shows the calls that made up a run.
- **No at-a-glance health signal.** "Is the AI degraded right now?" requires reading charts.
- **Silent truncation/content-filter events invisible.** `finish_reason` is not captured.

## Decisions (agreed during brainstorm)

1. **In-app, not external platform.** Deepen the existing admin rather than adopting OTel export or a hosted LLM-observability product. Column naming follows OpenTelemetry GenAI semantic conventions where sensible (`error_type` ≈ `error.type`, `finish_reason` ≈ `gen_ai.response.finish_reasons`) so a future export is a mapping, not a rework.
2. **Error metadata only — never payloads.** Status, exception class, provider code, attempt, finish_reason. No prompt/completion text is ever stored (resumes/JDs are PII).
3. **Health badges, no notification infra.** Green/amber/red threshold badges in the admin; alerting/notifications remain the Azure ops layer's job (see "Two-layer contract").
4. **Extend `llm_call_log`, aggregate on read.** One migration; failures recorded through the existing `_record_call` chokepoint; endpoints compute windowed aggregates at read time (same philosophy as `cache_efficiency`). No rollup tables, no background jobs.
5. **UI adds only what doesn't exist.** Analytics keeps every current chart; nothing is duplicated.

### Two-layer contract (why no in-app alerting)

- **Azure ops layer (exists):** App Service console logs → Log Analytics (`monitoring.tf` diagnostic setting). Owns infra logs and notification-style alerting; tracebacks from LLM failures already land there. The spec appendix provides a ready-to-paste KQL query for alerting on LLM error spikes; no Terraform changes in this project.
- **In-app product layer (this spec):** structured LLM-semantic observability (tokens, cost, latency, errors, traces joined to users/jobs) rendered in the admin UI, working identically in local dev and production.

## A. Failure capture & schema

### Migration 0027 — `llm_call_log` columns

| Column | Type | Default | Meaning |
|---|---|---|---|
| `status` | VARCHAR(16) NOT NULL | `'ok'` | `ok` \| `error`; existing rows backfill to `ok` via the column default (no UPDATE needed) |
| `error_type` | VARCHAR(100) NULL | — | exception class name (LiteLLM taxonomy: `RateLimitError`, `Timeout`, `APIConnectionError`, `BadRequestError`, …) |
| `error_code` | VARCHAR(40) NULL | — | HTTP status / provider code when the exception exposes one (`getattr(exc, "status_code", None)`) |
| `attempt` | SMALLINT NOT NULL | `1` | attempt number at the call site; `complete_with_tools`' internal no-tools fallback records `2` |
| `finish_reason` | VARCHAR(40) NULL | — | `stop`/`length`/`tool_calls`/`content_filter` from the response on success |

Plus index `ix_llm_call_status_created (status, created_at)`. Migration is dialect-portable (plain `add_column`s — no ALTER-with-FK, safe on SQLite without batch mode; follow 0026's style). Model changes mirror the columns in `db/models.py::LlmCallLog`.

### Capture in `llm.py`

All three entry points (`complete`, `complete_with_tools`, `stream_chat`) wrap the provider call:

- **On exception:** record via the existing `_record_call` with `status='error'`, `error_type=exc.__class__.__name__`, `error_code=str(getattr(exc, "status_code", ""))[:40] or None`, measured `latency_ms`, zero tokens/cost (`cost_source='error'`), the current `trace_id`/`call_kind`/`model`/`provider` — then **re-raise unchanged**. Caller behavior is untouched; today these rows simply don't exist.
- **On success:** additionally record `finish_reason` (`response.choices[0].finish_reason`, defensively via getattr) and `status='ok'` (explicit).
- `complete_with_tools`' internal no-tools fallback passes `attempt=2` for both its error and success records.
- **Parity fix in passing:** `stream_chat`'s success record gains `cached_input_tokens`/`cache_hit` extraction (the same 3-line dance the other two paths already have), since these dicts are being edited anyway.

## B. Admin API — new module `backend/admin/observability.py`

Own `APIRouter(prefix="/admin/observability")`, same `get_admin_user` dependency as existing admin routes, registered in `main.py` alongside the existing admin router. `admin/router.py` (~1,060 lines) is not grown further. Existing `/admin/analytics/*` endpoints are untouched.

1. **`GET /health`** — 24h window vs 7-day baseline. Returns `{signals: {error_rate, p95_latency_ms, cost_burn_usd}, counts}`, each signal `{value, baseline, status}` with `status ∈ ok|warn|crit`:
   - error rate: warn ≥ 2%, crit ≥ 5% (of calls in window; `ok`-only windows report 0)
   - p95 latency: warn ≥ 1.5× baseline, crit ≥ 2× (baseline = 7-day p95; if baseline is empty, status `ok` with `baseline: null`)
   - cost burn: 24h cost vs 7-day daily average — warn ≥ 1.5×, crit ≥ 2.5×
   - Thresholds are module constants (`_ERROR_RATE_WARN = 0.02`, …); no config UI.
2. **`GET /series?days=30`** — buckets (daily; hourly when `days <= 2`): `calls, errors, error_rate_pct, p95_latency_ms` per bucket. Cost/token series deliberately excluded — `/admin/analytics/tokens` already serves them.
3. **`GET /latency?days=7`** — per-model `p50/p95/p99` of `latency_ms`, plus the same for `ttft_ms` over rows where it's non-null, and call counts. Percentiles computed in Python (SQLite has no `percentile_cont`) from windowed values, fetch hard-capped at 50,000 rows (newest first; response notes `capped: true` when hit).
4. **`GET /errors?days=7`** — `{breakdown: [{error_type, provider, model, count, last_seen, sample_error_code}], recent: [50 newest error rows: created_at, model, provider, call_kind, error_type, error_code, attempt, latency_ms, trace_id, job_id]}`.
5. **`GET /trace?trace_id=…` or `?job_id=…`** (exactly one required, else 422) — ordered calls for the trace/job: `{offset_ms (from first call's created_at), latency_ms, call_kind, model, status, error_type, finish_reason, input_tokens, output_tokens, cached_input_tokens, cost_usd, attempt}`, plus `{job: {status, error_message, created_at}}` when a `pipeline_jobs` row matches. 404 when no calls found.

Percentile helper (`_percentiles(values, (50, 95, 99))`) lives in `observability.py`; nearest-rank method; returns `None`s for empty input.

## C. Admin UI — additions only

- **`AdminDashboard.jsx`:** health badge row at the top — three tiles from `/health` using the existing stat-tile pattern in `adminUi.jsx`, colored by `status` (green/amber/red) showing value + baseline.
- **New `Observability.jsx`** (added to `AdminLayout` nav as "AI Observability"), exactly four views:
  1. error-rate trend — calls vs errors per bucket from `/series` with a 7/30/90-day switch (the one new chart; mirrors Analytics' existing `ChartCard` + chart approach),
  2. per-model latency percentile table from `/latency`,
  3. errors panel from `/errors` — by-type breakdown table + recent-errors table; rows with `trace_id`/`job_id` link to the waterfall,
  4. trace lookup (input accepting a trace id or job id) + waterfall render of `/trace` (horizontal bars proportional to `latency_ms`, offset-positioned, colored by status, labeled with call_kind/model/tokens/cost).
- **`PipelineRuns.jsx`:** one "LLM calls" link per run row → the waterfall view with that `job_id`.
- No changes to `Analytics.jsx`; no duplicated charts anywhere.

## D. Testing

Backend (WSL→Windows venv conventions: env vars via `os.environ.setdefault` inside test files; no non-ASCII in assertion literals):

- **Capture unit tests:** monkeypatch the provider call to raise (e.g. an exception with `status_code=429`) → assert an `status='error'` row lands with `error_type`/`error_code`/`latency_ms` and that the exception still propagates to the caller; success path records `finish_reason`; `stream_chat` records cached-token fields.
- **Aggregation unit tests:** `_percentiles` (empty, single, exact-boundary inputs); health threshold math at each boundary (1.99% vs 2.0% error rate, etc.); series bucketing day/hour switch.
- **Endpoint tests:** seeded `LlmCallLog` rows via the `get_admin_user` override pattern from `test_admin.py`; cover each endpoint incl. empty-window responses, `/trace` 422/404 cases, and the 50k cap flag.
- **Migration:** 0027 rides the existing `alembic upgrade head` SQLite smoke test (CI + test_migrations).

Frontend testing is manual (no frontend test infra exists in this repo — out of scope to introduce one here).

## Out of scope

- Notifications/alert delivery (Azure Monitor's job — appendix below), retention/TTL for ledger rows, OTel/OTLP export, eval/quality scoring, prompt/completion payload capture, threshold configuration UI.

## Appendix — Azure ops-layer KQL (documentation only, not built)

Alert candidate for Log Analytics (`AppServiceConsoleLogs`), e.g. scheduled query rule firing on >10 LLM errors in 15 minutes:

```kusto
AppServiceConsoleLogs
| where TimeGenerated > ago(15m)
| where ResultDescription has_any ("chat completion failed", "Pipeline error", "LLM call failed")
| summarize errors = count() by bin(TimeGenerated, 5m)
| where errors > 10
```

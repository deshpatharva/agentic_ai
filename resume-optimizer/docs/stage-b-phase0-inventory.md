# Stage B · Phase 0 — Backend Profiling & Inventory

**Date:** 2026-06-12 · **Scope:** read-only analysis; no code changed.
**Status:** ✅ **P1 (B1–B6) approved and implemented 2026-06-12.** ✅ **P3 (R1–R6) + E1 approved and implemented 2026-06-12.** ✅ **P2 (D1–D3) approved and implemented 2026-06-12** — `/upload`, `/analyze-jd`, `/generate-doc`, `/dashboard/match-analytics`, and the dead scorer helper (with its sklearn dependency and second spaCy load) removed along with their 11 orphaned tests; suite green at 194/194. ✅ **P4 (X1) approved and implemented 2026-06-12** — `utils/llm_json.parse_llm_json` replaces the four divergent parsing copies (scorer, jd_analyzer, profiles parse/interview, profile matching); 10 unit tests; suite 204/204. **Every inventory item is now resolved.**

## P3 + E1 implementation record

**E1 — test infrastructure repaired; full suite green for the first time (205/205, was 112/191 passing on pristine code).** Root causes fixed:
- Every API test module set `app.dependency_overrides[get_db]` at **import time** on the shared app object — the last-imported module hijacked every other module's DB. Overrides now install/remove inside each module-scoped fixture (10 files), and `test_prod_fixes` (which had no override at all) got one.
- `test_smoke` also points `main.AsyncSessionLocal` at its module DB (the `/download`/`/status` paths bypass `get_db`).
- Engines now `dispose()` before DB-file removal (Windows lock `PermissionError`s); register-or-login fixtures (function-scoped fixtures re-registered the same email per test → `KeyError: 'user'`); bootstrap tests send the now-required `secret`.
- The isolation work **unmasked three real production bugs**, all fixed: (1) naive-vs-aware datetime comparisons in promo redemption / trial extension / admin promo status on SQLite (`utils/time_utils.ensure_utc`); (2) `db/session.py` passed Postgres pool kwargs to SQLite (cold-start crash on `:memory:`); (3) migration 0013 used `information_schema` (Postgres-only) and an inline-FK `add_column` (un-ALTER-able on SQLite — now batch mode). Migration tests now assert against the live alembic head instead of a hard-coded revision.
- Stale tests aligned to current behavior (LLM helper 4-tuple returns, `{"text":…, "tokens":…}` wrappers, guard's `[VERIFY]`-flag policy, `analyze-jd` 422-on-oversized per the pre-existing prod-readiness test).

**R1** — `source`/`min_score` filtering moved inside `read_job_matches` BEFORE pagination; `total` is the filtered count (was: filtered after slicing + total overwritten). Test: `test_read_job_matches_filters_before_pagination`.
**R2** — `/download/{id}` falls back to the completed `PipelineJob` (owner + done + `download_path`) when the Resume row is missing, fixing the dead `done`-event fallback link. Tests: fallback 200 + pending-job 404.
**R3** — `utils/cache.py` is now a thread-safe LRU bounded at 256 entries. Tests: roundtrip, eviction, recent-use protection (`test_cache_bounds.py`).
**R4** — profile-match parses untrusted LLM output robustly (fence strip → array recovery from prose → clean 502). Tests: prose-wrapped recovery + unparseable 502.
**R5** — per-run `input_tokens`/`output_tokens` persisted on `PipelineJob` (migration **0014**, dialect-portable), written at pipeline completion, surfaced in `/admin/pipeline-runs` and the admin Runs table (Tokens column).
**R6** — dashboard/jd endpoints now log the exception and return generic details (no more `detail=str(e)` internals leakage).

**Verification:** full backend suite **205/205** (7 new regression tests added); frontend build green with the admin Tokens column.

## Phase 1 implementation record (approved scope only)

| Item | What shipped | Verification |
|---|---|---|
| B1 | `delta/writer.py write_job_matches(records)` — whole scrape batch in ONE Delta transaction; `write_job_match` kept as a thin wrapper; `main.py _persist` now makes a single call | `test_write_job_matches_single_transaction` (25 records → 1 commit), `test_write_job_match_delegates_to_batch`, empty-batch no-op |
| B2 | `/dashboard/summary` no longer scans Delta for uploads/tokens (uploads ≡ runs by construction; tokens no longer surfaced) and counts unread via new column-pruned `count_unread_matches` | `test_count_unread_matches` (+ no-table case); response keys unchanged; aligns with the pre-existing `test_prod_fixes` assertion that summary must not call `read_usage_last_n_days` |
| B3 | `read_job_matches` now pushes year/month **partition** filters (DNF derived from the cutoff) and prunes columns — `raw_description` (the largest column, rendered nowhere) is no longer read or returned | `test_match_filters_dnf_includes_partition_columns`, `test_read_job_matches_prunes_raw_description` |
| B4 | `storage.py` caches the `BlobServiceClient` (+credential) instead of rebuilding per call | existing `test_storage.py` green |
| B5 | `llm.complete` sets a 120 s per-call timeout and retries once on transient failures (timeout/connection/5xx) | `test_llm_calls_carry_timeout`, `test_transient_failure_retries_once` |
| B6 | `fabrication_guard` (spaCy/difflib) and the `/jd/scrape` BeautifulSoup parse moved off the event loop via `to_thread` | `test_jd.py` green; pipeline integration unchanged |

Also repaired in passing (tests of touched modules only): two stale delta tests patching `DeltaTable.from_uri` (code uses the constructor) and one stale llm test encoding pre-Gemini-caching behavior.

**Verification:** targeted suites (`test_delta_writer`, `test_storage`, `test_llm`, `test_jd`) **41/41 pass** (baseline was 29 pass + 3 stale failures; 9 new tests added). Adjacent suites (`test_analytics`, `test_health`, `test_smoke`, `test_ratelimit`) show an **identical pass/fail profile to pristine code** (their failures are pre-existing bootstrap-secret/Windows-teardown infra issues, reproduced via `git stash` comparison).

## Backend map (verified by reading, not assumed)

- **Entry:** `main.py` — FastAPI app, CORS/rate-limit/logging middleware, lifespan starts event-cleanup + stuck-job-reaper loops. Routers: auth, user, dashboard, admin, profiles (`/profiles` + `/profile`), jd.
- **Pipeline:** `POST /run-pipeline` → BackgroundTask `_run_pipeline_task` (3 phases: deterministic setup → agentic iteration loop → guard/humanize/docx). Events persisted to `PipelineEvent`, streamed via SSE with pg LISTEN/NOTIFY + polling fallback. LLM calls via `llm.complete` (LiteLLM `acompletion`, fully async). Blocking work (parsers, docx, storage, Delta) is already `asyncio.to_thread`-wrapped almost everywhere.
- **Storage:** `storage.py` sync Azure Blob SDK (to_thread-wrapped at call sites); `delta/writer.py` Delta Lake tables `daily_usage` (partition: date) and `job_matches` (partition: year/month) with per-table write locks and a cached MSI bearer token.
- **Overall judgment:** architecture is sound. The mandate "optimize only where demonstrable benefit" leaves a short list.

---

## Inventory (prioritized; each item has the expected benefit)

### P1 — Performance bottlenecks (real, measured by code inspection)

| # | Item | Where | Expected benefit | Size |
|---|---|---|---|---|
| B1 | **Per-row Delta transactions**: scrape persist loops `write_job_match` per posting → up to ~150 Delta commits/scrape, tiny-file proliferation, tx-log bloat, slower reads forever after | `main.py _persist` + `delta/writer.py` | Batch `write_job_matches(records)` → ~100× fewer commits; faster persist; smaller table; faster every subsequent read | S |
| B2 | **`/dashboard/summary` does 2 Delta scans per page load**: one for `uploads/tokens today` (values the UI no longer shows post-triage) and one fetching up to 1000 full match rows (incl. `raw_description`) just to count unread booleans | `dashboard/router.py:60-73` | Drop the usage scan; column-pruned/count-only unread query → biggest user-facing latency win (dashboard opens on every login) | S |
| B3 | **Ineffective Delta filter pushdown**: `read_job_matches` filters on `scraped_at`/`user_id` but partitions are `year/month` → full-table scan + in-memory pandas pagination on every matches request | `delta/writer.py:251-285` | Derive year/month partition filters from the cutoff + select only needed columns → bounded I/O | S |
| B4 | **New `BlobServiceClient` + `DefaultAzureCredential` per storage call** (token negotiation each download/upload) | `storage.py:35-37` | Module-cached client → shaves 100s of ms from download/generate paths | XS |
| B5 | **No timeout/retry on LLM calls** — a hung provider call stalls a pipeline until the 15-min stuck-job reaper kills it | `llm.py complete()` | Per-call timeout + one bounded retry on transient errors → tail-latency and reliability | XS |
| B6 | **CPU work on the event loop**: `fabrication_guard` (spaCy/difflib over the whole resume) called without `to_thread`; BeautifulSoup HTML parse in `/jd/scrape` likewise | `main.py:852`, `jd/router.py:100` | Wrap both → event loop stays responsive under concurrent runs | XS |

### P2 — Dead code (most orphaned by approved Stage A removals)

| # | Item | Where | Expected benefit | Size |
|---|---|---|---|---|
| D1 | `POST /upload`, `POST /analyze-jd`, `POST /generate-doc` + their request models + `_UPLOAD_MAGIC` — zero frontend consumers since AppPage removal (new flow: `/profile/parse` → `/profile/prepare-job`) | `main.py` (~170 lines) | Smaller attack surface; 3 fewer auth'd endpoints to maintain. **Caveat:** confirms the API is single-frontend; say if anything external calls these | S |
| D2 | `GET /dashboard/match-analytics` — consumer removed in Stage A (admin variant consciously deferred) | `dashboard/router.py` (~70 lines) | Removes an endpoint that reads 10 000 Delta rows per call | XS |
| D3 | `agents/scorer.py`: `_extract_jd_keywords` never called → its `spacy.load` (second model instance in memory) + entire sklearn import + unused `result_cache` import ride along | `agents/scorer.py` | ~2-3 s faster cold start; ~50-80 MB less RSS; sklearn possibly droppable from requirements | XS |
| D4 | Unused `result_cache` import in `main.py`; function-local re-imports in `dashboard/summary` | misc | Lint hygiene only — folded into touched files, not a standalone task | — |

### P3 — Reliability / correctness

| # | Item | Where | Expected benefit | Size |
|---|---|---|---|---|
| R1 | `/dashboard/job-matches` applies `source`/`min_score` filters **after** pagination and overwrites `total` → broken paging the moment the UI uses filters (latent today) | `dashboard/router.py:193-201` | Correct totals/pages; unblocks future filter UI | XS |
| R2 | Broken download fallback: when the `Resume` row save fails, the `done` event links `/download/{job_id}`, but `/download` looks up `Resume.id` → guaranteed 404 | `main.py:960-961` | Honest failure mode (or resolve blob by job id) — no dead links after partial failures | XS |
| R3 | `utils/cache.py` is an **unbounded** process-lifetime dict (JD-analysis results) — slow memory leak; stale "Claude calls" docstring | `utils/cache.py` | Cap with simple LRU/max-entries → bounded memory on a long-lived server | XS |
| R4 | `_score_profiles` parses LLM JSON with bare `json.loads` → malformed output = 500 to the user ("Profile matching failed") | `jd/router.py:142` | Reuse the robust extractor (see X1) → graceful degradation | XS |
| R5 | **Per-run token counts are never persisted** (only in the 24 h-TTL `done` event); admin cost view relies on `cost_usd` alone | `db.models.PipelineJob` + `_run_pipeline_task` | Two int columns + one migration → durable per-run token observability in the admin Runs table (flagged in Stage A Phase 3) | S |
| R6 | Inconsistent error responses: several endpoints return `detail=str(e)` (leaks internals), others swallow silently | dashboard/jd routers | Uniform pattern: log exception, return generic detail | S |

### P4 — Duplication worth consolidating

| # | Item | Where | Expected benefit | Size |
|---|---|---|---|---|
| X1 | LLM-JSON extraction logic re-implemented ≥3× (`scorer._extract_json`, jd fence-stripping, profiles interview parser) | agents/, jd/, profiles/ | One `utils/llm_json.py` robust parser; fixes R4 as a side effect; single place to harden | S |

### Enabler (prerequisite for Phase 1's "tests before each refactor block")

| # | Item | Where | Expected benefit | Size |
|---|---|---|---|---|
| E1 | Test-infra fixture failures on Windows (`KeyError: 'user'` module-scoped fixture + SQLite teardown `PermissionError`) — pre-existing, reproduce on pristine code | `backend/tests/conftest.py` / `test_admin.py` | A green suite locally — without it, the incremental-validation rule of Stage B Phase 1 can't be honored | S |

### Examined and deliberately dropped (no concrete benefit)

- `optimizer_agent`'s `asyncio.run`-per-tool-call inside `to_thread` — unusual but correct; touching it risks agent behavior (CrewAI-integrity constraint).
- `scraper.py` — already concurrent, timeoutted, deduplicated. Leave alone.
- `profiles/router.py` — clean (use_count via single outer-join, no N+1). Leave alone.
- `POST /scrape-jobs` — no frontend consumer but it's the ops/cron entry for nightly matching. Keep.
- Per-run `write_daily_usage` single-row appends — same small-file pattern as B1 but volume-bounded; revisit only if run volume grows.
- Wholesale type-hint/docstring sweeps — only on modules touched by approved items.

---

## Proposed execution order (Phase 1, after approval)

1. **E1** (green tests) → 2. **B1+B3** (delta writer, one module, one test file) → 3. **B2** (summary) → 4. **B4+B5+B6** (small independents) → 5. **R1–R4, X1** → 6. **R5** (migration) → 7. **D1+D2+D3** (removals last, after everything else is verified against the slimmer surface) → 8. **R6** sweep on touched modules.

Behavioral parity holds throughout except where an item *is* an approved bug fix (R1, R2, R4).

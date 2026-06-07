# Block C — Pipeline Recovery & Health Endpoint: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Block C adds two production safety mechanisms: a stuck-job reaper that automatically recovers pipeline jobs orphaned by worker restarts, and a `/health` endpoint for App Service liveness probes and monitoring. Admin visibility is extended with a `stuck_jobs` count in the existing admin stats dashboard.

## Problem

When App Service restarts mid-pipeline (deploy, crash, scale event), `PipelineJob` rows remain in `status='running'` indefinitely. There is no timeout, no recovery, and no liveness probe. Users see a spinner that never resolves; admins have no visibility into the failure.

---

## Section 1: Stuck-Job Reaper

### Approach

A `_reap_stuck_jobs()` async coroutine, registered as `asyncio.create_task()` in the FastAPI lifespan alongside the existing `_cleanup_events()` task. No new dependencies — same pattern already in use.

### Behaviour

- Wakes every **5 minutes** (`asyncio.sleep(300)`)
- Finds all `PipelineJob` rows where:
  - `status = 'running'`
  - `updated_at < now(UTC) - STUCK_JOB_TIMEOUT_MINUTES`
- Batch-updates them:
  - `status = 'error'`
  - `error_message = "Job timed out — worker may have restarted."`
  - `updated_at = now(UTC)`
- Logs one `WARNING` per cycle containing the count and list of job IDs:
  ```
  WARNING: Reaped 2 stuck jobs: [<uuid1>, <uuid2>]
  ```
- If no stuck jobs found: no log, no action.

### Configuration

`STUCK_JOB_TIMEOUT_MINUTES` environment variable, default `30`. The longest realistic pipeline run (multiple LLM calls + doc generation) is under 15 minutes, so 30 minutes avoids false positives while catching genuine crashes within the next reap cycle.

### Recovery policy

No retry — the job is marked `error` and the user must re-submit. This is intentional: re-running a partially-completed job risks duplicate blob writes and unpredictable LLM output.

---

## Section 2: `GET /health` Endpoint

### Purpose

Liveness probe for App Service health checks and any external monitoring tool. No authentication required.

### Checks (run in parallel)

1. **DB** — `SELECT 1` via the existing async session pool
2. **Storage** — low-cost Azure Blob connectivity check (skipped if `AZURE_STORAGE_ACCOUNT_NAME` env var is absent — local dev mode)
3. **Job counts** — single query:
   - `stuck_jobs`: `COUNT(*) WHERE status='running' AND updated_at < now - STUCK_JOB_TIMEOUT_MINUTES`
   - `pending_jobs`: `COUNT(*) WHERE status='pending'`

### Response

```json
{
  "status": "ok" | "degraded",
  "db": "ok" | "error",
  "storage": "ok" | "error" | "skipped",
  "stuck_jobs": 0,
  "pending_jobs": 3
}
```

### HTTP status codes

| Condition | HTTP status | Reason |
|---|---|---|
| `db = "ok"` | `200` | App Service considers instance alive |
| `db = "error"` | `503` | Forces App Service to recycle the instance |
| Storage failure only | `200` + `status: "degraded"` | Downloads break but auth/pipeline still work |
| `AZURE_STORAGE_ACCOUNT_NAME` absent | `200` + `storage: "skipped"` | Local dev mode |

---

## Section 3: Admin Stats — `stuck_jobs` Field

### Backend

Add `stuck_jobs: int` to `AdminStats` in `admin/schemas.py`.

Add the count query in `admin/router.py` `GET /admin/stats` handler alongside the existing queries:

```python
stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_JOB_TIMEOUT_MINUTES)
stuck_result = await session.execute(
    select(func.count()).where(
        PipelineJob.status == JobStatus.running,
        PipelineJob.updated_at < stuck_cutoff,
    )
)
stuck_jobs = stuck_result.scalar()
```

### Frontend

Add a 5th stat card to `AdminDashboard.jsx` — **"Stuck Jobs"**:
- Value `0`: neutral gray (same style as other cards)
- Value `> 0`: amber/yellow warning color to draw attention

No additional page or action needed — the reaper handles recovery automatically.

---

## Files Changed

| Action | Path |
|---|---|
| Modify | `resume-optimizer/backend/main.py` |
| Modify | `resume-optimizer/backend/admin/schemas.py` |
| Modify | `resume-optimizer/backend/admin/router.py` |
| Modify | `resume-optimizer/frontend/src/pages/admin/AdminDashboard.jsx` |
| Create | `resume-optimizer/backend/tests/test_health.py` |
| Modify | `resume-optimizer/backend/tests/test_admin.py` |

---

## Security Notes

- `GET /health` requires no authentication — standard for liveness probes
- Stuck job count and pending job count are non-sensitive aggregate values; exposing them unauthenticated is acceptable
- The reaper operates only on the app's own database rows; no external side effects

## Out of Scope

- Block D (rate limiting, Postgres VNet)
- Block E (observability — structured logging, metrics, tracing)
- Block F (agent unit tests)
- Manual "reset stuck job" button in admin UI (not needed — reaper handles it automatically)

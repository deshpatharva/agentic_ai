"""Admin AI-observability endpoints: health, series, latency, errors, traces.

Aggregates the llm_call_log ledger at read time (same philosophy as
admin.router's cache_efficiency). Failure rows exist since migration 0027.
All queries are windowed and row-capped; bucketing and percentiles happen in
Python so the same code path serves SQLite (no percentile_cont) and Postgres.
"""

import math
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from admin.dependencies import get_admin_user
from db.models import LlmCallLog, PipelineJob, User
from db.session import get_db

router = APIRouter(prefix="/admin/observability", tags=["admin-observability"])

_FETCH_CAP = 50_000
_ERROR_RATE_WARN, _ERROR_RATE_CRIT = 0.02, 0.05
_LATENCY_WARN_X, _LATENCY_CRIT_X = 1.5, 2.0
_COST_WARN_X, _COST_CRIT_X = 1.5, 2.5


def _percentiles(values, points=(50, 95, 99)):
    """Nearest-rank percentiles; each point is None when values is empty."""
    if not values:
        return {p: None for p in points}
    vs = sorted(values)
    return {p: float(vs[max(0, math.ceil(p / 100 * len(vs)) - 1)]) for p in points}


def _grade(value, warn, crit):
    """ok/warn/crit for a signal value; None (no data / no baseline) is ok."""
    if value is None:
        return "ok"
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


async def _window_rows(db, since, columns):
    """Newest-first windowed fetch, hard-capped. Returns (rows, capped)."""
    rows = (await db.execute(
        select(*columns)
        .where(LlmCallLog.created_at >= since)
        .order_by(LlmCallLog.created_at.desc())
        .limit(_FETCH_CAP)
    )).all()
    return rows, len(rows) == _FETCH_CAP


@router.get("/health")
async def observability_health(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """24h signals vs a 7-day baseline, graded ok/warn/crit."""
    now = datetime.now(timezone.utc)
    day_rows, _c = await _window_rows(
        db, now - timedelta(hours=24),
        (LlmCallLog.status, LlmCallLog.latency_ms, LlmCallLog.cost_usd))
    week_rows, _c = await _window_rows(
        db, now - timedelta(days=7),
        (LlmCallLog.status, LlmCallLog.latency_ms, LlmCallLog.cost_usd))

    def _stats(rows):
        calls = len(rows)
        errors = sum(1 for r in rows if r.status == "error")
        lats = [r.latency_ms for r in rows if r.status == "ok" and r.latency_ms is not None]
        cost = sum(r.cost_usd or 0.0 for r in rows)
        return calls, errors, _percentiles(lats)[95], cost

    d_calls, d_errors, d_p95, d_cost = _stats(day_rows)
    w_calls, w_errors, w_p95, w_cost = _stats(week_rows)

    error_rate = (d_errors / d_calls) if d_calls else 0.0
    baseline_daily_cost = w_cost / 7.0
    cost_ratio = (d_cost / baseline_daily_cost) if baseline_daily_cost > 0 else None
    lat_ratio = (d_p95 / w_p95) if (d_p95 is not None and w_p95) else None

    return {
        "counts": {"calls_24h": d_calls, "errors_24h": d_errors,
                   "calls_7d": w_calls, "errors_7d": w_errors},
        "signals": {
            "error_rate": {
                "value": round(error_rate, 4),
                "baseline": round(w_errors / w_calls, 4) if w_calls else None,
                "status": _grade(error_rate, _ERROR_RATE_WARN, _ERROR_RATE_CRIT),
            },
            "p95_latency_ms": {
                "value": d_p95,
                "baseline": w_p95,
                "status": _grade(lat_ratio, _LATENCY_WARN_X, _LATENCY_CRIT_X),
            },
            "cost_burn_usd": {
                "value": round(d_cost, 4),
                "baseline": round(baseline_daily_cost, 4),
                "status": _grade(cost_ratio, _COST_WARN_X, _COST_CRIT_X),
            },
        },
    }


@router.get("/series")
async def observability_series(
    days: int = Query(30, ge=1, le=180),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Calls/errors/error-rate/p95 per bucket (daily; hourly when days <= 2).

    Cost/token series are deliberately absent — /admin/analytics/tokens
    already serves them (spec decision 5: no duplication).
    """
    now = datetime.now(timezone.utc)
    rows, capped = await _window_rows(
        db, now - timedelta(days=days),
        (LlmCallLog.created_at, LlmCallLog.status, LlmCallLog.latency_ms))
    hourly = days <= 2
    fmt = "%Y-%m-%d %H:00" if hourly else "%Y-%m-%d"
    buckets: dict[str, dict] = {}
    for r in rows:
        ts = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        b = buckets.setdefault(ts.astimezone(timezone.utc).strftime(fmt),
                               {"calls": 0, "errors": 0, "lats": []})
        b["calls"] += 1
        if r.status == "error":
            b["errors"] += 1
        elif r.latency_ms is not None:
            b["lats"].append(r.latency_ms)
    return {
        "bucket": "hour" if hourly else "day",
        "capped": capped,
        "series": [
            {"bucket": k, "calls": b["calls"], "errors": b["errors"],
             "error_rate_pct": round(100.0 * b["errors"] / b["calls"], 2) if b["calls"] else 0.0,
             "p95_latency_ms": _percentiles(b["lats"])[95]}
            for k, b in sorted(buckets.items())
        ],
    }


@router.get("/latency")
async def observability_latency(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-model p50/p95/p99 for latency_ms and ttft_ms (successful calls)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows, capped = await _window_rows(
        db, since,
        (LlmCallLog.model, LlmCallLog.status, LlmCallLog.latency_ms, LlmCallLog.ttft_ms))
    per_model: dict[str, dict] = {}
    for r in rows:
        if r.status != "ok":
            continue
        m = per_model.setdefault(r.model, {"lats": [], "ttfts": [], "calls": 0})
        m["calls"] += 1
        if r.latency_ms is not None:
            m["lats"].append(r.latency_ms)
        if r.ttft_ms is not None:
            m["ttfts"].append(r.ttft_ms)
    models = []
    for name, m in sorted(per_model.items(), key=lambda kv: -kv[1]["calls"]):
        lp, tp = _percentiles(m["lats"]), _percentiles(m["ttfts"])
        models.append({
            "model": name, "calls": m["calls"],
            "latency_ms": {"p50": lp[50], "p95": lp[95], "p99": lp[99]},
            "ttft_ms": {"p50": tp[50], "p95": tp[95], "p99": tp[99]},
        })
    return {"window_days": days, "capped": capped, "models": models}


@router.get("/errors")
async def observability_errors(
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Error breakdown by type x provider x model, plus the 50 newest errors."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    breakdown = (await db.execute(
        select(
            LlmCallLog.error_type, LlmCallLog.provider, LlmCallLog.model,
            func.count().label("count"),
            func.max(LlmCallLog.created_at).label("last_seen"),
            func.max(LlmCallLog.error_code).label("sample_error_code"),
        )
        .where(LlmCallLog.created_at >= since, LlmCallLog.status == "error")
        .group_by(LlmCallLog.error_type, LlmCallLog.provider, LlmCallLog.model)
        .order_by(func.count().desc())
    )).all()
    recent = (await db.execute(
        select(LlmCallLog)
        .where(LlmCallLog.created_at >= since, LlmCallLog.status == "error")
        .order_by(LlmCallLog.created_at.desc())
        .limit(50)
    )).scalars().all()
    return {
        "window_days": days,
        "breakdown": [
            {"error_type": r.error_type or "unknown", "provider": r.provider,
             "model": r.model, "count": int(r.count), "last_seen": str(r.last_seen),
             "sample_error_code": r.sample_error_code}
            for r in breakdown
        ],
        "recent": [
            {"created_at": str(r.created_at), "model": r.model, "provider": r.provider,
             "call_kind": r.call_kind, "error_type": r.error_type, "error_code": r.error_code,
             "attempt": r.attempt, "latency_ms": r.latency_ms,
             "trace_id": r.trace_id, "job_id": str(r.job_id) if r.job_id else None}
            for r in recent
        ],
    }


@router.get("/trace")
async def observability_trace(
    trace_id: str | None = Query(None),
    job_id: str | None = Query(None),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Waterfall: ordered LLM calls for one trace or pipeline job."""
    if bool(trace_id) == bool(job_id):
        raise HTTPException(status_code=422, detail="Pass exactly one of trace_id or job_id.")
    q = select(LlmCallLog).order_by(LlmCallLog.created_at, LlmCallLog.id)
    job = None
    if trace_id:
        q = q.where(LlmCallLog.trace_id == trace_id)
    else:
        try:
            jid = _uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="job_id is not a valid UUID.")
        q = q.where(LlmCallLog.job_id == jid)
        job = await db.get(PipelineJob, jid)
    calls = (await db.execute(q.limit(500))).scalars().all()
    if not calls:
        raise HTTPException(status_code=404, detail="No LLM calls found for that id.")

    def _aware(ts):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    t0 = _aware(calls[0].created_at)
    return {
        "trace_id": trace_id or calls[0].trace_id,
        "job": ({"status": job.status.value, "error_message": job.error_message,
                 "created_at": str(job.created_at)} if job is not None else None),
        "calls": [
            {"offset_ms": int((_aware(c.created_at) - t0).total_seconds() * 1000),
             "latency_ms": c.latency_ms, "call_kind": c.call_kind, "model": c.model,
             "status": c.status, "error_type": c.error_type, "finish_reason": c.finish_reason,
             "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
             "cached_input_tokens": c.cached_input_tokens, "cost_usd": c.cost_usd,
             "attempt": c.attempt}
            for c in calls
        ],
    }

"""
Dashboard endpoints — summary, resumes, usage history, job matches.
All require authentication.
"""

import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from db.models import DailyUsageCounter, PlanLimit, Resume, User
from db.session import get_db
from delta.writer import count_unread_matches, read_job_matches

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return overview: user info, today's usage, plan limits, resume stats, unread matches."""
    user_id = str(user.id)

    # Plan limits
    lim_res = await db.execute(select(PlanLimit).where(PlanLimit.plan == user.plan.value))
    limits = lim_res.scalar_one_or_none()

    # Resume stats
    res_q = await db.execute(
        select(func.count(Resume.id), func.max(Resume.final_score), func.avg(Resume.final_score))
        .where(Resume.user_id == user.id)
    )
    total_resumes, best_score, avg_score = res_q.one()

    # Recent resumes (last 5)
    recent_q = await db.execute(
        select(Resume).where(Resume.user_id == user.id)
        .order_by(Resume.created_at.desc()).limit(5)
    )
    recent = recent_q.scalars().all()

    today_str = date.today().isoformat()

    # runs_today: use transactional counter — authoritative for quota display
    counter = await db.scalar(
        select(DailyUsageCounter).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    )
    runs_today = counter.runs if counter else 0

    # uploads mirrors runs (one upload per run); per-run token totals live in
    # Delta analytics and are no longer surfaced here (approved Stage B item B2 —
    # this removed one full Delta scan from every dashboard load).
    uploads_today = runs_today
    tokens_today = 0

    # Unread job matches — count-only, column-pruned Delta read
    try:
        unread_count = await asyncio.to_thread(count_unread_matches, user_id, 30)
    except Exception:
        unread_count = 0

    quota_pct = round((runs_today / limits.daily_uploads * 100) if limits and limits.daily_uploads else 0, 1)

    return {
        "user": {
            "email":       user.email,
            "full_name":   user.full_name or "",
            "plan":        user.plan.value,
            "member_since": user.created_at.isoformat(),
        },
        "today": {
            "runs":        runs_today,
            "uploads":     uploads_today,
            "tokens_used": tokens_today,
        },
        "limits": {
            "daily_uploads":        limits.daily_uploads if limits else 0,
            "job_scraping_enabled": limits.job_scraping_enabled if limits else False,
        },
        "quota_pct": quota_pct,
        "stats": {
            "total_resumes":  total_resumes or 0,
            "best_score":     round(float(best_score), 1) if best_score else 0,
            "avg_score":      round(float(avg_score), 1)  if avg_score  else 0,
            "unread_matches": unread_count,
        },
        "recent_resumes": [
            {
                "id":           str(r.id),
                "filename":     r.original_filename,
                "final_score":  r.final_score,
                "iterations":   r.iterations,
                "version":      r.version,
                "created_at":   r.created_at.isoformat(),
                "download_url": f"/download/{r.id}",
            }
            for r in recent
        ],
    }


@router.get("/resumes")
async def list_resumes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
):
    offset = (page - 1) * per_page
    count_q = await db.execute(select(func.count(Resume.id)).where(Resume.user_id == user.id))
    total = count_q.scalar()

    res_q = await db.execute(
        select(Resume).where(Resume.user_id == user.id)
        .order_by(Resume.created_at.desc())
        .offset(offset).limit(per_page)
    )
    resumes = res_q.scalars().all()

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "results": [
            {
                "id":           str(r.id),
                "filename":     r.original_filename,
                "final_score":  r.final_score,
                "scores":       r.scores_json,
                "iterations":   r.iterations,
                "version":      r.version,
                "created_at":   r.created_at.isoformat(),
                "download_url": f"/download/{r.id}",
            }
            for r in resumes
        ],
    }


@router.get("/usage-history")
async def usage_history(
    user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    try:
        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        result = await db.execute(
            select(DailyUsageCounter.date, DailyUsageCounter.runs)
            .where(DailyUsageCounter.user_id == user.id, DailyUsageCounter.date >= cutoff)
            .order_by(DailyUsageCounter.date)
        )
        db_rows = {row.date: row.runs for row in result}

        # Fill every date in the window so the chart has a continuous line
        rows = []
        for i in range(days - 1, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            rows.append({
                "date": d,
                "pipeline_runs": db_rows.get(d, 0),
                "uploads": db_rows.get(d, 0),
            })

        return {"days": days, "rows": rows}
    except Exception:
        logger.exception("usage_history read failed for user=%s", user.id)
        raise HTTPException(status_code=500, detail="Failed to read usage.")


@router.get("/job-matches")
async def job_matches(
    user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=90),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    source: str = Query(None),
    min_score: float = Query(None, ge=0.0, le=1.0),
):
    try:
        # Filters are applied inside the read, BEFORE pagination, so `total`
        # and page boundaries stay correct.
        return await asyncio.to_thread(
            read_job_matches, str(user.id), days, page, per_page, source, min_score
        )
    except Exception:
        logger.exception("job_matches read failed for user=%s", user.id)
        raise HTTPException(status_code=500, detail="Failed to read job matches.")

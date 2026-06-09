"""
Dashboard endpoints — summary, resumes, usage history, job matches.
All require authentication.
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from db.models import PlanLimit, Resume, User, ProviderCost
from db.session import get_db
from delta.writer import read_job_matches, read_usage_last_n_days
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

    from datetime import date
    from db.models import DailyUsageCounter
    today_str = date.today().isoformat()

    # runs_today: use transactional counter — authoritative for quota display
    counter = await db.scalar(
        select(DailyUsageCounter).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    )
    runs_today = counter.runs if counter else 0

    # uploads_today, tokens_today: best-effort from Delta analytics
    try:
        df = await asyncio.to_thread(read_usage_last_n_days, user_id, 1)
        today_df = df[df["date"] == today_str]
        uploads_today = int(today_df["uploads"].sum()) if not today_df.empty else 0
        tokens_today  = int(today_df["tokens_used"].sum()) if not today_df.empty else 0
    except Exception:
        uploads_today = tokens_today = 0

    # Unread job matches from Delta
    try:
        matches = await asyncio.to_thread(read_job_matches, user_id, 30, 1, 1000)
        unread_count = sum(1 for r in matches["results"] if not r.get("is_read"))
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
        df = await asyncio.to_thread(read_usage_last_n_days, str(user.id), days)

        # Fetch active provider costs to calculate cost_cents for each day
        cost_result = await db.execute(
            select(ProviderCost).where(
                (ProviderCost.provider == "anthropic") & (ProviderCost.active == True)
            )
        )
        cost_row = cost_result.scalar_one_or_none()

        # Convert DataFrame to dict and add cost_cents calculation
        rows = df.to_dict(orient="records")
        if cost_row:
            for row in rows:
                input_tokens = int(row.get("input_tokens", 0))
                output_tokens = int(row.get("output_tokens", 0))
                input_cost = (input_tokens / 1_000_000) * cost_row.input_cost_per_1m_tokens
                output_cost = (output_tokens / 1_000_000) * cost_row.output_cost_per_1m_tokens
                row["cost_cents"] = int((input_cost + output_cost) * 100)
        else:
            # If no cost row found, set cost_cents to 0
            for row in rows:
                row["cost_cents"] = 0

        return {"days": days, "rows": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read usage: {str(e)}")


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
        result = await asyncio.to_thread(read_job_matches, str(user.id), days, page, per_page)
        rows = result["results"]
        if source:
            rows = [r for r in rows if r.get("source") == source]
        if min_score is not None:
            rows = [r for r in rows if (r.get("similarity_score") or 0) >= min_score]
        result["results"] = rows
        result["total"]   = len(rows)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read job matches: {str(e)}")


@router.get("/match-analytics")
async def match_analytics(
    user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=90),
):
    """
    Return job match analytics grouped by date.

    Each day includes:
    - match_count: number of job matches that day
    - avg_similarity_score: average similarity score (0.0-1.0)
    - source_breakdown: dict of match counts by source

    Results sorted by date descending (most recent first).
    """
    try:
        user_id = str(user.id)
        # Read all matches for the specified period
        result = await asyncio.to_thread(read_job_matches, user_id, days, 1, 10000)
        matches = result["results"]

        if not matches:
            return {"analytics": []}

        # Group matches by date (from scraped_at)
        from datetime import date
        daily_groups = {}

        for match in matches:
            # Extract date from scraped_at ISO datetime string
            scraped_at_str = match.get("scraped_at", "")
            if scraped_at_str:
                # Parse ISO datetime and extract date portion
                date_str = scraped_at_str[:10]  # YYYY-MM-DD from ISO string
            else:
                continue

            if date_str not in daily_groups:
                daily_groups[date_str] = []
            daily_groups[date_str].append(match)

        # Aggregate metrics for each day
        analytics = []
        for date_str in sorted(daily_groups.keys(), reverse=True):
            day_matches = daily_groups[date_str]
            match_count = len(day_matches)

            # Calculate average similarity score
            scores = [m.get("similarity_score") for m in day_matches if m.get("similarity_score") is not None]
            avg_score = sum(scores) / len(scores) if scores else 0.0

            # Build source breakdown
            source_breakdown = {}
            for match in day_matches:
                source = match.get("source", "unknown")
                source_breakdown[source] = source_breakdown.get(source, 0) + 1

            analytics.append({
                "date": date_str,
                "match_count": match_count,
                "avg_similarity_score": round(avg_score, 2),
                "source_breakdown": source_breakdown,
            })

        return {"analytics": analytics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read match analytics: {str(e)}")

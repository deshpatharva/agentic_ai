"""Admin API routes. All endpoints (except /bootstrap) require get_admin_user."""
import asyncio
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from admin.dependencies import get_admin_user
from admin.schemas import AdminStats, BootstrapRequest, UserUpdate, ProviderCostCreate, ProviderCostsResponse, AnalyticsResponse, PromoCodeCreate
from limiter import limiter
from config import STUCK_JOB_TIMEOUT_MINUTES, BOOTSTRAP_SECRET
from db.models import JobStatus, LlmCallLog, PipelineEvent, PipelineJob, PlanType, Resume, User, ProviderCost
from db.session import get_db
from delta.writer import read_job_matches
from utils.time_utils import ensure_utc

router = APIRouter(prefix="/admin", tags=["admin"])

_VALID_PLANS = {"free", "pro", "enterprise"}


def _user_dict(user: User, resume_count: int) -> dict:
    return {
        "id":               str(user.id),
        "email":            user.email,
        "full_name":        user.full_name or "",
        "plan":             user.plan.value,
        "is_active":        user.is_active,
        "is_admin":         user.is_admin,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "created_at":       user.created_at.isoformat(),
        "resume_count":     resume_count,
    }


async def _user_detail(user: User, db: AsyncSession) -> dict:
    uid = user.id
    total_resumes = (
        await db.execute(select(func.count(Resume.id)).where(Resume.user_id == uid))
    ).scalar() or 0

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    runs_today = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.user_id == uid,
                PipelineJob.created_at >= today_start,
                PipelineJob.status == JobStatus.done,
            )
        )
    ).scalar() or 0

    last_active = (
        await db.execute(
            select(func.max(Resume.created_at)).where(Resume.user_id == uid)
        )
    ).scalar()

    return {
        **_user_dict(user, total_resumes),
        "runs_today":    runs_today,
        "total_resumes": total_resumes,
        "last_active":   last_active.isoformat() if last_active else None,
    }


# ── Bootstrap ─────────────────────────────────────────────────────────────────

@router.post("/bootstrap")
@limiter.limit("3/minute")
async def bootstrap(
    request: Request,
    body: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    """Promote first user to admin. Requires BOOTSTRAP_SECRET env var."""
    if not BOOTSTRAP_SECRET or body.secret != BOOTSTRAP_SECRET:
        raise HTTPException(status_code=403, detail="Invalid bootstrap secret.")

    admin_count = (
        await db.execute(select(func.count(User.id)).where(User.is_admin == True))
    ).scalar()
    if admin_count > 0:
        raise HTTPException(status_code=403, detail="An admin already exists.")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.is_admin = True
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "email": user.email, "is_admin": user.is_admin}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStats)
@limiter.limit("30/minute")
async def get_stats(
    request: Request,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)

    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (
        await db.execute(select(func.count(User.id)).where(User.is_active == True))
    ).scalar() or 0
    total_resumes = (await db.execute(select(func.count(Resume.id)))).scalar() or 0
    pipeline_runs_today = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.created_at >= today_start,
                PipelineJob.status == JobStatus.done,
            )
        )
    ).scalar() or 0
    stuck_jobs = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.status == JobStatus.running,
                PipelineJob.updated_at < stuck_cutoff,
            )
        )
    ).scalar() or 0

    # Calculate costs directly from pipeline_jobs.cost_usd (set by LiteLLM)
    cost_today_usd = (
        await db.execute(
            select(func.coalesce(func.sum(PipelineJob.cost_usd), 0.0)).where(
                PipelineJob.created_at >= today_start,
                PipelineJob.status == JobStatus.done,
            )
        )
    ).scalar() or 0.0

    cost_month_usd = (
        await db.execute(
            select(func.coalesce(func.sum(PipelineJob.cost_usd), 0.0)).where(
                PipelineJob.created_at >= month_start,
                PipelineJob.status == JobStatus.done,
            )
        )
    ).scalar() or 0.0

    pipeline_runs_month = (
        await db.execute(
            select(func.count(PipelineJob.id)).where(
                PipelineJob.created_at >= month_start,
                PipelineJob.status == JobStatus.done,
            )
        )
    ).scalar() or 0

    total_cost_cents_today = int(cost_today_usd * 100)
    total_cost_cents_month = int(cost_month_usd * 100)
    avg_cost_per_run = round(cost_month_usd / pipeline_runs_month, 4) if pipeline_runs_month > 0 else 0.0

    return AdminStats(
        total_users=total_users,
        active_users=active_users,
        total_resumes=total_resumes,
        pipeline_runs_today=pipeline_runs_today,
        stuck_jobs=stuck_jobs,
        total_cost_cents_today=total_cost_cents_today,
        total_cost_cents_month=total_cost_cents_month,
        avg_cost_per_run=round(avg_cost_per_run, 2),
    )


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics", response_model=AnalyticsResponse)
@limiter.limit("10/minute")
async def get_analytics(
    request: Request,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=90),
):
    """Get system-wide analytics with user growth, costs, sources, and pipeline health."""
    today_dt = datetime.now(timezone.utc)
    today = today_dt.date()
    start_date = today - timedelta(days=days - 1)

    # ── 1. User growth: daily signups + cumulative users ────────────────────

    user_growth_data = []
    cumulative_users = 0

    # Query all users created in the range
    start_datetime = datetime.combine(start_date, time.min).replace(tzinfo=timezone.utc)
    users_in_range = (
        await db.execute(
            select(User.created_at)
            .where(User.created_at >= start_datetime)
            .order_by(User.created_at.asc())
        )
    ).scalars().all()

    # Build user counts by date
    daily_signups_by_date = defaultdict(int)
    for user_created_at in users_in_range:
        date_str = user_created_at.date().isoformat()
        daily_signups_by_date[date_str] += 1

    # Get total users before start_date for cumulative calculation
    total_before = (
        await db.execute(
            select(func.count(User.id)).where(
                User.created_at < start_datetime
            )
        )
    ).scalar() or 0

    cumulative_users = total_before
    for current_date in (start_date + timedelta(days=d) for d in range(days)):
        if current_date > today:
            break
        date_str = current_date.isoformat()
        daily_signups = daily_signups_by_date.get(date_str, 0)
        cumulative_users += daily_signups
        user_growth_data.append({
            "date": date_str,
            "cumulative_users": cumulative_users,
            "daily_signups": daily_signups,
        })

    # ── 2. Plan distribution: current counts by plan ─────────────────────────

    plan_rows = (
        await db.execute(
            select(User.plan, func.count(User.id))
            .group_by(User.plan)
        )
    ).all()

    plan_distribution = {
        "free": 0,
        "pro": 0,
        "enterprise": 0,
    }
    for plan_type, count in plan_rows:
        plan_distribution[plan_type.value] = count

    # ── 3. Daily costs: summed from pipeline_jobs.cost_usd ───────────────────

    daily_costs_data = []

    cost_rows = (
        await db.execute(
            select(
                func.date(PipelineJob.created_at).label("job_date"),
                func.coalesce(func.sum(PipelineJob.cost_usd), 0.0).label("daily_cost_usd"),
            )
            .where(
                PipelineJob.created_at >= start_datetime,
                PipelineJob.status == JobStatus.done,
            )
            .group_by(func.date(PipelineJob.created_at))
        )
    ).all()

    daily_costs_by_date = {
        row.job_date.isoformat(): int((row.daily_cost_usd or 0.0) * 100)
        for row in cost_rows
    }

    for current_date in (start_date + timedelta(days=d) for d in range(days)):
        if current_date > today:
            break
        date_str = current_date.isoformat()
        daily_costs_data.append({
            "date": date_str,
            "cost_cents": daily_costs_by_date.get(date_str, 0),
        })

    # ── 4. Source counts: from job matches (placeholder for now) ────────────

    source_counts = {
        "linkedin": 0,
        "indeed": 0,
        "other": 0,
    }

    try:
        # Try to read job_matches from Delta
        matches_df = await asyncio.to_thread(read_job_matches, "", days, 10000)
        if not matches_df.empty and "source" in matches_df.columns:
            source_counts["linkedin"] = int((matches_df["source"] == "linkedin").sum())
            source_counts["indeed"] = int((matches_df["source"] == "indeed").sum())
            source_counts["other"] = int(len(matches_df) - source_counts["linkedin"] - source_counts["indeed"])
    except (ValueError, KeyError, AttributeError):
        # If Delta read fails, use placeholder defaults
        pass

    # ── 5. Pipeline health: successful/failed runs per day ──────────────────

    pipeline_health_data = []

    pipeline_rows = (
        await db.execute(
            select(
                func.date(PipelineJob.created_at).label("job_date"),
                PipelineJob.status,
                func.count(PipelineJob.id),
            )
            .where(
                PipelineJob.created_at >= start_datetime,
                func.date(PipelineJob.created_at).isnot(None),
            )
            .group_by(func.date(PipelineJob.created_at), PipelineJob.status)
            .order_by(func.date(PipelineJob.created_at).desc())
        )
    ).all()

    # Build pipeline counts by date
    pipeline_by_date = defaultdict(lambda: {"successful": 0, "failed": 0})
    for job_date, status, count in pipeline_rows:
        date_str = job_date.isoformat()
        if status == JobStatus.done:
            pipeline_by_date[date_str]["successful"] += count
        elif status == JobStatus.error:
            pipeline_by_date[date_str]["failed"] += count

    # Add data for each day in range
    for current_date in (start_date + timedelta(days=d) for d in range(days)):
        if current_date > today:
            break
        date_str = current_date.isoformat()
        counts = pipeline_by_date.get(date_str, {"successful": 0, "failed": 0})
        pipeline_health_data.append({
            "date": date_str,
            "successful": counts["successful"],
            "failed": counts["failed"],
        })

    # Reverse lists to sort by date ascending (oldest first)
    user_growth_data.reverse()
    daily_costs_data.reverse()
    pipeline_health_data.reverse()

    return AnalyticsResponse(
        user_growth=user_growth_data,
        plan_distribution=plan_distribution,
        daily_costs=daily_costs_data,
        source_counts=source_counts,
        pipeline_health=pipeline_health_data,
    )


# ── User list ─────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
):
    base_filter = []
    if search:
        base_filter.append(func.lower(User.email).like(f"{search.lower()}%"))

    total = (
        await db.execute(select(func.count(User.id)).where(*base_filter))
    ).scalar() or 0

    users = (
        await db.execute(
            select(User)
            .where(*base_filter)
            .order_by(User.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    user_ids = [u.id for u in users]
    counts = {}
    if user_ids:
        rows = (
            await db.execute(
                select(Resume.user_id, func.count(Resume.id))
                .where(Resume.user_id.in_(user_ids))
                .group_by(Resume.user_id)
            )
        ).all()
        counts = {str(row[0]): row[1] for row in rows}

    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "results":  [_user_dict(u, counts.get(str(u.id), 0)) for u in users],
    }


# ── User detail ───────────────────────────────────────────────────────────────

@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found.")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return await _user_detail(user, db)


# ── User update ───────────────────────────────────────────────────────────────

@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found.")

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.plan is not None and body.plan not in _VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"plan must be one of {sorted(_VALID_PLANS)}")
    if body.is_active is False and user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot suspend an admin user.")
    if body.is_active is False and str(user.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="Cannot suspend yourself.")
    if body.is_admin is False:
        raise HTTPException(status_code=400, detail="Admin demotion via API is not allowed.")

    if body.plan is not None:
        user.plan = PlanType(body.plan)
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_admin is True:
        user.is_admin = True

    await db.commit()
    await db.refresh(user)
    return await _user_detail(user, db)


# ── Promo code helpers ────────────────────────────────────────────────────────

def _promo_status(code) -> str:
    if code.deactivated_at:
        return "deactivated"
    # SQLite returns naive datetimes — normalize before comparing
    if code.expires_at and ensure_utc(code.expires_at) <= datetime.now(timezone.utc):
        return "expired"
    return "active"


# ── Promo code create ─────────────────────────────────────────────────────────

@router.post("/promo-codes", status_code=201)
async def create_promo_code(
    body: PromoCodeCreate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a promo code."""
    from db.models import PromoCode

    result = await db.execute(select(PromoCode).where(PromoCode.code == body.code))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Code already exists")

    promo = PromoCode(
        id=uuid.uuid4(),
        code=body.code,
        type=body.type,
        target_plan=body.target_plan,
        days_to_add=body.days_to_add,
        discount_percent=body.discount_percent,
        max_uses=body.max_uses,
        expires_at=body.expires_at,
        created_at=datetime.now(timezone.utc),
    )
    db.add(promo)
    await db.commit()

    return {
        "id": str(promo.id),
        "code": promo.code,
        "type": promo.type,
        "target_plan": promo.target_plan,
        "days_to_add": promo.days_to_add,
        "discount_percent": promo.discount_percent,
        "max_uses": promo.max_uses,
        "current_uses": promo.current_uses,
        "expires_at": promo.expires_at.isoformat() if promo.expires_at else None,
        "created_at": promo.created_at.isoformat(),
        "deactivated_at": None,
    }


# ── Promo code list ───────────────────────────────────────────────────────────

@router.get("/promo-codes")
async def list_promo_codes(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List promo codes with optional filters."""
    from db.models import PromoCode

    query = select(PromoCode)

    if status == "active":
        query = query.where(
            (PromoCode.deactivated_at == None) &  # noqa: E711
            ((PromoCode.expires_at == None) | (PromoCode.expires_at > datetime.now(timezone.utc)))  # noqa: E711
        )
    elif status == "expired":
        query = query.where(
            (PromoCode.deactivated_at == None) &  # noqa: E711
            (PromoCode.expires_at <= datetime.now(timezone.utc))
        )
    elif status == "deactivated":
        query = query.where(PromoCode.deactivated_at != None)  # noqa: E711

    if type:
        query = query.where(PromoCode.type == type)

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0

    result = await db.execute(query.limit(limit).offset(offset))
    codes = result.scalars().all()

    items = []
    for code in codes:
        status_val = _promo_status(code)
        days_until = None
        if code.expires_at:
            delta = (ensure_utc(code.expires_at) - datetime.now(timezone.utc)).days
            days_until = max(0, delta)

        items.append({
            "id": str(code.id),
            "code": code.code,
            "type": code.type,
            "max_uses": code.max_uses,
            "current_uses": code.current_uses,
            "expires_at": code.expires_at.isoformat() if code.expires_at else None,
            "created_at": code.created_at.isoformat(),
            "status": status_val,
            "days_until_expiry": days_until,
        })

    return {"total": total, "codes": items}


# ── Promo code deactivate ─────────────────────────────────────────────────────

@router.patch("/promo-codes/{code_id}")
async def deactivate_promo_code(
    code_id: str,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a promo code."""
    from db.models import PromoCode

    try:
        uid = uuid.UUID(code_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Code not found")

    result = await db.execute(select(PromoCode).where(PromoCode.id == uid))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="Code not found")

    code.deactivated_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "id": str(code.id),
        "code": code.code,
        "deactivated_at": code.deactivated_at.isoformat(),
    }


# ── Promo code stats ──────────────────────────────────────────────────────────

@router.get("/promo-codes/{code_id}/stats")
async def promo_code_stats(
    code_id: str,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get statistics for a promo code."""
    from db.models import PromoCode, UserPromoRedemption, User as UserModel

    try:
        uid = uuid.UUID(code_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Code not found")

    result = await db.execute(select(PromoCode).where(PromoCode.id == uid))
    code = result.scalar_one_or_none()
    if not code:
        raise HTTPException(status_code=404, detail="Code not found")

    # Redemptions by plan
    rows = (
        await db.execute(
            select(UserModel.plan, func.count(UserPromoRedemption.id))
            .join(UserModel, UserModel.id == UserPromoRedemption.user_id)
            .where(UserPromoRedemption.promo_code_id == code.id)
            .group_by(UserModel.plan)
        )
    ).all()
    redeemed_by_plan = {row[0].value: row[1] for row in rows}

    # First / last redemption timestamps
    first_redeemed, last_redeemed = (
        await db.execute(
            select(
                func.min(UserPromoRedemption.redeemed_at),
                func.max(UserPromoRedemption.redeemed_at),
            ).where(UserPromoRedemption.promo_code_id == code.id)
        )
    ).one()

    return {
        "code": code.code,
        "type": code.type,
        "discount_percent": code.discount_percent,
        "max_uses": code.max_uses,
        "current_uses": code.current_uses,
        "remaining_uses": code.max_uses - code.current_uses,
        "redeemed_by_plan": {plan: redeemed_by_plan.get(plan, 0) for plan in ["free", "pro", "enterprise"]},
        "last_redeemed_at": last_redeemed.isoformat() if last_redeemed else None,
        "first_redeemed_at": first_redeemed.isoformat() if first_redeemed else None,
    }


# ── Provider costs ────────────────────────────────────────────────────────────

@router.post("/provider-costs", status_code=201)
async def create_provider_cost(
    body: ProviderCostCreate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update provider pricing. Marks previous active rate as inactive."""
    if body.provider not in ["anthropic", "google", "groq"]:
        raise HTTPException(status_code=400, detail="provider must be one of: anthropic, google, groq")
    if body.input_cost_per_1m_tokens < 0 or body.output_cost_per_1m_tokens < 0:
        raise HTTPException(status_code=400, detail="costs must be non-negative")

    # Mark existing active row as inactive
    result = await db.execute(
        select(ProviderCost).where(
            (ProviderCost.provider == body.provider) & (ProviderCost.active == True)
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.active = False

    # Create new active row
    new_cost = ProviderCost(
        id=uuid.uuid4(),
        provider=body.provider,
        input_cost_per_1m_tokens=body.input_cost_per_1m_tokens,
        output_cost_per_1m_tokens=body.output_cost_per_1m_tokens,
        active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(new_cost)
    await db.commit()
    await db.refresh(new_cost)

    return {
        "id": str(new_cost.id),
        "provider": new_cost.provider,
        "input_cost_per_1m_tokens": new_cost.input_cost_per_1m_tokens,
        "output_cost_per_1m_tokens": new_cost.output_cost_per_1m_tokens,
        "active": new_cost.active,
        "created_at": new_cost.created_at.isoformat(),
        "updated_at": new_cost.updated_at.isoformat(),
    }


@router.get("/provider-costs", response_model=ProviderCostsResponse)
async def list_provider_costs(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all provider pricing rows (active and inactive)."""
    result = await db.execute(
        select(ProviderCost).order_by(ProviderCost.provider, ProviderCost.active.desc(), ProviderCost.created_at.desc())
    )
    costs = result.scalars().all()

    return ProviderCostsResponse(
        providers=[
            {
                "provider": cost.provider,
                "input_cost_per_1m_tokens": cost.input_cost_per_1m_tokens,
                "output_cost_per_1m_tokens": cost.output_cost_per_1m_tokens,
                "active": cost.active,
                "updated_at": cost.updated_at.isoformat(),
            }
            for cost in costs
        ]
    )


# ── Pipeline run observability (read-only, Stage A) ──────────────────────────

@router.get("/pipeline-runs")
@limiter.limit("30/minute")
async def list_pipeline_runs(
    request: Request,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
):
    """Recent pipeline runs with status, score, cost, and timing. Read-only."""
    filters = []
    if status:
        try:
            filters.append(PipelineJob.status == JobStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status '{status}'")

    total = (
        await db.execute(select(func.count(PipelineJob.id)).where(*filters))
    ).scalar() or 0

    rows = (
        await db.execute(
            select(PipelineJob, User.email)
            .join(User, PipelineJob.user_id == User.id, isouter=True)
            .where(*filters)
            .order_by(PipelineJob.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()

    def _final_score(job: PipelineJob):
        scores = job.scores_json or {}
        avg = scores.get("average")
        return round(avg, 1) if isinstance(avg, (int, float)) else None

    return {
        "total": total,
        "results": [
            {
                "id":            str(job.id),
                "user_email":    email,
                "status":        job.status.value,
                "filename":      job.original_filename,
                "final_score":   _final_score(job),
                "iterations":    job.iteration,
                "cost_usd":      round(job.cost_usd, 4) if job.cost_usd else 0.0,
                "tokens":        (job.input_tokens or 0) + (job.output_tokens or 0),
                "error_message": job.error_message,
                "created_at":    job.created_at.isoformat(),
                "duration_s":    max(0, int((job.updated_at - job.created_at).total_seconds()))
                                 if job.status in (JobStatus.done, JobStatus.error) else None,
            }
            for job, email in rows
        ],
    }


@router.get("/pipeline-runs/{job_id}/events")
@limiter.limit("30/minute")
async def get_pipeline_run_events(
    request: Request,
    job_id: uuid.UUID,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Stage-by-stage event timeline for one run (events expire after 24h). Read-only."""
    job = (
        await db.execute(select(PipelineJob).where(PipelineJob.id == job_id))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Run not found")

    events = (
        await db.execute(
            select(PipelineEvent)
            .where(PipelineEvent.job_id == job_id)
            .order_by(PipelineEvent.id.asc())
        )
    ).scalars().all()

    return {
        "job_id": str(job_id),
        "status": job.status.value,
        "events": [
            {"at": ev.created_at.isoformat(), **(ev.event_json or {})}
            for ev in events
        ],
    }


# ── LLM analytics ─────────────────────────────────────────────────────────────

@router.get("/analytics/tokens")
@limiter.limit("10/minute")
async def token_analytics(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily input vs output token split across all models."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(
            func.date(LlmCallLog.created_at).label("day"),
            func.coalesce(func.sum(LlmCallLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCallLog.output_tokens), 0).label("output_tokens"),
        )
        .where(LlmCallLog.created_at >= cutoff)
        .group_by(func.date(LlmCallLog.created_at))
        .order_by(func.date(LlmCallLog.created_at))
    )).all()

    series = [
        {
            "date": str(r.day),
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
        }
        for r in rows
    ]
    return {
        "window_days":          days,
        "total_input_tokens":   sum(r["input_tokens"] for r in series),
        "total_output_tokens":  sum(r["output_tokens"] for r in series),
        "series":               series,
    }


@router.get("/analytics/by-model")
@limiter.limit("10/minute")
async def by_model_analytics(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-model token, cost, and latency matrix."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(
            LlmCallLog.model,
            LlmCallLog.provider,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmCallLog.input_tokens),  0).label("input_tokens"),
            func.coalesce(func.sum(LlmCallLog.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(LlmCallLog.cost_usd),      0.0).label("cost_usd"),
            func.avg(LlmCallLog.latency_ms).label("avg_latency_ms"),
            func.avg(LlmCallLog.ttft_ms).label("avg_ttft_ms"),
        )
        .where(LlmCallLog.created_at >= cutoff)
        .group_by(LlmCallLog.model, LlmCallLog.provider)
        .order_by(func.sum(LlmCallLog.cost_usd).desc())
    )).all()

    return {
        "window_days": days,
        "models": [
            {
                "model":          r.model,
                "provider":       r.provider,
                "calls":          r.calls,
                "input_tokens":   int(r.input_tokens),
                "output_tokens":  int(r.output_tokens),
                "cost_usd":       round(float(r.cost_usd), 6),
                "avg_latency_ms": round(float(r.avg_latency_ms or 0), 1),
                "avg_ttft_ms":    round(float(r.avg_ttft_ms or 0), 1),
            }
            for r in rows
        ],
    }


@router.get("/analytics/cost-audit")
@limiter.limit("10/minute")
async def cost_audit(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Breakdown of cost_source values — reveals how often LiteLLM pricing is missing."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(
            LlmCallLog.cost_source,
            func.count().label("calls"),
            func.coalesce(func.sum(LlmCallLog.cost_usd), 0.0).label("total_cost_usd"),
        )
        .where(LlmCallLog.created_at >= cutoff)
        .group_by(LlmCallLog.cost_source)
    )).all()

    total_calls = sum(r.calls for r in rows)
    return {
        "window_days": days,
        "total_calls": total_calls,
        "by_source": [
            {
                "source":        r.cost_source,
                "calls":         r.calls,
                "pct":           round(100.0 * r.calls / total_calls, 1) if total_calls else 0.0,
                "total_cost_usd": round(float(r.total_cost_usd), 6),
            }
            for r in rows
        ],
    }

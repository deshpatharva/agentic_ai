"""Admin API routes. All endpoints (except /bootstrap) require get_admin_user."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from admin.dependencies import get_admin_user
from admin.schemas import AdminStats, BootstrapRequest, UserUpdate
from config import STUCK_JOB_TIMEOUT_MINUTES
from db.models import JobStatus, PipelineJob, PlanType, Resume, User
from db.session import get_db

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
async def bootstrap(
    body: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    """Promote a user to admin. Self-disables once any admin exists."""
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
async def get_stats(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_TIMEOUT_MINUTES)
    return AdminStats(
        total_users=(await db.execute(select(func.count(User.id)))).scalar() or 0,
        active_users=(
            await db.execute(select(func.count(User.id)).where(User.is_active == True))
        ).scalar() or 0,
        total_resumes=(await db.execute(select(func.count(Resume.id)))).scalar() or 0,
        pipeline_runs_today=(
            await db.execute(
                select(func.count(PipelineJob.id)).where(
                    PipelineJob.created_at >= today_start,
                    PipelineJob.status == JobStatus.done,
                )
            )
        ).scalar() or 0,
        stuck_jobs=(
            await db.execute(
                select(func.count(PipelineJob.id)).where(
                    PipelineJob.status == JobStatus.running,
                    PipelineJob.updated_at < stuck_cutoff,
                )
            )
        ).scalar() or 0,
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
    if code.expires_at and code.expires_at <= datetime.utcnow():
        return "expired"
    return "active"


# ── Promo code create ─────────────────────────────────────────────────────────

@router.post("/promo-codes", status_code=201)
async def create_promo_code(
    body: dict,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a promo code."""
    from db.models import PromoCode

    code_str = body.get("code", "").strip()
    if not code_str or len(code_str) > 50:
        raise HTTPException(status_code=400, detail="Code must be 1-50 chars")
    code_type = body.get("type", "").strip()
    if code_type not in ["plan_upgrade", "trial_extension", "discount"]:
        raise HTTPException(status_code=400, detail="Invalid type")
    max_uses = body.get("max_uses", 0)
    if max_uses < 1:
        raise HTTPException(status_code=400, detail="max_uses must be >= 1")

    result = await db.execute(select(PromoCode).where(PromoCode.code == code_str))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Code already exists")

    expires_at_raw = body.get("expires_at")
    expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None

    promo = PromoCode(
        id=uuid.uuid4(),
        code=code_str,
        type=code_type,
        target_plan=body.get("target_plan"),
        days_to_add=body.get("days_to_add"),
        discount_percent=body.get("discount_percent"),
        max_uses=max_uses,
        expires_at=expires_at,
        created_at=datetime.utcnow(),
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
            ((PromoCode.expires_at == None) | (PromoCode.expires_at > datetime.utcnow()))  # noqa: E711
        )
    elif status == "expired":
        query = query.where(
            (PromoCode.deactivated_at == None) &  # noqa: E711
            (PromoCode.expires_at <= datetime.utcnow())
        )
    elif status == "deactivated":
        query = query.where(PromoCode.deactivated_at != None)  # noqa: E711

    if type:
        query = query.where(PromoCode.type == type)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    codes = result.scalars().all()

    items = []
    for code in codes:
        status_val = _promo_status(code)
        days_until = None
        if code.expires_at:
            delta = (code.expires_at - datetime.utcnow()).days
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

    return {"total": len(items), "codes": items}


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

    code.deactivated_at = datetime.utcnow()
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

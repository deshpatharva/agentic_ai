"""
Auth endpoints — register, login, me.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt

# passlib 1.7.4 looks for bcrypt.__about__.__version__ which bcrypt 4.x removed
import bcrypt as _bcrypt
if not hasattr(_bcrypt, "__about__"):
    class _About:
        __version__ = _bcrypt.__version__
    _bcrypt.__about__ = _About()

from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET, RATE_LIMIT_AUTH, TRIAL_DAYS
from limiter import limiter
from db.models import PlanLimit, PlanType, PromoCode, User, UserPromoRedemption
from db.session import get_db
from auth.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])
user_router = APIRouter(prefix="/user", tags=["user"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Request / response schemas ────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""


class UpdateProfileRequest(BaseModel):
    full_name: str = ""
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode({"sub": user_id, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _user_dict(user: User, limits: PlanLimit = None) -> dict:
    d = {
        "id":          str(user.id),
        "email":       user.email,
        "full_name":   user.full_name or "",
        "plan":        user.plan.value,
        "is_active":   user.is_active,
        "is_admin":         user.is_admin,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "created_at":       user.created_at.isoformat(),
    }
    if limits:
        d["limits"] = {
            "daily_uploads":        limits.daily_uploads,
            "max_stored_resumes":   limits.max_stored_resumes,
            "job_scraping_enabled": limits.job_scraping_enabled,
            "price_cents":          limits.price_cents,
        }
    return d


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered.")

    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    user = User(
        email=body.email,
        password_hash=pwd_context.hash(body.password),
        full_name=body.full_name,
        trial_expires_at=datetime.utcnow() + timedelta(days=TRIAL_DAYS),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = _make_token(str(user.id))
    return TokenResponse(access_token=token, user=_user_dict(user))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    result2 = await db.execute(select(PlanLimit).where(PlanLimit.plan == user.plan.value))
    limits = result2.scalar_one_or_none()

    token = _make_token(str(user.id))
    return TokenResponse(access_token=token, user=_user_dict(user, limits))


@router.get("/me")
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == user.plan.value))
    limits = result.scalar_one_or_none()
    return _user_dict(user, limits)


@router.put("/me")
async def update_profile(
    request: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if request.email != user.email:
        existing = await db.execute(select(User).where(User.email == request.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already in use.")

    user.full_name = request.full_name
    user.email = request.email
    await db.commit()
    await db.refresh(user)

    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == user.plan.value))
    limits = result.scalar_one_or_none()
    return _user_dict(user, limits)


# ── User routes ────────────────────────────────────────────────────────────────

@user_router.post("/redeem-promo-code")
async def redeem_promo_code(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a promo code."""
    code_str = body.get("code", "").strip()
    if not code_str:
        raise HTTPException(status_code=400, detail="Code is required")

    # Fetch code
    result = await db.execute(
        select(PromoCode).where(PromoCode.code == code_str)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=400, detail="Invalid code")

    # Check validity
    if promo.deactivated_at:
        raise HTTPException(status_code=409, detail="Code deactivated")
    if promo.expires_at and promo.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=409, detail="Code expired")
    if promo.current_uses >= promo.max_uses:
        raise HTTPException(status_code=409, detail="Code exhausted")

    # Check already redeemed
    result = await db.execute(
        select(UserPromoRedemption).where(
            (UserPromoRedemption.user_id == user.id) &
            (UserPromoRedemption.promo_code_id == promo.id)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already redeemed")

    # Apply effect
    message = ""
    if promo.type == "plan_upgrade":
        user.plan = PlanType(promo.target_plan)
        user.trial_expires_at = None
        message = f"{promo.target_plan.capitalize()} plan activated!"
    elif promo.type == "trial_extension":
        if not user.trial_expires_at or user.trial_expires_at <= datetime.utcnow():
            raise HTTPException(status_code=400, detail="No active trial to extend")
        user.trial_expires_at = user.trial_expires_at + timedelta(days=promo.days_to_add)
        message = f"Trial extended {promo.days_to_add} days"
    elif promo.type == "discount":
        # For now, just record it; discount handling deferred to Stripe phase
        message = "Discount applied"

    # Record redemption
    redemption = UserPromoRedemption(user_id=user.id, promo_code_id=promo.id)
    db.add(redemption)

    # Increment counter
    promo.current_uses += 1

    await db.commit()

    return {
        "message": message,
        "effect": promo.type,
        "user": _user_dict(user),
    }

"""
Auth endpoints — register, login, me.
"""

import re as _re
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET, RATE_LIMIT_AUTH, TRIAL_DAYS
from limiter import limiter
from db.models import PlanLimit, PlanType, PromoCode, User, UserPromoRedemption, TokenBlocklist
from utils.time_utils import ensure_utc
from db.session import get_db
from auth.dependencies import get_current_user, oauth2_scheme

router = APIRouter(prefix="/auth", tags=["auth"])
user_router = APIRouter(prefix="/user", tags=["user"])


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if len(password) > 128:
        raise HTTPException(status_code=400, detail="Password too long (max 128 characters).")
    if not any(c.isupper() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one digit.")
    if password != password.strip():
        raise HTTPException(status_code=400, detail="Password cannot start or end with whitespace.")


def _sanitize_full_name(name: str) -> str:
    name = name.strip()
    if not name:
        return name
    if len(name) > 255:
        raise HTTPException(status_code=400, detail="Name too long (max 255 characters).")
    if not _re.match(r"^[\w\s\-'.]+$", name, _re.UNICODE):
        raise HTTPException(status_code=400, detail="Name contains invalid characters.")
    return name


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


class RedeemPromoRequest(BaseModel):
    code: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_token(user_id: str) -> str:
    import uuid as _uuid_lib
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "jti": str(_uuid_lib.uuid4())},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


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

    _validate_password(body.password)
    body.full_name = _sanitize_full_name(body.full_name)

    user = User(
        email=body.email,
        password_hash=_hash_password(body.password),
        full_name=body.full_name,
        trial_expires_at=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
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

    if not user or not _verify_password(body.password, user.password_hash):
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
    request.full_name = _sanitize_full_name(request.full_name)

    if request.email != user.email:
        existing = await db.execute(select(User).where(User.email == request.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already in use.")

    user.full_name = request.full_name
    user.email = request.email
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Email already in use.")

    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == user.plan.value))
    limits = result.scalar_one_or_none()
    return _user_dict(user, limits)


@router.post("/logout")
async def logout(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current JWT by adding it to the blocklist."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        jti = payload.get("jti")
        if jti:
            expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            db.add(TokenBlocklist(jti=jti, expires_at=expires_at))
            try:
                await db.commit()
            except Exception:
                await db.rollback()
    except Exception:
        pass
    return {"detail": "Logged out"}


# ── User routes ────────────────────────────────────────────────────────────────

def _mint_sse_token(user_id: str) -> str:
    """Mint a 60-second SSE-only JWT for the given user_id string.

    Extracted so chat/handoff.py can issue SSE tokens without going through HTTP.
    """
    import time
    payload = {
        "sub": user_id,
        "sse": True,
        "exp": int(time.time()) + 60,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@user_router.post("/sse-token")
async def get_sse_token(current_user: User = Depends(get_current_user)):
    """Issue a 60-second token valid only for SSE connections.

    EventSource cannot send Authorization headers, so tokens must go in the URL.
    Using the 7-day session token in a URL leaks it into server logs and browser history.
    This endpoint issues a short-lived, SSE-only token that expires before it can be abused.
    """
    return {"sse_token": _mint_sse_token(str(current_user.id))}


@user_router.post("/redeem-promo-code")
async def redeem_promo_code(
    body: RedeemPromoRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a promo code."""
    code_str = body.code.strip()
    if not code_str:
        raise HTTPException(status_code=400, detail="Code is required")

    # Fetch code
    result = await db.execute(
        select(PromoCode).where(PromoCode.code == code_str)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=400, detail="Invalid code")

    # Check validity (SQLite returns naive datetimes — normalize before comparing)
    if promo.deactivated_at:
        raise HTTPException(status_code=409, detail="Code deactivated")
    if promo.expires_at and ensure_utc(promo.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Code expired")

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
        trial_end = ensure_utc(user.trial_expires_at)
        if not trial_end or trial_end <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="No active trial to extend")
        user.trial_expires_at = trial_end + timedelta(days=promo.days_to_add)
        message = f"Trial extended {promo.days_to_add} days"
    elif promo.type == "discount":
        message = "Discount code recorded — your discount will apply at your next billing cycle when Stripe billing is enabled."

    # Atomic increment — only succeeds if current_uses < max_uses (prevents double-redemption race)
    result_inc = await db.execute(
        update(PromoCode)
        .where(PromoCode.id == promo.id, PromoCode.current_uses < PromoCode.max_uses)
        .values(current_uses=PromoCode.current_uses + 1)
    )
    await db.flush()
    if result_inc.rowcount == 0:
        raise HTTPException(status_code=409, detail="Code exhausted")

    # Record redemption
    redemption = UserPromoRedemption(user_id=user.id, promo_code_id=promo.id)
    db.add(redemption)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Already redeemed")

    return {
        "message": message,
        "effect": promo.type,
        "user": _user_dict(user),
    }

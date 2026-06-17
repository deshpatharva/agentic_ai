"""
Auth dependencies — JWT decoding, user fetching, plan limit checking.
"""

import uuid as _uuid_module
from datetime import date, datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import JWT_ALGORITHM, JWT_SECRET
from db.models import DailyUsageCounter, PlanLimit, User, TokenBlocklist
from db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def decode_token(token: str) -> str:
    """Decode a JWT and return the user_id (sub claim). Raises HTTP 401 on failure.

    Used by endpoints that cannot use the Authorization header (e.g. SSE via EventSource).
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def decode_sse_token(token: str) -> str:
    """Decode a short-lived SSE token and return user_id. Raises HTTP 401 on failure.

    SSE tokens must have the 'sse': True claim — rejects regular session tokens
    to prevent the 7-day token from being used in URLs (where it appears in logs).
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if not payload.get("sse"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token for SSE — use POST /auth/sse-token",
            )
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
        jti: str = payload.get("jti")
    except JWTError:
        raise credentials_exc

    if jti:
        blocked = await db.scalar(
            select(TokenBlocklist).where(TokenBlocklist.jti == jti)
        )
        if blocked:
            raise credentials_exc

    try:
        user_uuid = _uuid_module.UUID(user_id)
    except (ValueError, AttributeError):
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == user_uuid, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exc
    return user


def _effective_plan(user: User) -> str:
    """Return the user's effective plan, honouring an active free trial."""
    trial_exp = user.trial_expires_at
    if trial_exp and trial_exp.tzinfo is None:
        trial_exp = trial_exp.replace(tzinfo=timezone.utc)
    if trial_exp and trial_exp > datetime.now(timezone.utc):
        return "pro"
    return user.plan.value


async def check_plan_limit(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Raise HTTP 429 if the user has already hit their daily pipeline-run limit.
    Only CHECKS — does NOT increment. The counter is incremented only when a
    pipeline run completes successfully (in _run_pipeline_task in main.py).
    This ensures failed runs never consume quota.
    """
    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == _effective_plan(user)))
    limits = result.scalar_one_or_none()
    if not limits:
        return user

    today_str = date.today().isoformat()
    counter_result = await db.execute(
        select(DailyUsageCounter.runs).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    )
    used = counter_result.scalar() or 0

    if used >= limits.daily_uploads:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "limit_reached",
                "limit": limits.daily_uploads,
                "used": used,
                "plan": user.plan.value,
                "upgrade_message": "Upgrade to Pro for 20 uploads/day",
            },
        )
    return user

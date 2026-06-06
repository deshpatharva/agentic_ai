"""
Auth dependencies — JWT decoding, user fetching, plan limit checking.
"""

import uuid as _uuid_module
from datetime import date, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import JWT_ALGORITHM, JWT_SECRET
from db.models import DailyUsageCounter, PlanLimit, User
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
    except JWTError:
        raise credentials_exc

    try:
        user_uuid = _uuid_module.UUID(user_id)
    except (ValueError, AttributeError):
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == user_uuid, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exc
    return user


def _effective_plan(user: User) -> str:
    """Return the user's effective plan, honouring an active free trial.

    trial_expires_at is stored as naive UTC (DateTime column). Compare
    against datetime.utcnow() — also naive UTC — to avoid TypeError.
    """
    if user.trial_expires_at and user.trial_expires_at > datetime.utcnow():
        return "pro"
    return user.plan.value


async def check_plan_limit(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Raise HTTP 429 if user has hit their daily upload limit.
    Uses PostgreSQL DailyUsageCounter — transactional, accurate under concurrent load.
    Delta Lake reads are too slow (200-2000ms) and writes are fire-and-forget,
    allowing free users to bypass limits with concurrent requests.
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

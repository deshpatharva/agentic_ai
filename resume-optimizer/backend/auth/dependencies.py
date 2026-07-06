"""
Auth dependencies — JWT decoding, user fetching, plan limit checking.
"""

import uuid as _uuid_module
from datetime import date, datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import JWT_ALGORITHM, JWT_SECRET
from db.models import DailyUsageCounter, PlanLimit, User, TokenBlocklist
from db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def decode_token_checked(token: str, db: AsyncSession) -> str:
    """Decode a session JWT AND verify it has not been revoked (logout blocklist).

    Used by query-param auth paths (downloads) where the token travels in the URL
    and is therefore the most likely to leak into logs/history — so honouring the
    logout blocklist here matters most. Raises HTTP 401 on invalid or revoked tokens.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    jti: str = payload.get("jti")
    if jti:
        blocked = await db.scalar(select(TokenBlocklist).where(TokenBlocklist.jti == jti))
        if blocked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user_id


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


async def reserve_run_quota(user: User, db: AsyncSession) -> bool:
    """Atomically reserve one pipeline run against the user's daily limit.

    Returns True if a slot was reserved (the counter was incremented), False if the
    user is already at their limit. Reserving up-front — rather than incrementing
    only after a run finishes — closes the race where many concurrent submissions
    each pass a read-only check at used=0 and every one burns real LLM spend.
    Failed runs are returned to the pool via refund_run_quota, so the
    "failures never consume quota" guarantee still holds.

    Uses the stored UUID hex form (no dashes) so the ON CONFLICT target matches the
    row SQLAlchemy writes — a dashed string silently creates a phantom row on SQLite.
    """
    limits = await db.scalar(select(PlanLimit).where(PlanLimit.plan == _effective_plan(user)))
    uid_hex = _uuid_module.UUID(str(user.id)).hex
    today_str = date.today().isoformat()

    if limits is None:
        # No configured limit — count the run for analytics but never reject.
        await db.execute(
            text(
                "INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
                "VALUES (:uid, :date, 1, 0) "
                "ON CONFLICT (user_id, date) DO UPDATE "
                "SET runs = daily_usage_counters.runs + 1"
            ),
            {"uid": uid_hex, "date": today_str},
        )
        await db.commit()
        return True

    if limits.daily_uploads <= 0:
        return False

    # The WHERE guards the DO UPDATE branch; the first insert of the day (no
    # conflict) is unconditional but safe because daily_uploads >= 1 here.
    result = await db.execute(
        text(
            "INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
            "VALUES (:uid, :date, 1, 0) "
            "ON CONFLICT (user_id, date) DO UPDATE "
            "SET runs = daily_usage_counters.runs + 1 "
            "WHERE daily_usage_counters.runs < :limit"
        ),
        {"uid": uid_hex, "date": today_str, "limit": limits.daily_uploads},
    )
    await db.commit()
    return result.rowcount == 1


def _counter_date_for(dt) -> str:
    """Local calendar date of a timestamp, on the same basis reserve uses
    (date.today()). Used to refund the day a run was *reserved*, not the day the
    refund happens — otherwise a run failing/reaped across midnight decrements the
    wrong row."""
    if dt is None:
        return date.today().isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date().isoformat()


async def refund_run_quota(user_id, db: AsyncSession, run_date: str | None = None) -> None:
    """Return one reserved run to the pool (used when a run fails), flooring at 0.

    run_date defaults to today; callers that know the reservation date (the
    pipeline task, the reaper) pass it so a cross-midnight refund hits the row the
    reservation incremented.
    """
    uid_hex = _uuid_module.UUID(str(user_id)).hex
    date_str = run_date or date.today().isoformat()
    await db.execute(
        text(
            "UPDATE daily_usage_counters SET runs = runs - 1 "
            "WHERE user_id = :uid AND date = :date AND runs > 0"
        ),
        {"uid": uid_hex, "date": date_str},
    )
    await db.commit()


async def reserve_edit_quota(user: User, db: AsyncSession) -> bool:
    """Atomically reserve one edit against the user's daily edit limit.

    Mirrors reserve_run_quota — reserving up-front closes the same read-then-act
    race where concurrent edits all pass a used<limit check and each burns an LLM
    call. Failed edits are returned via refund_edit_quota.
    """
    limits = await db.scalar(select(PlanLimit).where(PlanLimit.plan == _effective_plan(user)))
    uid_hex = _uuid_module.UUID(str(user.id)).hex
    today_str = date.today().isoformat()

    if limits is None:
        await db.execute(
            text(
                "INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
                "VALUES (:uid, :date, 0, 1) "
                "ON CONFLICT (user_id, date) DO UPDATE "
                "SET edits = daily_usage_counters.edits + 1"
            ),
            {"uid": uid_hex, "date": today_str},
        )
        await db.commit()
        return True

    if limits.daily_edits <= 0:
        return False

    result = await db.execute(
        text(
            "INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
            "VALUES (:uid, :date, 0, 1) "
            "ON CONFLICT (user_id, date) DO UPDATE "
            "SET edits = daily_usage_counters.edits + 1 "
            "WHERE daily_usage_counters.edits < :limit"
        ),
        {"uid": uid_hex, "date": today_str, "limit": limits.daily_edits},
    )
    await db.commit()
    return result.rowcount == 1


async def refund_edit_quota(user_id, db: AsyncSession, run_date: str | None = None) -> None:
    """Return one reserved edit to the pool (used when an edit fails), flooring at 0."""
    uid_hex = _uuid_module.UUID(str(user_id)).hex
    date_str = run_date or date.today().isoformat()
    await db.execute(
        text(
            "UPDATE daily_usage_counters SET edits = edits - 1 "
            "WHERE user_id = :uid AND date = :date AND edits > 0"
        ),
        {"uid": uid_hex, "date": date_str},
    )
    await db.commit()

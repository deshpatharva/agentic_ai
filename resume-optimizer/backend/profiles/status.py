"""Profile completeness check shared by /auth/me and the chat guardrail."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Profile, User


async def compute_profile_status(user: User, db: AsyncSession) -> str:
    """Return 'complete' if the user owns at least one profile with experience or summary."""
    profs = (
        await db.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalars().all()

    for p in profs:
        s = p.sections or {}
        exp = s.get("experience") or []
        if (isinstance(exp, list) and len(exp) > 0) or (s.get("summary") or "").strip():
            return "complete"

    return "incomplete"

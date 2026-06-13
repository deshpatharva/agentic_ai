"""FastAPI dependency that resolves or creates a ChatSession for the current user."""

import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from db.models import ChatSession, User
from db.session import get_db


async def get_or_create_session(
    session_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSession:
    """Resolve the conversation thread for this turn, scoped to the authenticated user.

    - session_id present & owned by this user -> resume it
    - session_id present & owned by another  -> 404 (never leak another user's thread)
    - session_id absent / unparseable         -> create a fresh thread
    """
    if session_id:
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            sid = None
        if sid:
            sess = await db.scalar(select(ChatSession).where(ChatSession.id == sid))
            if sess and str(sess.user_id) == str(current_user.id):
                return sess
            if sess:
                raise HTTPException(status_code=404, detail="Session not found.")

    now = datetime.now(timezone.utc)
    sess = ChatSession(user_id=current_user.id, context={}, created_at=now, updated_at=now)
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess

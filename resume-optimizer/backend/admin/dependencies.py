from fastapi import Depends, HTTPException
from db.models import User
from auth.dependencies import get_current_user


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """Dependency that enforces admin access. Returns 403 for non-admins, 401 for unauthenticated."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request


def get_user_id_key(request: Request) -> str:
    """Per-user rate limit key for authenticated endpoints.

    Falls back to IP if user is not authenticated (should not happen on
    protected endpoints, but prevents KeyError).
    Trust X-Forwarded-For for accurate IP behind Azure load balancer.
    """
    # Try to get user from request state (set by auth dependency)
    user = getattr(request.state, "user", None)
    if user is not None:
        return f"user:{getattr(user, 'id', str(user))}"
    # Fall back to real IP (respecting X-Forwarded-For)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


# IP-based limiter for auth endpoints (login, register)
# key_func=get_remote_address is the default for all routes unless overridden per-route
limiter = Limiter(key_func=get_remote_address)

# Per-user limiter for pipeline endpoints
# Use as @pipeline_limiter.limit(...) on /run-pipeline so that the
# app.state.limiter (ip-based) handles auth routes while pipeline routes
# get their own per-user limiter instance registered separately.
pipeline_limiter = Limiter(key_func=get_user_id_key)

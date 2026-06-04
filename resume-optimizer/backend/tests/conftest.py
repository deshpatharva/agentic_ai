import sys
from pathlib import Path

import pytest_asyncio

# Makes backend/ importable as root when pytest runs from resume-optimizer/
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest_asyncio.fixture(autouse=True)
async def reset_rate_limits(request):
    """Reset in-memory rate-limit counters before every test.

    Prevents counts from one test bleeding into another — especially important
    for test_admin.py which calls /auth/register and /auth/login in fixtures.

    Skips for litellm tests and pipeline tests which don't need the app.
    """
    # Skip for tests that don't need the app
    if "litellm" in request.node.fspath.strpath or "pipeline" in request.node.fspath.strpath or "loop_controller" in request.node.fspath.strpath:
        yield
        return

    from main import app
    if hasattr(app.state, "limiter") and hasattr(app.state.limiter, "_storage"):
        app.state.limiter._storage.reset()
    yield

import os
import sys
from pathlib import Path

import pytest_asyncio

# Makes backend/ importable as root when pytest runs from resume-optimizer/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Required secrets — set defaults so tests don't fail on import of config.py
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-must-be-32-chars-min!!")


@pytest_asyncio.fixture(autouse=True)
async def reset_rate_limits():
    """Reset in-memory rate-limit counters before every test.

    Prevents counts from one test bleeding into another — especially important
    for test_admin.py which calls /auth/register and /auth/login in fixtures.
    Silently skips if the app cannot be imported (e.g. missing optional deps).
    """
    try:
        from main import app
        if hasattr(app.state, "limiter") and hasattr(app.state.limiter, "_storage"):
            app.state.limiter._storage.reset()
    except ImportError:
        pass
    yield

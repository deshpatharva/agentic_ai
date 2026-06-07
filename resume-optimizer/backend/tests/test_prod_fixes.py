"""Tests for production readiness fixes (P0 + High severity)."""
import sys
import os
import inspect
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_prod_fixes.db")
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-xyz")

from main import app
from db.models import Base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

_engine = create_async_engine("sqlite+aiosqlite:///./test_prod_fixes.db")


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    try:
        os.remove("./test_prod_fixes.db")
    except Exception:
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client):
    await client.post("/auth/register", json={
        "email": "fix@test.com", "password": "Test1234!", "full_name": "Fix User"
    })
    resp = await client.post("/auth/login", json={"email": "fix@test.com", "password": "Test1234!"})
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ── Task 1: Input validation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_jobs_rejects_oversized_per_source(auth_client):
    """per_source > 50 must return HTTP 422."""
    r = await auth_client.post("/scrape-jobs", json={
        "resume_id": "00000000-0000-0000-0000-000000000001",
        "keywords": "engineer",
        "per_source": 99999,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scrape_jobs_accepts_valid_per_source(auth_client):
    """per_source=50 must not be rejected by validation."""
    r = await auth_client.post("/scrape-jobs", json={
        "resume_id": "00000000-0000-0000-0000-000000000001",
        "keywords": "engineer",
        "per_source": 50,
    })
    assert r.status_code != 422


@pytest.mark.asyncio
async def test_register_rejects_password_over_128_chars(client):
    """Passwords longer than 128 chars must return HTTP 400."""
    r = await client.post("/auth/register", json={
        "email": "longpass@test.com",
        "password": "A" * 129,
        "full_name": "Test",
    })
    assert r.status_code == 400
    assert "too long" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_analyze_jd_rejects_oversized_body(auth_client):
    """jd_text longer than MAX_JD_CHARS must return HTTP 422."""
    r = await auth_client.post("/analyze-jd", json={"jd_text": "x" * 100_001})
    assert r.status_code == 422


# ── Task 2: Global cache ──────────────────────────────────────────────────────

def test_result_cache_clear_not_in_pipeline():
    """result_cache.clear() must not be called inside _run_pipeline_task."""
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert "result_cache.clear()" not in source, (
        "result_cache.clear() found in _run_pipeline_task — wipes cached data for ALL concurrent jobs."
    )


# ── Task 3: Bootstrap security ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_requires_secret(client):
    """Bootstrap without the correct secret must return 403."""
    r = await client.post("/admin/bootstrap", json={"email": "admin@test.com", "secret": "wrong"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_bootstrap_without_secret_field_returns_422(client):
    """Bootstrap with no secret field must return 422."""
    r = await client.post("/admin/bootstrap", json={"email": "admin@test.com"})
    assert r.status_code == 422


# ── Task 4: Fire-and-forget ───────────────────────────────────────────────────

def test_scrape_jobs_uses_background_tasks_not_create_task():
    """Persistence must use BackgroundTasks, not asyncio.create_task."""
    from main import scrape_jobs_endpoint
    source = inspect.getsource(scrape_jobs_endpoint)
    assert "asyncio.create_task" not in source, (
        "asyncio.create_task found in scrape_jobs_endpoint — use BackgroundTasks instead."
    )


# ── Task 5: Silent Resume save ────────────────────────────────────────────────

def test_resume_save_failure_is_not_silently_swallowed():
    """Resume save failures must be logged, not silently ignored."""
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert "except Exception:\n                    pass" not in source, (
        "Silent 'except Exception: pass' found in Resume save block — must log the failure."
    )


# ── Task 6: Promo code atomic ─────────────────────────────────────────────────

def test_promo_increment_is_atomic():
    """current_uses increment must use UPDATE WHERE current_uses < max_uses."""
    from auth.router import redeem_promo_code
    source = inspect.getsource(redeem_promo_code)
    assert "current_uses < " in source, (
        "Promo increment is not atomic — use UPDATE WHERE current_uses < max_uses."
    )


# ── Task 7: Email update race ─────────────────────────────────────────────────

def test_email_update_conflict_returns_400_not_500():
    """update_profile must catch IntegrityError and return HTTP 400."""
    from auth.router import update_profile
    source = inspect.getsource(update_profile)
    assert "IntegrityError" in source, (
        "update_profile must catch IntegrityError — without this, email conflicts return HTTP 500."
    )


# ── Task 8: Cost tracking provider ───────────────────────────────────────────

def test_cost_tracking_queries_google_not_anthropic():
    """Cost tracking must query Google provider — all models are Gemini/Groq."""
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    # Should not hardcode anthropic in the cost query section
    assert '== "anthropic"' not in source or "Google" in source, (
        "Cost tracking hardcoded to 'anthropic' — all models are Gemini/Groq, cost will be 0."
    )


# ── Task 9: Env var casing ────────────────────────────────────────────────────

def test_env_var_names_are_screaming_snake_case():
    """All API key env vars must use SCREAMING_SNAKE_CASE."""
    import config as cfg_module
    source = inspect.getsource(cfg_module)
    assert 'os.environ.get("google_ai_studio_api_key"' not in source, \
        "google_ai_studio_api_key should be GOOGLE_AI_STUDIO_API_KEY"
    assert 'os.environ.get("groq_api_key"' not in source, \
        "groq_api_key should be GROQ_API_KEY"


# ── Task 10: Connection pool ──────────────────────────────────────────────────

def test_db_engine_has_custom_pool_config():
    """Engine must be created with explicit pool_size and max_overflow."""
    from db import session as db_session
    source = inspect.getsource(db_session)
    assert "pool_size=" in source, "db/session.py must set pool_size explicitly"
    assert "max_overflow=" in source, "db/session.py must set max_overflow explicitly"


# ── Task 11: DB scope ─────────────────────────────────────────────────────────

def test_pipeline_does_not_hold_single_db_session_for_llm_calls():
    """_run_pipeline_task must not wrap LLM calls in a single long-lived DB session."""
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    lines = source.split('\n')
    # Count top-level (4-space indent inside async def) AsyncSessionLocal opens
    top_level = sum(
        1 for line in lines
        if 'async with AsyncSessionLocal() as db:' in line
        and line.startswith('    async with')  # exactly one level of indent inside the function
        and not line.strip().startswith('#')
    )
    assert top_level == 0, (
        f"Found {top_level} top-level AsyncSessionLocal contexts — "
        "use per-operation sessions so LLM calls don't hold DB connections."
    )


# ── Task 13: Rate limiting ────────────────────────────────────────────────────

def test_rate_limit_uses_postgres_not_delta():
    """check_plan_limit must query PostgreSQL DailyUsageCounter, not Delta Lake."""
    from auth import dependencies
    source = inspect.getsource(dependencies)
    assert "read_usage_last_n_days" not in source, (
        "check_plan_limit still uses Delta Lake — replace with DailyUsageCounter."
    )
    assert "DailyUsageCounter" in source, (
        "check_plan_limit must query DailyUsageCounter."
    )


# ── Task 14: Discount message ─────────────────────────────────────────────────

def test_discount_promo_returns_pending_message_not_applied():
    """Discount promo must not claim 'Discount applied' — nothing is actually applied."""
    from auth.router import redeem_promo_code
    source = inspect.getsource(redeem_promo_code)
    assert '"Discount applied"' not in source, (
        "Discount promo returns 'Discount applied' but no discount is applied."
    )

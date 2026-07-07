"""Admin AI-observability endpoints: health grading, series bucketing."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_obs.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, LlmCallLog, User, PlanType
from db.session import get_db
from main import app

TEST_DB_URL = "sqlite+aiosqlite:///./test_obs.db"
_engine = create_async_engine(TEST_DB_URL, echo=False)
_TestSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    app.dependency_overrides[get_db] = _override_get_db
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    app.dependency_overrides.pop(get_db, None)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    try:
        os.remove("./test_obs.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def admin_client():
    from admin.dependencies import get_admin_user  # noqa: PLC0415 — same module the router depends on
    admin = User(id=uuid.uuid4(), email="obs-admin@test.com", password_hash="x",
                 plan=PlanType.free, is_admin=True)

    async def _admin():
        return admin

    app.dependency_overrides[get_admin_user] = _admin
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_admin_user, None)


def _row(status="ok", latency=100, cost=0.001, age_hours=1, model="groq/m", **kw):
    return LlmCallLog(
        model=model, provider=model.split("/")[0], status=status,
        error_type=("FakeError" if status == "error" else None),
        input_tokens=10, output_tokens=5, cost_usd=cost, cost_source="zero",
        latency_ms=latency,
        created_at=datetime.now(timezone.utc) - timedelta(hours=age_hours), **kw)


async def _seed(rows):
    async with _TestSession() as db:
        for r in rows:
            db.add(r)
        await db.commit()


async def test_health_empty_window_is_ok(admin_client):
    r = await admin_client.get("/admin/observability/health")
    assert r.status_code == 200
    body = r.json()
    assert body["signals"]["error_rate"]["status"] == "ok"
    assert body["counts"]["calls_24h"] == 0


async def test_health_grades_error_rate_crit(admin_client):
    await _seed([_row() for _ in range(45)] + [_row(status="error") for _ in range(5)])
    r = await admin_client.get("/admin/observability/health")
    body = r.json()
    assert body["counts"]["calls_24h"] == 50
    assert body["counts"]["errors_24h"] == 5
    assert body["signals"]["error_rate"]["status"] == "crit"  # 10% >= 5%


async def test_series_daily_buckets(admin_client):
    await _seed([_row(age_hours=30), _row(age_hours=30, status="error")])
    r = await admin_client.get("/admin/observability/series", params={"days": 7})
    body = r.json()
    assert body["bucket"] == "day"
    assert body["capped"] is False
    total_calls = sum(b["calls"] for b in body["series"])
    total_errors = sum(b["errors"] for b in body["series"])
    assert total_calls >= 2 and total_errors >= 1


async def test_series_hourly_when_short_window(admin_client):
    r = await admin_client.get("/admin/observability/series", params={"days": 1})
    assert r.json()["bucket"] == "hour"


def test_percentiles_nearest_rank():
    from admin.observability import _percentiles
    assert _percentiles([])[95] is None
    assert _percentiles([100])[50] == 100.0
    p = _percentiles(list(range(1, 101)))
    assert p[50] == 50.0 and p[95] == 95.0 and p[99] == 99.0


def test_grade_boundaries():
    from admin.observability import _grade
    assert _grade(0.019, 0.02, 0.05) == "ok"
    assert _grade(0.02, 0.02, 0.05) == "warn"
    assert _grade(0.05, 0.02, 0.05) == "crit"
    assert _grade(None, 0.02, 0.05) == "ok"


async def test_latency_percentiles_per_model(admin_client):
    await _seed([_row(model="groq/fast", latency=100) for _ in range(9)]
                + [_row(model="groq/fast", latency=1000)])
    r = await admin_client.get("/admin/observability/latency", params={"days": 7})
    body = r.json()
    fast = next(m for m in body["models"] if m["model"] == "groq/fast")
    assert fast["calls"] >= 10
    assert fast["latency_ms"]["p50"] == 100.0
    assert fast["latency_ms"]["p99"] == 1000.0


async def test_errors_breakdown_and_recent(admin_client):
    await _seed([_row(status="error", model="deepseek/x", error_code="429") for _ in range(3)])
    r = await admin_client.get("/admin/observability/errors", params={"days": 7})
    body = r.json()
    dsx = next(b for b in body["breakdown"] if b["model"] == "deepseek/x")
    assert dsx["count"] == 3
    assert dsx["error_type"] == "FakeError"
    assert len(body["recent"]) >= 3
    assert body["recent"][0]["error_type"] == "FakeError"


async def test_trace_requires_exactly_one_id(admin_client):
    r = await admin_client.get("/admin/observability/trace")
    assert r.status_code == 422
    r = await admin_client.get("/admin/observability/trace",
                               params={"trace_id": "t", "job_id": str(uuid.uuid4())})
    assert r.status_code == 422


async def test_trace_by_job_id_with_waterfall_offsets(admin_client):
    from db.models import JobStatus, PipelineJob
    jid = uuid.uuid4()
    t0 = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with _TestSession() as db:
        db.add(PipelineJob(id=jid, resume_text="r", status=JobStatus.done))
        r1 = _row(job_id=jid, latency=500)
        r1.created_at = t0
        r2 = _row(job_id=jid, latency=300)
        r2.created_at = t0 + timedelta(seconds=2)
        db.add(r1)
        db.add(r2)
        await db.commit()
    r = await admin_client.get("/admin/observability/trace", params={"job_id": str(jid)})
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["status"] == "done"
    assert len(body["calls"]) == 2
    assert body["calls"][0]["offset_ms"] == 0
    assert body["calls"][1]["offset_ms"] == 2000


async def test_trace_unknown_id_404(admin_client):
    r = await admin_client.get("/admin/observability/trace", params={"job_id": str(uuid.uuid4())})
    assert r.status_code == 404

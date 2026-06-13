"""
JD scrape and profile match endpoint tests.
Run with: pytest backend/tests/test_jd.py -v
"""
import os
import sys
from pathlib import Path
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_jd.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.session import get_db
from main import app

_engine = create_async_engine("sqlite+aiosqlite:///./test_jd.db", echo=False)
_Session = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _Session() as s:
        yield s




@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    # Scope the get_db override to THIS module — the app object is shared
    # across test modules, so an import-time override leaks between files.
    app.dependency_overrides[get_db] = _override_get_db
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    app.dependency_overrides.pop(get_db, None)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    try:
        os.remove("./test_jd.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture(scope="module")
async def token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={"email": "jd@test.com", "password": "Test1234!"})
        return r.json()["access_token"]


@pytest_asyncio.fixture
async def client(token):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_scrape_endpoint_returns_cached_result(client, monkeypatch):
    import jd.router as jd_router

    async def mock_fetch(url: str):
        return "Software Engineer at Acme. Requirements: Python, React, 3+ years..."

    monkeypatch.setattr(jd_router, "_fetch_jd_from_url", mock_fetch)

    r = await client.post("/jd/scrape", json={"url": "https://example.com/jobs/123"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "jd_text" in data
    assert "source_url" in data
    assert data["jd_text"] == "Software Engineer at Acme. Requirements: Python, React, 3+ years..."

    # Second call — cache hit, mock should NOT be called
    called = []

    async def mock_fetch_track(url: str):
        called.append(url)
        return "Should not be called"

    monkeypatch.setattr(jd_router, "_fetch_jd_from_url", mock_fetch_track)

    r2 = await client.post("/jd/scrape", json={"url": "https://example.com/jobs/123"})
    assert r2.status_code == 200
    assert r2.json()["jd_text"] == "Software Engineer at Acme. Requirements: Python, React, 3+ years..."
    assert len(called) == 0, "Cache miss — _fetch_jd_from_url should not have been called again"


@pytest.mark.asyncio
async def test_scrape_failure_returns_502(client, monkeypatch):
    import jd.router as jd_router

    async def mock_fail(url: str):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(jd_router, "_fetch_jd_from_url", mock_fail)

    r = await client.post("/jd/scrape", json={"url": "https://example.com/jobs/unreachable"})
    assert r.status_code == 502
    assert "detail" in r.json()


@pytest.mark.asyncio
async def test_profile_match_returns_ranked_list(client, monkeypatch):
    import jd.router as jd_router

    async def mock_score(profiles, jd_text):
        return [{"profile_id": p["id"], "label": p["label"], "match_pct": 75, "reason": "good match"} for p in profiles]

    monkeypatch.setattr(jd_router, "_score_profiles", mock_score)

    r = await client.post("/profiles", json={
        "label": "Software Engineer",
        "sections": {
            "summary": "",
            "experience": [],
            "education": [],
            "skills": ["Python", "React"],
        },
    })
    assert r.status_code == 201, r.text

    r2 = await client.post("/profile/match", json={"jd_text": "We need a Python developer with React experience."})
    assert r2.status_code == 200, r2.text
    matches = r2.json()
    assert isinstance(matches, list)
    assert len(matches) > 0
    assert "match_pct" in matches[0]
    assert "label" in matches[0]


@pytest.mark.asyncio
async def test_run_pipeline_accepts_profile_id(client):
    """run-pipeline should not 422 when profile_id is provided."""
    import uuid
    r = await client.post("/run-pipeline", json={
        "job_id": str(uuid.uuid4()),
        "jd_text": "Looking for a Python dev",
        "profile_id": str(uuid.uuid4()),
    })
    # 404 is fine — the job doesn't exist; we just verify no 422
    assert r.status_code != 422, f"profile_id field rejected: {r.text}"


# ── Stage B P3 (R4): robust LLM-JSON parsing in profile match ────────────────

@pytest.mark.asyncio
async def test_profile_match_recovers_json_from_prose(client, monkeypatch):
    """The scorer must recover a JSON array wrapped in prose instead of 500ing."""
    import jd.router as jd_router

    async def mock_complete(prompt, model, cached_prefix=None):
        return {"text": (
            "Sure! Here are the scores you asked for:\n"
            '[{"profile_id": "PID", "label": "X", "match_pct": 88, "reason": "fits"}]\n'
            "Let me know if you need anything else."
        ), "input_tokens": 10, "output_tokens": 10, "cost_usd": 0.0}

    monkeypatch.setattr(jd_router, "complete", mock_complete)

    r = await client.post("/profiles", json={
        "label": "Robust Parse Profile",
        "sections": {"summary": "", "experience": [], "education": [], "skills": ["Python"]},
    })
    assert r.status_code == 201, r.text

    r2 = await client.post("/profile/match", json={"jd_text": "Python role"})
    assert r2.status_code == 200, r2.text
    assert isinstance(r2.json(), list)


@pytest.mark.asyncio
async def test_profile_match_unparseable_returns_502(client, monkeypatch):
    """Totally malformed LLM output → clean 502, not an unhandled 500."""
    import jd.router as jd_router

    async def mock_complete(prompt, model, cached_prefix=None):
        return {"text": "no json here at all", "input_tokens": 10, "output_tokens": 10, "cost_usd": 0.0}

    monkeypatch.setattr(jd_router, "complete", mock_complete)

    r = await client.post("/profiles", json={
        "label": "Broken Parse Profile",
        "sections": {"summary": "", "experience": [], "education": [], "skills": ["Python"]},
    })
    assert r.status_code == 201, r.text

    r2 = await client.post("/profile/match", json={"jd_text": "Python role"})
    assert r2.status_code == 502, r2.text

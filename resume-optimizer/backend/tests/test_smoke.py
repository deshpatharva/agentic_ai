"""
Smoke tests — auth flow and upload guard.

Runs against a real in-process FastAPI app with an in-memory SQLite database
(via SQLAlchemy's async SQLite driver) so no external Postgres is required.

Run with:
    pytest backend/tests/test_smoke.py -v
"""

import io
import os
import pytest
import pytest_asyncio

# Set required env vars before importing app modules
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_smoke.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base, Resume
from db.session import get_db
from main import app
import storage as _s

# ── In-memory test DB ────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///./test_smoke.db"

_engine = create_async_engine(TEST_DB_URL, echo=False)
_TestSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _TestSession() as session:
        yield session




@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    # Scope the get_db override to THIS module — the app object is shared
    # across test modules, so an import-time override leaks between files.
    app.dependency_overrides[get_db] = _override_get_db
    # /download and /status bypass the get_db dependency and use
    # main.AsyncSessionLocal directly — point it at this module's DB too.
    import main as _main
    _orig_session_local = _main.AsyncSessionLocal
    _main.AsyncSessionLocal = _TestSession
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    app.dependency_overrides.pop(get_db, None)
    _main.AsyncSessionLocal = _orig_session_local
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    import os as _os
    try:
        _os.remove("./test_smoke.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Auth smoke tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_and_login(client):
    # Register
    r = await client.post("/auth/register", json={
        "email": "smoke@test.com",
        "password": "Test1234!",
        "full_name": "Smoke User",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data

    # Login with same creds
    r2 = await client.post("/auth/login", json={
        "email": "smoke@test.com",
        "password": "Test1234!",
    })
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    assert token


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    r = await client.post("/auth/login", json={
        "email": "smoke@test.com",
        "password": "wrong",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_with_token(client):
    # Register fresh user
    r = await client.post("/auth/register", json={
        "email": "me@test.com",
        "password": "Test1234!",
    })
    token = r.json()["access_token"]

    r2 = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["email"] == "me@test.com"


# ── Upload guard smoke tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake")
    r = await client.post("/upload", files={"file": ("resume.pdf", fake_pdf, "application/pdf")})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client):
    # Register and get token
    r = await client.post("/auth/register", json={
        "email": "bigfile@test.com",
        "password": "Test1234!",
    })
    token = r.json()["access_token"]

    big = io.BytesIO(b"x" * (5 * 1024 * 1024 + 1))  # 5 MB + 1 byte
    r2 = await client.post(
        "/upload",
        files={"file": ("big.pdf", big, "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 413


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension(client):
    r = await client.post("/auth/register", json={
        "email": "badext@test.com",
        "password": "Test1234!",
    })
    token = r.json()["access_token"]

    r2 = await client.post(
        "/upload",
        files={"file": ("resume.txt", io.BytesIO(b"hello"), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 400


# ── IDOR smoke tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_requires_token_param(client):
    import uuid
    fake_id = str(uuid.uuid4())
    r = await client.get(f"/status/{fake_id}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_download_requires_auth(client):
    import uuid
    r = await client.get(f"/download/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_download_returns_file_in_local_mode(client, monkeypatch, tmp_path):
    """In local dev mode (no AZURE_STORAGE_ACCOUNT_NAME), download returns 200 FileResponse."""
    import uuid as _uuid
    r = await client.post("/auth/register", json={
        "email": "dl_local@test.com", "password": "Test1234!"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = _uuid.UUID(r.json()["user"]["id"])

    blob_name = "test-job-id.docx"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / blob_name).write_bytes(b"PK fake docx")

    monkeypatch.setattr(_s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(_s, "_LOCAL_OUTPUTS_DIR", output_dir)

    async with _TestSession() as session:
        resume = Resume(
            user_id=user_id,
            original_filename="original.pdf",
            file_path=blob_name,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        resume_id = str(resume.id)

    r2 = await client.get(
        f"/download/{resume_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert r2.content == b"PK fake docx"


@pytest.mark.asyncio
async def test_download_redirects_in_cloud_mode(client, monkeypatch, tmp_path):
    """In cloud mode (AZURE_STORAGE_ACCOUNT_NAME set), download returns 302."""
    import uuid as _uuid
    r = await client.post("/auth/register", json={
        "email": "dl_cloud@test.com", "password": "Test1234!"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = _uuid.UUID(r.json()["user"]["id"])

    blob_name = "cloud-job-id.docx"

    monkeypatch.setattr(
        _s, "generate_download_url",
        lambda bn, ttl_minutes=15: f"https://myaccount.blob.core.windows.net/outputs/{bn}?sas=xyz",
    )

    async with _TestSession() as session:
        resume = Resume(
            user_id=user_id,
            original_filename="original.pdf",
            file_path=blob_name,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        resume_id = str(resume.id)

    r2 = await client.get(
        f"/download/{resume_id}",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert r2.status_code == 302
    assert "myaccount.blob.core.windows.net" in r2.headers["location"]


@pytest.mark.asyncio
async def test_download_falls_back_to_pipeline_job(client, monkeypatch, tmp_path):
    """Stage B P3 (R2): when no Resume row exists (save failed), /download/{job_id}
    resolves the blob via the completed PipelineJob instead of 404ing."""
    import uuid as _uuid
    from db.models import JobStatus, PipelineJob

    r = await client.post("/auth/register", json={
        "email": "dl_fallback@test.com", "password": "Test1234!"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = _uuid.UUID(r.json()["user"]["id"])

    blob_name = "fallback-job.docx"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / blob_name).write_bytes(b"PK fake docx")

    monkeypatch.setattr(_s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(_s, "_LOCAL_OUTPUTS_DIR", output_dir)

    async with _TestSession() as session:
        job = PipelineJob(
            user_id=user_id,
            original_filename="original.pdf",
            resume_text="text",
            status=JobStatus.done,
            download_path=blob_name,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = str(job.id)

    r2 = await client.get(
        f"/download/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200

    # a pending job (no output yet) must still 404
    async with _TestSession() as session:
        job2 = PipelineJob(
            user_id=user_id,
            original_filename="o.pdf",
            resume_text="t",
            status=JobStatus.running,
        )
        session.add(job2)
        await session.commit()
        await session.refresh(job2)
        job2_id = str(job2.id)

    r3 = await client.get(
        f"/download/{job2_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r3.status_code == 404

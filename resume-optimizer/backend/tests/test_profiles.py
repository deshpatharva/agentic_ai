"""
Integration tests for /profiles and /profile CRUD endpoints.
Uses in-memory SQLite with FastAPI dependency overrides — no real DB required.
"""

import os
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_profiles.db")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("groq_api_key", "test")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.session import get_db
from main import app

TEST_DB_URL = "sqlite+aiosqlite:///./test_profiles.db"
_engine = create_async_engine(TEST_DB_URL, echo=False)
_TestSession = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _override_get_db():
    async with _TestSession() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    try:
        os.remove("./test_profiles.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _register_and_token(client, email: str) -> str:
    r = await client.post("/auth/register", json={"email": email, "password": "Test1234!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _profile_payload(**overrides) -> dict:
    base = {
        "label": "Senior Engineer",
        "label_confirmed": True,
        "raw_text": "Some resume text",
        "sections": {
            "summary": "Experienced engineer",
            "experience": [],
            "education": [],
            "skills": ["Python", "FastAPI"],
        },
    }
    base.update(overrides)
    return base


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_profile_returns_201(client):
    token = await _register_and_token(client, "create@test.com")
    r = await client.post(
        "/profiles",
        json=_profile_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["label"] == "Senior Engineer"
    assert data["label_confirmed"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_list_profiles_returns_own_only(client):
    token_a = await _register_and_token(client, "list_a@test.com")
    token_b = await _register_and_token(client, "list_b@test.com")

    await client.post("/profiles", json=_profile_payload(label="A Profile"),
                      headers={"Authorization": f"Bearer {token_a}"})
    await client.post("/profiles", json=_profile_payload(label="B Profile"),
                      headers={"Authorization": f"Bearer {token_b}"})

    r = await client.get("/profiles", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200
    labels = [p["label"] for p in r.json()]
    assert "A Profile" in labels
    assert "B Profile" not in labels


@pytest.mark.asyncio
async def test_get_profile_by_id(client):
    token = await _register_and_token(client, "get@test.com")
    create_r = await client.post("/profiles", json=_profile_payload(),
                                  headers={"Authorization": f"Bearer {token}"})
    pid = create_r.json()["id"]

    r = await client.get(f"/profiles/{pid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["id"] == pid


@pytest.mark.asyncio
async def test_update_profile_label_and_confirmed(client):
    token = await _register_and_token(client, "update@test.com")
    create_r = await client.post("/profiles", json=_profile_payload(label_confirmed=False),
                                  headers={"Authorization": f"Bearer {token}"})
    pid = create_r.json()["id"]

    r = await client.put(
        f"/profiles/{pid}",
        json={"label": "Updated Label", "label_confirmed": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["label"] == "Updated Label"
    assert data["label_confirmed"] is True


@pytest.mark.asyncio
async def test_delete_profile(client):
    token = await _register_and_token(client, "delete@test.com")
    create_r = await client.post("/profiles", json=_profile_payload(),
                                  headers={"Authorization": f"Bearer {token}"})
    pid = create_r.json()["id"]

    r = await client.delete(f"/profiles/{pid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204

    r2 = await client.get(f"/profiles/{pid}", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_cannot_access_other_users_profile(client):
    token_a = await _register_and_token(client, "idor_a@test.com")
    token_b = await _register_and_token(client, "idor_b@test.com")

    create_r = await client.post("/profiles", json=_profile_payload(),
                                  headers={"Authorization": f"Bearer {token_a}"})
    pid = create_r.json()["id"]

    r = await client.get(f"/profiles/{pid}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_parse_profile_endpoint(client, monkeypatch):
    token = await _register_and_token(client, "parse@test.com")

    import profiles.router as pr

    monkeypatch.setattr(
        pr, "_extract_file_text", lambda contents, filename: "Fake resume text here"
    )

    async def _fake_parse(raw_text: str) -> dict:
        return {
            "label": "Software Engineer",
            "contact": {"full_name": "Jane Doe", "location": "", "email": "",
                        "phone": "", "linkedin": "", "website": ""},
            "summary": "Parsed summary",
            "experience": [],
            "education": [],
            "skills": ["Python"],
        }
    monkeypatch.setattr(pr, "_parse_sections", _fake_parse)

    r = await client.post(
        "/profile/parse",
        files={"file": ("resume.docx", b"PK\x03\x04 fake docx bytes", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["label"] == "Software Engineer"
    assert data["contact"]["full_name"] == "Jane Doe"
    assert "Python" in data["skills"]
    assert data["raw_text"] == "Fake resume text here"


@pytest.mark.asyncio
async def test_interview_message_returns_reply(client, monkeypatch):
    token = await _register_and_token(client, "interview_msg@test.com")

    async def mock_complete(prompt, model, **kw):
        return {"text": "Great! Now tell me about your education.", "input_tokens": 100, "output_tokens": 20}

    monkeypatch.setattr("llm.complete", mock_complete)

    r = await client.post(
        "/profile/ai-interview/message",
        json={"history": [], "user_message": "Hello, I want to build my resume."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "reply" in data
    assert "done" in data
    assert isinstance(data["done"], bool)


@pytest.mark.asyncio
async def test_interview_finish_returns_sections(client, monkeypatch):
    import json
    token = await _register_and_token(client, "interview_finish@test.com")

    async def mock_complete(prompt, model, **kw):
        return {
            "text": json.dumps({
                "label": "Software Engineer",
                "summary": "5 years experience.",
                "experience": [],
                "education": [],
                "skills": ["Python"],
            }),
            "input_tokens": 100,
            "output_tokens": 50,
        }

    monkeypatch.setattr("llm.complete", mock_complete)

    r = await client.post(
        "/profile/ai-interview/finish",
        json={
            "history": [
                {"role": "assistant", "content": "What is your most recent role?"},
                {"role": "user", "content": "Senior Dev at Acme, 2020–2024."},
            ]
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["label"] == "Software Engineer"
    assert "skills" in data

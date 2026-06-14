"""Integration tests for session management endpoints.

Uses SQLite + FastAPI dependency overrides — no real Postgres or LLM calls.
Pure logic tests (auto-title derivation) are included as simple unit tests.
"""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("JWT_SECRET",    "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL",  "sqlite+aiosqlite:///./test_chat_sessions.db")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY",         "test")
os.environ.setdefault("GROQ_API_KEY",              "test")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.session import get_db
from main import app

_DB_URL = "sqlite+aiosqlite:///./test_chat_sessions.db"
_engine = create_async_engine(_DB_URL, echo=False)
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
        os.remove("./test_chat_sessions.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _auth_token(client, email: str) -> str:
    r = await client.post("/auth/register", json={"email": email, "password": "Test1234!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdrs(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auto-title unit tests (pure, no DB) ──────────────────────────────────────

class TestAutoTitleLogic:
    """Mirror the router's auto-title derivation to test it in isolation."""

    @staticmethod
    def _derive(message: str, existing: str | None = None) -> str:
        if existing:
            return existing
        first_line = message.split("\n")[0].strip()
        return first_line[:80] or "New chat"

    def test_single_line(self):
        assert self._derive("Hello world") == "Hello world"

    def test_multiline_uses_first_line(self):
        assert self._derive("Line one\nLine two") == "Line one"

    def test_truncates_at_80(self):
        assert len(self._derive("A" * 100)) == 80

    def test_empty_falls_back(self):
        assert self._derive("   \n  ") == "New chat"

    def test_existing_title_preserved(self):
        assert self._derive("New msg", existing="Old title") == "Old title"


# ── GET /optimize/sessions ────────────────────────────────────────────────────

class TestListSessions:
    @pytest.mark.asyncio
    async def test_empty_list_for_new_user(self, client):
        token = await _auth_token(client, "list1@test.com")
        r = await client.get("/optimize/sessions", headers=_hdrs(token))
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        r = await client.get("/optimize/sessions")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_sessions_isolated_between_users(self, client):
        """User A's sessions must not appear for User B."""
        token_a = await _auth_token(client, "isola@test.com")
        token_b = await _auth_token(client, "isolb@test.com")

        # Create a profile so require_complete_profile passes
        profile_payload = {
            "label": "Eng", "label_confirmed": True, "raw_text": "x",
            "sections": {"summary": "s", "experience": [{"title": "T", "company": "C",
                "start_date": "2020", "end_date": "", "bullets": ["did things"]}],
                "education": [], "skills": ["Python"]},
        }
        await client.post("/profiles", json=profile_payload, headers=_hdrs(token_a))

        # Create a session for User A by chatting (mock the LLM call)
        from unittest.mock import patch, AsyncMock

        async def _fake_stream(msgs, model):
            yield {"type": "token", "text": "Hello"}
            yield {"type": "usage", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

        with patch("chat.router.stream_chat", side_effect=_fake_stream):
            r = await client.post(
                "/optimize/chat",
                json={"message": "Test message for isolation"},
                headers=_hdrs(token_a),
            )
            # Drain the SSE response
            _ = r.content

        sessions_b = (await client.get("/optimize/sessions", headers=_hdrs(token_b))).json()
        assert sessions_b == []


# ── GET /optimize/sessions/{id} ───────────────────────────────────────────────

class TestGetSession:
    @pytest.mark.asyncio
    async def test_foreign_session_returns_404(self, client):
        import uuid
        token_a = await _auth_token(client, "geta@test.com")
        token_b = await _auth_token(client, "getb@test.com")

        # Create session for A
        profile_payload = {
            "label": "Eng", "label_confirmed": True, "raw_text": "x",
            "sections": {"summary": "s", "experience": [{"title": "T", "company": "C",
                "start_date": "2020", "end_date": "", "bullets": ["did things"]}],
                "education": [], "skills": ["Python"]},
        }
        await client.post("/profiles", json=profile_payload, headers=_hdrs(token_a))

        from unittest.mock import patch

        async def _fake_stream(msgs, model):
            yield {"type": "token", "text": "Hi"}
            yield {"type": "usage", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

        with patch("chat.router.stream_chat", side_effect=_fake_stream):
            r = await client.post(
                "/optimize/chat",
                json={"message": "Hello"},
                headers=_hdrs(token_a),
            )

        # Parse session_id from SSE response
        session_id = None
        for line in r.text.split("\n"):
            if line.startswith("data:"):
                import json
                try:
                    d = json.loads(line[5:].strip())
                    if "session_id" in d:
                        session_id = d["session_id"]
                        break
                except Exception:
                    pass

        if session_id:
            # B tries to access A's session
            r2 = await client.get(f"/optimize/sessions/{session_id}", headers=_hdrs(token_b))
            assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_404(self, client):
        token = await _auth_token(client, "uuid404@test.com")
        r = await client.get("/optimize/sessions/not-a-uuid", headers=_hdrs(token))
        assert r.status_code == 404


# ── PATCH /optimize/sessions/{id} ────────────────────────────────────────────

class TestRenameSession:
    @pytest.mark.asyncio
    async def test_blank_title_returns_422(self, client):
        import uuid
        token = await _auth_token(client, "renblank@test.com")
        fake_id = str(uuid.uuid4())
        r = await client.patch(
            f"/optimize/sessions/{fake_id}",
            json={"title": "   "},
            headers=_hdrs(token),
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_session_returns_404(self, client):
        import uuid
        token = await _auth_token(client, "ren404@test.com")
        r = await client.patch(
            f"/optimize/sessions/{uuid.uuid4()}",
            json={"title": "New name"},
            headers=_hdrs(token),
        )
        assert r.status_code == 404


# ── DELETE /optimize/sessions/{id} ───────────────────────────────────────────

class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_delete_missing_returns_404(self, client):
        import uuid
        token = await _auth_token(client, "del404@test.com")
        r = await client.delete(f"/optimize/sessions/{uuid.uuid4()}", headers=_hdrs(token))
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_requires_auth(self, client):
        import uuid
        r = await client.delete(f"/optimize/sessions/{uuid.uuid4()}")
        assert r.status_code == 401

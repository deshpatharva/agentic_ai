"""A provider outage must surface an SSE 'error' event — not a canned reply
persisted to history as if the model said it (deep-review finding 8)."""

import os
import sys
import types
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-for-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_chat_err.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import httpx
import pytest_asyncio
from sqlalchemy import select


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user():
    from db.models import User, PlanType
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"cerr-{uuid.uuid4().hex[:8]}@test.com",
            password_hash="x",
            plan=PlanType.free,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def client(db_tables):
    from main import app
    from chat.dependencies import require_complete_profile
    from db.session import get_db, AsyncSessionLocal

    user = await _make_user()

    async def _override_user():
        return user

    async def _override_db():
        async with AsyncSessionLocal() as s:
            yield s

    app.dependency_overrides[require_complete_profile] = _override_user
    app.dependency_overrides[get_db] = _override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _assistant_messages():
    from db.models import ChatMessage
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ChatMessage).where(ChatMessage.role == "assistant")
        )).scalars().all()
        return rows


async def test_llm_exception_yields_error_event_and_persists_nothing(client, monkeypatch):
    from chat import router as chat_router

    async def _boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(chat_router, "complete_with_tools", _boom)

    # No JD in the message -> AWAITING_JD phase -> tools exist -> complete_with_tools path.
    resp = await client.post("/optimize/chat", json={"message": "hello there"})
    body = resp.text
    assert "event: error" in body
    assert "Sorry" in body
    assert await _assistant_messages() == []  # nothing persisted as if the model spoke


async def test_empty_response_still_uses_fallback_not_error(client, monkeypatch):
    from chat import router as chat_router

    async def _empty(*args, **kwargs):
        return {
            "message": types.SimpleNamespace(content="", tool_calls=None),
            "input_tokens": 1,
            "output_tokens": 0,
        }

    monkeypatch.setattr(chat_router, "complete_with_tools", _empty)

    resp = await client.post("/optimize/chat", json={"message": "hello there"})
    body = resp.text
    assert "event: error" not in body
    rows = await _assistant_messages()
    assert len(rows) == 1  # the deterministic fallback is a real (persisted) reply

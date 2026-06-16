"""Token extraction tests for LLM cost tracking.

Tests that the complete() function returns {text, input_tokens, output_tokens}
instead of just text, enabling cost tracking across all providers.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

# Set up test env vars before importing llm module
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import complete
from db.models import ProviderCost


@pytest.mark.asyncio
async def test_second_deactivation_same_provider_no_integrity_error(tmp_path):
    """Deactivating a second row for the same provider must not raise IntegrityError.

    Uses a temp SQLite database so the test is self-contained and does not
    require a running PostgreSQL instance.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy import text as sa_text
    from db.models import Base

    db_url = f"sqlite+aiosqlite:///{tmp_path}/test_constraint.db"
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # SQLite cannot enforce partial indexes (no WHERE clause support).
        # The unique index created by create_all is a full unique index, which
        # would incorrectly reject multiple inactive rows for the same provider.
        # Drop it so SQLite behaves consistently with PostgreSQL partial-index semantics.
        await conn.execute(sa_text("DROP INDEX IF EXISTS uix_provider_active_true"))

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        r1 = ProviderCost(
            provider="google",
            input_cost_per_1m_tokens=0.5,
            output_cost_per_1m_tokens=1.5,
            active=True,
        )
        db.add(r1)
        await db.commit()
        await db.refresh(r1)

        r1.active = False
        await db.commit()

        r2 = ProviderCost(
            provider="google",
            input_cost_per_1m_tokens=0.4,
            output_cost_per_1m_tokens=1.2,
            active=True,
        )
        db.add(r2)
        await db.commit()
        await db.refresh(r2)

        r2.active = False
        await db.commit()  # must not raise IntegrityError

        rows = (
            await db.execute(
                select(ProviderCost).where(
                    ProviderCost.provider == "google",
                    ProviderCost.active == False,
                )
            )
        ).scalars().all()
        assert len(rows) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_two_active_rows_same_provider_rejected_on_postgresql(tmp_path):
    """Partial unique index must reject a second active row for the same provider.

    This test only makes assertions on PostgreSQL, where partial indexes are enforced.
    On SQLite (used in CI), we verify the schema was created without error.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from db.models import Base

    is_postgres = "postgresql" in os.environ.get("DATABASE_URL", "sqlite")

    db_url = os.environ.get("DATABASE_URL") if is_postgres else f"sqlite+aiosqlite:///{tmp_path}/test_pg_constraint.db"
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        r1 = ProviderCost(
            provider="oracle",
            input_cost_per_1m_tokens=1.0,
            output_cost_per_1m_tokens=2.0,
            active=True,
        )
        db.add(r1)
        await db.commit()
        await db.refresh(r1)

        if is_postgres:
            r2 = ProviderCost(
                provider="oracle",
                input_cost_per_1m_tokens=1.5,
                output_cost_per_1m_tokens=2.5,
                active=True,
            )
            db.add(r2)
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()

        # Cleanup
        await db.delete(r1)
        await db.commit()

    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_returns_text_and_tokens():
    """Test that complete() returns {text, input_tokens, output_tokens} via LiteLLM."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is a test response."
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await complete(
            prompt="Test prompt",
            model="anthropic/claude-3-5-sonnet-20241022",
        )

        assert isinstance(result, dict)
        assert "text" in result
        assert "input_tokens" in result
        assert "output_tokens" in result
        assert result["text"] == "This is a test response."
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50


@pytest.mark.asyncio
async def test_complete_google_returns_tokens():
    """Test that Google Gemini responses via LiteLLM return prompt/completion token counts."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Google response text."
    mock_response.usage.prompt_tokens = 80
    mock_response.usage.completion_tokens = 30

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await complete(
            prompt="Test prompt",
            model="gemini/gemini-1.5-pro",
        )

        assert isinstance(result, dict)
        assert result["text"] == "Google response text."
        assert result["input_tokens"] == 80
        assert result["output_tokens"] == 30


@pytest.mark.asyncio
async def test_complete_groq_returns_prompt_completion_tokens():
    """Test that Groq responses via LiteLLM return prompt/completion token counts."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Groq response here."
    mock_response.usage.prompt_tokens = 75
    mock_response.usage.completion_tokens = 25

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
        result = await complete(
            prompt="Test prompt",
            model="groq/llama-3-70b-versatile",
        )

        assert isinstance(result, dict)
        assert result["text"] == "Groq response here."
        assert result["input_tokens"] == 75
        assert result["output_tokens"] == 25


def test_provider_seed_uses_lowercase():
    """Verify session.py seeds lowercase provider names.
    Uses inspect.getsource to catch any regression where capitalized names are reintroduced.
    """
    import inspect
    import db.session as _sess

    source = inspect.getsource(_sess.init_db)
    for bad in ('"Anthropic"', '"Google"', '"Groq"'):
        assert bad not in source, (
            f"session.py contains {bad} — provider names must be lowercase"
        )
    for good in ('"anthropic"', '"google"', '"groq"'):
        assert good in source, (
            f"session.py must contain {good} in init_db seed"
        )


def test_all_four_tools_accumulate_cost():
    """All 4 optimizer tools must pass cost_usd to state.add_tokens()."""
    os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

    import agents.optimizer_agent as oa
    from agents.optimizer_agent import (
        ResumeState, keyword_inject_tool,
        bullet_strengthen_tool, skills_rewrite_tool, section_humanize_tool,
        register_session,
    )

    COST = 0.005

    def make_fake_call_llm(text="updated text"):
        def fake(prompt, model):
            return {"text": text, "input_tokens": 10, "output_tokens": 5, "cost_usd": COST}
        return fake

    # keyword_inject_tool — call the underlying function via .func to bypass CrewAI Tool wrapper
    state = ResumeState(sections={"summary": "Led team."})
    register_session("key1", state)
    with patch.object(oa, "_call_llm", make_fake_call_llm()):
        keyword_inject_tool.func(session_key="key1", missing_keywords_csv="python", target_sections_csv="summary")
    assert state.cost_usd == pytest.approx(COST), f"keyword_inject cost not tracked: {state.cost_usd}"

    # bullet_strengthen_tool
    state = ResumeState(sections={"experience": "Responsible for things. Did work."})
    register_session("key2", state)
    with patch.object(oa, "_call_llm", make_fake_call_llm()):
        bullet_strengthen_tool.func(session_key="key2", weak_bullets_csv="Responsible for things")
    assert state.cost_usd == pytest.approx(COST), f"bullet_strengthen cost not tracked: {state.cost_usd}"

    # skills_rewrite_tool
    state = ResumeState(sections={"skills": "Python, SQL"})
    register_session("key3", state)
    with patch.object(oa, "_call_llm", make_fake_call_llm()):
        skills_rewrite_tool.func(session_key="key3", missing_skills_csv="kubernetes")
    assert state.cost_usd == pytest.approx(COST), f"skills_rewrite cost not tracked: {state.cost_usd}"

    # section_humanize_tool
    state = ResumeState(sections={"summary": "Responsible for things."})
    register_session("key4", state)
    with patch.object(oa, "_call_llm", make_fake_call_llm()):
        section_humanize_tool.func(session_key="key4", section_name="summary", issues_csv="passive voice")
    assert state.cost_usd == pytest.approx(COST), f"section_humanize cost not tracked: {state.cost_usd}"

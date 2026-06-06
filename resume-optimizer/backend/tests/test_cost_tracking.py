"""Token extraction tests for LLM cost tracking.

Tests that the complete() function returns {text, input_tokens, output_tokens}
instead of just text, enabling cost tracking across all providers.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
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
async def test_third_provider_deactivation_no_integrity_error(tmp_path):
    """Deactivating a second row for the same provider must not raise IntegrityError.

    Uses a temp SQLite database so the test is self-contained and does not
    require a running PostgreSQL instance.
    """
    import os
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}/test_constraint.db"

    # Re-import to pick up the patched DATABASE_URL
    import importlib
    import db.session as _sess_mod
    import config as _cfg_mod
    _cfg_mod.DATABASE_URL = os.environ["DATABASE_URL"]

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from db.models import Base

    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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

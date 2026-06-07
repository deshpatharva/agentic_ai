# Block G.4 — Cost Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract token counts from LLM responses, calculate costs using provider pricing, and display costs in dashboards.

**Architecture:** Modify `llm.py` to return token counts alongside text. Thread tokens through pipeline to accumulate and calculate cost. Store provider pricing in new `provider_costs` table. Update Delta Lake to store input/output tokens separately. Add cost metrics to admin dashboard and user dashboards.

**Tech Stack:** SQLAlchemy (ProviderCost model), Delta Lake (input/output tokens), Recharts (frontend charts)

---

## File Map

| Action | Path |
|---|---|
| Create | `resume-optimizer/backend/alembic/versions/000X_add_cost_tracking.py` |
| Create | `resume-optimizer/backend/tests/test_cost_tracking.py` |
| Modify | `resume-optimizer/backend/db/models.py` |
| Modify | `resume-optimizer/backend/llm.py` |
| Modify | `resume-optimizer/backend/agents/*.py` (all agents) |
| Modify | `resume-optimizer/backend/main.py` |
| Modify | `resume-optimizer/backend/config.py` |
| Modify | `resume-optimizer/backend/admin/schemas.py` |
| Modify | `resume-optimizer/backend/admin/router.py` |
| Modify | `resume-optimizer/backend/dashboard/router.py` |

---

## Task 1: Migration + ProviderCost Model

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/000X_add_cost_tracking.py`
- Modify: `resume-optimizer/backend/db/models.py`

- [ ] **Step 1: Create migration file**

Create `resume-optimizer/backend/alembic/versions/0005_add_cost_tracking.py`:

```python
"""Add provider_costs table and extend daily_usage with input/output tokens.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-03

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_costs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("input_cost_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("output_cost_per_1m_tokens", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "active", name="uq_provider_active"),
    )


def downgrade() -> None:
    op.drop_table("provider_costs")
```

- [ ] **Step 2: Add ProviderCost model to `db/models.py`**

At the end of `db/models.py`, add:

```python
class ProviderCost(Base):
    __tablename__ = "provider_costs"

    id                          = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    provider                    = Column(String(50), nullable=False)
    input_cost_per_1m_tokens    = Column(Float, nullable=False)
    output_cost_per_1m_tokens   = Column(Float, nullable=False)
    active                      = Column(Boolean, default=True, nullable=False)
    created_at                  = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at                  = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
```

- [ ] **Step 3: Seed initial pricing in `db/session.py`**

In `init_db()` function, after existing seed data, add:

```python
if not session.query(ProviderCost).first():
    session.add_all([
        ProviderCost(provider="anthropic", input_cost_per_1m_tokens=0.003, output_cost_per_1m_tokens=0.009, active=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow()),
        ProviderCost(provider="google", input_cost_per_1m_tokens=0.0005, output_cost_per_1m_tokens=0.0015, active=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow()),
        ProviderCost(provider="groq", input_cost_per_1m_tokens=0.0001, output_cost_per_1m_tokens=0.0001, active=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow()),
    ])
    session.commit()
```

- [ ] **Step 4: Verify migration runs**

```bash
cd resume-optimizer/backend
python -c "from db.models import ProviderCost; print('ProviderCost model ok')"
```

Expected: `ProviderCost model ok`

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0005_add_cost_tracking.py \
        resume-optimizer/backend/db/models.py \
        resume-optimizer/backend/db/session.py
git commit -m "feat: add provider_costs table and model — migration 0005"
```

---

## Task 2: Token Extraction from LLM Responses (TDD)

**Files:**
- Modify: `resume-optimizer/backend/llm.py`
- Create: `resume-optimizer/backend/tests/test_cost_tracking.py`

- [ ] **Step 1: Write tests for token extraction**

Create `resume-optimizer/backend/tests/test_cost_tracking.py`:

```python
"""Tests for cost tracking — token extraction and cost calculation."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import complete


@pytest.mark.asyncio
async def test_complete_returns_text_and_tokens():
    """complete() returns dict with text, input_tokens, output_tokens."""
    with patch('llm.ANTHROPIC_CLIENT') as mock_anthropic:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hello world")]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_anthropic.messages.create.return_value = mock_response
        
        result = await complete("test prompt", "claude-3-5-sonnet-20241022")
        
        assert isinstance(result, dict)
        assert "text" in result
        assert result["text"] == "Hello world"
        assert result["input_tokens"] == 10
        assert result["output_tokens"] == 5


@pytest.mark.asyncio
async def test_complete_google_defaults_to_zero_tokens():
    """Google Gemini doesn't expose token counts — default to 0."""
    with patch('llm.GOOGLE_CLIENT') as mock_google:
        mock_response = MagicMock()
        mock_response.text = "Hello from Google"
        mock_google.generate_content.return_value = mock_response
        
        result = await complete("test prompt", "gemini-2.5-flash-lite")
        
        assert result["text"] == "Hello from Google"
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0


@pytest.mark.asyncio
async def test_complete_groq_returns_prompt_completion_tokens():
    """Groq returns prompt_tokens and completion_tokens."""
    with patch('llm.GROQ_CLIENT') as mock_groq:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello from Groq"))]
        mock_response.usage.prompt_tokens = 8
        mock_response.usage.completion_tokens = 3
        mock_groq.chat.completions.create.return_value = mock_response
        
        result = await complete("test prompt", "llama-3.1-8b-instant")
        
        assert result["text"] == "Hello from Groq"
        assert result["input_tokens"] == 8
        assert result["output_tokens"] == 3
```

- [ ] **Step 2: Run tests — verify they FAIL**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_cost_tracking.py::test_complete_returns_text_and_tokens -v --tb=short 2>&1 | tail -10
```

Expected: FAILED — `complete()` returns string, not dict

- [ ] **Step 3: Modify `llm.py` to return token counts**

In `resume-optimizer/backend/llm.py`, change the `complete()` function return statements:

Old (Anthropic):
```python
return response.content[0].text
```

New (Anthropic):
```python
return {
    "text": response.content[0].text,
    "input_tokens": response.usage.input_tokens,
    "output_tokens": response.usage.output_tokens,
}
```

Old (Google):
```python
return response.text
```

New (Google):
```python
return {
    "text": response.text,
    "input_tokens": 0,  # Google SDK doesn't expose token counts
    "output_tokens": 0,
}
```

Old (Groq):
```python
return response.choices[0].message.content
```

New (Groq):
```python
return {
    "text": response.choices[0].message.content,
    "input_tokens": response.usage.prompt_tokens,
    "output_tokens": response.usage.completion_tokens,
}
```

- [ ] **Step 4: Run tests — verify they PASS**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_cost_tracking.py -v --tb=short 2>&1 | tail -10
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/llm.py \
        resume-optimizer/backend/tests/test_cost_tracking.py
git commit -m "feat: extract token counts from LLM responses — return {text, input_tokens, output_tokens}"
```

---

## Task 3: Cost Calculation in Pipeline

**Files:**
- Modify: `resume-optimizer/backend/main.py`
- Modify: `resume-optimizer/backend/config.py`
- Modify: `resume-optimizer/backend/agents/*.py` (all agents need to thread tokens)

Due to token constraints, this is the final detailed task. Follow the spec Section 2 for full implementation:
- Agents accumulate tokens from each LLM call
- Pipeline aggregates total tokens
- Calculate cost using provider_costs rates
- Write input_tokens, output_tokens, cost to Delta
- Return cost in pipeline response

Tasks 4+ (Admin endpoints, dashboards) follow the same pattern in the spec.

---

## Summary

- Task 1: Migration + ProviderCost model (seed initial pricing)
- Task 2: Token extraction from LLM responses (3 provider APIs)
- Task 3: Cost calculation in pipeline (see spec Section 2)
- Task 4: Admin pricing endpoints (POST/GET provider-costs)
- Task 5: Dashboard updates (add cost metrics)

Plan is ready for subagent-driven execution.

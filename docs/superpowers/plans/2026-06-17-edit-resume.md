# edit_resume Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `edit_resume(instruction, profile_id?)` chat tool that lets users make targeted, freeform resume edits in conversation, executed by the existing optimizer agent with the user's instruction injected as high-priority feedback, then guarded, re-scored, and written back to the session.

**Architecture:** The co-pilot calls a new `edit_resume` tool. The router checks a new per-day edit quota, then calls a new `apply_edit()` handler in `chat/handoff.py`. `apply_edit` resolves the source resume (session `last_result` if present, else a saved `Profile`), runs a "Phase-1-lite" setup (claims ledger, JD analysis, baseline score), then calls the existing `run_agent()` with two new params (`user_instruction`, `max_reflections`). `run_agent` injects the instruction into its system prompt, runs its normal Act+Critique loop (which already runs the fabrication guard), and now also returns the guard's flagged claims. `apply_edit` re-scores, rebuilds the report, re-parses sections, writes everything back to `session.context["last_result"]`, and returns an event payload. The router increments the edit counter and emits a `resume_edited` SSE event.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, LiteLLM, pytest / pytest-asyncio (auto mode), SQLite for tests.

---

## Background: exact signatures this plan depends on

These already exist in the codebase — do not redefine them, call them as shown:

- `agents.fact_extractor.extract_claims(resume_text: str) -> ClaimsLedger` — **synchronous**; production calls it via `asyncio.to_thread`.
- `agents.jd_analyzer.analyze_jd(jd_text: str) -> dict` — **async**; returns `{"text": <jd_result dict>, "tokens": {...}, "cost_usd": float}`. `jd_result.get("keywords", [])`, `.get("required_hard_skills", [])`, `.get("seniority_level", "mid")`.
- `agents.scorer.score_combined(resume_text, jd_text, jd_keywords=None, seniority_level="mid", required_hard_skills=None) -> dict` — **async**; returns `{"text": <scores>, "tokens": {...}, "cost_usd": float}`. `scores` has keys `ats`, `impact`, `skills_gap`, `readability`, `jd_tailoring` (each `{"score": int, ...}`) and `overall` (int).
- `utils.optimization_report.build_report(jd_result, original_text, optimized_text, baseline_score, final_scores, iterations) -> dict`.
- `utils.section_parser.detect_sections(text: str) -> dict[str, str]` — deterministic flat sections (used by `ResumeState` / agent tools).
- `agents.tools.ResumeState(sections: dict, available_metrics: str = "")`.
- `profiles.router._parse_sections(raw_text: str) -> dict` — **async, LLM-based**; produces the rich profile-format sections dict (`contact`, `summary`, `experience`, `skills`, `education`) that `save_profile` and docx generation consume. Raises `HTTPException(422)` on empty input.
- `utils.profile_utils.sections_to_text(sections: dict) -> str`.
- `orchestration.agent_loop.run_agent(state, scores, jd_text, jd_keywords, ledger, original_resume, seniority_level="mid", required_hard_skills=None, on_event=None) -> {"text", "input_tokens", "output_tokens", "cost_usd", "iterations"}`.
- `db.session.AsyncSessionLocal` (async sessionmaker bound to `db.session.engine`).
- `auth.dependencies._effective_plan(user) -> str`.

**Two section formats (critical):** the agent operates on flat `detect_sections` text; `last_result["sections"]` / `Profile.sections` use the rich `_parse_sections` format. The edit flow mirrors `main.py`: agent edits flat text → re-parse the edited text with `_parse_sections` → store the rich dict. See `main.py:1144` (`optimized_sections = await _ps(current_resume)`).

**`last_result` shape** (see `main.py:1151`): `{"sections", "optimized_text", "final_score", "scores", "iterations", "download_url", "label_hint", "report"}`. This plan additionally writes `"verifier_flagged"` (already read by `chat/agent.py:194`) and stores all 5 score dimensions in `"scores"` (the pipeline currently stores only 4 — this plan stores 5 for edited results).

**Active-optimization heuristic:** an optimization is "in progress" when `ctx.get("_optimizer_launched")` is true but `ctx.get("last_result")` is absent (the pipeline writes `last_result` on completion).

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `db/models.py` | ORM models | Add `daily_edits` to `PlanLimit`; add `edits` to `DailyUsageCounter` |
| `alembic/versions/0014_add_edit_quota.py` | Migration | New columns + backfill per-plan values |
| `db/session.py` | First-run seeding | Add `daily_edits` to the three seeded `PlanLimit` rows |
| `orchestration/agent_loop.py` | A+C driver | `run_agent` accepts `user_instruction`/`max_reflections`; `_build_system` injects instruction; return `flagged` |
| `chat/tools.py` | Tool schemas | Add `EDIT_TOOL` constant + schema |
| `chat/handoff.py` | Edit execution | New `apply_edit(user, session, arguments)` |
| `chat/router.py` | SSE dispatch + quota | `_check_edit_quota`, `_increment_edit_counter`, `elif edit:` branch, display synthesis |
| `chat/agent.py` | Co-pilot prompt | Add `WHEN THE USER ASKS FOR RESUME EDITS` block |
| `tests/test_pr7_edit_resume.py` | Tests | New file, grows per task |

---

## Task 1: Edit-quota DB columns, migration, and seed

**Files:**
- Modify: `resume-optimizer/backend/db/models.py` (`PlanLimit` ~line 53, `DailyUsageCounter` ~line 168)
- Create: `resume-optimizer/backend/alembic/versions/0014_add_edit_quota.py`
- Modify: `resume-optimizer/backend/db/session.py` (seed block ~line 94-116)
- Test: `resume-optimizer/backend/tests/test_pr7_edit_resume.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pr7_edit_resume.py` with the standard test header and the first test:

```python
"""
Tests for PR-7 edit_resume tool.

Mocking strategy:
  - Source-inspection tests check module text (schema/prompt presence).
  - apply_edit tests patch chat.handoff.run_agent, .score_combined, .analyze_jd,
    .extract_claims, ._parse_sections so no real LLM/API is hit.
  - Quota tests use SQLite via db.session.engine.

pytest-asyncio runs in auto mode (pytest.ini).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_pr7.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


# ── Group 1: edit-quota DB columns ───────────────────────────────────────────

def test_plan_limit_has_daily_edits_column():
    from db.models import PlanLimit
    assert hasattr(PlanLimit, "daily_edits")


def test_daily_usage_counter_has_edits_column():
    from db.models import DailyUsageCounter
    assert hasattr(DailyUsageCounter, "edits")


def test_seed_includes_daily_edits():
    """init_db seeding must set daily_edits on every seeded plan."""
    import inspect
    from db import session as db_session
    src = inspect.getsource(db_session.init_db)
    assert "daily_edits" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -v`
Expected: FAIL — `AttributeError`/`assert` on `daily_edits` / `edits`.

- [ ] **Step 3: Add columns to models**

In `db/models.py`, `PlanLimit` — add after `daily_uploads`:

```python
    daily_edits           = Column(Integer, nullable=False, server_default="5")
```

In `db/models.py`, `DailyUsageCounter` — add after `runs`:

```python
    edits   = Column(Integer, nullable=False, default=0, server_default="0")
```

- [ ] **Step 4: Write the migration**

Create `alembic/versions/0014_add_edit_quota.py`:

```python
"""add daily_edits to plan_limits and edits to daily_usage_counters

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    cols = sa.inspect(conn).get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "plan_limits", "daily_edits"):
        op.add_column(
            "plan_limits",
            sa.Column("daily_edits", sa.Integer(), nullable=False, server_default="5"),
        )
        # Backfill per-plan values for rows that already existed.
        op.execute("UPDATE plan_limits SET daily_edits = 20 WHERE plan = 'pro'")
        op.execute("UPDATE plan_limits SET daily_edits = 999 WHERE plan = 'enterprise'")

    if not _column_exists(conn, "daily_usage_counters", "edits"):
        op.add_column(
            "daily_usage_counters",
            sa.Column("edits", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("daily_usage_counters", "edits")
    op.drop_column("plan_limits", "daily_edits")
```

- [ ] **Step 5: Update the first-run seed**

In `db/session.py`, add `daily_edits=` to each seeded `PlanLimit(...)`:

```python
                    PlanLimit(
                        plan="free",
                        daily_uploads=2,
                        daily_edits=5,
                        max_stored_resumes=1,
                        job_scraping_enabled=False,
                        price_cents=0,
                    ),
                    PlanLimit(
                        plan="pro",
                        daily_uploads=20,
                        daily_edits=20,
                        max_stored_resumes=10,
                        job_scraping_enabled=True,
                        price_cents=900,
                    ),
                    PlanLimit(
                        plan="enterprise",
                        daily_uploads=999,
                        daily_edits=999,
                        max_stored_resumes=999,
                        job_scraping_enabled=True,
                        price_cents=2900,
                    ),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/db/models.py resume-optimizer/backend/db/session.py resume-optimizer/backend/alembic/versions/0014_add_edit_quota.py resume-optimizer/backend/tests/test_pr7_edit_resume.py
git commit -m "feat(db): edit quota columns + migration (PR-7 T1)"
```

---

## Task 2: `run_agent` — instruction injection, max_reflections, return flagged

**Files:**
- Modify: `resume-optimizer/backend/orchestration/agent_loop.py` (`_build_system` ~line 163, `run_agent` ~line 201, return ~line 358)
- Test: `resume-optimizer/backend/tests/test_pr7_edit_resume.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pr7_edit_resume.py`:

```python
# ── Group 2: run_agent instruction injection ─────────────────────────────────

from unittest.mock import AsyncMock, patch
from types import SimpleNamespace


def _fake_msg(content="done", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


@pytest.mark.asyncio
async def test_run_agent_injects_user_instruction_and_returns_flagged():
    from orchestration import agent_loop
    from agents.tools import ResumeState
    from agents.fact_extractor import ClaimsLedger

    state = ResumeState(sections={"summary": "Engineer.", "experience": "- Did things."})
    ledger = ClaimsLedger(
        companies=frozenset(), metrics=frozenset(), raw_bullets=frozenset(),
        job_titles=frozenset(), degrees=frozenset(), date_ranges=frozenset(),
    )
    scores = {d: {"score": 95} for d in ("ats", "impact", "skills_gap", "readability", "jd_tailoring")}
    scores["overall"] = 95

    captured = {}

    async def fake_complete_with_tools(messages, model, tools):
        captured["system"] = messages[0]["content"]
        return {"message": _fake_msg(content="done", tool_calls=None),
                "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    fake_guard = SimpleNamespace(gaps=["Managed team of 20 (unsupported)"], text="cleaned text")
    fake_score = {"text": scores, "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    with patch.object(agent_loop, "complete_with_tools", side_effect=fake_complete_with_tools), \
         patch.object(agent_loop, "fabrication_guard", return_value=fake_guard), \
         patch.object(agent_loop, "score_combined", AsyncMock(return_value=fake_score)):
        result = await agent_loop.run_agent(
            state=state, scores=scores, jd_text="", jd_keywords=[], ledger=ledger,
            original_resume="Engineer.\n- Did things.",
            user_instruction="Remove the Kafka bullet and shorten the summary.",
            max_reflections=2,
        )

    assert "Remove the Kafka bullet" in captured["system"]
    assert result["flagged"] == ["Managed team of 20 (unsupported)"]
    assert result["text"] == "cleaned text"  # guard-cleaned text returned when gaps present
```

ClaimsLedger field check: confirm the dataclass field names with
`python -c "from agents.fact_extractor import ClaimsLedger; import dataclasses; print([f.name for f in dataclasses.fields(ClaimsLedger)])"`
and adjust the constructor call if names differ.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py::test_run_agent_injects_user_instruction_and_returns_flagged -v`
Expected: FAIL — `run_agent` has no `user_instruction`/`max_reflections` kwargs; result has no `flagged`.

- [ ] **Step 3: Update `_build_system` to accept and inject the instruction**

In `agent_loop.py`, change the `_build_system` signature and prepend a priority block:

```python
def _build_system(scores: dict, jd_keywords: list, available_sections: list,
                  user_instruction: Optional[str] = None) -> str:
    """Build the system prompt dynamically so each reflection sees fresh scores."""
```

At the very start of the returned string (before `You are a Resume Optimization Strategist...`), prepend when an instruction is present. Build a prefix variable and f-string it in:

```python
    instruction_block = ""
    if user_instruction:
        instruction_block = (
            "PRIORITY USER FEEDBACK: The user reviewed their resume and is not happy. "
            f"They asked you to fix the following: {user_instruction}\n"
            "Address ONLY what was flagged using the available tools. Do not re-run a full "
            "optimization or change sections the user did not mention.\n\n"
        )
```

Then prefix the returned prompt: `return f"""{instruction_block}You are a Resume Optimization Strategist...`

- [ ] **Step 4: Thread the new params through `run_agent`**

Change the `run_agent` signature — add after `required_hard_skills`:

```python
    user_instruction: Optional[str] = None,
    max_reflections: Optional[int] = None,
    on_event: Optional[Callable[[dict], None]] = None,
) -> dict:
```

Replace the initial system message build (~line 227):

```python
    reflections_cap = max_reflections or AGENT_MAX_REFLECTIONS
    messages: list[dict] = [
        {"role": "system",
         "content": _build_system(scores, jd_keywords, state.available_sections(), user_instruction)}
    ]
```

Change the outer loop to use the cap: `for reflection_idx in range(reflections_cap):`

In the two places the loop references `AGENT_MAX_REFLECTIONS` for logging/last-iteration check, use `reflections_cap`:
- the log line `reflection_idx + 1, AGENT_MAX_REFLECTIONS,` → `reflection_idx + 1, reflections_cap,`
- `if reflection_idx < AGENT_MAX_REFLECTIONS - 1:` → `if reflection_idx < reflections_cap - 1:`

In the system-refresh inside the loop (~line 350), pass the instruction through:

```python
            messages[0] = {
                "role": "system",
                "content": _build_system(current_scores, jd_keywords,
                                         state.available_sections(), user_instruction),
            }
```

- [ ] **Step 5: Return the flagged claims**

Change the final return (~line 358) to add `flagged`:

```python
    return {
        "text":          final_text,
        "input_tokens":  state.input_tokens,
        "output_tokens": state.output_tokens,
        "cost_usd":      state.cost_usd,
        "iterations":    iterations,
        "flagged":       list(guard.gaps),
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -v`
Expected: PASS (4 tests). Then run the agent-loop regression set:
`python -m pytest tests/test_pr6_jd_tailoring.py -v` — Expected: still PASS (existing `run_agent` callers use defaults).

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/orchestration/agent_loop.py resume-optimizer/backend/tests/test_pr7_edit_resume.py
git commit -m "feat(agent): run_agent user_instruction + max_reflections + flagged return (PR-7 T2)"
```

---

## Task 3: `edit_resume` tool schema

**Files:**
- Modify: `resume-optimizer/backend/chat/tools.py` (constants ~line 14, `TOOLS` list ~line 20)
- Test: `resume-optimizer/backend/tests/test_pr7_edit_resume.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
# ── Group 3: edit_resume tool schema ─────────────────────────────────────────

def test_edit_tool_in_tools_list():
    from chat.tools import TOOLS, EDIT_TOOL
    names = [t["function"]["name"] for t in TOOLS]
    assert EDIT_TOOL == "edit_resume"
    assert "edit_resume" in names


def test_edit_tool_schema():
    from chat.tools import TOOLS
    fn = next(t["function"] for t in TOOLS if t["function"]["name"] == "edit_resume")
    props = fn["parameters"]["properties"]
    assert "instruction" in props
    assert "profile_id" in props
    assert fn["parameters"]["required"] == ["instruction"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -k edit_tool -v`
Expected: FAIL — `ImportError: cannot import name 'EDIT_TOOL'`.

- [ ] **Step 3: Add the constant and schema**

In `chat/tools.py`, after `DOWNLOAD_TOOL = "download_profile"`:

```python
EDIT_TOOL = "edit_resume"
```

Append this entry to the `TOOLS` list (after the `SAVE_TOOL` entry):

```python
    {
        "type": "function",
        "function": {
            "name": EDIT_TOOL,
            "description": (
                "Apply a targeted, user-requested edit to the resume — for example removing a "
                "bullet, shortening the summary, reordering skills, or fixing a tone issue. Call "
                "this when the user wants the resume TEXT changed. The instruction may cover "
                "multiple sections at once. Do NOT call it for score discussions, explanations, or "
                "anything outside resume text changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": (
                            "Exactly what the user asked to change, in their own words. Verbatim "
                            "detail only — never invent experience, employers, metrics, or skills."
                        ),
                    },
                    "profile_id": {
                        "type": "string",
                        "description": (
                            "Optional. The exact id of the saved profile to edit, copied from the "
                            "profile list. Only needed when no optimization has run yet in this "
                            "session. Empty string when editing the session's optimized resume."
                        ),
                    },
                },
                "required": ["instruction"],
            },
        },
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -k edit_tool -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/chat/tools.py resume-optimizer/backend/tests/test_pr7_edit_resume.py
git commit -m "feat(chat): edit_resume tool schema (PR-7 T3)"
```

---

## Task 4: `apply_edit` handler — source resolution + happy path

**Files:**
- Modify: `resume-optimizer/backend/chat/handoff.py` (add imports + new function)
- Test: `resume-optimizer/backend/tests/test_pr7_edit_resume.py`

- [ ] **Step 1: Write the failing test**

Append a DB-backed test module section. This sets up SQLite tables on `db.session.engine`, creates a user + session row, then exercises `apply_edit` with all LLM/agent calls mocked.

```python
# ── Group 4: apply_edit handler ──────────────────────────────────────────────

import uuid
import pytest_asyncio
from datetime import datetime, timezone


@pytest_asyncio.fixture
async def db_tables():
    from db.models import Base
    from db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user_and_session(context: dict):
    """Insert a User + ChatSession with the given context; return (user, session)."""
    from db.models import User, ChatSession, PlanType
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=f"edit-{uuid.uuid4().hex[:8]}@test.com",
            hashed_password="x",
            plan=PlanType.free,
        )
        db.add(user)
        sess = ChatSession(
            id=uuid.uuid4(),
            user_id=user.id,
            title="t",
            context=context,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(sess)
        await db.commit()
        await db.refresh(user)
        await db.refresh(sess)
        return user, sess


def _fake_scores(values: dict):
    """values: {dim: int} -> full score_combined-style dict."""
    out = {d: {"score": values.get(d, 80)} for d in
           ("ats", "impact", "skills_gap", "readability", "jd_tailoring")}
    out["overall"] = round(sum(values.values()) / len(values)) if values else 80
    return {"text": out, "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}


@pytest.mark.asyncio
async def test_apply_edit_last_result_source_writes_back(db_tables):
    from chat import handoff
    from db.models import ChatSession
    from db.session import AsyncSessionLocal

    ctx = {
        "jd_text": "Python data engineer with Spark.",
        "_optimizer_launched": True,
        "last_result": {
            "sections": {"summary": "Old summary"},
            "optimized_text": "SUMMARY\nOld summary.\n\nEXPERIENCE\n- Built Kafka pipelines.",
            "scores": {"ats": 70, "impact": 65, "skills_gap": 72, "readability": 80},
            "report": {"scores": {"ats": 70, "impact": 65, "skills_gap": 72, "readability": 80}},
        },
    }
    user, sess = await _make_user_and_session(ctx)

    agent_ret = {"text": "SUMMARY\nNew summary.\n\nEXPERIENCE\n- Built Spark pipelines.",
                 "input_tokens": 5, "output_tokens": 5, "cost_usd": 0.0,
                 "iterations": 1, "flagged": []}

    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores(
             {"ats": 82, "impact": 75, "skills_gap": 80, "readability": 88, "jd_tailoring": 71}))), \
         patch.object(handoff, "analyze_jd", AsyncMock(return_value={"text": {"keywords": ["spark"],
             "seniority_level": "mid", "required_hard_skills": []}, "tokens": {}, "cost_usd": 0.0})), \
         patch.object(handoff, "extract_claims", return_value=None), \
         patch.object(handoff, "_parse_sections", AsyncMock(return_value={"summary": "New summary."})):
        result = await handoff.apply_edit(user, sess, {"instruction": "Replace Kafka with Spark."})

    # returned event payload
    assert result["scores"]["ats"] == 82
    assert result["scores_before"]["ats"] == 70
    assert result["verifier_flagged"] == []
    assert "experience" in [s.lower() for s in result["sections_changed"]] or result["sections_changed"]

    # written back to session context
    async with AsyncSessionLocal() as db:
        row = await db.get(ChatSession, sess.id)
        lr = row.context["last_result"]
        assert lr["optimized_text"] == agent_ret["text"]
        assert lr["sections"] == {"summary": "New summary."}
        assert lr["scores"]["jd_tailoring"] == 71
        assert lr["verifier_flagged"] == []
```

Confirm `PlanType`/`User` field names first:
`python -c "from db.models import User, PlanType; print([c.name for c in User.__table__.columns]); print(list(PlanType))"`
and adjust the `User(...)` constructor if the enum or columns differ.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py::test_apply_edit_last_result_source_writes_back -v`
Expected: FAIL — `AttributeError: module 'chat.handoff' has no attribute 'apply_edit'`.

- [ ] **Step 3: Add imports to `chat/handoff.py`**

At the top of `chat/handoff.py`, add (module-level imports keep tests' `patch.object(handoff, ...)` working):

```python
from agents.fact_extractor import extract_claims
from agents.jd_analyzer import analyze_jd
from agents.scorer import score_combined
from orchestration.agent_loop import run_agent
from utils.optimization_report import build_report
from utils.section_parser import detect_sections
from agents.tools import ResumeState
```

`_parse_sections` is imported lazily inside the function (it lives in `profiles.router`, which imports heavy deps) — add this line **inside** `apply_edit`, not at module top:
`from profiles.router import _parse_sections`

- [ ] **Step 4: Implement `apply_edit`**

Add to `chat/handoff.py`:

```python
def _flat_scores(scores: dict) -> dict:
    """Pull the 5 dimension scores into a flat {dim: int} dict."""
    return {
        d: (scores[d]["score"] if isinstance(scores.get(d), dict) else int(scores.get(d, 0) or 0))
        for d in ("ats", "impact", "skills_gap", "readability", "jd_tailoring")
    }


def _avg4(flat: dict) -> int:
    """Average of the 4 pipeline dimensions (keeps final_score comparable to the pipeline)."""
    keys = ("ats", "impact", "skills_gap", "readability")
    return round(sum(flat.get(k, 0) for k in keys) / len(keys))


async def apply_edit(user: User, session: ChatSession, arguments: dict) -> dict:
    """Apply a targeted, user-instructed edit via the optimizer agent.

    Source: session last_result if present, else the saved Profile named by profile_id.
    Result always written back to session.context["last_result"].
    Returns the resume_edited event payload.
    """
    from profiles.router import _parse_sections  # lazy: avoids heavy import at module load

    instruction = (arguments.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="Tell me what you'd like to change.")

    ctx = dict(session.context or {})
    last_result = ctx.get("last_result")

    # Block edits while an optimization is still running (launched but no result yet).
    if ctx.get("_optimizer_launched") and not last_result:
        raise HTTPException(
            status_code=409,
            detail="An optimization is in progress — wait for it to finish before making manual edits.",
        )

    # ── Resolve source text + pre-edit scores ────────────────────────────────
    if last_result:
        source_text = last_result.get("optimized_text") or sections_to_text(last_result.get("sections") or {})
        scores_before = {**_flat_scores({}), **(last_result.get("scores") or {})}
    else:
        profile_id = str(arguments.get("profile_id", "") or "")
        try:
            pid = uuid.UUID(profile_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Nothing to edit yet — run the optimizer first, or tell me which saved profile to update.",
            )
        async with AsyncSessionLocal() as db:
            prof = await db.scalar(
                select(Profile).where(Profile.id == pid, Profile.user_id == user.id)
            )
            if not prof:
                raise HTTPException(
                    status_code=400,
                    detail="Couldn't find that profile. Please pick one from the list.",
                )
            source_text = prof.raw_text or sections_to_text(prof.sections or {})
        scores_before = None  # computed below from baseline scoring

    if not source_text.strip():
        raise HTTPException(status_code=400, detail="That resume has no text to edit.")

    jd_text = ctx.get("jd_text", "") or ""

    # ── Phase-1-lite: claims, JD analysis, baseline scoring ──────────────────
    ledger = await asyncio.to_thread(extract_claims, source_text)
    if jd_text:
        jd_dict = await analyze_jd(jd_text)
        jd_result = jd_dict.get("text", jd_dict) or {}
    else:
        jd_result = {}
    jd_keywords = jd_result.get("keywords", []) or []
    seniority = jd_result.get("seniority_level", "mid")
    required_hard_skills = jd_result.get("required_hard_skills", []) or []

    baseline_dict = await score_combined(
        source_text, jd_text, jd_keywords=jd_keywords,
        seniority_level=seniority, required_hard_skills=required_hard_skills,
    )
    baseline_scores = baseline_dict.get("text", {}) or {}
    if scores_before is None:
        scores_before = _flat_scores(baseline_scores)

    # ── Run the agent with the user's instruction injected ───────────────────
    sections = detect_sections(source_text)
    available_metrics = ", ".join(sorted(ledger.metrics)[:15]) if (ledger and ledger.metrics) else ""
    state = ResumeState(sections=sections, available_metrics=available_metrics)

    agent_result = await run_agent(
        state=state,
        scores=baseline_scores,
        jd_text=jd_text,
        jd_keywords=jd_keywords,
        ledger=ledger,
        original_resume=source_text,
        seniority_level=seniority,
        required_hard_skills=required_hard_skills,
        user_instruction=instruction,
        max_reflections=2,
    )

    edited_text = (agent_result.get("text") or "").strip()
    if not edited_text or edited_text == source_text.strip():
        raise HTTPException(
            status_code=422,
            detail="The edit produced no change — your resume is unchanged.",
        )

    verifier_flagged = agent_result.get("flagged", []) or []

    # ── Re-score the edited draft (hits PR-3 result cache when unchanged) ─────
    new_dict = await score_combined(
        edited_text, jd_text, jd_keywords=jd_keywords,
        seniority_level=seniority, required_hard_skills=required_hard_skills,
    )
    new_scores = new_dict.get("text", {}) or {}
    new_flat = _flat_scores(new_scores)
    new_scores_for_report = {**new_scores, "average": _avg4(new_flat)}

    report = build_report(
        jd_result=jd_result,
        original_text=source_text,
        optimized_text=edited_text,
        baseline_score=_avg4(scores_before),
        final_scores=new_scores_for_report,
        iterations=agent_result.get("iterations", 1),
    )

    # ── Re-parse edited text into rich profile sections (for save/docx) ───────
    new_sections = await _parse_sections(edited_text)

    sections_changed = list((report.get("section_diff") or {}).keys())

    # ── Write back to session.context["last_result"] ─────────────────────────
    async with AsyncSessionLocal() as db:
        sess_row = await db.get(ChatSession, session.id)
        if sess_row:
            new_ctx = dict(sess_row.context or {})
            prev = dict(new_ctx.get("last_result") or {})
            prev.update({
                "sections":        new_sections or {},
                "optimized_text":  edited_text,
                "final_score":     float(new_scores_for_report["average"]),
                "scores":          new_flat,
                "report":          report,
                "verifier_flagged": list(verifier_flagged),
            })
            new_ctx["last_result"] = prev
            sess_row.context = new_ctx
            sess_row.updated_at = datetime.now(timezone.utc)
            await db.commit()

    return {
        "sections_changed": sections_changed,
        "scores":           new_flat,
        "scores_before":    scores_before,
        "verifier_flagged": list(verifier_flagged),
    }
```

Add `import asyncio` at the top of `chat/handoff.py` if not already present (it is — confirm).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py::test_apply_edit_last_result_source_writes_back -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/chat/handoff.py resume-optimizer/backend/tests/test_pr7_edit_resume.py
git commit -m "feat(chat): apply_edit handler — source resolution + write-back (PR-7 T4)"
```

---

## Task 5: `apply_edit` — profile source + precondition errors

**Files:**
- Test only: `resume-optimizer/backend/tests/test_pr7_edit_resume.py` (the handler from Task 4 already implements these paths; this task verifies them and fixes any gaps found)

- [ ] **Step 1: Write the failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_apply_edit_profile_source(db_tables):
    """No last_result → edit the saved profile named by profile_id."""
    from chat import handoff
    from db.models import Profile
    from db.session import AsyncSessionLocal

    user, sess = await _make_user_and_session({})  # no jd, no last_result
    async with AsyncSessionLocal() as db:
        prof = Profile(
            id=uuid.uuid4(), user_id=user.id, label="Data Engineer",
            raw_text="SUMMARY\nGeneric summary.\n\nSKILLS\nPython, SQL.",
            sections={"summary": "Generic summary."},
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        db.add(prof)
        await db.commit()
        pid = str(prof.id)

    agent_ret = {"text": "SUMMARY\nTighter summary.\n\nSKILLS\nPython, SQL.",
                 "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0,
                 "iterations": 1, "flagged": []}

    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores(
             {"ats": 80, "impact": 80, "skills_gap": 80, "readability": 90, "jd_tailoring": 60}))), \
         patch.object(handoff, "extract_claims", return_value=None), \
         patch.object(handoff, "_parse_sections", AsyncMock(return_value={"summary": "Tighter summary."})):
        result = await handoff.apply_edit(user, sess, {"instruction": "Shorten the summary.", "profile_id": pid})

    assert result["scores"]["readability"] == 90
    # result lands in the session, not mutating the profile row
    from db.models import ChatSession
    async with AsyncSessionLocal() as db:
        row = await db.get(ChatSession, sess.id)
        assert row.context["last_result"]["optimized_text"] == agent_ret["text"]


@pytest.mark.asyncio
async def test_apply_edit_no_source_returns_400(db_tables):
    from chat import handoff
    from fastapi import HTTPException
    user, sess = await _make_user_and_session({})
    with pytest.raises(HTTPException) as exc:
        await handoff.apply_edit(user, sess, {"instruction": "Fix it."})
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_apply_edit_blocked_during_active_optimization(db_tables):
    from chat import handoff
    from fastapi import HTTPException
    user, sess = await _make_user_and_session({"_optimizer_launched": True})  # no last_result yet
    with pytest.raises(HTTPException) as exc:
        await handoff.apply_edit(user, sess, {"instruction": "Fix it."})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_edit_empty_output_returns_422(db_tables):
    from chat import handoff
    from fastapi import HTTPException
    ctx = {"last_result": {"optimized_text": "SUMMARY\nSame text.", "sections": {}, "scores": {}}}
    user, sess = await _make_user_and_session(ctx)
    agent_ret = {"text": "SUMMARY\nSame text.", "flagged": [], "iterations": 1,
                 "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores({"ats": 80}))), \
         patch.object(handoff, "extract_claims", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await handoff.apply_edit(user, sess, {"instruction": "no-op"})
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_apply_edit_fabrication_flagged_still_writes_back(db_tables):
    from chat import handoff
    from db.models import ChatSession
    from db.session import AsyncSessionLocal
    ctx = {"last_result": {"optimized_text": "SUMMARY\nReal text.", "sections": {}, "scores": {"ats": 70}}}
    user, sess = await _make_user_and_session(ctx)
    agent_ret = {"text": "SUMMARY\nEdited text.", "flagged": ["Managed a team of 20"],
                 "iterations": 1, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}
    with patch.object(handoff, "run_agent", AsyncMock(return_value=agent_ret)), \
         patch.object(handoff, "score_combined", AsyncMock(return_value=_fake_scores({"ats": 75}))), \
         patch.object(handoff, "extract_claims", return_value=None), \
         patch.object(handoff, "_parse_sections", AsyncMock(return_value={"summary": "Edited text."})):
        result = await handoff.apply_edit(user, sess, {"instruction": "Add team leadership."})
    assert result["verifier_flagged"] == ["Managed a team of 20"]
    async with AsyncSessionLocal() as db:
        row = await db.get(ChatSession, sess.id)
        assert row.context["last_result"]["verifier_flagged"] == ["Managed a team of 20"]
```

- [ ] **Step 2: Run tests**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -k apply_edit -v`
Expected: all PASS. If any fail, fix `apply_edit` in `chat/handoff.py` to satisfy the asserted behaviour (do not weaken the tests).

- [ ] **Step 3: Commit**

```bash
git add resume-optimizer/backend/chat/handoff.py resume-optimizer/backend/tests/test_pr7_edit_resume.py
git commit -m "test(chat): apply_edit profile source + precondition errors (PR-7 T5)"
```

---

## Task 6: Router wiring — quota check, counter increment, dispatch branch

**Files:**
- Modify: `resume-optimizer/backend/chat/router.py` (import ~line 18; add `_check_edit_quota` + `_increment_edit_counter` near `_check_quota` ~line 279; dispatch in `event_generator` ~line 427-450)
- Test: `resume-optimizer/backend/tests/test_pr7_edit_resume.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
# ── Group 5: router quota helpers ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_edit_quota_blocks_when_over(db_tables):
    from chat import router
    from db.models import User, PlanType, PlanLimit, DailyUsageCounter
    from db.session import AsyncSessionLocal
    from fastapi import HTTPException
    from datetime import date

    async with AsyncSessionLocal() as db:
        db.add(PlanLimit(plan="free", daily_uploads=2, daily_edits=3,
                         max_stored_resumes=1, job_scraping_enabled=False, price_cents=0))
        user = User(id=uuid.uuid4(), email=f"q-{uuid.uuid4().hex[:8]}@t.com",
                    hashed_password="x", plan=PlanType.free)
        db.add(user)
        db.add(DailyUsageCounter(user_id=user.id, date=date.today().isoformat(), runs=0, edits=3))
        await db.commit()
        await db.refresh(user)

    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await router._check_edit_quota(user, db)
        assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_increment_edit_counter(db_tables):
    from chat import router
    from db.models import User, PlanType, DailyUsageCounter
    from db.session import AsyncSessionLocal
    from sqlalchemy import select
    from datetime import date

    async with AsyncSessionLocal() as db:
        user = User(id=uuid.uuid4(), email=f"i-{uuid.uuid4().hex[:8]}@t.com",
                    hashed_password="x", plan=PlanType.free)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    async with AsyncSessionLocal() as db:
        await router._increment_edit_counter(str(user.id), db)
        await router._increment_edit_counter(str(user.id), db)

    async with AsyncSessionLocal() as db:
        n = await db.scalar(select(DailyUsageCounter.edits).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == date.today().isoformat()))
        assert n == 2


def test_router_imports_edit_tool_and_apply_edit():
    import inspect
    from chat import router
    src = inspect.getsource(router)
    assert "EDIT_TOOL" in src
    assert "apply_edit" in src
    assert "resume_edited" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -k "edit_quota or increment_edit or router_imports" -v`
Expected: FAIL — helpers/imports absent.

- [ ] **Step 3: Update the router import**

In `chat/router.py` line 18, add `EDIT_TOOL` and `apply_edit`:

```python
from chat.tools import TOOLS, LAUNCH_TOOL, SAVE_TOOL, DOWNLOAD_TOOL, EDIT_TOOL, parse_tool_calls, message_text
from chat.handoff import fire_optimizer, save_profile_from_session, resolve_profile_download, apply_edit
```

- [ ] **Step 4: Add quota helpers**

After `_check_quota` (~line 308) in `chat/router.py`:

```python
async def _check_edit_quota(user: User, db: AsyncSession) -> None:
    """Raise HTTP 429 if the user has hit their daily edit limit (separate from pipeline runs)."""
    from auth.dependencies import _effective_plan
    from datetime import date

    plan = _effective_plan(user)
    limits = await db.scalar(select(PlanLimit).where(PlanLimit.plan == plan))
    if not limits:
        return

    today_str = date.today().isoformat()
    used = await db.scalar(
        select(DailyUsageCounter.edits).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    ) or 0

    if used >= limits.daily_edits:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "edit_limit_reached",
                "limit": limits.daily_edits,
                "used": used,
                "upgrade_message": "You've reached your daily edit limit. Upgrade to Pro for more edits.",
            },
        )


async def _increment_edit_counter(user_id: str, db: AsyncSession) -> None:
    """Increment today's edit counter for the user (upsert)."""
    from datetime import date
    await db.execute(
        text(
            "INSERT INTO daily_usage_counters (user_id, date, runs, edits) "
            "VALUES (:uid, :date, 0, 1) "
            "ON CONFLICT (user_id, date) DO UPDATE "
            "SET edits = daily_usage_counters.edits + 1"
        ),
        {"uid": user_id, "date": date.today().isoformat()},
    )
    await db.commit()
```

`text` is already imported in `chat/router.py`? Confirm — `from sqlalchemy import func, select` is present; add `text`:
change that import line to `from sqlalchemy import func, select, text`.

Note: the SQLite test engine in `db.session` must support `ON CONFLICT` on the `(user_id, date)` unique constraint — it does (the constraint is `uq_user_date`). The same upsert pattern is already used by `main.py`.

- [ ] **Step 5: Add the dispatch branch**

In `event_generator`, after the `download = next(...)` line (~line 429), add:

```python
        edit = next((c for c in tool_calls if c["name"] == EDIT_TOOL), None)
```

Update the display synthesis block (~line 444) to include editing:

```python
        display = text or (
            "Launching the optimizer now…" if launch
            else "Generating your document…" if download
            else "Saving your profile…" if save
            else "Editing your resume…" if edit
            else "Sorry, I didn't catch that. Could you rephrase?"
        )
```

Add a new dispatch branch alongside the others (after the `elif save:` block, ~line 504, before the final `yield {"event": "done", ...}`):

```python
        # ── Targeted user-instructed edit ───────────────────────────────────
        elif edit:
            try:
                await _check_edit_quota(current_user, db)
            except HTTPException as exc:
                detail = exc.detail
                msg = (detail.get("upgrade_message", "Daily edit limit reached.")
                       if isinstance(detail, dict) else str(detail))
                yield {"event": "error", "data": json.dumps({"message": msg})}
                yield {"event": "done", "data": json.dumps({"session_id": session_id_str})}
                return
            try:
                edit_result = await apply_edit(current_user, session, edit["arguments"])
                async with AsyncSessionLocal() as wdb:
                    await _increment_edit_counter(str(current_user.id), wdb)
                yield {"event": "resume_edited", "data": json.dumps(edit_result)}
            except HTTPException as exc:
                msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                yield {"event": "error", "data": json.dumps({"message": msg})}
```

Because this is `elif`, place it in the existing `if launch: … elif download: … elif save: …` chain (it becomes `… elif edit:`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -k "edit_quota or increment_edit or router_imports" -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/chat/router.py resume-optimizer/backend/tests/test_pr7_edit_resume.py
git commit -m "feat(chat): router edit_resume dispatch + edit quota (PR-7 T6)"
```

---

## Task 7: Co-pilot system prompt guidance

**Files:**
- Modify: `resume-optimizer/backend/chat/agent.py` (`_SYSTEM_PROMPT`, tools list ~line 18, add a new behaviour block)
- Test: `resume-optimizer/backend/tests/test_pr7_edit_resume.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
# ── Group 6: co-pilot prompt guidance ────────────────────────────────────────

def test_system_prompt_has_edit_guidance():
    import inspect
    from chat import agent
    src = inspect.getsource(agent)
    assert "edit_resume" in src
    assert "RESUME EDITS" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py::test_system_prompt_has_edit_guidance -v`
Expected: FAIL.

- [ ] **Step 3: Add the tool to the tools list and a behaviour block**

In `chat/agent.py`, in the `YOU HAVE THREE TOOLS` list, change the heading to `YOU HAVE FOUR TOOLS` and add a fourth bullet:

```
- edit_resume(instruction, profile_id): apply a targeted, user-requested change to the resume \
text (remove a bullet, shorten the summary, reorder skills, fix tone). Pass the user's request \
verbatim as instruction. If no optimization has run this session and the user has multiple \
profiles, ask which profile to edit and pass its id as profile_id.
```

After the `WHEN ASKED ABOUT THE OPTIMIZATION PROCESS` block, add:

```
WHEN THE USER ASKS FOR RESUME EDITS:
Call edit_resume(instruction) with exactly what the user asked for — verbatim detail only, no \
interpretation or invention. If there is no optimized result yet and multiple profiles exist, ask \
which profile to edit before calling. After it completes, summarize: which sections changed, the \
score delta (before → after), and any fabrication flags. If a claim was flagged: "The verifier \
flagged that — it wasn't supported by your original resume, so I didn't keep it." Do NOT call \
edit_resume for score discussions or explanations — only when the user wants the resume TEXT changed.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py::test_system_prompt_has_edit_guidance -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/chat/agent.py resume-optimizer/backend/tests/test_pr7_edit_resume.py
git commit -m "feat(chat): co-pilot edit_resume guidance (PR-7 T7)"
```

---

## Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the new test file**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr7_edit_resume.py -v`
Expected: all PASS (~16 tests).

- [ ] **Step 2: Run the chat + agent regression suites**

Run: `cd resume-optimizer/backend && python -m pytest tests/test_pr6_jd_tailoring.py tests/test_chat_agent.py tests/test_chat_sessions.py tests/test_stream_chat.py -v`
Expected: all PASS — no regressions from the `run_agent`, `router`, or `agent.py` changes.

- [ ] **Step 3: Run the entire backend suite**

Run: `cd resume-optimizer/backend && python -m pytest -q`
Expected: all PASS.

- [ ] **Step 4: Commit any fixups**

If Steps 1-3 surfaced regressions, fix them and commit:

```bash
git add -A
git commit -m "fix(pr7): resolve regressions from edit_resume integration"
```

---

## Self-Review

**Spec coverage:**
- New chat tool `edit_resume(instruction, profile_id?)` → Task 3 ✓
- Source resolution (last_result vs Profile) → Task 4 (last_result), Task 5 (profile) ✓
- Agent execution with injected instruction + max 2 reflections + standard driver → Task 2 (params), Task 4 (call with `max_reflections=2`) ✓
- Post-processing: fabrication guard (runs inside `run_agent`, returned via `flagged`) + re-score + build_report → Task 2 (flagged), Task 4 ✓
- Write-back to `last_result` (sections, optimized_text, report, verifier_flagged) → Task 4 ✓
- `resume_edited` SSE event with sections_changed/scores/scores_before/verifier_flagged → Task 4 (payload), Task 6 (emit) ✓
- Co-pilot guidance block → Task 7 ✓
- Edit quota (PlanLimit.daily_edits, DailyUsageCounter.edits, `_check_edit_quota`, increment, migration) → Task 1, Task 6 ✓
- Error handling: no source 400, empty output 422, fabrication non-blocking, no-JD, active-optimization 409, quota 429 → Tasks 4/5/6 ✓
- All 11 spec test scenarios are covered across Tasks 1-7 ✓

**Deviations from spec (intentional, noted for the reviewer):**
- Spec described `run_optimization_async(state, …, plan="standard", max_iterations=2, user_instruction=…)`. That signature does not exist; the real driver is `run_agent`. The plan injects the instruction into `run_agent` directly (matching the spec's file-change table, which lists `agent_loop.py`). The reflection-count override is named `max_reflections` (the outer "pass" loop), set to 2.
- Spec's empty-output case said "keep original, error." Implemented as HTTP 422 with an unchanged session — same user-visible outcome.
- Active-optimization block returns 409 (semantically correct for a conflicting in-progress operation); spec said "SSE error" without a code.
- `last_result["scores"]` now stores all 5 dimensions for edited results (the pipeline stores 4); `final_score`/`average` still uses the 4-dimension mean to stay comparable to pipeline scores.

**Placeholder scan:** none — every code step contains complete code.

**Type consistency:** `apply_edit(user, session, arguments)`, `_check_edit_quota(user, db)`, `_increment_edit_counter(user_id, db)`, `run_agent(..., user_instruction=, max_reflections=)`, `result["flagged"]` — names consistent across Tasks 2/4/5/6 and the tests.

**Verification-first caveats baked into the plan:** Tasks 2 and 4 instruct the implementer to confirm `ClaimsLedger` field names and `User`/`PlanType` columns before finalizing the test fixtures, since those are constructed directly in tests.

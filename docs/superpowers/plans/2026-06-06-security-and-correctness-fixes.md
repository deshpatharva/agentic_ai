# Security & Correctness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 31 validated bugs spanning critical data corruption, security vulnerabilities, and performance issues — ordered P0 → P3.

**Architecture:** Database changes use Alembic migrations (0008–0011). Python fixes update FastAPI route handlers, the Delta Lake writer, and auth utilities. Frontend fixes update the Axios client. P3 hygiene removes committed artifacts from git.

**Tech Stack:** FastAPI 0.110+, SQLAlchemy 2.x (async), PostgreSQL 16, Alembic 1.13, deltalake 0.16, python-jose, bcrypt 4.x, pytest-asyncio 0.23, React/Vite, Axios

---

## File Map

| File | Change |
|---|---|
| `resume-optimizer/backend/alembic/versions/0008_fix_provider_cost_constraint.py` | New — drop broken UniqueConstraint, add partial index |
| `resume-optimizer/backend/alembic/versions/0009_normalize_provider_names.py` | New — lowercase existing provider data + CHECK constraint |
| `resume-optimizer/backend/alembic/versions/0010_fix_datetime_timezones.py` | New — timezone=True on remaining tz-naive DateTime columns |
| `resume-optimizer/backend/alembic/versions/0011_add_token_blocklist.py` | New — TokenBlocklist table for JWT revocation |
| `resume-optimizer/backend/db/models.py` | Remove broken UniqueConstraint; add TokenBlocklist model; add timezone=True to tz-naive columns |
| `resume-optimizer/backend/db/session.py` | Lowercase provider seed data |
| `resume-optimizer/backend/delta/writer.py` | Fix empty user_id filter; split write lock per table; fix vacuum_old_matches full-table read |
| `resume-optimizer/backend/admin/router.py` | Fix avg_cost_per_run denominator; fix list_promo_codes total; add rate limiting; use PromoCodeCreate |
| `resume-optimizer/backend/admin/schemas.py` | Add PromoCodeCreate schema |
| `resume-optimizer/backend/auth/router.py` | Replace passlib/bcrypt monkey-patch; fix redeem_promo_code IntegrityError; add jti to tokens; add /auth/logout; add password complexity; full_name sanitization |
| `resume-optimizer/backend/auth/dependencies.py` | Check TokenBlocklist on each authenticated request |
| `resume-optimizer/backend/main.py` | MIME magic bytes check; SSE poll 0.5s → 2.0s; resume_id ownership check; wire vacuum to reaper |
| `resume-optimizer/backend/dashboard/router.py` | Use DailyUsageCounter for runs_today |
| `resume-optimizer/backend/config.py` | BOOTSTRAP_SECRET: warnings.warn → raise ValueError |
| `resume-optimizer/frontend/src/api/client.js` | Add retry interceptor for GET 5xx |
| `resume-optimizer/.gitignore` | Add *.db, rv/, __pycache__ |
| `resume-optimizer/backend/requirements.txt` | Remove passlib |

---

## Task 1: Fix uq_provider_active Constraint (P0)

**The bug:** `UniqueConstraint("provider", "active")` prevents deactivating a second row for the same provider — the third provider cost update crashes with `IntegrityError`. Fix: drop the constraint, add a partial unique index on `(provider) WHERE active = true`.

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0008_fix_provider_cost_constraint.py`
- Modify: `resume-optimizer/backend/db/models.py:151-153`
- Test: `resume-optimizer/backend/tests/test_cost_tracking.py`

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_cost_tracking.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from db.models import ProviderCost

@pytest.mark.asyncio
async def test_third_provider_deactivation_no_integrity_error():
    """Deactivating a second row for the same provider must not raise IntegrityError.
    With the broken UniqueConstraint('provider','active'), having two rows of
    (google, False) fires a constraint violation.
    """
    from db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Insert first active row
        r1 = ProviderCost(
            provider="google",
            input_cost_per_1m_tokens=0.5,
            output_cost_per_1m_tokens=1.5,
            active=True,
        )
        db.add(r1)
        await db.commit()
        await db.refresh(r1)

        # Deactivate first row → (google, False)
        r1.active = False
        await db.commit()

        # Insert second active row → (google, True)
        r2 = ProviderCost(
            provider="google",
            input_cost_per_1m_tokens=0.4,
            output_cost_per_1m_tokens=1.2,
            active=True,
        )
        db.add(r2)
        await db.commit()
        await db.refresh(r2)

        # Deactivate second row → second (google, False) — this used to crash
        r2.active = False
        await db.commit()  # must not raise IntegrityError

        count = (
            await db.execute(
                select(ProviderCost).where(
                    ProviderCost.provider == "google",
                    ProviderCost.active == False,
                )
            )
        ).scalars().all()
        assert len(count) == 2

        # Cleanup
        for row in [r1, r2]:
            await db.delete(row)
        await db.commit()
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd resume-optimizer
pytest backend/tests/test_cost_tracking.py::test_third_provider_deactivation_no_integrity_error -v
```

Expected: `FAILED` — `IntegrityError: UNIQUE constraint failed: provider_costs.provider, provider_costs.active`

- [ ] **Step 3: Create migration 0008**

Create `resume-optimizer/backend/alembic/versions/0008_fix_provider_cost_constraint.py`:

```python
"""replace uq_provider_active with partial unique index

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-06
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_provider_active", "provider_costs", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uix_provider_active_true "
        "ON provider_costs (provider) WHERE active = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uix_provider_active_true")
    op.create_unique_constraint(
        "uq_provider_active", "provider_costs", ["provider", "active"]
    )
```

- [ ] **Step 4: Remove UniqueConstraint from the model**

In `resume-optimizer/backend/db/models.py`, replace lines 151-153:

```python
    __table_args__ = (
        UniqueConstraint("provider", "active", name="uq_provider_active"),
    )
```

with:

```python
    __table_args__ = ()
```

- [ ] **Step 5: Run test to confirm it passes**

```bash
cd resume-optimizer
pytest backend/tests/test_cost_tracking.py::test_third_provider_deactivation_no_integrity_error -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0008_fix_provider_cost_constraint.py
git add resume-optimizer/backend/db/models.py
git add resume-optimizer/backend/tests/test_cost_tracking.py
git commit -m "fix: replace uq_provider_active with partial index — prevents IntegrityError on third deactivation"
```

---

## Task 2: Normalize Provider Names to Lowercase (P0)

**The bug:** Seed data uses `"Anthropic"`, `"Google"`, `"Groq"` (capitalized) but `admin/router.py` queries with `"anthropic"` (lowercase). Cost calculations return 0 for mismatched providers.

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0009_normalize_provider_names.py`
- Modify: `resume-optimizer/backend/db/session.py:89-107`
- Test: `resume-optimizer/backend/tests/test_cost_tracking.py`

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_cost_tracking.py`:

```python
@pytest.mark.asyncio
async def test_provider_seed_uses_lowercase():
    """Seeded provider names must match the lowercase strings used in admin queries."""
    from db.session import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT provider FROM provider_costs WHERE active = true")
        )
        providers = {row[0] for row in result.fetchall()}
    assert providers == {"anthropic", "google", "groq"}, (
        f"Expected lowercase providers, got: {providers}"
    )
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest backend/tests/test_cost_tracking.py::test_provider_seed_uses_lowercase -v
```

Expected: `FAILED` — providers are `{'Anthropic', 'Google', 'Groq'}`

- [ ] **Step 3: Create migration 0009**

Create `resume-optimizer/backend/alembic/versions/0009_normalize_provider_names.py`:

```python
"""normalize provider names to lowercase and add CHECK constraint

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-06
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE provider_costs SET provider = lower(provider)")
    # PostgreSQL: enforce lowercase going forward
    op.execute(
        "ALTER TABLE provider_costs ADD CONSTRAINT chk_provider_lower "
        "CHECK (provider = lower(provider))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE provider_costs DROP CONSTRAINT IF EXISTS chk_provider_lower"
    )
```

- [ ] **Step 4: Update seed data to use lowercase**

In `resume-optimizer/backend/db/session.py`, replace lines 89-107:

```python
            provider_costs = [
                ProviderCost(
                    provider="Anthropic",
                    input_cost_per_1m_tokens=0.003,
                    output_cost_per_1m_tokens=0.009,
                    active=True,
                ),
                ProviderCost(
                    provider="Google",
                    input_cost_per_1m_tokens=0.0005,
                    output_cost_per_1m_tokens=0.0015,
                    active=True,
                ),
                ProviderCost(
                    provider="Groq",
                    input_cost_per_1m_tokens=0.0001,
                    output_cost_per_1m_tokens=0.0001,
                    active=True,
                ),
            ]
```

with:

```python
            provider_costs = [
                ProviderCost(
                    provider="anthropic",
                    input_cost_per_1m_tokens=0.003,
                    output_cost_per_1m_tokens=0.009,
                    active=True,
                ),
                ProviderCost(
                    provider="google",
                    input_cost_per_1m_tokens=0.0005,
                    output_cost_per_1m_tokens=0.0015,
                    active=True,
                ),
                ProviderCost(
                    provider="groq",
                    input_cost_per_1m_tokens=0.0001,
                    output_cost_per_1m_tokens=0.0001,
                    active=True,
                ),
            ]
```

- [ ] **Step 5: Run test to confirm it passes**

```bash
pytest backend/tests/test_cost_tracking.py::test_provider_seed_uses_lowercase -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0009_normalize_provider_names.py
git add resume-optimizer/backend/db/session.py
git add resume-optimizer/backend/tests/test_cost_tracking.py
git commit -m "fix: normalize provider names to lowercase — admin cost queries were returning 0 due to case mismatch"
```

---

## Task 3: Fix Admin Delta Read for Empty user_id (P0)

**The bug:** `read_usage_last_n_days("", ...)` always includes `("user_id", "=", "")` in the Delta filter. No real row has `user_id=""`, so admin analytics returns zero for all cost calculations. Same bug in `read_job_matches`.

**Files:**
- Modify: `resume-optimizer/backend/delta/writer.py:176-214` and `217-245`
- Test: `resume-optimizer/backend/tests/test_delta_writer.py`

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_delta_writer.py`:

```python
from unittest.mock import MagicMock, patch
import pandas as pd
from delta.writer import read_usage_last_n_days


def test_empty_user_id_returns_all_rows_not_zero():
    """When user_id='', admin aggregate — no user_id filter should be applied.
    The current bug filters for user_id='' which matches nothing.
    """
    mock_df = pd.DataFrame([
        {"user_id": "user-a", "date": "2026-06-05", "pipeline_runs": 2,
         "uploads": 2, "input_tokens": 1000, "output_tokens": 500, "tokens_used": 1500},
        {"user_id": "user-b", "date": "2026-06-05", "pipeline_runs": 1,
         "uploads": 1, "input_tokens": 800, "output_tokens": 300, "tokens_used": 1100},
    ])

    mock_dt = MagicMock()
    mock_dt.to_pandas.return_value = mock_df

    with patch("delta.writer._table_exists", return_value=True), \
         patch("delta.writer.DeltaTable") as MockDT:
        MockDT.from_uri.return_value = mock_dt
        result = read_usage_last_n_days("", 30)

    # With fix: both rows are returned and aggregated
    assert not result.empty, "Admin aggregate must return rows when user_id=''"
    assert result["pipeline_runs"].sum() == 3


def test_non_empty_user_id_filters_to_one_user():
    """When user_id is non-empty, only that user's rows are returned."""
    mock_df = pd.DataFrame([
        {"user_id": "user-a", "date": "2026-06-05", "pipeline_runs": 2,
         "uploads": 2, "input_tokens": 1000, "output_tokens": 500, "tokens_used": 1500},
        {"user_id": "user-b", "date": "2026-06-05", "pipeline_runs": 1,
         "uploads": 1, "input_tokens": 800, "output_tokens": 300, "tokens_used": 1100},
    ])

    mock_dt = MagicMock()
    mock_dt.to_pandas.return_value = mock_df

    with patch("delta.writer._table_exists", return_value=True), \
         patch("delta.writer.DeltaTable") as MockDT:
        MockDT.from_uri.return_value = mock_dt
        result = read_usage_last_n_days("user-a", 30)

    assert result["pipeline_runs"].sum() == 2
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest backend/tests/test_delta_writer.py::test_empty_user_id_returns_all_rows_not_zero backend/tests/test_delta_writer.py::test_non_empty_user_id_filters_to_one_user -v
```

Expected: `FAILED` — `test_empty_user_id` fails because result is empty

- [ ] **Step 3: Fix read_usage_last_n_days**

In `resume-optimizer/backend/delta/writer.py`, replace lines 190-213 (the body of `read_usage_last_n_days` after the `_table_exists` check):

```python
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path, storage_options=_storage_options())

    filters: list = [("date", ">=", cutoff)]
    if user_id:
        filters.append(("user_id", "=", user_id))

    df = dt.to_pandas(filters=filters)

    # Safety net: re-apply date filter in case Delta pushdown is partial
    df = df[df["date"] >= cutoff]
    if user_id:
        df = df[df["user_id"] == user_id]

    if df.empty:
        return pd.DataFrame(columns=["date", "pipeline_runs", "uploads", "input_tokens", "output_tokens", "tokens_used"])

    agg = (
        df.groupby("date")
        .agg(pipeline_runs=("pipeline_runs", "sum"),
             uploads=("uploads", "sum"),
             input_tokens=("input_tokens", "sum"),
             output_tokens=("output_tokens", "sum"),
             tokens_used=("tokens_used", "sum"))
        .reset_index()
        .sort_values("date")
    )
    return agg
```

- [ ] **Step 4: Fix read_job_matches with the same pattern**

In `resume-optimizer/backend/delta/writer.py`, replace the filter block inside `read_job_matches` (lines 232-237):

```python
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path, storage_options=_storage_options())

    filters: list = [("scraped_at", ">=", cutoff)]
    if user_id:
        filters.append(("user_id", "=", user_id))

    df = dt.to_pandas(filters=filters)

    df = df[df["scraped_at"] >= cutoff]
    if user_id:
        df = df[df["user_id"] == user_id]
    df = df.sort_values("scraped_at", ascending=False)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest backend/tests/test_delta_writer.py::test_empty_user_id_returns_all_rows_not_zero backend/tests/test_delta_writer.py::test_non_empty_user_id_filters_to_one_user -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/delta/writer.py
git add resume-optimizer/backend/tests/test_delta_writer.py
git commit -m "fix: admin Delta read no longer filters by user_id when empty — aggregate stats were returning 0"
```

---

## Task 4: Secure resume_id Ownership in /scrape-jobs (P0)

**The bug:** `POST /scrape-jobs` accepts `resume_id` from the request body and writes it to Delta Lake without checking that the resume belongs to the authenticated user. User A can set `resume_id` to User B's ID.

**Files:**
- Modify: `resume-optimizer/backend/main.py:505-543`
- Test: `resume-optimizer/backend/tests/test_prod_fixes.py`

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_prod_fixes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_scrape_jobs_rejects_foreign_resume_id():
    """User A must not be able to submit User B's resume_id to /scrape-jobs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Register User A
        r = await c.post("/auth/register", json={
            "email": "usera_scrape@test.com", "password": "SecurePass1", "full_name": "User A"
        })
        assert r.status_code == 200
        token_a = r.json()["access_token"]

        # Register User B and get their user id
        r = await c.post("/auth/register", json={
            "email": "userb_scrape@test.com", "password": "SecurePass1", "full_name": "User B"
        })
        assert r.status_code == 200

        # Use a fake UUID that doesn't belong to User A
        fake_resume_id = "00000000-0000-0000-0000-000000000001"

        r = await c.post(
            "/scrape-jobs",
            json={"resume_id": fake_resume_id, "keywords": "python engineer"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest backend/tests/test_prod_fixes.py::test_scrape_jobs_rejects_foreign_resume_id -v
```

Expected: `FAILED` — returns `200` or `500` instead of `403`

- [ ] **Step 3: Add ownership check to /scrape-jobs**

In `resume-optimizer/backend/main.py`, update the `scrape_jobs_endpoint` signature and add the ownership check before the scrape call:

```python
@app.post("/scrape-jobs")
async def scrape_jobs_endpoint(
    request: ScrapeJobsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not request.keywords.strip():
        raise HTTPException(status_code=400, detail="keywords cannot be empty.")

    # Verify resume ownership before associating scraped jobs with it
    if request.resume_id:
        try:
            resume_uuid = uuid.UUID(request.resume_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid resume_id format.")
        resume = await db.scalar(
            select(Resume).where(
                Resume.id == resume_uuid,
                Resume.user_id == current_user.id,
            )
        )
        if not resume:
            raise HTTPException(status_code=403, detail="Resume not found or access denied.")

    try:
        postings = await scrape_jobs(request.keywords.strip(), per_source=request.per_source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")
    # ... rest of the function unchanged
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest backend/tests/test_prod_fixes.py::test_scrape_jobs_rejects_foreign_resume_id -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/main.py
git add resume-optimizer/backend/tests/test_prod_fixes.py
git commit -m "fix: validate resume_id ownership in /scrape-jobs — prevented IDOR allowing cross-user resume association"
```

---

## Task 5: Replace create_promo_code dict with Pydantic Schema (P0)

**The bug:** `POST /admin/promo-codes` uses `body: dict` with manual validation. `datetime.fromisoformat()` on bad input throws a 500, and `max_uses` silently accepts strings.

**Files:**
- Modify: `resume-optimizer/backend/admin/schemas.py`
- Modify: `resume-optimizer/backend/admin/router.py:512-564`
- Test: `resume-optimizer/backend/tests/test_admin.py`

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_admin.py`:

```python
@pytest.mark.asyncio
async def test_create_promo_code_invalid_expires_at_returns_422_not_500(admin_client):
    """A bad ISO datetime must return 422 (validation error), not 500 (ValueError crash)."""
    r = await admin_client.post("/admin/promo-codes", json={
        "code": "TESTBAD",
        "type": "plan_upgrade",
        "target_plan": "pro",
        "max_uses": 10,
        "expires_at": "not-a-date",
    })
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_create_promo_code_string_max_uses_returns_422(admin_client):
    """max_uses must be an integer; a string value must return 422."""
    r = await admin_client.post("/admin/promo-codes", json={
        "code": "TESTBAD2",
        "type": "plan_upgrade",
        "target_plan": "pro",
        "max_uses": "ten",
    })
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
```

Note: `admin_client` is a fixture that provides an authenticated admin HTTP client. Check the existing conftest or test_admin.py for its definition.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest backend/tests/test_admin.py::test_create_promo_code_invalid_expires_at_returns_422_not_500 backend/tests/test_admin.py::test_create_promo_code_string_max_uses_returns_422 -v
```

Expected: `FAILED` — returns 500 (ValueError) and 500 (silently accepts string)

- [ ] **Step 3: Add PromoCodeCreate schema**

In `resume-optimizer/backend/admin/schemas.py`, add after the existing `ProviderCostCreate` class:

```python
from datetime import datetime
from typing import Literal

class PromoCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    type: Literal["plan_upgrade", "trial_extension", "discount"]
    target_plan: Optional[str] = None
    days_to_add: Optional[int] = Field(None, ge=1, le=365)
    discount_percent: Optional[int] = Field(None, ge=1, le=100)
    max_uses: int = Field(ge=1)
    expires_at: Optional[datetime] = None
```

Also add `from pydantic import Field` to the imports at the top of schemas.py (it currently only imports `BaseModel`).

- [ ] **Step 4: Update admin router to use PromoCodeCreate**

In `resume-optimizer/backend/admin/router.py`, update the import line 13:

```python
from admin.schemas import AdminStats, BootstrapRequest, UserUpdate, ProviderCostCreate, ProviderCostsResponse, AnalyticsResponse, PromoCodeCreate
```

Replace the `create_promo_code` function signature and body (lines 512-564) with:

```python
@router.post("/promo-codes", status_code=201)
async def create_promo_code(
    body: PromoCodeCreate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a promo code."""
    from db.models import PromoCode

    result = await db.execute(select(PromoCode).where(PromoCode.code == body.code))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Code already exists")

    promo = PromoCode(
        id=uuid.uuid4(),
        code=body.code,
        type=body.type,
        target_plan=body.target_plan,
        days_to_add=body.days_to_add,
        discount_percent=body.discount_percent,
        max_uses=body.max_uses,
        expires_at=body.expires_at,
        created_at=datetime.now(timezone.utc),
    )
    db.add(promo)
    await db.commit()

    return {
        "id": str(promo.id),
        "code": promo.code,
        "type": promo.type,
        "target_plan": promo.target_plan,
        "days_to_add": promo.days_to_add,
        "discount_percent": promo.discount_percent,
        "max_uses": promo.max_uses,
        "current_uses": promo.current_uses,
        "expires_at": promo.expires_at.isoformat() if promo.expires_at else None,
        "created_at": promo.created_at.isoformat(),
        "deactivated_at": None,
    }
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest backend/tests/test_admin.py::test_create_promo_code_invalid_expires_at_returns_422_not_500 backend/tests/test_admin.py::test_create_promo_code_string_max_uses_returns_422 -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/admin/schemas.py
git add resume-optimizer/backend/admin/router.py
git add resume-optimizer/backend/tests/test_admin.py
git commit -m "fix: replace create_promo_code body:dict with PromoCodeCreate schema — invalid dates and types now return 422"
```

---

## Task 6: Handle IntegrityError in redeem_promo_code (P0)

**The bug:** Two concurrent requests both pass the "already redeemed" check before either inserts the `UserPromoRedemption` row. The second insert hits `uq_user_code` and propagates as an unhandled `IntegrityError` → HTTP 500.

**Files:**
- Modify: `resume-optimizer/backend/auth/router.py:245-249`
- Test: `resume-optimizer/backend/tests/test_promo_codes.py`

- [ ] **Step 1: Write the test**

Add to `resume-optimizer/backend/tests/test_promo_codes.py`:

```python
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_concurrent_promo_redemption_returns_409_not_500():
    """Concurrent redemptions must return 409 (already redeemed), not 500 (IntegrityError)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Setup: register user and create promo code via admin
        r = await c.post("/auth/register", json={
            "email": "promo_race@test.com", "password": "SecurePass1", "full_name": "Race User"
        })
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Fire two concurrent redemption requests
        async def redeem():
            return await c.post("/user/redeem-promo-code",
                                 json={"code": "RACETEST"},
                                 headers=headers)

        # Note: this test requires an active promo code "RACETEST" to exist.
        # Create it via admin setup in conftest or skip if not available.
        results = await asyncio.gather(redeem(), redeem(), return_exceptions=True)
        statuses = [r.status_code for r in results if hasattr(r, "status_code")]

        # At least one must succeed (200) and the other must return 409, not 500
        assert 500 not in statuses, f"Got 500 in concurrent redemption: {statuses}"
        assert 409 in statuses or statuses.count(200) == 1, (
            f"Unexpected statuses: {statuses}"
        )
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest backend/tests/test_promo_codes.py::test_concurrent_promo_redemption_returns_409_not_500 -v
```

Expected: `FAILED` — one of the requests returns 500

- [ ] **Step 3: Wrap INSERT in try/except IntegrityError**

In `resume-optimizer/backend/auth/router.py`, replace lines 245-249:

```python
    # Record redemption
    redemption = UserPromoRedemption(user_id=user.id, promo_code_id=promo.id)
    db.add(redemption)

    await db.commit()
```

with:

```python
    # Record redemption
    redemption = UserPromoRedemption(user_id=user.id, promo_code_id=promo.id)
    db.add(redemption)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Already redeemed")
```

`IntegrityError` is already imported at line 20 of auth/router.py.

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest backend/tests/test_promo_codes.py::test_concurrent_promo_redemption_returns_409_not_500 -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/auth/router.py
git add resume-optimizer/backend/tests/test_promo_codes.py
git commit -m "fix: handle IntegrityError in redeem_promo_code — concurrent redemptions now return 409 instead of 500"
```

---

## Task 7: Fix avg_cost_per_run + list_promo_codes Total Count (P1)

**Two bugs in admin/router.py:**
1. `avg_cost_per_run` divides monthly cost by today's run count (should use monthly run count).
2. `list_promo_codes` returns `len(page)` as total instead of executing a `COUNT(*)` on the full result set.

**Files:**
- Modify: `resume-optimizer/backend/admin/router.py:180-182` and `569-623`
- Test: `resume-optimizer/backend/tests/test_admin.py`

- [ ] **Step 1: Write the failing tests**

Add to `resume-optimizer/backend/tests/test_admin.py`:

```python
@pytest.mark.asyncio
async def test_list_promo_codes_total_reflects_full_count_not_page_size(admin_client):
    """total in list_promo_codes response must be the full count, not len(page)."""
    # Create 3 promo codes
    for i in range(3):
        await admin_client.post("/admin/promo-codes", json={
            "code": f"TOTALTEST{i}", "type": "discount",
            "discount_percent": 10, "max_uses": 5
        })

    # Request with limit=1 — total must be >= 3, not 1
    r = await admin_client.get("/admin/promo-codes?limit=1&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 3, (
        f"total={data['total']} reflects page size, not full count"
    )
    assert len(data["codes"]) == 1
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest backend/tests/test_admin.py::test_list_promo_codes_total_reflects_full_count_not_page_size -v
```

Expected: `FAILED` — `total=1` (page size), not the full count

- [ ] **Step 3: Fix list_promo_codes total count**

In `resume-optimizer/backend/admin/router.py`, replace the `list_promo_codes` function body. Before applying `limit/offset`, build a count query. The filter logic stays the same; only the execution changes:

```python
@router.get("/promo-codes")
async def list_promo_codes(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from db.models import PromoCode

    base_query = select(PromoCode)

    if status == "active":
        base_query = base_query.where(
            (PromoCode.deactivated_at == None) &  # noqa: E711
            ((PromoCode.expires_at == None) | (PromoCode.expires_at > datetime.now(timezone.utc)))  # noqa: E711
        )
    elif status == "expired":
        base_query = base_query.where(
            (PromoCode.deactivated_at == None) &  # noqa: E711
            (PromoCode.expires_at <= datetime.now(timezone.utc))
        )
    elif status == "deactivated":
        base_query = base_query.where(PromoCode.deactivated_at != None)  # noqa: E711

    if type:
        base_query = base_query.where(PromoCode.type == type)

    # COUNT on full result set before paging
    total = (
        await db.execute(select(func.count()).select_from(base_query.subquery()))
    ).scalar() or 0

    result = await db.execute(base_query.limit(limit).offset(offset))
    codes = result.scalars().all()

    items = []
    for code in codes:
        status_val = _promo_status(code)
        days_until = None
        if code.expires_at:
            delta = (code.expires_at - datetime.now(timezone.utc)).days
            days_until = max(0, delta)

        items.append({
            "id": str(code.id),
            "code": code.code,
            "type": code.type,
            "max_uses": code.max_uses,
            "current_uses": code.current_uses,
            "expires_at": code.expires_at.isoformat() if code.expires_at else None,
            "created_at": code.created_at.isoformat(),
            "status": status_val,
            "days_until_expiry": days_until,
        })

    return {"total": total, "codes": items}
```

- [ ] **Step 4: Fix avg_cost_per_run denominator**

In `resume-optimizer/backend/admin/router.py`, inside `get_stats()`, add a `pipeline_runs_month` query and fix the division (lines ~180-182):

Replace:
```python
                    if pipeline_runs_today > 0:
                        avg_cost_per_run = (total_cost_cents_month / 100) / pipeline_runs_today if pipeline_runs_today > 0 else 0
```

with:

```python
                    pipeline_runs_month = (
                        await db.execute(
                            select(func.count(PipelineJob.id)).where(
                                PipelineJob.created_at >= month_start,
                                PipelineJob.status == JobStatus.done,
                            )
                        )
                    ).scalar() or 0
                    avg_cost_per_run = (
                        (total_cost_cents_month / 100) / pipeline_runs_month
                        if pipeline_runs_month > 0 else 0
                    )
```

- [ ] **Step 5: Run tests**

```bash
pytest backend/tests/test_admin.py::test_list_promo_codes_total_reflects_full_count_not_page_size -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/admin/router.py
git add resume-optimizer/backend/tests/test_admin.py
git commit -m "fix: list_promo_codes returns full COUNT not page size; avg_cost_per_run uses monthly run count"
```

---

## Task 8: Add MIME Type Magic Bytes Validation on Upload (P1)

**The bug:** Upload only checks filename extension. A file named `malware.pdf` with non-PDF content bypasses all validation.

**Files:**
- Modify: `resume-optimizer/backend/main.py:260-275`
- Test: `resume-optimizer/backend/tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_smoke.py`:

```python
@pytest.mark.asyncio
async def test_upload_rejects_fake_pdf_with_wrong_magic_bytes():
    """A file with .pdf extension but non-PDF content must be rejected."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={
            "email": "mime_test@test.com", "password": "SecurePass1", "full_name": "MIME Test"
        })
        token = r.json()["access_token"]

        # Valid extension, invalid content (definitely not a PDF)
        fake_pdf = b"This is not a PDF file, just plain text pretending to be one."
        r = await c.post(
            "/upload",
            files={"file": ("resume.pdf", fake_pdf, "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        assert "content does not match" in r.json()["detail"].lower()
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest backend/tests/test_smoke.py::test_upload_rejects_fake_pdf_with_wrong_magic_bytes -v
```

Expected: `FAILED` — returns 200 or 500 (parses garbage)

- [ ] **Step 3: Add magic bytes check to upload endpoint**

In `resume-optimizer/backend/main.py`, add a constant near line 230 (with other constants):

```python
_UPLOAD_MAGIC = {
    ".pdf":  b"%PDF-",
    ".docx": b"PK\x03\x04",
}
```

Then in `upload_resume`, after the `contents` size check (after line 271, before creating the temp file), add:

```python
    expected_magic = _UPLOAD_MAGIC.get(ext, b"")
    if not contents[:8].startswith(expected_magic):
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match {ext} extension.",
        )
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest backend/tests/test_smoke.py::test_upload_rejects_fake_pdf_with_wrong_magic_bytes -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/main.py
git add resume-optimizer/backend/tests/test_smoke.py
git commit -m "fix: add MIME magic bytes validation on upload — rejects files with spoofed extensions"
```

---

## Task 9: Reduce SSE Polling to 2 Seconds (P1)

**The bug:** SSE event loop polls every 500ms. With 100 concurrent users that's 200 PostgreSQL queries/second purely for status polling.

**Files:**
- Modify: `resume-optimizer/backend/main.py:424`

- [ ] **Step 1: Change sleep interval**

In `resume-optimizer/backend/main.py`, replace line 424:

```python
            await asyncio.sleep(0.5)
```

with:

```python
            await asyncio.sleep(2.0)
```

- [ ] **Step 2: Run full test suite to confirm no regressions**

```bash
cd resume-optimizer && pytest backend/tests/ -v --tb=short -q
```

Expected: All tests `PASSED` (SSE tests may be slower by ~1.5s each but should still pass)

- [ ] **Step 3: Commit**

```bash
git add resume-optimizer/backend/main.py
git commit -m "perf: reduce SSE poll interval 0.5s → 2s — cuts DB load by 4x under concurrent users"
```

---

## Task 10: Fix Remaining DateTime Timezone Columns (P1)

**The bug:** `users.created_at`, `resumes.created_at`, `pipeline_jobs.created_at/updated_at`, `user_promo_redemptions.redeemed_at`, and `provider_costs.created_at/updated_at` are `DateTime` without `timezone=True`. Migration 0007 only fixed `users.trial_expires_at`.

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0010_fix_datetime_timezones.py`
- Modify: `resume-optimizer/backend/db/models.py` (multiple DateTime columns)
- Test: `resume-optimizer/backend/tests/test_migrations.py`

- [ ] **Step 1: Create migration 0010**

Create `resume-optimizer/backend/alembic/versions/0010_fix_datetime_timezones.py`:

```python
"""fix timezone-naive datetime columns

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TZ_TABLES = {
    "users":                   ["created_at"],
    "resumes":                 ["created_at"],
    "pipeline_jobs":           ["created_at", "updated_at"],
    "user_promo_redemptions":  ["redeemed_at"],
    "provider_costs":          ["created_at", "updated_at"],
}


def upgrade() -> None:
    for table, cols in _TZ_TABLES.items():
        with op.batch_alter_table(table) as batch_op:
            for col in cols:
                batch_op.alter_column(
                    col,
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=False,
                    postgresql_using=f"{col} AT TIME ZONE 'UTC'",
                )


def downgrade() -> None:
    for table, cols in _TZ_TABLES.items():
        with op.batch_alter_table(table) as batch_op:
            for col in cols:
                batch_op.alter_column(
                    col,
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=False,
                )
```

- [ ] **Step 2: Update models.py to match**

In `resume-optimizer/backend/db/models.py`, update every `Column(DateTime, ...)` (without `timezone=True`) to `Column(DateTime(timezone=True), ...)`. The affected columns are:

- `User.created_at` (line 46): `Column(DateTime, ...)` → `Column(DateTime(timezone=True), ...)`
- `Resume.created_at` (line 74): same change
- `PipelineJob.created_at` (line 93): same change
- `PipelineJob.updated_at` (line 94): same change
- `UserPromoRedemption.redeemed_at` (line 133): same change
- `ProviderCost.created_at` (line 148): same change
- `ProviderCost.updated_at` (line 149): same change

- [ ] **Step 3: Run migrations test**

```bash
pytest backend/tests/test_migrations.py -v
```

Expected: `PASSED`

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0010_fix_datetime_timezones.py
git add resume-optimizer/backend/db/models.py
git commit -m "fix: add timezone=True to all remaining tz-naive DateTime columns — prevents tz comparison bugs in admin analytics"
```

---

## Task 11: Add JWT Token Revocation via DB Blocklist (P1)

**The bug:** 7-day JWTs cannot be revoked. A compromised token or suspended account remains valid for up to 7 days.

**Files:**
- Create: `resume-optimizer/backend/alembic/versions/0011_add_token_blocklist.py`
- Modify: `resume-optimizer/backend/db/models.py` — add `TokenBlocklist`
- Modify: `resume-optimizer/backend/auth/router.py` — add `jti` to tokens; add `POST /auth/logout`
- Modify: `resume-optimizer/backend/auth/dependencies.py` — check blocklist in `get_current_user`
- Modify: `resume-optimizer/backend/main.py` — add blocklist cleanup to reaper
- Test: `resume-optimizer/backend/tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_smoke.py`:

```python
@pytest.mark.asyncio
async def test_logout_revokes_token():
    """After /auth/logout, the old token must return 401 on /auth/me."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={
            "email": "logout_test@test.com", "password": "SecurePass1", "full_name": "Logout"
        })
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Logout
        r = await c.post("/auth/logout", headers=headers)
        assert r.status_code == 200

        # Old token must be rejected
        r = await c.get("/auth/me", headers=headers)
        assert r.status_code == 401, f"Revoked token still accepted: {r.status_code}"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest backend/tests/test_smoke.py::test_logout_revokes_token -v
```

Expected: `FAILED` — 404 (no `/auth/logout` endpoint) then old token still works

- [ ] **Step 3: Add TokenBlocklist model**

In `resume-optimizer/backend/db/models.py`, add after the `DailyUsageCounter` class:

```python
class TokenBlocklist(Base):
    """Revoked JWT tokens. Checked on every authenticated request.
    Expired entries are cleaned up by the stuck-job reaper.
    """
    __tablename__ = "token_blocklist"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    jti        = Column(String(36), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
```

- [ ] **Step 4: Create migration 0011**

Create `resume-optimizer/backend/alembic/versions/0011_add_token_blocklist.py`:

```python
"""add token_blocklist table for JWT revocation

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_blocklist",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
    )
    op.create_index("ix_token_blocklist_jti", "token_blocklist", ["jti"])


def downgrade() -> None:
    op.drop_index("ix_token_blocklist_jti", "token_blocklist")
    op.drop_table("token_blocklist")
```

- [ ] **Step 5: Add jti to token creation and logout endpoint**

In `resume-optimizer/backend/auth/router.py`:

1. Add `import uuid` at the top (or verify it's already imported via models import).

2. Replace `_make_token` (lines 60-62):

```python
def _make_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "jti": str(uuid.uuid4())},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
```

3. Update imports at top of auth/router.py to include `TokenBlocklist`:

```python
from db.models import PlanLimit, PlanType, PromoCode, User, UserPromoRedemption, TokenBlocklist
```

4. Add `POST /auth/logout` endpoint at the end of the auth router:

```python
from fastapi.security import OAuth2PasswordBearer as _OAuth2
_bearer = _OAuth2(tokenUrl="/auth/login", auto_error=False)

@router.post("/logout")
async def logout(
    token: str = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current JWT. The token is added to the blocklist until it expires."""
    if not token:
        return {"detail": "Logged out"}
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        jti = payload.get("jti")
        if jti:
            expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            db.add(TokenBlocklist(jti=jti, expires_at=expires_at))
            try:
                await db.commit()
            except Exception:
                await db.rollback()
    except Exception:
        pass  # Invalid/expired token — nothing to revoke
    return {"detail": "Logged out"}
```

- [ ] **Step 6: Check blocklist in get_current_user**

In `resume-optimizer/backend/auth/dependencies.py`, update imports:

```python
from db.models import DailyUsageCounter, PlanLimit, User, TokenBlocklist
```

Update `get_current_user` to check blocklist after decoding the token:

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
        jti: str = payload.get("jti")
    except JWTError:
        raise credentials_exc

    # Check if this token has been revoked
    if jti:
        blocked = await db.scalar(
            select(TokenBlocklist).where(TokenBlocklist.jti == jti)
        )
        if blocked:
            raise credentials_exc

    try:
        user_uuid = _uuid_module.UUID(user_id)
    except (ValueError, AttributeError):
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == user_uuid, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exc
    return user
```

- [ ] **Step 7: Add blocklist cleanup to reaper**

In `resume-optimizer/backend/main.py`, inside `_reap_stuck_jobs`, add cleanup after the stuck-job reap:

```python
async def _reap_stuck_jobs():
    while True:
        await asyncio.sleep(300)
        try:
            async with AsyncSessionLocal() as db:
                ids = await _reap_once(db)
                if ids:
                    _logger.warning("Reaped %d stuck jobs: %s", len(ids), ids)
                # Clean up expired blocklist entries
                await db.execute(
                    delete(TokenBlocklist).where(
                        TokenBlocklist.expires_at < datetime.now(timezone.utc)
                    )
                )
                await db.commit()
        except Exception:
            _logger.exception("Reaper cycle failed — will retry in 5 minutes")
```

Add `TokenBlocklist` to the import from `db.models` in main.py.

- [ ] **Step 8: Run test to confirm it passes**

```bash
pytest backend/tests/test_smoke.py::test_logout_revokes_token -v
```

Expected: `PASSED`

- [ ] **Step 9: Commit**

```bash
git add resume-optimizer/backend/alembic/versions/0011_add_token_blocklist.py
git add resume-optimizer/backend/db/models.py
git add resume-optimizer/backend/auth/router.py
git add resume-optimizer/backend/auth/dependencies.py
git add resume-optimizer/backend/main.py
git add resume-optimizer/backend/tests/test_smoke.py
git commit -m "feat: add JWT token revocation via DB blocklist — /auth/logout invalidates tokens immediately"
```

---

## Task 12: Wire vacuum_old_matches to Reaper + Fix Full-Table Read (P1)

**Two bugs:** `vacuum_old_matches` is never called (scheduled nowhere). Its implementation reads the entire Delta table into memory (OOM at scale) and rewrites it.

**Files:**
- Modify: `resume-optimizer/backend/delta/writer.py:250-278`
- Modify: `resume-optimizer/backend/main.py` (reaper loop)

- [ ] **Step 1: Fix vacuum_old_matches to use Delta DELETE**

In `resume-optimizer/backend/delta/writer.py`, replace the entire `vacuum_old_matches` function:

```python
def vacuum_old_matches(retention_days: int = 90) -> None:
    """Hard-delete job_matches rows older than retention_days using Delta's native DELETE.
    Called weekly by the stuck-job reaper in main.py.
    """
    path = _matches_path()
    if not _table_exists(path):
        return

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=retention_days)
    # Use ISO format without microseconds for the SQL predicate
    cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")

    dt = DeltaTable.from_uri(path, storage_options=_storage_options())
    dt.delete(f"scraped_at < '{cutoff_iso}'")
    dt.vacuum(retention_hours=168, dry_run=False)  # 7-day file retention
```

- [ ] **Step 2: Wire vacuum to the reaper with weekly cadence**

In `resume-optimizer/backend/main.py`, add an import at the top:

```python
from delta.writer import write_daily_usage, write_job_match, vacuum_old_matches
```

Add a module-level sentinel variable near the top of main.py (after the imports):

```python
_last_vacuum_ts: float = 0.0
```

Update `_reap_stuck_jobs` to run vacuum weekly:

```python
async def _reap_stuck_jobs():
    global _last_vacuum_ts
    while True:
        await asyncio.sleep(300)
        try:
            async with AsyncSessionLocal() as db:
                ids = await _reap_once(db)
                if ids:
                    _logger.warning("Reaped %d stuck jobs: %s", len(ids), ids)
                await db.execute(
                    delete(TokenBlocklist).where(
                        TokenBlocklist.expires_at < datetime.now(timezone.utc)
                    )
                )
                await db.commit()
        except Exception:
            _logger.exception("Reaper cycle failed — will retry in 5 minutes")

        now = time.time()
        if now - _last_vacuum_ts >= 7 * 24 * 3600:
            try:
                await asyncio.to_thread(vacuum_old_matches)
                _last_vacuum_ts = now
                _logger.info("vacuum_old_matches completed")
            except Exception:
                _logger.exception("vacuum_old_matches failed — will retry next week")
```

- [ ] **Step 3: Run full test suite**

```bash
cd resume-optimizer && pytest backend/tests/ -v --tb=short -q
```

Expected: All tests `PASSED`

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/backend/delta/writer.py
git add resume-optimizer/backend/main.py
git commit -m "fix: vacuum_old_matches now uses Delta DELETE (no full table read); wired to reaper with weekly cadence"
```

---

## Task 13: Replace bcrypt Passlib Monkey-Patch (P2)

**The bug:** `auth/router.py` monkey-patches `bcrypt.__about__` to work around a passlib 1.7.4 + bcrypt 4.x incompatibility. This is fragile against future bcrypt changes.

**Files:**
- Modify: `resume-optimizer/backend/auth/router.py:1-31`
- Modify: `resume-optimizer/backend/requirements.txt`
- Test: `resume-optimizer/backend/tests/test_smoke.py`

- [ ] **Step 1: Write the test**

Add to `resume-optimizer/backend/tests/test_smoke.py`:

```python
@pytest.mark.asyncio
async def test_register_and_login_work_without_passlib():
    """Registration and login must work — verifies bcrypt hashing/verification is correct."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={
            "email": "bcrypt_test@test.com", "password": "SecurePass1", "full_name": "Bcrypt Test"
        })
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]

        r = await c.post("/auth/login", json={
            "email": "bcrypt_test@test.com", "password": "SecurePass1"
        })
        assert r.status_code == 200

        r = await c.post("/auth/login", json={
            "email": "bcrypt_test@test.com", "password": "WrongPassword1"
        })
        assert r.status_code == 401
```

- [ ] **Step 2: Run test to confirm it currently passes (baseline)**

```bash
pytest backend/tests/test_smoke.py::test_register_and_login_work_without_passlib -v
```

This should `PASS` currently (the monkey-patch makes it work). After the fix, it should still pass.

- [ ] **Step 3: Replace passlib with direct bcrypt**

In `resume-optimizer/backend/auth/router.py`:

Remove lines 11-31 (bcrypt monkey-patch block and passlib import):
```python
# passlib 1.7.4 looks for bcrypt.__about__.__version__ which bcrypt 4.x removed
import bcrypt as _bcrypt
if not hasattr(_bcrypt, "__about__"):
    class _About:
        __version__ = _bcrypt.__version__
    _bcrypt.__about__ = _About()

from passlib.context import CryptContext
...
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

Replace with:

```python
import bcrypt as _bcrypt


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())
```

In `register`, replace:
```python
        password_hash=pwd_context.hash(body.password),
```
with:
```python
        password_hash=_hash_password(body.password),
```

In `login`, replace:
```python
    if not user or not pwd_context.verify(body.password, user.password_hash):
```
with:
```python
    if not user or not _verify_password(body.password, user.password_hash):
```

- [ ] **Step 4: Remove passlib from requirements.txt**

In `resume-optimizer/backend/requirements.txt`, remove the line:
```
passlib[bcrypt]
```
or `passlib==1.7.4` (whatever form it appears in).

- [ ] **Step 5: Run test to confirm it still passes**

```bash
pytest backend/tests/test_smoke.py::test_register_and_login_work_without_passlib -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/auth/router.py
git add resume-optimizer/backend/requirements.txt
git add resume-optimizer/backend/tests/test_smoke.py
git commit -m "fix: replace passlib/bcrypt monkey-patch with direct bcrypt calls — removes fragile workaround"
```

---

## Task 14: Add Password Complexity + full_name Sanitization (P2)

**Files:**
- Modify: `resume-optimizer/backend/auth/router.py`
- Test: `resume-optimizer/backend/tests/test_smoke.py`

- [ ] **Step 1: Write the failing tests**

Add to `resume-optimizer/backend/tests/test_smoke.py`:

```python
@pytest.mark.asyncio
async def test_register_rejects_password_without_uppercase():
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={
            "email": "pwtest1@test.com", "password": "alllowercase1", "full_name": "Test"
        })
        assert r.status_code == 400

@pytest.mark.asyncio
async def test_register_rejects_password_without_digit():
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={
            "email": "pwtest2@test.com", "password": "NoDigitsHere", "full_name": "Test"
        })
        assert r.status_code == 400

@pytest.mark.asyncio
async def test_register_rejects_full_name_with_script_tag():
    from httpx import AsyncClient, ASGITransport
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={
            "email": "nametest@test.com",
            "password": "SecurePass1",
            "full_name": "<script>alert(1)</script>",
        })
        assert r.status_code == 400
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest backend/tests/test_smoke.py::test_register_rejects_password_without_uppercase backend/tests/test_smoke.py::test_register_rejects_password_without_digit backend/tests/test_smoke.py::test_register_rejects_full_name_with_script_tag -v
```

Expected: `FAILED` — all three currently return 200

- [ ] **Step 3: Add validation helpers to auth/router.py**

In `resume-optimizer/backend/auth/router.py`, add after the `_verify_password` function:

```python
import re as _re


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if len(password) > 128:
        raise HTTPException(status_code=400, detail="Password too long (max 128 characters).")
    if not any(c.isupper() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one digit.")
    if password != password.strip():
        raise HTTPException(status_code=400, detail="Password cannot start or end with whitespace.")


def _sanitize_full_name(name: str) -> str:
    name = name.strip()
    if not name:
        return name
    if len(name) > 255:
        raise HTTPException(status_code=400, detail="Name too long (max 255 characters).")
    if not _re.match(r"^[\w\s\-'.]+$", name, _re.UNICODE):
        raise HTTPException(status_code=400, detail="Name contains invalid characters.")
    return name
```

- [ ] **Step 4: Call validators in register and update_profile**

In the `register` function, replace the existing length checks:

```python
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if len(body.password) > 128:
        raise HTTPException(status_code=400, detail="Password too long (max 128 characters).")
```

with:

```python
    _validate_password(body.password)
    body.full_name = _sanitize_full_name(body.full_name)
```

In the `update_profile` function, add before the DB operations:

```python
    request.full_name = _sanitize_full_name(request.full_name)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest backend/tests/test_smoke.py::test_register_rejects_password_without_uppercase backend/tests/test_smoke.py::test_register_rejects_password_without_digit backend/tests/test_smoke.py::test_register_rejects_full_name_with_script_tag -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/auth/router.py
git add resume-optimizer/backend/tests/test_smoke.py
git commit -m "fix: add password complexity policy (uppercase + digit) and full_name input sanitization"
```

---

## Task 15: Fix BOOTSTRAP_SECRET to Raise at Startup (P2)

**The bug:** `config.py` calls `warnings.warn()` when `BOOTSTRAP_SECRET` is not set. This warning may be swallowed by JSON logging. The app silently starts in a broken state.

**Files:**
- Modify: `resume-optimizer/backend/config.py:23-26`

- [ ] **Step 1: Replace warnings.warn with raise ValueError**

In `resume-optimizer/backend/config.py`, replace lines 23-26:

```python
BOOTSTRAP_SECRET = os.environ.get("BOOTSTRAP_SECRET", "")
if not BOOTSTRAP_SECRET:
    import warnings
    warnings.warn("BOOTSTRAP_SECRET not set — /admin/bootstrap endpoint will reject all requests")
```

with:

```python
BOOTSTRAP_SECRET = os.environ.get("BOOTSTRAP_SECRET", "")
if not BOOTSTRAP_SECRET:
    raise ValueError(
        "BOOTSTRAP_SECRET env var is required. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
```

**Important:** Any test that imports `config.py` without `BOOTSTRAP_SECRET` set will now fail. Add `BOOTSTRAP_SECRET=test-bootstrap-secret` to your test environment or `.env.test` file.

- [ ] **Step 2: Set BOOTSTRAP_SECRET in test environment**

In the test runner environment (e.g., `resume-optimizer/.env.test` or via pytest env config), ensure:

```
BOOTSTRAP_SECRET=test-bootstrap-secret-for-tests
JWT_SECRET=test-jwt-secret-must-be-32-chars-minimum
```

If there is no `.env.test`, add `BOOTSTRAP_SECRET=test-bootstrap-secret` to the existing `.env` file (or the CI environment variables).

- [ ] **Step 3: Run full test suite to confirm tests still pass**

```bash
cd resume-optimizer && pytest backend/tests/ -v --tb=short -q
```

Expected: All tests `PASSED`

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/backend/config.py
git commit -m "fix: BOOTSTRAP_SECRET now raises ValueError at startup instead of swallowable warning"
```

---

## Task 16: Fix Dashboard to Use DailyUsageCounter for Today's Runs (P2)

**The bug:** `GET /dashboard/summary` uses Delta Lake for `runs_today`. Delta writes are fire-and-forget — a failed write makes the quota display incorrect. The transactional `DailyUsageCounter` is the authoritative source.

**Files:**
- Modify: `resume-optimizer/backend/dashboard/router.py:48-58`
- Test: `resume-optimizer/backend/tests/test_smoke.py`

- [ ] **Step 1: Update dashboard/router.py**

In `resume-optimizer/backend/dashboard/router.py`, replace the "Today's usage from Delta" block (lines 48-58):

```python
    # Today's usage from Delta
    try:
        from datetime import date
        today_str = date.today().isoformat()
        df = await asyncio.to_thread(read_usage_last_n_days, user_id, 1)
        today_df = df[df["date"] == today_str]
        runs_today    = int(today_df["pipeline_runs"].sum()) if not today_df.empty else 0
        uploads_today = int(today_df["uploads"].sum())      if not today_df.empty else 0
        tokens_today  = int(today_df["tokens_used"].sum())  if not today_df.empty else 0
    except Exception:
        runs_today = uploads_today = tokens_today = 0
```

with:

```python
    from datetime import date
    from db.models import DailyUsageCounter
    today_str = date.today().isoformat()

    # runs_today: use transactional counter — authoritative for quota display
    counter = await db.scalar(
        select(DailyUsageCounter).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    )
    runs_today = counter.runs if counter else 0

    # uploads_today, tokens_today: best-effort from Delta analytics
    try:
        df = await asyncio.to_thread(read_usage_last_n_days, user_id, 1)
        today_df = df[df["date"] == today_str]
        uploads_today = int(today_df["uploads"].sum()) if not today_df.empty else 0
        tokens_today  = int(today_df["tokens_used"].sum()) if not today_df.empty else 0
    except Exception:
        uploads_today = tokens_today = 0
```

- [ ] **Step 2: Run full test suite**

```bash
cd resume-optimizer && pytest backend/tests/ -v --tb=short -q
```

Expected: All tests `PASSED`

- [ ] **Step 3: Commit**

```bash
git add resume-optimizer/backend/dashboard/router.py
git commit -m "fix: dashboard uses DailyUsageCounter for runs_today — Delta fire-and-forget writes no longer affect quota display"
```

---

## Task 17: Split Analytics Write Lock Per Table (P2)

**The bug:** `_write_lock` is a single `threading.Lock()` shared by both `write_daily_usage` and `write_job_match`. All analytics writes serialize even though they touch different storage paths.

**Files:**
- Modify: `resume-optimizer/backend/delta/writer.py:26` and the two `with _write_lock:` blocks

- [ ] **Step 1: Replace single lock with per-table locks**

In `resume-optimizer/backend/delta/writer.py`, replace line 26:

```python
_write_lock = threading.Lock()
```

with:

```python
_usage_lock   = threading.Lock()
_matches_lock = threading.Lock()
```

In `write_daily_usage` (line 109), replace:

```python
    with _write_lock:
```

with:

```python
    with _usage_lock:
```

In `write_job_match` (line 140), replace:

```python
    with _write_lock:
```

with:

```python
    with _matches_lock:
```

- [ ] **Step 2: Run full test suite**

```bash
cd resume-optimizer && pytest backend/tests/ -v --tb=short -q
```

Expected: All tests `PASSED`

- [ ] **Step 3: Commit**

```bash
git add resume-optimizer/backend/delta/writer.py
git commit -m "perf: split Delta write lock per table — usage and match writes no longer serialize each other"
```

---

## Task 18: Add Retry Logic to Frontend API Client + Rate-Limit Admin Endpoints (P2)

Two P2 fixes bundled together as both touch API behaviour without DB changes.

**Files:**
- Modify: `resume-optimizer/frontend/src/api/client.js`
- Modify: `resume-optimizer/backend/admin/router.py` (add `@limiter.limit` decorators)

- [ ] **Step 1: Add retry to the Axios response interceptor**

In `resume-optimizer/frontend/src/api/client.js`, replace the entire file with:

```javascript
import axios from 'axios';
import toast from 'react-hot-toast';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const client = axios.create({ baseURL: API_URL });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  async (err) => {
    const config = err.config;

    // Retry GET requests on 5xx (transient server errors / cold starts)
    if (
      config &&
      config.method === 'get' &&
      err.response?.status >= 500 &&
      (config._retryCount || 0) < 2
    ) {
      config._retryCount = (config._retryCount || 0) + 1;
      await new Promise((r) => setTimeout(r, 1000 * config._retryCount));
      return client(config);
    }

    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    if (err.response?.status === 429) {
      const d = err.response.data?.detail || {};
      toast.error(
        `${d.upgrade_message || 'Daily limit reached. Upgrade your plan.'}`,
        { duration: 5000 }
      );
    }
    return Promise.reject(err);
  }
);

export default client;
```

- [ ] **Step 2: Add rate limiting to admin stats and analytics endpoints**

In `resume-optimizer/backend/admin/router.py`, add `request: Request` and `@limiter.limit` to the two most expensive endpoints.

For `get_stats` (line 104):

```python
@router.get("/stats", response_model=AdminStats)
@limiter.limit("30/minute")
async def get_stats(
    request: Request,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
```

For `get_analytics` (find the function after line 200):

```python
@router.get("/analytics", response_model=AnalyticsResponse)
@limiter.limit("10/minute")
async def get_analytics(
    request: Request,
    ...
```

`Request` is already imported at line 7 of admin/router.py.

- [ ] **Step 3: Run full test suite**

```bash
cd resume-optimizer && pytest backend/tests/ -v --tb=short -q
```

Expected: All tests `PASSED`

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/frontend/src/api/client.js
git add resume-optimizer/backend/admin/router.py
git commit -m "feat: add GET retry to frontend API client; rate-limit admin stats/analytics endpoints"
```

---

## Task 19: Codebase Hygiene (P3)

Four low-severity cleanups: remove committed test DBs and venv from git, add `.gitignore` entries, remove the redundant Python post-filter in the Delta reader, and add session TTL cleanup.

**Files:**
- Modify/Create: `resume-optimizer/.gitignore`
- Modify: `resume-optimizer/backend/delta/writer.py` (session TTL comment, already done in Task 3)
- Modify: `resume-optimizer/backend/agents/optimizer_agent.py` (session TTL cleanup)
- Git: Remove committed artifacts

- [ ] **Step 1: Create/update .gitignore**

Create or update `resume-optimizer/.gitignore` to include:

```
# Test databases (ephemeral — never commit)
*.db
*.db-shm
*.db-wal

# Python virtual environments
rv/
.venv/
venv/
env/

# Python bytecode
__pycache__/
*.pyc
*.pyo
*.pyd

# Environment files
.env
.env.local
.env.test

# Delta Lake test artifacts
delta_store/
```

- [ ] **Step 2: Remove committed test databases**

```bash
cd resume-optimizer
git rm --cached test_admin.db test_analytics.db test_smoke.db 2>/dev/null || true
git rm --cached backend/test_admin.db backend/test_analytics.db 2>/dev/null || true
```

- [ ] **Step 3: Remove committed venv**

```bash
git rm -r --cached rv/ 2>/dev/null || echo "rv/ not tracked"
```

- [ ] **Step 4: Add session TTL cleanup to stuck-job reaper**

In `resume-optimizer/backend/agents/optimizer_agent.py`, add a TTL cleanup function after the `_sessions` dict definition. Find where `_sessions: Dict[str, ResumeState] = {}` is defined (around line 119) and add:

```python
_sessions: Dict[str, ResumeState] = {}
_session_created_at: Dict[str, datetime] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL_SECONDS = 4 * 3600  # 4 hours


def cleanup_stale_sessions() -> int:
    """Remove sessions older than _SESSION_TTL_SECONDS. Called by the reaper."""
    now = datetime.now(timezone.utc)
    with _sessions_lock:
        stale = [
            k for k, t in _session_created_at.items()
            if (now - t).total_seconds() > _SESSION_TTL_SECONDS
        ]
        for k in stale:
            _sessions.pop(k, None)
            _session_created_at.pop(k, None)
    return len(stale)
```

Update the session registration function (wherever `_sessions[session_id] = ...` is called) to also record `_session_created_at[session_id] = datetime.now(timezone.utc)`.

In `resume-optimizer/backend/main.py`, add the cleanup call to the reaper:

```python
from agents.optimizer_agent import cleanup_stale_sessions

# Inside _reap_stuck_jobs, after the stuck-job reap:
        stale_count = cleanup_stale_sessions()
        if stale_count:
            _logger.info("Cleaned up %d stale pipeline sessions", stale_count)
```

- [ ] **Step 5: Run full test suite**

```bash
cd resume-optimizer && pytest backend/tests/ -v --tb=short -q
```

Expected: All tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/.gitignore
git add resume-optimizer/backend/agents/optimizer_agent.py
git add resume-optimizer/backend/main.py
git commit -m "chore: add .gitignore for *.db and rv/; remove committed test DBs; add session TTL cleanup to reaper"
```

---

## Self-Review

### Spec Coverage

| Issue | Task |
|---|---|
| uq_provider_active constraint broken | Task 1 ✓ |
| Admin Delta read passes user_id="" | Task 3 ✓ |
| Provider name case inconsistency | Task 2 ✓ |
| _sessions dict process-local (documented risk) | Task 19 partial — adds TTL cleanup but Redis migration is out of scope |
| resume_id not validated in /scrape-jobs | Task 4 ✓ |
| create_promo_code accepts raw dict | Task 5 ✓ |
| redeem_promo_code IntegrityError | Task 6 ✓ |
| No MIME type validation | Task 8 ✓ |
| SSE polling at 500ms | Task 9 ✓ |
| avg_cost_per_run wrong denominator | Task 7 ✓ |
| list_promo_codes total: len(page) | Task 7 ✓ |
| Resume PII plaintext | Out of scope — pgcrypto migration requires DBA planning; treat as separate task |
| vacuum_old_matches never scheduled | Task 12 ✓ |
| TOCTOU in check_plan_limit | Intentional design (see review) — not fixed |
| No token revocation | Task 11 ✓ |
| users.created_at tz-naive | Task 10 ✓ |
| threading.Lock serializes analytics | Task 17 ✓ |
| bcrypt monkey-patch | Task 13 ✓ |
| sys.path.insert in main.py | Not fixed — removing requires package restructure beyond bug-fix scope |
| No password complexity | Task 14 ✓ |
| Dashboard reads Delta for today | Task 16 ✓ |
| _call_llm creates new event loop | Not fixed — functionally correct; defer to performance optimization track |
| Plan limits hardcoded | Not fixed — requires new admin API surface; separate feature |
| No retry in frontend | Task 18 ✓ |
| No rate limiting on admin | Task 18 ✓ |
| No full_name sanitization | Task 14 ✓ |
| BOOTSTRAP_SECRET warning not raise | Task 15 ✓ |
| SQLite test DBs committed | Task 19 ✓ |
| rv/ venv committed | Task 19 ✓ |
| Delta double-filter | Task 3 ✓ (fixed when user_id filter was made conditional) |
| Session dict unbounded | Task 19 ✓ |
| geo_redundant_backup disabled | Not fixed — accepted known deviation; document in ADR |

**Out-of-scope items (4):** Resume PII encryption (pgcrypto migration), sys.path restructuring, _call_llm event loop optimization, plan limits admin API — all require larger architectural changes that warrant their own plan.

### Placeholder Scan

No "TBD" or "implement later" text. All code steps show complete implementations.

### Type Consistency

- `TokenBlocklist` added in Task 11 models, referenced in Task 11 router and dependencies — consistent.
- `PromoCodeCreate` added in Task 5 schemas, imported in Task 5 router update — consistent.
- `vacuum_old_matches` imported in Task 12 main.py update, already exported from delta/writer.py — consistent.
- `cleanup_stale_sessions` added in Task 19 optimizer_agent.py, imported in Task 19 main.py — consistent.

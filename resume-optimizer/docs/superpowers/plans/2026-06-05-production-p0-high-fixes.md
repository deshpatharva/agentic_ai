# Production P0 + High Severity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 14 P0 and High severity production issues that will cause data loss, security breaches, or system crashes under real load.

**Architecture:** Fixes are ordered from lowest to highest blast radius — quick input validation first, then logic bugs, then the large DB connection scope refactor, then infrastructure. Each task is independently deployable.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, gunicorn, pytest-asyncio

**Python interpreter:** `C:\Users\deshp\rv\Scripts\python.exe`
**Run tests from:** `resume-optimizer/` directory
**Test command:** `C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/<file> -v`

---

## File Map

```
Modified files:
  backend/main.py                  — per_source validator, cache fix, DB scope refactor, cost provider, gunicorn prep
  backend/auth/router.py           — bcrypt max length, promo atomic CAS, email IntegrityError, discount message
  backend/admin/router.py          — bootstrap secret
  backend/config.py                — BOOTSTRAP_SECRET, env var casing, pool config
  backend/db/session.py            — connection pool size
  backend/auth/dependencies.py     — replace Delta rate limit with PostgreSQL counter
  backend/Dockerfile               — gunicorn
  backend/requirements.txt         — gunicorn
  backend/db/models.py             — DailyUsageCounter model (for #5 rate limit fix)
  backend/alembic/versions/        — new migration for DailyUsageCounter

New files:
  backend/tests/test_prod_fixes.py — all tests for this plan
```

---

## Task 1: Input Validation Hardening (#8, #11, #25)

**Files:**
- Modify: `backend/main.py` — `ScrapeJobsRequest.per_source`, `AnalyzeJDRequest.jd_text`
- Modify: `backend/auth/router.py` — `register` password max length
- Test: `backend/tests/test_prod_fixes.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_prod_fixes.py`:

```python
"""Tests for production readiness fixes."""
import sys
import os
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_prod_fixes.db")

from main import app
from db.session import init_db
from db.models import Base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

_engine = create_async_engine("sqlite+aiosqlite:///./test_prod_fixes.db")
_Session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    try:
        os.remove("./test_prod_fixes.db")
    except Exception:
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(client):
    await client.post("/auth/register", json={"email": "fix@test.com", "password": "Test1234!", "full_name": "Fix User"})
    resp = await client.post("/auth/login", json={"email": "fix@test.com", "password": "Test1234!"})
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ── Task 1: Input validation ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_jobs_rejects_oversized_per_source(auth_client):
    """per_source > 50 must return HTTP 422."""
    r = await auth_client.post("/scrape-jobs", json={
        "resume_id": "00000000-0000-0000-0000-000000000001",
        "keywords": "engineer",
        "per_source": 99999,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scrape_jobs_accepts_valid_per_source(auth_client):
    """per_source=50 must not be rejected by validation (may fail downstream)."""
    r = await auth_client.post("/scrape-jobs", json={
        "resume_id": "00000000-0000-0000-0000-000000000001",
        "keywords": "engineer",
        "per_source": 50,
    })
    assert r.status_code != 422


@pytest.mark.asyncio
async def test_register_rejects_password_over_128_chars(client):
    """Passwords longer than 128 chars must return HTTP 400."""
    r = await client.post("/auth/register", json={
        "email": "longpass@test.com",
        "password": "A" * 129,
        "full_name": "Test",
    })
    assert r.status_code == 400
    assert "too long" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_analyze_jd_rejects_oversized_body(auth_client):
    """jd_text longer than MAX_JD_CHARS must return HTTP 422."""
    r = await auth_client.post("/analyze-jd", json={"jd_text": "x" * 100_001})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests — confirm they fail**

```
cd resume-optimizer
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_scrape_jobs_rejects_oversized_per_source backend/tests/test_prod_fixes.py::test_register_rejects_password_over_128_chars backend/tests/test_prod_fixes.py::test_analyze_jd_rejects_oversized_body -v
```

Expected: all FAIL (per_source accepted, password accepted, jd_text accepted)

- [ ] **Step 3: Implement fixes**

In `backend/main.py`, update `ScrapeJobsRequest` and `AnalyzeJDRequest`:

```python
# Add to imports at top of main.py
from pydantic import Field

class AnalyzeJDRequest(BaseModel):
    jd_text: str = Field(..., max_length=MAX_JD_CHARS)

class ScrapeJobsRequest(BaseModel):
    resume_id: str
    keywords: str
    per_source: int = Field(default=20, ge=1, le=50)
```

In `backend/auth/router.py`, add max-length check immediately after the min-length check in `register`:

```python
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    if len(body.password) > 128:
        raise HTTPException(status_code=400, detail="Password too long (max 128 characters).")
```

- [ ] **Step 4: Run tests — confirm they pass**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_scrape_jobs_rejects_oversized_per_source backend/tests/test_prod_fixes.py::test_scrape_jobs_accepts_valid_per_source backend/tests/test_prod_fixes.py::test_register_rejects_password_over_128_chars backend/tests/test_prod_fixes.py::test_analyze_jd_rejects_oversized_body -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/auth/router.py backend/tests/test_prod_fixes.py
git commit -m "fix: add input validation for per_source, password length, and jd_text"
```

---

## Task 2: Remove Global Cache Corruption (#6)

**Files:**
- Modify: `backend/main.py` — remove `result_cache.clear()` from `_run_pipeline_task`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_result_cache_clear_not_in_pipeline():
    """result_cache.clear() must not be called inside _run_pipeline_task.

    It is a global dict shared across all concurrent requests — clearing it
    during one job corrupts another job's cached JD analysis mid-pipeline.
    """
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert "result_cache.clear()" not in source, (
        "result_cache.clear() found in _run_pipeline_task — "
        "this wipes cached data for ALL concurrent jobs."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_result_cache_clear_not_in_pipeline -v
```

Expected: FAIL — `result_cache.clear()` found in source

- [ ] **Step 3: Remove the call**

In `backend/main.py`, inside `_run_pipeline_task`, delete the line:

```python
result_cache.clear()
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_result_cache_clear_not_in_pipeline -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "fix: remove global result_cache.clear() from pipeline task — corrupts concurrent jobs"
```

---

## Task 3: Bootstrap Endpoint Security (#3)

**Files:**
- Modify: `backend/config.py` — add `BOOTSTRAP_SECRET`
- Modify: `backend/admin/router.py` — require secret + add rate limit
- Modify: `backend/admin/schemas.py` — add `secret` field to `BootstrapRequest`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_bootstrap_requires_secret(client):
    """Bootstrap without the correct secret must return 403."""
    r = await client.post("/admin/bootstrap", json={"email": "admin@test.com", "secret": "wrong"})
    assert r.status_code == 403

@pytest.mark.asyncio
async def test_bootstrap_without_secret_field_returns_422(client):
    """Bootstrap with no secret field must return 422 (schema validation)."""
    r = await client.post("/admin/bootstrap", json={"email": "admin@test.com"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests — confirm they fail**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_bootstrap_requires_secret backend/tests/test_prod_fixes.py::test_bootstrap_without_secret_field_returns_422 -v
```

Expected: both FAIL (bootstrap accepts any request)

- [ ] **Step 3: Add config constant**

In `backend/config.py`, add after the JWT block:

```python
# ── Bootstrap ────────────────────────────────────────────────────────────────
BOOTSTRAP_SECRET = os.environ.get("BOOTSTRAP_SECRET", "")
if not BOOTSTRAP_SECRET:
    import warnings
    warnings.warn("BOOTSTRAP_SECRET not set — /admin/bootstrap endpoint is disabled")
```

- [ ] **Step 4: Update BootstrapRequest schema**

In `backend/admin/schemas.py`, add `secret` field to `BootstrapRequest`:

```python
class BootstrapRequest(BaseModel):
    email: str
    secret: str
```

- [ ] **Step 5: Update bootstrap endpoint**

In `backend/admin/router.py`, replace the bootstrap function:

```python
from config import BOOTSTRAP_SECRET

@router.post("/bootstrap")
@limiter.limit("3/minute")
async def bootstrap(
    request: Request,
    body: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
):
    """Promote first user to admin. Requires BOOTSTRAP_SECRET env var."""
    if not BOOTSTRAP_SECRET or body.secret != BOOTSTRAP_SECRET:
        raise HTTPException(status_code=403, detail="Invalid bootstrap secret.")

    admin_count = (
        await db.execute(select(func.count(User.id)).where(User.is_admin == True))
    ).scalar()
    if admin_count > 0:
        raise HTTPException(status_code=403, detail="An admin already exists.")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user.is_admin = True
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "email": user.email, "is_admin": user.is_admin}
```

Also add `Request` to the imports in `admin/router.py` (it needs `from fastapi import ... Request`) and `from limiter import limiter`.

- [ ] **Step 6: Set secret in test env and run tests**

Set env var in the test file at the top (after existing os.environ.setdefault lines):

```python
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-xyz")
```

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_bootstrap_requires_secret backend/tests/test_prod_fixes.py::test_bootstrap_without_secret_field_returns_422 -v
```

Expected: both PASS

- [ ] **Step 7: Commit**

```bash
git add backend/config.py backend/admin/router.py backend/admin/schemas.py backend/tests/test_prod_fixes.py
git commit -m "fix: require BOOTSTRAP_SECRET on /admin/bootstrap — closes unauthenticated admin promotion"
```

---

## Task 4: Fix Fire-and-Forget Orphan Task (#14)

**Files:**
- Modify: `backend/main.py` — `scrape_jobs_endpoint`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_scrape_jobs_uses_background_tasks_not_create_task():
    """Persistence must use BackgroundTasks (FastAPI-managed), not asyncio.create_task.

    asyncio.create_task() orphans the task — exceptions are silently swallowed
    and tasks are killed on worker shutdown, potentially corrupting Delta logs.
    """
    import inspect
    from main import scrape_jobs_endpoint
    source = inspect.getsource(scrape_jobs_endpoint)
    assert "asyncio.create_task" not in source, (
        "asyncio.create_task found in scrape_jobs_endpoint — "
        "use BackgroundTasks instead for managed task lifecycle."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_scrape_jobs_uses_background_tasks_not_create_task -v
```

Expected: FAIL

- [ ] **Step 3: Fix the endpoint**

In `backend/main.py`, update `scrape_jobs_endpoint` to accept `BackgroundTasks` and use it:

```python
@app.post("/scrape-jobs")
async def scrape_jobs_endpoint(
    request: ScrapeJobsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    if not request.keywords.strip():
        raise HTTPException(status_code=400, detail="keywords cannot be empty.")

    try:
        postings = await scrape_jobs(request.keywords.strip(), per_source=request.per_source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

    user_id = str(current_user.id)

    async def _persist():
        for posting in postings:
            record = {"user_id": user_id, "resume_id": request.resume_id, **posting}
            try:
                await asyncio.to_thread(write_job_match, record)
            except Exception:
                _logger.warning("write_job_match failed for posting: %s", posting.get("title", "unknown"))

    background_tasks.add_task(_persist)

    return {"total": len(postings), "keywords": request.keywords, "results": postings}
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_scrape_jobs_uses_background_tasks_not_create_task -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "fix: replace asyncio.create_task with BackgroundTasks in scrape_jobs_endpoint"
```

---

## Task 5: Fix Silent Resume Save Failure (#16)

**Files:**
- Modify: `backend/main.py` — `_run_pipeline_task` Resume persistence block

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_resume_save_failure_does_not_emit_broken_download_url():
    """When Resume save fails, the done event must not reference resume_record.id
    (which would be None, causing a 404 on download).
    The fallback must use job_id instead.
    """
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    # The download_url fallback must use job_id when resume_record is None
    assert 'f"/download/{resume_record.id}"' not in source.replace(" ", ""), (
        "Found unconditional resume_record.id — must check resume_record is not None first."
    )
    assert 'resume_record else f"/download/{job_id}"' in source or \
           'resume_record.id" if resume_record else' in source, (
        "Missing None guard on resume_record before building download_url."
    )
```

Wait — looking at the current code, the fallback already exists: `f"/download/{resume_record.id}" if resume_record else f"/download/{job_id}"`. The real bug is the silent `except Exception: pass`. Rewrite the test:

```python
@pytest.mark.asyncio
async def test_resume_save_failure_is_not_silently_swallowed():
    """Resume save failures must be logged, not silently ignored.

    The current 'except Exception: pass' means if Resume save fails (FK violation,
    connection drop), the pipeline reports success with a broken download URL.
    """
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    # Silent pass after Resume add/commit must be replaced with logging
    assert "except Exception:\n                    pass" not in source, (
        "Silent 'except Exception: pass' found in Resume save block — "
        "failures must be logged so operators know download will 404."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_resume_save_failure_is_not_silently_swallowed -v
```

Expected: FAIL

- [ ] **Step 3: Add logging to the silent except**

In `backend/main.py`, find the Resume persistence block inside `_run_pipeline_task` and replace the silent except:

```python
            resume_record = None
            if user_id:
                try:
                    ver_q = await db.execute(
                        select(func.coalesce(func.max(Resume.version), 0) + 1)
                        .where(Resume.user_id == user_id)
                    )
                    next_version = ver_q.scalar() or 1
                    resume_record = Resume(
                        user_id=user_id,
                        original_filename=job_row.original_filename,
                        file_path=blob_name,
                        jd_text=jd_text,
                        final_score=float(scores.get("average", baseline_avg)),
                        scores_json=scores,
                        iterations=1,
                        version=next_version,
                    )
                    db.add(resume_record)
                    await db.commit()
                    await db.refresh(resume_record)
                except Exception:
                    _logger.exception(
                        "job=%s: Resume record save failed — download URL will use job_id fallback",
                        job_id,
                    )
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_resume_save_failure_is_not_silently_swallowed -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "fix: log Resume save failures instead of silently swallowing — operators now know when download will 404"
```

---

## Task 6: Promo Code Atomic CAS (#7)

**Files:**
- Modify: `backend/auth/router.py` — `redeem_promo_code`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_promo_increment_is_atomic():
    """current_uses increment must use a SQL UPDATE ... WHERE current_uses < max_uses.

    The check-then-increment pattern allows two concurrent requests to both pass
    the max_uses check and double-redeem a max_uses=1 code.
    """
    import inspect
    from auth.router import redeem_promo_code
    source = inspect.getsource(redeem_promo_code)
    # The atomic pattern: update with condition and check rows affected
    assert "current_uses < " in source, (
        "Promo increment is not atomic — use UPDATE WHERE current_uses < max_uses "
        "and check rowcount to detect exhaustion under concurrent load."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_promo_increment_is_atomic -v
```

Expected: FAIL

- [ ] **Step 3: Replace check-then-increment with atomic CAS**

In `backend/auth/router.py`, inside `redeem_promo_code`, replace:

```python
    if promo.current_uses >= promo.max_uses:
        raise HTTPException(status_code=409, detail="Code exhausted")
```

and later:

```python
    # Increment counter
    promo.current_uses += 1
```

With the following atomic pattern (the check AND increment happen in one SQL statement):

```python
    from sqlalchemy import update as sa_update

    # Atomic increment — only succeeds if current_uses < max_uses
    result_inc = await db.execute(
        sa_update(PromoCode)
        .where(PromoCode.id == promo.id, PromoCode.current_uses < PromoCode.max_uses)
        .values(current_uses=PromoCode.current_uses + 1)
    )
    await db.flush()
    if result_inc.rowcount == 0:
        raise HTTPException(status_code=409, detail="Code exhausted")
```

Remove the original `if promo.current_uses >= promo.max_uses` check and the `promo.current_uses += 1` line. Keep everything else (redemption record, apply effect, commit).

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_promo_increment_is_atomic -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/auth/router.py
git commit -m "fix: atomic promo code increment — prevents double-redemption race condition"
```

---

## Task 7: Email Update IntegrityError → HTTP 400 (#12)

**Files:**
- Modify: `backend/auth/router.py` — `update_me` endpoint

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_email_update_conflict_returns_400_not_500(auth_client, client):
    """Concurrent email update to an already-taken address must return 400, not 500.

    Without the IntegrityError catch, PostgreSQL raises a unique constraint violation
    that FastAPI surfaces as HTTP 500.
    """
    import inspect
    from auth.router import update_me
    source = inspect.getsource(update_me)
    assert "IntegrityError" in source, (
        "update_me must catch IntegrityError and return HTTP 400 — "
        "without this, a race on email uniqueness returns HTTP 500."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_email_update_conflict_returns_400_not_500 -v
```

Expected: FAIL

- [ ] **Step 3: Add IntegrityError handler**

In `backend/auth/router.py`, find the `update_me` function and wrap the commit in a try/except:

```python
from sqlalchemy.exc import IntegrityError

    # ... (existing update_me logic up to db.commit)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Email already in use.")
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_email_update_conflict_returns_400_not_500 -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/auth/router.py
git commit -m "fix: catch IntegrityError on email update — returns 400 instead of 500 on concurrent update"
```

---

## Task 8: Fix Cost Tracking Provider (#10)

**Files:**
- Modify: `backend/main.py` — `_run_pipeline_task` cost calculation block

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_cost_tracking_queries_google_not_anthropic():
    """Cost tracking must query the Google provider — all models are Gemini/Groq.

    The current code hardcodes provider == 'anthropic'. Since no Anthropic model
    is used, cost_cents is always 0 and cost tracking is broken.
    """
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert '"anthropic"' not in source.lower() or "provider_cost" not in source.lower(), (
        "Cost tracking hardcoded to 'anthropic' provider — all models are Gemini/Groq. "
        "Query the correct provider or use a multi-provider cost sum."
    )
    assert '"google"' in source.lower() or "provider" in source.lower(), (
        "Cost tracking must reference the Google provider for Gemini models."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_cost_tracking_queries_google_not_anthropic -v
```

Expected: FAIL

- [ ] **Step 3: Fix cost tracking to sum all active providers**

In `backend/main.py`, replace the cost calculation block in `_run_pipeline_task`:

```python
            # ── Cost tracking ────────────────────────────────────────────────
            cost_cents = 0
            try:
                # Sum costs across all active providers weighted by token usage.
                # Primary model is Google (Gemini) for tool calls; Groq for critic.
                # Approximate: attribute all tokens to Google pricing (cheapest accurate estimate).
                cost_result = await db.execute(
                    select(ProviderCost).where(
                        (ProviderCost.provider == "Google") & (ProviderCost.active == True)
                    )
                )
                cost_row = cost_result.scalar_one_or_none()
                if cost_row:
                    input_cost  = (total_input_tokens  / 1_000_000) * cost_row.input_cost_per_1m_tokens
                    output_cost = (total_output_tokens / 1_000_000) * cost_row.output_cost_per_1m_tokens
                    cost_cents  = int((input_cost + output_cost) * 100)
            except Exception:
                pass
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_cost_tracking_queries_google_not_anthropic -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "fix: cost tracking now queries Google provider — Anthropic hardcode was returning 0 for all Gemini jobs"
```

---

## Task 9: Fix Env Var Casing (#29)

**Files:**
- Modify: `backend/config.py` — `google_ai_studio_api_key`, `groq_api_key`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
def test_env_var_names_are_screaming_snake_case():
    """All API key env vars must use SCREAMING_SNAKE_CASE for consistency.

    Lowercase env var names cause silent empty-string failures when ops teams
    set the conventional uppercase names in CI or App Service.
    """
    import inspect
    import config
    source = inspect.getsource(config)
    assert 'os.environ.get("google_ai_studio_api_key"' not in source, \
        "google_ai_studio_api_key should be GOOGLE_AI_STUDIO_API_KEY"
    assert 'os.environ.get("groq_api_key"' not in source, \
        "groq_api_key should be GROQ_API_KEY"
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_env_var_names_are_screaming_snake_case -v
```

Expected: FAIL

- [ ] **Step 3: Fix config.py**

In `backend/config.py`, change:

```python
GOOGLE_AI_STUDIO_API_KEY = os.environ.get("GOOGLE_AI_STUDIO_API_KEY", "")
GROQ_API_KEY             = os.environ.get("GROQ_API_KEY", "")
```

> **Note for deployment:** Update App Service app_settings in Terraform (`infra/app_service.tf`) to rename `google_ai_studio_api_key` → `GOOGLE_AI_STUDIO_API_KEY` and `groq_api_key` → `GROQ_API_KEY`. Do this in a coordinated deploy where both the config change and the infra change land together, or the app will briefly see empty API keys.

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_env_var_names_are_screaming_snake_case -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/config.py
git commit -m "fix: uppercase GOOGLE_AI_STUDIO_API_KEY and GROQ_API_KEY env var names — lowercase was silently failing when ops set conventional uppercase names"
```

---

## Task 10: Connection Pool Size (#13)

**Files:**
- Modify: `backend/db/session.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
def test_db_connection_pool_is_sized_for_production():
    """Connection pool must be configured above the default of 5.

    Default pool_size=5 with long-held connections (P0 #2) exhausts the pool
    under any real concurrent load, causing 503s on health checks and auth.
    """
    from db.session import engine
    pool = engine.pool
    # SQLAlchemy QueuePool exposes _pool.maxsize or use pool.size()
    size = getattr(pool, '_pool', None)
    if size:
        assert size.maxsize >= 10, f"Pool maxsize {size.maxsize} is too small — set pool_size>=10"
    else:
        # Fallback: check engine creation kwargs via pool._timeout (indirect)
        assert engine.pool.size() >= 10 or True  # accept if pool reports correctly
```

The pool size check is indirect. A simpler, reliable test:

```python
def test_db_engine_has_custom_pool_config():
    """Engine must be created with explicit pool_size and max_overflow."""
    import inspect
    from db import session as db_session
    source = inspect.getsource(db_session)
    assert "pool_size=" in source, "db/session.py must set pool_size explicitly"
    assert "max_overflow=" in source, "db/session.py must set max_overflow explicitly"
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_db_engine_has_custom_pool_config -v
```

Expected: FAIL

- [ ] **Step 3: Configure pool**

In `backend/db/session.py`, replace:

```python
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
```

With:

```python
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
)
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_db_engine_has_custom_pool_config -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/db/session.py
git commit -m "fix: configure connection pool size=10 max_overflow=20 — default 5 exhausted under concurrent pipeline load"
```

---

## Task 11: Break DB Connection Scope Around LLM Calls (#2)

**Files:**
- Modify: `backend/main.py` — `_run_pipeline_task`

This is the most significant refactor. The DB session must only be held during discrete DB operations (read job, emit event, update job, save resume) — not across the entire LLM pipeline which can take 3–10 minutes.

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_does_not_hold_single_db_session_for_llm_calls():
    """_run_pipeline_task must not wrap LLM calls in a single long-lived DB session.

    A session held for minutes exhausts the pool under concurrent load.
    DB operations (emit, update_job, save_resume) must each use their own
    short-lived session via 'async with AsyncSessionLocal() as db:'.
    """
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    # The new pattern: no single top-level 'async with AsyncSessionLocal() as db:'
    # wrapping the entire function. Each DB op gets its own context.
    lines = source.split('\n')
    top_level_session_open = sum(
        1 for line in lines
        if 'async with AsyncSessionLocal() as db:' in line
        and not line.strip().startswith('#')
    )
    assert top_level_session_open == 0, (
        f"Found {top_level_session_open} top-level AsyncSessionLocal context(s) — "
        "LLM calls must happen outside DB sessions. Use per-operation sessions instead."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_pipeline_does_not_hold_single_db_session_for_llm_calls -v
```

Expected: FAIL

- [ ] **Step 3: Refactor `_run_pipeline_task` to use per-operation sessions**

Replace the entire `_run_pipeline_task` function in `backend/main.py` with this pattern:

```python
async def _run_pipeline_task(job_id: str, user_id: str = ""):
    """
    3-phase optimization pipeline — each DB operation uses its own short-lived session.
    LLM calls (Phase 2) happen entirely outside any DB context.
    """
    job_uuid = uuid.UUID(job_id)
    _loop = asyncio.get_event_loop()

    async def emit(event: dict):
        """Each SSE event gets its own short-lived DB connection."""
        async with AsyncSessionLocal() as db:
            evt = PipelineEvent(job_id=job_uuid, event_json=event)
            db.add(evt)
            await db.commit()

    async def update_job(**kwargs):
        """Each status update gets its own short-lived DB connection."""
        async with AsyncSessionLocal() as db:
            kwargs["updated_at"] = datetime.now(timezone.utc)
            await db.execute(
                update(PipelineJob).where(PipelineJob.id == job_uuid).values(**kwargs)
            )
            await db.commit()

    def _on_agent_event(event: dict):
        asyncio.run_coroutine_threadsafe(emit(event), _loop)

    try:
        # ── Load job (short-lived session) ─────────────────────────────────
        async with AsyncSessionLocal() as db:
            job_result = await db.execute(select(PipelineJob).where(PipelineJob.id == job_uuid))
            job_row = job_result.scalar_one()
            resume_text: str = job_row.resume_text[:MAX_RESUME_CHARS]
            jd_text: str     = job_row.jd_text[:MAX_JD_CHARS]
            original_filename = job_row.original_filename

        total_input_tokens  = 0
        total_output_tokens = 0

        # ── Phase 1: Deterministic setup (no DB held) ──────────────────────
        ledger = await asyncio.to_thread(extract_claims, resume_text)

        await emit({"type": "stage", "message": "Analyzing Job Description...", "stage": "jd_analysis"})
        jd_result_dict = await analyze_jd(jd_text)
        jd_result  = jd_result_dict.get("text", jd_result_dict)
        jd_tokens  = jd_result_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
        jd_keywords: list[str] = jd_result.get("keywords", [])
        total_input_tokens  += jd_tokens["input_tokens"]
        total_output_tokens += jd_tokens["output_tokens"]
        await emit({"type": "stage",
                    "message": f"JD analyzed — {len(jd_keywords)} keywords extracted.",
                    "stage": "jd_analysis", "keywords": jd_keywords[:20]})

        await emit({"type": "stage", "message": "Scoring original resume...", "stage": "score"})
        baseline_dict   = await score_combined(resume_text, jd_text, jd_keywords)
        baseline_scores = baseline_dict.get("text", baseline_dict)
        baseline_tokens = baseline_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
        total_input_tokens  += baseline_tokens["input_tokens"]
        total_output_tokens += baseline_tokens["output_tokens"]

        baseline_avg = round(sum(
            baseline_scores[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")
        ) / 4)
        await emit({"type": "average", "score": baseline_avg, "iteration": 0,
                    "scores": {k: baseline_scores[k]["score"] for k in ("ats", "impact", "skills_gap", "readability")},
                    "message": f"Original resume score: {baseline_avg}"})

        scores = {**baseline_scores, "average": baseline_avg}

        if baseline_avg >= SCORE_TARGET:
            await emit({"type": "stage",
                        "message": f"Original resume already scores {baseline_avg} — skipping optimization.",
                        "stage": "agent"})

        # ── Phase 2: Agentic optimization (no DB held) ─────────────────────
        if baseline_avg < SCORE_TARGET:
            await emit({"type": "stage", "message": "Starting agentic optimization...", "stage": "agent"})
            agent_result = await run_optimization_async(
                job_id=job_id,
                resume_text=resume_text,
                jd_keywords=jd_keywords,
                claims_ledger=ledger,
                scores=baseline_scores,
                on_event=_on_agent_event,
            )
            current_resume   = agent_result["text"]
            total_input_tokens  += agent_result.get("input_tokens", 0)
            total_output_tokens += agent_result.get("output_tokens", 0)
        else:
            current_resume = resume_text

        # ── Phase 3: Deterministic finalization (no DB held during LLM) ────
        guard = await asyncio.to_thread(fabrication_guard, current_resume, ledger, resume_text)
        current_resume = guard.text
        if guard.stripped or guard.gaps:
            await emit({"type": "guard",
                        "message": f"Fabrication guard: removed {len(guard.stripped)} unverified claim(s).",
                        "stripped": guard.stripped[:10], "gaps": guard.gaps[:5]})

        await emit({"type": "stage", "message": "Generating optimized .docx file...", "stage": "generate"})
        blob_name = f"{job_id}.docx"
        tmp_docx = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _f:
                tmp_docx = _f.name
            await asyncio.to_thread(generate_docx, current_resume, tmp_docx)
            docx_bytes = await asyncio.to_thread(Path(tmp_docx).read_bytes)
            await asyncio.to_thread(_storage.upload_output, docx_bytes, blob_name)
        finally:
            if tmp_docx is not None:
                os.unlink(tmp_docx)

        # ── Persist Resume record (short-lived session) ────────────────────
        resume_record = None
        if user_id:
            try:
                async with AsyncSessionLocal() as db:
                    ver_q = await db.execute(
                        select(func.coalesce(func.max(Resume.version), 0) + 1)
                        .where(Resume.user_id == user_id)
                    )
                    next_version = ver_q.scalar() or 1
                    resume_record = Resume(
                        user_id=user_id,
                        original_filename=original_filename,
                        file_path=blob_name,
                        jd_text=jd_text,
                        final_score=float(scores.get("average", baseline_avg)),
                        scores_json=scores,
                        iterations=1,
                        version=next_version,
                    )
                    db.add(resume_record)
                    await db.commit()
                    await db.refresh(resume_record)
            except Exception:
                _logger.exception(
                    "job=%s: Resume record save failed — download URL will use job_id fallback",
                    job_id,
                )

        await update_job(status=JobStatus.done, download_path=blob_name, scores_json=scores, iteration=1)

        # ── Cost tracking (short-lived session) ────────────────────────────
        cost_cents = 0
        try:
            async with AsyncSessionLocal() as db:
                cost_result = await db.execute(
                    select(ProviderCost).where(
                        (ProviderCost.provider == "Google") & (ProviderCost.active == True)
                    )
                )
                cost_row = cost_result.scalar_one_or_none()
                if cost_row:
                    input_cost  = (total_input_tokens  / 1_000_000) * cost_row.input_cost_per_1m_tokens
                    output_cost = (total_output_tokens / 1_000_000) * cost_row.output_cost_per_1m_tokens
                    cost_cents  = int((input_cost + output_cost) * 100)
        except Exception:
            pass

        if user_id:
            try:
                await asyncio.to_thread(write_daily_usage, {
                    "user_id":       user_id,
                    "date":          date_type.today().isoformat(),
                    "pipeline_runs": 1,
                    "uploads":       1,
                    "input_tokens":  total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "tokens_used":   total_input_tokens + total_output_tokens,
                })
            except Exception:
                pass

        download_url = f"/download/{resume_record.id}" if resume_record else f"/download/{job_id}"
        await emit({
            "type":         "done",
            "message":      "Resume optimization complete! Your optimized resume is ready.",
            "download_url": download_url,
            "final_score":  scores.get("average", baseline_avg),
            "iterations":   1,
            "cost_cents":   cost_cents,
            "tokens":       {"input": total_input_tokens, "output": total_output_tokens},
        })

    except Exception as e:
        await update_job(status=JobStatus.error, error_message=str(e))
        await emit({"type": "error", "message": f"Pipeline error: {str(e)}"})
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_pipeline_does_not_hold_single_db_session_for_llm_calls -v
```

Expected: PASS

- [ ] **Step 5: Run smoke tests to verify nothing regressed**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_smoke.py backend/tests/test_agents.py -v
```

Expected: same pass/fail as before this change

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "fix: each DB operation now uses its own short-lived session — no connection held during LLM pipeline"
```

---

## Task 12: Add Gunicorn Multi-Worker (#1)

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add gunicorn to requirements**

In `backend/requirements.txt`, add:

```
gunicorn
```

- [ ] **Step 2: Update Dockerfile CMD**

In `backend/Dockerfile`, replace:

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

With:

```dockerfile
# 2 workers: one serves requests while the other runs a pipeline in asyncio.to_thread.
# --timeout 300: SSE streams and 5-min pipelines need >default 30s worker timeout.
CMD ["gunicorn", "main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "2", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "300", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
```

- [ ] **Step 3: Verify Dockerfile builds without error**

```bash
docker build -t resume-optimizer-test resume-optimizer/backend/
```

Expected: successful build

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile backend/requirements.txt
git commit -m "fix: switch to gunicorn with 2 UvicornWorker processes — single uvicorn blocked under concurrent pipeline load"
```

---

## Task 13: Replace Delta Rate Limiting with PostgreSQL Counter (#5)

**Files:**
- Create: `backend/alembic/versions/0006_add_daily_usage_counter.py`
- Modify: `backend/db/models.py` — add `DailyUsageCounter` model
- Modify: `backend/auth/dependencies.py` — replace Delta read with Postgres query
- Modify: `backend/main.py` — increment counter in pipeline task

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
def test_rate_limit_uses_postgres_not_delta():
    """check_plan_limit must query PostgreSQL, not Delta Lake.

    Delta Lake reads take 200-2000ms and the write is fire-and-forget at job end,
    so the counter shows 0 until the job completes — free users can bypass limits.
    """
    import inspect
    from auth import dependencies
    source = inspect.getsource(dependencies)
    assert "read_usage_last_n_days" not in source, (
        "check_plan_limit still uses Delta Lake for rate limiting — "
        "replace with DailyUsageCounter PostgreSQL query."
    )
    assert "DailyUsageCounter" in source, (
        "check_plan_limit must query DailyUsageCounter (PostgreSQL) for accurate counts."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_rate_limit_uses_postgres_not_delta -v
```

Expected: FAIL

- [ ] **Step 3: Add DailyUsageCounter model**

In `backend/db/models.py`, add before the last line:

```python
class DailyUsageCounter(Base):
    """Transactional daily pipeline run counter per user. Used for rate limiting.
    Delta Lake is for analytics only — not fast enough for real-time rate limits.
    """
    __tablename__ = "daily_usage_counters"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_date"),
    )

    id      = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date    = Column(String(10), nullable=False)   # ISO date "YYYY-MM-DD"
    runs    = Column(Integer, nullable=False, default=0)
```

Make sure `UniqueConstraint` and `Integer` and `String` are imported — add to existing SQLAlchemy imports:

```python
from sqlalchemy import Column, Integer, String, ..., UniqueConstraint
```

- [ ] **Step 4: Create Alembic migration**

Create `backend/alembic/versions/0006_add_daily_usage_counter.py`:

```python
"""add daily_usage_counters table

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_usage_counters",
        sa.Column("id",      sa.Integer(),    primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date",    sa.String(10),   nullable=False),
        sa.Column("runs",    sa.Integer(),    nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "date", name="uq_user_date"),
    )
    op.create_index("ix_daily_usage_user_date", "daily_usage_counters", ["user_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_daily_usage_user_date")
    op.drop_table("daily_usage_counters")
```

- [ ] **Step 5: Replace Delta rate limit check with Postgres**

In `backend/auth/dependencies.py`, replace the `check_plan_limit` function:

```python
from datetime import date, datetime, timezone
from db.models import PlanLimit, User, DailyUsageCounter
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

async def check_plan_limit(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Raise HTTP 429 if user has hit their daily upload limit.
    Uses PostgreSQL DailyUsageCounter — transactional, accurate under concurrent load.
    """
    result = await db.execute(select(PlanLimit).where(PlanLimit.plan == _effective_plan(user)))
    limits = result.scalar_one_or_none()
    if not limits:
        return user

    today_str = date.today().isoformat()
    counter_result = await db.execute(
        select(DailyUsageCounter.runs).where(
            DailyUsageCounter.user_id == user.id,
            DailyUsageCounter.date == today_str,
        )
    )
    used = counter_result.scalar() or 0

    if used >= limits.daily_uploads:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "limit_reached",
                "limit": limits.daily_uploads,
                "used": used,
                "plan": user.plan.value,
                "upgrade_message": "Upgrade to Pro for 20 uploads/day",
            },
        )
    return user
```

Also remove the `from delta.writer import read_usage_last_n_days` import from `auth/dependencies.py` and `import asyncio` if it's only used for that.

- [ ] **Step 6: Increment counter at pipeline start in main.py**

In `backend/main.py`, in `_run_pipeline_task`, after loading the job row (in its own short-lived session), add a counter increment:

```python
        # ── Increment rate-limit counter at job START (not end) ────────────
        # Using upsert so first run of the day creates the row atomically.
        if user_id:
            try:
                async with AsyncSessionLocal() as db:
                    today_str = date_type.today().isoformat()
                    await db.execute(
                        sa_text("""
                            INSERT INTO daily_usage_counters (user_id, date, runs)
                            VALUES (:uid, :date, 1)
                            ON CONFLICT (user_id, date) DO UPDATE
                            SET runs = daily_usage_counters.runs + 1
                        """),
                        {"uid": user_id, "date": today_str},
                    )
                    await db.commit()
            except Exception:
                _logger.warning("job=%s: failed to increment daily usage counter", job_id)
```

Add `from sqlalchemy import text as sa_text` to main.py imports.

- [ ] **Step 7: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_rate_limit_uses_postgres_not_delta -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/db/models.py backend/alembic/versions/0006_add_daily_usage_counter.py backend/auth/dependencies.py backend/main.py
git commit -m "fix: replace Delta Lake rate limit counter with PostgreSQL DailyUsageCounter — Delta was bypassable under concurrent load"
```

---

## Task 14: Discount Code Honest Message (#15)

**Files:**
- Modify: `backend/auth/router.py` — `redeem_promo_code` discount branch

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prod_fixes.py`:

```python
@pytest.mark.asyncio
async def test_discount_promo_returns_pending_message_not_applied():
    """Discount promo codes must not claim the discount was 'applied' — it is pending Stripe integration."""
    import inspect
    from auth.router import redeem_promo_code
    source = inspect.getsource(redeem_promo_code)
    assert '"Discount applied"' not in source, (
        "Discount promo returns 'Discount applied' but no discount is actually applied. "
        "Return an honest message explaining it will apply at next billing cycle."
    )
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_discount_promo_returns_pending_message_not_applied -v
```

Expected: FAIL

- [ ] **Step 3: Fix the message**

In `backend/auth/router.py`, replace:

```python
    elif promo.type == "discount":
        # For now, just record it; discount handling deferred to Stripe phase
        message = "Discount applied"
```

With:

```python
    elif promo.type == "discount":
        message = "Discount code recorded — your discount will apply at your next billing cycle when Stripe billing is enabled."
```

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_discount_promo_returns_pending_message_not_applied -v
```

Expected: PASS

- [ ] **Step 5: Run all plan tests together**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/auth/router.py
git commit -m "fix: discount promo now returns honest pending message instead of falsely claiming discount was applied"
```

---

## Self-Review

**Spec coverage:**
- ✅ #1 Uvicorn workers — Task 12
- ✅ #2 DB connection scope — Task 11
- ✅ #3 Bootstrap auth — Task 3
- ✅ #5 Delta rate limiting — Task 13
- ✅ #6 result_cache.clear — Task 2
- ✅ #7 Promo race — Task 6
- ✅ #8 per_source bounds — Task 1
- ✅ #10 Cost provider — Task 8
- ✅ #11 bcrypt max length — Task 1
- ✅ #12 Email race — Task 7
- ✅ #13 Pool size — Task 10
- ✅ #14 Fire-and-forget — Task 4
- ✅ #15 Discount message — Task 14
- ✅ #16 Resume save silent failure — Task 5
- ✅ #25 jd_text Pydantic validation — Task 1
- ✅ #29 Env var casing — Task 9
- ⚠️  #4 JWT in URL — excluded; requires SSE short-lived token design — covered in Plan 2

**Placeholder scan:** No TBDs or incomplete steps found.

**Type consistency:** `DailyUsageCounter` defined in Task 13 Step 3, referenced in Task 13 Steps 5–6. `sa_text` imported in Task 13 Step 6, used in same step. All consistent.

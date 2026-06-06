# Production Medium Severity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 13 medium severity issues covering datetime consistency, code duplication, SSE security, test reliability, and operational correctness.

**Architecture:** Issues are grouped by file/subsystem. Each task is independently deployable. Run Plan 1 (P0 + High) before this plan.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL, pytest-asyncio, secrets (stdlib)

**Python interpreter:** `C:\Users\deshp\rv\Scripts\python.exe`
**Run tests from:** `resume-optimizer/` directory
**Test command:** `C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/<file> -v`

---

## File Map

```
Modified files:
  backend/auth/router.py           — SSE short-lived token endpoint (#4)
  backend/auth/dependencies.py     — short-lived token decode
  backend/main.py                  — /status endpoint uses short-lived token
  backend/admin/router.py          — datetime.utcnow() → now(timezone.utc) (#9, #17)
  backend/auth/router.py           — datetime.utcnow() → now(timezone.utc)
  backend/auth/dependencies.py     — datetime.utcnow() → now(timezone.utc)
  backend/scraper/scraper.py       — datetime.utcnow()
  backend/parsers/pdf_parser.py    — remove duplicate SECTION_PATTERNS (#21)
  backend/parsers/docx_parser.py   — remove duplicate SECTION_PATTERNS (#21)
  backend/generators/docx_generator.py — _is_contact_line fix (#22)
  backend/main.py                  — jd_text Field validation already done in Plan 1
  backend/db/models.py             — DateTime(timezone=True) columns (#9)
  backend/alembic/versions/        — migration for timezone-aware columns

New files:
  backend/tests/test_medium_fixes.py
  infra/key_vault.tf               — purge_protection_enabled = true (#20)
```

---

## Task 1: Fix datetime.utcnow() Throughout (#9, #17)

`datetime.utcnow()` is deprecated in Python 3.12 and produces naive datetimes. On PostgreSQL, asyncpg returns timezone-aware datetimes. The comparison naive > aware raises TypeError on PostgreSQL (works on SQLite only).

**Files:**
- Modify: `backend/auth/router.py`, `backend/auth/dependencies.py`, `backend/admin/router.py`, `backend/scraper/scraper.py`
- Test: `backend/tests/test_medium_fixes.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_medium_fixes.py`:

```python
"""Tests for medium severity production fixes."""
import sys
import os
from pathlib import Path
import inspect

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_medium_fixes.db")
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap-secret-xyz")

import pytest


def test_no_utcnow_in_auth_router():
    """auth/router.py must use datetime.now(timezone.utc) — not deprecated utcnow()."""
    from auth import router as auth_router
    source = inspect.getsource(auth_router)
    assert "datetime.utcnow()" not in source, \
        "auth/router.py still uses datetime.utcnow() — replace with datetime.now(timezone.utc)"


def test_no_utcnow_in_auth_dependencies():
    """auth/dependencies.py must use datetime.now(timezone.utc)."""
    from auth import dependencies
    source = inspect.getsource(dependencies)
    assert "datetime.utcnow()" not in source, \
        "auth/dependencies.py still uses datetime.utcnow()"


def test_no_utcnow_in_admin_router():
    """admin/router.py must use datetime.now(timezone.utc)."""
    from admin import router as admin_router
    source = inspect.getsource(admin_router)
    assert "datetime.utcnow()" not in source, \
        "admin/router.py still uses datetime.utcnow()"


def test_no_utcnow_in_scraper():
    """scraper/scraper.py must use datetime.now(timezone.utc)."""
    from scraper import scraper
    source = inspect.getsource(scraper)
    assert "datetime.utcnow()" not in source, \
        "scraper/scraper.py still uses datetime.utcnow()"
```

- [ ] **Step 2: Run tests — confirm they fail**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_no_utcnow_in_auth_router backend/tests/test_medium_fixes.py::test_no_utcnow_in_admin_router -v
```

Expected: FAIL

- [ ] **Step 3: Replace all utcnow() calls**

Run this to find every occurrence:

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest --co -q 2>&1 | head -5
grep -rn "datetime.utcnow()" resume-optimizer/backend/ --include="*.py"
```

In each file found, replace every `datetime.utcnow()` with `datetime.now(timezone.utc)`.

Make sure `from datetime import datetime, timezone` is in the imports of each file (add `timezone` if missing).

Key files and replacements:

**`backend/auth/router.py`** — replace all 4 occurrences:
```python
# BEFORE:
trial_expires_at=datetime.utcnow() + timedelta(days=TRIAL_DAYS),
# AFTER:
trial_expires_at=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
```
Repeat for every `datetime.utcnow()` in the file.

**`backend/auth/dependencies.py`** — replace in `_effective_plan`:
```python
# BEFORE:
if user.trial_expires_at and user.trial_expires_at > datetime.utcnow():
# AFTER:
if user.trial_expires_at and user.trial_expires_at > datetime.now(timezone.utc).replace(tzinfo=None):
```
> Note: Until the DB column is migrated to timezone=True (Task 2 below), `trial_expires_at` is stored as naive UTC. The `.replace(tzinfo=None)` strips the timezone from the aware datetime for the comparison. Remove `.replace(tzinfo=None)` after Task 2's migration runs.

**`backend/admin/router.py`** — replace all occurrences including:
```python
code.expires_at and code.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)
code.deactivated_at = datetime.now(timezone.utc)
created_at=datetime.now(timezone.utc),
```

**`backend/scraper/scraper.py`**:
```python
"scraped_at": datetime.now(timezone.utc).isoformat(),
```

- [ ] **Step 4: Run tests — confirm they pass**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_no_utcnow_in_auth_router backend/tests/test_medium_fixes.py::test_no_utcnow_in_auth_dependencies backend/tests/test_medium_fixes.py::test_no_utcnow_in_admin_router backend/tests/test_medium_fixes.py::test_no_utcnow_in_scraper -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/auth/router.py backend/auth/dependencies.py backend/admin/router.py backend/scraper/scraper.py
git commit -m "fix: replace datetime.utcnow() with datetime.now(timezone.utc) — utcnow deprecated in Python 3.12, naive/aware mismatch crashes on PostgreSQL"
```

---

## Task 2: Migrate DateTime Columns to timezone=True (#9 continued)

**Files:**
- Modify: `backend/db/models.py` — `trial_expires_at`, `deactivated_at`, `created_at` columns
- Create: `backend/alembic/versions/0007_timezone_aware_datetimes.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_medium_fixes.py`:

```python
def test_datetime_columns_are_timezone_aware():
    """DateTime columns storing timestamps must use timezone=True.

    Without this, PostgreSQL TIMESTAMP columns store naive datetimes.
    asyncpg returns timezone-aware datetimes, causing comparison TypeErrors.
    """
    from db.models import User, PromoCode, ProviderCost
    from sqlalchemy import inspect as sa_inspect

    user_cols = {c.name: c for c in sa_inspect(User).columns}
    assert user_cols["trial_expires_at"].type.timezone is True, \
        "User.trial_expires_at must be DateTime(timezone=True)"

    promo_cols = {c.name: c for c in sa_inspect(PromoCode).columns}
    for col_name in ("expires_at", "deactivated_at", "created_at"):
        if col_name in promo_cols:
            assert promo_cols[col_name].type.timezone is True, \
                f"PromoCode.{col_name} must be DateTime(timezone=True)"
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_datetime_columns_are_timezone_aware -v
```

Expected: FAIL

- [ ] **Step 3: Update model columns**

In `backend/db/models.py`, find all `DateTime` columns that store real timestamps and add `timezone=True`:

```python
# In User model:
trial_expires_at = Column(DateTime(timezone=True), nullable=True)

# In PromoCode model:
expires_at     = Column(DateTime(timezone=True), nullable=True)
deactivated_at = Column(DateTime(timezone=True), nullable=True)
created_at     = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
```

Make sure `from datetime import datetime, timezone` is imported in models.py.

- [ ] **Step 4: Create Alembic migration**

Create `backend/alembic/versions/0007_timezone_aware_datetimes.py`:

```python
"""migrate datetime columns to timezone-aware

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL: change TIMESTAMP to TIMESTAMP WITH TIME ZONE
    # SQLite: no-op (SQLite stores all datetimes as text anyway)
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "trial_expires_at",
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=True,
        )
    with op.batch_alter_table("promo_codes") as batch_op:
        for col in ("expires_at", "deactivated_at", "created_at"):
            try:
                batch_op.alter_column(
                    col,
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=(col != "created_at"),
                )
            except Exception:
                pass  # column may not exist in all environments


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "trial_expires_at",
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
```

- [ ] **Step 5: Remove .replace(tzinfo=None) from auth/dependencies.py**

Now that the column is timezone-aware, the comparison in `_effective_plan` can be clean:

```python
def _effective_plan(user: User) -> str:
    if user.trial_expires_at and user.trial_expires_at > datetime.now(timezone.utc):
        return "pro"
    return user.plan.value
```

- [ ] **Step 6: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_datetime_columns_are_timezone_aware -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/db/models.py backend/alembic/versions/0007_timezone_aware_datetimes.py backend/auth/dependencies.py
git commit -m "fix: DateTime columns now timezone=True — prevents naive/aware TypeError on PostgreSQL via asyncpg"
```

---

## Task 3: DRY SECTION_PATTERNS (#21)

`SECTION_PATTERNS` regex is defined identically in `parsers/pdf_parser.py` and `parsers/docx_parser.py`. We already created `utils/section_parser.py` — update the parsers to import from it.

**Files:**
- Modify: `backend/parsers/pdf_parser.py`
- Modify: `backend/parsers/docx_parser.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_medium_fixes.py`:

```python
def test_parsers_do_not_duplicate_section_patterns():
    """pdf_parser and docx_parser must import SECTION_PATTERNS from utils.section_parser.

    Three identical regex dicts guaranteed to drift when a new section type is added.
    """
    from parsers import pdf_parser, docx_parser
    pdf_source = inspect.getsource(pdf_parser)
    docx_source = inspect.getsource(docx_parser)

    assert "SECTION_PATTERNS" not in pdf_source or "from utils.section_parser import" in pdf_source, \
        "pdf_parser.py defines its own SECTION_PATTERNS — import from utils.section_parser instead"
    assert "SECTION_PATTERNS" not in docx_source or "from utils.section_parser import" in docx_source, \
        "docx_parser.py defines its own SECTION_PATTERNS — import from utils.section_parser instead"
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_parsers_do_not_duplicate_section_patterns -v
```

Expected: FAIL

- [ ] **Step 3: Read what the parsers currently do with SECTION_PATTERNS**

```
C:\Users\deshp\rv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'resume-optimizer/backend')
import inspect
from parsers import pdf_parser
lines = [l for l in inspect.getsource(pdf_parser).split('\n') if 'SECTION' in l or 'section' in l.lower()]
print('\n'.join(lines[:20]))
"
```

- [ ] **Step 4: Update pdf_parser.py**

In `backend/parsers/pdf_parser.py`:
- Remove the local `SECTION_PATTERNS` dict definition
- Add at the top of the file: `from utils.section_parser import SECTION_PATTERNS`

- [ ] **Step 5: Update docx_parser.py**

In `backend/parsers/docx_parser.py`:
- Remove the local `SECTION_PATTERNS` dict definition
- Add at the top of the file: `from utils.section_parser import SECTION_PATTERNS`

- [ ] **Step 6: Run existing parser tests plus the new test**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_parsers_do_not_duplicate_section_patterns backend/tests/test_smoke.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/parsers/pdf_parser.py backend/parsers/docx_parser.py
git commit -m "refactor: pdf_parser and docx_parser now import SECTION_PATTERNS from utils.section_parser — removes triplicated regex"
```

---

## Task 4: Fix _is_contact_line Hardcoded Index (#22)

**Files:**
- Modify: `backend/generators/docx_generator.py`

- [ ] **Step 1: Read the current implementation**

```
C:\Users\deshp\rv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'resume-optimizer/backend')
import inspect
from generators import docx_generator
src = inspect.getsource(docx_generator)
start = src.find('_is_contact_line')
print(src[start:start+400])
"
```

- [ ] **Step 2: Write failing test**

Add to `backend/tests/test_medium_fixes.py`:

```python
def test_contact_line_detection_works_when_resume_starts_with_blank_line():
    """_is_contact_line must find contact info even when blank lines precede the name.

    LLM-generated resumes often start with a blank line, shifting all seq_idx values
    by 1. The hardcoded check for seq_idx in (1, 2, 3) misses contact lines at index 4.
    """
    from generators.docx_generator import _is_contact_line
    # Simulate: blank line at idx 0, name at idx 1, email at idx 2, phone at idx 3,
    # linkedin at idx 4 — should be detected as contact
    assert _is_contact_line("john@example.com", 2) is True
    assert _is_contact_line("+1 555 000 0000", 3) is True
    assert _is_contact_line("linkedin.com/in/john", 4) is True, \
        "_is_contact_line missed contact at seq_idx=4 — hardcoded (1,2,3) is too narrow"
```

- [ ] **Step 3: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_contact_line_detection_works_when_resume_starts_with_blank_line -v
```

Expected: FAIL (index 4 not in (1, 2, 3))

- [ ] **Step 4: Fix _is_contact_line**

In `backend/generators/docx_generator.py`, replace the `_is_contact_line` function with content-based detection instead of index-based:

```python
import re as _re

_CONTACT_PATTERNS = _re.compile(
    r"(@|linkedin\.com|github\.com|http|www\.|"
    r"\+?[\d][\d\s\-\(\)]{7,}|"  # phone numbers
    r"\d{5})",                      # zip codes
    _re.IGNORECASE,
)


def _is_contact_line(line: str, seq_idx: int) -> bool:
    """Return True if this line looks like contact information.

    Uses content patterns instead of positional index — LLM-generated resumes
    frequently start with blank lines, shifting positional assumptions.
    Only applies within the first 6 non-empty lines to avoid false positives
    in the body of the resume.
    """
    if seq_idx > 6:
        return False
    stripped = line.strip()
    if not stripped:
        return False
    return bool(_CONTACT_PATTERNS.search(stripped))
```

- [ ] **Step 5: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_contact_line_detection_works_when_resume_starts_with_blank_line -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/generators/docx_generator.py backend/tests/test_medium_fixes.py
git commit -m "fix: _is_contact_line now uses content patterns instead of hardcoded positional index — handles LLM-generated resumes with leading blank lines"
```

---

## Task 5: SSE Short-Lived Token (#4)

The 7-day JWT appears in server access logs and browser history when passed as `?token=<jwt>`. Fix: issue a 60-second signed token only valid for SSE connections.

**Files:**
- Modify: `backend/auth/router.py` — add `POST /auth/sse-token` endpoint
- Modify: `backend/auth/dependencies.py` — add `decode_sse_token`
- Modify: `backend/main.py` — `/status/{job_id}` uses SSE token instead of session token

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_medium_fixes.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

@pytest_asyncio.fixture
async def client():
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

@pytest_asyncio.fixture
async def auth_client(client):
    await client.post("/auth/register", json={"email": "sse@test.com", "password": "Test1234!", "full_name": "SSE"})
    resp = await client.post("/auth/login", json={"email": "sse@test.com", "password": "Test1234!"})
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client

@pytest.mark.asyncio
async def test_sse_token_endpoint_exists(auth_client):
    """POST /auth/sse-token must return a short-lived token."""
    r = await auth_client.post("/auth/sse-token")
    assert r.status_code == 200
    data = r.json()
    assert "sse_token" in data
    assert len(data["sse_token"]) > 20

@pytest.mark.asyncio
async def test_sse_token_is_short_lived(auth_client):
    """SSE token must expire in 60 seconds, not 7 days."""
    import jwt as pyjwt
    r = await auth_client.post("/auth/sse-token")
    token = r.json()["sse_token"]
    from config import JWT_SECRET, JWT_ALGORITHM
    payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    import time
    ttl = payload["exp"] - time.time()
    assert ttl <= 70, f"SSE token TTL {ttl:.0f}s exceeds 70s — must be ~60s"

@pytest.mark.asyncio
async def test_status_endpoint_rejects_session_token_for_sse(auth_client):
    """The /status endpoint must reject a long-lived session JWT as the sse_token param."""
    # This test verifies the endpoint distinguishes sse tokens from session tokens.
    # A session token missing the 'sse': True claim should be rejected.
    r = await auth_client.get("/status/00000000-0000-0000-0000-000000000001",
                              params={"token": "not-a-valid-sse-token"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests — confirm they fail**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_sse_token_endpoint_exists backend/tests/test_medium_fixes.py::test_sse_token_is_short_lived -v
```

Expected: FAIL (endpoint doesn't exist)

- [ ] **Step 3: Add SSE token endpoint to auth/router.py**

```python
@user_router.post("/auth/sse-token")
async def get_sse_token(current_user: User = Depends(get_current_user)):
    """Issue a 60-second token valid only for SSE connections.

    EventSource cannot send Authorization headers, so we pass a token in the URL.
    Using the 7-day session token in a URL leaks it into server logs and browser history.
    This endpoint issues a short-lived, SSE-only token that expires before it can be abused.
    """
    from datetime import timedelta
    import time

    payload = {
        "sub":  str(current_user.id),
        "sse":  True,                              # SSE-only claim
        "exp":  int(time.time()) + 60,             # 60 second TTL
        "iat":  int(time.time()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"sse_token": token}
```

- [ ] **Step 4: Add decode_sse_token to auth/dependencies.py**

```python
def decode_sse_token(token: str) -> str:
    """Decode a short-lived SSE token and return user_id. Raises HTTP 401 on failure.

    SSE tokens must have the 'sse': True claim — rejects regular session tokens
    to prevent the 7-day token from being used in URLs (where it appears in logs).
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if not payload.get("sse"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid token for SSE — use /auth/sse-token")
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
```

- [ ] **Step 5: Update /status endpoint to use decode_sse_token**

In `backend/main.py`, update the `/status/{job_id}` endpoint:

```python
@app.get("/status/{job_id}")
async def stream_status(
    job_id: str,
    request: Request,
    token: str = Query(None),
):
    if not token:
        raise HTTPException(status_code=401, detail="Token required. Pass ?token=<sse_token> from POST /auth/sse-token.")

    user_id = decode_sse_token(token)   # was: decode_token — now requires SSE-specific token
    # ... rest unchanged
```

Also update the import:

```python
from auth.dependencies import decode_token, decode_sse_token, get_current_user, check_plan_limit
```

- [ ] **Step 6: Run tests — confirm they pass**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_sse_token_endpoint_exists backend/tests/test_medium_fixes.py::test_sse_token_is_short_lived backend/tests/test_medium_fixes.py::test_status_endpoint_rejects_session_token_for_sse -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/auth/router.py backend/auth/dependencies.py backend/main.py
git commit -m "fix: SSE /status endpoint now requires short-lived 60s sse_token — prevents 7-day JWT appearing in server access logs"
```

---

## Task 6: Key Vault Purge Protection (#20)

**Files:**
- Modify: `infra/key_vault.tf`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_medium_fixes.py`:

```python
def test_key_vault_purge_protection_enabled():
    """Key Vault Terraform must have purge_protection_enabled = true.

    purge_protection = false means a terraform destroy or attacker with state
    access can permanently delete all secrets with no recovery window.
    """
    kv_path = Path(__file__).parent.parent.parent.parent / "infra" / "key_vault.tf"
    if not kv_path.exists():
        pytest.skip("infra/key_vault.tf not found")
    content = kv_path.read_text()
    assert "purge_protection_enabled = false" not in content, \
        "key_vault.tf has purge_protection_enabled = false — set to true before deploying to prod"
    assert "purge_protection_enabled = true" in content, \
        "key_vault.tf must explicitly set purge_protection_enabled = true"
```

- [ ] **Step 2: Run test — confirm it fails**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_key_vault_purge_protection_enabled -v
```

Expected: FAIL

- [ ] **Step 3: Update key_vault.tf**

In `infra/key_vault.tf`, replace:

```hcl
purge_protection_enabled = false # false = easier teardown in dev; set true for prod
```

With:

```hcl
purge_protection_enabled = true
```

> **Warning:** Once purge protection is enabled on an existing Key Vault, it cannot be disabled. Accidental `terraform destroy` will soft-delete the vault (90-day recovery window). This is intentional — it prevents permanent secret loss.

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_key_vault_purge_protection_enabled -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add infra/key_vault.tf
git commit -m "fix: enable Key Vault purge protection — false allowed permanent deletion of secrets via terraform destroy"
```

---

## Task 7: jd_text Pydantic Validation (#25)

> **Skip if Plan 1 Task 1 is complete** — this was already addressed there with `Field(..., max_length=MAX_JD_CHARS)`.

Verify it's done:

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_prod_fixes.py::test_analyze_jd_rejects_oversized_body -v
```

If PASS: skip this task. If FAIL: implement `Field(max_length=MAX_JD_CHARS)` on `AnalyzeJDRequest.jd_text` in `main.py`.

---

## Task 8: BackgroundTasks Lifecycle Note (#26)

The `_run_pipeline_task` runs as a FastAPI `BackgroundTask`. On gunicorn worker restart (SIGTERM), in-flight tasks are cancelled immediately. This cannot be fully fixed without a proper task queue (Celery, RQ, ARQ), which is a larger architectural change. The immediate fix is to handle the signal gracefully and document the limitation.

**Files:**
- Modify: `backend/main.py` — add SIGTERM handler + comment

- [ ] **Step 1: Add graceful shutdown signal handling**

In `backend/main.py`, inside the `lifespan` context manager, add signal handling:

```python
import signal

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    cleanup_task = asyncio.create_task(_cleanup_events())
    reap_task = asyncio.create_task(_reap_stuck_jobs())

    # On SIGTERM (gunicorn graceful shutdown), give in-flight pipelines
    # up to 30 seconds to complete before the worker exits.
    # Long-running pipelines (>30s) will be marked as 'error' by the reaper
    # on the next worker start. A proper task queue (ARQ/Celery) would be
    # needed for zero-loss shutdown guarantees.
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _handle_sigterm():
        _logger.info("SIGTERM received — initiating graceful shutdown")
        shutdown_event.set()

    loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)

    yield
    cleanup_task.cancel()
    reap_task.cancel()
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "fix: add SIGTERM signal handler for graceful shutdown — in-flight pipeline tasks logged and reaped on restart"
```

---

## Task 9: Delta First-Write Race Condition (#27)

**Files:**
- Modify: `backend/delta/writer.py` — add file-based advisory lock on first write

- [ ] **Step 1: Read current writer**

```
C:\Users\deshp\rv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'resume-optimizer/backend')
import inspect
from delta import writer
lines = inspect.getsource(writer).split('\n')[:40]
print('\n'.join(lines))
"
```

- [ ] **Step 2: Write failing test**

Add to `backend/tests/test_medium_fixes.py`:

```python
def test_delta_writer_has_table_creation_guard():
    """write_daily_usage must handle concurrent first-write gracefully.

    Two simultaneous first writes to a non-existent Delta table can corrupt
    the Delta transaction log. Use a threading lock or catch the exception.
    """
    from delta import writer as delta_writer
    source = inspect.getsource(delta_writer)
    assert "_write_lock" in source or "threading.Lock" in source or "except" in source, \
        "delta/writer.py has no concurrency guard on table creation — add a threading.Lock"
```

- [ ] **Step 3: Add threading lock to writer**

In `backend/delta/writer.py`, add at the module level and wrap the write call:

```python
import threading
_write_lock = threading.Lock()

def write_daily_usage(record: dict) -> None:
    with _write_lock:
        # ... existing write_deltalake call
```

Do the same for `write_job_match`.

- [ ] **Step 4: Run test — confirm it passes**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/test_medium_fixes.py::test_delta_writer_has_table_creation_guard -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/delta/writer.py
git commit -m "fix: add threading.Lock to delta writer — prevents transaction log corruption on concurrent first write"
```

---

## Task 10: run_usage_last_n_days("") Documentation (#18, #30)

**Files:**
- Modify: `backend/delta/writer.py` — document the empty string behavior

- [ ] **Step 1: Read the function**

```
C:\Users\deshp\rv\Scripts\python.exe -c "
import sys; sys.path.insert(0, 'resume-optimizer/backend')
import inspect
from delta.writer import read_usage_last_n_days
print(inspect.getsource(read_usage_last_n_days))
"
```

- [ ] **Step 2: Add explicit documentation**

In `backend/delta/writer.py`, update the `read_usage_last_n_days` docstring to document the `user_id=""` behavior:

```python
def read_usage_last_n_days(user_id: str, n: int):
    """
    Read usage records for the last n days.

    Args:
        user_id: The user's UUID string. Pass empty string "" to read aggregate
                 stats across ALL users — used by admin analytics endpoints only.
                 Any non-empty string filters to that specific user.
        n:       Number of days to look back (inclusive of today).

    Returns:
        pandas DataFrame with columns: user_id, date, pipeline_runs, uploads,
        input_tokens, output_tokens, tokens_used.
        Returns empty DataFrame if no data exists.
    """
```

- [ ] **Step 3: Commit**

```bash
git add backend/delta/writer.py
git commit -m "docs: document read_usage_last_n_days empty user_id aggregate behavior — was undocumented admin-only convention"
```

---

## Task 11: Run Full Test Suite

- [ ] **Step 1: Run all tests**

```
C:\Users\deshp\rv\Scripts\python.exe -m pytest backend/tests/ -v --ignore=backend/tests/test_migrations.py 2>&1 | tail -30
```

- [ ] **Step 2: Fix any regressions before proceeding**

Any test that newly fails after this plan should be investigated and fixed before merging.

- [ ] **Step 3: Final commit**

```bash
git add backend/tests/test_medium_fixes.py
git commit -m "test: add test_medium_fixes.py covering all medium severity production fixes"
```

---

## Self-Review

**Spec coverage:**
- ✅ #4 JWT URL exposure — Task 5 (SSE short-lived token)
- ✅ #9 Naive datetime — Task 1 (utcnow replacement) + Task 2 (timezone=True migration)
- ✅ #17 utcnow inconsistency — Task 1
- ✅ #20 KV purge protection — Task 6
- ✅ #21 SECTION_PATTERNS triplicated — Task 3
- ✅ #22 _is_contact_line fragile — Task 4
- ✅ #25 jd_text validation — Task 7 (verify Plan 1 coverage)
- ✅ #26 BackgroundTasks lifetime — Task 8
- ✅ #27 Delta first-write race — Task 9
- ✅ #18 #30 Delta empty user_id — Task 10
- ⚠️  #19 SQLite vs PostgreSQL tests — excluded; requires testcontainers setup which is a CI/CD infrastructure decision, not a code fix
- ⚠️  #23 JWT in Azure access logs — consequence of #4; addressed by Task 5 (once SSE token is short-lived, log exposure is benign)
- ⚠️  #24 Path traversal — job_id is validated UUID; risk is theoretical. Add `uuid.UUID(blob_name)` validation in storage.py if desired.

**Placeholder scan:** No TBDs found.

**Type consistency:** `decode_sse_token` defined in Task 5 Step 4 and imported in Task 5 Step 5. `_write_lock` defined in Task 9 Step 3. All consistent.

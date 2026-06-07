# Block E — Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured JSON logging with per-request correlation IDs to the FastAPI backend and wire Azure Log Analytics to capture and retain those logs for 7 days.

**Architecture:** A new `logging_config.py` module configures the root Python logger with `JsonFormatter` (called once at startup before any other imports). A `LoggingMiddleware` class wraps every non-health request: generates a UUID `request_id`, times the call, logs `{method, path, status_code, latency_ms, request_id}` as JSON, and injects `X-Request-ID` in the response. On the infrastructure side, a new `monitoring.tf` provisions a Log Analytics Workspace and a diagnostic setting that forwards App Service console logs to it.

**Tech Stack:** python-json-logger 2.0.7, Starlette BaseHTTPMiddleware, Terraform azurerm (Log Analytics workspace + diagnostic setting)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `resume-optimizer/requirements.txt` | Add `python-json-logger>=2.0.7` |
| Modify | `resume-optimizer/backend/config.py` | Add `LOG_LEVEL` env var |
| Create | `resume-optimizer/backend/logging_config.py` | `setup_logging()` — root logger → JSON stdout |
| Modify | `resume-optimizer/backend/main.py` | Call `setup_logging()`, add `LoggingMiddleware`, `import time` |
| Create | `resume-optimizer/backend/tests/test_logging.py` | `X-Request-ID` header tests |
| Create | `resume-optimizer/infra/monitoring.tf` | Log Analytics workspace + diagnostic setting |
| Modify | `resume-optimizer/infra/app_service.tf` | Remove `WEBSITE_HTTPLOGGING_RETENTION_DAYS` |

---

## Task 1: Python structured logging + request middleware (TDD)

**Files:**
- Modify: `resume-optimizer/requirements.txt`
- Modify: `resume-optimizer/backend/config.py`
- Create: `resume-optimizer/backend/logging_config.py`
- Modify: `resume-optimizer/backend/main.py`
- Create: `resume-optimizer/backend/tests/test_logging.py`

### Context

`main.py` current structure (key lines):
- Line 12: stdlib imports include `import logging` but NOT `import time` — add `import time`
- Line 20: `sys.path.insert(0, str(Path(__file__).parent))` — call `setup_logging()` immediately after this
- Line 72: `_logger = logging.getLogger(__name__)` — already exists, reused by `LoggingMiddleware`
- Line 121: `app = FastAPI(...)` — put `LoggingMiddleware` class definition before this
- Line 134: `app.add_middleware(SlowAPIMiddleware)` — add `app.add_middleware(LoggingMiddleware)` after this line

`config.py` ends around line 77. Add `LOG_LEVEL` after the Rate limiting section (line 79).

`requirements.txt` — add `python-json-logger>=2.0.7` after the `slowapi` line.

- [ ] **Step 1: Create `tests/test_logging.py` (write tests first — TDD)**

Create `resume-optimizer/backend/tests/test_logging.py`:

```python
"""Tests for LoggingMiddleware — X-Request-ID header presence."""
import os
import sys
import uuid

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_logging.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base
from db.session import get_db
from main import app

TEST_DB_URL = "sqlite+aiosqlite:///./test_logging.db"
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
        os.remove("./test_logging.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_request_id_header_present(client):
    """Non-health requests get X-Request-ID in the response."""
    r = await client.post("/auth/login", json={"email": "x@x.com", "password": "wrong"})
    assert "x-request-id" in r.headers
    uuid.UUID(r.headers["x-request-id"])  # raises ValueError if not a valid UUID


@pytest.mark.asyncio
async def test_health_has_no_request_id(client):
    """Health endpoint is excluded from LoggingMiddleware — no X-Request-ID header."""
    r = await client.get("/health")
    assert "x-request-id" not in r.headers
```

- [ ] **Step 2: Run tests — verify they FAIL**

```
cd resume-optimizer
python -m pytest backend/tests/test_logging.py -v --tb=short 2>&1 | tail -15
```

Expected: `FAILED test_request_id_header_present` — `AssertionError: 'x-request-id' not in {'content-type': ..., ...}` (header absent because middleware doesn't exist yet).

- [ ] **Step 3: Add `LOG_LEVEL` to `config.py`**

In `resume-optimizer/backend/config.py`, after the `RATE_LIMIT_AUTH` line, add:

```python
# ── Observability ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
```

- [ ] **Step 4: Add `python-json-logger` to `requirements.txt`**

In `resume-optimizer/requirements.txt`, add after the `slowapi>=0.1.9` line:

```
python-json-logger>=2.0.7
```

- [ ] **Step 5: Create `backend/logging_config.py`**

Create `resume-optimizer/backend/logging_config.py`:

```python
import logging
import sys

from pythonjsonlogger.jsonlogger import JsonFormatter

from config import LOG_LEVEL


def setup_logging() -> None:
    """Configure root logger to emit structured JSON on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    root.handlers = [handler]
```

- [ ] **Step 6: Update `main.py` — add `import time`, call `setup_logging()`, add `LoggingMiddleware`**

**6a.** Add `import time` to the stdlib imports block (after `import sys`, around line 12):

```python
import time
```

**6b.** After `sys.path.insert(0, str(Path(__file__).parent))` (line 20), add:

```python
from logging_config import setup_logging
setup_logging()
```

**6c.** After the existing SlowAPI imports (after `from limiter import limiter`, around line 28), add:

```python
from starlette.middleware.base import BaseHTTPMiddleware
```

**6d.** Before `app = FastAPI(...)` (before line 121), add the `LoggingMiddleware` class:

```python
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        _logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response
```

**6e.** After `app.add_middleware(SlowAPIMiddleware)` (line 134), add:

```python
app.add_middleware(LoggingMiddleware)
```

- [ ] **Step 7: Run tests — verify they PASS**

```
cd resume-optimizer
python -m pytest backend/tests/test_logging.py -v --tb=short 2>&1 | tail -15
```

Expected: `2 passed`

- [ ] **Step 8: Run import smoke test**

```
cd resume-optimizer/backend
python -c "import main; print('ok')"
```

Expected: `ok`

- [ ] **Step 9: Commit**

```bash
git add resume-optimizer/requirements.txt \
        resume-optimizer/backend/config.py \
        resume-optimizer/backend/logging_config.py \
        resume-optimizer/backend/main.py \
        resume-optimizer/backend/tests/test_logging.py
git commit -m "feat: structured JSON logging + X-Request-ID middleware"
```

---

## Task 2: Terraform — Log Analytics workspace + diagnostic setting

**Files:**
- Create: `resume-optimizer/infra/monitoring.tf`
- Modify: `resume-optimizer/infra/app_service.tf`

### Context

`app_service.tf` line 66: `WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"` — delete this line; Log Analytics replaces it.

No Terraform state changes for existing resources — `monitoring.tf` only creates new resources. `app_service.tf` change is a settings removal on the existing web app (Terraform will update in place).

- [ ] **Step 1: Create `infra/monitoring.tf`**

Create `resume-optimizer/infra/monitoring.tf`:

```hcl
# ── Log Analytics Workspace ───────────────────────────────────────────────────
# Receives App Service console logs (structured JSON stdout) and HTTP access logs.
# 7-day retention keeps costs near zero on student credit.
# PerGB2018: first 5 GB/month free, ~$2.30/GB after.

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.prefix}-logs"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 7
  tags                = local.tags
}

# ── Diagnostic Setting — App Service → Log Analytics ─────────────────────────
# AppServiceConsoleLogs: stdout/stderr from the Python process (our JSON logs).
# AppServiceHTTPLogs:    platform-level HTTP access log (redundant backup).

resource "azurerm_monitor_diagnostic_setting" "app_service" {
  name                       = "${local.prefix}-app-diag"
  target_resource_id         = azurerm_linux_web_app.backend.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "AppServiceConsoleLogs"
  }

  enabled_log {
    category = "AppServiceHTTPLogs"
  }
}
```

- [ ] **Step 2: Remove `WEBSITE_HTTPLOGGING_RETENTION_DAYS` from `app_service.tf`**

In `resume-optimizer/infra/app_service.tf`, delete line 66:

```hcl
    WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"
```

The `app_settings` block should now end with `WEBSITES_PORT = "8000"` before the closing brace.

- [ ] **Step 3: Format (if Terraform CLI is available)**

```
cd resume-optimizer/infra
terraform fmt 2>&1 || echo "terraform not installed — skipping"
```

- [ ] **Step 4: Commit**

```bash
git add resume-optimizer/infra/monitoring.tf \
        resume-optimizer/infra/app_service.tf
git commit -m "feat: Log Analytics workspace + App Service diagnostic setting (7-day retention)"
```

---

## Task 3: Final verification + push

- [ ] **Step 1: Run logging tests in isolation**

```
cd resume-optimizer
python -m pytest backend/tests/test_logging.py -v --tb=short 2>&1 | tail -10
```

Expected: `2 passed`

- [ ] **Step 2: Run full backend test suite**

```
cd resume-optimizer
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: logging tests pass (2 new). Pre-existing cross-module DB isolation failures remain unchanged and are acceptable.

- [ ] **Step 3: Verify git log**

```
git log --oneline -5
```

Expected (most recent first):
```
feat: Log Analytics workspace + App Service diagnostic setting (7-day retention)
feat: structured JSON logging + X-Request-ID middleware
```

- [ ] **Step 4: Push**

```
git push origin backend_design
```

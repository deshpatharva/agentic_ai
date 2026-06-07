# Block D — Rate Limiting & Postgres VNet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SlowAPI rate limiting on `/auth/login` and `/auth/register` (5/minute per IP) and move the PostgreSQL Flexible Server to private-access VNet mode via Terraform.

**Architecture:** A standalone `limiter.py` module exports the SlowAPI singleton (avoids circular imports since `main.py` imports from `auth/router.py`). Rate limit decorators on the two auth endpoints rename the Pydantic body param to `body` and add `request: Request` as the first arg, which SlowAPI requires to read the client IP. The Terraform changes create a new `vnet.tf` with a VNet, two delegated subnets, and a private DNS zone; `postgres.tf` switches to private-access mode (destroy+recreate on apply); `app_service.tf` gains VNet integration.

**Tech Stack:** Python/FastAPI, slowapi 0.1.9, limits (transitive), SQLAlchemy 2.0 async, pytest-asyncio, Terraform azurerm provider

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `resume-optimizer/requirements.txt` | Add `slowapi>=0.1.9` |
| Create | `resume-optimizer/backend/limiter.py` | SlowAPI Limiter singleton |
| Modify | `resume-optimizer/backend/config.py` | Add `RATE_LIMIT_AUTH` env var |
| Modify | `resume-optimizer/backend/main.py` | Register SlowAPI middleware + exception handler |
| Modify | `resume-optimizer/backend/auth/router.py` | Add `@limiter.limit` on login + register; rename body param |
| Modify | `resume-optimizer/backend/tests/conftest.py` | Add autouse fixture to reset limiter storage between tests |
| Create | `resume-optimizer/backend/tests/test_ratelimit.py` | Rate limit tests (TDD) |
| Create | `resume-optimizer/infra/vnet.tf` | VNet, subnets, private DNS zone |
| Modify | `resume-optimizer/infra/postgres.tf` | Add private-access fields; remove public firewall rule |
| Modify | `resume-optimizer/infra/app_service.tf` | Add `virtual_network_subnet_id` |

---

## Task 1: SlowAPI foundation — `limiter.py`, `config.py`, `requirements.txt`, `main.py`

**Files:**
- Create: `resume-optimizer/backend/limiter.py`
- Modify: `resume-optimizer/backend/config.py`
- Modify: `resume-optimizer/requirements.txt`
- Modify: `resume-optimizer/backend/main.py`

### Context

`main.py` currently imports `from auth.router import router as auth_router`. If `auth/router.py` imported back from `main.py`, that's a circular import and Python would crash at startup. Putting the `Limiter` singleton in its own `limiter.py` file breaks the cycle: `main.py` and `auth/router.py` both import from `limiter.py`, which imports nothing from the app.

Current `main.py` relevant lines:
- Line 117: `app = FastAPI(title="Resume Optimizer API", version="1.0.0", lifespan=lifespan)`
- Lines 121–127: `app.add_middleware(CORSMiddleware, ...)`
- Lines 129–131: `app.include_router(...)` calls

Current `config.py` ends at line 77 (Stripe section). Add `RATE_LIMIT_AUTH` at line 76, before Stripe.

- [ ] **Step 1: Create `backend/limiter.py`**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

- [ ] **Step 2: Add `RATE_LIMIT_AUTH` to `config.py`**

In `resume-optimizer/backend/config.py`, after the `OUTPUTS_CONTAINER` line (line 74) and before the Stripe section, add:

```python
# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_AUTH = os.environ.get("RATE_LIMIT_AUTH", "5/minute")
```

- [ ] **Step 3: Add `slowapi` to `requirements.txt`**

In `resume-optimizer/requirements.txt`, add after the `httpx` line:

```
slowapi>=0.1.9
```

- [ ] **Step 4: Wire SlowAPI into `main.py`**

**4a.** In the imports section of `main.py`, add these three lines after the existing `from fastapi.middleware.cors import CORSMiddleware` import:

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from limiter import limiter
```

**4b.** After `app.add_middleware(CORSMiddleware, ...)` (after line 127), add:

```python
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
```

- [ ] **Step 5: Verify `main.py` imports without errors**

```
cd resume-optimizer/backend
python -c "import main; print('ok')"
```

Expected: `ok` (no ImportError)

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/limiter.py \
        resume-optimizer/backend/config.py \
        resume-optimizer/requirements.txt \
        resume-optimizer/backend/main.py
git commit -m "feat: add SlowAPI rate limiting foundation"
```

---

## Task 2: Auth rate-limit decorators + tests (TDD)

**Files:**
- Modify: `resume-optimizer/backend/auth/router.py`
- Modify: `resume-optimizer/backend/tests/conftest.py`
- Create: `resume-optimizer/backend/tests/test_ratelimit.py`

### Context

Current `auth/router.py` imports: `from fastapi import APIRouter, Depends, HTTPException, status` and `from config import JWT_ALGORITHM, JWT_EXPIRE_DAYS, JWT_SECRET`.

Current `register` signature (line 77): `async def register(request: RegisterRequest, db: ...)` — internally uses `request.email`, `request.password`, `request.full_name`.

Current `login` signature (line 99): `async def login(request: LoginRequest, db: ...)` — internally uses `request.email`, `request.password`.

SlowAPI requires a `fastapi.Request` object as a parameter named `request` (or any name — it searches by type annotation). Because the param name `request` is already taken by the Pydantic body, rename the Pydantic param to `body` and add `request: Request` as the first parameter.

`conftest.py` currently only sets `sys.path`. It needs an `autouse` fixture to reset the in-memory rate-limit counters before every test, otherwise repeated calls to `/auth/login` across tests accumulate and trigger 429 unexpectedly in non-rate-limit tests.

- [ ] **Step 1: Update `conftest.py`**

Replace `resume-optimizer/backend/tests/conftest.py` entirely with:

```python
import sys
from pathlib import Path

import pytest_asyncio

# Makes backend/ importable as root when pytest runs from resume-optimizer/
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest_asyncio.fixture(autouse=True)
async def reset_rate_limits():
    """Reset in-memory rate-limit counters before every test.

    Prevents counts from one test bleeding into another — especially important
    for test_admin.py which calls /auth/register and /auth/login in fixtures.
    """
    from main import app
    if hasattr(app.state, "limiter") and hasattr(app.state.limiter, "_storage"):
        app.state.limiter._storage.reset()
    yield
```

- [ ] **Step 2: Create `tests/test_ratelimit.py` (write tests first — TDD)**

Create `resume-optimizer/backend/tests/test_ratelimit.py`:

```python
"""Rate limit tests for /auth/login and /auth/register."""
import os
import sys

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_ratelimit.db")
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

TEST_DB_URL = "sqlite+aiosqlite:///./test_ratelimit.db"
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
        os.remove("./test_ratelimit.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_rate_limit(client):
    """6th login attempt within a minute returns 429."""
    payload = {"email": "noone@test.com", "password": "wrongpass"}
    for i in range(5):
        r = await client.post("/auth/login", json=payload)
        assert r.status_code == 401, f"Expected 401 on attempt {i + 1}, got {r.status_code}"
    r = await client.post("/auth/login", json=payload)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_register_rate_limit(client):
    """6th register attempt within a minute returns 429."""
    for i in range(5):
        r = await client.post("/auth/register", json={
            "email": f"ratelimit_spam{i}@test.com",
            "password": "Test1234!",
            "full_name": "Spam",
        })
        assert r.status_code in (200, 400), f"Expected 200/400 on attempt {i + 1}, got {r.status_code}"
    r = await client.post("/auth/register", json={
        "email": "ratelimit_spam5@test.com",
        "password": "Test1234!",
        "full_name": "Spam",
    })
    assert r.status_code == 429
```

- [ ] **Step 3: Run tests — verify they FAIL**

```
cd resume-optimizer
python -m pytest backend/tests/test_ratelimit.py -v --tb=short 2>&1 | tail -20
```

Expected: both tests fail — `AssertionError: assert 401 == 429` on `test_login_rate_limit` and `AssertionError: assert 200 == 429` (or 400) on `test_register_rate_limit`, because the `@limiter.limit` decorator hasn't been applied yet.

- [ ] **Step 4: Update `auth/router.py`**

Make these changes to `resume-optimizer/backend/auth/router.py`:

**4a.** Change the FastAPI import line (line 7):

Old:
```python
from fastapi import APIRouter, Depends, HTTPException, status
```

New:
```python
from fastapi import APIRouter, Depends, HTTPException, Request, status
```

**4b.** Add these two lines after the existing `from config import ...` line (line 14):

```python
from config import RATE_LIMIT_AUTH
from limiter import limiter
```

**4c.** Replace the `register` endpoint (lines 76–95) with:

```python
@router.post("/register", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered.")

    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    user = User(
        email=body.email,
        password_hash=pwd_context.hash(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = _make_token(str(user.id))
    return TokenResponse(access_token=token, user=_user_dict(user))
```

**4d.** Replace the `login` endpoint (lines 98–113) with:

```python
@router.post("/login", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    result2 = await db.execute(select(PlanLimit).where(PlanLimit.plan == user.plan.value))
    limits = result2.scalar_one_or_none()

    token = _make_token(str(user.id))
    return TokenResponse(access_token=token, user=_user_dict(user, limits))
```

- [ ] **Step 5: Run tests — verify they PASS**

```
cd resume-optimizer
python -m pytest backend/tests/test_ratelimit.py -v --tb=short 2>&1 | tail -20
```

Expected: `2 passed`

- [ ] **Step 6: Run full backend test suite to confirm no regressions**

```
cd resume-optimizer
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all previously passing tests still pass. New rate limit tests pass. Pre-existing Windows teardown noise acceptable.

- [ ] **Step 7: Commit**

```bash
git add resume-optimizer/backend/auth/router.py \
        resume-optimizer/backend/tests/conftest.py \
        resume-optimizer/backend/tests/test_ratelimit.py
git commit -m "feat: rate limit /auth/login and /auth/register at 5/minute per IP"
```

---

## Task 3: Terraform VNet — create `vnet.tf`, update `postgres.tf` and `app_service.tf`

**Files:**
- Create: `resume-optimizer/infra/vnet.tf`
- Modify: `resume-optimizer/infra/postgres.tf`
- Modify: `resume-optimizer/infra/app_service.tf`

### Context

`postgres.tf` currently has these resources:
1. `azurerm_postgresql_flexible_server.main` — needs `delegated_subnet_id` + `private_dns_zone_id` added
2. `azurerm_postgresql_flexible_server_database.app` — unchanged
3. `azurerm_postgresql_flexible_server_firewall_rule.allow_azure_services` — **REMOVE ENTIRELY** (incompatible with private-access mode; Terraform errors if it exists alongside `delegated_subnet_id`)
4. Commented `allow_local` block — leave as-is
5. `azurerm_postgresql_flexible_server_configuration.extensions` — unchanged

`app_service.tf` resource `azurerm_linux_web_app.backend` needs one new top-level attribute added: `virtual_network_subnet_id`.

**⚠️ Destroy+recreate warning:** Adding `delegated_subnet_id` to `azurerm_postgresql_flexible_server` forces Terraform to destroy and recreate the server. This is safe for new/dev environments. For production with existing data: take a pg_dump backup first, apply Terraform, then restore the dump.

- [ ] **Step 1: Create `infra/vnet.tf`**

Create `resume-optimizer/infra/vnet.tf`:

```hcl
# ── Virtual Network ───────────────────────────────────────────────────────────

resource "azurerm_virtual_network" "main" {
  name                = "${local.prefix}-vnet"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.0.0.0/16"]
  tags                = local.tags
}

# ── Postgres subnet — delegated to PostgreSQL Flexible Server ─────────────────
# Flexible Server requires a dedicated delegated subnet; no other resources
# can be deployed into this subnet.

resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]

  delegation {
    name = "postgres-delegation"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# ── App Service subnet ────────────────────────────────────────────────────────
# Regional VNet integration requires a dedicated subnet delegated to
# Microsoft.Web/serverFarms. Minimum /27 (32 addresses) recommended.

resource "azurerm_subnet" "app_service" {
  name                 = "app-service"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.2.0/24"]

  delegation {
    name = "app-service-delegation"
    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

# ── Private DNS zone for Postgres ─────────────────────────────────────────────
# Required for Flexible Server private access.
# Inside the VNet, <server>.postgres.database.azure.com resolves to the
# server's private IP via this zone — DATABASE_URL in Key Vault is unchanged.

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "${local.prefix}-postgres-dns-link"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.tags
}
```

- [ ] **Step 2: Update `postgres.tf` — add private-access fields**

In `resume-optimizer/infra/postgres.tf`, in the `azurerm_postgresql_flexible_server.main` resource block, add these two lines after `zone = "1"` (after line 12):

```hcl
  delegated_subnet_id = azurerm_subnet.postgres.id
  private_dns_zone_id = azurerm_private_dns_zone.postgres.id
```

- [ ] **Step 3: Update `postgres.tf` — remove public firewall rule**

In `resume-optimizer/infra/postgres.tf`, delete the entire `azurerm_postgresql_flexible_server_firewall_rule.allow_azure_services` resource block (lines 49–54):

```hcl
# DELETE THIS ENTIRE BLOCK:
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}
```

Leave the commented `allow_local` block and the `extensions` configuration unchanged.

- [ ] **Step 4: Update `app_service.tf` — add VNet integration**

In `resume-optimizer/infra/app_service.tf`, in the `azurerm_linux_web_app.backend` resource block, add this line after `https_only = true` (after line 21):

```hcl
  virtual_network_subnet_id = azurerm_subnet.app_service.id
```

- [ ] **Step 5: Format Terraform files**

If Terraform CLI is installed:
```
cd resume-optimizer/infra
terraform fmt
```

If not installed, skip — CI will handle formatting checks.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/infra/vnet.tf \
        resume-optimizer/infra/postgres.tf \
        resume-optimizer/infra/app_service.tf
git commit -m "feat: Postgres private-access VNet + App Service VNet integration"
```

---

## Task 4: Final verification + push

- [ ] **Step 1: Run complete backend test suite**

```
cd resume-optimizer
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: rate limit tests pass (2 new), all previously passing tests still pass. Pre-existing Windows teardown noise acceptable.

- [ ] **Step 2: Verify git log shows all Block D commits**

```
git log --oneline -6
```

Expected (most recent first):
```
feat: Postgres private-access VNet + App Service VNet integration
feat: rate limit /auth/login and /auth/register at 5/minute per IP
feat: add SlowAPI rate limiting foundation
```

- [ ] **Step 3: Push to origin**

```
git push origin backend_design
```

# Block D — Rate Limiting & Postgres VNet: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Block D adds two independent production security layers:

1. **Rate limiting** — SlowAPI middleware protecting `/auth/login` and `/auth/register` from brute-force and account-creation spam. 5 requests/minute per client IP, configurable via env var.
2. **Postgres VNet integration** — Moves the PostgreSQL Flexible Server from public-access mode (firewall to all Azure services) to private-access mode inside a dedicated VNet. App Service connects via regional VNet integration. No public Postgres endpoint after this change.

These are independent: rate limiting is application code, VNet is pure Terraform.

---

## Section 1: Rate Limiting

### Approach

SlowAPI is the FastAPI-native rate limiting library built on the `limits` package. It integrates via a `Limiter` singleton registered as ASGI middleware. Decorators on individual route handlers set per-endpoint limits. In-memory backend — no Redis required for a single App Service instance. Limits reset on process restart, which is acceptable here.

### New file: `backend/limiter.py`

Isolates the singleton to avoid circular imports (`main.py` already imports from `auth/router.py`; if `auth/router.py` imported from `main.py`, the import cycle would crash at startup).

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

### `config.py`

Add one new setting after the input guards section:

```python
# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_AUTH = os.environ.get("RATE_LIMIT_AUTH", "5/minute")
```

### `main.py` — middleware registration

After `app = FastAPI(...)`:

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from limiter import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
```

The exception handler returns HTTP 429 with body `{"error": "Rate limit exceeded: 5 per 1 minute"}`.

### `auth/router.py` — endpoint decorators

Both `register` and `login` currently use `request` as the parameter name for the Pydantic body model. SlowAPI requires a `fastapi.Request` object to be present in the function signature (to read `request.client.host`). Rename the Pydantic body param to `body` and add `request: Request` as the first parameter.

```python
from fastapi import Request
from limiter import limiter
from config import RATE_LIMIT_AUTH

@router.post("/register", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # use body.email, body.password, body.full_name (was request.email etc.)
    ...

@router.post("/login", response_model=TokenResponse)
@limiter.limit(RATE_LIMIT_AUTH)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    # use body.email, body.password (was request.email etc.)
    ...
```

Internal references to `request.email`, `request.password`, `request.full_name` in both handlers must be updated to `body.*`.

### `requirements.txt`

Add:
```
slowapi>=0.1.9
```

### Testing: `tests/test_ratelimit.py`

Isolated test file. Verifies the 6th login attempt within one minute returns 429.

Setup: use the existing test DB pattern (`sqlite+aiosqlite`). The limiter uses `request.client.host` as the key — in HTTPX test client, this is `testclient`. Reset the limiter's in-memory storage in a per-test `autouse` fixture so counts don't bleed between tests.

```python
@pytest_asyncio.fixture(autouse=True)
async def reset_limiter():
    app.state.limiter._storage.reset()
    yield
```

Tests:
- `test_login_rate_limit`: call `/auth/login` 6 times in a loop; first 5 return 401 (wrong password), 6th returns 429
- `test_register_rate_limit`: call `/auth/register` 6 times with unique emails; first 5 succeed or return 400 (duplicate), 6th returns 429

---

## Section 2: Postgres VNet Integration

### Approach

Azure PostgreSQL Flexible Server supports two connectivity modes set at creation time:
- **Public access** — server has a public endpoint; IP-based firewall rules control access
- **Private access** — server is deployed into a delegated VNet subnet; no public endpoint; DNS resolves via a private DNS zone

Currently the server uses public access with `0.0.0.0/0.0.0.0` ("allow all Azure services"). This change moves it to private access.

**⚠️ Terraform will destroy and recreate the Postgres server.** This is safe for fresh/dev deployments. For production with existing data: take a manual backup → apply Terraform (new server) → restore backup → run `alembic stamp head` on the new server.

### New file: `infra/vnet.tf`

```hcl
# ── Virtual Network ───────────────────────────────────────────────────────────

resource "azurerm_virtual_network" "main" {
  name                = "${local.prefix}-vnet"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.0.0.0/16"]
  tags                = local.tags
}

# ── Postgres subnet (delegated to PostgreSQL Flexible Server) ─────────────────

resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]

  delegation {
    name = "postgres-delegation"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

# ── App Service subnet ────────────────────────────────────────────────────────

resource "azurerm_subnet" "app_service" {
  name                 = "app-service"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.2.0/24"]

  delegation {
    name = "app-service-delegation"
    service_delegation {
      name = "Microsoft.Web/serverFarms"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/action",
      ]
    }
  }
}

# ── Private DNS zone for Postgres ─────────────────────────────────────────────
# Required for Flexible Server private access.
# Within the VNet, <server>.postgres.database.azure.com resolves to the private IP.

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

### `infra/postgres.tf` — changes

Add to `azurerm_postgresql_flexible_server.main`:
```hcl
delegated_subnet_id = azurerm_subnet.postgres.id
private_dns_zone_id = azurerm_private_dns_zone.postgres.id
```

Remove the `azurerm_postgresql_flexible_server_firewall_rule.allow_azure_services` resource entirely — it is incompatible with private-access mode and Terraform will error if it's left in.

No change to the `azurerm_postgresql_flexible_server_database.app` resource or the extensions configuration.

### `infra/app_service.tf` — changes

Add one line to `azurerm_linux_web_app.backend`:
```hcl
virtual_network_subnet_id = azurerm_subnet.app_service.id
```

This enables regional VNet integration so the App Service's outbound traffic flows through the `app_service` subnet, which can reach the Postgres server's private IP via the VNet.

### DATABASE_URL — no change required

The private DNS zone (`privatelink.postgres.database.azure.com`) is linked to the VNet. From within the VNet, `<server>.postgres.database.azure.com` resolves to the server's private IP. The DATABASE_URL in Key Vault uses this hostname already — no update needed.

---

## Files Changed

| Action | Path |
|---|---|
| Modify | `resume-optimizer/requirements.txt` |
| Create | `resume-optimizer/backend/limiter.py` |
| Modify | `resume-optimizer/backend/config.py` |
| Modify | `resume-optimizer/backend/main.py` |
| Modify | `resume-optimizer/backend/auth/router.py` |
| Create | `resume-optimizer/backend/tests/test_ratelimit.py` |
| Create | `resume-optimizer/infra/vnet.tf` |
| Modify | `resume-optimizer/infra/postgres.tf` |
| Modify | `resume-optimizer/infra/app_service.tf` |

---

## Security Notes

- Rate limit key is `request.client.host` (client IP). Behind a reverse proxy (Azure Front Door, App Gateway), this may be the proxy IP. If that becomes an issue, switch `key_func` to `get_remote_address` with `X-Forwarded-For` stripping via Trusted Hosts middleware — out of scope here.
- SlowAPI in-memory backend: limits reset on App Service restart. Acceptable for single-instance deployment.
- Postgres private access: no public endpoint. The only path to the server is through the VNet. App Service → VNet subnet → Postgres private IP.
- DATABASE_URL still contains credentials — stored in Key Vault, injected at runtime. The VNet adds network-layer isolation on top.

## Out of Scope

- Block E (observability — structured logging, metrics)
- Block F (agent unit tests)
- Block G.2–G.5 (promo codes, free trials, cost tracking, analytics)
- Global catch-all rate limit (login/register only was chosen)
- `X-Forwarded-For` trust configuration (proxy header handling)
- Storage Account network ACLs

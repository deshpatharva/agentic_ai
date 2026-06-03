# Block E — Observability: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Block E adds structured JSON logging to the FastAPI backend and wires Azure Log Analytics to capture and retain those logs for 7 days. Every HTTP request is logged with method, path, status code, latency, and a per-request correlation ID. Logs are queryable via KQL in Azure Portal within minutes of being emitted.

## Scope

- Structured JSON logging via `python-json-logger` (replaces default Python logging format)
- Per-request `LoggingMiddleware` that logs latency + injects `X-Request-ID` response header
- Azure Log Analytics Workspace (7-day retention, PerGB2018 SKU)
- Diagnostic setting on App Service forwarding `AppServiceConsoleLogs` + `AppServiceHTTPLogs` to the workspace
- Remove redundant `WEBSITE_HTTPLOGGING_RETENTION_DAYS` app setting

## Out of Scope

- Application Insights (traces, live metrics, smart alerts) — future Block E.2
- OpenTelemetry distributed tracing
- Custom metrics / dashboards
- Alerting rules

---

## Section 1: Python — Structured Logging + Request Middleware

### `config.py`

Add one new setting after the Rate limiting section:

```python
# ── Observability ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
```

### New file: `backend/logging_config.py`

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

`setup_logging()` is called once at the top of `main.py` (before `app = FastAPI(...)`) so all loggers — including SQLAlchemy, uvicorn, and app-level — emit JSON.

### `main.py` — `LoggingMiddleware`

Added as a `BaseHTTPMiddleware` subclass, registered after `SlowAPIMiddleware`:

```python
from starlette.middleware.base import BaseHTTPMiddleware
import time

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

`/health` is excluded — App Service probes it every 30 seconds and logging it would add ~2,880 log entries/day of noise.

### `requirements.txt`

Add:
```
python-json-logger>=2.0.7
```

### Testing: `tests/test_logging.py`

One test: make a GET request to `/health` (no log emitted) and a POST to `/auth/login` (log emitted), assert `X-Request-ID` header is present and is a valid UUID on the non-health endpoint.

```python
@pytest.mark.asyncio
async def test_request_id_header_present(client):
    r = await client.post("/auth/login", json={"email": "x@x.com", "password": "wrong"})
    assert "x-request-id" in r.headers
    # validate it's a UUID
    uuid.UUID(r.headers["x-request-id"])

@pytest.mark.asyncio
async def test_health_has_no_request_id(client):
    r = await client.get("/health")
    assert "x-request-id" not in r.headers
```

---

## Section 2: Terraform — Log Analytics + Diagnostic Settings

### New file: `infra/monitoring.tf`

```hcl
# ── Log Analytics Workspace ───────────────────────────────────────────────────
# Receives App Service console logs (our structured JSON) and HTTP access logs.
# 7-day retention keeps costs near zero on student credit.
# PerGB2018 SKU: first 5 GB/month free, then ~$2.30/GB.

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
# AppServiceHTTPLogs:    platform-level HTTP access log (backup / cross-check).

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

### `infra/app_service.tf` — remove redundant setting

Remove `WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"` from `app_settings` in `azurerm_linux_web_app.backend`. Log Analytics replaces this; keeping both creates confusing dual retention.

### Querying logs in Azure Portal

After deployment, navigate to **Log Analytics Workspace → Logs** and run:

```kql
AppServiceConsoleLogs
| where TimeGenerated > ago(7d)
| project TimeGenerated, ResultDescription
| order by TimeGenerated desc
```

`ResultDescription` contains the raw JSON line. Parse fields with `parse_json()`:

```kql
AppServiceConsoleLogs
| extend log = parse_json(ResultDescription)
| project TimeGenerated, level=log.levelname, path=log.path, status=log.status_code, latency=log.latency_ms, request_id=log.request_id
| where status >= 400
| order by TimeGenerated desc
```

---

## Files Changed

| Action | Path |
|---|---|
| Modify | `resume-optimizer/requirements.txt` |
| Modify | `resume-optimizer/backend/config.py` |
| Create | `resume-optimizer/backend/logging_config.py` |
| Modify | `resume-optimizer/backend/main.py` |
| Create | `resume-optimizer/backend/tests/test_logging.py` |
| Create | `resume-optimizer/infra/monitoring.tf` |
| Modify | `resume-optimizer/infra/app_service.tf` |

---

## Security Notes

- `X-Request-ID` is generated server-side (UUID v4). Client-supplied `X-Request-ID` headers are ignored — no header injection risk.
- Log entries contain method, path, status code, and latency only. Request bodies, passwords, and tokens are never logged.
- Log Analytics workspace uses Azure RBAC; access is restricted to the subscription owner by default.

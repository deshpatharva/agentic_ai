# Azure App Service Deployment — Errors & Fixes

First-time deployment of the resume-optimizer FastAPI app to Azure dev environment (App Service B1, Linux, Python 3.12, PostgreSQL Flexible Server).

---

## Error 1 — Migration 0009 PostgreSQL Syntax Crash

### Symptom

App crashed silently 8–38 seconds after startup, always at migration `0009`. No Python traceback appeared in `containerStream.log`. All 9 migrations re-ran on every restart because Alembic's `alembic_version` table was never committed.

### Root Cause

Invalid PostgreSQL syntax in [backend/alembic/versions/0009_normalize_provider_names.py](../backend/alembic/versions/0009_normalize_provider_names.py):

```sql
-- BROKEN
ALTER TABLE provider_costs ADD CONSTRAINT IF NOT EXISTS chk_provider_lower
CHECK (provider = lower(provider))
```

PostgreSQL only supports `IF NOT EXISTS` on `DROP CONSTRAINT`, not `ADD CONSTRAINT`. This caused the entire Alembic transaction to roll back atomically on every startup (including the `alembic_version` insert), so all migrations re-ran each time and the crash was silent because `default_docker.log` wasn't being checked.

### Fix

Removed `IF NOT EXISTS` from the `ADD CONSTRAINT` statement:

```sql
-- FIXED
ALTER TABLE provider_costs ADD CONSTRAINT chk_provider_lower
CHECK (provider = lower(provider))
```

### How It Was Found

Added checkpoint logging to `/home/debug_init.log` (persistent Azure Files) with `os.fsync()`, read and printed on the next startup before heavy imports. The actual traceback was also visible in `default_docker.log` (not `containerStream.log`) once `PYTHONUNBUFFERED=1` was active.

---

## Error 2 — numpy ABI Incompatibility (thinc / spaCy crash)

### Symptom

App crashed at startup with:

```
ValueError: numpy.dtype size changed, may indicate binary incompatibility.
Expected 96 from C header, got 88 from PyObject
```

### Root Cause

Oryx (Azure's server-side build system) switched from gzip (`output.tar.gz`) to zstd (`output.tar.zst`) compression. This triggered a full fresh pip install that pulled in numpy 2.x. The `thinc` package (a spaCy dependency) ships pre-compiled Cython wheels built against numpy 1.x (96-byte `dtype`). numpy 2.x changed the `dtype` struct layout to 88 bytes, causing a binary ABI mismatch at import time.

### Fix

Pinned numpy below 2.0 in [requirements.txt](../requirements.txt):

```
numpy<2.0          # thinc (spaCy dep) compiled against numpy 1.x ABI — numpy 2.x breaks it
spacy==3.7.5
```

### Impact

Startup time dropped from 500–700 s to ~188 s after the pin took effect on the next build.

---

## Error 3 — Container Startup Timeout (WEBSITES_CONTAINER_START_TIME_LIMIT)

### Symptom

App Service killed the container after 600 seconds with no error. A new container immediately started (then hit the numpy crash from Error 2).

### Root Cause

The default `WEBSITES_CONTAINER_START_TIME_LIMIT` is 230 s; it had been manually set to 600 s, but spaCy + CrewAI import on a B1 instance (1.75 GB RAM) takes 500–700 s, which occasionally exceeded 600 s.

### Fix

Increased to 1800 s (Azure maximum) via CLI and updated [infra/app_service.tf](../infra/app_service.tf):

```bash
az webapp config appsettings set \
  --name resumeai-app-dev \
  --resource-group resumeai-rg-dev \
  --settings WEBSITES_CONTAINER_START_TIME_LIMIT=1800
```

```hcl
WEBSITES_CONTAINER_START_TIME_LIMIT = "1800"
```

---

## Error 4 — Silent Container Crash (No Traceback in Logs)

### Symptom

Crash logs showed the container exiting with no Python traceback, only an "Application Error" page. `containerStream.log` was empty at the point of crash.

### Root Cause

`PYTHONUNBUFFERED` was not set, so Python buffered stdout/stderr. When the process was killed, buffered output was lost before it could be written to the log stream.

### Fix

Added `PYTHONUNBUFFERED = "1"` to app settings in [infra/app_service.tf](../infra/app_service.tf):

```hcl
PYTHONUNBUFFERED = "1"    # flush stdout/stderr immediately so crash tracebacks appear in logs
```

Additionally, added a `/home/debug_init.log` checkpoint system in [backend/db/session.py](../backend/db/session.py) that writes progress with `os.fsync()` to persistent Azure Files storage, then prints its contents on the next startup before any heavy imports.

---

## Error 5 — Storage Health Check Returning `"error"` (AuthorizationPermissionMismatch)

### Symptom

After the app started successfully, `/health` returned:

```json
{"status": "degraded", "db": "ok", "storage": "error"}
```

Log contained:

```
ERROR [storage] ping_storage failed: This request is not authorized to perform
this operation using this permission.
ErrorCode: AuthorizationPermissionMismatch
```

### Root Cause

`ping_storage()` called `BlobServiceClient.get_account_information()`. This API requires management-plane access (ARM `Reader` role) on HNS-enabled (ADLS Gen2, `is_hns_enabled = true`) storage accounts. The Managed Identity had only data-plane roles (`Storage Blob Data Contributor` and `Storage Blob Delegator`), which are insufficient for that specific call on an HNS account.

### Fix

Changed `ping_storage()` in [backend/storage.py](../backend/storage.py) to use `list_containers()` — a pure data-plane operation covered by `Storage Blob Data Contributor`:

```python
# Before (broken on HNS accounts)
_blob_service_client().get_account_information()

# After (data-plane, works with Storage Blob Data Contributor)
next(iter(_blob_service_client().list_containers()), None)
```

---

## Error 6 — `list_containers(max_results=1)` TypeError

### Symptom

After switching `ping_storage` to `list_containers`, the health check still returned `"error"`:

```
TypeError: Session.request() got an unexpected keyword argument 'max_results'
```

### Root Cause

`max_results` is not a valid keyword argument for `BlobServiceClient.list_containers()` in the installed version of `azure-storage-blob`. The SDK's `ItemPaged` plumbing passed the unknown kwarg all the way down to the underlying `requests.Session.request()`, which raised `TypeError`.

### Fix

Dropped `max_results=1` — calling `list_containers()` with no arguments is valid in all SDK versions. The `ItemPaged` iterator is lazy, so a single `next()` call still makes exactly one HTTP request regardless of page size.

```python
# Before (broken — max_results leaks to HTTP layer)
next(iter(_blob_service_client().list_containers(max_results=1)), None)

# After
next(iter(_blob_service_client().list_containers()), None)
```

---

## Supporting Changes Made During Debugging

| File | Change | Reason |
|------|--------|--------|
| `backend/db/session.py` | Added `/home/debug_init.log` checkpoint writer with `os.fsync()` + stderr mirror | Catch crash location when stdout is buffered or process is killed |
| `backend/main.py` | Read and print crash log at startup (before heavy imports), then delete it | Surface previous-run crash context in next container's log stream |
| `backend/storage.py` | Added `exc_info=True` to `ping_storage` exception handler | Expose full traceback for storage errors instead of swallowing them |
| `infra/app_service.tf` | `pool_size=3, max_overflow=7, pool_timeout=30` | Avoid exhausting PostgreSQL connections on B1 with limited memory |
| `requirements.txt` | `numpy<2.0` pin above spaCy | Fix thinc ABI incompatibility with numpy 2.x |

---

## Managed Identity Role Assignments (Confirmed Working)

| Role | Scope | Purpose |
|------|-------|---------|
| `Key Vault Secrets User` | Key Vault | Resolve `@Microsoft.KeyVault(...)` app settings at startup |
| `Storage Blob Data Contributor` | Storage Account | Read/write/delete blobs; `list_containers` ping |
| `Storage Blob Delegator` | Storage Account | `get_user_delegation_key()` for SAS URL generation |

---

## Useful Diagnostic Commands

```bash
# Tail live container logs
az webapp log tail --name resumeai-app-dev --resource-group resumeai-rg-dev

# Check persistent crash log (if app is running)
curl https://resumeai-app-dev.azurewebsites.net/health

# Verify role assignments on storage account
az role assignment list \
  --assignee <mi-principal-id> \
  --scope /subscriptions/<sub>/resourceGroups/resumeai-rg-dev/providers/Microsoft.Storage/storageAccounts/resumeaistdevnp \
  --query "[].roleDefinitionName"

# Check KV secret value
az keyvault secret show --vault-name resumeai-kv-dev --name AZURE-STORAGE-ACCOUNT-NAME --query value -o tsv
```

> **Note:** `az webapp config appsettings list` always shows raw `@Microsoft.KeyVault(...)` strings — this is expected. The resolved values are injected into the process environment at runtime and are not shown in the CLI.

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

## Error 7 — `DeltaTable` has no attribute `from_uri`

### Symptom

Dashboard Analytics page showed:

```
Error: Failed to read match analytics: type object 'DeltaTable' has no attribute 'from_uri'
```

### Root Cause

`deltalake` 1.2.1 removed the `DeltaTable.from_uri()` class method that existed in 0.x. The codebase had 4 call sites using `DeltaTable.from_uri(path, storage_options=...)`.

### Fix

Replaced all 4 occurrences in [backend/delta/writer.py](../backend/delta/writer.py):

```python
# Before (deltalake 0.x)
DeltaTable.from_uri(path, storage_options=_storage_options())

# After (deltalake 1.x)
DeltaTable(path, storage_options=_storage_options())
```

---

## Error 8 — Delta Lake MSI Token Acquisition Fails (Connection refused 111)

### Symptom

Dashboard Analytics showed:

```
Error: Failed to read match analytics: Kernel error → Generic MicrosoftAzure error
Error performing token request
Error performing GET http://169.254.169.254/metadata/identity/oauth2/token?...
after 10 retries — Connection refused (os error 111)
```

### Root Cause

The `deltalake` Rust library's `object_store` crate acquires Managed Identity tokens from the IMDS endpoint at `169.254.169.254`. Azure App Service does not expose IMDS — it uses a different internal MSI endpoint exposed via the `IDENTITY_ENDPOINT` and `IDENTITY_HEADER` environment variables. The Python `azure-identity` SDK handles both, but the Rust layer does not.

### Fix

Replaced `use_azure_managed_identity: true` with a Python-acquired `bearer_token` in [backend/delta/writer.py](../backend/delta/writer.py). A token cache (50 min TTL) prevents hammering the MSI endpoint:

```python
_token_cache: dict = {"token": None, "expiry": 0.0}
_token_lock = threading.Lock()

def _get_bearer_token() -> str:
    now = _time.monotonic()
    with _token_lock:
        if _token_cache["token"] and now < _token_cache["expiry"]:
            return _token_cache["token"]
        from azure.identity import DefaultAzureCredential
        token = DefaultAzureCredential().get_token("https://storage.azure.com/.default")
        _token_cache["token"] = token.token
        _token_cache["expiry"] = now + 3000  # 50 minutes
        return token.token

def _storage_options() -> dict:
    if AZURE_STORAGE_ACCOUNT_NAME:
        try:
            return {"account_name": AZURE_STORAGE_ACCOUNT_NAME, "bearer_token": _get_bearer_token()}
        except Exception:
            return {"account_name": AZURE_STORAGE_ACCOUNT_NAME, "use_azure_managed_identity": "true"}
    return {}
```

---

## Error 9 — JD Analysis Returns 422 (Pydantic max_length)

### Symptom

Clicking "Extract Keywords" silently returned `422 Unprocessable Entity`. Nothing appeared in the App Service log stream. Toast showed "JD analysis failed".

### Root Cause

`AnalyzeJDRequest` had `jd_text: str = Field(..., max_length=MAX_JD_CHARS)` where `MAX_JD_CHARS = 8000`. Pydantic rejected the request before it reached the handler (so no Python logging fired). The user's JD was 8202 chars.

### Fix

Removed `max_length` from `AnalyzeJDRequest` in [backend/main.py](../backend/main.py) — the endpoint already truncates internally with `[:MAX_JD_CHARS]`. Also raised `MAX_JD_CHARS` to 20 000 in [backend/config.py](../backend/config.py) since Gemini's context window is 1 M tokens.

```python
# Before
class AnalyzeJDRequest(BaseModel):
    jd_text: str = Field(..., max_length=MAX_JD_CHARS)

# After
class AnalyzeJDRequest(BaseModel):
    jd_text: str  # truncated to MAX_JD_CHARS in the endpoint
```

---

## Error 10 — JD Analysis Returns 500 (Missing Gemini API Key)

### Symptom

`POST /analyze-jd` returned:

```json
{"detail": "JD analysis failed: litellm.APIConnectionError: Missing Gemini API key.
Set the GEMINI_API_KEY or GOOGLE_API_KEY environment variable."}
```

### Root Cause

The Azure App Service app setting was named `GOOGLE_AI_STUDIO_API_KEY`. LiteLLM looks for `GEMINI_API_KEY` or `GOOGLE_API_KEY` — it does not recognise the `GOOGLE_AI_STUDIO_API_KEY` name.

### Fix

Two-part fix in [backend/config.py](../backend/config.py):

1. Accept any of the three env var names (operator can use whichever they prefer).
2. Set both LiteLLM aliases at startup so they are always available regardless of which name was configured.

```python
GOOGLE_AI_STUDIO_API_KEY = (
    os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
    or os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
    or ""
)
if GOOGLE_AI_STUDIO_API_KEY:
    os.environ.setdefault("GEMINI_API_KEY", GOOGLE_AI_STUDIO_API_KEY)
    os.environ.setdefault("GOOGLE_API_KEY", GOOGLE_AI_STUDIO_API_KEY)
```

**Immediate workaround (no redeploy needed):**
```bash
az webapp config appsettings set \
  --name resumeai-api-dev --resource-group resumeai-rg-dev \
  --settings GEMINI_API_KEY="<your-google-ai-studio-key>"
```

---

## Error 11 — Quota Counter Increments on Failed Runs and on Upload

### Symptom

Users reported usage count increasing even when the pipeline failed or when they only clicked "Extract Keywords". A free-plan user (limit 2) could exhaust their daily quota with just 1 upload + 1 failed pipeline run.

### Root Cause

`check_plan_limit` (which atomically increments the counter) was applied as a FastAPI dependency to both `/upload` **and** `/run-pipeline`. This caused double-counting: each attempt consumed 2 quota units. Additionally, the increment happened at request time (before the background task ran), so failed pipeline runs still consumed quota.

### Fix

Three changes in [backend/auth/dependencies.py](../backend/auth/dependencies.py) and [backend/main.py](../backend/main.py):

1. `/upload` now uses `get_current_user` — uploading a file is free.
2. `check_plan_limit` only **checks** the counter (no increment).
3. The counter is incremented inside `_run_pipeline_task` **only on success**.

```python
# check_plan_limit — check only, no increment
used = counter_result.scalar() or 0
if used >= limits.daily_uploads:
    raise HTTPException(status_code=429, ...)

# _run_pipeline_task — increment only on success, just before emitting "done"
async with AsyncSessionLocal() as db:
    await db.execute(
        text("INSERT INTO daily_usage_counters ... ON CONFLICT DO UPDATE SET runs = runs + 1"),
        {"uid": user_id, "date": date_type.today().isoformat()},
    )
    await db.commit()
```

---

## Error 12 — SSE Status Stream Returns 401 (Wrong Token Type)

### Symptom

After clicking "Optimize Resume", the EventSource connection to `/status/{job_id}` immediately returned `401 Unauthorized` with:

```json
{"detail": "Invalid token for SSE — use POST /auth/sse-token"}
```

### Root Cause

The frontend passed the regular 7-day session JWT directly in the EventSource URL (`?token=...`). The `/status` endpoint intentionally rejects session tokens — it requires a short-lived SSE token (60 s, `sse: true` claim) to prevent long-lived tokens from appearing in server access logs and browser history.

### Fix

In [frontend/src/pages/AppPage.jsx](../frontend/src/pages/AppPage.jsx), call `POST /user/sse-token` in parallel with `POST /run-pipeline` and use the returned `sse_token` for the EventSource:

```javascript
const [, { data: sseData }] = await Promise.all([
  client.post('/run-pipeline', { job_id: jobIdLocal, jd_text: jdText }),
  client.post('/user/sse-token'),
]);
const es = new EventSource(
  `${client.defaults.baseURL}/status/${jobIdLocal}?token=${encodeURIComponent(sseData.sse_token)}`
);
```

---

## Error 13 — Pipeline Crashes with `'int' object has no attribute 'setdefault'`

### Symptom

SSE stream emitted:

```json
{"type": "error", "message": "Pipeline error: 'int' object has no attribute 'setdefault'"}
```

The pipeline failed immediately after the "Scoring original resume…" stage.

### Root Cause

In [backend/agents/scorer.py](../backend/agents/scorer.py), the post-processing loop applied defaults with:

```python
result.setdefault(section, {}).setdefault(key, val)
```

Gemini occasionally returns scores as flat integers — `{"ats": 75, "impact": 60, ...}` — instead of the expected nested objects `{"ats": {"score": 75, ...}, ...}`. When `result["ats"]` is `75`, `result.setdefault("ats", {})` returns `75` (the existing value), and calling `.setdefault(key, val)` on an integer crashes.

### Fix

Normalise flat integer section values to `{"score": n}` before applying defaults:

```python
for section, defs in defaults.items():
    if isinstance(result.get(section), (int, float)):
        result[section] = {"score": int(result[section])}
    result.setdefault(section, {})
    for key, val in defs.items():
        result[section].setdefault(key, val)
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

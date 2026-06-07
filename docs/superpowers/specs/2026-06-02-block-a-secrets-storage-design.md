# Block A — Secrets & Storage: Design Spec
**Date:** 2026-06-02
**Branch:** backend_design
**Status:** Approved

## Problem

The application has two hard blockers that prevent it from running correctly on Azure App Service:

1. **Secrets are never loaded from Key Vault.** `config.py` reads from `os.environ.get()`. Terraform stores all secrets in Azure Key Vault and injects only `KEY_VAULT_URL` as an app setting — which nothing in the app reads. The server crashes on startup because `JWT_SECRET` is missing.

2. **Files are written to the local ephemeral disk.** Uploaded resumes are parsed and left on disk. Optimised `.docx` outputs are written to `OUTPUTS_DIR` on disk. Azure App Service wipes the local filesystem on every restart and redeploy. All download links break.

Delta Lake defaults to `./delta_store` locally, which means plan-limit enforcement silently resets after every restart in production.

---

## Approach: App Service Key Vault References + Azure Blob Storage

**Key Vault:** Azure App Service natively resolves app settings of the form `@Microsoft.KeyVault(SecretUri=...)` to their secret values before injecting them into the process environment. `config.py` continues calling `os.environ.get()` unchanged. Only Terraform changes.

**File storage:** A new `backend/storage.py` module abstracts Blob Storage behind three functions. Mode is determined by whether `AZURE_STORAGE_ACCOUNT_NAME` is set — if not, falls back to local disk. Local dev needs zero new setup.

**Local dev:** `.env` file continues to work exactly as today. No Key Vault emulator required.

---

## Files Changed

| File | Change |
|---|---|
| `infra/app_service.tf` | Replace `KEY_VAULT_URL` with KV reference strings for all secrets; add `Storage Blob Delegator` role |
| `infra/outputs.tf` | Update `local_env_snippet` — remove `KEY_VAULT_URL`, note direct `.env` approach |
| `requirements.txt` | Add `azure-storage-blob`, `azure-identity` |
| `backend/config.py` | Add `AZURE_STORAGE_ACCOUNT_NAME`, `OUTPUTS_CONTAINER`; remove `KEY_VAULT_URL` |
| `backend/storage.py` | New module — Blob upload, SAS URL generation, local fallback |
| `backend/main.py` | Upload → tempfile; pipeline output → blob; downloads → SAS redirect; remove dir creation |
| `backend/delta/writer.py` | Cloud URI path handling; `storage_options` passthrough |

---

## Section 1: Terraform — `infra/app_service.tf`

### Replace `app_settings`

Remove:
```hcl
KEY_VAULT_URL = azurerm_key_vault.main.vault_uri
```

Add KV reference strings for every secret that `config.py` reads. Use `versionless_id` (no version pin) so secret rotations are picked up on the next App Service restart without a Terraform re-apply:

```hcl
app_settings = {
  # ── Secrets resolved from Key Vault at startup ──────────────────────────────
  JWT_SECRET                  = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.jwt_secret.versionless_id})"
  DATABASE_URL                = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.database_url.versionless_id})"
  ANTHROPIC_API_KEY           = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.anthropic_api_key.versionless_id})"
  google_ai_studio_api_key    = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.google_ai_api_key.versionless_id})"
  groq_api_key                = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.groq_api_key.versionless_id})"
  STRIPE_SECRET_KEY           = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.stripe_secret_key.versionless_id})"
  ADZUNA_APP_ID               = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.adzuna_app_id.versionless_id})"
  ADZUNA_APP_KEY              = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.adzuna_app_key.versionless_id})"
  THE_MUSE_API_KEY            = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.the_muse_api_key.versionless_id})"
  APIFY_TOKEN                 = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.apify_token.versionless_id})"
  DELTA_STORAGE_PATH          = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.delta_storage_path.versionless_id})"
  AZURE_STORAGE_ACCOUNT_NAME  = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.azure_storage_account_name.versionless_id})"

  # ── Non-secret bootstrap values ─────────────────────────────────────────────
  SCM_DO_BUILD_DURING_DEPLOYMENT     = "true"
  WEBSITES_PORT                      = "8000"
  WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"
}
```

Note: `google_ai_studio_api_key` and `groq_api_key` are injected lowercase to match the exact key names in `config.py`'s `os.environ.get()` calls.

### Add `Storage Blob Delegator` role

User Delegation SAS tokens (required because `shared_access_key_enabled = false`) need the `Storage Blob Delegator` role on the storage account. Add alongside the existing `mi_storage_contributor` assignment:

```hcl
resource "azurerm_role_assignment" "mi_storage_delegator" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_linux_web_app.backend.identity[0].principal_id
}
```

---

## Section 2: `infra/outputs.tf` — update `local_env_snippet`

The `local_env_snippet` output currently instructs developers to set `KEY_VAULT_URL`. With Approach 1, local dev uses `.env` directly — no Key Vault lookup at runtime. Update the output to note this and remove `KEY_VAULT_URL`:

```hcl
output "local_env_snippet" {
  description = "Seed values for resume-optimizer/.env local development. Fill in actual secret values."
  value       = <<-EOT
    # Copy to resume-optimizer/.env and fill in real values.
    # On App Service, these are injected from Key Vault automatically.
    JWT_SECRET=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
    DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/resumeopt
    ANTHROPIC_API_KEY=sk-ant-...
    google_ai_studio_api_key=...
    groq_api_key=...
    # AZURE_STORAGE_ACCOUNT_NAME — omit locally to use local file fallback
    # DELTA_STORAGE_PATH         — omit locally to use ./delta_store fallback
  EOT
}
```

---

## Section 3: `requirements.txt`

Add:
```
azure-storage-blob>=12.19.0
azure-identity>=1.15.0
```

---

## Section 4: `backend/config.py`

Add two new reads. Remove `KEY_VAULT_URL`:

```python
# Remove:
# KEY_VAULT_URL = os.environ.get("KEY_VAULT_URL", "")

# Add:
AZURE_STORAGE_ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "")
OUTPUTS_CONTAINER          = os.environ.get("OUTPUTS_CONTAINER", "outputs")
```

`OUTPUTS_CONTAINER` defaults to `"outputs"` matching `local.outputs_container` in Terraform.

---

## Section 5: New `backend/storage.py`

Thin abstraction over Azure Blob Storage with a local-disk fallback for dev.

**Mode detection:** if `AZURE_STORAGE_ACCOUNT_NAME` is set → Azure Blob (prod). Otherwise → local `outputs/` directory (dev).

**Three public functions:**

```python
def upload_output(data: bytes, blob_name: str) -> str:
    """Upload bytes to the outputs container. blob_name is the path within the
    container (e.g. "{job_id}.docx"). Returns blob_name unchanged."""

def generate_download_url(blob_name: str, ttl_minutes: int = 15) -> str:
    """
    Prod: generate a User Delegation SAS URL valid for ttl_minutes.
         URL form: https://<account>.blob.core.windows.net/outputs/<blob_name>?<sas>
    Dev:  return a local file path string (caller uses FileResponse).
    """

def delete_output(blob_name: str) -> None:
    """Delete a blob. No-op if not found. Used by future cleanup jobs."""
```

**User Delegation SAS (prod path):**
1. `BlobServiceClient(account_url, credential=DefaultAzureCredential())`
2. `client.get_user_delegation_key(start=now - 1min, expiry=now + ttl_minutes)`
3. `generate_blob_sas(account_name, container, blob_name, user_delegation_key=key, permission=BlobSasPermissions(read=True), expiry=now + ttl_minutes)`
4. Return `f"https://{account}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"`

The `- 1 min` start skew on the delegation key handles clock drift between the App Service and Azure.

**Local fallback (dev path):**
- `upload_output`: writes bytes to `outputs/{blob_name}` on disk, creating dirs as needed
- `generate_download_url`: returns the local file path string (caller uses `FileResponse`)
- Both branches share the same function signatures so callers need no conditional logic

**Caller pattern (main.py) stays identical in both modes:**
```python
blob_name = f"{job_id}.docx"   # path within the outputs container; no container prefix
url = storage.generate_download_url(blob_name)
# prod → SAS URL → RedirectResponse
# dev  → local path → FileResponse (handled in main.py with one startswith("http") check)
```

---

## Section 6: `backend/main.py`

### Remove directory setup

Remove:
```python
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
```

### Upload endpoint — parse-and-discard

Replace permanent save path with `tempfile`:

```python
import tempfile

with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
    f.write(contents)
    tmp_path = f.name
try:
    parser = parse_pdf if ext == ".pdf" else parse_docx
    parsed = await asyncio.wait_for(asyncio.to_thread(parser, tmp_path), timeout=30)
finally:
    os.unlink(tmp_path)
```

### Pipeline output → blob

In `_run_pipeline_task`, replace:
```python
output_path = str(OUTPUTS_DIR / f"{job_id}.docx")
generate_docx(current_resume, output_path)
```

With:
```python
import storage as _storage

with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
    tmp_path = f.name
try:
    await asyncio.to_thread(generate_docx, current_resume, tmp_path)
    blob_name = f"{job_id}.docx"          # path within the outputs container
    data = await asyncio.to_thread(Path(tmp_path).read_bytes)
    await asyncio.to_thread(_storage.upload_output, data, blob_name)
finally:
    os.unlink(tmp_path)
```

`Resume.file_path` stores `blob_name` (`"{job_id}.docx"` — the path within the `outputs` container). Column type and width unchanged.

Note: `generate_docx` is now wrapped in `asyncio.to_thread` — fixing an existing bug where it blocked the event loop.

### `/download/{resume_id}` — SAS redirect

Replace:
```python
return FileResponse(path=resume.file_path, filename=..., media_type=...)
```

With:
```python
url = await asyncio.to_thread(_storage.generate_download_url, resume.file_path)
if url.startswith("http"):
    return RedirectResponse(url, status_code=302)
# dev fallback: url is a local path
return FileResponse(path=url, filename=f"optimized_{resume.original_filename or 'resume'}.docx",
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
```

### `/generate-doc` — same pattern

Replace the local `output_path` write and `FileResponse` with the same tempfile → blob → redirect pattern. Blob name: `"outputs/gen_{doc_id}.docx"`.

---

## Section 7: `backend/delta/writer.py`

### Path helper — no pathlib for cloud URIs

Replace the current `Path`-based path helpers:

```python
def _is_cloud_path(path: str) -> bool:
    return path.startswith(("az://", "abfss://", "s3://", "gs://"))

def _join_path(base: str, *parts: str) -> str:
    if _is_cloud_path(base):
        return base.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)
    return str(Path(base, *parts))

def _usage_path() -> str:
    return _join_path(DELTA_STORAGE_PATH, "daily_usage")

def _matches_path() -> str:
    return _join_path(DELTA_STORAGE_PATH, "job_matches")
```

### Storage options — MI credential for cloud paths

```python
from config import AZURE_STORAGE_ACCOUNT_NAME

def _storage_options() -> dict:
    if AZURE_STORAGE_ACCOUNT_NAME:
        return {
            "account_name": AZURE_STORAGE_ACCOUNT_NAME,
            "use_azure_managed_identity": "true",
        }
    return {}
```

### Existence check — handle cloud paths

Replace:
```python
if not Path(path).exists() or not (Path(path) / "_delta_log").exists():
```

With:
```python
def _table_exists(path: str) -> bool:
    if _is_cloud_path(path):
        try:
            DeltaTable.from_uri(path, storage_options=_storage_options())
            return True
        except Exception:
            return False
    return Path(path).exists() and (Path(path) / "_delta_log").exists()
```

### Thread `storage_options` through all calls

Every `write_deltalake(...)` and `DeltaTable.from_uri(...)` call gains `storage_options=_storage_options()`.

---

## Data Flow After Changes

```
Upload request
  → tempfile (parse) → delete temp → PipelineJob.resume_text (DB)

Pipeline run
  → agents run → tempfile .docx → azure blob container "outputs", blob "{job_id}.docx"
  → Resume.file_path = "{job_id}.docx" (DB — path within outputs container)

GET /download/{id}
  → load Resume.file_path → generate 15-min SAS URL → HTTP 302
  → browser downloads directly from Azure Blob Storage

Delta Lake (usage / job matches)
  → az://delta/delta/daily_usage   (prod, MI auth)
  → ./delta_store/daily_usage      (dev, local)
```

---

## What This Does Not Change

- `config.py` — zero lines changed (Approach 1 intent)
- `.env` local dev workflow — unchanged
- `db/models.py` — no schema change; `Resume.file_path` column is reused with new semantic
- All agent code — untouched
- Frontend — untouched
- CI smoke tests — untouched (use local SQLite + local file fallback)

---

## Out of Scope (other blocks)

- Alembic migrations (Block B)
- Stuck pipeline job recovery (Block C)
- Rate limiting, token refresh (Block D)
- Observability (Block E)
- Agent unit tests (Block F)

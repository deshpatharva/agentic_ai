# Block A — Secrets & Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Azure Key Vault references into App Service app settings and replace ephemeral local-disk file I/O with Azure Blob Storage for pipeline outputs and Delta Lake.

**Architecture:** Terraform injects Key Vault reference strings as app settings — App Service resolves them to plain env vars before the process starts, so `config.py` needs zero changes. A new `backend/storage.py` module wraps Blob Storage behind three functions and falls back to local disk when `AZURE_STORAGE_ACCOUNT_NAME` is unset (dev mode). Delta Lake path helpers are updated to handle `az://` URIs and pass Managed Identity credentials.

**Tech Stack:** `azure-storage-blob>=12.19.0`, `azure-identity>=1.15.0`, `azure-keyvault` (not needed — KV references handled by App Service), `pytest`, `pytest-asyncio`, `monkeypatch`

**Spec:** `docs/superpowers/specs/2026-06-02-block-a-secrets-storage-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `resume-optimizer/infra/app_service.tf` | Replace `KEY_VAULT_URL` with KV reference strings; add `Storage Blob Delegator` role |
| Modify | `resume-optimizer/infra/outputs.tf` | Update `local_env_snippet` to remove `KEY_VAULT_URL` |
| Modify | `resume-optimizer/requirements.txt` | Add `azure-storage-blob`, `azure-identity` |
| Modify | `resume-optimizer/backend/config.py` | Add `AZURE_STORAGE_ACCOUNT_NAME`, `OUTPUTS_CONTAINER` |
| Create | `resume-optimizer/backend/storage.py` | Blob upload, SAS URL generation, local fallback |
| Create | `resume-optimizer/backend/tests/test_storage.py` | Unit tests for `storage.py` local fallback |
| Create | `resume-optimizer/backend/tests/test_delta_writer.py` | Unit tests for path helpers and storage options |
| Modify | `resume-optimizer/backend/delta/writer.py` | Cloud URI path handling; `storage_options` passthrough |
| Modify | `resume-optimizer/backend/main.py` | Upload→tempfile; output→blob; download→SAS redirect; generate-doc→blob |
| Modify | `resume-optimizer/backend/tests/test_smoke.py` | Add download redirect smoke test |

---

## Task 1: Terraform — KV references + Storage Blob Delegator

**Files:**
- Modify: `resume-optimizer/infra/app_service.tf`
- Modify: `resume-optimizer/infra/outputs.tf`

- [ ] **Step 1: Replace `app_settings` in `app_service.tf`**

Open `resume-optimizer/infra/app_service.tf`. Replace the entire `app_settings` block (currently injecting `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `KEY_VAULT_URL`, and three SCM settings) with:

```hcl
  app_settings = {
    # ── Secrets resolved by App Service from Key Vault at startup ──────────────
    # App Service resolves @Microsoft.KeyVault(...) references before injecting
    # into the process environment. config.py sees plain os.environ values.
    JWT_SECRET                 = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.jwt_secret.versionless_id})"
    DATABASE_URL               = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.database_url.versionless_id})"
    ANTHROPIC_API_KEY          = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.anthropic_api_key.versionless_id})"
    google_ai_studio_api_key   = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.google_ai_api_key.versionless_id})"
    groq_api_key               = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.groq_api_key.versionless_id})"
    STRIPE_SECRET_KEY          = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.stripe_secret_key.versionless_id})"
    ADZUNA_APP_ID              = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.adzuna_app_id.versionless_id})"
    ADZUNA_APP_KEY             = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.adzuna_app_key.versionless_id})"
    THE_MUSE_API_KEY           = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.the_muse_api_key.versionless_id})"
    APIFY_TOKEN                = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.apify_token.versionless_id})"
    DELTA_STORAGE_PATH         = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.delta_storage_path.versionless_id})"
    AZURE_STORAGE_ACCOUNT_NAME = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.azure_storage_account_name.versionless_id})"

    # ── Non-secret bootstrap values ────────────────────────────────────────────
    SCM_DO_BUILD_DURING_DEPLOYMENT     = "true"
    WEBSITES_PORT                      = "8000"
    WEBSITE_HTTPLOGGING_RETENTION_DAYS = "3"
  }
```

Note: `google_ai_studio_api_key` and `groq_api_key` are lowercase to match `config.py`'s `os.environ.get("google_ai_studio_api_key")` calls exactly.

- [ ] **Step 2: Add `Storage Blob Delegator` role assignment in `app_service.tf`**

Add this block directly after the existing `azurerm_role_assignment.mi_storage_contributor` resource (around line 72):

```hcl
# ── Managed Identity → Storage Blob Delegator ────────────────────────────────
# Required to call get_user_delegation_key() for generating SAS tokens.
# shared_access_key_enabled = false on the storage account means account-key
# SAS is not available; user delegation SAS is the only option.

resource "azurerm_role_assignment" "mi_storage_delegator" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_linux_web_app.backend.identity[0].principal_id
}
```

- [ ] **Step 3: Update `local_env_snippet` in `outputs.tf`**

Replace the `local_env_snippet` output value:

```hcl
output "local_env_snippet" {
  description = "Seed for resume-optimizer/.env local development. Fill in actual secret values — no Key Vault lookup needed locally."
  value       = <<-EOT
    # Copy to resume-optimizer/.env and fill in real values.
    # On App Service, all secrets are injected automatically from Key Vault.
    #
    # Generate JWT_SECRET with:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    JWT_SECRET=<your-32-char-hex-secret>
    DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/resumeopt
    ANTHROPIC_API_KEY=sk-ant-...
    google_ai_studio_api_key=AIza...
    groq_api_key=gsk_...
    # Leave these unset locally to use local-disk fallback:
    # AZURE_STORAGE_ACCOUNT_NAME=
    # DELTA_STORAGE_PATH=   (defaults to ./delta_store)
  EOT
}
```

- [ ] **Step 4: Validate Terraform formatting**

```bash
cd resume-optimizer/infra
terraform fmt -check -recursive
```

Expected: no output (all files already formatted). If there are formatting issues, run `terraform fmt -recursive` to fix them.

- [ ] **Step 5: Validate Terraform syntax**

```bash
terraform validate
```

Expected:
```
Success! The configuration is valid.
```

If you see errors about unknown resource attributes (`versionless_id`), ensure the `azurerm` provider version supports it (≥3.0.0). Check `providers.tf` for the version constraint.

- [ ] **Step 6: Commit**

```bash
cd ../../   # repo root
git add resume-optimizer/infra/app_service.tf resume-optimizer/infra/outputs.tf
git commit -m "infra: replace KEY_VAULT_URL with KV references; add Storage Blob Delegator role"
```

---

## Task 2: Dependencies — `requirements.txt` + `backend/config.py`

**Files:**
- Modify: `resume-optimizer/requirements.txt`
- Modify: `resume-optimizer/backend/config.py`

- [ ] **Step 1: Add packages to `requirements.txt`**

Open `resume-optimizer/requirements.txt`. Add these two lines (anywhere after the existing entries):

```
azure-storage-blob>=12.19.0
azure-identity>=1.15.0
```

- [ ] **Step 2: Add `AZURE_STORAGE_ACCOUNT_NAME` and `OUTPUTS_CONTAINER` to `config.py`**

Open `resume-optimizer/backend/config.py`. Find the `# ── Stripe (optional)` section at the bottom. Add before it:

```python
# ── Azure Storage ─────────────────────────────────────────────────────────────
AZURE_STORAGE_ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "")
OUTPUTS_CONTAINER          = os.environ.get("OUTPUTS_CONTAINER", "outputs")
```

Also remove the now-unused `KEY_VAULT_URL` line if it exists. (There is no `KEY_VAULT_URL` read in config.py currently — it was only injected as an app setting — so nothing to remove.)

- [ ] **Step 3: Install new packages**

```bash
cd resume-optimizer
pip install azure-storage-blob>=12.19.0 azure-identity>=1.15.0
```

Expected: packages install successfully (or "already satisfied" if already installed).

- [ ] **Step 4: Verify the new config values import cleanly**

```bash
cd backend
python -c "
import sys; sys.path.insert(0, '.')
import os
os.environ['JWT_SECRET'] = 'test-secret-32-chars-long-enough-x'
from config import AZURE_STORAGE_ACCOUNT_NAME, OUTPUTS_CONTAINER
print('AZURE_STORAGE_ACCOUNT_NAME:', repr(AZURE_STORAGE_ACCOUNT_NAME))
print('OUTPUTS_CONTAINER:', repr(OUTPUTS_CONTAINER))
print('OK')
"
```

Expected:
```
AZURE_STORAGE_ACCOUNT_NAME: ''
OUTPUTS_CONTAINER: 'outputs'
OK
```

- [ ] **Step 5: Commit**

```bash
cd ../..   # repo root
git add resume-optimizer/requirements.txt resume-optimizer/backend/config.py
git commit -m "deps: add azure-storage-blob, azure-identity; add AZURE_STORAGE_ACCOUNT_NAME to config"
```

---

## Task 3: Create `backend/storage.py` — TDD

**Files:**
- Create: `resume-optimizer/backend/storage.py`
- Create: `resume-optimizer/backend/tests/test_storage.py`

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_storage.py`:

```python
"""
Unit tests for storage.py — tests local-disk fallback mode only.
Azure Blob mode is exercised in staging with real credentials.
"""
import os
import sys
from pathlib import Path

# Set required env vars before any backend import
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_smoke.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

sys.path.insert(0, str(Path(__file__).parent.parent))

import storage as s


def test_upload_output_local_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(s, "_LOCAL_OUTPUTS_DIR", tmp_path)

    result = s.upload_output(b"fake docx bytes", "abc123.docx")

    assert result == "abc123.docx"
    assert (tmp_path / "abc123.docx").read_bytes() == b"fake docx bytes"


def test_upload_output_local_overwrites_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(s, "_LOCAL_OUTPUTS_DIR", tmp_path)
    (tmp_path / "abc123.docx").write_bytes(b"old content")

    s.upload_output(b"new content", "abc123.docx")

    assert (tmp_path / "abc123.docx").read_bytes() == b"new content"


def test_generate_download_url_local_returns_path_not_url(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(s, "_LOCAL_OUTPUTS_DIR", tmp_path)
    (tmp_path / "abc123.docx").write_bytes(b"data")

    url = s.generate_download_url("abc123.docx")

    assert not url.startswith("http"), f"Expected local path, got URL: {url}"
    assert "abc123.docx" in url


def test_delete_output_local_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(s, "_LOCAL_OUTPUTS_DIR", tmp_path)
    target = tmp_path / "abc123.docx"
    target.write_bytes(b"data")

    s.delete_output("abc123.docx")

    assert not target.exists()


def test_delete_output_local_noop_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(s, "_LOCAL_OUTPUTS_DIR", tmp_path)

    s.delete_output("does_not_exist.docx")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail (module not found)**

```bash
cd resume-optimizer
pytest backend/tests/test_storage.py -v
```

Expected: `ModuleNotFoundError: No module named 'storage'` (the file doesn't exist yet).

- [ ] **Step 3: Implement `backend/storage.py`**

Create `resume-optimizer/backend/storage.py`:

```python
"""
Azure Blob Storage abstraction for pipeline output files.

Mode selection (automatic):
  AZURE_STORAGE_ACCOUNT_NAME set  →  Azure Blob Storage (prod/staging)
  AZURE_STORAGE_ACCOUNT_NAME unset →  local outputs/ directory (dev/test)

Public API:
  upload_output(data, blob_name)         → str (blob_name)
  generate_download_url(blob_name, ttl)  → str (HTTPS SAS URL or local path)
  delete_output(blob_name)               → None
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    generate_blob_sas,
)

from config import AZURE_STORAGE_ACCOUNT_NAME, OUTPUTS_CONTAINER

# Local fallback directory used when AZURE_STORAGE_ACCOUNT_NAME is not set.
_LOCAL_OUTPUTS_DIR = Path(__file__).parent / "outputs"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _blob_service_client() -> BlobServiceClient:
    account_url = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    return BlobServiceClient(account_url, credential=DefaultAzureCredential())


# ── Public API ────────────────────────────────────────────────────────────────

def upload_output(data: bytes, blob_name: str) -> str:
    """
    Upload bytes to the outputs container.

    blob_name is the path within the container, e.g. "{job_id}.docx".
    Returns blob_name unchanged so callers can store it in the DB.
    """
    if not AZURE_STORAGE_ACCOUNT_NAME:
        dest = _LOCAL_OUTPUTS_DIR / blob_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return blob_name

    client = _blob_service_client()
    blob = client.get_blob_client(container=OUTPUTS_CONTAINER, blob=blob_name)
    blob.upload_blob(data, overwrite=True)
    return blob_name


def generate_download_url(blob_name: str, ttl_minutes: int = 15) -> str:
    """
    Return a URL for the given blob.

    Prod:  HTTPS User Delegation SAS URL valid for ttl_minutes.
           Requires Storage Blob Delegator role on the MI.
    Dev:   Local file path string (caller uses FileResponse).

    Caller distinguishes the two cases with url.startswith("http").
    """
    if not AZURE_STORAGE_ACCOUNT_NAME:
        return str(_LOCAL_OUTPUTS_DIR / blob_name)

    now = datetime.now(timezone.utc)
    client = _blob_service_client()

    # get_user_delegation_key requires Storage Blob Delegator role.
    # start_time is set 1 minute in the past to absorb clock skew.
    delegation_key = client.get_user_delegation_key(
        key_start_time=now - timedelta(minutes=1),
        key_expiry_time=now + timedelta(minutes=ttl_minutes),
    )
    sas_token = generate_blob_sas(
        account_name=AZURE_STORAGE_ACCOUNT_NAME,
        container_name=OUTPUTS_CONTAINER,
        blob_name=blob_name,
        user_delegation_key=delegation_key,
        permission=BlobSasPermissions(read=True),
        expiry=now + timedelta(minutes=ttl_minutes),
    )
    return (
        f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
        f"/{OUTPUTS_CONTAINER}/{blob_name}?{sas_token}"
    )


def delete_output(blob_name: str) -> None:
    """Delete a blob. No-op if the blob does not exist."""
    if not AZURE_STORAGE_ACCOUNT_NAME:
        path = _LOCAL_OUTPUTS_DIR / blob_name
        if path.exists():
            path.unlink()
        return

    client = _blob_service_client()
    blob = client.get_blob_client(container=OUTPUTS_CONTAINER, blob=blob_name)
    blob.delete_blob(delete_snapshots="include")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd resume-optimizer
pytest backend/tests/test_storage.py -v
```

Expected:
```
PASSED backend/tests/test_storage.py::test_upload_output_local_creates_file
PASSED backend/tests/test_storage.py::test_upload_output_local_overwrites_existing
PASSED backend/tests/test_storage.py::test_generate_download_url_local_returns_path_not_url
PASSED backend/tests/test_storage.py::test_delete_output_local_removes_file
PASSED backend/tests/test_storage.py::test_delete_output_local_noop_when_missing
5 passed
```

- [ ] **Step 5: Run existing smoke tests to confirm nothing broke**

```bash
pytest backend/tests/test_smoke.py -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
cd ..   # resume-optimizer root
git add backend/storage.py backend/tests/test_storage.py
git commit -m "feat: add storage.py — Blob Storage abstraction with local dev fallback"
```

---

## Task 4: Update `backend/delta/writer.py` — TDD

**Files:**
- Modify: `resume-optimizer/backend/delta/writer.py`
- Create: `resume-optimizer/backend/tests/test_delta_writer.py`

- [ ] **Step 1: Write the failing tests**

Create `resume-optimizer/backend/tests/test_delta_writer.py`:

```python
"""
Unit tests for delta/writer.py path helpers and storage options.
No Delta Lake I/O is performed — these are pure function tests.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_smoke.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

sys.path.insert(0, str(Path(__file__).parent.parent))

import delta.writer as dw
import config


# ── _is_cloud_path ────────────────────────────────────────────────────────────

def test_is_cloud_path_az():
    assert dw._is_cloud_path("az://delta/delta/") is True

def test_is_cloud_path_abfss():
    assert dw._is_cloud_path("abfss://delta@account.dfs.core.windows.net/path") is True

def test_is_cloud_path_s3():
    assert dw._is_cloud_path("s3://bucket/path") is True

def test_is_cloud_path_local_relative():
    assert dw._is_cloud_path("./delta_store") is False

def test_is_cloud_path_local_absolute():
    assert dw._is_cloud_path("/abs/path") is False


# ── _join_path ────────────────────────────────────────────────────────────────

def test_join_path_local_uses_pathlib():
    result = dw._join_path("./delta_store", "daily_usage")
    assert result == str(Path("./delta_store", "daily_usage"))

def test_join_path_cloud_with_trailing_slash():
    result = dw._join_path("az://delta/delta/", "daily_usage")
    assert result == "az://delta/delta/daily_usage"

def test_join_path_cloud_without_trailing_slash():
    result = dw._join_path("az://delta/delta", "daily_usage")
    assert result == "az://delta/delta/daily_usage"

def test_join_path_cloud_strips_leading_slash_on_part():
    result = dw._join_path("az://delta/delta/", "/daily_usage")
    assert result == "az://delta/delta/daily_usage"


# ── _storage_options ──────────────────────────────────────────────────────────

def test_storage_options_empty_when_no_account(monkeypatch):
    monkeypatch.setattr(dw, "AZURE_STORAGE_ACCOUNT_NAME", "")
    assert dw._storage_options() == {}

def test_storage_options_set_when_account_configured(monkeypatch):
    monkeypatch.setattr(dw, "AZURE_STORAGE_ACCOUNT_NAME", "myaccount")
    opts = dw._storage_options()
    assert opts == {
        "account_name": "myaccount",
        "use_azure_managed_identity": "true",
    }


# ── _table_exists ─────────────────────────────────────────────────────────────

def test_table_exists_local_missing(tmp_path):
    assert dw._table_exists(str(tmp_path / "nonexistent")) is False

def test_table_exists_local_dir_no_delta_log(tmp_path):
    p = tmp_path / "table"
    p.mkdir()
    assert dw._table_exists(str(p)) is False

def test_table_exists_local_with_delta_log(tmp_path):
    p = tmp_path / "table"
    (p / "_delta_log").mkdir(parents=True)
    assert dw._table_exists(str(p)) is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd resume-optimizer
pytest backend/tests/test_delta_writer.py -v
```

Expected: `AttributeError: module 'delta.writer' has no attribute '_is_cloud_path'` (the functions don't exist yet).

- [ ] **Step 3: Add helper functions to `delta/writer.py`**

Open `resume-optimizer/backend/delta/writer.py`.

**3a.** Update the import line at the top to add `AZURE_STORAGE_ACCOUNT_NAME`:

```python
# Old:
from config import DELTA_STORAGE_PATH

# New:
from config import AZURE_STORAGE_ACCOUNT_NAME, DELTA_STORAGE_PATH
```

**3b.** Replace the existing `_usage_path()` and `_matches_path()` functions with the full set of helpers. Find the two functions (they're right after the schema definitions) and replace them:

```python
# ── Path and storage helpers ──────────────────────────────────────────────────

def _is_cloud_path(path: str) -> bool:
    """Return True if path is a cloud URI (az://, abfss://, s3://, gs://)."""
    return path.startswith(("az://", "abfss://", "s3://", "gs://"))


def _join_path(base: str, *parts: str) -> str:
    """Join path components. Uses string ops for cloud URIs, pathlib for local."""
    if _is_cloud_path(base):
        return base.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)
    return str(Path(base, *parts))


def _usage_path() -> str:
    return _join_path(DELTA_STORAGE_PATH, "daily_usage")


def _matches_path() -> str:
    return _join_path(DELTA_STORAGE_PATH, "job_matches")


def _storage_options() -> dict:
    """Return storage_options dict for deltalake calls. Empty dict for local dev."""
    if AZURE_STORAGE_ACCOUNT_NAME:
        return {
            "account_name": AZURE_STORAGE_ACCOUNT_NAME,
            "use_azure_managed_identity": "true",
        }
    return {}


def _table_exists(path: str) -> bool:
    """Return True if a Delta table exists at path (local or cloud)."""
    if _is_cloud_path(path):
        try:
            DeltaTable.from_uri(path, storage_options=_storage_options())
            return True
        except Exception:
            return False
    return Path(path).exists() and (Path(path) / "_delta_log").exists()
```

- [ ] **Step 4: Update all `write_deltalake` and `DeltaTable.from_uri` calls to pass `storage_options`**

There are 5 call sites to update. Replace each one:

**In `write_daily_usage`:**
```python
# Old:
    write_deltalake(
        _usage_path(),
        df,
        schema=_USAGE_SCHEMA,
        partition_by=["date"],
        mode="append",
    )

# New:
    write_deltalake(
        _usage_path(),
        df,
        schema=_USAGE_SCHEMA,
        partition_by=["date"],
        mode="append",
        storage_options=_storage_options(),
    )
```

**In `write_job_match`:**
```python
# Old:
    write_deltalake(
        _matches_path(),
        df,
        schema=_MATCHES_SCHEMA,
        partition_by=["year", "month"],
        mode="append",
    )

# New:
    write_deltalake(
        _matches_path(),
        df,
        schema=_MATCHES_SCHEMA,
        partition_by=["year", "month"],
        mode="append",
        storage_options=_storage_options(),
    )
```

**In `read_usage_last_n_days`:**
```python
# Old:
    if not Path(path).exists() or not (Path(path) / "_delta_log").exists():
        return pd.DataFrame(columns=["date", "pipeline_runs", "uploads", "tokens_used"])

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path)

# New:
    if not _table_exists(path):
        return pd.DataFrame(columns=["date", "pipeline_runs", "uploads", "tokens_used"])

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path, storage_options=_storage_options())
```

**In `read_job_matches`:**
```python
# Old:
    if not Path(path).exists() or not (Path(path) / "_delta_log").exists():
        return {"total": 0, "page": page, "per_page": per_page, "results": []}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path)

# New:
    if not _table_exists(path):
        return {"total": 0, "page": page, "per_page": per_page, "results": []}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path, storage_options=_storage_options())
```

**In `vacuum_old_matches`:**
```python
# Old:
    if not Path(path).exists() or not (Path(path) / "_delta_log").exists():
        return

    ...
    dt = DeltaTable.from_uri(path)
    df = dt.to_pandas()

    df_keep = df[df["scraped_at"] >= cutoff_str]
    if len(df_keep) < len(df):
        write_deltalake(
            path,
            df_keep,
            schema=_MATCHES_SCHEMA,
            partition_by=["year", "month"],
            mode="overwrite",
        )
        dt = DeltaTable.from_uri(path)
        dt.vacuum(...)

# New:
    if not _table_exists(path):
        return

    ...
    dt = DeltaTable.from_uri(path, storage_options=_storage_options())
    df = dt.to_pandas()

    df_keep = df[df["scraped_at"] >= cutoff_str]
    if len(df_keep) < len(df):
        write_deltalake(
            path,
            df_keep,
            schema=_MATCHES_SCHEMA,
            partition_by=["year", "month"],
            mode="overwrite",
            storage_options=_storage_options(),
        )
        dt = DeltaTable.from_uri(path, storage_options=_storage_options())
        dt.vacuum(retention_hours=0, enforce_retention_duration=False, dry_run=False)
```

- [ ] **Step 5: Run delta writer tests to verify they pass**

```bash
cd resume-optimizer
pytest backend/tests/test_delta_writer.py -v
```

Expected:
```
PASSED ...::test_is_cloud_path_az
PASSED ...::test_is_cloud_path_abfss
PASSED ...::test_is_cloud_path_s3
PASSED ...::test_is_cloud_path_local_relative
PASSED ...::test_is_cloud_path_local_absolute
PASSED ...::test_join_path_local_uses_pathlib
PASSED ...::test_join_path_cloud_with_trailing_slash
PASSED ...::test_join_path_cloud_without_trailing_slash
PASSED ...::test_join_path_cloud_strips_leading_slash_on_part
PASSED ...::test_storage_options_empty_when_no_account
PASSED ...::test_storage_options_set_when_account_configured
PASSED ...::test_table_exists_local_missing
PASSED ...::test_table_exists_local_dir_no_delta_log
PASSED ...::test_table_exists_local_with_delta_log
14 passed
```

- [ ] **Step 6: Run full test suite**

```bash
pytest --tb=short -v
```

Expected: all tests pass (smoke + storage + delta writer).

- [ ] **Step 7: Commit**

```bash
cd ..   # repo root
git add resume-optimizer/backend/delta/writer.py resume-optimizer/backend/tests/test_delta_writer.py
git commit -m "feat: delta/writer.py — cloud URI path helpers, storage_options passthrough for Azure MI"
```

---

## Task 5: Update `backend/main.py` — upload endpoint (tempfile)

**Files:**
- Modify: `resume-optimizer/backend/main.py`

- [ ] **Step 1: Verify existing upload smoke tests pass before touching anything**

```bash
cd resume-optimizer
pytest backend/tests/test_smoke.py -v -k "upload"
```

Expected: 3 tests pass (`test_upload_requires_auth`, `test_upload_rejects_oversized_file`, `test_upload_rejects_bad_extension`).

- [ ] **Step 2: Remove `UPLOADS_DIR` and `OUTPUTS_DIR` from `main.py`**

Open `resume-optimizer/backend/main.py`. Find and delete these lines (around lines 88–92):

```python
# DELETE these 4 lines:
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
```

Keep `BASE_DIR = Path(__file__).parent` — it's still used for the `outputs` path in the Dockerfile entrypoint context.

- [ ] **Step 3: Add `import tempfile` and `import storage as _storage` to `main.py` imports**

Find the existing `import` block at the top of `main.py` (the block with `import asyncio`, `import json`, etc.). Add:

```python
import os
import tempfile
```

`os` is likely already imported; add `tempfile` if missing. Also add the storage import near the agent imports section:

```python
import storage as _storage
```

Place it alongside the other local imports (e.g., after `from generators.docx_generator import generate_docx`).

- [ ] **Step 4: Replace the file-save block inside `/upload` with tempfile**

Find the upload endpoint. Locate these lines:

```python
    job_id = str(uuid.uuid4())
    save_path = UPLOADS_DIR / f"{job_id}{ext}"

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    await asyncio.to_thread(save_path.write_bytes, contents)

    try:
        parser = parse_pdf if ext == ".pdf" else parse_docx
        parsed = await asyncio.wait_for(
            asyncio.to_thread(parser, str(save_path)),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Resume parsing timed out. Try a simpler PDF or convert to .docx.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")
```

Replace with:

```python
    job_id = str(uuid.uuid4())

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(contents)
        tmp_path = f.name

    try:
        parser = parse_pdf if ext == ".pdf" else parse_docx
        parsed = await asyncio.wait_for(
            asyncio.to_thread(parser, tmp_path),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Resume parsing timed out. Try a simpler PDF or convert to .docx.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse file: {str(e)}")
    finally:
        os.unlink(tmp_path)
```

- [ ] **Step 5: Run upload smoke tests to verify they still pass**

```bash
cd resume-optimizer
pytest backend/tests/test_smoke.py -v -k "upload"
```

Expected: same 3 tests pass as in Step 1.

- [ ] **Step 6: Commit**

```bash
cd ..   # repo root
git add resume-optimizer/backend/main.py
git commit -m "fix: upload endpoint — parse-and-discard temp file instead of permanent UPLOADS_DIR"
```

---

## Task 6: Update `backend/main.py` — pipeline output → blob + download → SAS redirect

**Files:**
- Modify: `resume-optimizer/backend/main.py`
- Modify: `resume-optimizer/backend/tests/test_smoke.py`

- [ ] **Step 1: Add the download redirect smoke test**

Open `resume-optimizer/backend/tests/test_smoke.py`. Add these imports near the top (with the existing imports):

```python
from passlib.context import CryptContext
from db.models import Resume
import storage as _s
```

Then add the following test at the end of the file:

```python
@pytest.mark.asyncio
async def test_download_returns_file_in_local_mode(client, monkeypatch, tmp_path):
    """In local dev mode (no AZURE_STORAGE_ACCOUNT_NAME), download returns 200 FileResponse."""
    # Register user
    r = await client.post("/auth/register", json={
        "email": "dl_local@test.com", "password": "Test1234!"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = r.json()["user"]["id"]

    # Create a real output file in a temp directory
    blob_name = "test-job-id.docx"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / blob_name).write_bytes(b"PK fake docx")  # minimal non-empty file

    # Patch storage to use the temp directory and local mode
    monkeypatch.setattr(_s, "AZURE_STORAGE_ACCOUNT_NAME", "")
    monkeypatch.setattr(_s, "_LOCAL_OUTPUTS_DIR", output_dir)

    # Insert a Resume record pointing to blob_name
    async with _TestSession() as session:
        resume = Resume(
            user_id=user_id,
            original_filename="original.pdf",
            file_path=blob_name,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        resume_id = str(resume.id)

    r2 = await client.get(
        f"/download/{resume_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert r2.content == b"PK fake docx"


@pytest.mark.asyncio
async def test_download_redirects_in_cloud_mode(client, monkeypatch, tmp_path):
    """In cloud mode (AZURE_STORAGE_ACCOUNT_NAME set), download returns 302."""
    r = await client.post("/auth/register", json={
        "email": "dl_cloud@test.com", "password": "Test1234!"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    user_id = r.json()["user"]["id"]

    blob_name = "cloud-job-id.docx"

    # Patch generate_download_url to return an HTTPS URL (simulates prod)
    monkeypatch.setattr(
        _s, "generate_download_url",
        lambda bn, ttl_minutes=15: f"https://myaccount.blob.core.windows.net/outputs/{bn}?sas=xyz",
    )

    async with _TestSession() as session:
        resume = Resume(
            user_id=user_id,
            original_filename="original.pdf",
            file_path=blob_name,
        )
        session.add(resume)
        await session.commit()
        await session.refresh(resume)
        resume_id = str(resume.id)

    r2 = await client.get(
        f"/download/{resume_id}",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert r2.status_code == 302
    assert "myaccount.blob.core.windows.net" in r2.headers["location"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd resume-optimizer
pytest backend/tests/test_smoke.py -v -k "download"
```

Expected: `test_download_requires_auth` passes (existing), new tests fail because `download` still uses `FileResponse` (old code).

- [ ] **Step 3: Update `/download/{resume_id}` in `main.py`**

Find the `/download/{resume_id}` endpoint. Replace the return statement at the end:

```python
    # Old:
    return FileResponse(
        path=resume.file_path,
        filename=f"optimized_{resume.original_filename or 'resume'}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # New:
    url = await asyncio.to_thread(_storage.generate_download_url, resume.file_path)
    if url.startswith("http"):
        return RedirectResponse(url, status_code=302)
    return FileResponse(
        path=url,
        filename=f"optimized_{resume.original_filename or 'resume'}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
```

Also add `RedirectResponse` to the FastAPI imports at the top of `main.py`:

```python
# Old:
from fastapi.responses import FileResponse

# New:
from fastapi.responses import FileResponse, RedirectResponse
```

- [ ] **Step 4: Update the pipeline output block in `_run_pipeline_task`**

Find the `# ── Step 5: Generate .docx ──` section inside `_run_pipeline_task`. Replace:

```python
            # ── Step 5: Generate .docx ──────────────────────────────────────────
            await emit({"type": "stage", "message": "Generating optimized .docx file...", "stage": "generate"})
            output_path = str(OUTPUTS_DIR / f"{job_id}.docx")
            generate_docx(current_resume, output_path)
```

With:

```python
            # ── Step 5: Generate .docx and upload to blob ────────────────────────
            await emit({"type": "stage", "message": "Generating optimized .docx file...", "stage": "generate"})
            blob_name = f"{job_id}.docx"
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _f:
                tmp_docx = _f.name
            try:
                await asyncio.to_thread(generate_docx, current_resume, tmp_docx)
                docx_bytes = await asyncio.to_thread(Path(tmp_docx).read_bytes)
                await asyncio.to_thread(_storage.upload_output, docx_bytes, blob_name)
            finally:
                os.unlink(tmp_docx)
```

Also find the `Resume` record creation block (a few lines later) and update `file_path`:

```python
                    # Old:
                    file_path=output_path,

                    # New:
                    file_path=blob_name,
```

And find the `update_job` call and update `download_path`:

```python
            # Old:
            await update_job(
                status=JobStatus.done,
                download_path=output_path,
                ...
            )

            # New:
            await update_job(
                status=JobStatus.done,
                download_path=blob_name,
                ...
            )
```

- [ ] **Step 5: Run the download tests to verify they pass**

```bash
cd resume-optimizer
pytest backend/tests/test_smoke.py -v -k "download"
```

Expected: all 3 download tests pass (`test_download_requires_auth`, `test_download_returns_file_in_local_mode`, `test_download_redirects_in_cloud_mode`).

- [ ] **Step 6: Run full test suite**

```bash
pytest --tb=short -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd ..   # repo root
git add resume-optimizer/backend/main.py resume-optimizer/backend/tests/test_smoke.py
git commit -m "feat: pipeline output → Azure Blob; /download → SAS redirect (302) in prod, FileResponse in dev"
```

---

## Task 7: Update `backend/main.py` — `/generate-doc` endpoint

**Files:**
- Modify: `resume-optimizer/backend/main.py`

- [ ] **Step 1: Replace the `/generate-doc` endpoint body**

Find `@app.post("/generate-doc")`. Replace the body (everything after the input validation):

```python
    # Old:
    doc_id = str(uuid.uuid4())
    output_path = str(OUTPUTS_DIR / f"gen_{doc_id}.docx")

    try:
        await asyncio.to_thread(generate_docx, request.resume_text, output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate document: {str(e)}")

    return FileResponse(
        path=output_path,
        filename="resume.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # New:
    doc_id = str(uuid.uuid4())
    blob_name = f"gen_{doc_id}.docx"

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as _f:
        tmp_docx = _f.name
    try:
        await asyncio.to_thread(generate_docx, request.resume_text, tmp_docx)
        docx_bytes = await asyncio.to_thread(Path(tmp_docx).read_bytes)
        await asyncio.to_thread(_storage.upload_output, docx_bytes, blob_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate document: {str(e)}")
    finally:
        os.unlink(tmp_docx)

    url = await asyncio.to_thread(_storage.generate_download_url, blob_name)
    if url.startswith("http"):
        return RedirectResponse(url, status_code=302)
    return FileResponse(
        path=url,
        filename="resume.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
```

- [ ] **Step 2: Run full test suite**

```bash
cd resume-optimizer
pytest --tb=short -v
```

Expected: all tests pass. The smoke tests don't exercise `/generate-doc` (it requires a real DOCX generator), so no new test failures expected.

- [ ] **Step 3: Verify `main.py` has no remaining references to `UPLOADS_DIR` or `OUTPUTS_DIR`**

```bash
grep -n "UPLOADS_DIR\|OUTPUTS_DIR" backend/main.py
```

Expected: no output. If either string appears, delete those references.

- [ ] **Step 4: Commit**

```bash
cd ..   # repo root
git add resume-optimizer/backend/main.py
git commit -m "feat: /generate-doc endpoint — write to blob, return SAS redirect"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run complete test suite one last time**

```bash
cd resume-optimizer
pytest --tb=short -v
```

Expected output (exact test names may vary by order):
```
PASSED backend/tests/test_smoke.py::test_register_and_login
PASSED backend/tests/test_smoke.py::test_login_wrong_password
PASSED backend/tests/test_smoke.py::test_me_requires_auth
PASSED backend/tests/test_smoke.py::test_me_with_token
PASSED backend/tests/test_smoke.py::test_upload_requires_auth
PASSED backend/tests/test_smoke.py::test_upload_rejects_oversized_file
PASSED backend/tests/test_smoke.py::test_upload_rejects_bad_extension
PASSED backend/tests/test_smoke.py::test_status_requires_token_param
PASSED backend/tests/test_smoke.py::test_download_requires_auth
PASSED backend/tests/test_smoke.py::test_download_returns_file_in_local_mode
PASSED backend/tests/test_smoke.py::test_download_redirects_in_cloud_mode
PASSED backend/tests/test_storage.py::test_upload_output_local_creates_file
PASSED backend/tests/test_storage.py::test_upload_output_local_overwrites_existing
PASSED backend/tests/test_storage.py::test_generate_download_url_local_returns_path_not_url
PASSED backend/tests/test_storage.py::test_delete_output_local_removes_file
PASSED backend/tests/test_storage.py::test_delete_output_local_noop_when_missing
PASSED backend/tests/test_delta_writer.py::test_is_cloud_path_az
... (14 delta writer tests)
```

All tests pass.

- [ ] **Step 2: Verify no local disk references remain in the output path**

```bash
grep -n "OUTPUTS_DIR\|UPLOADS_DIR\|outputs_dir\|uploads_dir" backend/main.py
```

Expected: no output.

- [ ] **Step 3: Verify import check still passes**

```bash
cd backend
python -c "import sys; sys.path.insert(0,'.'); import main; print('imports OK')"
```

Expected: `imports OK`

- [ ] **Step 4: Run frontend build to ensure nothing broke there**

```bash
cd ../frontend
npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Final commit (if any cleanup needed)**

If linting or import-check revealed issues, fix and commit:
```bash
cd ../../   # repo root
git add -p  # stage only what changed
git commit -m "chore: block-a cleanup — remove unused UPLOADS_DIR/OUTPUTS_DIR imports"
```

---

## Deployment Checklist (after plan is complete)

Before running `terraform apply` and deploying the backend:

1. **Confirm Key Vault secrets exist**: All secrets referenced in `app_service.tf` must already exist in Key Vault (`JWT-SECRET`, `DATABASE-URL`, `ANTHROPIC-API-KEY`, etc.). They were created by the previous Terraform apply.

2. **Confirm MI RBAC is applied**: The `azurerm_role_assignment.mi_kv_secrets_user` must be active (was created in a previous apply). The new `mi_storage_delegator` role will be created by this apply.

3. **Run Terraform apply** via the manual-dispatch workflow in GitHub Actions (requires reviewer approval per `terraform.yml`).

4. **Run deploy-backend workflow**: Triggers automatically on push to `main` for backend path changes, or manually dispatch.

5. **Smoke test production**: After deploy, call `GET /auth/me` with a valid token and `POST /upload` with a small PDF to verify the app starts and secrets are loaded.

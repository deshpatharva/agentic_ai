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
from urllib.parse import quote

from azure.core.exceptions import ResourceNotFoundError
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
        key_expiry_time=now + timedelta(minutes=ttl_minutes + 5),
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
        f"/{OUTPUTS_CONTAINER}/{quote(blob_name, safe='/')}?{sas_token}"
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
    try:
        blob.delete_blob(delete_snapshots="include")
    except ResourceNotFoundError:
        pass


def ping_storage() -> str:
    """Check storage connectivity. Returns 'ok', 'error', or 'skipped'."""
    if not AZURE_STORAGE_ACCOUNT_NAME:
        return "skipped"
    try:
        # get_account_information() requires management-plane access on HNS accounts.
        # list_containers() works with Storage Blob Data Contributor (data-plane).
        next(iter(_blob_service_client().list_containers(max_results=1)), None)
        return "ok"
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("ping_storage failed: %s", exc, exc_info=True)
        return "error"

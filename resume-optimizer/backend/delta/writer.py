"""
Delta Lake writer — append-only analytics tables.

Tables
------
daily_usage   partitioned by date          — pipeline runs, uploads, token counts
job_matches   partitioned by year/month    — scraped job postings per user

Storage path: DELTA_STORAGE_PATH env var (default: ./delta_store)
Prod: set DELTA_STORAGE_PATH=s3://your-bucket/delta/
"""

import threading
import time as _time
from typing import Optional
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from deltalake.exceptions import TableNotFoundError

from config import AZURE_STORAGE_ACCOUNT_NAME, DELTA_STORAGE_PATH

# Per-table write locks — prevents transaction log corruption on concurrent writes
_usage_lock   = threading.Lock()
_matches_lock = threading.Lock()

# Bearer token cache — deltalake's Rust object_store can't use App Service MSI
# directly (it tries IMDS at 169.254.169.254 which is refused). We get the token
# via Python's DefaultAzureCredential (which handles App Service MSI correctly)
# and pass it as a static bearer_token. Cached for 50 min (tokens last 60 min).
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
        try:
            return {
                "account_name": AZURE_STORAGE_ACCOUNT_NAME,
                "bearer_token": _get_bearer_token(),
            }
        except Exception:
            # Fallback — works in environments where IMDS is reachable
            return {
                "account_name": AZURE_STORAGE_ACCOUNT_NAME,
                "use_azure_managed_identity": "true",
            }
    return {}


def _table_exists(path: str) -> bool:
    """Return True if a Delta table exists at path (local or cloud)."""
    if _is_cloud_path(path):
        try:
            DeltaTable(path, storage_options=_storage_options())
            return True
        except TableNotFoundError:
            return False
    return Path(path).exists() and (Path(path) / "_delta_log").exists()


# ── Schemas ───────────────────────────────────────────────────────────────────

_USAGE_SCHEMA = pa.schema([
    pa.field("user_id",        pa.string(),    nullable=False),
    pa.field("date",           pa.string(),    nullable=False),   # ISO date YYYY-MM-DD
    pa.field("pipeline_runs",  pa.int32(),     nullable=False),
    pa.field("uploads",        pa.int32(),     nullable=False),
    pa.field("input_tokens",   pa.int64(),     nullable=False),
    pa.field("output_tokens",  pa.int64(),     nullable=False),
    pa.field("tokens_used",    pa.int64(),     nullable=False),
    pa.field("written_at",     pa.string(),    nullable=False),   # ISO datetime
])

_MATCHES_SCHEMA = pa.schema([
    pa.field("user_id",          pa.string(),  nullable=False),
    pa.field("resume_id",        pa.string(),  nullable=False),
    pa.field("job_title",        pa.string(),  nullable=False),
    pa.field("company",          pa.string(),  nullable=True),
    pa.field("url",              pa.string(),  nullable=True),
    pa.field("source",           pa.string(),  nullable=False),
    pa.field("similarity_score", pa.float64(), nullable=True),
    pa.field("raw_description",  pa.string(),  nullable=True),
    pa.field("scraped_at",       pa.string(),  nullable=False),   # ISO datetime
    pa.field("is_read",          pa.bool_(),   nullable=False),
    pa.field("year",             pa.int32(),   nullable=False),   # partition column
    pa.field("month",            pa.int32(),   nullable=False),   # partition column
])


# ── Writers ───────────────────────────────────────────────────────────────────

def write_daily_usage(record: dict) -> None:
    """
    Append a usage record to the daily_usage Delta table.

    Expected keys: user_id, date (str YYYY-MM-DD or date obj),
                   pipeline_runs, uploads, input_tokens, output_tokens, tokens_used
    """
    with _usage_lock:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "user_id":       str(record["user_id"]),
            "date":          str(record.get("date", date.today().isoformat())),
            "pipeline_runs": int(record.get("pipeline_runs", 0)),
            "uploads":       int(record.get("uploads", 0)),
            "input_tokens":  int(record.get("input_tokens", 0)),
            "output_tokens": int(record.get("output_tokens", 0)),
            "tokens_used":   int(record.get("tokens_used", 0)),
            "written_at":    now,
        }
        df = pd.DataFrame([row])
        write_deltalake(
            _usage_path(),
            df,
            schema=_USAGE_SCHEMA,
            partition_by=["date"],
            mode="append",
            storage_options=_storage_options(),
        )


def _match_row(record: dict) -> dict:
    scraped_at = record.get("scraped_at", datetime.now(timezone.utc).isoformat())
    if isinstance(scraped_at, datetime):
        scraped_at_str = scraped_at.isoformat()
        dt = scraped_at
    else:
        scraped_at_str = str(scraped_at)
        dt = datetime.fromisoformat(scraped_at_str[:19])

    return {
        "user_id":          str(record["user_id"]),
        "resume_id":        str(record.get("resume_id", "")),
        "job_title":        str(record.get("job_title", "")),
        "company":          str(record.get("company", "")) if record.get("company") else None,
        "url":              str(record.get("url", "")) if record.get("url") else None,
        "source":           str(record.get("source", "unknown")),
        "similarity_score": float(record["similarity_score"]) if record.get("similarity_score") is not None else None,
        "raw_description":  str(record.get("raw_description", "")) if record.get("raw_description") else None,
        "scraped_at":       scraped_at_str,
        "is_read":          bool(record.get("is_read", False)),
        "year":             dt.year,
        "month":            dt.month,
    }


def write_job_matches(records: list[dict]) -> None:
    """
    Append scraped job matches to the job_matches Delta table in ONE transaction.

    Per-record keys: user_id, resume_id, job_title, company, url, source,
                     similarity_score, raw_description, scraped_at (ISO str or datetime),
                     is_read (bool, default False)
    """
    if not records:
        return
    with _matches_lock:
        df = pd.DataFrame([_match_row(r) for r in records])
        write_deltalake(
            _matches_path(),
            df,
            schema=_MATCHES_SCHEMA,
            partition_by=["year", "month"],
            mode="append",
            storage_options=_storage_options(),
        )


def write_job_match(record: dict) -> None:
    """Append a single job match (thin wrapper over the batch writer)."""
    write_job_matches([record])


# ── Readers ───────────────────────────────────────────────────────────────────

def read_usage_last_n_days(user_id: str, days: int = 30) -> pd.DataFrame:
    """Read usage records for the last n days.

    Args:
        user_id: The user's UUID string. Pass empty string "" to read aggregate
                 stats across ALL users — used by admin analytics endpoints only.
                 Any non-empty string filters to that specific user.
        days:    Number of days to look back (inclusive of today).

    Returns:
        pandas DataFrame with columns: user_id, date, pipeline_runs, uploads,
        input_tokens, output_tokens, tokens_used.
        Returns empty DataFrame if no data exists.
    """
    path = _usage_path()
    if not _table_exists(path):
        return pd.DataFrame(columns=["date", "pipeline_runs", "uploads", "input_tokens", "output_tokens", "tokens_used"])

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    dt = DeltaTable(path, storage_options=_storage_options())

    filters: list = [("date", ">=", cutoff)]
    if user_id:
        filters.append(("user_id", "=", user_id))

    df = dt.to_pandas(filters=filters)

    # Safety net for partial Delta pushdown
    df = df[df["date"] >= cutoff]
    if user_id:
        df = df[df["user_id"] == user_id]
    if df.empty:
        return pd.DataFrame(columns=["date", "pipeline_runs", "uploads", "input_tokens", "output_tokens", "tokens_used"])

    agg = (
        df.groupby("date")
        .agg(pipeline_runs=("pipeline_runs", "sum"),
             uploads=("uploads", "sum"),
             input_tokens=("input_tokens", "sum"),
             output_tokens=("output_tokens", "sum"),
             tokens_used=("tokens_used", "sum"))
        .reset_index()
        .sort_values("date")
    )
    return agg


def _match_filters_dnf(cutoff_iso: str, cutoff_dt: datetime, user_id: str) -> list:
    """
    Build DNF filters (OR of AND-lists) that include the year/month PARTITION
    columns, so the Delta reader can prune files instead of scanning the whole
    table (scraped_at/user_id alone are not partition columns).
    """
    now = datetime.now(timezone.utc)
    base: list = [("scraped_at", ">=", cutoff_iso)]
    if user_id:
        base.append(("user_id", "=", user_id))

    pairs = []
    y, m = cutoff_dt.year, cutoff_dt.month
    while (y, m) <= (now.year, now.month):
        pairs.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1

    return [
        [("year", "=", y), ("month", "=", m)] + base
        for y, m in pairs
    ]


# raw_description is excluded — it is by far the largest column and no API
# consumer renders it (approved Stage B item B3: column pruning).
_MATCH_READ_COLUMNS = [
    "user_id", "resume_id", "job_title", "company", "url",
    "source", "similarity_score", "scraped_at", "is_read",
]


def read_job_matches(
    user_id: str,
    days: int = 30,
    page: int = 1,
    per_page: int = 20,
    source: Optional[str] = None,
    min_score: Optional[float] = None,
) -> dict:
    """
    Return paginated job matches for user_id scraped in the last N days.
    `source`/`min_score` filters are applied BEFORE pagination, so `total`
    reflects the filtered count and page boundaries stay correct.
    Returns: {total, page, per_page, results: list[dict]}
    """
    path = _matches_path()
    if not _table_exists(path):
        return {"total": 0, "page": page, "per_page": per_page, "results": []}

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff = cutoff_dt.isoformat()
    dt = DeltaTable(path, storage_options=_storage_options())

    df = dt.to_pandas(
        filters=_match_filters_dnf(cutoff, cutoff_dt, user_id),
        columns=_MATCH_READ_COLUMNS,
    )

    # Safety net for partial Delta pushdown
    df = df[df["scraped_at"] >= cutoff]
    if user_id:
        df = df[df["user_id"] == user_id]
    if source:
        df = df[df["source"] == source]
    if min_score is not None:
        df = df[df["similarity_score"].fillna(0) >= min_score]
    df = df.sort_values("scraped_at", ascending=False)

    total = len(df)
    start = (page - 1) * per_page
    page_df = df.iloc[start: start + per_page]

    results = page_df.to_dict(orient="records")
    return {"total": total, "page": page, "per_page": per_page, "results": results}


def count_unread_matches(user_id: str, days: int = 30) -> int:
    """
    Count unread matches without materialising full rows — reads only the
    columns needed for filtering. Used by /dashboard/summary.
    """
    path = _matches_path()
    if not _table_exists(path):
        return 0

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff = cutoff_dt.isoformat()
    dt = DeltaTable(path, storage_options=_storage_options())

    df = dt.to_pandas(
        filters=_match_filters_dnf(cutoff, cutoff_dt, user_id),
        columns=["user_id", "scraped_at", "is_read"],
    )
    df = df[df["scraped_at"] >= cutoff]
    if user_id:
        df = df[df["user_id"] == user_id]
    return int((~df["is_read"]).sum())


# ── Maintenance ───────────────────────────────────────────────────────────────

def vacuum_old_matches(retention_days: int = 90) -> None:
    """Hard-delete job_matches rows older than retention_days using Delta's native DELETE.
    Called weekly by the stuck-job reaper in main.py.
    """
    path = _matches_path()
    if not _table_exists(path):
        return

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_iso = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S")

    dt = DeltaTable(path, storage_options=_storage_options())
    dt.delete(f"scraped_at < '{cutoff_iso}'")
    dt.vacuum(retention_hours=168, dry_run=False)  # 7-day file retention

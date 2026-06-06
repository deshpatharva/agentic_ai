"""
Delta Lake writer — append-only analytics tables.

Tables
------
daily_usage   partitioned by date          — pipeline runs, uploads, token counts
job_matches   partitioned by year/month    — scraped job postings per user

Storage path: DELTA_STORAGE_PATH env var (default: ./delta_store)
Prod: set DELTA_STORAGE_PATH=s3://your-bucket/delta/
"""

import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from deltalake.exceptions import TableNotFoundError

from config import AZURE_STORAGE_ACCOUNT_NAME, DELTA_STORAGE_PATH

# Threading lock to prevent concurrent first-write table corruption
_write_lock = threading.Lock()

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
    with _write_lock:
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


def write_job_match(record: dict) -> None:
    """
    Append a scraped job match to the job_matches Delta table.

    Expected keys: user_id, resume_id, job_title, company, url, source,
                   similarity_score, raw_description, scraped_at (ISO str or datetime),
                   is_read (bool, default False)
    """
    with _write_lock:
        scraped_at = record.get("scraped_at", datetime.now(timezone.utc).isoformat())
        if isinstance(scraped_at, datetime):
            scraped_at_str = scraped_at.isoformat()
            dt = scraped_at
        else:
            scraped_at_str = str(scraped_at)
            dt = datetime.fromisoformat(scraped_at_str[:19])

        row = {
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
        df = pd.DataFrame([row])
        write_deltalake(
            _matches_path(),
            df,
            schema=_MATCHES_SCHEMA,
            partition_by=["year", "month"],
            mode="append",
            storage_options=_storage_options(),
        )


# ── Readers ───────────────────────────────────────────────────────────────────

def read_usage_last_n_days(user_id: str, days: int = 30) -> pd.DataFrame:
    """
    Return aggregated daily usage totals for user_id over the last N days.
    Columns: date, pipeline_runs, uploads, input_tokens, output_tokens, tokens_used
    """
    path = _usage_path()
    if not _table_exists(path):
        return pd.DataFrame(columns=["date", "pipeline_runs", "uploads", "input_tokens", "output_tokens", "tokens_used"])

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path, storage_options=_storage_options())
    df = dt.to_pandas(
        filters=[("user_id", "=", user_id), ("date", ">=", cutoff)]
    )

    df = df[(df["user_id"] == user_id) & (df["date"] >= cutoff)]
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


def read_job_matches(
    user_id: str,
    days: int = 30,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """
    Return paginated job matches for user_id scraped in the last N days.
    Returns: {total, page, per_page, results: list[dict]}
    """
    path = _matches_path()
    if not _table_exists(path):
        return {"total": 0, "page": page, "per_page": per_page, "results": []}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    dt = DeltaTable.from_uri(path, storage_options=_storage_options())
    df = dt.to_pandas(
        filters=[("user_id", "=", user_id), ("scraped_at", ">=", cutoff)]
    )

    df = df[(df["user_id"] == user_id) & (df["scraped_at"] >= cutoff)]
    df = df.sort_values("scraped_at", ascending=False)

    total = len(df)
    start = (page - 1) * per_page
    page_df = df.iloc[start: start + per_page]

    results = page_df.drop(columns=["year", "month"], errors="ignore").to_dict(orient="records")
    return {"total": total, "page": page, "per_page": per_page, "results": results}


# ── Maintenance ───────────────────────────────────────────────────────────────

def vacuum_old_matches(retention_days: int = 90) -> None:
    """
    Hard-delete job_matches rows older than retention_days using Delta VACUUM.
    Run weekly via APScheduler.
    """
    path = _matches_path()
    if not _table_exists(path):
        return

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff_dt.isoformat()

    dt = DeltaTable.from_uri(path, storage_options=_storage_options())
    df = dt.to_pandas()

    # Keep only recent rows — rewrite the table
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

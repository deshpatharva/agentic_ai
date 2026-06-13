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


# ── read_usage_last_n_days — empty user_id (admin aggregate) ──────────────────

from unittest.mock import MagicMock, patch
import pandas as pd


def test_empty_user_id_returns_all_rows():
    """When user_id='', no user_id filter is applied — all rows returned."""
    mock_df = pd.DataFrame([
        {"user_id": "user-a", "date": "2026-06-05", "pipeline_runs": 2,
         "uploads": 2, "input_tokens": 1000, "output_tokens": 500, "tokens_used": 1500},
        {"user_id": "user-b", "date": "2026-06-05", "pipeline_runs": 1,
         "uploads": 1, "input_tokens": 800, "output_tokens": 300, "tokens_used": 1100},
    ])
    mock_dt = MagicMock()
    mock_dt.to_pandas.return_value = mock_df

    with patch("delta.writer._table_exists", return_value=True), \
         patch("delta.writer.DeltaTable") as MockDT:
        MockDT.return_value = mock_dt
        from delta.writer import read_usage_last_n_days
        result = read_usage_last_n_days("", 30)

    assert not result.empty, "Admin aggregate must return rows when user_id=''"
    assert result["pipeline_runs"].sum() == 3


def test_non_empty_user_id_filters_rows():
    """When user_id is non-empty, only that user's rows are returned."""
    mock_df = pd.DataFrame([
        {"user_id": "user-a", "date": "2026-06-05", "pipeline_runs": 2,
         "uploads": 2, "input_tokens": 1000, "output_tokens": 500, "tokens_used": 1500},
        {"user_id": "user-b", "date": "2026-06-05", "pipeline_runs": 1,
         "uploads": 1, "input_tokens": 800, "output_tokens": 300, "tokens_used": 1100},
    ])
    mock_dt = MagicMock()
    mock_dt.to_pandas.return_value = mock_df

    with patch("delta.writer._table_exists", return_value=True), \
         patch("delta.writer.DeltaTable") as MockDT:
        MockDT.return_value = mock_dt
        from delta.writer import read_usage_last_n_days
        result = read_usage_last_n_days("user-a", 30)

    assert result["pipeline_runs"].sum() == 2


# ── Batch writes, partition pushdown, unread count (Stage B items B1–B3) ──────

from datetime import datetime, timedelta, timezone


def _recent_iso(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_write_job_matches_single_transaction():
    """A batch of N records produces exactly ONE write_deltalake call with N rows."""
    records = [
        {"user_id": "u1", "job_title": f"Role {i}", "source": "adzuna",
         "scraped_at": _recent_iso()}
        for i in range(25)
    ]
    with patch("delta.writer.write_deltalake") as mock_write:
        dw.write_job_matches(records)

    assert mock_write.call_count == 1
    df = mock_write.call_args.args[1]
    assert len(df) == 25
    assert mock_write.call_args.kwargs["mode"] == "append"


def test_write_job_matches_empty_is_noop():
    with patch("delta.writer.write_deltalake") as mock_write:
        dw.write_job_matches([])
    assert mock_write.call_count == 0


def test_write_job_match_delegates_to_batch():
    """The single-record wrapper still works (one call, one row)."""
    with patch("delta.writer.write_deltalake") as mock_write:
        dw.write_job_match({"user_id": "u1", "job_title": "Role", "source": "adzuna",
                            "scraped_at": _recent_iso()})
    assert mock_write.call_count == 1
    assert len(mock_write.call_args.args[1]) == 1


def test_match_filters_dnf_includes_partition_columns():
    """Every OR-branch must constrain the year/month partition columns."""
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=45)
    dnf = dw._match_filters_dnf(cutoff_dt.isoformat(), cutoff_dt, "u1")

    assert len(dnf) >= 2  # 45 days spans at least 2 calendar months
    for branch in dnf:
        keys = [cond[0] for cond in branch]
        assert "year" in keys and "month" in keys
        assert ("user_id", "=", "u1") in branch
        assert any(c[0] == "scraped_at" and c[1] == ">=" for c in branch)


def test_read_job_matches_prunes_raw_description():
    """raw_description must not be requested from Delta nor returned to callers."""
    mock_df = pd.DataFrame([{
        "user_id": "u1", "resume_id": "", "job_title": "Role", "company": "Acme",
        "url": None, "source": "adzuna", "similarity_score": 0.8,
        "scraped_at": _recent_iso(), "is_read": False,
    }])
    mock_dt = MagicMock()
    mock_dt.to_pandas.return_value = mock_df

    with patch("delta.writer._table_exists", return_value=True), \
         patch("delta.writer.DeltaTable") as MockDT:
        MockDT.return_value = mock_dt
        result = dw.read_job_matches("u1", 30, 1, 20)

    assert "raw_description" not in mock_dt.to_pandas.call_args.kwargs["columns"]
    assert result["total"] == 1
    assert "raw_description" not in result["results"][0]


def test_count_unread_matches():
    mock_df = pd.DataFrame([
        {"user_id": "u1", "scraped_at": _recent_iso(0), "is_read": False},
        {"user_id": "u1", "scraped_at": _recent_iso(1), "is_read": True},
        {"user_id": "u1", "scraped_at": _recent_iso(2), "is_read": False},
    ])
    mock_dt = MagicMock()
    mock_dt.to_pandas.return_value = mock_df

    with patch("delta.writer._table_exists", return_value=True), \
         patch("delta.writer.DeltaTable") as MockDT:
        MockDT.return_value = mock_dt
        assert dw.count_unread_matches("u1", 30) == 2

    # count must use a column-pruned read
    cols = mock_dt.to_pandas.call_args.kwargs["columns"]
    assert "raw_description" not in cols and "job_title" not in cols


def test_count_unread_matches_no_table():
    with patch("delta.writer._table_exists", return_value=False):
        assert dw.count_unread_matches("u1", 30) == 0


# ── Stage B P3: filters before pagination (R1) ───────────────────────────────

def test_read_job_matches_filters_before_pagination():
    """source/min_score filtering must happen BEFORE pagination: total reflects
    the filtered count and page slicing applies to the filtered set."""
    rows = []
    for i in range(30):
        rows.append({
            "user_id": "u1", "resume_id": "", "job_title": f"Role {i}",
            "company": "Acme", "url": None,
            "source": "adzuna" if i % 2 == 0 else "remoteok",
            "similarity_score": 0.9 if i % 3 == 0 else 0.2,
            "scraped_at": _recent_iso(0), "is_read": False,
        })
    mock_df = pd.DataFrame(rows)
    mock_dt = MagicMock()
    mock_dt.to_pandas.return_value = mock_df

    with patch("delta.writer._table_exists", return_value=True),          patch("delta.writer.DeltaTable") as MockDT:
        MockDT.return_value = mock_dt
        result = dw.read_job_matches("u1", 30, 1, 5, source="adzuna")

    assert result["total"] == 15, "total must be the FILTERED count"
    assert len(result["results"]) == 5
    assert all(r["source"] == "adzuna" for r in result["results"])

    with patch("delta.writer._table_exists", return_value=True),          patch("delta.writer.DeltaTable") as MockDT:
        MockDT.return_value = mock_dt
        result = dw.read_job_matches("u1", 30, 1, 50, min_score=0.5)

    assert result["total"] == 10
    assert all((r["similarity_score"] or 0) >= 0.5 for r in result["results"])

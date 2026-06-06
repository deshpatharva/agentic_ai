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
        MockDT.from_uri.return_value = mock_dt
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
        MockDT.from_uri.return_value = mock_dt
        from delta.writer import read_usage_last_n_days
        result = read_usage_last_n_days("user-a", 30)

    assert result["pipeline_runs"].sum() == 2

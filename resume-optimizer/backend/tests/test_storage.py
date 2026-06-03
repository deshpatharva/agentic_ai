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

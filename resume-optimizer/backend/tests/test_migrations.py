"""
Tests for Alembic migration execution.
Verifies that 0001_initial_schema runs cleanly on SQLite and is idempotent.
"""
import os
import sys
import sqlite3
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_smoke.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("google_ai_studio_api_key", "test")
os.environ.setdefault("groq_api_key", "test")

sys.path.insert(0, str(Path(__file__).parent.parent))

import config as cfg
from db.session import _run_migrations


def test_migrations_create_all_tables(tmp_path, monkeypatch):
    """Migrations must create all 8 expected tables."""
    db_file = tmp_path / "test_migrate.db"
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    _run_migrations()

    conn = sqlite3.connect(str(db_file))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'alembic_%'"
        ).fetchall()
    }
    conn.close()

    assert tables == {"users", "resumes", "pipeline_jobs", "pipeline_events", "plan_limits", "promo_codes", "user_promo_redemptions", "provider_costs"}


def test_migrations_idempotent(tmp_path, monkeypatch):
    """Running migrations twice must not raise."""
    db_file = tmp_path / "test_migrate_idem.db"
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    _run_migrations()
    _run_migrations()  # must not raise


def test_migrations_stamped_after_run(tmp_path, monkeypatch):
    """Alembic version table must contain head revision after migration."""
    db_file = tmp_path / "test_migrate_stamp.db"
    monkeypatch.setattr(cfg, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")

    _run_migrations()

    conn = sqlite3.connect(str(db_file))
    rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "0005"

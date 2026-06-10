"""
Schema-level tests — verify Profile and JdScrapeCache tables + Resume.profile_id column.
No HTTP; uses in-memory SQLite.
"""

import os
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_models.db")
os.environ.setdefault("google_ai_studio_api_key", "test")

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from db.models import Base

TEST_DB_URL = "sqlite+aiosqlite:///./test_models.db"
_engine = create_async_engine(TEST_DB_URL, echo=False)


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()
    try:
        os.remove("./test_models.db")
    except (FileNotFoundError, PermissionError):
        pass


@pytest.mark.asyncio
async def test_profiles_table_exists():
    async with _engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert "profiles" in tables


@pytest.mark.asyncio
async def test_jd_scrape_cache_table_exists():
    async with _engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert "jd_scrape_cache" in tables


@pytest.mark.asyncio
async def test_resumes_has_profile_id_column():
    async with _engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sync_conn: [c["name"] for c in inspect(sync_conn).get_columns("resumes")]
        )
    assert "profile_id" in cols

"""Tests for _resolve_or_create_profile (auto-profile feature).

All DB and LLM calls are mocked — these are pure logic tests.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Set env vars before any app imports so db.session picks up sqlite.
os.environ.setdefault("JWT_SECRET",   "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_auto_profile.db")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("ANTHROPIC_API_KEY",         "test")
os.environ.setdefault("GROQ_API_KEY",              "test")


def _make_profile(label="Software Engineer", pid=None):
    p = MagicMock()
    p.id = pid or uuid.uuid4()
    p.label = label
    p.sections = {"summary": "Experienced engineer", "skills": ["Python"]}
    p.created_at = datetime.now(timezone.utc)
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_job(profile_id=None):
    job = MagicMock()
    job.profile_id = profile_id
    return job


# ── same domain: top score above threshold → reuse matching profile ───────────

class TestSameDomain:
    @pytest.mark.asyncio
    async def test_links_best_matching_profile(self):
        from main import _resolve_or_create_profile

        existing_id = uuid.uuid4()
        existing = _make_profile("Software Engineer", pid=existing_id)
        job_uuid = uuid.uuid4()

        scored = [{"id": str(existing_id), "label": "Software Engineer",
                   "match_pct": 85, "reason": "close match"}]

        with (
            patch("main.AsyncSessionLocal") as mock_session_cls,
            patch("main._score_profiles", new=AsyncMock(return_value=scored)) as mock_score,
        ):
            db_ctx = AsyncMock()
            db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
            db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = db_ctx

            # job has no source profile
            db_ctx.scalar = AsyncMock(return_value=_make_job(profile_id=None))
            mock_result = MagicMock()
            mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
            db_ctx.execute = AsyncMock(return_value=mock_result)

            result = await _resolve_or_create_profile(
                job_uuid=job_uuid,
                user_id=str(uuid.uuid4()),
                optimized_text="optimized resume",
                jd_text="Senior Python Developer",
                jd_keywords=["Python", "FastAPI"],
                industry="software",
            )

        assert result == existing_id

    @pytest.mark.asyncio
    async def test_no_new_profile_created_for_same_domain(self):
        from main import _resolve_or_create_profile

        existing_id = uuid.uuid4()
        existing = _make_profile("Python Developer", pid=existing_id)
        scored = [{"id": str(existing_id), "label": "Python Developer",
                   "match_pct": 75, "reason": "same domain"}]

        with (
            patch("main.AsyncSessionLocal") as mock_session_cls,
            patch("main._score_profiles", new=AsyncMock(return_value=scored)),
        ):
            db_ctx = AsyncMock()
            db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
            db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = db_ctx
            db_ctx.scalar = AsyncMock(return_value=_make_job(profile_id=None))
            mock_result = MagicMock()
            mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
            db_ctx.execute = AsyncMock(return_value=mock_result)
            db_ctx.add = MagicMock()
            db_ctx.commit = AsyncMock()

            await _resolve_or_create_profile(
                job_uuid=uuid.uuid4(),
                user_id=str(uuid.uuid4()),
                optimized_text="text",
                jd_text="Python Backend",
                jd_keywords=["Python"],
                industry="software",
            )
            # Should NOT create a new profile row
            db_ctx.add.assert_not_called()


# ── new domain: top score below threshold → create new profile ────────────────

class TestNewDomain:
    @pytest.mark.asyncio
    async def test_creates_new_profile_for_different_domain(self):
        from main import _resolve_or_create_profile

        existing_id = uuid.uuid4()
        existing = _make_profile("Backend Engineer", pid=existing_id)
        scored = [{"id": str(existing_id), "label": "Backend Engineer",
                   "match_pct": 45, "reason": "different domain"}]

        new_profile_id = uuid.uuid4()
        new_profile = _make_profile("Full-Stack Developer (auto)", pid=new_profile_id)

        fake_sections = {"summary": "Full-stack dev", "skills": ["React", "Node"]}

        with (
            patch("main.AsyncSessionLocal") as mock_session_cls,
            patch("main._score_profiles", new=AsyncMock(return_value=scored)),
            patch("main._parse_sections", new=AsyncMock(return_value=fake_sections)),
        ):
            db_ctx = AsyncMock()
            db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
            db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = db_ctx
            db_ctx.scalar = AsyncMock(return_value=_make_job(profile_id=None))

            mock_result = MagicMock()
            mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
            db_ctx.execute = AsyncMock(return_value=mock_result)
            db_ctx.add = MagicMock()
            db_ctx.commit = AsyncMock()
            db_ctx.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, 'id', new_profile_id))

            result = await _resolve_or_create_profile(
                job_uuid=uuid.uuid4(),
                user_id=str(uuid.uuid4()),
                optimized_text="full-stack resume",
                jd_text="Full Stack Web Developer",
                jd_keywords=["React", "Node.js"],
                industry="Full-Stack Developer",
            )

        # New profile was added
        db_ctx.add.assert_called_once()
        added = db_ctx.add.call_args[0][0]
        assert "(auto)" in added.label
        assert added.label_confirmed is False
        assert added.sections == fake_sections

    @pytest.mark.asyncio
    async def test_duplicate_label_guard_skips_creation(self):
        """If an (auto) profile with the same derived label already exists, skip."""
        from main import _resolve_or_create_profile

        auto_profile_id = uuid.uuid4()
        auto_profile = _make_profile("Full-Stack Developer (auto)", pid=auto_profile_id)
        scored = [{"id": str(auto_profile_id), "label": "Full-Stack Developer (auto)",
                   "match_pct": 30, "reason": "different"}]

        with (
            patch("main.AsyncSessionLocal") as mock_session_cls,
            patch("main._score_profiles", new=AsyncMock(return_value=scored)),
        ):
            db_ctx = AsyncMock()
            db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
            db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = db_ctx
            db_ctx.scalar = AsyncMock(return_value=_make_job(profile_id=None))

            mock_result = MagicMock()
            mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[auto_profile])))
            db_ctx.execute = AsyncMock(return_value=mock_result)
            db_ctx.add = MagicMock()

            result = await _resolve_or_create_profile(
                job_uuid=uuid.uuid4(),
                user_id=str(uuid.uuid4()),
                optimized_text="text",
                jd_text="Full Stack Web Developer",
                jd_keywords=["React"],
                industry="Full-Stack Developer",
            )

        # No new profile — returned existing auto profile
        db_ctx.add.assert_not_called()
        assert result == auto_profile_id


# ── resilience: failures must never crash the pipeline ───────────────────────

class TestResilience:
    @pytest.mark.asyncio
    async def test_score_profiles_exception_returns_source_profile(self):
        from main import _resolve_or_create_profile

        source_id = uuid.uuid4()
        existing = _make_profile()

        with (
            patch("main.AsyncSessionLocal") as mock_session_cls,
            patch("main._score_profiles", new=AsyncMock(side_effect=Exception("LLM down"))),
        ):
            db_ctx = AsyncMock()
            db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
            db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = db_ctx
            db_ctx.scalar = AsyncMock(return_value=_make_job(profile_id=source_id))

            mock_result = MagicMock()
            mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
            db_ctx.execute = AsyncMock(return_value=mock_result)

            # Should raise — the caller in _run_pipeline_task wraps in try/except.
            with pytest.raises(Exception):
                await _resolve_or_create_profile(
                    job_uuid=uuid.uuid4(),
                    user_id=str(uuid.uuid4()),
                    optimized_text="text",
                    jd_text="Some JD",
                    jd_keywords=[],
                    industry="",
                )

    @pytest.mark.asyncio
    async def test_parse_sections_failure_returns_source_profile(self):
        """When _parse_sections fails on new-domain path, fall back to source profile."""
        from main import _resolve_or_create_profile

        source_id = uuid.uuid4()
        existing = _make_profile("Backend Engineer", pid=uuid.uuid4())
        scored = [{"id": str(existing.id), "label": "Backend Engineer",
                   "match_pct": 20, "reason": "different"}]

        with (
            patch("main.AsyncSessionLocal") as mock_session_cls,
            patch("main._score_profiles", new=AsyncMock(return_value=scored)),
            patch("main._parse_sections", new=AsyncMock(side_effect=Exception("parse failed"))),
        ):
            db_ctx = AsyncMock()
            db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
            db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = db_ctx
            db_ctx.scalar = AsyncMock(return_value=_make_job(profile_id=source_id))

            mock_result = MagicMock()
            mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
            db_ctx.execute = AsyncMock(return_value=mock_result)
            db_ctx.add = MagicMock()

            result = await _resolve_or_create_profile(
                job_uuid=uuid.uuid4(),
                user_id=str(uuid.uuid4()),
                optimized_text="text",
                jd_text="Web Dev JD",
                jd_keywords=["React"],
                industry="Web Developer",
            )

        # Fell back to source profile, no new profile created
        db_ctx.add.assert_not_called()
        assert result == source_id

    @pytest.mark.asyncio
    async def test_no_profiles_returns_source_profile_id(self):
        """If user has no profiles, return the source profile without any LLM call."""
        from main import _resolve_or_create_profile

        source_id = uuid.uuid4()

        with (
            patch("main.AsyncSessionLocal") as mock_session_cls,
            patch("main._score_profiles", new=AsyncMock()) as mock_score,
        ):
            db_ctx = AsyncMock()
            db_ctx.__aenter__ = AsyncMock(return_value=db_ctx)
            db_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = db_ctx
            db_ctx.scalar = AsyncMock(return_value=_make_job(profile_id=source_id))

            mock_result = MagicMock()
            mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            db_ctx.execute = AsyncMock(return_value=mock_result)

            result = await _resolve_or_create_profile(
                job_uuid=uuid.uuid4(),
                user_id=str(uuid.uuid4()),
                optimized_text="text",
                jd_text="Some JD",
                jd_keywords=[],
                industry="",
            )

        mock_score.assert_not_called()
        assert result == source_id

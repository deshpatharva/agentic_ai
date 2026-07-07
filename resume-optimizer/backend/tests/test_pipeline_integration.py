"""Tests for Task 8: JD metadata threading and MAX_ITERATIONS loop."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

_BACKEND = Path(__file__).parent.parent
_MAIN_SRC = (_BACKEND / "main.py").read_text(encoding="utf-8")
# Slice to just _run_pipeline_task body (avoids matching imports/other funcs)
_FUNC_START = _MAIN_SRC.find("async def _run_pipeline_task(")
assert _FUNC_START != -1, "_run_pipeline_task not found in main.py"
_PIPELINE_SRC = _MAIN_SRC[_FUNC_START:]


def test_pipeline_delegates_iterations_to_agent_loop():
    """The old MAX_ITERATIONS loop moved into the Phase 2 agent loop:
    the pipeline must call run_optimization_async and surface its iteration count."""
    assert "run_optimization_async(" in _PIPELINE_SRC, \
        "Pipeline must delegate Phase 2 to run_optimization_async"
    assert "iterations" in _PIPELINE_SRC, \
        "Pipeline must surface the agent loop's iteration count"


def test_pipeline_threads_seniority_to_scorer():
    """_run_pipeline_task must pass seniority_level to score_combined."""
    assert "seniority_level" in _PIPELINE_SRC, \
        "seniority_level from JD analyzer not threaded to score_combined"


def test_pipeline_calls_humanize_resume():
    """_run_pipeline_task must call humanize_resume after optimization."""
    assert "humanize_resume" in _PIPELINE_SRC, \
        "humanize_resume not called in _run_pipeline_task"


def test_pipeline_threads_industry_to_humanizer():
    """humanize_resume call must receive industry argument."""
    humanize_pos = _PIPELINE_SRC.find("humanize_resume(")
    assert humanize_pos != -1, "humanize_resume not called in pipeline"
    # Get context around the call
    call_context = _PIPELINE_SRC[humanize_pos: humanize_pos + 300]
    assert "industry" in call_context, \
        "industry not passed to humanize_resume"


def test_pipeline_iterations_not_hardcoded_to_one():
    """iterations= value persisted to DB must not be hardcoded to 1."""
    assert "iterations=1" not in _PIPELINE_SRC, \
        "iterations persisted to Resume is hardcoded to 1 — use actual loop count"

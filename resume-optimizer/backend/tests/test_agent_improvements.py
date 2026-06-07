"""Tests for agent pipeline integration improvements."""
import os, sys, inspect
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


def test_fabrication_guard_called_after_optimization():
    """fabrication_guard must be called after optimization and before generate_docx."""
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    guard_pos = source.find("fabrication_guard(")
    docx_pos  = source.find("generate_docx(")
    optim_pos = source.find("run_optimization_async(")
    assert guard_pos != -1, "fabrication_guard not called in _run_pipeline_task"
    assert optim_pos != -1, "run_optimization_async not found in _run_pipeline_task"
    assert docx_pos  != -1, "generate_docx not found in _run_pipeline_task"
    assert optim_pos < guard_pos, \
        "fabrication_guard must be called AFTER run_optimization_async"
    assert guard_pos < docx_pos, \
        "fabrication_guard must be called BEFORE generate_docx"

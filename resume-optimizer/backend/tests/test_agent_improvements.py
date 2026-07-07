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


def test_no_live_crewai_imports():
    """No module outside _archive/ and optimizer_agent.py should import the crewai package."""
    import re
    from pathlib import Path
    backend = Path(__file__).parent.parent
    # Match actual import statements, not docstrings or comments.
    _crewai_import_re = re.compile(r"^\s*(from\s+crewai|import\s+crewai)", re.MULTILINE)
    violations = []
    for py_file in backend.rglob("*.py"):
        # Skip archived and soon-to-be-archived files
        if "_archive" in str(py_file) or py_file.name == "optimizer_agent.py":
            continue
        if "__pycache__" in str(py_file):
            continue
        source = py_file.read_text(encoding="utf-8")
        if _crewai_import_re.search(source):
            violations.append(str(py_file.relative_to(backend)))
    assert not violations, f"Live crewai imports found: {violations}"


def test_fabrication_guard_called_after_optimization():
    """fabrication_guard must be called after optimization and before generate_docx."""
    main_path = Path(__file__).parent.parent / "main.py"
    main_source = main_path.read_text(encoding="utf-8")
    func_start = main_source.find("async def _run_pipeline_task(")
    assert func_start != -1, "_run_pipeline_task not found in main.py"
    source = main_source[func_start:]

    # matches both direct calls and asyncio.to_thread(fabrication_guard, ...)
    guard_pos = source.find("fabrication_guard")
    docx_pos  = source.find("generate_docx")
    optim_pos = source.find("run_optimization_async(")
    assert guard_pos != -1, "fabrication_guard not called in _run_pipeline_task"
    assert optim_pos != -1, "run_optimization_async not found in _run_pipeline_task"
    assert docx_pos  != -1, "generate_docx not found in _run_pipeline_task"
    assert optim_pos < guard_pos, \
        "fabrication_guard must be called AFTER run_optimization_async"
    assert guard_pos < docx_pos, \
        "fabrication_guard must be called BEFORE generate_docx"

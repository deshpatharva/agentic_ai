"""
Tests for T5.1 (stateless session design) and T5.3 (Delta writes fire-and-forget).
"""
from pathlib import Path


# -- T5.1: Session isolation ---------------------------------------------------

def test_resume_state_is_isolated_between_runs():
    """Two ResumeState instances must not share mutable state."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.tools import ResumeState

    state_a = ResumeState({"experience": "5 years at Acme"})
    state_b = ResumeState({"experience": "2 years at Beta"})

    # Mutate only state_a
    state_a.update_section("experience", "10 years at Acme -- updated")
    state_a.add_tokens(100, 50)

    # state_b must be unaffected
    assert state_b.get_section("experience") == "2 years at Beta", (
        "Mutating state_a should not affect state_b -- instances must be independent"
    )
    assert state_b.total_tokens() == 0, (
        "Token accounting in state_b must not reflect state_a's token adds"
    )


def test_no_module_level_sessions_dict():
    """agents/tools.py must not contain a module-level _sessions dict."""
    tools_path = Path(__file__).parent.parent / "agents" / "tools.py"
    source = tools_path.read_text()

    # Check for the old CrewAI-era patterns that would indicate shared state
    assert "_sessions: dict" not in source, (
        "agents/tools.py must not declare a module-level _sessions dict -- "
        "found '_sessions: dict'. Remove shared session state."
    )
    assert "_sessions = {}" not in source, (
        "agents/tools.py must not declare a module-level _sessions dict -- "
        "found '_sessions = {}'. Remove shared session state."
    )


# -- T5.3: Delta writes fire-and-forget ----------------------------------------

def test_delta_write_is_fire_and_forget():
    """write_daily_usage must be wrapped in asyncio.create_task, not awaited directly."""
    source = (Path(__file__).parent.parent / "main.py").read_text()

    # Find the *call site* (not the import line).
    # The import line: 'from delta.writer import write_daily_usage ...' has no create_task.
    # The call site: asyncio.create_task(asyncio.to_thread(write_daily_usage, {...}))
    search_term = "write_daily_usage"
    import_marker = "from delta.writer import"

    idx = source.find(search_term)
    while idx != -1:
        line_start = source.rfind("\n", 0, idx) + 1
        line = source[line_start:source.find("\n", idx)]
        if import_marker not in line:
            break
        idx = source.find(search_term, idx + 1)

    assert idx != -1, "write_daily_usage call site not found in main.py"

    surrounding = source[max(0, idx - 100):idx + 200]
    assert "create_task" in surrounding, (
        "write_daily_usage must be wrapped in asyncio.create_task -- "
        "pipeline should not block on Delta Lake writes. "
        "Context around call:\n" + surrounding
    )

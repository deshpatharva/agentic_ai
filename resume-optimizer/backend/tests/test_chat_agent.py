"""Tests for the optimize co-pilot — pure functions only, no DB or LLM calls."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── agent.py ─────────────────────────────────────────────────────────────────

from chat.agent import render_system_prompt
from chat.tools import parse_tool_calls, message_text, TOOLS, LAUNCH_TOOL, SAVE_TOOL, DOWNLOAD_TOOL, EDIT_TOOL
from chat.gaps import compute_gaps
from utils.text_sanitizer import sanitize_resume_text
from utils.optimization_report import build_report


class TestOptimizationReport:
    def test_addressed_vs_remaining(self):
        jd = {"required_hard_skills": ["Snowflake", "Azure Data Factory", "PySpark"]}
        r = build_report(jd, "PySpark work", "PySpark and Snowflake migration", 70,
                         {"average": 90, "ats": 88, "impact": 92, "skills_gap": 95, "readability": 90}, 2)
        assert r["baseline_score"] == 70 and r["final_score"] == 90
        assert "Snowflake" in r["gaps_addressed"]
        assert "Azure Data Factory" in r["gaps_remaining"]
        assert r["iterations"] == 2

    def test_report_surfaced_in_prompt(self):
        jd = {"required_hard_skills": ["Snowflake"]}
        r = build_report(jd, "no match", "now has Snowflake", 70,
                         {"average": 90, "ats": 88, "impact": 92, "skills_gap": 95, "readability": 90}, 1)
        prompt = render_system_prompt({"last_result": {"report": r}})
        assert "Score improved from 70 to 90" in prompt
        assert "Snowflake" in prompt


class TestSanitizeResumeText:
    def test_strips_placeholder_metric_clause(self):
        assert sanitize_resume_text("improved agility by [XX%].") == "improved agility."

    def test_strips_standalone_placeholder(self):
        # "of [XX%]" matches the connective-clause pattern, so "of" is consumed too.
        assert sanitize_resume_text("gain of [XX%] here") == "gain here"

    def test_preserves_currency(self):
        s = "saved $500K and $200K, lost $335"
        assert sanitize_resume_text(s) == s

    def test_strips_latex_dollar_leak(self):
        assert sanitize_resume_text("processed $(100M+events/day$ daily") == "processed (100M+events/day daily"

    def test_empty(self):
        assert sanitize_resume_text("") == ""


class TestParseToolCalls:
    def test_launch_call_with_json_string_args(self):
        msg = {"content": "Tailoring now.", "tool_calls": [
            {"function": {"name": "launch_optimizer",
                          "arguments": '{"profile_id": "abc-123", "added_context": "Azure ML at Contoso"}'}}
        ]}
        calls = parse_tool_calls(msg)
        assert calls == [{"name": "launch_optimizer",
                          "arguments": {"profile_id": "abc-123", "added_context": "Azure ML at Contoso"}}]
        assert message_text(msg) == "Tailoring now."

    def test_malformed_args_yield_empty_dict(self):
        msg = {"content": "", "tool_calls": [{"function": {"name": "save_profile", "arguments": "{not json"}}]}
        assert parse_tool_calls(msg) == [{"name": "save_profile", "arguments": {}}]

    def test_no_tool_calls(self):
        assert parse_tool_calls({"content": "just chatting"}) == []

    def test_dict_args_passthrough(self):
        msg = {"tool_calls": [{"function": {"name": "save_profile", "arguments": {"label": "DE"}}}]}
        assert parse_tool_calls(msg) == [{"name": "save_profile", "arguments": {"label": "DE"}}]

    def test_tools_shape(self):
        names = {t["function"]["name"] for t in TOOLS}
        assert names == {LAUNCH_TOOL, SAVE_TOOL, DOWNLOAD_TOOL, EDIT_TOOL}


class TestComputeGaps:
    def test_missing_skill_surfaces(self):
        jd = {"required_hard_skills": ["Azure Data Factory", "PySpark", "Snowflake"],
              "critical_keywords": ["dbt"], "tech_stack": ["Kafka"]}
        gaps = compute_gaps(jd, ["PySpark", "Kafka"], "Built Snowflake warehouse and dbt models")
        assert gaps == ["Azure Data Factory"]

    def test_empty_inputs(self):
        assert compute_gaps({}, [], "") == []

    def test_priority_and_limit(self):
        jd = {"required_hard_skills": ["A", "B"], "critical_keywords": ["C"], "tech_stack": ["D"]}
        assert compute_gaps(jd, [], "", limit=2) == ["A", "B"]

    def test_case_insensitive_match(self):
        jd = {"required_hard_skills": ["python"]}
        assert compute_gaps(jd, ["Python"], "") == []


class TestPromptToolGuidance:
    def test_no_id_leak_instruction_present(self):
        prompt = render_system_prompt({"profiles": [{"id": "abc", "label": "SWE"}]})
        assert "NEVER print a profile id" in prompt

    def test_tools_described(self):
        prompt = render_system_prompt({})
        assert "launch_optimizer" in prompt and "save_profile" in prompt

    def test_gaps_injected(self):
        prompt = render_system_prompt({
            "jd_text": "x",
            "profiles": [{"id": "a", "label": "DE"}],
            "_jd_matched_profiles": [{"id": "a", "label": "DE", "match_pct": 80}],
            "gaps": ["Azure Data Factory"],
        })
        assert "Azure Data Factory" in prompt

    def test_last_result_state_shown(self):
        prompt = render_system_prompt({"last_result": {"sections": {}, "final_score": 80}})
        assert "optimized resume was produced" in prompt
        assert "call save_profile" in prompt

    def test_no_last_result_no_result_state(self):
        prompt = render_system_prompt({})
        assert "optimized resume was produced" not in prompt

    def test_launched_state_blocks_relaunch(self):
        prompt = render_system_prompt({"_optimizer_launched": True, "profiles": []})
        assert "already been launched" in prompt
        assert "Do NOT call launch_optimizer again" in prompt


class TestRenderSystemPrompt:
    def test_profiles_injected(self):
        ctx = {"profiles": [{"id": "abc-123", "label": "Data Engineer"}]}
        prompt = render_system_prompt(ctx)
        assert "abc-123" in prompt
        assert "Data Engineer" in prompt

    def test_no_jd_state(self):
        prompt = render_system_prompt({})
        assert "No job description yet" in prompt

    def test_jd_present_state(self):
        prompt = render_system_prompt({"jd_text": "some jd", "profiles": []})
        assert "A job description has already been captured" in prompt

    def test_jd_fetch_error_state(self):
        prompt = render_system_prompt({"jd_fetch_error": True, "profiles": []})
        assert "FAILED to fetch" in prompt or "could not be fetched" in prompt or "FAILED" in prompt

    def test_no_profiles_message(self):
        prompt = render_system_prompt({})
        assert "no saved profiles" in prompt


# ── window.py ─────────────────────────────────────────────────────────────────

from chat.window import build_window


class TestBuildWindow:
    def test_system_prompt_pinned_first(self):
        window = build_window("sys", [{"role": "user", "content": "hi"}])
        assert window[0] == {"role": "system", "content": "sys"}

    def test_turns_appended(self):
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        window = build_window("s", history)
        assert window[1]["role"] == "user"
        assert window[2]["role"] == "assistant"

    def test_sliding_window_trims(self):
        history = [{"role": "user", "content": str(i)} for i in range(20)]
        window = build_window("s", history, n=5)
        # system + 5 recent turns
        assert len(window) == 6
        assert window[-1]["content"] == "19"

    def test_orm_objects_supported(self):
        class FakeMsg:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        history = [FakeMsg("user", "hi"), FakeMsg("assistant", "there")]
        window = build_window("s", history)
        assert window[1]["content"] == "hi"
        assert window[2]["content"] == "there"

    def test_empty_history(self):
        window = build_window("only system", [])
        assert len(window) == 1
        assert window[0]["role"] == "system"


# ── session auto-title logic (mirrors chat/router.py — no DB import) ──────────

def _derive_title(message: str, existing: str | None = None) -> str:
    """Local copy of the auto-title logic so we can unit-test it without importing main."""
    if existing:
        return existing
    first_line = message.split("\n")[0].strip()
    return first_line[:80] or "New chat"


class TestAutoTitle:
    def test_single_line(self):
        assert _derive_title("Hello world") == "Hello world"

    def test_multiline_uses_first_line(self):
        assert _derive_title("Line one\nLine two") == "Line one"

    def test_truncates_at_80(self):
        assert len(_derive_title("A" * 100)) == 80

    def test_empty_falls_back(self):
        assert _derive_title("   \n  ") == "New chat"

    def test_existing_title_preserved(self):
        assert _derive_title("New msg", existing="Old title") == "Old title"


# ── sections_to_text grouped skills ──────────────────────────────────────────

from utils.profile_utils import sections_to_text


class TestSectionsToTextSkills:
    def test_flat_skills_when_no_categories(self):
        text = sections_to_text({"skills": ["Python", "SQL"]})
        assert "Python, SQL" in text

    def test_grouped_skills_emit_label_lines(self):
        sections = {
            "skills": ["Python", "SQL", "AWS"],
            "skill_categories": {
                "Languages": ["Python", "SQL"],
                "Cloud": ["AWS"],
            },
        }
        text = sections_to_text(sections)
        assert "Languages: Python, SQL" in text
        assert "Cloud: AWS" in text

    def test_empty_category_skipped(self):
        sections = {
            "skills": ["Python"],
            "skill_categories": {"Languages": ["Python"], "Empty": []},
        }
        text = sections_to_text(sections)
        assert "Empty" not in text


# ── categorize_skills fallback ────────────────────────────────────────────────

import asyncio


class TestCategorizeSkillsFallback:
    def test_returns_flat_on_empty_input(self):
        from utils.skills_normalizer import categorize_skills
        result = asyncio.run(categorize_skills([], ""))
        assert result == {"": []}

    def test_returns_flat_on_empty_tokens_immediately(self):
        """categorize_skills short-circuits on empty input without any LLM call."""
        from utils.skills_normalizer import categorize_skills
        # Empty input → immediate flat return, no LLM call at all.
        result = asyncio.run(categorize_skills([], "data engineer"))
        assert result == {"": []}


# ── domain threshold constant is set and is numeric ───────────────────────────

class TestDomainThreshold:
    def test_threshold_in_config(self):
        import os
        os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
        os.environ.setdefault("ANTHROPIC_API_KEY",         "test")
        os.environ.setdefault("GROQ_API_KEY",              "test")
        from config import DOMAIN_MATCH_THRESHOLD
        assert isinstance(DOMAIN_MATCH_THRESHOLD, int)
        assert 0 < DOMAIN_MATCH_THRESHOLD <= 100

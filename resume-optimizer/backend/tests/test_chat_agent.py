"""Tests for the optimize co-pilot — pure functions only, no DB or LLM calls."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── agent.py ─────────────────────────────────────────────────────────────────

from chat.agent import extract_handoff, in_sentinel, render_system_prompt


class TestExtractHandoff:
    def test_valid_payload(self):
        text = 'Launching now.\n[READY_TO_OPTIMIZE: {"profile_id": "abc", "instruction": ""}]'
        clean, payload = extract_handoff(text)
        assert payload == {"profile_id": "abc", "instruction": ""}
        assert "READY_TO_OPTIMIZE" not in clean
        assert "Launching now" in clean

    def test_malformed_json_returns_none(self):
        text = "text [READY_TO_OPTIMIZE: {not valid json}]"
        clean, payload = extract_handoff(text)
        assert payload is None
        assert clean  # visible text still returned

    def test_no_sentinel_returns_none(self):
        _, payload = extract_handoff("just a regular reply")
        assert payload is None

    def test_sentinel_mid_text(self):
        text = "Before.\n[READY_TO_OPTIMIZE: {\"profile_id\": \"x\", \"instruction\": \"\"}]\nAfter."
        clean, payload = extract_handoff(text)
        assert payload is not None
        assert "Before" in clean
        assert "After" in clean  # text after token is also kept

    def test_instruction_with_content(self):
        text = '[READY_TO_OPTIMIZE: {"profile_id": "123", "instruction": "emphasize leadership"}]'
        _, payload = extract_handoff(text)
        assert payload["instruction"] == "emphasize leadership"


class TestInSentinel:
    def test_true_when_prefix_present(self):
        assert in_sentinel("partial [READY_TO_OPTIMIZE: {") is True

    def test_false_when_no_prefix(self):
        assert in_sentinel("just a normal reply") is False

    def test_false_on_empty(self):
        assert in_sentinel("") is False


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

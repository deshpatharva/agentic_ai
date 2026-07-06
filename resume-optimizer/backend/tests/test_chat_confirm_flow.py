"""Confirm-before-acting: ambiguous short messages must PROPOSE paid actions,
never fire them (deep-review findings 4 and 5). Pure state-machine unit tests."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")

from chat.state_machine import (
    AWAITING_JD, JD_CAPTURED, try_deterministic,
)

PROFILES = [
    {"id": "p1", "label": "Data Engineer"},
    {"id": "p2", "label": "Software Engineer"},
]


def _jd_ctx(**extra):
    ctx = {"jd_text": "We need a data engineer with Kafka experience."}
    ctx.update(extra)
    return ctx


def test_bare_label_proposes_launch_instead_of_firing():
    ctx = _jd_ctx()
    out = try_deterministic(JD_CAPTURED, "Data Engineer", ctx, PROFILES)
    assert out["action"] == "respond"
    assert "yes" in out["response"].lower()
    assert ctx["_pending_confirm"] == {"action": "launch", "profile_id": "p1"}


def test_fuzzy_label_proposes_not_launches():
    ctx = _jd_ctx()
    out = try_deterministic(JD_CAPTURED, "data engineering", ctx, PROFILES)
    assert out["action"] == "respond"
    assert ctx["_pending_confirm"]["action"] == "launch"


def test_yes_with_pending_launch_fires():
    ctx = _jd_ctx(_pending_confirm={"action": "launch", "profile_id": "p1"})
    out = try_deterministic(JD_CAPTURED, "yes", ctx, PROFILES)
    assert out["action"] == "launch"
    assert out["profile_id"] == "p1"
    assert "_pending_confirm" not in ctx  # consumed


def test_yes_without_pending_goes_to_llm():
    # The gap-question case: "yes" may answer "do you have Kafka experience?"
    ctx = _jd_ctx(_jd_matched_profiles=[{"id": "p1", "label": "Data Engineer"}])
    out = try_deterministic(JD_CAPTURED, "yes", ctx, PROFILES)
    assert out is None


def test_other_message_clears_pending():
    ctx = _jd_ctx(_pending_confirm={"action": "launch", "profile_id": "p1"})
    out = try_deterministic(JD_CAPTURED, "actually, tell me about the gaps first", ctx, PROFILES)
    assert out is None  # goes to the LLM
    assert "_pending_confirm" not in ctx  # proposal dropped


def test_bare_label_in_awaiting_jd_proposes_download():
    ctx = {}
    out = try_deterministic(AWAITING_JD, "Software Engineer", ctx, PROFILES)
    assert out["action"] == "respond"
    assert ctx["_pending_confirm"] == {"action": "download", "profile_id": "p2"}


def test_yes_with_pending_download_fires():
    ctx = {"_pending_confirm": {"action": "download", "profile_id": "p2"}}
    out = try_deterministic(AWAITING_JD, "yes", ctx, PROFILES)
    assert out["action"] == "download"
    assert out["profile_id"] == "p2"


def test_picker_click_still_fires_instantly():
    ctx = _jd_ctx()
    out = try_deterministic(JD_CAPTURED, 'Use my "Data Engineer" profile', ctx, PROFILES)
    assert out["action"] == "launch"
    assert out["profile_id"] == "p1"

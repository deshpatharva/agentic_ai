"""Regression: fire_optimizer must resolve profile labels with the hardened
matcher, so a short/generic agent-emitted label can't incidentally select — and
launch a paid optimization against — the wrong profile.

The label-resolution was duplicated inline in fire_optimizer with an unguarded
bidirectional substring match; state_machine._find_profile_by_label was hardened
(min length + ratio) but that fix never reached this (paid) path.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_handoff.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")


class _Prof:
    """Minimal stand-in for a Profile row (only .label is read for matching)."""
    def __init__(self, label):
        self.label = label


def test_incidental_short_label_does_not_match_wrong_profile():
    from chat.handoff import _resolve_profile_by_label
    profiles = [_Prof("Senior Machine Learning Engineer")]
    # 'eng' is a substring of the label but far too short to be a real selection.
    assert _resolve_profile_by_label("eng", profiles) is None


def test_exact_label_still_resolves():
    from chat.handoff import _resolve_profile_by_label
    p = _Prof("Senior Machine Learning Engineer")
    assert _resolve_profile_by_label("Senior Machine Learning Engineer", [p]) is p


def test_quoted_exact_label_resolves():
    from chat.handoff import _resolve_profile_by_label
    p = _Prof("Data Scientist")
    assert _resolve_profile_by_label('"Data Scientist"', [p]) is p


def test_blank_label_matches_nothing():
    from chat.handoff import _resolve_profile_by_label
    assert _resolve_profile_by_label("", [_Prof("Data Scientist")]) is None

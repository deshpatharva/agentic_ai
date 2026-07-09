"""The profile-picker click must launch the EXACT chosen profile, deterministically.

Regression for the selection bug: the click's exact id was discarded and the chat
LLM re-resolved the profile by label — picking the wrong one among similar labels
(e.g. "Senior Data Engineer" vs an auto-created "Optimized Resume (auto)").
"""

from chat.router import _explicit_pick_launch

PROFILES = [
    {"id": "78bbacf2-good", "label": "Senior Data Engineer"},
    {"id": "63e9f1de-auto", "label": "Optimized Resume (auto)"},
]


def test_explicit_pick_launches_exact_id():
    out = _explicit_pick_launch("78bbacf2-good", PROFILES)

    assert out is not None
    assert out["action"] == "launch"
    assert out["profile_id"] == "78bbacf2-good"  # exact id, never re-resolved by label
    assert "Senior Data Engineer" in out["response"]


def test_explicit_pick_disambiguates_between_similar_profiles():
    # The other profile of the pair resolves to ITS own id — no cross-over.
    out = _explicit_pick_launch("63e9f1de-auto", PROFILES)
    assert out["profile_id"] == "63e9f1de-auto"


def test_explicit_pick_none_without_selection():
    # Typed messages carry no profile_id and must fall through to normal handling.
    assert _explicit_pick_launch(None, PROFILES) is None
    assert _explicit_pick_launch("", PROFILES) is None


def test_explicit_pick_ignores_foreign_id():
    # An id that isn't one of the user's own profiles is never launched blindly.
    assert _explicit_pick_launch("someone-elses-id", PROFILES) is None

"""Regression: fabrication_guard must not treat blank lines as dropped sentences.

reassemble() (utils/section_parser.reassemble) joins canonical sections with
"\n\n", so every real multi-section draft contains blank lines. A blank line is
not a fabrication, so it must not populate guard.gaps — otherwise the reflection
loop's early-exit `if all_above and not guard.gaps` (agent_loop.py) can never
fire and the model is fed phantom "persona-domain sentence dropped: ''" feedback.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_fabguard.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

# A clean, fully-attested two-section draft shaped exactly like reassemble() output.
_DRAFT = "Summary\nDrove a 40% latency reduction at scale.\n\nSkills\nPython, CI/CD, testing."


def test_clean_multisection_draft_yields_no_gaps():
    from agents.fact_extractor import extract_claims
    from agents.fabrication_guard import fabrication_guard

    ledger = extract_claims(_DRAFT)          # source == draft: nothing is fabricated
    guard = fabrication_guard(_DRAFT, ledger, _DRAFT)

    assert guard.gaps == [], guard.gaps


def test_blank_line_preserved_in_guard_text():
    from agents.fact_extractor import extract_claims
    from agents.fabrication_guard import fabrication_guard

    ledger = extract_claims(_DRAFT)
    guard = fabrication_guard(_DRAFT, ledger, _DRAFT)

    # The blank line between the two sections must survive so section spacing is kept.
    assert "" in guard.text.split("\n"), repr(guard.text)

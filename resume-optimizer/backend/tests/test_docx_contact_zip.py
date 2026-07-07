"""Regression: docx contact detection must recognize common US address lines
that the tightened ZIP heuristic dropped, without re-matching bare 5-digit
numbers in prose.

The prior fix (for '50000 users' false positives) replaced bare \\d{5} with
'ZIP+4' and 'City, ST 12345' branches only, so 'Boston MA 02115' (no comma) and
'Boston, Massachusetts 02139' (spelled-out state) regressed to plain body text.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_docxzip.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")


def test_recognizes_noncomma_and_spelled_out_state_zip():
    from generators.docx_generator import _is_contact_line
    assert _is_contact_line("Boston MA 02115", 1)              # no comma, 2-letter state
    assert _is_contact_line("Boston, Massachusetts 02139", 1)  # spelled-out state
    assert _is_contact_line("Chicago IL 60601", 1)             # no comma


def test_still_recognizes_previously_supported_formats():
    from generators.docx_generator import _is_contact_line
    assert _is_contact_line("Austin, TX 78701", 1)
    assert _is_contact_line("San Francisco, CA 94105-1234", 1)


def test_prose_with_bare_5digit_numbers_is_not_contact():
    from generators.docx_generator import _is_contact_line
    assert not _is_contact_line("Reached 50000 users; migrated 12000 records", 2)
    assert not _is_contact_line("Grew ARR to 45000 in Q3", 2)

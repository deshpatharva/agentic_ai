"""Final-pass sanitizer for generated resume text.

Strips two classes of LLM artifacts that degrade the output regardless of which
model produced them:

  1. Placeholder metrics — e.g. "increasing agility by [XX%]". The model should
     never invent a placeholder for a number it doesn't have; we remove them.
  2. LaTeX/markdown math leakage — stray "$" used as math delimiters (e.g.
     "$(100M+events/day$"), WITHOUT touching real currency like "$500K".

This is defensive: prompts also forbid these, but a deterministic strip
guarantees they never reach the .docx.
"""

from __future__ import annotations

import re

# "by/to/of [whatever]" — removes the dangling connective along with the placeholder.
_PLACEHOLDER_CLAUSE = re.compile(
    r"(?i)\s*\b(?:by|to|of|reaching|up\s+to|by\s+approximately|by\s+~)\s+\[[^\]]*\]"
)
# Any remaining bracket that looks like a placeholder (XX, %, TBD, N/A, "number", "...").
_PLACEHOLDER_BRACKET = re.compile(
    r"(?i)\[[^\]]*(?:%|x{2,}|tbd|n/?a|number|metric|value|placeholder|insert|\.\.\.|_{2,})[^\]]*\]"
)
# A "$" NOT immediately followed by (optional space +) a digit → LaTeX/stray, not currency.
_LATEX_DOLLAR = re.compile(r"\$(?!\s?\d)")

_MULTISPACE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:)])")


def sanitize_resume_text(text: str) -> str:
    """Remove placeholder metrics and LaTeX `$` leakage; preserve real currency."""
    if not text:
        return text
    t = _PLACEHOLDER_CLAUSE.sub("", text)
    t = _PLACEHOLDER_BRACKET.sub("", t)
    t = _LATEX_DOLLAR.sub("", t)
    # Tidy artifacts left by removals ("word  ," / "word ." / doubled spaces).
    t = _MULTISPACE.sub(" ", t)
    t = _SPACE_BEFORE_PUNCT.sub(r"\1", t)
    return t

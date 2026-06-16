"""
Async tool functions for the native-agent optimizer (Phase 2, PR-2).

DESIGN
======
This module is a standalone replacement for the CrewAI @tool-decorated
functions in optimizer_agent.py. Key differences:

  - All tool functions are plain ``async def`` — no @tool decorator, no
    asyncio.run(). The A+C driver awaits them directly.
  - Tool signatures accept ``state: ResumeState`` directly instead of a
    ``session_key`` string. The driver resolves the session and passes state in.
  - ResumeState, the session registry, and _budget_ok are defined here so
    other PR-2 modules (e.g. orchestration/optimizer.py) can import them
    without pulling in CrewAI dependencies from optimizer_agent.py.

SHARED STATE PATTERN
====================
Tools do NOT accept resume_text as a parameter.

Reasons:
  1. Token avalanche — passing a 1,500-word resume through JSON tool arguments
     embeds the resume 3x per tool call. Over 3 iterations with 4 tools that
     is ~36,000 words of redundant resume context.
  2. JSON serialisation failures — em-dashes, curly quotes, and multi-line
     bullet points inside JSON strings crash LiteLLM's serialiser.

Each tool:
  1. Receives ``state`` (a ResumeState) + small metadata CSVs
  2. Loads the target SECTION text from state (~200–400 words)
  3. Calls the LLM on that section only
  4. Updates the section in state and returns a short status string

TOKEN BUDGET ENFORCEMENT
========================
Tokens accumulate in ResumeState (thread-safe). Every tool checks the budget
at the start and returns early if exceeded.
"""

import threading
from typing import Dict, Optional

from config import (
    AGENT_TOKEN_BUDGET,
    MODEL_BULLET_STRENGTHEN,
    MODEL_KEYWORD_INJECT,
    MODEL_SECTION_HUMANIZE,
    MODEL_SKILLS_REWRITE,
)
from llm import complete
from utils.section_parser import SECTION_ORDER


# ── Shared session state ──────────────────────────────────────────────────────


class ResumeState:
    """
    Thread-safe container for resume sections and token accounting.

    One instance is created per optimisation job and registered in the
    module-level session registry before the agent loop starts. Tools mutate
    sections in-place. Token totals are the authoritative budget counter.
    """

    def __init__(self, sections: Dict[str, str], available_metrics: str = "") -> None:
        self._sections: Dict[str, str] = dict(sections)
        self.available_metrics: str = available_metrics
        self._total_input:    int   = 0
        self._total_output:   int   = 0
        self._total_cost_usd: float = 0.0
        self._lock = threading.Lock()

    # ── Section access ────────────────────────────────────────────────────────

    def get_section(self, name: str) -> str:
        with self._lock:
            return self._sections.get(name, "")

    def update_section(self, name: str, text: str) -> None:
        with self._lock:
            self._sections[name] = text

    def available_sections(self) -> list:
        with self._lock:
            return [k for k, v in self._sections.items() if v.strip()]

    # ── Token accounting ──────────────────────────────────────────────────────

    def add_tokens(self, input_tokens: int, output_tokens: int, cost_usd: float = 0.0) -> None:
        with self._lock:
            self._total_input  += input_tokens
            self._total_output += output_tokens
            self._total_cost_usd += cost_usd

    def total_tokens(self) -> int:
        with self._lock:
            return self._total_input + self._total_output

    @property
    def input_tokens(self) -> int:
        with self._lock:
            return self._total_input

    @property
    def output_tokens(self) -> int:
        with self._lock:
            return self._total_output

    @property
    def cost_usd(self) -> float:
        with self._lock:
            return self._total_cost_usd

    # ── Reassembly ────────────────────────────────────────────────────────────

    def reassemble(self) -> str:
        """Return the full resume text in canonical section order."""
        with self._lock:
            parts: list = []
            for name in SECTION_ORDER:
                text = self._sections.get(name, "").strip()
                if text:
                    parts.append(text)
            for name, text in self._sections.items():
                if name not in SECTION_ORDER and text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts)


# ── Session registry ──────────────────────────────────────────────────────────

_sessions: Dict[str, ResumeState] = {}
_sessions_lock = threading.Lock()
_session_created_at: dict = {}
_SESSION_TTL_SECONDS = 4 * 3600  # 4 hours


def cleanup_stale_sessions() -> int:
    """Remove sessions older than _SESSION_TTL_SECONDS. Called by the stuck-job reaper.

    Returns count of cleaned-up sessions.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    with _sessions_lock:
        stale = [
            k for k, t in _session_created_at.items()
            if (now - t).total_seconds() > _SESSION_TTL_SECONDS
        ]
        for k in stale:
            _sessions.pop(k, None)
            _session_created_at.pop(k, None)
    return len(stale)


def register_session(session_key: str, state: ResumeState) -> None:
    from datetime import datetime, timezone
    with _sessions_lock:
        _sessions[session_key] = state
        _session_created_at[session_key] = datetime.now(timezone.utc)


def get_session(session_key: str) -> Optional[ResumeState]:
    with _sessions_lock:
        return _sessions.get(session_key)


def cleanup_session(session_key: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_key, None)
        _session_created_at.pop(session_key, None)


# ── Budget helper ─────────────────────────────────────────────────────────────


def _budget_ok(state: ResumeState) -> tuple:
    """Return (True, '') if budget available, (False, message) if exceeded."""
    total = state.total_tokens()
    if total >= AGENT_TOKEN_BUDGET:
        return False, (
            f"Token budget reached ({total:,}/{AGENT_TOKEN_BUDGET:,}). "
            f"Optimization complete — remaining sections unchanged."
        )
    return True, ""


# ── Tool 1: Keyword injection (fixes low ATS score) ──────────────────────────


async def keyword_inject(
    state: ResumeState,
    missing_keywords_csv: str,
    target_sections_csv: str = "experience,summary",
) -> str:
    """
    Surgically inject missing ATS keywords into the target sections.

    Args:
        state: The ResumeState for this optimisation session.
        missing_keywords_csv: Comma-separated keywords from the ATS score's missing_keywords.
        target_sections_csv: Comma-separated sections to inject into.
            Valid: summary, experience, education, skills, certifications, projects.
            Default: experience,summary

    Returns:
        Short status string. Resume state is updated in-place.
    """
    ok, msg = _budget_ok(state)
    if not ok:
        return msg

    keywords = [k.strip() for k in missing_keywords_csv.split(",") if k.strip()]
    if not keywords:
        return "No keywords provided — nothing to inject."
    target_sections = [s.strip() for s in target_sections_csv.split(",") if s.strip()]
    updated: list = []

    for section_name in target_sections:
        section_text = state.get_section(section_name)
        if not section_text.strip():
            continue

        ok, msg = _budget_ok(state)
        if not ok:
            if updated:
                return msg + f" Partially updated: {', '.join(updated)}."
            return msg

        prompt = f"""Inject these missing keywords into the resume section below.

RULES — strictly follow all of them:
- Weave keywords into EXISTING sentences/bullets only. Do NOT add new sentences, clauses, or bullets.
- Inject only keywords that match the candidate's actual profession and the target role's domain.
- Skip any keyword implying a job function the candidate has never performed, regardless of field.
- Do NOT introduce any new responsibilities, collaborations, or role claims not already in the text.
- Do NOT change any metrics, dates, company names, or facts. NEVER insert placeholder metrics ("[XX%]").
- Do NOT copy job-description phrases verbatim, and do NOT repeat the same phrase across multiple
  bullets — vary the wording so it reads naturally, not keyword-stuffed.
- Plain text only — no markdown bold (**), no asterisks, no LaTeX or "$" math wrappers.

Keywords to inject: {', '.join(keywords)}

Section:
\"\"\"
{section_text}
\"\"\"

Return ONLY the updated section text."""

        try:
            result = await complete(prompt, MODEL_KEYWORD_INJECT)
        except Exception as exc:
            return f"LLM call failed: {exc}"
        state.add_tokens(
            result.get("input_tokens", 0),
            result.get("output_tokens", 0),
            result.get("cost_usd", 0.0),
        )
        if result.get("text"):
            state.update_section(section_name, result["text"])
            updated.append(section_name)

    if updated:
        return f"Keywords ({missing_keywords_csv}) injected into: {', '.join(updated)}."
    available = state.available_sections()
    return f"No target sections found ({target_sections_csv}). Available: {', '.join(available)}."


# ── Tool 2: Bullet strengthener (fixes low Impact score) ─────────────────────


async def bullet_strengthen(
    state: ResumeState,
    weak_bullets_csv: str,
) -> str:
    """
    Rewrite only the identified weak impact bullets with stronger action verbs.

    Args:
        state: The ResumeState for this optimisation session.
        weak_bullets_csv: The weak bullet texts verbatim from the Impact score's weak_bullets.

    Returns:
        Short status string. Resume state is updated in-place.
    """
    ok, msg = _budget_ok(state)
    if not ok:
        return msg

    experience_text = state.get_section("experience")
    if not experience_text.strip():
        available = state.available_sections()
        return (
            f"No experience section in state. Available: {', '.join(available)}. "
            f"Try keyword_inject on summary instead."
        )

    weak = [b.strip() for b in weak_bullets_csv.split(",") if b.strip()]
    if not weak:
        return "No weak bullets provided — nothing to strengthen."
    metrics_note = (
        f"You MAY use these verified metrics: {state.available_metrics}"
        if state.available_metrics
        else "Do NOT add metrics or numbers — none are verified from the original resume."
    )

    prompt = f"""Rewrite ONLY the following weak bullets with stronger past-tense action verbs.
Find them in the section below and replace them in-place.

Weak bullets to rewrite:
{chr(10).join(f'  - {b}' for b in weak)}

{metrics_note}

Rules:
- Only change the listed bullets — all other text stays IDENTICAL
- Strong past-tense action verb at the start of each bullet
- No fabricated companies, titles, dates, or metrics
- NEVER insert placeholder metrics like "[XX%]", "[N]", or "[number]". If a bullet has no
  number in the source, strengthen the verb and impact WITHOUT adding one.
- NEVER invent, inflate, or alter existing numbers. Keep every metric exactly as written.
  Do NOT introduce absolute claims like "100% reliability" or "100% compliance".
- Plain text only — no markdown, no LaTeX, no "$" math wrappers. Write currency as plain text ($500K).

Experience section:
\"\"\"
{experience_text}
\"\"\"

Return ONLY the complete updated experience section text."""

    try:
        result = await complete(prompt, MODEL_BULLET_STRENGTHEN)
    except Exception as exc:
        return f"LLM call failed: {exc}"
    state.add_tokens(
        result.get("input_tokens", 0),
        result.get("output_tokens", 0),
        result.get("cost_usd", 0.0),
    )
    if result.get("text"):
        state.update_section("experience", result["text"])
        return f"Strengthened {len(weak)} bullet(s) in the experience section."
    return "Bullet strengthening returned empty output — section unchanged."


# ── Tool 3: Skills section rewriter (fixes low Skills Gap score) ──────────────


async def skills_rewrite(
    state: ResumeState,
    missing_skills_csv: str,
) -> str:
    """
    Rewrite only the skills section to incorporate missing required skills.

    Args:
        state: The ResumeState for this optimisation session.
        missing_skills_csv: Comma-separated skills from the Skills Gap score's missing_skills.

    Returns:
        Short status string. Resume state is updated in-place.
    """
    ok, msg = _budget_ok(state)
    if not ok:
        return msg

    skills_text = state.get_section("skills")
    if not skills_text.strip():
        return (
            "No skills section found. Call keyword_inject with "
            f"target_sections_csv='experience' and missing_keywords_csv='{missing_skills_csv}'."
        )

    missing = [s.strip() for s in missing_skills_csv.split(",") if s.strip()]
    if not missing:
        return "No missing skills provided — nothing to add."

    prompt = f"""Rewrite the Skills section below to include the missing skills.
Integrate naturally — group with related existing skills if grouped.
Do NOT invent certifications or proficiency claims.
Only add a skill if it is plausible the candidate has it (a real tool/technology) —
skip skills that don't fit the candidate's background.
STRIP any parenthetical examples — add "Data migration tools", NOT "Data migration tools (e.g., SnowConvert)".
Do NOT copy job-description phrasing verbatim.
Plain text only — no LaTeX or "$" math.

Missing skills to add: {', '.join(missing)}

Skills section:
\"\"\"
{skills_text}
\"\"\"

Return ONLY the complete updated skills section text."""

    try:
        result = await complete(prompt, MODEL_SKILLS_REWRITE)
    except Exception as exc:
        return f"LLM call failed: {exc}"
    state.add_tokens(
        result.get("input_tokens", 0),
        result.get("output_tokens", 0),
        result.get("cost_usd", 0.0),
    )
    if result.get("text"):
        state.update_section("skills", result["text"])
        return f"Skills section updated to include: {missing_skills_csv}."
    return "Skills rewrite returned empty output — section unchanged."


# ── Tool 4: Section humanizer (fixes low Readability score) ──────────────────


async def section_humanize(
    state: ResumeState,
    section_name: str,
    issues_csv: str = "",
) -> str:
    """
    Polish language and readability of one resume section.

    Args:
        state: The ResumeState for this optimisation session.
        section_name: Section to polish: summary, experience, skills, or education.
        issues_csv: Comma-separated issues from the Readability score's issues field.
            Leave empty for general polish.

    Returns:
        Short status string. Resume state is updated in-place.
    """
    ok, msg = _budget_ok(state)
    if not ok:
        return msg

    section_text = state.get_section(section_name)
    if not section_text.strip():
        available = state.available_sections()
        return (
            f"Section '{section_name}' not found. "
            f"Available sections: {', '.join(available)}. "
            f"Retry with one of those names."
        )

    issues_note = (
        f"Specifically fix: {issues_csv}"
        if issues_csv.strip()
        else "Apply general language polish."
    )

    prompt = f"""Polish the {section_name} section below for readability and professional tone.
{issues_note}

Rules:
- Remove robotic phrases ('responsible for', 'assisted in', 'helped with', 'worked on')
- Strong action verbs, varied sentence structure
- Preserve ALL facts — no changes to names, dates, companies, or metrics
- NEVER insert placeholder metrics ("[XX%]") or invent/inflate numbers
- Plain text ONLY — no markdown, and NO LaTeX or "$" math wrappers (write "100M+ events/day"
  and "$500K" as plain text, never "$(100M+events/day$")

{section_name.title()} section:
\"\"\"
{section_text}
\"\"\"

Return ONLY the complete updated {section_name} section text."""

    try:
        result = await complete(prompt, MODEL_SECTION_HUMANIZE)
    except Exception as exc:
        return f"LLM call failed: {exc}"
    state.add_tokens(
        result.get("input_tokens", 0),
        result.get("output_tokens", 0),
        result.get("cost_usd", 0.0),
    )
    if result.get("text"):
        state.update_section(section_name, result["text"])
        return f"'{section_name}' polished. Issues addressed: {issues_csv or 'general polish'}."
    return f"Humanization of '{section_name}' returned empty output — section unchanged."

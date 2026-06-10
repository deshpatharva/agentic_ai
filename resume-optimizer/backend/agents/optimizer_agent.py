"""
Optimization Agent — Phase 2 of the resume optimization pipeline.

SHARED STATE PATTERN
====================
Tools do NOT accept resume_text as a parameter.

Reasons:
  1. Token avalanche — passing a 1,500-word resume through JSON tool arguments
     embeds the resume 3x per tool call (task desc + arg + output). Over 3
     iterations with 4 tools that is 36,000 words of redundant resume context.
  2. JSON serialization failures — em-dashes, curly quotes, and multi-line
     bullet points inside JSON strings crash LiteLLM's serializer.

Instead each tool:
  1. Receives only session_key (a short UUID string) + small metadata CSVs
  2. Loads the target SECTION text from module-level ResumeState (~200-400 words)
  3. Calls the LLM on that section only
  4. Updates the section in state and returns a short status string

TOKEN BUDGET ENFORCEMENT
========================
Tokens accumulate in ResumeState (thread-safe). Every tool checks the budget
at the start and returns early if exceeded. No RuntimeError is raised in callbacks
because CrewAI catches those in some versions — early return is more reliable.
"""

import asyncio
import threading
from typing import Dict, Optional

from crewai import Agent
try:
    from crewai.tools import tool
except ImportError:
    # Older crewai versions lack the @tool decorator — provide a no-op shim.
    def tool(func_or_name=None, **kwargs):  # type: ignore[misc]
        if callable(func_or_name):
            return func_or_name
        return lambda f: f

from config import (
    AGENT_TOKEN_BUDGET,
    MODEL_BULLET_STRENGTHEN,
    MODEL_KEYWORD_INJECT,
    MODEL_OPTIMIZER,
    MODEL_SECTION_HUMANIZE,
    MODEL_SKILLS_REWRITE,
    SCORE_TARGET,
)

from utils.section_parser import SECTION_ORDER

AGENT_MAX_ITER = 6  # max CrewAI agent iterations before forced stop


# ── Shared session state ──────────────────────────────────────────────────────

class ResumeState:
    """
    Thread-safe container for resume sections and token accounting.

    One instance is created per optimization job and registered in the
    module-level session registry before the crew starts. Tools mutate
    sections in-place. Token totals are the authoritative budget counter.
    """

    def __init__(self, sections: Dict[str, str], available_metrics: str = "") -> None:
        self._sections: Dict[str, str] = dict(sections)
        self.available_metrics: str = available_metrics
        self._total_input:  int = 0
        self._total_output: int = 0
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

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self._total_input  += input_tokens
            self._total_output += output_tokens

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
_session_created_at: Dict[str, "datetime"] = {}
_SESSION_TTL_SECONDS = 4 * 3600  # 4 hours


def cleanup_stale_sessions() -> int:
    """Remove sessions older than _SESSION_TTL_SECONDS. Called by the stuck-job reaper.
    Returns count of cleaned up sessions.
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


# ── LLM helper ────────────────────────────────────────────────────────────────

def _call_llm(prompt: str, model: str) -> dict:
    """
    Call llm.complete() from a synchronous tool context.

    Tools run inside asyncio.to_thread() — a fresh OS thread with no event loop.
    asyncio.run() is legal and correct here: it creates a new loop, runs the
    coroutine to completion, and destroys the loop. All LLM calls route through
    llm.py (token counting, provider routing all work identically).
    """
    from llm import complete
    return asyncio.run(complete(prompt, model))


def _budget_ok(state: ResumeState, session_key: str) -> tuple:
    """Return (True, '') if budget available, (False, message) if exceeded."""
    total = state.total_tokens()
    if total >= AGENT_TOKEN_BUDGET:
        return False, (
            f"Token budget reached ({total:,}/{AGENT_TOKEN_BUDGET:,}). "
            f"Optimization complete — remaining sections unchanged."
        )
    return True, ""


# ── Tool 1: Keyword injection (fixes low ATS score) ──────────────────────────

@tool("Inject missing ATS keywords into resume sections")
def keyword_inject_tool(
    session_key: str,
    missing_keywords_csv: str,
    target_sections_csv: str = "experience,summary",
) -> str:
    """
    Surgically inject missing ATS keywords into the target sections.
    Call this when the ATS score is below 75.

    Args:
        session_key: The optimization session identifier (given in the task description).
        missing_keywords_csv: Comma-separated keywords from the ATS score's missing_keywords.
        target_sections_csv: Comma-separated sections to inject into.
            Valid: summary, experience, education, skills, certifications, projects.
            Default: experience,summary

    Returns:
        Short status string. Resume state is updated automatically.
    """
    state = get_session(session_key)
    if state is None:
        return f"Error: session '{session_key}' not found."

    ok, msg = _budget_ok(state, session_key)
    if not ok:
        return msg

    keywords = [k.strip() for k in missing_keywords_csv.split(",") if k.strip()]
    target_sections = [s.strip() for s in target_sections_csv.split(",") if s.strip()]
    updated: list = []

    for section_name in target_sections:
        section_text = state.get_section(section_name)
        if not section_text.strip():
            continue

        ok, msg = _budget_ok(state, session_key)
        if not ok:
            return msg + f" Partially updated: {updated}."

        prompt = f"""Inject these missing keywords into the resume section below.
Integrate them naturally into existing sentences and bullets.
Do NOT keyword-stuff. Do NOT add new bullet points solely for keywords.
Do NOT change any metrics, dates, company names, or facts.

Keywords to inject: {', '.join(keywords)}

Section:
\"\"\"
{section_text}
\"\"\"

Return ONLY the updated section text."""

        result = _call_llm(prompt, MODEL_KEYWORD_INJECT)
        state.add_tokens(result.get("input_tokens", 0), result.get("output_tokens", 0))
        if result.get("text"):
            state.update_section(section_name, result["text"])
            updated.append(section_name)

    if updated:
        return f"Keywords ({missing_keywords_csv}) injected into: {', '.join(updated)}."
    available = state.available_sections()
    return f"No target sections found ({target_sections_csv}). Available: {', '.join(available)}."


# ── Tool 2: Bullet strengthener (fixes low Impact score) ─────────────────────

@tool("Strengthen weak impact bullets in the experience section")
def bullet_strengthen_tool(
    session_key: str,
    weak_bullets_csv: str,
) -> str:
    """
    Rewrite only the identified weak impact bullets with stronger action verbs.
    Call this when the Impact score is below 75.

    Args:
        session_key: The optimization session identifier (given in the task description).
        weak_bullets_csv: The weak bullet texts verbatim from the Impact score's weak_bullets.

    Returns:
        Short status string. Resume state is updated automatically.
    """
    state = get_session(session_key)
    if state is None:
        return f"Error: session '{session_key}' not found."

    ok, msg = _budget_ok(state, session_key)
    if not ok:
        return msg

    experience_text = state.get_section("experience")
    if not experience_text.strip():
        available = state.available_sections()
        return f"No experience section in state. Available: {', '.join(available)}. Try keyword_inject_tool on summary instead."

    weak = [b.strip() for b in weak_bullets_csv.split(",") if b.strip()]
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
- Plain text only — no markdown

Experience section:
\"\"\"
{experience_text}
\"\"\"

Return ONLY the complete updated experience section text."""

    result = _call_llm(prompt, MODEL_BULLET_STRENGTHEN)
    state.add_tokens(result.get("input_tokens", 0), result.get("output_tokens", 0))
    if result.get("text"):
        state.update_section("experience", result["text"])
        return f"Strengthened {len(weak)} bullet(s) in the experience section."
    return "Bullet strengthening returned empty output — section unchanged."


# ── Tool 3: Skills section rewriter (fixes low Skills Gap score) ──────────────

@tool("Rewrite the skills section to address the skills gap")
def skills_rewrite_tool(
    session_key: str,
    missing_skills_csv: str,
) -> str:
    """
    Rewrite only the skills section to incorporate missing required skills.
    Call this when the Skills Gap score is below 75.

    Args:
        session_key: The optimization session identifier (given in the task description).
        missing_skills_csv: Comma-separated skills from the Skills Gap score's missing_skills.

    Returns:
        Short status string. Resume state is updated automatically.
    """
    state = get_session(session_key)
    if state is None:
        return f"Error: session '{session_key}' not found."

    ok, msg = _budget_ok(state, session_key)
    if not ok:
        return msg

    skills_text = state.get_section("skills")
    if not skills_text.strip():
        return (
            "No skills section found. Call keyword_inject_tool with "
            f"target_sections_csv='experience' and missing_keywords_csv='{missing_skills_csv}'."
        )

    missing = [s.strip() for s in missing_skills_csv.split(",") if s.strip()]

    prompt = f"""Rewrite the Skills section below to include the missing skills.
Integrate naturally — group with related existing skills if grouped.
Do NOT invent certifications or proficiency claims.
Plain text only.

Missing skills to add: {', '.join(missing)}

Skills section:
\"\"\"
{skills_text}
\"\"\"

Return ONLY the complete updated skills section text."""

    result = _call_llm(prompt, MODEL_SKILLS_REWRITE)
    state.add_tokens(result.get("input_tokens", 0), result.get("output_tokens", 0))
    if result.get("text"):
        state.update_section("skills", result["text"])
        return f"Skills section updated to include: {missing_skills_csv}."
    return "Skills rewrite returned empty output — section unchanged."


# ── Tool 4: Section humanizer (fixes low Readability score) ──────────────────

@tool("Polish language and readability in a specific resume section")
def section_humanize_tool(
    session_key: str,
    section_name: str,
    issues_csv: str = "",
) -> str:
    """
    Polish language and readability of one resume section.
    Call this when the Readability score is below 75.

    Args:
        session_key: The optimization session identifier (given in the task description).
        section_name: Section to polish: summary, experience, skills, or education.
        issues_csv: Comma-separated issues from the Readability score's issues field.
            Leave empty for general polish.

    Returns:
        Short status string. Resume state is updated automatically.
    """
    state = get_session(session_key)
    if state is None:
        return f"Error: session '{session_key}' not found."

    ok, msg = _budget_ok(state, session_key)
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
- Plain text only — no markdown

{section_name.title()} section:
\"\"\"
{section_text}
\"\"\"

Return ONLY the complete updated {section_name} section text."""

    result = _call_llm(prompt, MODEL_SECTION_HUMANIZE)
    state.add_tokens(result.get("input_tokens", 0), result.get("output_tokens", 0))
    if result.get("text"):
        state.update_section(section_name, result["text"])
        return f"'{section_name}' polished. Issues addressed: {issues_csv or 'general polish'}."
    return f"Humanization of '{section_name}' returned empty output — section unchanged."


# ── Agent factory ─────────────────────────────────────────────────────────────

def create_optimizer_agent() -> Agent:
    """
    Build the Optimization Strategist agent.

    The agent reads the task description (score breakdown + session_key),
    decides which tools to call, and passes the session_key to each tool.
    It never sees or handles resume text directly.
    """
    return Agent(
        role="Resume Optimization Strategist",
        goal=(
            f"Raise each score dimension above {SCORE_TARGET} by calling targeted tools "
            f"on underperforming sections only. Skip any dimension not marked NEEDS WORK."
        ),
        backstory=(
            "You are a senior resume strategist who applies precise, surgical fixes. "
            "You never rewrite the whole resume when one section needs work. "
            "You always pass the session_key to tools exactly as written in the task."
        ),
        tools=[
            keyword_inject_tool,
            bullet_strengthen_tool,
            skills_rewrite_tool,
            section_humanize_tool,
        ],
        llm=MODEL_OPTIMIZER,
        max_iter=AGENT_MAX_ITER,
        verbose=True,
    )

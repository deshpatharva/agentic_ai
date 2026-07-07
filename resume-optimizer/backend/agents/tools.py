"""
Async tool functions for the native-agent optimizer (Phase 2, PR-2).

DESIGN
======
This module is a standalone replacement for the CrewAI @tool-decorated
functions in _archive/optimizer_agent.py. Key differences:

  - All tool functions are plain ``async def`` — no @tool decorator, no
    asyncio.run(). The A+C driver awaits them directly.
  - Tool signatures accept ``state: ResumeState`` directly instead of a
    ``session_key`` string. The driver resolves the session and passes state in.
  - ResumeState and _budget_ok are defined here so other PR-2 modules
    (e.g. orchestration/optimizer.py) can import them without pulling in
    CrewAI dependencies from _archive/optimizer_agent.py.

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

import re
import threading
from typing import Dict

from config import (
    AGENT_TOKEN_BUDGET,
    DEBATE_TOKEN_BUDGET,
    MODEL_BULLET_STRENGTHEN,
    MODEL_CRITIQUE,
    MODEL_KEYWORD_INJECT,
    MODEL_SKILLS_REWRITE,
)
from llm import complete
from observability.trace import current_call_kind
from utils.section_parser import reassemble as _reassemble_sections


# ── Shared session state ──────────────────────────────────────────────────────


class ResumeState:
    """
    Thread-safe container for resume sections and token accounting.

    One instance is created per optimisation job and passed directly to the
    agent loop. Tools mutate sections in-place. Token totals are the
    authoritative budget counter.
    """

    def __init__(self, sections: Dict[str, str], available_metrics: str = "",
                 capabilities: frozenset = frozenset()) -> None:
        self._sections: Dict[str, str] = dict(sections)
        self.available_metrics: str = available_metrics
        self.capabilities: frozenset = frozenset(t.lower() for t in capabilities)
        self._gaps: set = set()
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

    # -- Honest gaps -----------------------------------------------------------

    def add_gaps(self, items) -> None:
        """Record JD asks that cannot be truthfully added (no evidence)."""
        with self._lock:
            self._gaps.update(i.strip() for i in items if i and i.strip())

    def honest_gaps(self) -> list:
        with self._lock:
            return sorted(self._gaps)

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
        """Return the full resume text in canonical section order.

        Delegates to utils.section_parser.reassemble so the assembled draft stays
        byte-identical to the before/after diff the optimization report renders.
        """
        with self._lock:
            return _reassemble_sections(dict(self._sections))


# ── Budget helper ─────────────────────────────────────────────────────────────


def _budget_ok(state: ResumeState) -> tuple:
    """Return (True, '') if budget available, (False, message) if exceeded.

    Picks the budget based on the active call kind so debate gets its larger
    cap (40K) instead of the single-agent cap (20K).
    """
    budget = DEBATE_TOKEN_BUDGET if current_call_kind() == "pro_debate" else AGENT_TOKEN_BUDGET
    total = state.total_tokens()
    if total >= budget:
        return False, (
            f"Token budget reached ({total:,}/{budget:,}). "
            f"Optimization complete — remaining sections unchanged."
        )
    return True, ""


# -- Evidence filtering ---------------------------------------------------------

_SENIORITY_STOPWORDS = frozenset({
    "senior", "junior", "lead", "principal", "staff", "expert", "seasoned",
    "entry-level", "mid-level", "experienced",
})

# Role/credential nouns marking a compound claim (job title, certification)
# riding on a matched capability substring -- e.g. "Senior Backend Engineer"
# must not be promoted to evidenced just because "backend" matches; the title
# claim itself is not evidenced. Checked as whole words anywhere in the item,
# not just full-string equality (unlike a bare "Senior").
_COMPOUND_CLAIM_MARKERS = frozenset({
    "engineer", "developer", "architect", "manager", "director",
    "administrator", "specialist", "consultant", "analyst", "scientist",
    "certified", "certification", "certificate", "accredited", "licensed",
})

_WORD_RE = re.compile(r"[a-z]+")


def _contains_drop_marker(n: str) -> bool:
    return any(w in _COMPOUND_CLAIM_MARKERS for w in _WORD_RE.findall(n))


def _is_pure_marker_phrase(n: str) -> bool:
    """True if n carries no substantive content of its own -- either the whole
    (possibly hyphenated) string is a seniority stopword, or every word in it
    is a seniority/marker word. Such phrases are never evidenced, even on an
    exact capability match, since a bare marker word reaching `capabilities`
    is most likely resume-parsing noise, not an intentional self-description."""
    if n in _SENIORITY_STOPWORDS:
        return True
    words = _WORD_RE.findall(n)
    return bool(words) and all(w in _SENIORITY_STOPWORDS or w in _COMPOUND_CLAIM_MARKERS
                               for w in words)


def _norm_term(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", s.lower())          # strip parentheticals
    return re.sub(r"\s+", " ", s).strip(" .")


def split_evidenced(items, capabilities) -> tuple:
    """Partition JD asks into (evidenced, gaps) against the capabilities allowlist.

    Seniority/role/credential-only phrases are never evidenced -- dropped from
    BOTH lists, not a closable gap either (spec 2b). A multi-word phrase that
    contains marker words alongside substantive content (e.g. "Senior Python
    Developer") IS evidenced when it exact-matches a capability captured
    verbatim from the resume, since citing it back is not a new claim.
    """
    evidenced, gaps = [], []
    for item in items:
        n = _norm_term(item)
        if not n or _is_pure_marker_phrase(n):
            continue
        if n in capabilities:
            evidenced.append(item)
            continue
        if _contains_drop_marker(n):
            continue
        hit = any(
            re.search(r"(?<![\w+#])" + re.escape(c) + r"(?![\w+#])", n)
            for c in capabilities
        )
        (evidenced if hit else gaps).append(item)
    return evidenced, gaps


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
        return "No keywords provided -- nothing to inject."
    evidenced, gaps = split_evidenced(keywords, state.capabilities)
    if gaps:
        state.add_gaps(gaps)
    if not evidenced:
        return (f"All requested items lack evidence -- recorded as honest gaps: "
                f"{', '.join(gaps)}.")
    target_sections = [s.strip() for s in target_sections_csv.split(",") if s.strip()]
    updated: list = []
    used_note = ""

    for section_name in target_sections:
        section_text = state.get_section(section_name)
        if not section_text.strip():
            continue

        ok, msg = _budget_ok(state)
        if not ok:
            if updated:
                return msg + f" Partially updated: {', '.join(updated)}."
            return msg

        prompt = f"""Weave these keywords into the resume section below. Every keyword listed is already
evidenced by the candidate's own material -- your job is presentation, not addition.

RULES -- strictly follow all of them:
- Weave keywords into EXISTING sentences/bullets only. Do NOT add new sentences,
  clauses, or bullets.
- Rephrase what the candidate already does so it uses the keyword. Do NOT claim new
  duties, projects, tools, or role scope to host a keyword.
- Do NOT change any metrics, dates, company names, job titles, or seniority wording.
  NEVER insert placeholder metrics ("[XX%]").
- Do NOT copy job-description phrases verbatim, and do NOT repeat the same phrase across
  bullets -- vary the wording so it reads naturally.
- If a keyword cannot be woven without inventing a new claim, skip it.
- Plain text only -- no markdown bold, no LaTeX or "$" math wrappers.
{used_note}
Keywords to weave in: {', '.join(evidenced)}

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
            used_note = (f"\nAlready used in another section: {', '.join(evidenced)} "
                         f"-- do not repeat them here.")

    skipped_note = (f" Skipped (no evidence -- recorded as gaps): {', '.join(gaps)}."
                    if gaps else "")
    if updated:
        return (f"Injected (evidenced): {', '.join(evidenced)} into: "
                f"{', '.join(updated)}.{skipped_note}")
    available = state.available_sections()
    return (f"No target sections found ({target_sections_csv}). "
            f"Available: {', '.join(available)}.{skipped_note}")


# ── Tool 2: Bullet strengthener (fixes low Impact score) ─────────────────────


async def bullet_strengthen(
    state: ResumeState,
    weak_bullets_csv: str,
) -> str:
    """
    Rewrite only the identified weak impact bullets with stronger action verbs.

    Args:
        state: The ResumeState for this optimisation session.
        weak_bullets_csv: Pipe-separated (|) weak bullet texts verbatim from the Impact score.
            Pipe delimiter is used because bullets frequently contain commas.

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

    # Accept either pipe-separated (preferred) or comma-separated input.
    delimiter = "|" if "|" in weak_bullets_csv else ","
    weak = [b.strip() for b in weak_bullets_csv.split(delimiter) if b.strip()]
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
- If a listed bullet does NOT appear in the section, skip it — do NOT guess which bullet was intended
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

    missing = [s.strip() for s in missing_skills_csv.split(",") if s.strip()]
    if not missing:
        return "No missing skills provided -- nothing to add."
    evidenced, gaps = split_evidenced(missing, state.capabilities)
    if gaps:
        state.add_gaps(gaps)
    if not evidenced:
        return (f"All requested items lack evidence -- recorded as honest gaps: "
                f"{', '.join(gaps)}.")

    skills_text = state.get_section("skills")
    if not skills_text.strip():
        return (
            "No skills section found. Call keyword_inject with "
            f"target_sections_csv='experience' and missing_keywords_csv='{', '.join(evidenced)}'."
        )

    prompt = f"""Rewrite the Skills section so it accurately reflects the candidate's evidenced skills.

You may ONLY add skills from this list -- each one already appears in the candidate's own
resume (experience, summary, or projects): {', '.join(evidenced)}

- Group added skills with related existing ones if the section is grouped.
- Keep every existing skill; deduplicate exact repeats.
- Do NOT add anything outside the list. Do NOT invent certifications or proficiency
  levels. STRIP parenthetical examples ("Data migration tools", not "(e.g., SnowConvert)").
- Plain text only -- no LaTeX or "$" math.

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
    skipped_note = (f" Skipped (no evidence -- recorded as gaps): {', '.join(gaps)}."
                    if gaps else "")
    if result.get("text"):
        state.update_section("skills", result["text"])
        return f"Skills section updated to include: {', '.join(evidenced)}.{skipped_note}"
    return "Skills rewrite returned empty output -- section unchanged."


# ── Tool 4: Bullet reorder (fixes low JD Tailoring score) ────────────────────


async def bullets_reorder(
    state: ResumeState,
    section_name: str,
    jd_focus_csv: str,
) -> str:
    """
    Reorder bullets in a section by JD relevance (most relevant first).

    Args:
        state: The ResumeState for this optimisation session.
        section_name: Section to reorder: experience, summary, or skills.
        jd_focus_csv: Comma-separated JD keywords to prioritize when reordering.

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
            f"Section '{section_name}' not found or empty. "
            f"Available sections: {', '.join(available)}. "
            f"Retry with one of those names."
        )

    prompt = f"""Reorder the bullets in the {section_name} section below so that the bullets most
relevant to the JD focus keywords appear first.

JD focus keywords: {jd_focus_csv}

Rules:
- ONLY reorder existing bullets — do NOT add, remove, or modify any bullet text
- Keep all bullet text exactly as written (no paraphrasing, no edits)
- Move the most JD-relevant bullets to the top; least relevant to the bottom
- If no bullets are present (e.g. a prose paragraph), return the section unchanged
- Plain text only — no markdown, no LaTeX, no formatting changes

{section_name.title()} section:
\"\"\"
{section_text}
\"\"\"

Return ONLY the complete {section_name} section text with bullets reordered."""

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
        state.update_section(section_name, result["text"])
        return f"Reordered bullets in '{section_name}' by JD relevance."
    return f"Bullet reorder of '{section_name}' returned empty output — section unchanged."


# ── Tool 5: Resume critique (qualitative feedback on the whole draft) ────────


async def critique_resume(
    state: ResumeState,
    focus_areas_csv: str = "",
) -> str:
    """
    Run a critic over the full resume draft and return structured feedback.

    The strategist can call this at any point to get qualitative feedback
    on what still reads weak, robotic, or generic — then decide which
    fix tools to call based on the critique.

    Args:
        state: The ResumeState for this optimisation session.
        focus_areas_csv: Optional comma-separated areas to focus critique on
            (e.g. "robotic language,weak bullets,keyword stuffing"). Empty
            means critique everything.

    Returns:
        Structured feedback string the strategist can act on.
    """
    ok, msg = _budget_ok(state)
    if not ok:
        return msg

    draft = state.reassemble()
    if not draft.strip():
        return "Resume draft is empty — nothing to critique."

    focus_note = (
        f"Focus your critique on: {focus_areas_csv}"
        if focus_areas_csv.strip()
        else "Critique on dimensions the optimizer can act on: weak bullets, missing keywords, missing skills, bullet ordering."
    )

    prompt = f"""You are a senior hiring manager reviewing a resume. Be specific and actionable.

{focus_note}

For each issue you find, quote the exact phrase from the resume that needs fixing.

The optimizer has tools that can only fix these dimensions — only return issues that map to one:
- "weak_bullets" → fixed by bullet_strengthen
- "missing_keywords" → fixed by keyword_inject
- "missing_skills" → fixed by skills_rewrite
- "ordering_issues" → fixed by bullets_reorder

Do NOT raise issues about tone, robotic language, or wording — a separate humanize stage handles those.

Return ONLY a JSON object with these keys (omit any key with an empty list):
- "weak_bullets": list of bullet texts that lack impact or measurable outcomes
- "missing_keywords": list of JD keywords the resume should include but doesn't
- "missing_skills": list of required skills missing from the skills section
- "ordering_issues": list of sections where the most JD-relevant bullets are not first

Resume:
\"\"\"
{draft}
\"\"\"

JSON:"""

    try:
        result = await complete(prompt, MODEL_CRITIQUE, response_format={"type": "json_object"})
    except Exception as exc:
        return f"Critique LLM call failed: {exc}"

    state.add_tokens(
        result.get("input_tokens", 0),
        result.get("output_tokens", 0),
        result.get("cost_usd", 0.0),
    )

    import json
    raw = result.get("text", "").strip()
    try:
        feedback = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return f"Critique returned non-JSON: {raw[:300]}"

    parts = []
    for key in ("weak_bullets", "missing_keywords", "missing_skills", "ordering_issues"):
        items = feedback.get(key, [])
        if items:
            label = key.replace("_", " ").title()
            parts.append(f"{label}: {'; '.join(str(i) for i in items[:5])}")

    if not parts:
        return "Critique found no issues — resume reads well."

    return " | ".join(parts)

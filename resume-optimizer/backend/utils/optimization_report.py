"""Build a structured, grounded optimization report at pipeline completion.

The report is stored on the chat session so the co-pilot can answer "what did you
change?" / "what gaps were filled?" from FACTS instead of guessing — and so those
follow-up questions never fail. Everything here is deterministic (diff + the
existing gap computation), no LLM calls.
"""

from __future__ import annotations

from chat.gaps import compute_gaps
from utils.section_parser import detect_sections


def merge_honest_gaps(agent_gaps: list, capability_gaps: list) -> list:
    """Merge agent- and guard-reported honest gaps, case-insensitively.

    agent_gaps preserve original JD casing (e.g. "Kubernetes"); capability_gaps
    are lowercased taxonomy terms from fabrication_guard (e.g. "kubernetes").
    A plain set union of the two would report the same gap twice under
    different casing -- dedup on the lowercase key instead, preferring the
    agent's original casing when both forms are present.
    """
    merged: dict[str, str] = {}
    for g in agent_gaps or []:
        if g:
            merged.setdefault(g.lower(), g)
    for g in capability_gaps or []:
        if g:
            merged.setdefault(g.lower(), g)
    return sorted(merged.values())


def build_report(
    jd_result: dict,
    original_text: str,
    optimized_text: str,
    baseline_score: float,
    final_scores: dict,
    iterations: int,
    honest_gaps: list | None = None,
) -> dict:
    """Compute what the optimization changed and which JD gaps it addressed.

    - gaps_identified: JD-required skills missing from the ORIGINAL resume.
    - gaps_addressed:  identified gaps that now appear in the OPTIMIZED resume.
    - gaps_remaining:  still missing after optimization (honest — don't overclaim).
    - gaps_for_jd:     the real gaps we couldn't truthfully close (accumulated by
                       tools/guard/rewriter across the run) -- honest, not optimistic.
    """
    identified = compute_gaps(jd_result, [], original_text or "", limit=12)
    remaining = compute_gaps(jd_result, [], optimized_text or "", limit=12)
    remaining_lower = {g.lower() for g in remaining}
    addressed = [g for g in identified if g.lower() not in remaining_lower]

    def _pick(dim: str, key: str, n: int = 5) -> list:
        d = final_scores.get(dim) or {}
        return (d.get(key) or [])[:n] if isinstance(d, dict) else []

    def _pick_str(dim: str, key: str) -> str:
        d = final_scores.get(dim) or {}
        return str(d.get(key) or "") if isinstance(d, dict) else ""

    # Build per-section before/after diff (capped at 800 chars each)
    _CAP = 800
    orig_sections = detect_sections(original_text or "")
    opt_sections = detect_sections(optimized_text or "")
    all_section_names = set(orig_sections) | set(opt_sections)
    section_diff: dict = {}
    for sec in all_section_names:
        before = orig_sections.get(sec, "")
        after = opt_sections.get(sec, "")
        if before.strip() == after.strip():
            continue  # skip identical sections
        section_diff[sec] = {
            "before": before[:_CAP],
            "after": after[:_CAP],
        }

    return {
        "baseline_score": round(float(baseline_score)),
        "final_score": round(float(final_scores.get("average", baseline_score))),
        "scores": {
            k: (final_scores[k]["score"] if isinstance(final_scores.get(k), dict)
                else final_scores.get(k, 0))
            for k in ("ats", "impact", "skills_gap", "readability", "jd_tailoring")
        },
        "gaps_identified": identified,
        "gaps_addressed": addressed,
        "gaps_remaining": remaining,
        "gaps_for_jd": list(honest_gaps or []),
        "iterations": int(iterations),
        # Per-dimension detail so the co-pilot can ask targeted improvement questions.
        # Capped at 5 items each to keep the context window lean.
        "dimension_detail": {
            "ats":         {"missing_keywords": _pick("ats",         "missing_keywords")},
            "impact":      {"weak_bullets":     _pick("impact",      "weak_bullets")},
            "skills_gap":  {"missing_skills":   _pick("skills_gap",  "missing_skills"),
                            "critical_missing": _pick("skills_gap",  "critical_missing")},
            "readability": {"issues":           _pick("readability", "issues"),
                            "worst_section":    _pick_str("readability", "worst_section")},
            "jd_tailoring": {"issues": _pick("jd_tailoring", "issues")},
        },
        "section_diff": section_diff,
    }

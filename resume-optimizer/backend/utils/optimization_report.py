"""Build a structured, grounded optimization report at pipeline completion.

The report is stored on the chat session so the co-pilot can answer "what did you
change?" / "what gaps were filled?" from FACTS instead of guessing — and so those
follow-up questions never fail. Everything here is deterministic (diff + the
existing gap computation), no LLM calls.
"""

from __future__ import annotations

from chat.gaps import compute_gaps


def build_report(
    jd_result: dict,
    original_text: str,
    optimized_text: str,
    baseline_score: float,
    final_scores: dict,
    iterations: int,
) -> dict:
    """Compute what the optimization changed and which JD gaps it addressed.

    - gaps_identified: JD-required skills missing from the ORIGINAL resume.
    - gaps_addressed:  identified gaps that now appear in the OPTIMIZED resume.
    - gaps_remaining:  still missing after optimization (honest — don't overclaim).
    """
    identified = compute_gaps(jd_result, [], original_text or "", limit=12)
    remaining = compute_gaps(jd_result, [], optimized_text or "", limit=12)
    remaining_lower = {g.lower() for g in remaining}
    addressed = [g for g in identified if g.lower() not in remaining_lower]

    return {
        "baseline_score": round(float(baseline_score)),
        "final_score": round(float(final_scores.get("average", baseline_score))),
        "scores": {
            k: (final_scores[k]["score"] if isinstance(final_scores.get(k), dict)
                else final_scores.get(k, 0))
            for k in ("ats", "impact", "skills_gap", "readability")
        },
        "gaps_identified": identified,
        "gaps_addressed": addressed,
        "gaps_remaining": remaining,
        "iterations": int(iterations),
    }

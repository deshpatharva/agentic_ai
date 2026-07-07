"""Prompt-builder contracts for the truthful optimizer (spec sections 2a/2b)."""

from agents.fact_extractor import ClaimsLedger

LEDGER = ClaimsLedger(
    companies=frozenset({"Acme"}), metrics=frozenset({"40%"}),
    raw_bullets=("Did things",), capabilities=frozenset({"python", "aws"}),
)

SCORES = {
    "ats":          {"score": 58, "missing_keywords": ["Python", "Kubernetes", "Senior"]},
    "impact":       {"score": 91, "weak_bullets": []},
    "skills_gap":   {"score": 40, "missing_skills": ["AWS", "Terraform"]},
    "readability":  {"score": 70},
    "jd_tailoring": {"score": 95, "issues": []},
    "overall": 60,
}


def test_system_prompt_states_truthful_objective():
    from orchestration.agent_loop import _build_system_stable

    text = _build_system_stable(["summary", "experience"], LEDGER)
    assert "VERIFIED" in text
    assert "Verified capabilities:" in text          # ledger block embedded
    assert "honest gaps" in text.lower()
    assert "above 90" not in text                    # old score-chasing objective gone
    assert "NEEDS WORK" not in text                  # moved to scores context semantics


def test_system_prompt_keeps_user_instruction_block():
    from orchestration.agent_loop import _build_system_stable

    text = _build_system_stable(["summary"], LEDGER, user_instruction="fix the summary")
    assert "PRIORITY USER FEEDBACK" in text and "fix the summary" in text


def test_scores_context_splits_evidence_and_caps():
    from orchestration.agent_loop import _build_scores_context, _dimension_work

    ctx = _build_scores_context(SCORES, LEDGER.capabilities)
    assert ctx.startswith("CURRENT SCORES (baseline):")
    assert "addable keywords (evidenced): Python" in ctx
    assert "Kubernetes" in ctx.split("gaps (no evidence", 1)[1]  # listed as gap
    assert "Senior" not in ctx                                    # seniority word dropped
    assert "off-limits" in ctx

    work = _dimension_work(SCORES, LEDGER.capabilities)
    assert work["ats"]["actionable"] is True
    assert work["skills_gap"]["addable"] == ["AWS"]
    assert work["skills_gap"]["gaps"] == ["Terraform"]
    assert work["impact"]["actionable"] is False      # no weak bullets left


def test_scores_context_capped_flag():
    from orchestration.agent_loop import _build_scores_context

    scores = {"ats": {"score": 50, "missing_keywords": ["Kubernetes"]},
              "impact": {"score": 95, "weak_bullets": []},
              "skills_gap": {"score": 95, "missing_skills": []},
              "jd_tailoring": {"score": 95, "issues": []}}
    ctx = _build_scores_context(scores, frozenset({"python"}))
    assert "capped (honest ceiling)" in ctx


def test_scores_context_custom_heading():
    from orchestration.agent_loop import _build_scores_context

    ctx = _build_scores_context(SCORES, LEDGER.capabilities,
                                heading="UPDATED SCORES (reflection 2)")
    assert ctx.startswith("UPDATED SCORES (reflection 2):")


async def test_rewriter_filters_keywords_and_reports_gaps(monkeypatch):
    import agents.rewriter as rewriter
    from agents.fact_extractor import ClaimsLedger

    captured = {}

    async def fake_complete(prompt, model, **kw):
        captured["prompt"] = prompt
        return {"text": "rewritten", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    monkeypatch.setattr(rewriter, "complete", fake_complete)
    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    result = await rewriter.rewrite_resume(
        resume_text="I use Python.", jd_keywords=["Python", "Kubernetes"],
        claims_ledger=ledger,
    )
    assert "TRUTHFUL KEYWORD ALIGNMENT" in captured["prompt"]
    assert "KEYWORD SATURATION" not in captured["prompt"]
    assert "Kubernetes" not in captured["prompt"]
    assert result["gaps"] == ["Kubernetes"]

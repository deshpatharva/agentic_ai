"""Scorer + JD analyzer prompt hygiene (spec 5d) -- standalone file, no
interface dependency on the capabilities/ledger track (Tasks 1-9,12)."""


async def test_scorer_prompt_bans_seniority_keywords(monkeypatch):
    import agents.scorer as scorer

    captured = {}

    async def fake_complete(prompt, model, **kw):
        captured["prompt"] = prompt
        captured["cached_prefix"] = kw.get("cached_prefix", "")
        return {"text": "{}", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    monkeypatch.setattr(scorer, "complete", fake_complete)
    from utils import cache as result_cache
    result_cache.clear()
    await scorer.score_combined("resume text unique-a", "jd text unique-a")
    combined = (captured.get("cached_prefix") or "") + captured["prompt"]
    assert "never seniority words" in combined


async def test_jd_analyzer_prompt_demands_short_skill_terms(monkeypatch):
    import agents.jd_analyzer as jd

    captured = {}

    async def fake_complete(prompt, model, **kw):
        captured["prompt"] = prompt
        return {"text": '{"job_title": "x"}', "input_tokens": 1, "output_tokens": 1,
                "cost_usd": 0.0}

    monkeypatch.setattr(jd, "complete", fake_complete)
    from utils import cache as result_cache
    result_cache.clear()
    await jd.analyze_jd("jd text unique-b")
    assert "1-3 word technologies or competencies" in captured["prompt"]

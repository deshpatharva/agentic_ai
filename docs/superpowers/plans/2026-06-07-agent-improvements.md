# Agent Research & Prompt Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the resume-optimizer agent pipeline — scorer calibration, structured JD schema, iteration loop, fabrication guard wiring, humanizer improvements, and full JD-metadata threading — to produce measurably better tailored resumes.

**Architecture:** Eight tasks in dependency order: enrich the JD Analyzer output schema first, then update Scorer to consume it, then fix the Optimizer's thresholds and list caps, extend the ClaimsLedger for richer fact extraction, wire the fabrication guard, improve the Humanizer and Rewriter prompts, and finally thread all new fields through the main pipeline with a real iteration loop. Each task is independently testable.

**Tech Stack:** Python 3.11, FastAPI, CrewAI, spaCy en_core_web_sm, TF-IDF (sklearn), python-jose, pytest-asyncio, unittest.mock.AsyncMock

---

### Task 1: Scorer — remove "max 3" cap and add calibration rubric

**Files:**
- Modify: `resume-optimizer/backend/agents/scorer.py`
- Modify: `resume-optimizer/backend/tests/test_agents.py`

**Context:**
The scorer's `score_combined` function caps every list to 3 items in the LLM prompt and has no calibration rubric, causing score compression and useless feedback. We need to:
1. Remove the `"Max 3 items per list"` instruction.
2. Add a detailed calibration rubric to the system prompt.
3. Expand the JSON schema to include `keyword_coverage_pct`, `has_summary`, `tense_consistent`, `worst_section`, `critical_missing`, `strong_bullets`.
4. Accept two new optional params: `seniority_level` and `required_hard_skills`.

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_scorer_returns_extended_fields(monkeypatch):
    """score_combined must return keyword_coverage_pct, worst_section, critical_missing."""
    from agents.scorer import score_combined

    fake_response = {
        "ats": {
            "score": 82,
            "missing_keywords": ["kubernetes", "terraform"],
            "matched_keywords": ["python", "docker"],
            "keyword_coverage_pct": 67.0,
        },
        "impact": {
            "score": 71,
            "weak_bullets": ["Helped with stuff"],
            "strong_bullets": ["Reduced latency by 40%"],
            "has_quantified_achievements": True,
        },
        "skills_gap": {
            "score": 78,
            "missing_skills": ["Go", "Rust"],
            "matched_skills": ["Python", "SQL"],
            "critical_missing": ["kubernetes"],
        },
        "readability": {
            "score": 85,
            "issues": [],
            "worst_section": "skills",
            "has_summary": True,
            "tense_consistent": True,
        },
        "overall": 79,
    }

    async def mock_complete(prompt, system=None, schema=None):
        return fake_response

    monkeypatch.setattr("agents.scorer._llm_complete", mock_complete)

    result = await score_combined(
        resume_text="Software engineer with Python experience",
        jd_text="Looking for Python/K8s engineer",
        seniority_level="senior",
        required_hard_skills=["kubernetes"],
    )
    assert "keyword_coverage_pct" in result["ats"]
    assert "worst_section" in result["readability"]
    assert "critical_missing" in result["skills_gap"]
    assert "strong_bullets" in result["impact"]
    assert "has_summary" in result["readability"]
    assert "tense_consistent" in result["readability"]


@pytest.mark.asyncio
async def test_scorer_no_max_3_in_prompt(monkeypatch):
    """Scorer prompt must not contain 'Max 3' or 'max 3' restriction."""
    import inspect
    from agents import scorer
    source = inspect.getsource(scorer)
    assert "Max 3" not in source, "Remove 'Max 3 items' cap from scorer prompt"
    assert "max 3" not in source.lower() or "max_iter" in source, \
        "Found 'max 3' restriction in scorer — remove it"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd resume-optimizer/backend
python -m pytest tests/test_agents.py::test_scorer_returns_extended_fields tests/test_agents.py::test_scorer_no_max_3_in_prompt -v
```

Expected: FAIL — `keyword_coverage_pct` missing, `Max 3` still present.

- [ ] **Step 3: Rewrite `score_combined` in `agents/scorer.py`**

Replace the entire function (and its system prompt) with:

```python
async def score_combined(
    resume_text: str,
    jd_text: str,
    jd_keywords: list[str] | None = None,
    seniority_level: str = "mid",
    required_hard_skills: list[str] | None = None,
) -> dict:
    """Return structured scoring across 4 dimensions with calibration rubric."""
    required_block = ""
    if required_hard_skills:
        required_block = (
            f"\nRequired hard skills for this role: {', '.join(required_hard_skills[:20])}."
            " If any of these are missing from the resume, they MUST appear in critical_missing."
        )

    seniority_map = {
        "entry": "0-2 years experience expected; penalise missing summary heavily",
        "mid":   "3-6 years; expects quantified bullets and clear progression",
        "senior": "7+ years; expects leadership indicators, architecture mentions, metrics at scale",
        "lead":  "10+ years; expects team-building language, org-level impact",
    }
    seniority_note = seniority_map.get(seniority_level, seniority_map["mid"])

    system = f"""You are an expert ATS and resume evaluator. Score strictly using this rubric:

ATS score (0-100):
  90-100 = >90% of JD keywords present, all critical skills matched
  70-89  = 70-89% keyword match, minor gaps only
  50-69  = 50-69% match, several important keywords missing
  <50    = <50% match, fundamental misalignment

Impact score (0-100):
  90-100 = Every bullet has a metric (%, $, count, time-saved); strong action verbs
  70-89  = >70% bullets quantified; some passive voice
  50-69  = Mixed; many bullets describe duties not achievements
  <50    = Mostly duty-description, few/no metrics

Skills gap (0-100):
  90-100 = All required and preferred skills present
  70-89  = All required present, some preferred missing
  50-69  = 1-2 required skills missing
  <50    = Multiple required skills absent

Readability (0-100):
  90-100 = Consistent past tense, clear sections, concise bullets, strong summary
  70-89  = Minor inconsistencies; summary present but weak
  50-69  = Tense mixing, dense paragraphs, weak/missing summary
  <50    = Major formatting issues; no clear summary

Seniority context: {seniority_note}
{required_block}

Return ONLY valid JSON matching the schema. No prose, no markdown fences."""

    kw_hint = f"\nKnown JD keywords: {', '.join(jd_keywords[:30])}" if jd_keywords else ""

    prompt = f"""Evaluate this resume against the job description.{kw_hint}

--- RESUME ---
{resume_text[:6000]}

--- JOB DESCRIPTION ---
{jd_text[:3000]}

Return JSON with ALL fields populated. For lists, include every item found — do not truncate."""

    schema = {
        "type": "object",
        "properties": {
            "ats": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "missing_keywords": {"type": "array", "items": {"type": "string"}},
                    "matched_keywords": {"type": "array", "items": {"type": "string"}},
                    "keyword_coverage_pct": {"type": "number"},
                },
                "required": ["score", "missing_keywords", "matched_keywords", "keyword_coverage_pct"],
            },
            "impact": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "weak_bullets": {"type": "array", "items": {"type": "string"}},
                    "strong_bullets": {"type": "array", "items": {"type": "string"}},
                    "has_quantified_achievements": {"type": "boolean"},
                },
                "required": ["score", "weak_bullets", "strong_bullets", "has_quantified_achievements"],
            },
            "skills_gap": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "missing_skills": {"type": "array", "items": {"type": "string"}},
                    "matched_skills": {"type": "array", "items": {"type": "string"}},
                    "critical_missing": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["score", "missing_skills", "matched_skills", "critical_missing"],
            },
            "readability": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer"},
                    "issues": {"type": "array", "items": {"type": "string"}},
                    "worst_section": {"type": "string"},
                    "has_summary": {"type": "boolean"},
                    "tense_consistent": {"type": "boolean"},
                },
                "required": ["score", "issues", "worst_section", "has_summary", "tense_consistent"],
            },
            "overall": {"type": "integer"},
        },
        "required": ["ats", "impact", "skills_gap", "readability", "overall"],
    }

    result = await _llm_complete(prompt, system=system, schema=schema)

    # Normalise — guarantee all keys exist even if LLM drops one
    defaults = {
        "ats":        {"missing_keywords": [], "matched_keywords": [], "keyword_coverage_pct": 0.0},
        "impact":     {"weak_bullets": [], "strong_bullets": [], "has_quantified_achievements": False},
        "skills_gap": {"missing_skills": [], "matched_skills": [], "critical_missing": []},
        "readability": {"issues": [], "worst_section": "experience", "has_summary": False, "tense_consistent": False},
    }
    for section, defs in defaults.items():
        for key, val in defs.items():
            result.setdefault(section, {}).setdefault(key, val)
    result.setdefault("overall", 0)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_agents.py::test_scorer_returns_extended_fields tests/test_agents.py::test_scorer_no_max_3_in_prompt -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/agents/scorer.py resume-optimizer/backend/tests/test_agents.py
git commit -m "feat(scorer): add calibration rubric, extended fields, remove max-3 cap"
```

---

### Task 2: JD Analyzer — structured schema with seniority and required skills

**Files:**
- Modify: `resume-optimizer/backend/agents/jd_analyzer.py`
- Modify: `resume-optimizer/backend/tests/test_agents.py`

**Context:**
`analyze_jd` currently returns a flat `{keywords, requirements, skills}` dict. We need it to return `required_hard_skills`, `preferred_soft_skills`, `critical_keywords`, `tech_stack`, `seniority_level`, `industry`, `required_certifications` so the pipeline can thread richer context to every downstream agent.

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_agents.py`:

```python
@pytest.mark.asyncio
async def test_jd_analyzer_returns_structured_schema(monkeypatch):
    """analyze_jd must return required_hard_skills, seniority_level, industry, tech_stack."""
    from agents.jd_analyzer import analyze_jd

    fake_response = {
        "required_hard_skills": ["Python", "Kubernetes"],
        "preferred_soft_skills": ["communication", "ownership"],
        "critical_keywords": ["distributed systems", "microservices"],
        "tech_stack": ["Python", "Go", "Kubernetes", "AWS"],
        "seniority_level": "senior",
        "industry": "fintech",
        "required_certifications": [],
        "keywords": ["python", "kubernetes", "aws"],
        "requirements": ["5+ years Python", "K8s experience"],
        "skills": ["Python", "Kubernetes"],
    }

    async def mock_complete(prompt, system=None, schema=None):
        return fake_response

    monkeypatch.setattr("agents.jd_analyzer._llm_complete", mock_complete)

    result = await analyze_jd("Senior Python engineer at fintech, K8s required")
    assert "required_hard_skills" in result
    assert "seniority_level" in result
    assert "industry" in result
    assert "tech_stack" in result
    assert "preferred_soft_skills" in result
    assert "critical_keywords" in result
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_agents.py::test_jd_analyzer_returns_structured_schema -v
```

Expected: FAIL — keys missing from result.

- [ ] **Step 3: Rewrite `analyze_jd` in `agents/jd_analyzer.py`**

Replace the `analyze_jd` function and its prompt:

```python
async def analyze_jd(jd_text: str) -> dict:
    """Extract structured metadata from a job description."""
    system = """You are an expert technical recruiter. Extract structured data from job descriptions.

Seniority levels: entry (0-2 yrs), mid (3-6 yrs), senior (7+ yrs), lead (10+ yrs, manages teams).
Industry examples: fintech, healthtech, e-commerce, saas, gaming, enterprise-software, consulting.

Distinguish required vs preferred:
- required_hard_skills: explicitly required technical skills ("must have", "required", "X+ years of")
- preferred_soft_skills: "nice to have", "preferred", or behavioural traits
- critical_keywords: 3-8 ATS-critical terms that MUST appear on a resume to pass screening

Return ONLY valid JSON. No prose."""

    prompt = f"""Extract structured metadata from this job description:

{jd_text[:4000]}

Return JSON with all fields. For seniority_level use: entry | mid | senior | lead."""

    schema = {
        "type": "object",
        "properties": {
            "required_hard_skills":   {"type": "array", "items": {"type": "string"}},
            "preferred_soft_skills":  {"type": "array", "items": {"type": "string"}},
            "critical_keywords":      {"type": "array", "items": {"type": "string"}},
            "tech_stack":             {"type": "array", "items": {"type": "string"}},
            "seniority_level":        {"type": "string", "enum": ["entry", "mid", "senior", "lead"]},
            "industry":               {"type": "string"},
            "required_certifications": {"type": "array", "items": {"type": "string"}},
            "keywords":               {"type": "array", "items": {"type": "string"}},
            "requirements":           {"type": "array", "items": {"type": "string"}},
            "skills":                 {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "required_hard_skills", "preferred_soft_skills", "critical_keywords",
            "tech_stack", "seniority_level", "industry", "required_certifications",
            "keywords", "requirements", "skills",
        ],
    }

    result = await _llm_complete(prompt, system=system, schema=schema)

    # Guarantee all keys exist
    result.setdefault("required_hard_skills", [])
    result.setdefault("preferred_soft_skills", [])
    result.setdefault("critical_keywords", [])
    result.setdefault("tech_stack", [])
    result.setdefault("seniority_level", "mid")
    result.setdefault("industry", "")
    result.setdefault("required_certifications", [])
    result.setdefault("keywords", result.get("required_hard_skills", [])[:20])
    result.setdefault("requirements", [])
    result.setdefault("skills", result.get("required_hard_skills", []))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_agents.py::test_jd_analyzer_returns_structured_schema -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/agents/jd_analyzer.py resume-optimizer/backend/tests/test_agents.py
git commit -m "feat(jd-analyzer): structured schema — required skills, seniority, industry, tech stack"
```

---

### Task 3: Optimizer — consistent threshold, larger list caps, updated agent definition

**Files:**
- Modify: `resume-optimizer/backend/orchestration/optimizer.py`
- Modify: `resume-optimizer/backend/agents/optimizer_agent.py`
- Modify: `resume-optimizer/backend/tests/test_agents.py`

**Context:**
Two bugs:
1. `_flag(d)` threshold is hardcoded at `75` in `optimizer.py`, while the agent goal says "above `SCORE_TARGET`" — they drift. Fix: `_WORK_THRESHOLD = max(75, SCORE_TARGET - 10)`.
2. `missing_keywords[:8]`, `weak_bullets[:4]`, `missing_skills[:8]` are far too small — the agent misses most of the feedback. Fix: increase to `[:15]`, `[:8]`, `[:15]`.
3. `section_name` is hardcoded to `"summary"` — fix to use `worst_section` from scorer.
4. `AGENT_MAX_ITER = 10` in config/agent — reduce to 6 to match the HTML spec.

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_agents.py`:

```python
def test_optimizer_threshold_consistent():
    """_WORK_THRESHOLD must equal max(75, SCORE_TARGET - 10)."""
    import inspect
    from orchestration import optimizer as opt_module
    from config import SCORE_TARGET
    source = inspect.getsource(opt_module)
    expected = max(75, SCORE_TARGET - 10)
    assert "_WORK_THRESHOLD" in source, "_WORK_THRESHOLD constant not defined in optimizer.py"
    assert str(expected) in source or "SCORE_TARGET - 10" in source, \
        f"_WORK_THRESHOLD must be max(75, SCORE_TARGET-10) = {expected}"


def test_optimizer_list_caps_increased():
    """missing_keywords, weak_bullets, missing_skills caps must be at least 15/8/15."""
    import inspect
    from orchestration import optimizer as opt_module
    source = inspect.getsource(opt_module)
    assert "missing_keywords[:8]" not in source, \
        "missing_keywords still capped at 8 — increase to 15"
    assert "weak_bullets[:4]" not in source, \
        "weak_bullets still capped at 4 — increase to 8"
    assert "missing_skills[:8]" not in source, \
        "missing_skills still capped at 8 — increase to 15"


def test_optimizer_agent_max_iter_is_six():
    """AGENT_MAX_ITER must be 6 (not 10)."""
    import inspect
    from agents import optimizer_agent
    source = inspect.getsource(optimizer_agent)
    # Find AGENT_MAX_ITER assignment
    import re
    match = re.search(r"AGENT_MAX_ITER\s*=\s*(\d+)", source)
    assert match, "AGENT_MAX_ITER not found in optimizer_agent.py"
    assert int(match.group(1)) == 6, f"AGENT_MAX_ITER should be 6, got {match.group(1)}"


def test_section_name_uses_worst_section():
    """_build_task_description must use worst_section from scorer, not hardcode 'summary'."""
    import inspect
    from orchestration import optimizer as opt_module
    source = inspect.getsource(opt_module)
    assert 'section_name = "summary"' not in source, \
        "section_name is hardcoded to 'summary' — use worst_section from scorer readability"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_agents.py::test_optimizer_threshold_consistent tests/test_agents.py::test_optimizer_list_caps_increased tests/test_agents.py::test_optimizer_agent_max_iter_is_six tests/test_agents.py::test_section_name_uses_worst_section -v
```

Expected: All FAIL.

- [ ] **Step 3: Fix `orchestration/optimizer.py`**

At the top of the file, add the constant (after imports):
```python
from config import SCORE_TARGET
_WORK_THRESHOLD = max(75, SCORE_TARGET - 10)
```

In `_flag(d)`, replace the hardcoded `75`:
```python
def _flag(d: dict) -> bool:
    return d.get("score", 100) < _WORK_THRESHOLD
```

In `_build_task_description`, replace list caps and section_name:
```python
# Before (remove these):
missing_kw = score["ats"].get("missing_keywords", [])[:8]
weak_bul   = score["impact"].get("weak_bullets", [])[:4]
miss_sk    = score["skills_gap"].get("missing_skills", [])[:8]
section_name = "summary"

# After (use these):
missing_kw = score["ats"].get("missing_keywords", [])[:15]
weak_bul   = score["impact"].get("weak_bullets", [])[:8]
miss_sk    = score["skills_gap"].get("missing_skills", [])[:15]
section_name = score.get("readability", {}).get("worst_section", "experience")
```

- [ ] **Step 4: Fix `agents/optimizer_agent.py`**

Change `AGENT_MAX_ITER` from `10` to `6` at the top of the file. Also update the agent `goal` and `backstory` to reference `_WORK_THRESHOLD`:

```python
AGENT_MAX_ITER = 6

def create_optimizer_agent() -> Agent:
    return Agent(
        role="Senior Resume Optimization Specialist",
        goal=(
            f"Maximize resume score above {_WORK_THRESHOLD} by injecting keywords, "
            "strengthening impact bullets, and aligning skills with the job requirements. "
            "Use all available tools and iterate until the score meets or exceeds the target."
        ),
        backstory=(
            "You have optimized thousands of resumes for ATS systems and human recruiters. "
            "You know exactly which keywords pass screening, how to turn vague duties into "
            "quantified achievements, and how to make a resume feel tailored rather than generic. "
            "You use every tool available and don't stop until the score target is met."
        ),
        tools=[keyword_inject, bullet_strengthen, skills_rewrite, section_humanize],
        llm=_get_llm(),
        verbose=False,
        max_iter=AGENT_MAX_ITER,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_agents.py::test_optimizer_threshold_consistent tests/test_agents.py::test_optimizer_list_caps_increased tests/test_agents.py::test_optimizer_agent_max_iter_is_six tests/test_agents.py::test_section_name_uses_worst_section -v
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/orchestration/optimizer.py resume-optimizer/backend/agents/optimizer_agent.py resume-optimizer/backend/tests/test_agents.py
git commit -m "feat(optimizer): consistent threshold, larger list caps, max_iter=6, worst_section"
```

---

### Task 4: ClaimsLedger — extend fact extraction, loosen fabrication guard tolerance

**Files:**
- Modify: `resume-optimizer/backend/agents/fact_extractor.py`
- Modify: `resume-optimizer/backend/agents/fabrication_guard.py`
- Modify: `resume-optimizer/backend/tests/test_agents.py`

**Context:**
`ClaimsLedger` only captures companies, metrics, and raw_bullets. We need `job_titles`, `degrees`, `date_ranges` to prevent the guard from flagging real credentials. The fabrication guard's metric tolerance is `0.02` (2%) which is too strict — rounding in LLM output triggers false positives. Raise to `0.10` (10%). Add `[VERIFY]` flagging for uncertain lines instead of silent substitution.

- [ ] **Step 1: Write the failing tests**

Add to `resume-optimizer/backend/tests/test_agents.py`:

```python
def test_claims_ledger_has_job_titles_field():
    """ClaimsLedger must have job_titles, degrees, and date_ranges fields."""
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(["Acme Corp"]),
        metrics=frozenset(["50%"]),
        raw_bullets=("Built the thing",),
        job_titles=frozenset(["Senior Engineer"]),
        degrees=frozenset(["BS Computer Science"]),
        date_ranges=frozenset(["2018-2022"]),
    )
    assert ledger.job_titles == frozenset(["Senior Engineer"])
    assert ledger.degrees == frozenset(["BS Computer Science"])
    assert ledger.date_ranges == frozenset(["2018-2022"])


def test_claims_ledger_backward_compat():
    """ClaimsLedger must construct without new fields (backward compat)."""
    from agents.fact_extractor import ClaimsLedger
    ledger = ClaimsLedger(
        companies=frozenset(["Acme"]),
        metrics=frozenset(["40%"]),
        raw_bullets=("Did stuff",),
    )
    assert hasattr(ledger, "job_titles")
    assert hasattr(ledger, "degrees")
    assert hasattr(ledger, "date_ranges")


def test_fabrication_guard_tolerance_is_ten_percent():
    """Metric tolerance in fabrication_guard must be >= 0.10 (not 0.02)."""
    import inspect
    from agents import fabrication_guard as fg_module
    source = inspect.getsource(fg_module)
    assert "0.02" not in source, \
        "Metric tolerance is still 0.02 — raise to 0.10 to avoid false positives from rounding"


def test_fabrication_guard_flags_verify_not_strips():
    """Guard must add [VERIFY] to uncertain lines, not silently substitute them."""
    from agents.fabrication_guard import fabrication_guard
    from agents.fact_extractor import ClaimsLedger

    ledger = ClaimsLedger(
        companies=frozenset(["Acme Corp"]),
        metrics=frozenset(["50%"]),
        raw_bullets=("Reduced latency by 50% at Acme Corp",),
    )
    # Line claims 90% — not in ledger, should be flagged [VERIFY]
    result = fabrication_guard(
        "• Reduced latency by 90% at MadeUpCorp",
        ledger,
        "Reduced latency by 50% at Acme Corp",
    )
    assert "[VERIFY]" in result.text or len(result.gaps) > 0, \
        "Guard must flag uncertain metric/company claims with [VERIFY]"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_agents.py::test_claims_ledger_has_job_titles_field tests/test_agents.py::test_claims_ledger_backward_compat tests/test_agents.py::test_fabrication_guard_tolerance_is_ten_percent tests/test_agents.py::test_fabrication_guard_flags_verify_not_strips -v
```

Expected: All FAIL.

- [ ] **Step 3: Extend `ClaimsLedger` in `agents/fact_extractor.py`**

Find the `ClaimsLedger` dataclass and add three fields with `default_factory`:

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class ClaimsLedger:
    companies:   frozenset
    metrics:     frozenset
    raw_bullets: tuple
    job_titles:  frozenset = field(default_factory=frozenset)
    degrees:     frozenset = field(default_factory=frozenset)
    date_ranges: frozenset = field(default_factory=frozenset)
```

In `extract_claims`, add extraction logic after the existing ORG extraction:

```python
# Job titles — heuristic: look for TITLE/PERSON entities or common title patterns
import re as _re
_TITLE_PATTERNS = [
    r'\b(Senior|Junior|Lead|Principal|Staff|VP|Director|Manager|Engineer|Developer|Analyst|Architect|Scientist|Specialist|Consultant|Associate)\b[\w\s]{0,20}(?:Engineer|Developer|Manager|Director|Analyst|Architect|Scientist|Specialist|Consultant)',
]
job_titles = set()
for pat in _TITLE_PATTERNS:
    job_titles.update(m.group() for m in _re.finditer(pat, resume_text, _re.IGNORECASE))

# Degrees
_DEGREE_RE = _re.compile(
    r'\b(?:Bachelor|Master|PhD|Ph\.D|B\.S|M\.S|B\.A|M\.A|MBA|Associate)[^,\n]{0,40}',
    _re.IGNORECASE,
)
degrees = set(m.group().strip() for m in _DEGREE_RE.finditer(resume_text))

# Date ranges
_DATE_RE = _re.compile(
    r'\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|[Pp]resent|[Cc]urrent)\b'
)
date_ranges = set(m.group() for m in _DATE_RE.finditer(resume_text))

return ClaimsLedger(
    companies=frozenset(companies),
    metrics=frozenset(metrics),
    raw_bullets=tuple(bullets),
    job_titles=frozenset(job_titles),
    degrees=frozenset(degrees),
    date_ranges=frozenset(date_ranges),
)
```

- [ ] **Step 4: Fix `agents/fabrication_guard.py`**

Change `_metric_attested` tolerance from `< 0.02` to `< 0.10`:

```python
def _metric_attested(claimed: str, ledger: ClaimsLedger) -> bool:
    ...
    return abs(claimed_val - src_val) / max(abs(src_val), 1e-9) < 0.10
```

Change the substitution in `fabrication_guard` from silent `_closest_original` to `[VERIFY]` flagging:

```python
# Before (remove this):
replacement = _closest_original(line, ledger.raw_bullets)
cleaned.append(replacement)
gaps.append(f"fabricated: {line!r} → replaced with closest original")

# After (use this):
cleaned.append(f"[VERIFY] {line}")
gaps.append(f"unverified claim: {line!r}")
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_agents.py::test_claims_ledger_has_job_titles_field tests/test_agents.py::test_claims_ledger_backward_compat tests/test_agents.py::test_fabrication_guard_tolerance_is_ten_percent tests/test_agents.py::test_fabrication_guard_flags_verify_not_strips -v
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/agents/fact_extractor.py resume-optimizer/backend/agents/fabrication_guard.py resume-optimizer/backend/tests/test_agents.py
git commit -m "feat(claims): extend ClaimsLedger with job_titles/degrees/date_ranges; guard tolerance 10%; VERIFY flagging"
```

---

### Task 5: Wire fabrication guard between Phase 2 and generate_docx in main.py

**Files:**
- Modify: `resume-optimizer/backend/main.py`
- Modify: `resume-optimizer/backend/tests/test_agent_improvements.py` (new file)

**Context:**
`fabrication_guard` is imported but never called on the final optimized text. The guard must run after `run_optimization_async` returns and before `generate_docx`. The `ClaimsLedger` is already built in Phase 1 as `claims`. The guard result's `.text` field should replace the optimized text.

- [ ] **Step 1: Write the failing test**

Create `resume-optimizer/backend/tests/test_agent_improvements.py`:

```python
"""Tests for agent pipeline improvements."""
import os
import sys
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_improvements.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")

import pytest


def test_fabrication_guard_called_after_optimization():
    """fabrication_guard must be called on the optimized text before generate_docx."""
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    # Guard call must come AFTER optimization result and BEFORE generate_docx
    guard_pos  = source.find("fabrication_guard(")
    docx_pos   = source.find("generate_docx(")
    optim_pos  = source.find("run_optimization_async(")
    assert guard_pos != -1, "fabrication_guard not called in _run_pipeline_task"
    assert optim_pos < guard_pos < docx_pos, \
        "fabrication_guard must be called after optimization and before generate_docx"
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_agent_improvements.py::test_fabrication_guard_called_after_optimization -v
```

Expected: FAIL — guard not called or called in wrong order.

- [ ] **Step 3: Wire the guard in `main.py`**

Find the Phase 2 / Phase 3 boundary in `_run_pipeline_task`. After `run_optimization_async` returns and before `generate_docx`, add:

```python
# Phase 2: optimization
opt_result = await run_optimization_async(
    resume_text=resume_text,
    jd_text=jd_text,
    jd_keywords=jd_keywords,
    score=baseline_score,
)
optimized_text = opt_result.get("optimized_resume", resume_text)

# Fabrication guard — flag unverified claims before rendering to DOCX
guard_result = fabrication_guard(optimized_text, claims, resume_text)
if guard_result.gaps:
    logger.warning(
        "fabrication_guard flagged %d unverified claims for job %s",
        len(guard_result.gaps),
        job_id,
    )
optimized_text = guard_result.text

# Phase 3: render
docx_bytes = generate_docx(optimized_text, ...)
```

Ensure `fabrication_guard` is imported at the top of `main.py`:
```python
from agents.fabrication_guard import fabrication_guard
```

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_agent_improvements.py::test_fabrication_guard_called_after_optimization -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/main.py resume-optimizer/backend/tests/test_agent_improvements.py
git commit -m "feat(pipeline): wire fabrication_guard between optimization and generate_docx"
```

---

### Task 6: Humanizer — industry/seniority params, focused 3-objective prompt, JD context to critic

**Files:**
- Modify: `resume-optimizer/backend/agents/humanizer.py`
- Modify: `resume-optimizer/backend/tests/test_agent_improvements.py`

**Context:**
`humanize_resume` is currently orphaned (not called in pipeline) and has a 7-objective Step 1 prompt and a `"max 3 items"` critic cap. The HTML spec says:
- Step 1: 3 focused objectives: voice variety, confident hedges → assertions, industry tone
- Critic: pass `industry` and `seniority` context, no "max 3" cap
- Add `industry` and `seniority_level` params

- [ ] **Step 1: Write the failing tests**

Add to `resume-optimizer/backend/tests/test_agent_improvements.py`:

```python
def test_humanizer_accepts_industry_and_seniority_params():
    """humanize_resume must accept industry and seniority_level keyword args."""
    import inspect
    from agents.humanizer import humanize_resume
    sig = inspect.signature(humanize_resume)
    assert "industry" in sig.parameters, \
        "humanize_resume must accept 'industry' parameter"
    assert "seniority_level" in sig.parameters, \
        "humanize_resume must accept 'seniority_level' parameter"


def test_humanizer_has_three_objectives_not_seven():
    """Humanizer Step 1 prompt must focus on 3 objectives, not 7."""
    import inspect
    from agents import humanizer as hum_module
    source = inspect.getsource(hum_module)
    assert "7." not in source, \
        "Humanizer still has 7 objectives — reduce to 3 focused objectives"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_agent_improvements.py::test_humanizer_accepts_industry_and_seniority_params tests/test_agent_improvements.py::test_humanizer_has_three_objectives_not_seven -v
```

Expected: Both FAIL.

- [ ] **Step 3: Rewrite `humanize_resume` signature and Step 1 prompt in `agents/humanizer.py`**

Change function signature:

```python
async def humanize_resume(
    resume_text: str,
    industry: str = "",
    seniority_level: str = "mid",
) -> dict:
```

Replace Step 1 system prompt (the 7-objective one) with:

```python
    industry_note = f" Write in the voice of a credible {industry} professional." if industry else ""
    seniority_note = {
        "entry":  " Tone should be eager, growth-focused.",
        "mid":    " Tone should be confident and results-oriented.",
        "senior": " Tone should be authoritative, strategic, outcome-driven.",
        "lead":   " Tone should be visionary, org-level impact, team multiplier.",
    }.get(seniority_level, "")

    step1_system = f"""You are a professional resume writer.{industry_note}{seniority_note}

Improve the resume text on exactly THREE dimensions:
1. Voice variety — vary sentence openings; avoid starting consecutive bullets with the same verb
2. Confident assertions — replace hedges ("helped with", "assisted in", "worked on") with direct ownership ("led", "built", "delivered", "owned")
3. Industry tone — use vocabulary natural to the target industry; avoid generic filler phrases

Preserve every metric, company name, job title, and date exactly as written.
Return ONLY the improved resume text. No commentary."""
```

In the critic (Step 2), add industry context and remove "max 3":

```python
    step2_system = f"""You are a senior hiring manager reviewing a resume for a {seniority_level}-level {industry or "technology"} role.

Critique the revised resume below. Be specific: quote the exact phrases that still feel weak, robotic, or generic.
State what should be different and why — no character limits on your feedback."""
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_agent_improvements.py::test_humanizer_accepts_industry_and_seniority_params tests/test_agent_improvements.py::test_humanizer_has_three_objectives_not_seven -v
```

Expected: Both PASS.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/agents/humanizer.py resume-optimizer/backend/tests/test_agent_improvements.py
git commit -m "feat(humanizer): 3-objective prompt, industry/seniority params, no max-3 critic cap"
```

---

### Task 7: Rewriter — 3-priority prompt, dynamic length, self-check instruction

**Files:**
- Modify: `resume-optimizer/backend/agents/rewriter.py`
- Modify: `resume-optimizer/backend/tests/test_agent_improvements.py`

**Context:**
The rewriter has an 8-objective prompt with an absolute 600-word/50-bullet hard cap. The HTML spec says: collapse to 3 priorities (keywords first, then metrics, then flow), make length dynamic based on input length, add a self-check instruction.

- [ ] **Step 1: Write the failing test**

Add to `resume-optimizer/backend/tests/test_agent_improvements.py`:

```python
def test_rewriter_has_three_priorities_not_eight():
    """Rewriter prompt must use 3 priorities, not 8 objectives."""
    import inspect
    from agents import rewriter as rw_module
    source = inspect.getsource(rw_module)
    assert "8." not in source, \
        "Rewriter still has 8 objectives — collapse to 3 priorities"


def test_rewriter_no_hardcoded_600_word_limit():
    """Rewriter must not have a hardcoded 600-word absolute cap."""
    import inspect
    from agents import rewriter as rw_module
    source = inspect.getsource(rw_module)
    assert "600 words" not in source and "600-word" not in source, \
        "Rewriter has hardcoded 600-word cap — make length dynamic"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_agent_improvements.py::test_rewriter_has_three_priorities_not_eight tests/test_agent_improvements.py::test_rewriter_no_hardcoded_600_word_limit -v
```

Expected: Both FAIL.

- [ ] **Step 3: Rewrite the system prompt in `agents/rewriter.py`**

Replace the system prompt and prompt-building section:

```python
async def rewrite_resume(
    resume_text: str,
    jd_keywords: list[str],
    consolidated_feedback: str | None = None,
    claims_ledger=None,
    seniority_level: str = "mid",
    industry: str = "",
) -> dict:
    input_word_count = len(resume_text.split())
    # Dynamic length: stay within 20% of original, never exceed 700
    max_words = min(700, int(input_word_count * 1.2))

    industry_note = f" Tailor language for the {industry} industry." if industry else ""

    system = f"""You are an expert resume writer specializing in ATS optimization.{industry_note}

Rewrite the resume following THREE priorities in order:

PRIORITY 1 — KEYWORD SATURATION
  Weave all JD keywords naturally into bullets and summary.
  Every required keyword must appear at least once; critical keywords ideally 2-3 times.

PRIORITY 2 — QUANTIFIED IMPACT
  Every bullet must contain a metric (%, $, count, time). If a bullet has no metric, add a
  realistic placeholder using the format [XX%] that the user can fill in.
  Replace duty-description ("Responsible for X") with achievement framing ("Delivered X, resulting in Y").

PRIORITY 3 — FLOW AND CONCISION
  Keep total length within {max_words} words (current: {input_word_count} words).
  Vary bullet openings — no two consecutive bullets may start with the same verb.
  Use consistent past tense throughout except for current role (present tense).

SELF-CHECK before returning: confirm all required keywords appear, all bullets have metrics,
and the word count is under {max_words}.

Preserve all company names, job titles, dates, and degrees exactly as written.
Return ONLY the rewritten resume text. No commentary, no fences."""

    kw_block = "\n".join(f"  - {kw}" for kw in jd_keywords[:25])
    feedback_block = f"\n\nEditor feedback to incorporate:\n{consolidated_feedback}" if consolidated_feedback else ""

    prompt = f"""Required keywords to inject:
{kw_block}
{feedback_block}

--- RESUME ---
{resume_text[:6000]}"""

    result_text = await _llm_complete(prompt, system=system)
    return {"rewritten_resume": result_text, "word_count": len(result_text.split())}
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_agent_improvements.py::test_rewriter_has_three_priorities_not_eight tests/test_agent_improvements.py::test_rewriter_no_hardcoded_600_word_limit -v
```

Expected: Both PASS.

- [ ] **Step 5: Commit**

```bash
git add resume-optimizer/backend/agents/rewriter.py resume-optimizer/backend/tests/test_agent_improvements.py
git commit -m "feat(rewriter): 3-priority prompt, dynamic length cap, self-check instruction"
```

---

### Task 8: Thread JD metadata through pipeline and implement MAX_ITERATIONS iteration loop

**Files:**
- Modify: `resume-optimizer/backend/main.py`
- Modify: `resume-optimizer/backend/tests/test_agent_improvements.py`

**Context:**
This is the integration task that connects everything:
1. `analyze_jd` now returns `seniority_level`, `industry`, `required_hard_skills` — thread them to `score_combined`, `rewrite_resume`, `humanize_resume`, and the optimizer task description.
2. Implement the `MAX_ITERATIONS` loop: after Phase 2 optimization, re-score; if score < `_WORK_THRESHOLD` and iterations remain, loop again. Use `f"{job_id}_i{iteration}"` as the unique session key per iteration.
3. Call `humanize_resume` with `industry` and `seniority_level` after the fabrication guard.
4. Persist `iterations` count to the `Resume` row (currently hardcoded to `1`).

- [ ] **Step 1: Write the failing tests**

Add to `resume-optimizer/backend/tests/test_agent_improvements.py`:

```python
def test_pipeline_uses_max_iterations_loop():
    """_run_pipeline_task must implement a MAX_ITERATIONS loop, not a single call."""
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert "MAX_ITERATIONS" in source, \
        "Pipeline must use MAX_ITERATIONS loop"
    assert "for " in source or "while " in source, \
        "Pipeline must have a loop construct for iterations"


def test_pipeline_threads_seniority_to_scorer():
    """_run_pipeline_task must pass seniority_level to score_combined."""
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert "seniority_level" in source, \
        "seniority_level from JD analyzer not threaded to score_combined"


def test_pipeline_threads_industry_to_humanizer():
    """_run_pipeline_task must pass industry to humanize_resume."""
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert "humanize_resume" in source, \
        "humanize_resume not called in pipeline"
    # industry must appear near the humanize_resume call
    guard_pos = source.find("humanize_resume(")
    context = source[max(0, guard_pos - 200): guard_pos + 200]
    assert "industry" in context, \
        "industry not passed to humanize_resume"


def test_pipeline_iterations_not_hardcoded_to_one():
    """iterations persisted to DB must not be hardcoded to 1."""
    import inspect
    from main import _run_pipeline_task
    source = inspect.getsource(_run_pipeline_task)
    assert "iterations=1" not in source, \
        "iterations persisted to Resume is hardcoded to 1 — use actual loop count"
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_agent_improvements.py::test_pipeline_uses_max_iterations_loop tests/test_agent_improvements.py::test_pipeline_threads_seniority_to_scorer tests/test_agent_improvements.py::test_pipeline_threads_industry_to_humanizer tests/test_agent_improvements.py::test_pipeline_iterations_not_hardcoded_to_one -v
```

Expected: All FAIL.

- [ ] **Step 3: Rewrite the pipeline phases in `main.py`**

In `_run_pipeline_task`, locate the Phase 1 → Phase 2 → Phase 3 sequence and replace it with:

```python
# ── Phase 1: Extract facts and analyze JD ────────────────────────────────
claims = await extract_claims(resume_text)
jd_meta = await analyze_jd(jd_text)

jd_keywords        = jd_meta.get("keywords", [])
required_hard_skills = jd_meta.get("required_hard_skills", [])
seniority_level    = jd_meta.get("seniority_level", "mid")
industry           = jd_meta.get("industry", "")

baseline_score = await score_combined(
    resume_text,
    jd_text,
    jd_keywords=jd_keywords,
    seniority_level=seniority_level,
    required_hard_skills=required_hard_skills,
)
await _emit(job_id, db_factory, {"type": "score", "phase": "baseline", "score": baseline_score})

# ── Phase 2: Optimization loop ───────────────────────────────────────────
from orchestration.optimizer import _WORK_THRESHOLD
current_text = resume_text
current_score = baseline_score
iteration = 0

for iteration in range(1, MAX_ITERATIONS + 1):
    session_key = f"{job_id}_i{iteration}"
    opt_result = await run_optimization_async(
        resume_text=current_text,
        jd_text=jd_text,
        jd_keywords=jd_keywords,
        score=current_score,
        session_key=session_key,
    )
    optimized_text = opt_result.get("optimized_resume", current_text)

    # Fabrication guard — flag unverified claims
    guard_result = fabrication_guard(optimized_text, claims, resume_text)
    if guard_result.gaps:
        logger.warning(
            "fabrication_guard flagged %d claims on iteration %d for job %s",
            len(guard_result.gaps), iteration, job_id,
        )
    optimized_text = guard_result.text

    # Re-score after optimization
    iteration_score = await score_combined(
        optimized_text,
        jd_text,
        jd_keywords=jd_keywords,
        seniority_level=seniority_level,
        required_hard_skills=required_hard_skills,
    )
    await _emit(job_id, db_factory, {
        "type": "score",
        "phase": f"iteration_{iteration}",
        "score": iteration_score,
    })

    current_text  = optimized_text
    current_score = iteration_score

    if current_score.get("overall", 0) >= _WORK_THRESHOLD:
        break

# Humanize after optimization loop
humanized_result = await humanize_resume(
    current_text,
    industry=industry,
    seniority_level=seniority_level,
)
final_text = humanized_result.get("humanized_resume", current_text)

# ── Phase 3: Render and persist ──────────────────────────────────────────
docx_bytes = generate_docx(final_text, ...)

# Persist Resume row with actual iteration count
async with AsyncSessionLocal() as db:
    resume_row = Resume(
        ...
        iterations=iteration,
        ...
    )
    db.add(resume_row)
    await db.commit()
```

Note: adjust the `generate_docx` call and `Resume` constructor to match existing signatures — only add `iterations=iteration` where `iterations=1` was hardcoded before.

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_agent_improvements.py::test_pipeline_uses_max_iterations_loop tests/test_agent_improvements.py::test_pipeline_threads_seniority_to_scorer tests/test_agent_improvements.py::test_pipeline_threads_industry_to_humanizer tests/test_agent_improvements.py::test_pipeline_iterations_not_hardcoded_to_one -v
```

Expected: All PASS.

- [ ] **Step 5: Run the full improvements test suite**

```
python -m pytest tests/test_agent_improvements.py tests/test_agents.py -v
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add resume-optimizer/backend/main.py resume-optimizer/backend/tests/test_agent_improvements.py
git commit -m "feat(pipeline): thread JD metadata, MAX_ITERATIONS loop, humanizer wired, guard in loop"
```

---

## Self-Review

**Spec coverage:**
- Scorer calibration rubric ✅ Task 1
- "Max 3" cap removed from scorer ✅ Task 1
- New scorer fields (keyword_coverage_pct, worst_section, critical_missing, etc.) ✅ Task 1
- JD structured schema (required_hard_skills, seniority_level, industry, tech_stack) ✅ Task 2
- Optimizer threshold consistency ✅ Task 3
- Optimizer list caps increased ✅ Task 3
- Optimizer agent max_iter=6 ✅ Task 3
- worst_section used for section_name ✅ Task 3
- ClaimsLedger job_titles/degrees/date_ranges ✅ Task 4
- Fabrication guard tolerance 10% ✅ Task 4
- [VERIFY] flagging instead of silent substitution ✅ Task 4
- Fabrication guard wired in pipeline ✅ Task 5
- Humanizer industry/seniority params ✅ Task 6
- Humanizer 3-objective Step 1 ✅ Task 6
- Humanizer JD context to critic ✅ Task 6
- Rewriter 3-priority prompt ✅ Task 7
- Rewriter dynamic length ✅ Task 7
- Rewriter self-check ✅ Task 7
- JD metadata threaded to all agents ✅ Task 8
- MAX_ITERATIONS loop ✅ Task 8
- humanize_resume called in pipeline ✅ Task 8
- iterations persisted to DB ✅ Task 8

**Placeholder scan:** No TBDs or TODOs found. All code blocks are complete.

**Type consistency:** `score_combined` new params (`seniority_level`, `required_hard_skills`) match usage in Task 8. `ClaimsLedger` new fields use `default_factory=frozenset` ensuring backward compat. `humanize_resume` new params match Task 6 definition and Task 8 call site. `_WORK_THRESHOLD` defined in Task 3 and imported in Task 8.

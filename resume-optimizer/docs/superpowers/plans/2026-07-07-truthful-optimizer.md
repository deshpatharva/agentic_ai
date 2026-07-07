# Truthful Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the Phase 2 optimizer from score-chasing to evidence-constrained presentation: a capabilities allowlist feeds the strategist and tools, unevidenced items become a user-facing honest-gap report, and the guard/verifier/score run on the delivered text.

**Architecture:** A deterministic `capabilities` set is added to `ClaimsLedger` (skills-section tokens + curated-taxonomy matches). `ResumeState` carries it plus a thread-safe gap collector. Tools filter inputs in Python before any LLM call; the agent loop stops when remaining deficits are gap-blocked; `main.py` reorders the tail to humanize → guard (capability-aware) → verifier → final score.

**Tech Stack:** Python 3.11 (Windows venv invoked from WSL), pytest + pytest-asyncio (auto mode), LiteLLM. No new dependencies.

**Spec:** `resume-optimizer/docs/superpowers/specs/2026-07-07-truthful-optimizer-design.md` — prompt texts in tasks below are copied verbatim from it.

## Global Constraints

- All commands run from `resume-optimizer/backend/`; python is `../.venv/Scripts/python.exe` (Windows venv from WSL — bash `VAR=x` prefixes do NOT propagate; env vars are set in `tests/conftest.py`).
- Test command pattern: `../.venv/Scripts/python.exe -m pytest tests/<file> -q` (full suite: `tests/ -q`; currently 464 passed, must stay green after every task).
- Console is cp1252: no unicode in test assertions or printed strings; use `--` not em-dashes in new prompt/test literals.
- Mocking convention: patch the name as resolved in the module under test (e.g. `agents.tools.complete`, `orchestration.agent_loop.complete_with_tools`).
- `SCORE_TARGET` stays 90. No new dependencies. No frontend changes.
- Commit after every task on branch `claude/effort-estimation-m4a4ep`; message style `feat|fix|test|docs: ...`.

---

### Task 1: Capabilities ledger

**Files:**
- Modify: `utils/skills_normalizer.py` (add `taxonomy_terms()` helper after the `_register(...)` calls)
- Modify: `agents/fact_extractor.py` (new `capabilities` field + extraction)
- Modify: `agents/memory.py` (serialize/merge the new field)
- Test: `tests/test_capabilities_ledger.py` (create)

**Interfaces:**
- Consumes: `utils.skills_normalizer._SKILL_CATEGORY` (existing dict, lowercased term → category), `utils.skills_normalizer._parse_skills(text) -> list[str]` (existing), `utils.section_parser.detect_sections(text) -> dict` (existing).
- Produces: `utils.skills_normalizer.taxonomy_terms() -> frozenset[str]` (lowercased); `ClaimsLedger.capabilities: frozenset` (lowercased terms); `ClaimsLedger.prompt_block()` including a `Verified capabilities:` line; `memory._ledger_to_dict/_dict_to_ledger/merge_ledgers` handling `capabilities`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_capabilities_ledger.py`:

```python
"""Capabilities ledger: deterministic skill-evidence extraction (spec section 1)."""

RESUME = """John Carter
Boston, MA

Summary
Software engineer working on web applications and backend services.

Experience
Meridian Software - Software Engineer (2021 - Present)
- Built REST APIs for the customer portal in Python
- Worked on the PostgreSQL database and query tuning
- Moved some services to AWS

Education
B.S. Computer Science, State University (2019)

Skills
Python, Flask, SQL, PostgreSQL, Git, SnowConvert Custom Tool
"""


def test_taxonomy_terms_exposed():
    from utils.skills_normalizer import taxonomy_terms
    terms = taxonomy_terms()
    assert "python" in terms and "kubernetes" in terms
    assert all(t == t.lower() for t in terms)


def test_capabilities_from_skills_section_and_taxonomy():
    from agents.fact_extractor import extract_claims
    ledger = extract_claims(RESUME)
    # skills-section tokens (even non-taxonomy ones) are evidenced
    assert "snowconvert custom tool" in ledger.capabilities
    # taxonomy term evidenced only in experience text
    assert "aws" in ledger.capabilities
    # NOT in the resume anywhere
    assert "kubernetes" not in ledger.capabilities
    assert "terraform" not in ledger.capabilities


def test_capabilities_word_boundaries():
    from agents.fact_extractor import extract_claims
    # "go" must not match inside "Django"; "r" must not match inside "Rust-like"
    ledger = extract_claims("Skills\nDjango only\n\nExperience\n- Built things")
    assert "go" not in ledger.capabilities
    assert "django" in ledger.capabilities


def test_prompt_block_includes_capabilities():
    from agents.fact_extractor import extract_claims
    ledger = extract_claims(RESUME)
    block = ledger.prompt_block()
    assert "Verified capabilities:" in block
    assert "python" in block.lower()


def test_memory_roundtrip_and_merge_with_capabilities():
    from agents.fact_extractor import ClaimsLedger
    from agents.memory import _dict_to_ledger, _ledger_to_dict, merge_ledgers

    a = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                     raw_bullets=(), capabilities=frozenset({"python"}))
    b = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                     raw_bullets=(), capabilities=frozenset({"aws"}))
    merged = merge_ledgers(a, b)
    assert merged.capabilities == frozenset({"python", "aws"})
    assert _dict_to_ledger(_ledger_to_dict(merged)).capabilities == merged.capabilities
    # old stored dicts (no key) load as empty frozenset
    d = _ledger_to_dict(a); d.pop("capabilities")
    assert _dict_to_ledger(d).capabilities == frozenset()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_capabilities_ledger.py -q`
Expected: FAIL — `ImportError: cannot import name 'taxonomy_terms'` / `TypeError: ... unexpected keyword argument 'capabilities'`.

- [ ] **Step 3: Implement**

In `utils/skills_normalizer.py`, directly after the last `_register(...)` call block:

```python
def taxonomy_terms() -> frozenset:
    """All known skill terms (lowercased) from the curated taxonomy.

    Single source of truth for capability evidence checks (fact_extractor,
    fabrication_guard)."""
    return frozenset(_SKILL_CATEGORY.keys())
```

In `agents/fact_extractor.py`:

Add imports near the top (after `import spacy`):

```python
from utils.section_parser import detect_sections
from utils.skills_normalizer import _parse_skills, taxonomy_terms
```

Add the field to `ClaimsLedger` (after `date_ranges`):

```python
    capabilities: frozenset = field(default_factory=frozenset)  # evidenced skills/tools (lowercased)
```

Extend `prompt_block()` — insert before the final `if not self.metrics ...` fallback:

```python
        if self.capabilities:
            parts.append(f"  Verified capabilities: {', '.join(sorted(self.capabilities))}")
```

and change the fallback condition to `if not self.metrics and not self.companies and not self.capabilities:`.

Add the extraction helper (module level, above `extract_claims`) and precompiled patterns:

```python
# Custom boundaries so "c++", "c#", "ci/cd" match whole terms and "go" never
# matches inside "Django". Compiled once at import.
_TAXONOMY_PATTERNS: dict = {
    t: re.compile(r"(?<![\w+#])" + re.escape(t) + r"(?![\w+#])")
    for t in taxonomy_terms()
}


def _extract_capabilities(resume_text: str) -> frozenset:
    caps: set = set()
    skills_text = detect_sections(resume_text).get("skills", "")
    if skills_text.strip():
        caps.update(t.lower() for t in _parse_skills(skills_text))
    text_lower = resume_text.lower()
    for term, pattern in _TAXONOMY_PATTERNS.items():
        if pattern.search(text_lower):
            caps.add(term)
    return frozenset(caps)
```

In `extract_claims`, add to the returned `ClaimsLedger(...)`:

```python
        capabilities=_extract_capabilities(resume_text),
```

In `agents/memory.py`: add `"capabilities": sorted(ledger.capabilities),` to `_ledger_to_dict`; add `capabilities = frozenset(d.get("capabilities", [])),` to `_dict_to_ledger`; add `capabilities = base.capabilities | fresh.capabilities,` to `merge_ledgers`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_capabilities_ledger.py tests/test_claims_memory.py tests/test_claims_improvements.py -q`
Expected: PASS (existing claims tests unaffected — new field has a default).

- [ ] **Step 5: Commit**

```bash
git add utils/skills_normalizer.py agents/fact_extractor.py agents/memory.py tests/test_capabilities_ledger.py
git commit -m "feat: capabilities ledger - deterministic skill evidence in ClaimsLedger"
```

---

### Task 2: ResumeState capabilities + honest-gap collector

**Files:**
- Modify: `agents/tools.py` (ResumeState `__init__`, new methods)
- Test: `tests/test_agent_tools.py` (append new tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ResumeState(sections, available_metrics="", capabilities=frozenset())` with `.capabilities: frozenset` (lowercased), `.add_gaps(items: Iterable[str]) -> None`, `.honest_gaps() -> list[str]` (sorted, deduped). All existing constructor call sites stay valid (new arg is defaulted).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_agent_tools.py`:

```python
# ---------------------------------------------------------------------------
# Capabilities + honest gaps (truthful optimizer)
# ---------------------------------------------------------------------------


def test_resume_state_capabilities_lowercased():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "x"}, capabilities=frozenset({"Python", "AWS"}))
    assert st.capabilities == frozenset({"python", "aws"})


def test_resume_state_gap_collector_dedups_and_sorts():
    from agents import tools

    st = tools.ResumeState(sections={"summary": "x"})
    st.add_gaps(["Kubernetes", "terraform", "Kubernetes", "  "])
    st.add_gaps(("docker",))
    assert st.honest_gaps() == ["Kubernetes", "docker", "terraform"]
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'capabilities'`.

- [ ] **Step 3: Implement** in `agents/tools.py`.

Change the `ResumeState.__init__` signature and body:

```python
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
```

Add after `available_sections()`:

```python
    # -- Honest gaps -----------------------------------------------------------

    def add_gaps(self, items) -> None:
        """Record JD asks that cannot be truthfully added (no evidence)."""
        with self._lock:
            self._gaps.update(i.strip() for i in items if i and i.strip())

    def honest_gaps(self) -> list:
        with self._lock:
            return sorted(self._gaps)
```

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/tools.py tests/test_agent_tools.py
git commit -m "feat: ResumeState capabilities allowlist and honest-gap collector"
```

---

### Task 3: Evidence filtering + new prompts for keyword_inject and skills_rewrite

**Files:**
- Modify: `agents/tools.py` (`split_evidenced` helper, `_SENIORITY_STOPWORDS`, both tool bodies + prompts)
- Test: `tests/test_agent_tools.py` (new tests; update any existing inject/skills tests that now filter everything out)

**Interfaces:**
- Consumes: `ResumeState.capabilities`, `ResumeState.add_gaps` (Task 2).
- Produces: `agents.tools.split_evidenced(items: list[str], capabilities: frozenset) -> tuple[list[str], list[str]]` (evidenced, gaps — seniority words dropped from both); `agents.tools._SENIORITY_STOPWORDS: frozenset`. Tool return strings: `"Injected (evidenced): ... Skipped (no evidence -- recorded as gaps): ..."` and `"All requested items lack evidence -- recorded as honest gaps: ..."`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_agent_tools.py`:

```python
def test_split_evidenced_partitions_and_drops_seniority():
    from agents.tools import split_evidenced

    caps = frozenset({"python", "aws", "ci/cd", "distributed systems"})
    evidenced, gaps = split_evidenced(
        ["Python", "Kubernetes", "AWS (ECS, Lambda)", "CI/CD pipelines",
         "distributed systems design", "Senior", "Terraform"],
        caps,
    )
    assert evidenced == ["Python", "AWS (ECS, Lambda)", "CI/CD pipelines",
                         "distributed systems design"]
    assert gaps == ["Kubernetes", "Terraform"]  # "Senior" dropped entirely


async def test_keyword_inject_filters_unevidenced_and_records_gaps():
    from agents import tools

    st = tools.ResumeState(
        sections={"experience": "Built APIs in Python for the portal."},
        capabilities=frozenset({"python"}),
    )
    captured = {}

    async def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return FAKE_RESULT

    with patch("agents.tools.complete", _capture):
        obs = await tools.keyword_inject(st, "Python, Kubernetes, Terraform",
                                         target_sections_csv="experience")
    assert "Kubernetes" not in captured["prompt"]
    assert "Terraform" not in captured["prompt"]
    assert "Python" in captured["prompt"]
    assert "Skipped (no evidence" in obs
    assert st.honest_gaps() == ["Kubernetes", "Terraform"]


async def test_keyword_inject_all_gaps_makes_no_llm_call():
    from agents import tools

    st = tools.ResumeState(sections={"experience": "Built things."},
                           capabilities=frozenset({"python"}))
    called = []

    async def _capture(prompt, model, **kw):
        called.append(1)
        return FAKE_RESULT

    with patch("agents.tools.complete", _capture):
        obs = await tools.keyword_inject(st, "Kubernetes, Terraform")
    assert not called
    assert "lack evidence" in obs
    assert st.honest_gaps() == ["Kubernetes", "Terraform"]


async def test_skills_rewrite_only_offers_evidenced_skills():
    from agents import tools

    st = tools.ResumeState(
        sections={"skills": "Skills\nPython, SQL", "experience": "Used AWS daily."},
        capabilities=frozenset({"python", "sql", "aws"}),
    )
    captured = {}

    async def _capture(prompt, model, **kw):
        captured["prompt"] = prompt
        return FAKE_RESULT

    with patch("agents.tools.complete", _capture):
        obs = await tools.skills_rewrite(st, "AWS, Kubernetes")
    assert "AWS" in captured["prompt"]
    assert "Kubernetes" not in captured["prompt"]
    assert "evidenced" in captured["prompt"]
    assert st.honest_gaps() == ["Kubernetes"]
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py -q`
Expected: FAIL — `ImportError: cannot import name 'split_evidenced'`.

- [ ] **Step 3: Implement** in `agents/tools.py`.

Add `import re` to the imports. Add above the tools (after `_budget_ok`):

```python
# -- Evidence filtering ---------------------------------------------------------

_SENIORITY_STOPWORDS = frozenset({
    "senior", "junior", "lead", "principal", "staff", "expert", "seasoned",
    "entry-level", "mid-level", "experienced",
})


def _norm_term(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", s.lower())          # strip parentheticals
    return re.sub(r"\s+", " ", s).strip(" .")


def split_evidenced(items, capabilities) -> tuple:
    """Partition JD asks into (evidenced, gaps) against the capabilities allowlist.

    Seniority/role adjectives are dropped from BOTH lists -- titles are never
    keyword-injectable and are not closable gaps either (spec 2b).
    """
    evidenced, gaps = [], []
    for item in items:
        n = _norm_term(item)
        if not n or n in _SENIORITY_STOPWORDS:
            continue
        hit = n in capabilities or any(
            re.search(r"(?<![\w+#])" + re.escape(c) + r"(?![\w+#])", n)
            for c in capabilities
        )
        (evidenced if hit else gaps).append(item)
    return evidenced, gaps
```

Replace the body of `keyword_inject` between the budget check and the section loop:

```python
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
```

Replace the prompt inside the section loop with (verbatim from spec 3c, plus the cross-section note):

```python
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
```

After a successful section update (`updated.append(section_name)`), set the note for the next section:

```python
            used_note = (f"\nAlready used in another section: {', '.join(evidenced)} "
                         f"-- do not repeat them here.")
```

Replace the final return strings of `keyword_inject`:

```python
    skipped_note = (f" Skipped (no evidence -- recorded as gaps): {', '.join(gaps)}."
                    if gaps else "")
    if updated:
        return (f"Injected (evidenced): {', '.join(evidenced)} into: "
                f"{', '.join(updated)}.{skipped_note}")
    available = state.available_sections()
    return (f"No target sections found ({target_sections_csv}). "
            f"Available: {', '.join(available)}.{skipped_note}")
```

Replace `skills_rewrite`'s missing-parse block and prompt:

```python
    missing = [s.strip() for s in missing_skills_csv.split(",") if s.strip()]
    if not missing:
        return "No missing skills provided -- nothing to add."
    evidenced, gaps = split_evidenced(missing, state.capabilities)
    if gaps:
        state.add_gaps(gaps)
    if not evidenced:
        return (f"All requested items lack evidence -- recorded as honest gaps: "
                f"{', '.join(gaps)}.")

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
```

and its success return:

```python
    skipped_note = (f" Skipped (no evidence -- recorded as gaps): {', '.join(gaps)}."
                    if gaps else "")
    if result.get("text"):
        state.update_section("skills", result["text"])
        return f"Skills section updated to include: {', '.join(evidenced)}.{skipped_note}"
    return "Skills rewrite returned empty output -- section unchanged."
```

The no-skills-section early return keeps its redirect but passes only evidenced items:
compute the partition BEFORE the `if not skills_text.strip():` check and use
`missing_keywords_csv='{', '.join(evidenced)}'` in that message (move the
`skills_text = state.get_section("skills")` lookup below the partition).

- [ ] **Step 4: Run to verify pass; fix any pre-existing tool tests**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_pr6_jd_tailoring.py tests/test_field_agnostic.py -q`

Pre-existing tests that call `keyword_inject`/`skills_rewrite` with a state built
without `capabilities` will now hit the all-gaps path. Fix each such failure by adding
`capabilities=frozenset({<the keywords the test injects, lowercased>})` to that test's
`ResumeState(...)` construction — do not weaken the new filtering.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/tools.py tests/test_agent_tools.py tests/test_pr6_jd_tailoring.py tests/test_field_agnostic.py
git commit -m "feat: evidence-filtered keyword_inject and skills_rewrite with honest-gap recording"
```

---

### Task 4: Remove critique_resume; fix bullets_reorder description

**Files:**
- Modify: `agents/tools.py` (delete `critique_resume` and the Tool 5 banner comment; drop `MODEL_CRITIQUE` import)
- Modify: `orchestration/agent_loop.py` (remove from `TOOL_DEFS` + `TOOL_MAP` + import; update `bullets_reorder` description)
- Modify: `tests/test_debate_loop.py:70` (tool list expectation)
- Test: whatever `grep -rn "critique" tests/` finds — delete those test functions

**Interfaces:**
- Consumes: nothing.
- Produces: `TOOL_DEFS` with exactly 4 entries; `TOOL_MAP` keys `{"keyword_inject", "bullet_strengthen", "skills_rewrite", "bullets_reorder"}`. Later tasks rely on there being no `critique_resume` anywhere.

- [ ] **Step 1: Update the failing expectation first** — in `tests/test_debate_loop.py` (line ~70) remove `"critique_resume",` from the expected tool-name list. Add to `tests/test_agent_tools.py`:

```python
def test_critique_resume_removed():
    from agents import tools
    from orchestration.agent_loop import TOOL_DEFS, TOOL_MAP

    assert not hasattr(tools, "critique_resume")
    assert "critique_resume" not in TOOL_MAP
    assert [t["function"]["name"] for t in TOOL_DEFS] == [
        "keyword_inject", "bullet_strengthen", "skills_rewrite", "bullets_reorder",
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py::test_critique_resume_removed -q`
Expected: FAIL — `assert not hasattr(...)`.

- [ ] **Step 3: Implement**

- `agents/tools.py`: delete the entire `critique_resume` function and its `# -- Tool 5 ...` banner; remove `MODEL_CRITIQUE` from the `config` import.
- `orchestration/agent_loop.py`: remove the `critique_resume` dict from `TOOL_DEFS`, the `"critique_resume": critique_resume,` entry from `TOOL_MAP`, and `critique_resume` from the `agents.tools` import. Change the `bullets_reorder` description to: `"Reorder bullets in a section (experience, summary, or skills) so the most JD-relevant appear first. Call when JD Tailoring score is below target due to bullet ordering."`
- Run `grep -rn "critique" tests/ --include='*.py'` and delete any test functions exercising `critique_resume` (expected in `tests/test_agent_tools.py` and/or `tests/test_agent_improvements.py`).

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_agent_loop.py tests/test_debate_loop.py tests/test_agent_improvements.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/tools.py orchestration/agent_loop.py tests/
git commit -m "feat: remove dead critique_resume tool; fix bullets_reorder description drift"
```

---

### Task 5: Strategist system prompt + evidence-split scores context

**Files:**
- Modify: `orchestration/agent_loop.py` (`_build_system_stable`, new `_dimension_work`, `_build_scores_context`, `_build_system`; `run_agent` call sites)
- Modify: `orchestration/debate_loop.py` (two builder call sites only)
- Test: `tests/test_truthful_prompts.py` (create)

**Interfaces:**
- Consumes: `ClaimsLedger.prompt_block()` (Task 1), `split_evidenced` (Task 3), `ResumeState.capabilities` (Task 2).
- Produces (later tasks call these with exactly these signatures):
  - `_build_system_stable(available_sections: list, ledger, user_instruction: Optional[str] = None) -> str`
  - `_dimension_work(scores: dict, capabilities: frozenset) -> dict` — keys `ats|impact|skills_gap|jd_tailoring`, each `{"score": int, "actionable": bool, ...}` with `addable`/`gaps` lists on ats and skills_gap, `items` on impact and jd_tailoring.
  - `_build_scores_context(scores: dict, capabilities: frozenset, heading: str = "CURRENT SCORES (baseline)") -> str`

- [ ] **Step 1: Write the failing tests** — create `tests/test_truthful_prompts.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_truthful_prompts.py -q`
Expected: FAIL — `TypeError` on new signatures / assertion errors on old text.

- [ ] **Step 3: Implement** in `orchestration/agent_loop.py`.

Add `split_evidenced` to the `agents.tools` import. Replace `_build_system_stable`:

```python
def _build_system_stable(available_sections: list, ledger,
                         user_instruction: Optional[str] = None) -> str:
    """Stable system prompt -- identical across reflections/rounds so the
    provider's context cache can hit on it. The ledger is per-job stable."""
    instruction_block = ""
    if user_instruction:
        instruction_block = (
            "PRIORITY USER FEEDBACK: The user reviewed their resume and is not happy. "
            f"They asked you to fix the following: {user_instruction}\n"
            "Address ONLY what was flagged using the available tools. Do not re-run a full "
            "optimization or change sections the user did not mention.\n\n"
        )

    return f"""{instruction_block}You are a Resume Optimization Strategist. Present this candidate's
VERIFIED experience as strongly and as relevantly to the target job as possible.

VERIFIED FACTS -- the only claims this resume may make:
{ledger.prompt_block()}

AVAILABLE RESUME SECTIONS: {', '.join(available_sections)}

HARD RULES:
- Never add a skill, tool, technology, job title, seniority claim, or number that is not
  in the VERIFIED FACTS above or already present in the resume text.
- Tools refuse unevidenced items and record them as honest gaps for the user's gap
  report. Do not retry a refused item; move on.
- If a score cannot reach target truthfully, leave it -- honest gaps are a product
  feature, not a failure.

Work only on items marked "addable" and on presentation fixes (bullet strength, bullet
ordering, JD tailoring of existing content). When no truthful work remains, output a
one-line summary and stop calling tools."""
```

Replace `_build_scores_context` (and add `_dimension_work` + `_flag_for` above it):

```python
def _dimension_work(scores: dict, capabilities: frozenset) -> dict:
    """Per-dimension score + what is truthfully actionable (spec 2b/2c)."""
    ats    = scores.get("ats", {}) or {}
    impact = scores.get("impact", {}) or {}
    skills = scores.get("skills_gap", {}) or {}
    tailor = scores.get("jd_tailoring", {}) or {}

    def _s(d: dict) -> int:
        v = d.get("score", 0)
        return v if isinstance(v, (int, float)) else 0

    kw_add, kw_gaps = split_evidenced(ats.get("missing_keywords", [])[:15], capabilities)
    sk_add, sk_gaps = split_evidenced(skills.get("missing_skills", [])[:15], capabilities)
    weak   = impact.get("weak_bullets", [])[:8]
    issues = tailor.get("issues", [])[:3]
    return {
        "ats":          {"score": _s(ats),    "actionable": bool(kw_add), "addable": kw_add, "gaps": kw_gaps},
        "impact":       {"score": _s(impact), "actionable": bool(weak),   "items": weak},
        "skills_gap":   {"score": _s(skills), "actionable": bool(sk_add), "addable": sk_add, "gaps": sk_gaps},
        "jd_tailoring": {"score": _s(tailor), "actionable": bool(issues), "items": issues},
    }


def _flag_for(entry: dict) -> str:
    if entry["score"] >= SCORE_TARGET:
        return "ok"
    return "NEEDS WORK" if entry["actionable"] else "capped (honest ceiling)"


def _build_scores_context(scores: dict, capabilities: frozenset,
                          heading: str = "CURRENT SCORES (baseline)") -> str:
    """Volatile scores block -- a user message so the system prompt stays cacheable.

    Missing items are split against the capabilities allowlist: only evidenced
    items are presented as work; the rest are explicitly off-limits gaps.
    Readability is omitted -- the post-loop humanize stage owns it."""
    w = _dimension_work(scores, capabilities)
    return f"""{heading}:
  ATS Match:    {w['ats']['score']:>3}  [{_flag_for(w['ats'])}]
    addable keywords (evidenced): {', '.join(w['ats']['addable'])}
    gaps (no evidence -- DO NOT add; reported to user): {', '.join(w['ats']['gaps'])}
  Impact:       {w['impact']['score']:>3}  [{_flag_for(w['impact'])}]
    weak_bullets: {', '.join(w['impact']['items'])}
  Skills Gap:   {w['skills_gap']['score']:>3}  [{_flag_for(w['skills_gap'])}]
    addable skills (evidenced): {', '.join(w['skills_gap']['addable'])}
    gaps (no evidence -- DO NOT add): {', '.join(w['skills_gap']['gaps'])}
  JD Tailoring: {w['jd_tailoring']['score']:>3}  [{_flag_for(w['jd_tailoring'])}]
    issues: {', '.join(w['jd_tailoring']['items'])}

Do the addable and presentation work above. Items listed as gaps are off-limits."""
```

Update `_build_system` (backward-compat wrapper):

```python
def _build_system(scores: dict, available_sections: list, ledger,
                  user_instruction: Optional[str] = None) -> str:
    """Full system prompt (backward-compat wrapper)."""
    return (_build_system_stable(available_sections, ledger, user_instruction)
            + "\n\n" + _build_scores_context(scores, ledger.capabilities))
```

In `run_agent`, update the initial messages:

```python
    messages: list[dict] = [
        {"role": "system",
         "content": _build_system_stable(state.available_sections(), ledger, user_instruction)},
        {"role": "user",
         "content": _build_scores_context(scores, state.capabilities)},
    ]
```

In `orchestration/debate_loop.py`, update the two call sites:
`stable_system = _build_system_stable(state.available_sections(), ledger)` and
`{"role": "user", "content": _build_scores_context(current_scores, state.capabilities)}`.
Also update the reflection-feedback call in `run_agent` (line ~404) to
`_build_scores_context(current_scores, state.capabilities)` so the module still imports
and runs — the reflection heading itself changes in Task 6.

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_truthful_prompts.py tests/test_agent_loop.py tests/test_debate_loop.py tests/test_agent_improvements.py -q`
If any existing test asserts old prompt fragments (e.g. "raise all resume scores"), update its expectation to the new text from this task.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestration/agent_loop.py orchestration/debate_loop.py tests/test_truthful_prompts.py tests/
git commit -m "feat: truthful strategist objective + evidence-split scores context"
```

---

### Task 6: Stop condition + honest_gaps in run_agent

**Files:**
- Modify: `orchestration/agent_loop.py` (`run_agent` reflection block)
- Test: `tests/test_agent_loop.py` (append)

**Interfaces:**
- Consumes: `_dimension_work` (Task 5), `ResumeState.add_gaps/honest_gaps` (Task 2).
- Produces: `run_agent(...)` result dict gains `"honest_gaps": list[str]`. Reflection feedback heading `UPDATED SCORES (reflection N)`. Done-check: every dimension `score >= SCORE_TARGET or not actionable`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_agent_loop.py` (reuse that file's existing fake-message helpers for `complete_with_tools`; the test below builds its own minimal ones if none fit):

```python
async def test_capped_dimensions_stop_reflections_and_report_gaps(monkeypatch):
    """Below-target but gap-blocked dimensions must end the loop (no treadmill)
    and surface honest_gaps in the result."""
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import agent_loop

    capped_scores = {
        "ats":          {"score": 50, "missing_keywords": ["Kubernetes"]},
        "impact":       {"score": 95, "weak_bullets": []},
        "skills_gap":   {"score": 55, "missing_skills": ["Terraform"]},
        "readability":  {"score": 60},
        "jd_tailoring": {"score": 95, "issues": []},
        "overall": 70,
    }
    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "Did python things."},
                        capabilities=ledger.capabilities)

    calls = {"llm": 0, "score": 0}

    class _Msg:
        content = "done"
        tool_calls = None

    async def fake_cwt(messages, model, tools, **kw):
        calls["llm"] += 1
        return {"message": _Msg(), "input_tokens": 10, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    async def fake_score(*a, **kw):
        calls["score"] += 1
        return {"text": capped_scores, "tokens": {"input_tokens": 0, "output_tokens": 0},
                "cost_usd": 0.0}

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(agent_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(agent_loop, "score_combined", fake_score)
    monkeypatch.setattr(agent_loop, "fabrication_guard", fake_guard)

    result = await agent_loop.run_agent(
        state=state, scores=capped_scores, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="Did python things.",
    )
    # one strategist turn, then loop ends: ats/skills below target but capped
    assert calls["llm"] == 1
    assert result["honest_gaps"] == ["Kubernetes", "Terraform"]
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_loop.py::test_capped_dimensions_stop_reflections_and_report_gaps -q`
Expected: FAIL — `KeyError: 'honest_gaps'` or `calls["llm"] == 3`.

- [ ] **Step 3: Implement** in `run_agent`'s reflection block.

Replace the `overall`/`_agent_dims`/`all_above` block with:

```python
        overall = current_scores.get("overall", 0)
        # Truthful done-check (spec 2c): a dimension is satisfied when it meets
        # target OR nothing truthfully actionable remains ("capped"). Readability
        # is excluded -- the post-loop humanize stage owns it.
        work = _dimension_work(current_scores, state.capabilities)
        for entry in work.values():
            state.add_gaps(entry.get("gaps", []))
        all_done = all(
            e["score"] >= SCORE_TARGET or not e["actionable"] for e in work.values()
        )
```

Rename the uses: `if all_above and ...` → `if all_done and ...`; update the `_logger.info`
line to log `all_done=%s`. Remove the now-unused `SCORE_DIMENSIONS` from the config
import if nothing else in the module uses it.

Update the reflection feedback (inside `if reflection_idx < reflections_cap - 1:`):

```python
            feedback_parts: list[str] = [
                _build_scores_context(
                    current_scores, state.capabilities,
                    heading=f"UPDATED SCORES (reflection {reflection_idx + 1})",
                )
            ]
```

Add to the returned dict:

```python
        "honest_gaps":   state.honest_gaps(),
```

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_agent_loop.py tests/test_truthful_prompts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestration/agent_loop.py tests/test_agent_loop.py
git commit -m "feat: gap-aware stop condition; run_agent returns honest_gaps"
```

---

### Task 7: Truthful fallback rewriter

**Files:**
- Modify: `agents/rewriter.py`
- Modify: `orchestration/optimizer.py` (`_deterministic_fallback` passes capabilities, surfaces gaps)
- Test: `tests/test_truthful_prompts.py` (append)

**Interfaces:**
- Consumes: `split_evidenced` (Task 3), `ClaimsLedger.capabilities` (Task 1).
- Produces: `rewrite_resume(...)` result dict gains `"gaps": list[str]`; its prompt contains `TRUTHFUL KEYWORD ALIGNMENT` and never contains unevidenced keywords. `_deterministic_fallback(...)` result gains `"honest_gaps": list[str]`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_truthful_prompts.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_truthful_prompts.py::test_rewriter_filters_keywords_and_reports_gaps -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`agents/rewriter.py`: add `from agents.tools import split_evidenced` to imports. At the
top of `rewrite_resume`, replace the `keywords_str` line with:

```python
    gaps: list[str] = []
    if claims_ledger is not None and getattr(claims_ledger, "capabilities", None):
        evidenced, gaps = split_evidenced(jd_keywords or [], claims_ledger.capabilities)
    else:
        evidenced = list(jd_keywords or [])
    keywords_str = ", ".join(evidenced[:40]) if evidenced else "None provided"
```

Replace PRIORITY 1 in the system text (verbatim spec 3f):

```
PRIORITY 1 -- TRUTHFUL KEYWORD ALIGNMENT
  Weave the VERIFIED keywords below into existing bullets and summary. Every keyword
  listed is evidenced by the resume itself; skip any keyword that would require claiming
  a new duty, tool, or role. Never add content solely to host a keyword.
```

Also update the SELF-CHECK line to `confirm all VERIFIED keywords appear where truthful` (it
currently demands "all required keywords appear ... all bullets have metrics" — change to
`confirm the VERIFIED keywords appear where truthful, no new facts were added,`).
Add `"gaps": gaps,` to the returned dict.

`orchestration/optimizer.py` `_deterministic_fallback` return gains:

```python
        "honest_gaps":   result.get("gaps", []),
```

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_truthful_prompts.py tests/test_agents.py tests/test_optimizer_improvements.py -q`
Update any existing rewriter-prompt assertions ("KEYWORD SATURATION") to the new text.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/rewriter.py orchestration/optimizer.py tests/
git commit -m "feat: fallback rewriter aligns only evidenced keywords, reports gaps"
```

---

### Task 8: Debate loop — presentation-only reviewer, final-round skip, gaps

**Files:**
- Modify: `orchestration/debate_loop.py`
- Test: `tests/test_debate_loop.py` (append/update)

**Interfaces:**
- Consumes: `_build_scores_context(scores, capabilities, heading=...)` (Task 5), `state.honest_gaps()` (Task 2).
- Produces: `run_debate(...)` result gains `"honest_gaps": list[str]`; on the final round (`round_idx == DEBATE_MAX_ROUNDS - 1`) neither `score_combined` nor the reviewer `complete` is called.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_debate_loop.py` (reuse the file's existing fakes for `complete_with_tools`; pattern below):

```python
async def test_final_round_skips_rescore_and_reviewer(monkeypatch):
    """Round DEBATE_MAX_ROUNDS-1: objection would be discarded, so neither the
    re-score nor the reviewer call may fire (spec 5b)."""
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import debate_loop

    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "python work"},
                        capabilities=ledger.capabilities)
    counts = {"reviewer": 0, "score": 0, "opt": 0}

    class _ToolCall:
        id = "t1"
        class function:  # noqa: N801 - mimic litellm shape
            name = "bullet_strengthen"
            arguments = '{"weak_bullets_csv": "python work"}'

    class _MsgTools:
        content = ""
        tool_calls = [_ToolCall()]

    class _MsgDone:
        content = "done"
        tool_calls = None

    msgs = [_MsgTools(), _MsgDone(), _MsgTools(), _MsgDone()]

    async def fake_cwt(messages, model, tools, **kw):
        counts["opt"] += 1
        return {"message": msgs.pop(0), "input_tokens": 5, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    async def fake_reviewer(prompt, model, **kw):
        counts["reviewer"] += 1
        return {"text": "OBJECTION: reorder the experience bullets",
                "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    async def fake_score(*a, **kw):
        counts["score"] += 1
        return {"text": {"overall": 70}, "tokens": {"input_tokens": 0, "output_tokens": 0},
                "cost_usd": 0.0}

    async def fake_tool(state_, **kw):
        state_.update_section("experience", "stronger python work " * counts["opt"])
        return "ok"

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(debate_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(debate_loop, "complete", fake_reviewer)
    monkeypatch.setattr(debate_loop, "score_combined", fake_score)
    monkeypatch.setattr(debate_loop, "fabrication_guard", fake_guard)
    monkeypatch.setattr(debate_loop, "TOOL_MAP", {"bullet_strengthen": fake_tool})

    result = await debate_loop.run_debate(
        state=state, scores={"overall": 60}, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="python work",
    )
    assert counts["reviewer"] == 1          # round 1 only; final round skipped
    assert counts["score"] == 1             # ditto
    assert "honest_gaps" in result


async def test_reviewer_prompt_is_presentation_only(monkeypatch):
    from agents.fact_extractor import ClaimsLedger
    from agents.tools import ResumeState
    from orchestration import debate_loop

    ledger = ClaimsLedger(companies=frozenset(), metrics=frozenset(),
                          raw_bullets=(), capabilities=frozenset({"python"}))
    state = ResumeState(sections={"experience": "python work"},
                        capabilities=ledger.capabilities)
    state.add_gaps(["Kubernetes"])
    captured = {}

    class _ToolCall:
        id = "t1"
        class function:  # noqa: N801
            name = "bullet_strengthen"
            arguments = '{"weak_bullets_csv": "python work"}'

    class _MsgTools:
        content = ""
        tool_calls = [_ToolCall()]

    class _MsgDone:
        content = "done"
        tool_calls = None

    msgs = [_MsgTools(), _MsgDone()]

    async def fake_cwt(messages, model, tools, **kw):
        return {"message": msgs.pop(0), "input_tokens": 5, "output_tokens": 5,
                "cost_usd": 0.0, "cached_input_tokens": 0}

    async def fake_reviewer(prompt, model, **kw):
        captured["prompt"] = prompt
        return {"text": "No objections.", "input_tokens": 1, "output_tokens": 1,
                "cost_usd": 0.0}

    async def fake_score(*a, **kw):
        return {"text": {"overall": 70, "ats": {"score": 70}},
                "tokens": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0.0}

    async def fake_tool(state_, **kw):
        state_.update_section("experience", "stronger python work")
        return "ok"

    def fake_guard(text, ledger_, original):
        return type("_G", (), {"gaps": [], "text": text})()

    monkeypatch.setattr(debate_loop, "complete_with_tools", fake_cwt)
    monkeypatch.setattr(debate_loop, "complete", fake_reviewer)
    monkeypatch.setattr(debate_loop, "score_combined", fake_score)
    monkeypatch.setattr(debate_loop, "fabrication_guard", fake_guard)
    monkeypatch.setattr(debate_loop, "TOOL_MAP", {"bullet_strengthen": fake_tool})

    await debate_loop.run_debate(
        state=state, scores={"overall": 60}, jd_text="jd", jd_keywords=[],
        ledger=ledger, original_resume="python work",
    )
    p = captured["prompt"]
    assert "PRESENTATION" in p
    assert "HONEST GAPS" in p and "Kubernetes" in p
    assert "CURRENT SCORES" in p or "UPDATED SCORES" in p
    assert "Do NOT raise objections about: missing skills" in p
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_debate_loop.py -q`
Expected: FAIL — reviewer called twice / `KeyError: 'honest_gaps'` / prompt asserts.

- [ ] **Step 3: Implement** in `orchestration/debate_loop.py`.

Immediately after the `if round_tool_calls == 0:` break block, insert:

```python
        # Final round: a re-score would only feed a reviewer whose objection can
        # never be acted on -- skip both (spec 5b; measured ~11% of pro-job cost).
        if round_idx >= DEBATE_MAX_ROUNDS - 1:
            _logger.info("debate_loop: final round %d complete -- skipping re-score and reviewer", round_idx + 1)
            break
```

(Then delete the old trailing `if round_idx >= DEBATE_MAX_ROUNDS - 1:` log block at the
bottom of the loop.)

Replace `reviewer_prompt` with:

```python
        reviewer_prompt = (
            "You are a skeptical resume reviewer. The optimizer revised this resume and can run more\n"
            "tools, but it can only make PRESENTATION fixes to existing, verified content:\n"
            "  - keyword_inject: weave pre-verified keywords into existing sentences\n"
            "  - bullet_strengthen: stronger verbs on existing bullets\n"
            "  - skills_rewrite: sync the skills section with skills evidenced elsewhere in the resume\n"
            "  - bullets_reorder: reorder existing bullets by JD relevance\n\n"
            f"{_build_scores_context(current_scores, state.capabilities)}\n\n"
            "HONEST GAPS already identified (impossible to fix truthfully -- do NOT raise these):\n"
            f"{', '.join(state.honest_gaps()) or 'none'}\n\n"
            f"CURRENT RESUME DRAFT:\n{draft}\n\n"
            "Raise ONE objection that is fixable purely by presentation changes to existing content.\n"
            "Do NOT raise objections about: missing skills, keywords, metrics, certifications, or\n"
            "experience the resume does not contain; tone or wording (a humanize stage follows);\n"
            "employment gaps or dates.\n"
            "If you have no fixable objection, respond EXACTLY: No objections.\n"
            "Otherwise respond EXACTLY: OBJECTION: <one presentation issue, 20 words or less>"
        )
```

Add `"honest_gaps": state.honest_gaps(),` to the returned dict.

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_debate_loop.py tests/test_tier_gating.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestration/debate_loop.py tests/test_debate_loop.py
git commit -m "feat: presentation-only reviewer with gaps context; skip discarded final-round calls"
```

---

### Task 9: Guard — capability check, substitute-or-drop, no [VERIFY]

**Files:**
- Modify: `agents/fabrication_guard.py`
- Modify: `tests/test_agents.py` (~lines 149-164), `tests/test_claims_improvements.py` (~lines 55-65) — both assert the old `[VERIFY]` behavior
- Test: `tests/test_fabrication_guard_capabilities.py` (create)

**Interfaces:**
- Consumes: `taxonomy_terms()` (Task 1), `ClaimsLedger.capabilities` (Task 1).
- Produces: `GuardResult` gains `capability_gaps: List[str]` (sorted, deduped taxonomy terms). Guard output text NEVER contains `[VERIFY]`; offending lines are replaced with the closest original bullet (difflib ratio > 0.35, not already present in output) or dropped.

- [ ] **Step 1: Write the failing tests** — create `tests/test_fabrication_guard_capabilities.py`:

```python
"""Guard capability check + substitute-or-drop semantics (spec 4b)."""

from agents.fabrication_guard import fabrication_guard
from agents.fact_extractor import extract_claims

SOURCE = """Summary
Software engineer building web apps.

Experience
- Built REST APIs for the portal in Python
- Worked on the PostgreSQL database

Skills
Python, PostgreSQL, Git
"""


def test_unevidenced_capability_line_is_replaced_or_dropped():
    ledger = extract_claims(SOURCE)
    generated = SOURCE.replace(
        "- Built REST APIs for the portal in Python",
        "- Deployed microservices with Kubernetes and Terraform",
    )
    result = fabrication_guard(generated, ledger, SOURCE)
    assert "[VERIFY]" not in result.text
    assert "kubernetes" not in result.text.lower()
    assert "terraform" not in result.text.lower()
    assert set(result.capability_gaps) == {"kubernetes", "terraform"}
    assert result.gaps  # recorded for the report


def test_evidenced_capabilities_pass_untouched():
    ledger = extract_claims(SOURCE)
    result = fabrication_guard(SOURCE, ledger, SOURCE)
    assert result.text == SOURCE
    assert result.capability_gaps == []


def test_metric_fabrication_no_longer_emits_verify_marker():
    ledger = extract_claims(SOURCE)
    generated = SOURCE.replace(
        "- Worked on the PostgreSQL database",
        "- Improved PostgreSQL throughput by 300%",
    )
    result = fabrication_guard(generated, ledger, SOURCE)
    assert "[VERIFY]" not in result.text
    assert "300%" not in result.text
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_fabrication_guard_capabilities.py -q`
Expected: FAIL — `AttributeError: capability_gaps` / `[VERIFY]` present.

- [ ] **Step 3: Implement** in `agents/fabrication_guard.py`.

Imports: add `from utils.skills_normalizer import taxonomy_terms`. Module level:

```python
# Precompiled taxonomy patterns for the capability novelty check. Custom
# boundaries keep "c++"/"c#" intact and stop "go" matching inside "Django".
_TAXONOMY_PATTERNS = {
    t: re.compile(r"(?<![\w+#])" + re.escape(t) + r"(?![\w+#])")
    for t in taxonomy_terms()
}


def _taxonomy_terms_in(text_lower: str) -> set:
    return {t for t, p in _TAXONOMY_PATTERNS.items() if p.search(text_lower)}
```

`GuardResult` gains a fourth field (add `field` to the existing `dataclasses` import):

```python
    capability_gaps: List[str] = field(default_factory=list)  # unevidenced tech terms found in output
```

In `fabrication_guard()`, after `allowed_persona = ...`:

```python
    # Capabilities the output may legitimately mention: the ledger's evidenced
    # set plus any taxonomy term already present in the source text.
    allowed_caps = set(ledger.capabilities) | _taxonomy_terms_in(source_text.lower())
    capability_gaps: set = set()
```

Replace the `if bad_metrics or bad_companies:` block (the `[VERIFY]` branch) with:

```python
        bad_caps = sorted(_taxonomy_terms_in(line.lower()) - allowed_caps)

        if bad_metrics or bad_companies or bad_caps:
            stripped.extend(bad_metrics)
            stripped.extend(bad_companies)
            stripped.extend(bad_caps)
            capability_gaps.update(bad_caps)

            # Substitute the closest original bullet, else drop the line.
            # No [VERIFY] markers: nothing unverifiable is ever kept (spec 4b).
            m = _BULLET_STRIP_RE.match(line)
            prefix = m.group(0) if m else ""
            best = _closest_original(bare, ledger.raw_bullets)
            if best and best not in "\n".join(output_lines):
                output_lines.append(f"{prefix}{best}")
                gaps.append(f"unverified claim replaced with original: {bare[:80]!r}")
            else:
                gaps.append(f"unverified claim dropped: {bare[:80]!r}")
        else:
            output_lines.append(line)
```

Return `capability_gaps=sorted(capability_gaps)` in the `GuardResult`. Update the module
docstring bullet "b)" to describe substitute-or-drop (no marker).

- [ ] **Step 4: Update the two old-behavior tests, run everything**

- `tests/test_agents.py` (~149-164): change `assert "[VERIFY]" in result.text` to
  `assert "[VERIFY]" not in result.text` and assert the fabricated metric is absent from
  `result.text` while still present in `result.stripped`.
- `tests/test_claims_improvements.py` (~55-65): this is a source-grep test demanding the
  `[VERIFY]` tag. Rewrite it to assert the new contract on the source:
  `assert "[VERIFY]" not in source` and `assert "_closest_original" in source`.

Run: `../.venv/Scripts/python.exe -m pytest tests/test_fabrication_guard_capabilities.py tests/test_agents.py tests/test_claims_improvements.py tests/test_fabrication_guard_blankline.py tests/test_field_agnostic.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/fabrication_guard.py tests/
git commit -m "feat: guard catches unevidenced capabilities; substitute-or-drop replaces [VERIFY] markers"
```

---

### Task 10: Humanizer truth rules

**Files:**
- Modify: `agents/humanizer.py`
- Test: `tests/test_humanizer_improvements.py` (append)

**Interfaces:**
- Consumes: nothing new (guard-after-humanize lands in Task 12).
- Produces: step-1 system with evidence-scoped ownership rule; critic call passes `response_format={"type": "json_object"}`; step-3 prompt carries the no-new-claims rule.

- [ ] **Step 1: Write the failing test** — append to `tests/test_humanizer_improvements.py`:

```python
async def test_humanizer_prompts_forbid_new_claims_and_scope_ownership(monkeypatch):
    import agents.humanizer as humanizer

    prompts, kwargs_seen = [], []

    async def fake_complete(prompt, model, **kw):
        prompts.append(prompt)
        kwargs_seen.append(kw)
        if len(prompts) == 2:  # critic step
            return {"text": '{"robotic_phrases": ["responsible for"]}',
                    "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}
        return {"text": "polished resume", "input_tokens": 1, "output_tokens": 1,
                "cost_usd": 0.0}

    monkeypatch.setattr(humanizer, "complete", fake_complete)
    await humanizer.humanize_resume("Some resume text.", industry="saas",
                                    seniority_level="mid")

    step1, step3 = prompts[0], prompts[2]
    assert "ONLY where the surrounding text shows the candidate owned that work" in step1
    assert "Do NOT add any new skill, tool, technology, metric, or achievement" in step1
    assert "Do NOT change job titles or seniority wording" in step1
    assert kwargs_seen[1].get("response_format") == {"type": "json_object"}
    assert "Do NOT add any new skill, tool, technology, metric, or achievement" in step3
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_humanizer_improvements.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** in `agents/humanizer.py`.

Replace dimension 2 in `step1_system` and extend the constraint block (spec 5a):

```python
    step1_system = f"""You are a professional resume writer.{industry_note}{seniority_note}

Improve the resume text on exactly THREE dimensions:
1. Voice variety -- vary sentence openings; avoid starting consecutive bullets with the same verb
2. Confident assertions -- replace hedges ("helped with", "assisted in") with direct
   ownership ("led", "built", "delivered") ONLY where the surrounding text shows the
   candidate owned that work. If ownership is not evidenced, keep the honest scope
   ("contributed to", "supported") and strengthen the verb within that scope.
3. Industry tone -- use vocabulary natural to the target industry; avoid generic filler phrases

Preserve every metric, company name, job title, and date exactly as written -- never invent,
inflate, or alter a number, and never insert a placeholder like "[XX%]".
Do NOT add any new skill, tool, technology, metric, or achievement. Do NOT change job
titles or seniority wording anywhere, including the summary.
Plain text ONLY: no markdown and NO LaTeX or "$" math wrappers. Write figures plainly
("100M+ events/day", "$500K") -- never "$(100M+events/day$".
Return ONLY the improved resume text. No commentary."""
```

Critic call (step 2): change to
`response = await complete(f"""{step2_system} ...""", MODEL_CRITIC, response_format={"type": "json_object"})`
(same prompt text, one added kwarg).

Step 3 prompt: replace the line `- Do NOT add new metrics, numbers, achievements, or facts that aren't already in the resume` with:

```
- Do NOT add any new skill, tool, technology, metric, or achievement. Do NOT change job
  titles or seniority wording.
```

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_humanizer_improvements.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/humanizer.py tests/test_humanizer_improvements.py
git commit -m "feat: humanizer evidence-scoped ownership + structured critic JSON"
```

---

### Task 11: Verifier hardening

**Files:**
- Modify: `agents/verifier.py`
- Modify: `orchestration/optimizer.py` (`_with_verifier` passes `original_resume` — temporary until Task 12)
- Test: `tests/test_verifier.py` (update line ~74 + add)

**Interfaces:**
- Consumes: nothing new.
- Produces: `verify_final_draft(draft: str, ledger: ClaimsLedger, original_resume: str) -> VerifierResult` (parameter REQUIRED); prompt contains the original resume and caps flags at 10.

- [ ] **Step 1: Write the failing tests** — in `tests/test_verifier.py`, update the existing call at line ~74 to `verify_final_draft(SAMPLE_DRAFT, ledger, SAMPLE_DRAFT)` (search the file for every `verify_final_draft(` call and add the third argument). Append:

```python
async def test_verifier_prompt_includes_original_and_flag_rules(monkeypatch):
    import agents.verifier as verifier
    from agents.fact_extractor import ClaimsLedger

    captured = {}

    async def fake_complete(prompt, model, **kw):
        captured["prompt"] = prompt
        return {"text": "VERIFIED", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

    monkeypatch.setattr(verifier, "complete", fake_complete)
    ledger = ClaimsLedger(companies=frozenset({"Acme"}), metrics=frozenset({"40%"}),
                          raw_bullets=())
    result = await verifier.verify_final_draft(
        "Reduced load time by 40% at Acme.", ledger,
        original_resume="Original: reduced page load time by 40% at Acme.",
    )
    p = captured["prompt"]
    assert "ORIGINAL RESUME (ground truth):" in p
    assert "reduced page load time by 40%" in p
    assert "Do not flag rephrasings of supported claims" in p
    assert "At most 10 flags" in p
    assert result.flagged == []
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_verifier.py -q`
Expected: FAIL — `TypeError` (missing arg) then prompt asserts.

- [ ] **Step 3: Implement**

`agents/verifier.py` — new signature `async def verify_final_draft(draft: str, ledger: ClaimsLedger, original_resume: str) -> VerifierResult:` and prompt (spec 5c):

```python
    prompt = f"""You are a resume verification assistant. Check this resume draft for unsupported claims.

ORIGINAL RESUME (ground truth):
{original_resume}

VERIFIED FACTS FROM ORIGINAL RESUME:
- Companies: {companies_str}
- Metrics: {metrics_str}
- Job Titles: {titles_str}
- Degrees: {degrees_str}

RESUME DRAFT:
{draft}

Flag ONLY concrete claims -- a skill, tool, title, company, degree, or number -- that
appear in the draft but have no support in the original resume or verified facts above.
Do not flag rephrasings of supported claims. At most 10 flags.
Output format: one unsupported claim per line, or "VERIFIED" if clean. No prose."""
```

Cap the parsed list: `flagged = flagged[:10]` after the splitlines parse.

`orchestration/optimizer.py`: change `_with_verifier(pipeline_result: dict, ledger: ClaimsLedger, original_resume: str)` and its `vr = await verify_final_draft(draft, ledger, original_resume)`; update all three call sites in `run_optimization_async` to pass `resume_text`.

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_verifier.py tests/test_tier_gating.py -q`
Expected: PASS (tier-gating mocks are signature-agnostic `AsyncMock`s).

- [ ] **Step 5: Commit**

```bash
git add agents/verifier.py orchestration/optimizer.py tests/test_verifier.py
git commit -m "feat: verifier sees original resume; bounded, rephrasing-tolerant flags"
```

---

### Task 12: Pipeline reorder + gaps plumbing (main.py, optimizer.py, handoff.py, report)

**Files:**
- Modify: `orchestration/optimizer.py` (thread capabilities; remove `_with_verifier`; pass through `honest_gaps`)
- Modify: `main.py` (`_run_pipeline_task` tail: humanize → normalize → sanitize → guard → verifier → final score; call kinds; gaps into report/`last_result`)
- Modify: `utils/optimization_report.py` (`build_report` gains `honest_gaps` param)
- Modify: `chat/handoff.py` (`apply_edit`: capabilities, guard+verifier tail)
- Modify: `tests/test_tier_gating.py` (verifier no longer inside optimizer)
- Test: `tests/test_pipeline_order.py` (create), `tests/test_pr7_edit_resume.py` (update)

**Interfaces:**
- Consumes: everything above.
- Produces: `run_optimization_async` result: `{"text", "input_tokens", "output_tokens", "cost_usd", "iterations", "fallback", "honest_gaps"}` — NO `verifier_flagged` (main.py owns the verifier now). `build_report(..., honest_gaps: list | None = None)` returns report with `"gaps_for_jd": list`. `apply_edit` return dict gains `"honest_gaps"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_order.py` (source-order assertions — same style as this
repo's existing source-grep tests — plus the report contract):

```python
"""Delivered-text ordering contract (spec 4a): humanize -> normalize -> sanitize
-> guard -> verifier -> final score. Asserted on main.py source order, matching
the repo's existing source-grep test style for pipeline invariants."""

from pathlib import Path

SRC = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")


def _pos(needle: str) -> int:
    idx = SRC.find(needle)
    assert idx != -1, f"main.py no longer contains {needle!r}"
    return idx


def test_tail_order_humanize_guard_verifier_score():
    humanize = _pos("humanize_resume(")
    guard    = _pos("guard_result = await asyncio.to_thread(fabrication_guard")
    verifier = _pos("verify_final_draft(")
    final    = _pos('set_call_kind("final_scoring")')
    assert humanize < guard < verifier < final


def test_call_kinds_set_for_humanize_and_verifier():
    assert 'set_call_kind("humanize")' in SRC
    assert 'set_call_kind("verifier")' in SRC


def test_optimizer_no_longer_owns_verifier():
    opt_src = (Path(__file__).parent.parent / "orchestration" / "optimizer.py").read_text(encoding="utf-8")
    assert "_with_verifier" not in opt_src
    assert "verify_final_draft" not in opt_src


def test_report_carries_honest_gaps():
    from utils.optimization_report import build_report

    report = build_report(
        jd_result={}, original_text="a", optimized_text="b",
        baseline_score=50, final_scores={"average": 80}, iterations=1,
        honest_gaps=["Kubernetes"],
    )
    assert report["gaps_for_jd"] == ["Kubernetes"]
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_pipeline_order.py -q`
Expected: FAIL on all four.

- [ ] **Step 3: Implement**

**`utils/optimization_report.py`** — signature `def build_report(jd_result, original_text, optimized_text, baseline_score, final_scores, iterations, honest_gaps=None) -> dict:` and add `"gaps_for_jd": list(honest_gaps or []),` to the returned dict.

**`orchestration/optimizer.py`**:
- `state = ResumeState(sections=sections, available_metrics=available_metrics, capabilities=claims_ledger.capabilities)`
- Delete `_with_verifier` and the `verify_final_draft` import; every
  `return await _with_verifier(pipeline_result, claims_ledger, resume_text)` becomes
  `return pipeline_result`.
- Fallback paths already carry `honest_gaps` (Task 7). Agent path: add
  `"honest_gaps": result.get("honest_gaps", []),` to `pipeline_result`.
- Update `run_optimization_async` docstring return line to
  `{"text", "input_tokens", "output_tokens", "cost_usd", "iterations", "fallback", "honest_gaps"}`.

**`main.py`** — replace the block from `verifier_flagged = agent_result.get(...)` (line
~1043) through the humanize/normalize/sanitize stages (through line ~1150) so the tail
reads (kept OUTSIDE the `if baseline_avg < SCORE_TARGET:` gate so skip-path jobs get the
same delivered-text treatment; `agent_honest_gaps = []` initialised next to `_iter = 0`,
set to `agent_result.get("honest_gaps", [])` in the optimize branch, and the
`final score` block that previously lived inside the gate is deleted from there):

```python
        # ── Humanize (spec 4a: runs BEFORE guard/verifier/score so the delivered
        # text is the checked and scored text) ─────────────────────────────────
        set_call_kind("humanize")
        await emit({"type": "stage", "message": "Humanizing resume language...", "stage": "humanize"})
        try:
            humanize_result = await humanize_resume(
                current_resume,
                industry=industry,
                seniority_level=seniority_level,
            )
            current_resume = humanize_result.get("text", current_resume)
            humanize_tokens = humanize_result.get("tokens", {"input_tokens": 0, "output_tokens": 0})
            total_input_tokens  += humanize_tokens["input_tokens"]
            total_output_tokens += humanize_tokens["output_tokens"]
            total_cost_usd      += humanize_result.get("cost_usd", 0.0)
        except Exception:
            _logger.exception("job=%s: humanize_resume failed -- skipping humanization", job_id)

        # ── Normalize skills + sanitize (unchanged bodies, moved before guard) ──
        # MOVE, do not retype: the existing "Normalize skills section" try/except
        # block (main.py ~1102-1142, starts "from utils.skills_normalizer import
        # categorize_skills") and the existing text-sanitizer try/except block
        # (main.py ~1144-1150, starts "from utils.text_sanitizer import
        # sanitize_resume_text") go here verbatim, in that order.

        # ── Fabrication guard on the DELIVERED text (capability-aware) ─────────
        guard_result = await asyncio.to_thread(fabrication_guard, current_resume, ledger, resume_text)
        if guard_result.gaps:
            _logger.warning(
                "fabrication_guard flagged %d unverified claims for job %s",
                len(guard_result.gaps), job_id,
            )
        current_resume = guard_result.text

        # ── Verifier on the delivered text ──────────────────────────────────────
        set_call_kind("verifier")
        vr = await verify_final_draft(current_resume, ledger, resume_text)
        verifier_flagged = vr.flagged
        total_input_tokens  += vr.input_tokens
        total_output_tokens += vr.output_tokens
        total_cost_usd      += vr.cost_usd

        # ── Final score on the delivered text ───────────────────────────────────
        set_call_kind("final_scoring")
        final_score_dict = await score_combined(
            current_resume, jd_text,
            jd_keywords=jd_keywords,
            seniority_level=seniority_level,
            required_hard_skills=required_hard_skills,
        )
        current_scores = final_score_dict.get("text", scores)
        final_tokens   = final_score_dict.get("tokens", {"input_tokens": 0, "output_tokens": 0})
        total_input_tokens  += final_tokens["input_tokens"]
        total_output_tokens += final_tokens["output_tokens"]
        total_cost_usd      += final_score_dict.get("cost_usd", 0.0)
        current_avg = round(
            sum(current_scores.get(k, {}).get("score", 0) for k in SCORE_DIMENSIONS) / len(SCORE_DIMENSIONS)
        )
        await emit({"type": "average", "score": current_avg, "iteration": max(_iter, 1),
                    "scores": {k: current_scores.get(k, {}).get("score", 0) for k in SCORE_DIMENSIONS},
                    "message": f"Score after optimization: {current_avg}"})
        scores = {**current_scores, "average": current_avg}

        honest_gaps = sorted(set(agent_honest_gaps) | set(guard_result.capability_gaps))
```

Required import in `main.py`: `from agents.verifier import verify_final_draft` (top of
file, next to the other agent imports). Update the `build_report` call (~line 1263) to
pass `honest_gaps=honest_gaps`, and add `"honest_gaps": honest_gaps,` to the
`ctx["last_result"]` dict (~line 1285).

**`chat/handoff.py` `apply_edit`**:
- `state = ResumeState(sections=sections, available_metrics=available_metrics, capabilities=ledger.capabilities)`
- After `edited_text` is validated, replace `verifier_flagged = agent_result.get("flagged", []) or []` with:

```python
    from agents.fabrication_guard import fabrication_guard  # noqa: PLC0415
    from agents.verifier import verify_final_draft  # noqa: PLC0415
    guard = await asyncio.to_thread(fabrication_guard, edited_text, ledger, source_text)
    edited_text = guard.text
    vr = await verify_final_draft(edited_text, ledger, source_text)
    verifier_flagged = vr.flagged
    honest_gaps = sorted(set(agent_result.get("honest_gaps", [])) | set(guard.capability_gaps))
```

(the re-score that follows now scores the guarded text). Add `"honest_gaps": honest_gaps,`
to both the `last_result` update and the returned dict.

**`tests/test_tier_gating.py`**: the four `patch.object(optimizer, "verify_final_draft", ...)`
lines now fail (name gone from optimizer). Change each to patch where it still exists —
`patch("agents.verifier.complete", ...)` is NOT needed; simply delete the verifier
patches and the `mock_verify.assert_called_once()` assertions, replacing them with
`assert "verifier_flagged" not in result` after each `run_optimization_async(...)` call
(the verifier moved to main.py; `tests/test_pipeline_order.py` owns the it-still-runs
guarantee).

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_pipeline_order.py tests/test_tier_gating.py tests/test_pr7_edit_resume.py tests/test_pipeline_integration.py tests/test_optimizer_improvements.py -q`

`apply_edit` imports the guard and verifier INSIDE the function body, so they resolve at
call time from their home modules. In failing `test_pr7_edit_resume.py` tests, patch the
home-module names: `patch("agents.verifier.verify_final_draft", new=AsyncMock(return_value=VerifierResult(text="", flagged=[])))`
(import `VerifierResult` from `agents.verifier`), and let the real fabrication_guard run
— it is pure CPU, deterministic, and safe in tests.
Expected: PASS.

- [ ] **Step 5: Run the FULL suite**

Run: `../.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: everything passes (count >= 464 + new tests). Fix any straggler assertions on
the old order/keys per the patterns above.

- [ ] **Step 6: Commit**

```bash
git add main.py orchestration/optimizer.py chat/handoff.py utils/optimization_report.py tests/
git commit -m "feat: guard/verifier/score run on delivered text; honest-gap report plumbed end to end"
```

---

### Task 13: Scorer + JD analyzer prompt hygiene

**Files:**
- Modify: `agents/scorer.py`, `agents/jd_analyzer.py`
- Test: `tests/test_truthful_prompts.py` (append)

**Interfaces:**
- Consumes/Produces: prompt-only; no signature changes.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_truthful_prompts.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_truthful_prompts.py -q`
Expected: the two new tests FAIL.

- [ ] **Step 3: Implement**

`agents/scorer.py` — in the `system` string, insert before the `Return ONLY a raw JSON object` line:

```
missing_keywords must be concrete skills, tools, or domain terms -- never seniority words
("Senior", "Lead"), role adjectives, or soft phrases.
```

`agents/jd_analyzer.py` — in the `system` string, append to the `Distinguish required vs preferred:` block:

```
required_hard_skills entries must be 1-3 word technologies or competencies, not
requirement sentences ("Kubernetes", not "5+ years of Kubernetes experience").
```

- [ ] **Step 4: Run to verify pass**

Run: `../.venv/Scripts/python.exe -m pytest tests/test_truthful_prompts.py tests/test_jd_analyzer_improvements.py tests/test_agents.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/scorer.py agents/jd_analyzer.py tests/test_truthful_prompts.py
git commit -m "feat: scorer/jd-analyzer emit injectable-safe skill terms only"
```

---

### Task 14: Profiler regression eval + full verification

**Files:**
- Modify: `_try_optimizer.py` (integrity assertions)
- No new tests (this task runs the suites and the live eval)

**Interfaces:**
- Consumes: `taxonomy_terms()` (Task 1), guard/report semantics (Tasks 9, 12).
- Produces: profiler exits non-zero on truthfulness regressions.

- [ ] **Step 1: Add assertions to `_try_optimizer.py`**

The harness's pipeline-mirror must match the new prod order: move its
`fabrication_guard` + verifier phases after the humanize phase and change its
`verify_final_draft` phase-wrapper call to pass `RESUME_TEXT`, mirroring Task 12's
`main.py` tail (the harness file documents itself as a prod mirror; update its
`# mirrors main.py` comments accordingly). Then, before the `out = {...}` dump at the
end of `main()`, add:

```python
    # ── TRUTHFULNESS ASSERTIONS (regression gate; spec Testing section) ──────
    from utils.skills_normalizer import taxonomy_terms
    import re as _re

    failures: list[str] = []
    if "[VERIFY]" in final_text:
        failures.append("[VERIFY] marker leaked into delivered text")
    _allowed = set(ledger.capabilities) | {
        t for t in taxonomy_terms()
        if _re.search(r"(?<![\w+#])" + _re.escape(t) + r"(?![\w+#])", RESUME_TEXT.lower())
    }
    _leaked = sorted(
        t for t in taxonomy_terms()
        if _re.search(r"(?<![\w+#])" + _re.escape(t) + r"(?![\w+#])", final_text.lower())
        and t not in _allowed
    )
    if _leaked:
        failures.append(f"unevidenced capabilities in delivered text: {_leaked}")
    if result.get("honest_gaps") is None:
        failures.append("phase2 result missing honest_gaps")

    print("\n  TRUTHFULNESS ASSERTIONS")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
    else:
        print("  all passed: no markers, no unevidenced capabilities, gaps reported")
```

and after the `print(f"\n  full ledger + texts -> {dump.name}")` line:

```python
    if failures:
        sys.exit(1)
```

Also update the harness's diag-rescore commentary: with the new order the diag re-score
should approximately EQUAL the prod final score (delivered == scored); print the delta as
`consistency check` instead of `delivery drift`.

- [ ] **Step 2: Full unit suite**

Run: `../.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass, 0 failures (count > 464).

- [ ] **Step 3: Live eval (requires .env keys; ~$0.02 total)**

Run: `../.venv/Scripts/python.exe _try_optimizer.py standard max none`
Expected: exits 0; "TRUTHFULNESS ASSERTIONS ... all passed"; `honest_gaps` non-empty
(sample JD demands Kubernetes/Terraform the sample resume lacks); phase rollup shows
`humanize` rows with call_kind `humanize` and a `verifier` row with call_kind `verifier`;
cost within ~2x of the 2026-07-07 baseline ($0.0096).

Run: `../.venv/Scripts/python.exe _try_optimizer.py pro max none`
Expected: exits 0; exactly ONE reviewer call in the ledger (final-round skip); cost <=
baseline ($0.0085).

- [ ] **Step 4: Commit**

```bash
git add _try_optimizer.py
git commit -m "test: profiler enforces truthfulness invariants as a regression gate"
```

---

## Self-review checklist (run after writing, fixed inline)

- Spec coverage: 1→Task 1; 2a/2b→Task 5; 2c→Task 6; 2d→Task 4; 3a/3b/3c/3d→Tasks 2-3; 3f→Task 7; 4a/4c→Task 12; 4b→Task 9; 5a→Task 10; 5b→Task 8; 5c→Task 11; 5d→Task 13; 6→Task 12; Testing→each task + Task 14.
- No placeholders; every code step shows the code.
- Type consistency: `split_evidenced(items, capabilities) -> (list, list)` used in Tasks 3/5/7; `_build_scores_context(scores, capabilities, heading=...)` in Tasks 5/6/8; `verify_final_draft(draft, ledger, original_resume)` in Tasks 11/12/14; `GuardResult.capability_gaps` in Tasks 9/12/14; `honest_gaps` key in Tasks 6/7/8/12/14.

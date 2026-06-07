# Block F — Agent Unit Tests: Design Spec
**Date:** 2026-06-03
**Branch:** backend_design
**Status:** Approved

## Overview

Block F adds unit tests for the two deterministic agents: `extract_claims` and `fabrication_guard`. Both are pure Python + spaCy with no LLM calls, making them ideal for fast, reliable tests. No mocking required. One new file: `tests/test_agents.py`.

## Scope

- `tests/test_agents.py` — 16 synchronous tests (8 per agent)
- No changes to any existing source files

## Out of Scope

- LLM-backed agents (`analyze_jd`, `score_combined`, `rewrite_resume`, `humanize_resume`) — would require mocking; deferred
- Private helper functions (`_normalise_metric`, `_metric_attested`, etc.) — tested implicitly through the public API

---

## Section 1: `extract_claims` tests (8 tests)

All tests call `extract_claims(text: str) -> ClaimsLedger` directly. No fixtures needed — input is an inline string per test.

### Test list

**1. `test_extract_claims_finds_metrics`**
Input: text containing `"30%"`, `"$1.2M"`, `"3x"`.
Assert: all three strings appear in `ledger.metrics`.

**2. `test_extract_claims_ignores_plain_integers`**
Input: text with `"5 engineers"` and `"2 teams"` (no %, $, K/M/B, x-multiplier).
Assert: `ledger.metrics` is empty.

**3. `test_extract_claims_extracts_bullets`**
Input: text with two bullet lines starting with `•`/`-`, both > 15 chars, neither ending with `:`.
Assert: both lines (stripped of bullet prefix) appear in `ledger.raw_bullets`.

**4. `test_extract_claims_excludes_short_lines`**
Input: text with a short line (≤ 15 chars after stripping prefix) and a long line.
Assert: short line absent from `raw_bullets`; long line present.

**5. `test_extract_claims_excludes_header_lines`**
Input: text with a line ending in `:` (e.g. `"Work Experience:"`) and a normal bullet line.
Assert: header line absent from `raw_bullets`; bullet line present.

**6. `test_extract_claims_empty_input`**
Input: `""`.
Assert: `ledger.companies == frozenset()`, `ledger.metrics == frozenset()`, `ledger.raw_bullets == ()`.

**7. `test_extract_claims_returns_correct_types`**
Input: any non-empty resume text.
Assert: `companies` is `frozenset`, `metrics` is `frozenset`, `raw_bullets` is `tuple`.

**8. `test_extract_claims_prompt_block`**
Input: text with a known metric and (optionally) a company.
Assert: `ledger.prompt_block()` returns a string starting with `"CLAIMS LEDGER"` and containing the metric; for an empty ledger, contains `"no explicit metrics"`.

---

## Section 2: `fabrication_guard` tests (8 tests)

All tests construct a `ClaimsLedger` inline and call `fabrication_guard(generated_text, ledger, source_text) -> GuardResult`. All synchronous.

### Test list

**1. `test_guard_clean_text_passes_through`**
Generated text uses only attested metric (`"30%"` present in source_text).
Assert: `result.stripped == []`, `"30%"` present in `result.text`.

**2. `test_guard_strips_fabricated_metric`**
Generated text claims `"99%"` but source only contains `"30%"`.
Assert: `"99%"` in `result.stripped`.

**3. `test_guard_allows_metric_within_tolerance`**
Generated `"30.5%"`, source `"30%"` — delta is 1.67%, within ±2%.
Assert: `result.stripped == []`.

**4. `test_guard_strips_metric_outside_tolerance`**
Generated `"60%"`, source `"30%"` — delta is 100%, outside ±2%.
Assert: `"60%"` in `result.stripped`.

**5. `test_guard_substitutes_with_closest_original`**
Fabricated line has a close match in `ledger.raw_bullets` (difflib ratio > 0.35).
Assert: original bullet appears in `result.text` and fabricated metric is in `result.stripped`.

**6. `test_guard_adds_to_gaps_when_no_match`**
Fabricated metric, `raw_bullets` is empty (no close original to substitute).
Assert: `len(result.gaps) > 0` and fabricated metric is in `result.stripped`.

**7. `test_guard_non_metric_lines_preserved`**
Generated text has a line with no metrics and no ORG entities — a clean prose line.
Assert: that line appears verbatim in `result.text`.

**8. `test_guard_stripped_list_is_deduplicated`**
Same fabricated metric appears on two different lines.
Assert: `result.stripped.count("99%") == 1` (deduplication preserved).

---

## File Changed

| Action | Path |
|---|---|
| Create | `resume-optimizer/backend/tests/test_agents.py` |

---

## Notes

- spaCy `en_core_web_sm` must be installed — it is already in `requirements.txt` and pinned as a wheel. Tests will fail at import time if the model is not present (same as prod).
- Company extraction via spaCy NER is intentionally not tested for exact values — NER results depend on the model version and context length. The `companies` field type and emptiness are tested; fabrication company tests rely on the guard's `_company_attested` path via `fabrication_guard` (implicitly exercised through tests 5 and 7).
- All 16 tests are synchronous (`def test_...`, not `async def`). No `pytest_asyncio` needed.

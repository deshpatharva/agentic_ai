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

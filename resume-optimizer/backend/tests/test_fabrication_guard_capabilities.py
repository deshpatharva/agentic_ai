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

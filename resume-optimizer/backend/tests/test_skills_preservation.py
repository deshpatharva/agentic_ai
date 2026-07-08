"""Skills-preservation invariant.

Regression guard for the "Senior Data Engineer" bug: an upstream LLM stage
(skills_rewrite or the humanizer) rewrote a 45-skill Skills section down to 12,
silently dropping JD-*required* PySpark, Apache Airflow, and Snowflake. No stage
may drop a skill the candidate already listed; the delivered Skills section must
be a superset of the candidate's original skills (minus intentional filler).

These tests exercise the deterministic backstop in utils.skills_normalizer — no
LLM, so they are fully reproducible.
"""

from utils.skills_normalizer import (
    _parse_skills,
    normalize_skills,
    restore_missing_skills,
)


def test_restore_missing_skills_appends_dropped():
    tokens = ["Python", "SQL"]
    required = ["Python", "SQL", "Snowflake", "Apache Airflow", "PySpark"]

    out = restore_missing_skills(tokens, required)

    low = {t.lower() for t in out}
    assert {"snowflake", "apache airflow", "pyspark"} <= low
    # Already-present skills are not duplicated.
    assert sum(1 for t in out if t.lower() == "python") == 1
    assert sum(1 for t in out if t.lower() == "sql") == 1


def test_restore_missing_skills_is_member_aware():
    # A required skill already present as a delimited member of a grouped token
    # must NOT be appended again as a standalone entry.
    tokens = ["CI/CD (Azure DevOps, Jenkins)"]
    required = ["Azure DevOps"]

    out = restore_missing_skills(tokens, required)

    assert out == tokens


def test_normalize_skills_restores_dropped_originals():
    # Simulate the delivered section after an upstream stage gutted it.
    reduced = "Skills\nSQL, Python, Spark SQL"
    original = _parse_skills(
        "SQL, PySpark, Python, Snowflake, Apache Airflow, Databricks, dbt, Spark SQL"
    )

    out = normalize_skills(
        reduced, experience_text="", seniority="senior", preserve_skills=original
    ).lower()

    for must in ("pyspark", "snowflake", "apache airflow", "databricks", "dbt"):
        assert must in out, f"{must!r} was dropped despite being an original skill"


def test_normalize_skills_preserve_does_not_readd_filler():
    # Filler intentionally stripped for senior candidates must stay stripped even
    # when it appears in the preserve list.
    reduced = "Skills\nSQL, Python"
    original = _parse_skills("SQL, Python, Data Modeling")

    out = normalize_skills(
        reduced, experience_text="", seniority="senior", preserve_skills=original
    ).lower()

    assert "data modeling" not in out


def test_normalize_skills_preserve_none_is_backward_compatible():
    # Omitting preserve_skills leaves the historical behavior untouched.
    out = normalize_skills("Skills\nPython, SQL", experience_text="", seniority="mid")
    low = out.lower()
    assert "python" in low and "sql" in low

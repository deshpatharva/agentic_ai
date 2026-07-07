"""
Skills section post-processor.

Three jobs:
  1. Reconcile — scan the experience section for tools/technologies mentioned
     there but absent from the skills list, and add them.
  2. Deduplicate — remove skills that are already covered by another entry
     (e.g. "Azure DevOps" appearing twice under different groupings).
  3. Strip low-signal filler — generic items that dilute strong skills for
     senior-level candidates.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

_logger = logging.getLogger(__name__)

# Low-signal items to remove for senior/lead resumes (mid/entry keep them).
_FILLER_SKILLS = frozenset({
    "data structures", "algorithms", "object-oriented programming", "oop",
    "functional programming", "software development lifecycle", "sdlc",
    "networking fundamentals", "cloud computing", "scalability",
    "api design", "database administration", "data modeling",
})

# Technologies we know to look for in experience text.
# Keys are the canonical skill label; values are patterns to search for.
_EXPERIENCE_TECH_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Kafka",              re.compile(r"\bKafka\b",              re.IGNORECASE)),
    ("JMeter",             re.compile(r"\bJMeter\b",             re.IGNORECASE)),
    ("CloudWatch",         re.compile(r"\bCloudWatch\b",         re.IGNORECASE)),
    ("Azure AI Foundry",   re.compile(r"\bAzure AI Foundry\b",   re.IGNORECASE)),
    ("Microsoft Graph API",re.compile(r"\bMicrosoft Graph\b",    re.IGNORECASE)),
    ("Spark",              re.compile(r"\bApache Spark\b|\bSpark\b", re.IGNORECASE)),
    ("Airflow",            re.compile(r"\bAirflow\b",            re.IGNORECASE)),
    ("FastAPI",            re.compile(r"\bFastAPI\b",            re.IGNORECASE)),
    ("GraphQL",            re.compile(r"\bGraphQL\b",            re.IGNORECASE)),
    ("Celery",             re.compile(r"\bCelery\b",             re.IGNORECASE)),
    ("RabbitMQ",           re.compile(r"\bRabbitMQ\b",           re.IGNORECASE)),
]


def _parse_skills(skills_text: str) -> list[str]:
    """Split a flat or categorized skills block into individual skill tokens."""
    # Strip section header line(s) before parsing
    lines = skills_text.splitlines()
    skill_lines = [ln for ln in lines if not re.match(
        r"^\s*(skills|technical skills|core competencies|competencies|technologies|tools)\s*:?\s*$",
        ln, re.IGNORECASE,
    )]
    combined = " ".join(skill_lines)
    # Split on commas and semicolons; handle "Foo (Bar)" as one token
    tokens = re.split(r"[,;]+", combined)
    return [t.strip() for t in tokens if t.strip()]


def _skills_lower_set(tokens: list[str]) -> set[str]:
    return {t.lower() for t in tokens}


def _members(token_lower: str) -> set[str]:
    """Return the delimited members of a (possibly grouped) token.

    'ci/cd (azure devops, jenkins)' → {'ci/cd', 'azure devops', 'jenkins'}.
    Splits on commas and parentheses ONLY — never on letters — so standalone
    skills like 'c++', 'node.js', or the language 'r' stay intact and are not
    matched as substrings of unrelated tokens.
    """
    parts = re.split(r"[(),]", token_lower)
    return {p.strip() for p in parts if p.strip()}


def _dedup(tokens: list[str]) -> list[str]:
    """
    Remove tokens that are exact case-insensitive duplicates of an earlier token,
    OR that appear as a delimited member of an earlier grouped token (catches
    'Azure DevOps' listed both standalone and inside 'CI/CD (Azure DevOps, Jenkins)').

    A previous raw-substring test wrongly deleted short skills — 'R' was eaten by
    'Spark', 'MongoDB' by 'Go', 'C' by 'C++'. Member matching only treats a token
    as a duplicate when it is a whole comma/paren-delimited member of another,
    never merely a character run inside one.
    """
    seen: list[tuple[str, set[str]]] = []  # (lowercased token, its delimited members)
    result: list[str] = []

    for tok in tokens:
        tl = tok.lower()
        members = _members(tl)
        duplicate = False
        for prev_tl, prev_members in seen:
            if tl == prev_tl or tl in prev_members or prev_tl in members:
                duplicate = True
                break
        if not duplicate:
            seen.append((tl, members))
            result.append(tok)

    return result


def _strip_filler(tokens: list[str], seniority: str) -> list[str]:
    """Remove low-signal generic skills for senior/lead candidates."""
    if seniority not in ("senior", "lead"):
        return tokens
    return [t for t in tokens if t.lower() not in _FILLER_SKILLS]


def _reconcile_from_experience(
    tokens: list[str],
    experience_text: str,
) -> list[str]:
    """Add tools found in experience but missing from skills."""
    existing_lower = _skills_lower_set(tokens)
    additions: list[str] = []

    for label, pattern in _EXPERIENCE_TECH_PATTERNS:
        if label.lower() not in existing_lower and pattern.search(experience_text):
            additions.append(label)

    return tokens + additions


def normalize_skills(
    skills_text: str,
    experience_text: str = "",
    seniority: str = "mid",
) -> str:
    """
    Normalize the skills section text.

    Args:
        skills_text:     Raw skills section (may include the section header line).
        experience_text: Full experience section text for reconciliation.
        seniority:       'entry' | 'mid' | 'senior' | 'lead' — controls filler removal.

    Returns:
        Normalized skills section text (header line preserved if present).
    """
    if not skills_text.strip():
        return skills_text

    # Preserve header line
    lines = skills_text.splitlines()
    header_line: Optional[str] = None
    if lines and re.match(
        r"^\s*(skills|technical skills|core competencies|competencies|technologies|tools)\s*:?\s*$",
        lines[0], re.IGNORECASE,
    ):
        header_line = lines[0]

    tokens = _parse_skills(skills_text)
    tokens = _reconcile_from_experience(tokens, experience_text)
    tokens = _strip_filler(tokens, seniority)
    tokens = _dedup(tokens)

    skills_line = ", ".join(tokens) + "."
    if header_line:
        return f"{header_line}\n{skills_line}"
    return skills_line


# ── Deterministic skill categorization ───────────────────────────────────────
#
# A curated taxonomy maps known skills to a fixed, ordered set of recruiter-
# friendly categories. This is DETERMINISTIC — the same skills always produce the
# same grouping (no LLM nondeterminism, no miscategorization, no cost/latency).
# Unknown skills fall through keyword heuristics, then into "Tools & Technologies".

# Catch-all bucket label for skills that match no category.
_CATCH_ALL = "Tools & Technologies"

# Canonical category order (only non-empty categories are emitted).
_CATEGORY_ORDER = [
    "Languages",
    "Data Engineering",
    "Cloud & Platforms",
    "Databases",
    "DevOps & CI/CD",
    "AI & Machine Learning",
    "BI & Visualization",
    "Data Governance",
    _CATCH_ALL,
]

# Exact skill (lowercased) → category. Checked before any heuristic.
_SKILL_CATEGORY: dict[str, str] = {}


def _register(category: str, *skills: str) -> None:
    for s in skills:
        _SKILL_CATEGORY[s.lower()] = category


_register(
    "Languages",
    # mainstream
    "python", "java", "scala", "r", "c", "c++", "c#", "go", "golang", "rust",
    "javascript", "typescript", "ruby", "php", "kotlin", "swift", "objective-c",
    "matlab", "sas", "perl", "dart", "elixir", "clojure", "haskell", "julia",
    "groovy", "lua", "f#", "vb.net", "visual basic", "cobol", "fortran",
    # query / shell / markup-ish languages
    "sql", "t-sql", "pl/sql", "spark sql", "hiveql", "bash", "shell",
    "shell scripting", "powershell", "vba", "dax",
)
_register(
    "Data Engineering",
    "pyspark", "spark", "apache spark", "spark structured streaming", "dbt",
    "kafka", "apache kafka", "flink", "apache flink", "airflow", "apache airflow",
    "beam", "apache beam", "hadoop", "hive", "presto", "trino", "delta lake",
    "iceberg", "apache iceberg", "hudi", "apache hudi", "kinesis", "event hubs",
    "azure event hubs", "nifi", "apache nifi", "sqoop", "luigi", "dagster",
    "prefect", "fivetran", "stitch", "airbyte", "talend", "informatica",
    "ssis", "databricks asset bundles", "etl", "elt", "data pipelines",
    "data modeling", "kimball", "star schema", "scd type 2", "semantic layer",
    "data warehousing", "data lake", "lakehouse", "medallion architecture",
    "pubsub", "pub/sub", "spark streaming", "storm", "samza", "debezium",
)
_register(
    "Cloud & Platforms",
    "aws", "azure", "gcp", "google cloud", "google cloud platform", "oci",
    "oracle cloud", "ibm cloud", "databricks", "snowflake", "redshift",
    "aws redshift", "bigquery", "synapse", "azure synapse analytics",
    "azure synapse", "emr", "aws emr", "aws glue", "glue", "lambda",
    "aws lambda", "azure functions", "s3", "ec2", "ecs", "eks", "aks", "gke",
    "unity catalog", "azure data factory", "adf", "data factory",
    "microsoft fabric", "fabric", "dataproc", "dataflow", "cloud functions",
    "cloud run", "athena", "kinesis firehose", "step functions", "sns", "sqs",
    "blob storage", "adls", "azure data lake", "cloudformation",
)
_register(
    "Databases",
    "postgresql", "postgres", "mysql", "oracle", "sql server", "mssql",
    "mongodb", "cassandra", "redis", "dynamodb", "pinot", "apache pinot",
    "druid", "apache druid", "clickhouse", "elasticsearch", "opensearch",
    "neo4j", "cosmos db", "mariadb", "sqlite", "hbase", "couchbase",
    "memcached", "duckdb", "teradata", "db2", "vertica", "greenplum",
    "timescaledb", "influxdb", "supabase", "firebase", "firestore",
)
_register(
    "DevOps & CI/CD",
    "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins",
    "github actions", "gitlab ci", "gitlab", "gitops", "ci/cd",
    "infrastructure as code", "iac", "helm", "puppet", "chef", "snyk",
    "azure devops", "circleci", "travis ci", "argocd", "flux", "prometheus",
    "grafana", "datadog", "splunk", "new relic", "pagerduty", "vault",
    "pulumi", "packer", "nginx", "linux", "git", "jira", "confluence",
    "bitbucket", "octopus deploy", "teamcity", "bamboo",
)
_register(
    "AI & Machine Learning",
    "llm", "rag", "machine learning", "ml", "deep learning", "tensorflow",
    "pytorch", "scikit-learn", "sklearn", "keras", "xgboost", "lightgbm",
    "hugging face", "transformers", "nlp", "computer vision", "mlflow",
    "kubeflow", "sagemaker", "vertex ai", "azure ml", "langchain",
    "llamaindex", "openai", "anthropic", "generative ai", "genai", "mcp",
    "mcp server", "sentiment analysis", "feature engineering", "pandas",
    "numpy", "spacy", "opencv", "vector database", "pinecone", "weaviate",
    "chromadb", "fine-tuning", "prompt engineering",
)
_register(
    "BI & Visualization",
    "tableau", "power bi", "powerbi", "looker", "looker studio", "qlik",
    "qlikview", "qlik sense", "sap businessobjects", "businessobjects",
    "web intelligence", "webi", "universes", "superset", "apache superset",
    "metabase", "mode", "sigma", "matplotlib", "seaborn", "plotly", "d3.js",
    "dashboards", "ssrs", "cognos", "microstrategy", "domo",
)
_register(
    "Data Governance",
    "pii", "data governance", "data quality", "gdpr", "hipaa", "ccpa", "soc 2",
    "great expectations", "soda", "monte carlo", "data catalog", "collibra",
    "alation", "data lineage", "lineage", "masking", "encryption", "rbac",
    "compliance", "data privacy", "mdm", "master data management",
)


def taxonomy_terms() -> frozenset:
    """All known skill terms (lowercased) from the curated taxonomy.

    Single source of truth for capability evidence checks (fact_extractor,
    fabrication_guard)."""
    return frozenset(_SKILL_CATEGORY.keys())


# Substring heuristics for unknown tokens (checked in order).
_KEYWORD_RULES: list[tuple[str, str]] = [
    ("aws ", "Cloud & Platforms"),
    ("azure ", "Cloud & Platforms"),
    ("gcp ", "Cloud & Platforms"),
    ("google cloud", "Cloud & Platforms"),
    ("databricks", "Cloud & Platforms"),
    ("sql", "Languages"),
    ("spark", "Data Engineering"),
    ("kafka", "Data Engineering"),
    ("airflow", "Data Engineering"),
    ("etl", "Data Engineering"),
    ("pipeline", "Data Engineering"),
    ("ci/cd", "DevOps & CI/CD"),
    ("devops", "DevOps & CI/CD"),
    ("docker", "DevOps & CI/CD"),
    ("kubernetes", "DevOps & CI/CD"),
    ("terraform", "DevOps & CI/CD"),
    ("machine learning", "AI & Machine Learning"),
    (" ml", "AI & Machine Learning"),
    ("llm", "AI & Machine Learning"),
    ("governance", "Data Governance"),
    ("tableau", "BI & Visualization"),
    ("power bi", "BI & Visualization"),
]


def _category_for(token: str) -> str:
    """Return the canonical category for a single skill token."""
    norm = token.lower().strip()
    # Exact match (full token, then without any parenthetical/qualifier).
    if norm in _SKILL_CATEGORY:
        return _SKILL_CATEGORY[norm]
    base = re.sub(r"\s*\(.*?\)", "", norm).strip()
    if base in _SKILL_CATEGORY:
        return _SKILL_CATEGORY[base]
    # Keyword heuristics.
    padded = f" {norm} "
    for kw, cat in _KEYWORD_RULES:
        if kw in padded or kw in norm:
            return cat
    return _CATCH_ALL


async def categorize_skills(
    tokens: list[str],
    role_hint: str = "",
) -> dict[str, list[str]]:
    """Group skill tokens into labeled categories deterministically.

    Returns an ordered dict {category_label: [skill, ...]} in canonical order,
    suitable for emitting as `Category: skill1, skill2` lines in the resume.

    Deterministic: a curated taxonomy + keyword heuristics — no LLM, so identical
    inputs always yield identical groupings. Empty input returns {"": tokens}.
    """
    if not tokens:
        return {"": tokens}

    # Assign each token to a category, preserving original casing and order.
    buckets: dict[str, list[str]] = {cat: [] for cat in _CATEGORY_ORDER}
    seen: set[str] = set()
    for tok in tokens:
        tok = tok.strip()
        if not tok or tok.lower() in seen:
            continue
        seen.add(tok.lower())
        buckets[_category_for(tok)].append(tok)

    # Emit non-empty categories in canonical order.
    ordered = {cat: buckets[cat] for cat in _CATEGORY_ORDER if buckets[cat]}

    # If the only surviving category is the catch-all (nothing matched a real
    # category), fall back to a flat list rather than a lone "Tools & Technologies:".
    if list(ordered.keys()) == [_CATCH_ALL]:
        return {"": tokens}

    return ordered or {"": tokens}

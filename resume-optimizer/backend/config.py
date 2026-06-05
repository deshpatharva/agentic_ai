"""
Central configuration — models, API keys, pipeline settings.
All agents import from here instead of hardcoding values.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY        = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_AI_STUDIO_API_KEY = os.environ.get("google_ai_studio_api_key", "")
GROQ_API_KEY             = os.environ.get("groq_api_key", "")

# ── Job scraper keys (all optional — sources are skipped when key is absent) ──
ADZUNA_APP_ID    = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.environ.get("ADZUNA_APP_KEY", "")
THE_MUSE_API_KEY = os.environ.get("THE_MUSE_API_KEY", "")   # optional for The Muse
APIFY_TOKEN      = os.environ.get("APIFY_TOKEN", "")        # optional paid source

# ── Delta Lake ────────────────────────────────────────────────────────────────
# Local dev: ./delta_store    Prod: s3://your-bucket/delta/
DELTA_STORAGE_PATH = os.environ.get("DELTA_STORAGE_PATH", "./delta_store")

# ── Models ────────────────────────────────────────────────────────────────────
# All model names use LiteLLM provider prefixes — change here to swap providers.
# Rewriter — Gemini 2.5 Flash Lite (fast, cheap, good at keyword incorporation)
MODEL_REWRITER      = "gemini/gemini-2.5-flash-lite"
# Rewriter iter 2+ — applying feedback diffs only, lite is sufficient
MODEL_REWRITER_FAST = "gemini/gemini-2.5-flash-lite"

# Humanizer main pass — Gemini 2.5 Flash-Lite
MODEL_HUMANIZER     = "gemini/gemini-2.5-flash-lite"

# Humanizer critic — Llama 3.1 8B via Groq (structured feedback, near-free)
MODEL_CRITIC        = "groq/llama-3.1-8b-instant"

# Scorers — Gemini 2.5 Flash-Lite (ultra-cheap, all 4 scores in 1 call)
MODEL_SCORER        = "gemini/gemini-2.5-flash-lite"

# JD Analyzer — Gemini 2.5 Flash-Lite (keyword extraction only)
MODEL_JD_ANALYZER   = "gemini/gemini-2.5-flash-lite"

# Agentic Phase 2 models
MODEL_OPTIMIZER          = "gemini/gemini-2.5-flash"        # Strategist — needs reasoning
MODEL_KEYWORD_INJECT     = "gemini/gemini-2.5-flash-lite"   # ATS tool — cheap, fast
MODEL_BULLET_STRENGTHEN  = "gemini/gemini-2.5-flash-lite"   # Impact tool
MODEL_SKILLS_REWRITE     = "gemini/gemini-2.5-flash-lite"   # Skills gap tool
MODEL_SECTION_HUMANIZE   = "gemini/gemini-2.5-flash-lite"   # Readability tool

# Phase 2 hard limits
AGENT_MAX_ITER     = 10       # max CrewAI agent iterations before forced stop
AGENT_TOKEN_BUDGET = 20_000   # cumulative input+output tokens across all Phase 2 tool calls

# ── API URLs ──────────────────────────────────────────────────────────────────
BACKEND_URL  = os.environ.get("BACKEND_URL",  "http://localhost:8000")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

# ── Pipeline settings ─────────────────────────────────────────────────────────
MAX_ITERATIONS      = 4
SCORE_TARGET        = 90

# ── Input guards ──────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES    = int(os.environ.get("MAX_UPLOAD_BYTES",    5 * 1024 * 1024))  # 5 MB
MAX_RESUME_CHARS    = int(os.environ.get("MAX_RESUME_CHARS",    15_000))  # ~2 pages of text
MAX_JD_CHARS        = int(os.environ.get("MAX_JD_CHARS",        8_000))   # typical JD fits here

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/resumeopt")

# ── JWT Auth ──────────────────────────────────────────────────────────────────
_JWT_SECRET_DEFAULT = "change-me-in-production-use-32-char-random-string"
JWT_SECRET = os.environ.get("JWT_SECRET", _JWT_SECRET_DEFAULT)
if not JWT_SECRET or JWT_SECRET == _JWT_SECRET_DEFAULT:
    raise ValueError(
        "JWT_SECRET env var is not set or is still the default placeholder. "
        "Generate a secret with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
JWT_ALGORITHM   = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))

# ── Azure Storage ─────────────────────────────────────────────────────────────
AZURE_STORAGE_ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "")
OUTPUTS_CONTAINER          = os.environ.get("OUTPUTS_CONTAINER", "outputs")

# ── Rate limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_AUTH = os.environ.get("RATE_LIMIT_AUTH", "5/minute")

# ── Observability ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# ── Free trial ────────────────────────────────────────────────────────────────
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "7"))

# ── Pipeline recovery ─────────────────────────────────────────────────────────
STUCK_JOB_TIMEOUT_MINUTES = int(os.environ.get("STUCK_JOB_TIMEOUT_MINUTES", "30"))

# ── Stripe (optional) ─────────────────────────────────────────────────────────
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")

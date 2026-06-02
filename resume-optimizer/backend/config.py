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
# Rewriter — Gemini 2.5 Flash (high intelligence, fast, cheap)
MODEL_REWRITER      = "gemini-2.5-flash"
# Rewriter iter 2+ — applying feedback diffs only, lite is sufficient
MODEL_REWRITER_FAST = "gemini-2.5-flash-lite"

# Humanizer main pass — Gemini 2.5 Flash-Lite
MODEL_HUMANIZER     = "gemini-2.5-flash-lite"

# Humanizer critic — Llama 3.1 8B via Groq (structured feedback, near-free)
MODEL_CRITIC        = "llama-3.1-8b-instant"

# Scorers — Gemini 2.5 Flash-Lite (direct 8B successor, ultra-cheap, all 3 in 1 call)
MODEL_SCORER        = "gemini-2.5-flash-lite"

# JD Analyzer — Gemini 2.5 Flash-Lite (keyword extraction only)
MODEL_JD_ANALYZER   = "gemini-2.5-flash-lite"

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

# ── Stripe (optional) ─────────────────────────────────────────────────────────
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")

"""
Central configuration — models, API keys, pipeline settings.
All agents import from here instead of hardcoding values.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY       = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_AI_STUDIO_API_KEY = os.environ.get("google_ai_studio_api_key", "")
GROQ_API_KEY            = os.environ.get("groq_api_key", "")

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
MAX_ITERATIONS      = 3
SCORE_TARGET        = 90


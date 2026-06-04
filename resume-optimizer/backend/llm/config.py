"""
LLM configuration module for litellm + CrewAI integration.

Defines provider settings, LLM model configurations, and optimization parameters.
All agents and tasks import from here for consistent LLM/optimization behavior.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    provider: str          # "anthropic", "google", "groq", etc.
    api_key: str           # API key for the provider
    base_url: Optional[str] = None  # Optional custom base URL


@dataclass
class LLMConfig:
    """Configuration for all LLM providers and model selections."""

    # Provider configs
    anthropic: ProviderConfig
    google: ProviderConfig
    groq: ProviderConfig

    # Model selections (provider/model format for litellm)
    model_rewriter: str
    model_rewriter_fast: str
    model_humanizer: str
    model_critic: str
    model_scorer: str
    model_jd_analyzer: str

    def __post_init__(self):
        """Validate that all required API keys are present."""
        configs = [self.anthropic, self.google, self.groq]
        for config in configs:
            if not config.api_key:
                raise ValueError(f"Missing API key for provider: {config.provider}")


@dataclass
class OptimizationConfig:
    """Configuration for resume optimization pipeline."""

    max_iterations: int = 4      # Max optimization iterations
    score_target: int = 90       # Target match score
    max_resume_chars: int = 15_000
    max_jd_chars: int = 8_000


# ── Module-level instances ────────────────────────────────────────────────────
import os
from dotenv import load_dotenv

load_dotenv()

llm_config = LLMConfig(
    anthropic=ProviderConfig(
        provider="anthropic",
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
    ),
    google=ProviderConfig(
        provider="google",
        api_key=os.environ.get("google_ai_studio_api_key", ""),
    ),
    groq=ProviderConfig(
        provider="groq",
        api_key=os.environ.get("groq_api_key", ""),
    ),
    model_rewriter="gemini-3.1-flash-lite",
    model_rewriter_fast="gemini-2.5-flash-lite",
    model_humanizer="gemini-2.5-flash-lite",
    model_critic="llama-3.1-8b-instant",
    model_scorer="gemini-2.5-flash-lite",
    model_jd_analyzer="gemini-2.5-flash-lite",
)

opt_config = OptimizationConfig(
    max_iterations=int(os.environ.get("MAX_ITERATIONS", 4)),
    score_target=int(os.environ.get("SCORE_TARGET", 90)),
    max_resume_chars=int(os.environ.get("MAX_RESUME_CHARS", 15_000)),
    max_jd_chars=int(os.environ.get("MAX_JD_CHARS", 8_000)),
)

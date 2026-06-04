"""
LiteLLM configuration and provider routing.
Centralizes all LLM provider settings and fallback chains.
"""

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""
    name: str
    model: str
    max_context_tokens: int
    temperature: float = 0.7
    max_output_tokens: int = 2000
    timeout_seconds: int = 60

@dataclass
class LLMConfig:
    """Master LLM configuration."""

    # Primary provider
    primary_provider: str = "anthropic"
    primary_model: str = "claude-opus-4-8"

    # Provider-specific limits
    provider_limits: dict = None

    # Fallback chain: [(provider, model), (provider, model), ...]
    fallback_chain: List[Tuple[str, str]] = None

    # Generation parameters
    temperature: float = 0.7
    max_output_tokens: int = 2000
    timeout_seconds: int = 60

    def __post_init__(self):
        if self.provider_limits is None:
            self.provider_limits = {
                "anthropic": 200000,      # Claude Opus 4.8
                "openai": 128000,         # GPT-4o
                "together": 32000,        # Llama 3.1
                "groq": 8000,             # Groq models
                "ollama": 8000,           # Local Ollama
            }

        if self.fallback_chain is None:
            self.fallback_chain = [
                ("openai", "gpt-4o"),
                ("together", "meta-llama/Llama-3.1-405B-Instruct-Turbo"),
            ]

    def get_max_context_tokens(self, provider: str = None) -> int:
        """Get context token limit for a provider."""
        provider = provider or self.primary_provider
        return self.provider_limits.get(provider, 8000)

@dataclass
class OptimizationConfig:
    """Resume optimization loop parameters."""
    max_iterations: int = 3
    quality_threshold: float = 0.85
    persistent_gap_threshold: int = 2  # Gaps that persist across N iterations are unfixable
    sse_enabled: bool = True
    progress_update_interval_ms: int = 2000

# Global instances (lazy-loaded)
llm_config = LLMConfig()
opt_config = OptimizationConfig()

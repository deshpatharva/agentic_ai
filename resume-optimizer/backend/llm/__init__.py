"""
LLM module — litellm + CrewAI integration.

Provides configuration, client initialization, and utility functions for LLM operations.
"""

from llm.config import (
    ProviderConfig,
    LLMConfig,
    OptimizationConfig,
    llm_config,
    opt_config,
)

__all__ = [
    "ProviderConfig",
    "LLMConfig",
    "OptimizationConfig",
    "llm_config",
    "opt_config",
]

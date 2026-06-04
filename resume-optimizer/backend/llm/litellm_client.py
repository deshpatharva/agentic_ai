"""
LiteLLM wrapper: unified LLM client for all providers.
Supports OpenAI, Anthropic, Together, Groq, Ollama with automatic fallback.
"""

import asyncio
import logging
import litellm
from typing import Optional, Dict, Any
from llm.config import LLMConfig

logger = logging.getLogger(__name__)

class LiteLLMClient:
    """
    Unified LLM client using litellm.
    Automatically routes to correct provider based on config.
    Handles retries, fallback, token counting, cost tracking.
    """

    def __init__(self, config: LLMConfig):
        """Initialize with configuration."""
        self.config = config
        self.primary_provider = config.primary_provider
        self.primary_model = config.primary_model
        self.fallback_chain = config.fallback_chain

        # litellm setup
        litellm.drop_params = True  # Ignore unsupported params per provider
        litellm.set_verbose = True  # Log all API calls

    async def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Send a prompt to LLM and return response + token counts.

        Args:
            prompt: The prompt text
            model: Override model (defaults to primary_model)
            max_tokens: Max output tokens (defaults to config max_output_tokens)
            temperature: Temperature (defaults to config temperature)

        Returns:
            dict with keys:
                - text (str): Generated response
                - input_tokens (int): Input token count
                - output_tokens (int): Output token count
        """
        model = model or self.primary_model
        max_tokens = max_tokens or self.config.max_output_tokens
        temperature = temperature if temperature is not None else self.config.temperature

        # Try primary provider first
        result = await self._call_provider(
            provider=self.primary_provider,
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        if result:
            return result

        # Fall back to fallback chain
        for provider, fallback_model in self.fallback_chain:
            result = await self._call_provider(
                provider=provider,
                model=fallback_model,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if result:
                return result

        # All providers failed
        raise RuntimeError(
            f"All LLM providers failed. Primary: {self.primary_provider}, "
            f"Fallbacks: {self.fallback_chain}"
        )

    async def _call_provider(
        self,
        provider: str,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Call a specific provider with error handling.
        Returns None if provider fails, dict with response if successful.
        """
        try:
            # Construct full model string for litellm (e.g., "openai/gpt-4")
            full_model = f"{provider}/{model}"

            response = await asyncio.to_thread(
                litellm.completion,
                model=full_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=self.config.timeout_seconds,
            )

            return {
                "text": response.choices[0].message.content.strip(),
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }

        except Exception as e:
            # Log failure but don't raise; allow fallback to try
            logger.warning(f"Provider {provider}/{model} failed: {str(e)}")
            return None

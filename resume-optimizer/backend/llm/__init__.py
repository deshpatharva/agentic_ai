"""LLM abstraction layer using litellm."""

from llm.config import LLMConfig, OptimizationConfig, llm_config, opt_config
from llm.litellm_client import LiteLLMClient

# Global client instance
_client = None

def _get_client():
    """Get or create the global LiteLLMClient instance."""
    global _client
    if _client is None:
        _client = LiteLLMClient(llm_config)
    return _client

async def complete(
    prompt: str,
    model=None,
    max_tokens=None,
    temperature=None,
):
    """
    Send a prompt to LLM and return response + token counts.
    Wrapper around the global LiteLLMClient instance.

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
    client = _get_client()
    return await client.complete(prompt, model, max_tokens, temperature)

__all__ = ["LiteLLMClient", "llm_config", "opt_config", "complete"]

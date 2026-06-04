from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime, timezone


@dataclass
class TokenCost:
    """Represents the cost structure for a provider/model combination."""
    provider: str
    model: str
    input_cost_per_1m_tokens: float
    output_cost_per_1m_tokens: float


# Provider costs in dollars per 1 million tokens
PROVIDER_COSTS = {
    "anthropic/claude-opus-4-8": TokenCost(
        provider="anthropic",
        model="claude-opus-4-8",
        input_cost_per_1m_tokens=3.00,
        output_cost_per_1m_tokens=15.00,
    ),
    "openai/gpt-4o": TokenCost(
        provider="openai",
        model="gpt-4o",
        input_cost_per_1m_tokens=3.00,
        output_cost_per_1m_tokens=6.00,
    ),
    "together/llama-3.1-405b": TokenCost(
        provider="together",
        model="llama-3.1-405b",
        input_cost_per_1m_tokens=0.90,
        output_cost_per_1m_tokens=0.90,
    ),
}


@dataclass
class CallRecord:
    """Record of a single LLM API call."""
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_cents: int
    timestamp: str


class CostTracker:
    """Tracks LLM API usage and costs."""

    def __init__(self):
        """Initialize empty tracking."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_cents = 0
        self.calls: List[CallRecord] = []

    def record_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        """
        Record an LLM API call and calculate its cost.

        Args:
            provider: Provider name (e.g., "anthropic", "openai")
            model: Model name (e.g., "claude-opus-4-8", "gpt-4o")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in cents (int)
        """
        # Look up pricing
        key = f"{provider}/{model}"
        cost_cents = 0

        if key in PROVIDER_COSTS:
            cost_info = PROVIDER_COSTS[key]
            input_cost = (input_tokens / 1_000_000) * cost_info.input_cost_per_1m_tokens
            output_cost = (
                output_tokens / 1_000_000
            ) * cost_info.output_cost_per_1m_tokens
            cost_cents = int((input_cost + output_cost) * 100)

        # Create call record
        record = CallRecord(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Update tracking
        self.calls.append(record)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_cents += cost_cents

        return cost_cents

    def get_summary(self) -> Dict:
        """
        Get a summary of all tracked usage and costs.

        Returns:
            Dict with total_input_tokens, total_output_tokens, total_cost_cents, and calls
        """
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_cents": self.total_cost_cents,
            "calls": self.calls,
        }

"""
Base CrewAI Agent Setup
Factory functions for creating CrewAI agents with LiteLLMClient integration.
Provides a unified way to instantiate agents with consistent LLM configuration.
"""

from typing import Optional, List

try:
    from crewai import Agent
except ImportError:
    Agent = None

from llm import LiteLLMClient, llm_config


def create_crewai_llm() -> LiteLLMClient:
    """
    Create a CrewAI-compatible LLM instance using LiteLLMClient.

    Returns:
        LiteLLMClient: Configured LLM instance with litellm integration
                      supporting multiple providers (Anthropic, OpenAI, etc.)
    """
    return LiteLLMClient(llm_config)


def create_agent(
    role: str,
    goal: str,
    backstory: str,
    tools: Optional[List] = None,
) -> Optional[object]:
    """
    Factory function to create a CrewAI Agent with standardized configuration.

    Args:
        role: The agent's role/title (e.g., "JD Analyzer")
        goal: The agent's primary goal/objective
        backstory: The agent's background and expertise description
        tools: List of tools the agent can use (default: empty list)

    Returns:
        Agent: Configured CrewAI Agent instance with:
               - Given role, goal, backstory
               - Tools list (default empty)
               - LiteLLMClient LLM instance
               - verbose=True for debugging/logging
               - allow_delegation=False to prevent sub-delegation
        None if CrewAI is not available
    """
    if Agent is None:
        return None

    if tools is None:
        tools = []

    llm = create_crewai_llm()

    agent = Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        tools=tools,
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    return agent

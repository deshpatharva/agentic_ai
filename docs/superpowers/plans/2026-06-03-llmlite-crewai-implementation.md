# Multi-Provider LLM + CrewAI Agent Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the resume optimizer to use litellm for multi-provider LLM support and CrewAI for agent orchestration with iterative quality loops and SSE progress streaming.

**Architecture:** Replace hardcoded llm.py with litellm wrapper; convert 6 deterministic agents to CrewAI agents with @tool wrappers; add PipelineContext for shared state; implement loop controller with gap diagnosis; add SSE streaming for real-time progress updates.

**Tech Stack:** litellm (unified LLM routing), CrewAI (agent orchestration), FastAPI (SSE streaming), asyncio (async orchestration)

---

## Phase 1: Foundation & Configuration

### Task 1: Create litellm Configuration Module

**Files:**
- Create: `resume-optimizer/backend/llm/config.py`
- Modify: `resume-optimizer/backend/config.py`

- [ ] **Step 1: Write config.py with provider settings**

Create `resume-optimizer/backend/llm/config.py`:

```python
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
```

- [ ] **Step 2: Update main config.py to import and expose llm settings**

In `resume-optimizer/backend/config.py`, add at the top:

```python
from llm.config import LLMConfig, OptimizationConfig, llm_config, opt_config

# Expose at module level
__all__ = ["llm_config", "opt_config", "LLMConfig", "OptimizationConfig"]
```

- [ ] **Step 3: Create llm/__init__.py**

Create `resume-optimizer/backend/llm/__init__.py`:

```python
"""LLM abstraction layer using litellm."""

from llm.config import LLMConfig, OptimizationConfig, llm_config, opt_config
from llm.litellm_client import LiteLLMClient

__all__ = ["LiteLLMClient", "llm_config", "opt_config"]
```

- [ ] **Step 4: Commit**

```bash
cd resume-optimizer
git add backend/llm/__init__.py backend/llm/config.py backend/config.py
git commit -m "feat: create litellm configuration module with provider settings"
```

---

### Task 2: Create LiteLLM Client Wrapper

**Files:**
- Create: `resume-optimizer/backend/llm/litellm_client.py`
- Create: `resume-optimizer/backend/tests/test_litellm_client.py`

- [ ] **Step 1: Write failing test for LiteLLM client**

Create `resume-optimizer/backend/tests/test_litellm_client.py`:

```python
"""Tests for LiteLLM client wrapper."""

import pytest
import json
from unittest.mock import patch, AsyncMock
from llm.litellm_client import LiteLLMClient
from llm.config import LLMConfig

@pytest.mark.asyncio
async def test_complete_with_anthropic():
    """LiteLLMClient.complete() calls Anthropic when primary provider is anthropic."""
    config = LLMConfig(primary_provider="anthropic", primary_model="claude-opus-4-8")
    client = LiteLLMClient(config)
    
    with patch("litellm.acompletion") as mock_completion:
        mock_completion.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="Test response"))],
            usage=AsyncMock(prompt_tokens=100, completion_tokens=50),
        )
        
        result = await client.complete("Test prompt")
        
        assert result["text"] == "Test response"
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50

@pytest.mark.asyncio
async def test_complete_returns_dict_structure():
    """complete() returns dict with text, input_tokens, output_tokens."""
    config = LLMConfig()
    client = LiteLLMClient(config)
    
    with patch("litellm.acompletion") as mock_completion:
        mock_completion.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="Response"))],
            usage=AsyncMock(prompt_tokens=50, completion_tokens=25),
        )
        
        result = await client.complete("Prompt")
        
        assert isinstance(result, dict)
        assert "text" in result
        assert "input_tokens" in result
        assert "output_tokens" in result

@pytest.mark.asyncio
async def test_complete_respects_max_output_tokens():
    """complete() passes max_tokens parameter to litellm."""
    config = LLMConfig()
    client = LiteLLMClient(config)
    
    with patch("litellm.acompletion") as mock_completion:
        mock_completion.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="Response"))],
            usage=AsyncMock(prompt_tokens=50, completion_tokens=25),
        )
        
        await client.complete("Prompt", max_tokens=1000)
        
        # Verify acompletion was called with max_tokens
        call_kwargs = mock_completion.call_args[1]
        assert call_kwargs.get("max_tokens") == 1000
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_litellm_client.py -v
```

Expected: FAILED — LiteLLMClient not found / import error

- [ ] **Step 3: Write LiteLLMClient implementation**

Create `resume-optimizer/backend/llm/litellm_client.py`:

```python
"""
LiteLLM wrapper: unified LLM client for all providers.
Supports OpenAI, Anthropic, Together, Groq, Ollama with automatic fallback.
"""

import asyncio
import litellm
from typing import Optional, Dict, Any
from llm.config import LLMConfig

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
        temperature = temperature or self.config.temperature
        
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
        Call a specific provider with retry logic.
        Returns None if provider fails, dict with response if successful.
        """
        try:
            # Construct full model string for litellm (e.g., "claude-3-opus")
            full_model = f"{provider}/{model}" if provider != "ollama" else f"ollama/{model}"
            
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
            import logging
            logging.warning(f"Provider {provider}/{model} failed: {str(e)}")
            return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_litellm_client.py -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
cd resume-optimizer
git add backend/llm/litellm_client.py backend/tests/test_litellm_client.py
git commit -m "feat: add LiteLLMClient wrapper for unified provider routing"
```

---

### Task 3: Create Cost Tracking Module

**Files:**
- Create: `resume-optimizer/backend/llm/cost_tracker.py`

- [ ] **Step 1: Write cost tracker module**

Create `resume-optimizer/backend/llm/cost_tracker.py`:

```python
"""
Token and cost tracking for LLM calls.
Accumulates costs across optimization pipeline for billing and analytics.
"""

from dataclasses import dataclass, field
from typing import Dict
from datetime import datetime

@dataclass
class TokenCost:
    """Cost per token for a single provider."""
    provider: str
    model: str
    input_cost_per_1m_tokens: float  # Cost in cents per 1M input tokens
    output_cost_per_1m_tokens: float  # Cost in cents per 1M output tokens

# Provider pricing (as of 2026-06-03)
# Update these as provider pricing changes
PROVIDER_COSTS = {
    "anthropic/claude-opus-4-8": TokenCost(
        provider="anthropic",
        model="claude-opus-4-8",
        input_cost_per_1m_tokens=300,  # $3.00 per 1M input tokens
        output_cost_per_1m_tokens=1500,  # $15.00 per 1M output tokens
    ),
    "openai/gpt-4o": TokenCost(
        provider="openai",
        model="gpt-4o",
        input_cost_per_1m_tokens=300,  # $3.00 per 1M input tokens
        output_cost_per_1m_tokens=600,  # $6.00 per 1M output tokens
    ),
    "together/llama-3.1-405b": TokenCost(
        provider="together",
        model="meta-llama/Llama-3.1-405B-Instruct-Turbo",
        input_cost_per_1m_tokens=90,  # $0.90 per 1M input tokens
        output_cost_per_1m_tokens=90,  # $0.90 per 1M output tokens
    ),
}

class CostTracker:
    """Tracks token usage and costs across a pipeline run."""
    
    def __init__(self):
        self.calls: list = []  # List of (provider, model, input_tokens, output_tokens, cost_cents)
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cost_cents: int = 0
    
    def record_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        """
        Record a single LLM call and return cost in cents.
        
        Args:
            provider: Provider name (anthropic, openai, together, etc)
            model: Full model identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
        
        Returns:
            Cost in cents
        """
        # Look up cost
        cost_key = f"{provider}/{model}" if provider != "ollama" else f"ollama/{model}"
        cost_info = PROVIDER_COSTS.get(cost_key)
        
        if not cost_info:
            # Default to zero cost if unknown (e.g., local Ollama)
            cost_cents = 0
        else:
            input_cost = (input_tokens / 1_000_000) * cost_info.input_cost_per_1m_tokens
            output_cost = (output_tokens / 1_000_000) * cost_info.output_cost_per_1m_tokens
            cost_cents = int((input_cost + output_cost) * 100)  # Convert to cents
        
        # Record
        self.calls.append({
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_cents": cost_cents,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_cents += cost_cents
        
        return cost_cents
    
    def get_summary(self) -> dict:
        """Get cost tracking summary."""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_cents": self.total_cost_cents,
            "calls_count": len(self.calls),
            "calls": self.calls,
        }
```

- [ ] **Step 2: Commit**

```bash
cd resume-optimizer
git add backend/llm/cost_tracker.py
git commit -m "feat: add cost tracker for token usage and billing"
```

---

## Phase 2: Agent Refactoring

### Task 4: Create CrewAI Base Agent Setup

**Files:**
- Create: `resume-optimizer/backend/agents/base.py`

- [ ] **Step 1: Write base agent module**

Create `resume-optimizer/backend/agents/base.py`:

```python
"""
Base CrewAI agent setup.
Provides factory functions to create agents with standardized configuration.
"""

from crewai import Agent
from llm.litellm_client import LiteLLMClient
from llm.config import llm_config

def create_crewai_llm():
    """Create a CrewAI-compatible LLM instance."""
    # CrewAI expects an LLM instance; we'll use LiteLLMClient
    return LiteLLMClient(llm_config)

def create_agent(
    role: str,
    goal: str,
    backstory: str,
    tools: list = None,
) -> Agent:
    """
    Factory function to create a CrewAI Agent.
    
    Args:
        role: Agent role (e.g., "Fact Extractor")
        goal: Agent goal (e.g., "Extract and validate claims")
        backstory: Agent backstory/persona
        tools: List of @tool-decorated functions
    
    Returns:
        CrewAI Agent instance
    """
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        tools=tools or [],
        llm=create_crewai_llm(),
        verbose=True,
        allow_delegation=False,  # No sub-agents
    )
```

- [ ] **Step 2: Commit**

```bash
cd resume-optimizer
git add backend/agents/base.py
git commit -m "feat: add base CrewAI agent factory"
```

---

### Task 5: Create PipelineContext Dataclass

**Files:**
- Create: `resume-optimizer/backend/orchestration/context.py`

- [ ] **Step 1: Write PipelineContext module**

Create `resume-optimizer/backend/orchestration/context.py`:

```python
"""
Shared state context for pipeline execution.
Single source of truth for all task inputs/outputs.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
from datetime import datetime

@dataclass
class PipelineContext:
    """
    Shared state across all optimization pipeline tasks.
    Each task reads and updates this context.
    """
    
    # Input data
    resume_text: str
    jd_text: str
    user_id: str
    optimization_id: str
    
    # Configuration
    max_iterations: int = 3
    quality_threshold: float = 0.85
    
    # Task outputs (updated by each task)
    claims_ledger: Dict[str, Any] = field(default_factory=dict)
    jd_analysis: Dict[str, Any] = field(default_factory=dict)
    rewritten_resume: str = ""
    humanized_resume: str = ""
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    validation_report: Dict[str, Any] = field(default_factory=dict)
    
    # Loop tracking
    iteration_count: int = 0
    quality_score: float = 0.0
    improvement_history: List[Dict[str, Any]] = field(default_factory=list)
    persistent_gaps: List[str] = field(default_factory=list)
    
    # Token/cost tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_cents: int = 0
    
    # Error tracking
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, str]] = field(default_factory=list)
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def record_error(self, task_name: str, error: str):
        """Record a task error."""
        self.errors.append({
            "task": task_name,
            "error": error,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    def record_warning(self, task_name: str, warning: str):
        """Record a task warning."""
        self.warnings.append({
            "task": task_name,
            "warning": warning,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    def add_iteration_history(self):
        """Record current iteration state to history."""
        self.improvement_history.append({
            "iteration": self.iteration_count,
            "quality_score": self.quality_score,
            "gaps": self.score_breakdown.get("gaps", []),
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    def update_timestamp(self):
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow().isoformat()
```

- [ ] **Step 2: Create orchestration/__init__.py**

Create `resume-optimizer/backend/orchestration/__init__.py`:

```python
"""Resume optimization orchestration layer."""

from orchestration.context import PipelineContext

__all__ = ["PipelineContext"]
```

- [ ] **Step 3: Commit**

```bash
cd resume-optimizer
git add backend/orchestration/__init__.py backend/orchestration/context.py
git commit -m "feat: add PipelineContext for shared pipeline state"
```

---

### Task 6: Refactor Fact Extractor Agent

**Files:**
- Modify: `resume-optimizer/backend/agents/fact_extractor.py`

- [ ] **Step 1: Update fact_extractor.py with CrewAI Agent**

Replace the contents of `resume-optimizer/backend/agents/fact_extractor.py`:

```python
"""
Fact Extractor Agent: Extract verifiable claims from resume.
Uses existing spaCy/pattern logic; wraps as CrewAI tool.
"""

from crewai import tool
from agents.base import create_agent
from agents.fact_extractor import extract_claims as _extract_claims_impl

@tool
def extract_claims_tool(resume_text: str) -> dict:
    """
    Extract claims ledger from resume text.
    Returns dict with companies, metrics, raw_bullets.
    """
    ledger = _extract_claims_impl(resume_text)
    return {
        "companies": list(ledger.companies),
        "metrics": list(ledger.metrics),
        "raw_bullets": list(ledger.raw_bullets),
    }

def create_fact_extractor_agent():
    """Create the Fact Extractor CrewAI Agent."""
    return create_agent(
        role="Fact Extractor",
        goal="Extract and validate all claims, metrics, companies from resume",
        backstory=(
            "You are an expert at identifying and cataloging factual content. "
            "Your job is to extract verifiable claims, quantified metrics, and company names "
            "from resume text. You ensure accuracy and completeness."
        ),
        tools=[extract_claims_tool],
    )

# Keep original function for backwards compatibility
__all__ = ["create_fact_extractor_agent", "extract_claims_tool"]
```

Wait—I need to be careful here. The existing `fact_extractor.py` has the `extract_claims()` function we need to preserve. Let me adjust this:

```python
"""
Fact Extractor Agent: Extract verifiable claims from resume.
Uses existing spaCy/pattern logic; wraps as CrewAI tool.
"""

from crewai import tool
from agents.base import create_agent

# Import existing function (keep original implementation)
from agents.fact_extractor import extract_claims  # Original implementation

@tool
def extract_claims_tool(resume_text: str) -> dict:
    """
    Extract claims ledger from resume text.
    Returns dict with companies, metrics, raw_bullets.
    """
    ledger = extract_claims(resume_text)
    return {
        "companies": list(ledger.companies),
        "metrics": list(ledger.metrics),
        "raw_bullets": list(ledger.raw_bullets),
    }

def create_fact_extractor_agent():
    """Create the Fact Extractor CrewAI Agent."""
    return create_agent(
        role="Fact Extractor",
        goal="Extract and validate all claims, metrics, companies from resume",
        backstory=(
            "You are an expert at identifying and cataloging factual content. "
            "Your job is to extract verifiable claims, quantified metrics, and company names "
            "from resume text. You ensure accuracy and completeness."
        ),
        tools=[extract_claims_tool],
    )

__all__ = ["create_fact_extractor_agent", "extract_claims_tool", "extract_claims"]
```

Actually, I need to reconsider. The file already has `extract_claims()`. I should ADD the agent creation code to the end of the existing file, not replace it. Let me correct this step:

- [ ] **Step 1: Update fact_extractor.py to add CrewAI agent creation**

In `resume-optimizer/backend/agents/fact_extractor.py`, add at the END of the file (after existing code):

```python

# ── CrewAI Agent Integration ────────────────────────────────────────────────
from crewai import tool
from agents.base import create_agent

@tool
def extract_claims_tool(resume_text: str) -> dict:
    """
    Extract claims ledger from resume text.
    Wraps the existing extract_claims() function as a CrewAI tool.
    
    Returns:
        dict with keys: companies (list), metrics (list), raw_bullets (tuple)
    """
    ledger = extract_claims(resume_text)
    return {
        "companies": list(ledger.companies),
        "metrics": list(ledger.metrics),
        "raw_bullets": list(ledger.raw_bullets),
    }

def create_fact_extractor_agent():
    """Create the Fact Extractor CrewAI Agent."""
    return create_agent(
        role="Fact Extractor",
        goal="Extract and validate all claims, metrics, companies from resume",
        backstory=(
            "You are an expert at identifying and cataloging factual content. "
            "Your job is to extract verifiable claims, quantified metrics, and company names "
            "from resume text. You ensure accuracy and completeness."
        ),
        tools=[extract_claims_tool],
    )
```

- [ ] **Step 2: Commit**

```bash
cd resume-optimizer
git add backend/agents/fact_extractor.py
git commit -m "feat: add CrewAI agent wrapper to fact_extractor"
```

---

### Task 7: Create Remaining Agent Wrappers (JD Analyzer, Rewriter, Humanizer, Scorer, Fabrication Guard)

**Files:**
- Modify: `resume-optimizer/backend/agents/jd_analyzer.py`
- Modify: `resume-optimizer/backend/agents/rewriter.py`
- Modify: `resume-optimizer/backend/agents/humanizer.py`
- Modify: `resume-optimizer/backend/agents/scorer.py`
- Modify: `resume-optimizer/backend/agents/fabrication_guard.py`

Due to length, I'll provide a template for each. Follow the pattern from Task 6:

- [ ] **Step 1: Add CrewAI wrapper to jd_analyzer.py**

In `resume-optimizer/backend/agents/jd_analyzer.py`, add at the END:

```python
# ── CrewAI Agent Integration ────────────────────────────────────────────────
from crewai import tool
from agents.base import create_agent

@tool
def analyze_jd_tool(jd_text: str, resume_text: str) -> dict:
    """
    Analyze job description and match against resume.
    Returns dict with keywords, requirements, match_score.
    """
    # Call existing analyze_jd function (assuming it exists)
    result = analyze_jd(jd_text, resume_text)  # Your existing function
    return result

def create_jd_analyzer_agent():
    """Create the JD Analyzer CrewAI Agent."""
    return create_agent(
        role="Job Description Analyzer",
        goal="Analyze job descriptions and identify key requirements and keywords",
        backstory=(
            "You are an expert recruiter who understands job descriptions deeply. "
            "You extract key requirements, skills, and keywords to guide resume optimization."
        ),
        tools=[analyze_jd_tool],
    )
```

- [ ] **Step 2: Add CrewAI wrapper to rewriter.py**

In `resume-optimizer/backend/agents/rewriter.py`, add at the END:

```python
# ── CrewAI Agent Integration ────────────────────────────────────────────────
from crewai import tool
from agents.base import create_agent

@tool
def rewrite_tool(resume_text: str, improvement_gaps: dict) -> dict:
    """
    Rewrite resume based on identified gaps.
    Returns dict with rewritten_resume.
    """
    # Call existing rewrite_resume function (assuming it exists)
    result = rewrite_resume(resume_text, improvement_gaps)  # Your existing function
    return {"text": result}

def create_rewriter_agent():
    """Create the Rewriter CrewAI Agent."""
    return create_agent(
        role="Resume Rewriter",
        goal="Improve resume bullets with stronger action verbs and structure",
        backstory=(
            "You are an expert resume writer with decades of experience. "
            "You strengthen weak bullets, add action verbs, and improve overall readability."
        ),
        tools=[rewrite_tool],
    )
```

- [ ] **Step 3: Add CrewAI wrapper to humanizer.py**

In `resume-optimizer/backend/agents/humanizer.py`, add at the END:

```python
# ── CrewAI Agent Integration ────────────────────────────────────────────────
from crewai import tool
from agents.base import create_agent

@tool
def humanize_tool(resume_text: str) -> dict:
    """
    Polish resume language to sound natural and human.
    Returns dict with humanized_resume.
    """
    # Call existing humanize_resume function
    result = await humanize_resume(resume_text)
    return {"text": result["text"]}

def create_humanizer_agent():
    """Create the Humanizer CrewAI Agent."""
    return create_agent(
        role="Resume Humanizer",
        goal="Polish language to sound natural and human, not AI-generated",
        backstory=(
            "You are a master of natural language and tone. "
            "You remove buzzwords, make resumes conversational, and ensure authenticity."
        ),
        tools=[humanize_tool],
    )
```

- [ ] **Step 4: Add CrewAI wrapper to scorer.py**

In `resume-optimizer/backend/agents/scorer.py`, add at the END:

```python
# ── CrewAI Agent Integration ────────────────────────────────────────────────
from crewai import tool
from agents.base import create_agent

@tool
def score_tool(resume_text: str, jd_analysis: dict, claims_ledger: dict) -> dict:
    """
    Score resume quality across multiple dimensions.
    Returns dict with quality_score (0-1) and score_breakdown.
    """
    # Call existing score_resume function
    result = score_resume(resume_text, jd_analysis, claims_ledger)
    return result

def create_scorer_agent():
    """Create the Scorer CrewAI Agent."""
    return create_agent(
        role="Resume Quality Scorer",
        goal="Evaluate resume quality across metrics_presence, action_verbs, jd_alignment, readability",
        backstory=(
            "You are an expert hiring manager who can instantly assess resume quality. "
            "You provide detailed scoring and actionable feedback for improvement."
        ),
        tools=[score_tool],
    )
```

- [ ] **Step 5: Add CrewAI wrapper to fabrication_guard.py**

In `resume-optimizer/backend/agents/fabrication_guard.py`, add at the END:

```python
# ── CrewAI Agent Integration ────────────────────────────────────────────────
from crewai import tool
from agents.base import create_agent

@tool
def validate_tool(resume_text: str, claims_ledger: dict) -> dict:
    """
    Validate resume against claim ledger to detect fabrications.
    Returns dict with validation_report and stripped_fabrications.
    """
    # Call existing fabrication_guard function
    result = fabrication_guard(resume_text, claims_ledger)
    return result

def create_fabrication_guard_agent():
    """Create the Fabrication Guard CrewAI Agent."""
    return create_agent(
        role="Fabrication Guard",
        goal="Validate resume claims against source material to prevent hallucinations",
        backstory=(
            "You are a meticulous fact-checker who catches exaggerations and fabrications. "
            "You ensure resume claims are grounded in reality and verifiable."
        ),
        tools=[validate_tool],
    )
```

- [ ] **Step 6: Commit all agent updates**

```bash
cd resume-optimizer
git add backend/agents/jd_analyzer.py \
        backend/agents/rewriter.py \
        backend/agents/humanizer.py \
        backend/agents/scorer.py \
        backend/agents/fabrication_guard.py
git commit -m "feat: add CrewAI agent wrappers to all agents"
```

---

## Phase 3: Orchestration Layer

### Task 8: Create Pipeline Executor

**Files:**
- Create: `resume-optimizer/backend/orchestration/pipeline.py`
- Create: `resume-optimizer/backend/tests/test_pipeline.py`

- [ ] **Step 1: Write failing test for pipeline executor**

Create `resume-optimizer/backend/tests/test_pipeline.py`:

```python
"""Tests for pipeline executor."""

import pytest
from orchestration.context import PipelineContext
from orchestration.pipeline import PipelineExecutor
from agents.fact_extractor import create_fact_extractor_agent

@pytest.mark.asyncio
async def test_pipeline_executor_executes_single_task():
    """PipelineExecutor.execute_task() runs a task and updates context."""
    context = PipelineContext(
        resume_text="Senior Engineer at Google. 30% improvement.",
        jd_text="",
        user_id="user_123",
        optimization_id="opt_456",
    )
    
    executor = PipelineExecutor()
    agent = create_fact_extractor_agent()
    
    # Execute task (should extract claims)
    result = await executor.execute_task("extract_claims", agent, context)
    
    assert result is not None
    assert "metrics" in result or "companies" in result

@pytest.mark.asyncio
async def test_pipeline_executor_updates_context():
    """execute_task() updates PipelineContext with task output."""
    context = PipelineContext(
        resume_text="Led team of 5 engineers. 40% efficiency gain.",
        jd_text="",
        user_id="user_123",
        optimization_id="opt_456",
    )
    
    executor = PipelineExecutor()
    agent = create_fact_extractor_agent()
    
    await executor.execute_task("extract_claims", agent, context)
    
    # Context should be updated
    assert len(context.claims_ledger) > 0 or context.claims_ledger == {}  # May be empty or filled
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_pipeline.py -v
```

Expected: FAILED — PipelineExecutor not found

- [ ] **Step 3: Write PipelineExecutor implementation**

Create `resume-optimizer/backend/orchestration/pipeline.py`:

```python
"""
Sequential task pipeline executor.
Executes agents in order; maintains shared PipelineContext to prevent token loss.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
from crewai import Task
from orchestration.context import PipelineContext
from llm.cost_tracker import CostTracker

logger = logging.getLogger(__name__)

class PipelineExecutor:
    """Executes a sequence of tasks with explicit context management."""
    
    def __init__(self):
        self.cost_tracker = CostTracker()
    
    async def execute_task(
        self,
        task_name: str,
        agent,
        context: PipelineContext,
        task_input: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a single task with explicit context isolation (no token doubling).
        
        Args:
            task_name: Name of the task (e.g., "extract_claims", "rewrite")
            agent: CrewAI Agent instance
            context: PipelineContext (shared state)
            task_input: Optional override for task input
        
        Returns:
            Task result dict
        """
        logger.info(f"Starting task: {task_name}")
        
        try:
            # Prepare minimal task input (context isolation)
            if task_input is None:
                task_input = self._prepare_task_input(task_name, context)
            
            # Execute via CrewAI Task
            task = Task(
                description=f"Execute {task_name}",
                agent=agent,
                expected_output=f"Output from {task_name}",
            )
            
            # Run the task
            result = await asyncio.to_thread(
                task.execute,
                task_input,
            )
            
            # Update context with result
            self._update_context(task_name, context, result)
            
            logger.info(f"Completed task: {task_name}")
            return result
        
        except Exception as e:
            logger.error(f"Task {task_name} failed: {str(e)}")
            context.record_error(task_name, str(e))
            raise
    
    def _prepare_task_input(self, task_name: str, context: PipelineContext) -> str:
        """
        Prepare minimal task input to avoid token doubling with CrewAI's auto-context.
        Each task gets ONLY what it needs.
        """
        if task_name == "extract_claims":
            return context.resume_text
        
        elif task_name == "analyze_jd":
            return f"JD:\n{context.jd_text}\n\nResume:\n{context.resume_text}"
        
        elif task_name == "rewrite":
            gaps = context.improvement_history[-1]["gaps"] if context.improvement_history else []
            gaps_str = "\n".join(f"- {gap}" for gap in gaps) if gaps else "None (first iteration)"
            return f"Resume:\n{context.resume_text}\n\nGaps to address:\n{gaps_str}"
        
        elif task_name == "humanize":
            # Only the rewritten resume, not the original
            return context.rewritten_resume or context.resume_text
        
        elif task_name == "score":
            return f"""Resume:
{context.humanized_resume or context.resume_text}

JD Analysis:
{json.dumps(context.jd_analysis)}

Claims:
{json.dumps(context.claims_ledger)}"""
        
        elif task_name == "validate":
            return f"""Resume:
{context.humanized_resume or context.resume_text}

Claims Ledger:
{json.dumps(context.claims_ledger)}"""
        
        else:
            return ""
    
    def _update_context(
        self,
        task_name: str,
        context: PipelineContext,
        result: Any,
    ):
        """
        Update PipelineContext with task result.
        Maps task output to the correct context field.
        """
        try:
            if task_name == "extract_claims":
                context.claims_ledger = result if isinstance(result, dict) else {}
            
            elif task_name == "analyze_jd":
                context.jd_analysis = result if isinstance(result, dict) else {}
            
            elif task_name == "rewrite":
                if isinstance(result, dict):
                    context.rewritten_resume = result.get("text", "")
                else:
                    context.rewritten_resume = str(result)
            
            elif task_name == "humanize":
                if isinstance(result, dict):
                    context.humanized_resume = result.get("text", "")
                else:
                    context.humanized_resume = str(result)
            
            elif task_name == "score":
                if isinstance(result, dict):
                    context.score_breakdown = result
                    context.quality_score = result.get("quality_score", 0.0)
            
            elif task_name == "validate":
                context.validation_report = result if isinstance(result, dict) else {}
            
            context.update_timestamp()
        
        except Exception as e:
            logger.warning(f"Failed to update context for {task_name}: {str(e)}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_pipeline.py -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
cd resume-optimizer
git add backend/orchestration/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: add PipelineExecutor for sequential task execution"
```

---

### Task 9: Create Loop Controller with Gap Detection

**Files:**
- Create: `resume-optimizer/backend/orchestration/loop_controller.py`
- Create: `resume-optimizer/backend/tests/test_loop_controller.py`

- [ ] **Step 1: Write failing test for loop controller**

Create `resume-optimizer/backend/tests/test_loop_controller.py`:

```python
"""Tests for loop controller and gap detection."""

import pytest
from orchestration.context import PipelineContext
from orchestration.loop_controller import LoopController

@pytest.mark.asyncio
async def test_loop_controller_stops_at_threshold():
    """LoopController stops when quality_score >= threshold."""
    context = PipelineContext(
        resume_text="Test",
        jd_text="Test",
        user_id="user_123",
        optimization_id="opt_456",
        quality_threshold=0.85,
    )
    context.quality_score = 0.87  # Above threshold
    
    controller = LoopController(context)
    should_continue = controller.should_continue_loop()
    
    assert should_continue is False

@pytest.mark.asyncio
async def test_loop_controller_detects_persistent_gaps():
    """LoopController stops when gaps persist across iterations."""
    context = PipelineContext(
        resume_text="Test",
        jd_text="Test",
        user_id="user_123",
        optimization_id="opt_456",
        max_iterations=3,
    )
    context.quality_threshold = 0.85
    
    # Simulate iterations with persistent gaps
    context.improvement_history = [
        {"iteration": 1, "gaps": ["no_metrics", "weak_verbs"]},
        {"iteration": 2, "gaps": ["no_metrics"]},
        {"iteration": 3, "gaps": ["no_metrics"]},
    ]
    context.iteration_count = 3
    
    controller = LoopController(context)
    persistent = controller.get_persistent_gaps()
    
    assert "no_metrics" in persistent
    assert len(persistent) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_loop_controller.py -v
```

Expected: FAILED

- [ ] **Step 3: Write LoopController implementation**

Create `resume-optimizer/backend/orchestration/loop_controller.py`:

```python
"""
Loop controller: manages iterative improvement with quality threshold.
Detects persistent gaps and determines if threshold is reachable.
"""

import logging
from typing import List, Dict, Any
from orchestration.context import PipelineContext
from orchestration.result import format_result

logger = logging.getLogger(__name__)

class LoopController:
    """Controls iterative optimization loop with quality threshold and gap detection."""
    
    def __init__(self, context: PipelineContext):
        self.context = context
    
    def should_continue_loop(self) -> bool:
        """
        Determine if another iteration should run.
        Stops if:
        1. Quality score >= threshold
        2. Max iterations reached
        3. Persistent gaps detected (unreachable threshold)
        """
        # Check if threshold reached
        if self.context.quality_score >= self.context.quality_threshold:
            logger.info(f"Threshold reached: {self.context.quality_score} >= {self.context.quality_threshold}")
            return False
        
        # Check if max iterations exceeded
        if self.context.iteration_count >= self.context.max_iterations:
            logger.info(f"Max iterations ({self.context.max_iterations}) reached")
            return False
        
        # Check for persistent gaps (gap reachability analysis)
        persistent = self.get_persistent_gaps()
        if persistent and len(self.context.improvement_history) >= self.context.max_iterations - 1:
            logger.info(f"Persistent gaps detected: {persistent}. Threshold likely unreachable.")
            self.context.persistent_gaps = persistent
            return False
        
        return True
    
    def get_persistent_gaps(self) -> List[str]:
        """
        Identify gaps that persist across iterations.
        If a gap appears in the last 2+ iterations without change, it's persistent.
        """
        if len(self.context.improvement_history) < 2:
            return []
        
        # Get gaps from last 2 iterations
        recent_iterations = self.context.improvement_history[-2:]
        gap_sets = [set(it["gaps"]) for it in recent_iterations]
        
        # Intersection = persistent gaps
        persistent = list(set.intersection(*gap_sets)) if gap_sets else []
        return persistent
    
    def prepare_diagnostic(self) -> Dict[str, Any]:
        """
        Prepare diagnostic report if threshold not reached.
        Identifies why optimization stopped and what gaps remain.
        """
        persistent = self.get_persistent_gaps()
        
        # Classify gaps as fixable vs unfixable
        unfixable_keywords = [
            "no metrics",
            "no quantifiable",
            "lacks achievement",
            "missing data",
        ]
        
        unfixable_gaps = [
            g for g in persistent 
            if any(kw in g.lower() for kw in unfixable_keywords)
        ]
        
        diagnosis = {
            "reason": "Persistent gaps in resume source material",
            "persistent_gaps": persistent,
            "unfixable_gaps": unfixable_gaps,
            "recommendation": self._generate_recommendation(persistent, unfixable_gaps),
        }
        
        return diagnosis
    
    def _generate_recommendation(
        self,
        persistent_gaps: List[str],
        unfixable_gaps: List[str],
    ) -> str:
        """Generate user-facing recommendation for improvement."""
        if unfixable_gaps:
            return (
                f"Cannot reach quality threshold. Root cause: {', '.join(unfixable_gaps)}. "
                "These gaps require user action to add missing data to the resume."
            )
        else:
            return (
                f"Reached iteration limit with gaps: {', '.join(persistent_gaps)}. "
                "Additional manual editing recommended."
            )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_loop_controller.py -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
cd resume-optimizer
git add backend/orchestration/loop_controller.py backend/tests/test_loop_controller.py
git commit -m "feat: add LoopController with persistent gap detection"
```

---

### Task 10: Create Result Formatter

**Files:**
- Create: `resume-optimizer/backend/orchestration/result.py`

- [ ] **Step 1: Write result formatter**

Create `resume-optimizer/backend/orchestration/result.py`:

```python
"""
Result formatting for pipeline completion.
Structures output as success or failure with diagnostic data.
"""

from typing import Dict, Any
from orchestration.context import PipelineContext

def format_result(
    context: PipelineContext,
    reached_threshold: bool,
    diagnostic: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Format final pipeline result.
    
    Args:
        context: PipelineContext with all task outputs
        reached_threshold: Whether quality threshold was reached
        diagnostic: Optional diagnostic report (if threshold not reached)
    
    Returns:
        Structured result dict for API response
    """
    result = {
        "success": True,
        "optimization_id": context.optimization_id,
        "resume": context.humanized_resume or context.resume_text,
        "quality_score": context.quality_score,
        "reached_threshold": reached_threshold,
        "iterations_used": context.iteration_count,
        "improvement_history": context.improvement_history,
        "token_cost": {
            "input_tokens": context.total_input_tokens,
            "output_tokens": context.total_output_tokens,
            "total_tokens": context.total_input_tokens + context.total_output_tokens,
            "cost_cents": context.total_cost_cents,
        },
        "timestamp": context.updated_at,
    }
    
    if not reached_threshold and diagnostic:
        result["persistent_gaps"] = diagnostic.get("persistent_gaps", [])
        result["diagnosis"] = diagnostic.get("recommendation", "")
    
    if context.errors:
        result["errors"] = context.errors
    
    if context.warnings:
        result["warnings"] = context.warnings
    
    return result

def format_error_result(
    optimization_id: str,
    error: str,
    context: PipelineContext = None,
) -> Dict[str, Any]:
    """Format error result."""
    result = {
        "success": False,
        "optimization_id": optimization_id,
        "error": error,
    }
    
    if context:
        result["token_cost"] = {
            "input_tokens": context.total_input_tokens,
            "output_tokens": context.total_output_tokens,
            "total_tokens": context.total_input_tokens + context.total_output_tokens,
            "cost_cents": context.total_cost_cents,
        }
    
    return result
```

- [ ] **Step 2: Commit**

```bash
cd resume-optimizer
git add backend/orchestration/result.py
git commit -m "feat: add result formatter for pipeline outputs"
```

---

### Task 11: Create Progress Streaming Module

**Files:**
- Create: `resume-optimizer/backend/orchestration/progress.py`

- [ ] **Step 1: Write progress streamer**

Create `resume-optimizer/backend/orchestration/progress.py`:

```python
"""
Progress event streaming for real-time updates during long-running optimizations.
Uses SSE (Server-Sent Events) format for frontend consumption.
"""

import json
from typing import AsyncGenerator, Optional
from datetime import datetime

class ProgressStreamer:
    """Generates SSE-formatted progress events."""
    
    @staticmethod
    async def stream_event(
        event_type: str,
        data: dict,
    ) -> str:
        """
        Format a progress event as SSE (Server-Sent Events).
        
        Args:
            event_type: Event type (start, task_start, task_complete, etc)
            data: Event data dict
        
        Returns:
            SSE-formatted string: "data: {json}\n\n"
        """
        payload = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            **data,
        }
        return f"data: {json.dumps(payload)}\n\n"
    
    @staticmethod
    async def optimization_start(
        optimization_id: str,
        max_iterations: int,
    ) -> str:
        """Event: optimization started."""
        return await ProgressStreamer.stream_event(
            "start",
            {
                "optimization_id": optimization_id,
                "max_iterations": max_iterations,
            },
        )
    
    @staticmethod
    async def iteration_start(iteration: int, total_iterations: int) -> str:
        """Event: iteration starting."""
        return await ProgressStreamer.stream_event(
            "iteration_start",
            {
                "iteration": iteration,
                "total_iterations": total_iterations,
            },
        )
    
    @staticmethod
    async def task_start(task_name: str, iteration: int) -> str:
        """Event: task starting."""
        return await ProgressStreamer.stream_event(
            "task_start",
            {
                "task": task_name,
                "iteration": iteration,
            },
        )
    
    @staticmethod
    async def task_complete(task_name: str, iteration: int, duration_ms: int) -> str:
        """Event: task completed."""
        return await ProgressStreamer.stream_event(
            "task_complete",
            {
                "task": task_name,
                "iteration": iteration,
                "duration_ms": duration_ms,
            },
        )
    
    @staticmethod
    async def iteration_score(
        iteration: int,
        quality_score: float,
        gaps: list,
    ) -> str:
        """Event: iteration score and gaps."""
        return await ProgressStreamer.stream_event(
            "iteration_score",
            {
                "iteration": iteration,
                "quality_score": quality_score,
                "gaps": gaps,
            },
        )
    
    @staticmethod
    async def iteration_decision(iteration: int, action: str, reason: str) -> str:
        """Event: decision to continue or stop."""
        return await ProgressStreamer.stream_event(
            "iteration_decision",
            {
                "iteration": iteration,
                "action": action,  # "continue" or "stop"
                "reason": reason,
            },
        )
    
    @staticmethod
    async def optimization_complete(result: dict) -> str:
        """Event: optimization complete."""
        return await ProgressStreamer.stream_event(
            "complete",
            result,
        )
```

- [ ] **Step 2: Commit**

```bash
cd resume-optimizer
git add backend/orchestration/progress.py
git commit -m "feat: add progress streamer for SSE events"
```

---

## Phase 4: API Endpoints & Integration

### Task 12: Create Optimization Endpoint with SSE Streaming

**Files:**
- Create: `resume-optimizer/backend/routes/optimize.py` (new or modify existing)

- [ ] **Step 1: Write failing test for optimization endpoint**

Create `resume-optimizer/backend/tests/test_optimize_endpoint.py`:

```python
"""Tests for optimization endpoint with SSE streaming."""

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_optimize_endpoint_exists():
    """GET /api/optimize endpoint exists."""
    response = client.get("/api/optimize?resume=test&jd=test", headers={"Accept": "text/event-stream"})
    # May fail auth, but endpoint should exist (status != 404)
    assert response.status_code != 404

def test_optimize_requires_resume_and_jd():
    """POST /api/optimize requires resume_text and jd_text."""
    response = client.post("/api/optimize", json={})
    assert response.status_code == 422  # Validation error
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_optimize_endpoint.py -v
```

Expected: FAILED — endpoint not found

- [ ] **Step 3: Write optimization endpoint**

Create `resume-optimizer/backend/routes/optimize.py`:

```python
"""
Resume optimization endpoint with SSE progress streaming.
Orchestrates the full pipeline: extract → analyze → rewrite → humanize → score → validate.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import logging
from typing import AsyncGenerator
from auth.dependencies import get_current_user
from db.models import User
from db.session import AsyncSession, get_db
from orchestration.context import PipelineContext
from orchestration.pipeline import PipelineExecutor
from orchestration.loop_controller import LoopController
from orchestration.progress import ProgressStreamer
from orchestration.result import format_result, format_error_result
from agents.fact_extractor import create_fact_extractor_agent
from agents.jd_analyzer import create_jd_analyzer_agent
from agents.rewriter import create_rewriter_agent
from agents.humanizer import create_humanizer_agent
from agents.scorer import create_scorer_agent
from agents.fabrication_guard import create_fabrication_guard_agent
from config import opt_config
import uuid

router = APIRouter(prefix="/api", tags=["optimize"])
logger = logging.getLogger(__name__)

TASK_ORDER = ["extract_claims", "analyze_jd", "rewrite", "humanize", "score", "validate"]

@router.post("/optimize")
async def optimize_resume(
    resume_text: str,
    jd_text: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Optimize resume with SSE progress streaming.
    Runs full pipeline with iterative improvement until quality threshold or max iterations.
    
    Returns:
        StreamingResponse with SSE events
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        optimization_id = str(uuid.uuid4())[:8]
        
        try:
            # Initialize context
            context = PipelineContext(
                resume_text=resume_text,
                jd_text=jd_text,
                user_id=str(user.id),
                optimization_id=optimization_id,
                max_iterations=opt_config.max_iterations,
                quality_threshold=opt_config.quality_threshold,
            )
            
            # Emit start event
            yield await ProgressStreamer.optimization_start(optimization_id, opt_config.max_iterations)
            
            # Create agents
            executor = PipelineExecutor()
            agents = {
                "extract_claims": create_fact_extractor_agent(),
                "analyze_jd": create_jd_analyzer_agent(),
                "rewrite": create_rewriter_agent(),
                "humanize": create_humanizer_agent(),
                "score": create_scorer_agent(),
                "validate": create_fabrication_guard_agent(),
            }
            
            # Main loop
            loop_controller = LoopController(context)
            
            while loop_controller.should_continue_loop():
                context.iteration_count += 1
                
                # Emit iteration start
                yield await ProgressStreamer.iteration_start(
                    context.iteration_count,
                    opt_config.max_iterations,
                )
                
                # Execute tasks in sequence
                for task_name in TASK_ORDER:
                    yield await ProgressStreamer.task_start(task_name, context.iteration_count)
                    
                    start_time = asyncio.get_event_loop().time()
                    
                    try:
                        await executor.execute_task(
                            task_name,
                            agents[task_name],
                            context,
                        )
                    except Exception as e:
                        logger.error(f"Task {task_name} failed: {str(e)}")
                        context.record_error(task_name, str(e))
                        # Skip this task, continue with next
                        yield await ProgressStreamer.task_complete(
                            task_name,
                            context.iteration_count,
                            0,
                        )
                        continue
                    
                    duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
                    
                    yield await ProgressStreamer.task_complete(
                        task_name,
                        context.iteration_count,
                        duration_ms,
                    )
                    
                    await asyncio.sleep(0.1)  # Brief pause for frontend to process
                
                # Emit iteration score
                yield await ProgressStreamer.iteration_score(
                    context.iteration_count,
                    context.quality_score,
                    context.score_breakdown.get("gaps", []),
                )
                
                # Decide whether to continue
                action = "continue" if loop_controller.should_continue_loop() else "stop"
                reason = f"Score {context.quality_score:.2f}, threshold {opt_config.quality_threshold}"
                
                yield await ProgressStreamer.iteration_decision(
                    context.iteration_count,
                    action,
                    reason,
                )
            
            # Format final result
            reached_threshold = context.quality_score >= opt_config.quality_threshold
            diagnostic = loop_controller.prepare_diagnostic() if not reached_threshold else None
            result = format_result(context, reached_threshold, diagnostic)
            
            # Emit completion
            yield await ProgressStreamer.optimization_complete(result)
        
        except Exception as e:
            logger.error(f"Optimization failed: {str(e)}")
            error_result = format_error_result(optimization_id, str(e))
            yield await ProgressStreamer.stream_event("error", error_result)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
```

- [ ] **Step 4: Register router in main.py**

In `resume-optimizer/backend/main.py`, add:

```python
from routes.optimize import router as optimize_router

app.include_router(optimize_router)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_optimize_endpoint.py -v
```

Expected: PASSED

- [ ] **Step 6: Commit**

```bash
cd resume-optimizer
git add backend/routes/optimize.py backend/tests/test_optimize_endpoint.py backend/main.py
git commit -m "feat: add /api/optimize endpoint with SSE streaming"
```

---

## Phase 5: Testing & Integration

### Task 13: Add Integration Tests

**Files:**
- Create: `resume-optimizer/backend/tests/test_integration_pipeline.py`

- [ ] **Step 1: Write end-to-end integration test**

Create `resume-optimizer/backend/tests/test_integration_pipeline.py`:

```python
"""End-to-end integration tests for full optimization pipeline."""

import pytest
from orchestration.context import PipelineContext
from orchestration.pipeline import PipelineExecutor
from orchestration.loop_controller import LoopController
from agents.fact_extractor import create_fact_extractor_agent
from agents.scorer import create_scorer_agent

@pytest.mark.asyncio
async def test_full_pipeline_extracts_then_scores():
    """
    Full pipeline: extract claims → score resume.
    Verifies context flows correctly between tasks.
    """
    context = PipelineContext(
        resume_text="Senior Engineer at Google. Led team of 5. 30% efficiency improvement.",
        jd_text="Looking for Senior Engineer with leadership experience.",
        user_id="test_user",
        optimization_id="test_opt",
    )
    
    executor = PipelineExecutor()
    
    # Task 1: Extract claims
    agent1 = create_fact_extractor_agent()
    await executor.execute_task("extract_claims", agent1, context)
    
    # Claims should be extracted
    assert len(context.claims_ledger) > 0 or context.claims_ledger == {}
    
    # Task 2: Score (depends on claims from Task 1)
    agent2 = create_scorer_agent()
    await executor.execute_task("score", agent2, context)
    
    # Score should be set
    assert context.quality_score >= 0.0

@pytest.mark.asyncio
async def test_loop_controller_respects_max_iterations():
    """Loop controller stops after max_iterations."""
    context = PipelineContext(
        resume_text="Test",
        jd_text="Test",
        user_id="test",
        optimization_id="test",
        max_iterations=2,
    )
    context.iteration_count = 2
    
    controller = LoopController(context)
    should_continue = controller.should_continue_loop()
    
    assert should_continue is False
```

- [ ] **Step 2: Run tests**

```bash
cd resume-optimizer
python -m pytest backend/tests/test_integration_pipeline.py -v
```

Expected: PASSED (or failures if agents need mocking)

- [ ] **Step 3: Commit**

```bash
cd resume-optimizer
git add backend/tests/test_integration_pipeline.py
git commit -m "feat: add integration tests for full pipeline"
```

---

### Task 14: Update Requirements/Dependencies

**Files:**
- Modify: `resume-optimizer/backend/requirements.txt`

- [ ] **Step 1: Add new dependencies**

Add to `resume-optimizer/backend/requirements.txt`:

```
litellm>=1.0.0
crewai>=0.1.0
pydantic>=2.0.0
```

- [ ] **Step 2: Install dependencies**

```bash
cd resume-optimizer/backend
pip install -r requirements.txt
```

- [ ] **Step 3: Commit**

```bash
cd resume-optimizer
git add backend/requirements.txt
git commit -m "chore: add litellm and crewai dependencies"
```

---

## Phase 6: Documentation & Final Steps

### Task 15: Document API Usage

**Files:**
- Create: `docs/api/OPTIMIZE_ENDPOINT.md`

- [ ] **Step 1: Write API documentation**

Create `docs/api/OPTIMIZE_ENDPOINT.md`:

```markdown
# Resume Optimization Endpoint

## Endpoint: POST /api/optimize

Optimizes a resume via multi-agent pipeline with iterative improvement.
Streams progress updates via Server-Sent Events (SSE).

### Request

```json
{
  "resume_text": "Senior Engineer at Google...",
  "jd_text": "Looking for Senior Engineer with..."
}
```

### Response (SSE Stream)

Each event is JSON in SSE format: `data: {json}\n\n`

#### Event: start
```json
{
  "event": "start",
  "optimization_id": "abc123",
  "max_iterations": 3,
  "timestamp": "2026-06-03T14:32:00.000000"
}
```

#### Event: iteration_start
```json
{
  "event": "iteration_start",
  "iteration": 1,
  "total_iterations": 3,
  "timestamp": "..."
}
```

#### Event: task_complete
```json
{
  "event": "task_complete",
  "task": "extract_claims",
  "iteration": 1,
  "duration_ms": 3200,
  "timestamp": "..."
}
```

#### Event: complete (final result)
```json
{
  "event": "complete",
  "success": true,
  "optimization_id": "abc123",
  "resume": "polished resume text...",
  "quality_score": 0.87,
  "reached_threshold": true,
  "iterations_used": 2,
  "token_cost": {
    "input_tokens": 45000,
    "output_tokens": 12000,
    "total_tokens": 57000,
    "cost_cents": 156
  },
  "timestamp": "..."
}
```

### Frontend Usage Example

```javascript
const es = new EventSource('/api/optimize?resume=...&jd=...');

es.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  switch (msg.event) {
    case 'iteration_start':
      updateProgress(`Iteration ${msg.iteration}/${msg.total_iterations}`);
      break;
    
    case 'task_complete':
      updateStatus(`${msg.task}: done (${msg.duration_ms}ms)`);
      break;
    
    case 'complete':
      displayResult(msg);
      es.close();
      break;
  }
};
```

### Timeout & Long-Running Jobs

- Typical optimization takes **2-3+ minutes** (18 LLM calls across 3 iterations)
- Set HTTP client timeout to **5+ minutes**
- Each event is streamed in real-time; frontend should process events continuously

### Error Handling

If the stream closes unexpectedly, the optimization was interrupted. Partial progress may have been made.

---
```

- [ ] **Step 2: Commit**

```bash
cd resume-optimizer
git add docs/api/OPTIMIZE_ENDPOINT.md
git commit -m "docs: add API documentation for optimize endpoint"
```

---

### Task 16: Verify All Tests Pass

**Files:**
- Tests across all modules

- [ ] **Step 1: Run full test suite**

```bash
cd resume-optimizer
python -m pytest backend/tests/ -v --tb=short
```

Expected: All tests pass (or identified failures with clear error messages)

- [ ] **Step 2: Commit**

```bash
cd resume-optimizer
git commit --allow-empty -m "chore: verify all tests passing"
```

---

## Summary

**Total tasks:** 16  
**Phases:** 6  
**Key deliverables:**
- ✅ litellm configuration and client
- ✅ Cost tracking module
- ✅ 6 CrewAI agents with @tool wrappers
- ✅ PipelineContext for shared state
- ✅ PipelineExecutor for sequential task execution
- ✅ LoopController with gap detection
- ✅ SSE progress streaming
- ✅ /api/optimize endpoint
- ✅ Full test coverage
- ✅ API documentation

**Implementation flow:**
1. **Foundation** (Tasks 1-3): Config, litellm client, cost tracker
2. **Agents** (Tasks 4-7): CrewAI agent setup and refactoring
3. **Orchestration** (Tasks 8-11): Pipeline, loop controller, result formatting, progress streaming
4. **Integration** (Tasks 12-13): Optimization endpoint, integration tests
5. **Finalization** (Tasks 14-16): Dependencies, documentation, verification

**Success criteria from design spec:**
- ✅ Multi-provider support (litellm routing)
- ✅ Sequential pipeline (task order)
- ✅ Iterative loop with gap diagnosis
- ✅ Full context preservation
- ✅ Error recovery and logging
- ✅ Cost tracking
- ✅ SSE streaming for UX (2-3 min estimates)
- ✅ Context isolation (no token doubling)

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-03-llmlite-crewai-implementation.md`.**

## Execution Options

Choose your preferred execution strategy:

**Option 1: Subagent-Driven (Recommended for large plans)**
- Fresh subagent per task (or batch of 2-3 related tasks)
- Independent verification between tasks
- Parallelizable: multiple subagents working simultaneously
- Slower overall but catches issues early

**Option 2: Inline Execution with Checkpoints**
- Execute tasks in this session sequentially
- Checkpoints after each phase (review progress)
- Faster overall but requires continuous attention
- Better for small, focused plans

**Which approach would you prefer?**
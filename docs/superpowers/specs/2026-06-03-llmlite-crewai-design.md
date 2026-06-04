# Multi-Provider LLM + CrewAI Agent Orchestration Design

**Date:** 2026-06-03  
**Author:** Brainstorming Session  
**Status:** Approved Design  

---

## Executive Summary

Replace the current hardcoded LLM routing (llm.py) with **llmlite** for multi-provider flexibility (OpenAI, Anthropic, Together AI, Ollama), and refactor agents into a **CrewAI** framework for orchestrated sequential pipelines + iterative quality loops. Remove token limits to preserve full context across resume optimization workflows.

**Goals:**
1. Support multiple LLM providers with zero agent code changes (provider switching at config level only)
2. Enable sequential agent pipelines (extract → rewrite → humanize → score → validate)
3. Implement iterative improvement loops with quality thresholds and gap diagnosis
4. Preserve full context (no token truncation between tasks)
5. Provide structured diagnostic reports when quality thresholds cannot be reached

---

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────┐
│   Config (provider + model)          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  llmlite (unified LLM abstraction)   │
│  - OpenAI, Anthropic, Together, etc  │
│  - Token counting & cost tracking    │
│  - Retry + fallback logic            │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  CrewAI (agent orchestration)        │
│  ├─ Fact Extractor Agent            │
│  ├─ JD Analyzer Agent                │
│  ├─ Rewriter Agent                   │
│  ├─ Humanizer Agent                  │
│  ├─ Scorer Agent                     │
│  └─ Fabrication Guard Agent          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  Task Pipeline (sequential)          │
│  1. Extract Claims                   │
│  2. Analyze Job Description          │
│  3. Rewrite Resume                   │
│  4. Humanize Language                │
│  5. Score Quality                    │
│  6. Validate Claims                  │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│  Loop Controller                     │
│  ├─ Evaluate quality_score           │
│  ├─ Identify gaps                    │
│  └─ Iterate or terminate             │
└─────────────────────────────────────┘
```

### Component Responsibilities

**llmlite (replaces llm.py):**
- Single config file: `LLM_PROVIDER`, `LLM_MODEL`, `MAX_CONTEXT_TOKENS`
- Routes calls to correct provider SDK (no per-agent config)
- Token counting, cost tracking, automatic retry/fallback
- Async-first design

**CrewAI Layer:**
- Defines 6 agents with roles, goals, backstories
- Wraps existing agent functions as `@tool` decorators
- Manages task execution, context passing, state
- Handles sequential pipelines natively

**Pipeline Controller:**
- Orchestrates sequential task execution
- Maintains shared context dict (prevents token loss)
- Feeds each task's output to the next task as input

**Loop Controller:**
- Evaluates quality_score after each iteration
- Extracts gaps from score_breakdown
- Determines if threshold is reachable (by tracking persistent gaps)
- Terminates with diagnostic report if max_iterations reached

---

## Token Management Strategy

### Problem Statement
- Current system: hardcoded `max_tokens=8096` truncates context
- Resume optimization loses critical details (metrics, experience, job description)
- Multi-step workflows accumulate context; current approach discards intermediate outputs

### Solution

**Per-provider limits (config-based):**
```
PROVIDER=anthropic    → MAX_CONTEXT=200000  (Claude Opus 4.8)
PROVIDER=openai       → MAX_CONTEXT=128000  (GPT-4o)
PROVIDER=together     → MAX_CONTEXT=32000   (Llama 3.1)
PROVIDER=ollama       → MAX_CONTEXT=8000    (local model, conservative)
```

**Context preservation:**
1. Each task output stored in `PipelineContext` dict (shared state)
2. Next task receives full context from prior steps
3. No intermediate outputs discarded between tasks
4. CrewAI's task history maintains full conversation

**Intelligent truncation (fallback only):**
- If a single prompt + context exceeds provider limit:
  1. Log warning with token count
  2. Truncate only the tail end (preserve head/summary)
  3. Include note in output: "Context truncated at {token_count}"
- Goal: rare edge case, not the happy path

**Cost tracking:**
- Accumulate `input_tokens + output_tokens` across entire pipeline
- Store in DB: `(user_id, optimization_id, total_tokens, cost_cents, timestamp)`
- Use for billing, usage analytics, dashboard

---

## Agent Definitions (CrewAI Mapping)

### Existing Agents → CrewAI Agents

Each agent becomes a CrewAI `Agent` paired with a `Tool`:

```python
# agents/fact_extractor.py (refactored)
from crewai import Agent, Task
from llmlite import LLMClient

@tool
def extract_claims_tool(resume_text: str) -> dict:
    """Extracts claims ledger from resume."""
    return extract_claims(resume_text)  # existing function

fact_extractor_agent = Agent(
    role="Fact Extractor",
    goal="Extract and validate all claims, metrics, companies from resume",
    backstory="You are an expert at identifying factual content...",
    tools=[extract_claims_tool],
    llm=llm_client,  # injected llmlite instance
    verbose=True,
)
```

### Agent Specifications

| Agent | Role | Input | Output | Tool |
|-------|------|-------|--------|------|
| **Fact Extractor** | Extract verifiable claims | resume_text | claims_ledger dict | extract_claims_tool |
| **JD Analyzer** | Parse job requirements | jd_text, resume_text | jd_analysis dict | analyze_jd_tool |
| **Rewriter** | Strengthen bullets | resume_text, claims_ledger, gaps | rewritten_resume | rewrite_tool |
| **Humanizer** | Polish language | rewritten_resume | humanized_resume | humanize_tool |
| **Scorer** | Evaluate quality | humanized_resume, jd_analysis, claims_ledger | quality_score + breakdown | score_tool |
| **Fabrication Guard** | Validate claims | humanized_resume, claims_ledger | validation_report | validate_tool |

---

## Sequential Pipeline & Iterative Loop

### Task Pipeline (Sequential Execution)

```
Task 1: Extract Claims
  Agent: Fact Extractor
  Input: resume_text
  Output: context.claims_ledger = {...}
  
Task 2: Analyze Job Description
  Agent: JD Analyzer
  Input: jd_text, resume_text
  Output: context.jd_analysis = {...}
  
Task 3: Rewrite Resume
  Agent: Rewriter
  Input: resume_text, claims_ledger, improvement_gaps (from prior iteration)
  Output: context.rewritten_resume = "..."
  
Task 4: Humanize Resume
  Agent: Humanizer
  Input: rewritten_resume
  Output: context.humanized_resume = "..."
  
Task 5: Score Resume
  Agent: Scorer
  Input: humanized_resume, jd_analysis, claims_ledger
  Output: context.score_breakdown = {...}, context.quality_score = 0.0-1.0
  
Task 6: Validate Claims
  Agent: Fabrication Guard
  Input: humanized_resume, claims_ledger
  Output: context.validation_report = {...}
```

### Iterative Loop Controller

```
Loop Logic:
  iteration = 0
  max_iterations = 3
  threshold = 0.85
  
  while iteration < max_iterations:
    1. Execute Tasks 1-6 (pipeline)
    2. quality_score = context.quality_score
    3. gaps = context.score_breakdown['gaps']
    
    if quality_score >= threshold:
      ✓ Return result (success)
    
    if gaps == previous_gaps:  # persistent gaps
      ✗ Return result with diagnosis (threshold unreachable)
    
    # Prepare for next iteration
    context.improvement_history.append({
      "iteration": iteration,
      "quality_score": quality_score,
      "gaps": gaps,
      "timestamp": now(),
    })
    iteration += 1
  
  # Max iterations reached
  ✗ Return result with diagnosis (max iterations exhausted)
```

### Gap Pinpointing Strategy

**During loop:**
- Track gaps per iteration: `[iter1_gaps, iter2_gaps, iter3_gaps]`
- Identify persistent gaps: `set(iter1) ∩ set(iter2) ∩ set(iter3)`
- Classify gaps:
  - **Fixable:** "Weak action verbs" → agent can improve
  - **Unfixable:** "No metrics in source" → agent cannot invent data
  - **Degrading:** Score improved but different gaps emerged

**In diagnostic report:**
```python
{
  "success": True,
  "resume": "best attempt",
  "quality_score": 0.83,
  "reached_threshold": False,
  "iterations_used": 3,
  "persistent_gaps": ["No quantifiable metrics in experience section"],
  "diagnosis": "Cannot reach 0.85 threshold. Root cause: Resume source material lacks quantifiable achievements. Improvement strategy: User should add metrics to resume (e.g., '15% cost reduction', '3x faster deployment').",
}
```

---

## Data Structures

### PipelineContext (Shared State)

```python
from dataclasses import dataclass, field
from typing import Any, list, dict

@dataclass
class PipelineContext:
    """Shared state across all pipeline tasks."""
    
    # Input
    resume_text: str
    jd_text: str
    user_id: str
    optimization_id: str
    
    # Configuration
    max_iterations: int = 3
    quality_threshold: float = 0.85
    
    # Task outputs
    claims_ledger: dict = field(default_factory=dict)
    jd_analysis: dict = field(default_factory=dict)
    rewritten_resume: str = ""
    humanized_resume: str = ""
    score_breakdown: dict = field(default_factory=dict)
    validation_report: dict = field(default_factory=dict)
    
    # Loop tracking
    iteration_count: int = 0
    quality_score: float = 0.0
    improvement_history: list = field(default_factory=list)
    persistent_gaps: list = field(default_factory=list)
    
    # Token/cost tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_cents: int = 0
    
    # Error tracking
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
```

### Scorer Agent Output Format

```python
{
    "quality_score": 0.78,  # 0-1
    "score_breakdown": {
        "metrics_presence": 0.6,      # % bullets with quantified metrics
        "action_verbs": 0.9,          # strength of action verbs
        "jd_alignment": 0.8,          # keyword overlap with job description
        "readability": 0.85,          # sentence structure, length
        "claim_validity": 0.95,       # no fabrications detected
    },
    "gaps": [
        "Only 40% of bullets have metrics (target: 80%)",
        "Missing keywords: [kubernetes, microservices]",
        "3 bullets exceed recommended length (50 chars)",
    ],
    "improvement_suggestions": [
        "Add quantified impact to 'Led design reviews' bullet",
        "Replace 'Responsible for' with stronger action verb",
    ]
}
```

### Final Result (Success)

```python
{
    "success": True,
    "optimization_id": "opt_abc123",
    "resume": "final humanized resume text",
    "quality_score": 0.87,
    "reached_threshold": True,
    "iterations_used": 2,
    "improvement_history": [
        {"iteration": 1, "quality_score": 0.78, "gaps": [...]},
        {"iteration": 2, "quality_score": 0.87, "gaps": []},
    ],
    "token_cost": {
        "input_tokens": 45000,
        "output_tokens": 12000,
        "total_tokens": 57000,
        "cost_cents": 156,  # provider-specific pricing
    },
    "timestamp": "2026-06-03T14:32:00Z",
}
```

### Final Result (Threshold Not Reached)

```python
{
    "success": True,
    "optimization_id": "opt_abc123",
    "resume": "best attempt (score 0.83)",
    "quality_score": 0.83,
    "reached_threshold": False,
    "iterations_used": 3,
    "improvement_history": [
        {"iteration": 1, "quality_score": 0.78, "gaps": ["no metrics", "weak verbs"]},
        {"iteration": 2, "quality_score": 0.82, "gaps": ["no metrics"]},
        {"iteration": 3, "quality_score": 0.83, "gaps": ["no metrics"]},
    ],
    "persistent_gaps": ["No quantifiable metrics in source material"],
    "diagnosis": "Cannot reach 0.85 threshold after 3 iterations. Root cause: Resume source material lacks quantifiable achievements. Recommendation: User should add specific metrics to their experience section.",
    "token_cost": {...},
    "timestamp": "2026-06-03T14:32:00Z",
}
```

---

## Error Handling

### Failure Modes & Recovery

| Failure | Cause | Recovery |
|---------|-------|----------|
| **Provider unavailable** | API down, rate limit | Retry with exponential backoff; fall back to secondary provider |
| **Token limit exceeded** | Context too large | Log warning; truncate tail intelligently; continue |
| **Task timeout** | LLM slow to respond | Retry once; abort task and skip iteration if second attempt fails |
| **Malformed agent output** | JSON parse error | Log error; use fallback output; continue (don't fail pipeline) |
| **Quality score unavailable** | Scorer agent fails | Skip iteration, treat as score=0, continue loop |

### Logging & Monitoring

- Log every task start/end with task name, duration, token counts
- Log every iteration with quality_score, gaps, timestamp
- Log warnings for truncation, retries, fallbacks
- Log final result: success/failure, threshold reached, iterations, cost

---

## File Structure

```
resume-optimizer/backend/
├── llm/
│   ├── __init__.py
│   ├── llmlite_client.py          # NEW: llmlite wrapper
│   ├── config.py                   # MOVED: provider config
│   └── cost_tracker.py             # NEW: token + cost tracking
│
├── agents/
│   ├── __init__.py
│   ├── base.py                     # NEW: base CrewAI Agent setup
│   ├── fact_extractor.py           # REFACTOR: extract_claims → Agent + Tool
│   ├── jd_analyzer.py              # REFACTOR: analyze_jd → Agent + Tool
│   ├── rewriter.py                 # REFACTOR: rewrite_resume → Agent + Tool
│   ├── humanizer.py                # REFACTOR: humanize_resume → Agent + Tool
│   ├── scorer.py                   # REFACTOR: score_resume → Agent + Tool
│   └── fabrication_guard.py        # REFACTOR: validate → Agent + Tool
│
├── orchestration/
│   ├── __init__.py
│   ├── pipeline.py                 # NEW: sequential task execution
│   ├── loop_controller.py          # NEW: quality loop + gap detection
│   ├── context.py                  # NEW: PipelineContext dataclass
│   └── result.py                   # NEW: result formatting
│
├── tests/
│   ├── test_agents.py              # EXISTING (update fixtures)
│   ├── test_pipeline.py            # NEW: pipeline integration tests
│   ├── test_loop_controller.py     # NEW: loop logic tests
│   └── test_llmlite_client.py      # NEW: provider routing tests
│
└── routes/
    └── optimize.py                 # NEW/MODIFY: endpoint that uses pipeline
```

---

## Implementation Notes

### Dependencies
```
crewai>=0.1.0
llmlite>=0.5.0  # or llama-index if preferred
anthropic>=0.34.0
openai>=1.0.0
```

### Backwards Compatibility
- Existing agent functions (`extract_claims`, `humanize_resume`, etc.) are preserved
- Wrap them in `@tool` decorators; they don't change
- `llm.complete()` call sites are refactored to use CrewAI's task execution

### Testing Strategy
- Unit tests for each agent (existing patterns)
- Integration tests for pipeline (sequential execution)
- Loop controller tests (threshold logic, gap detection)
- Provider routing tests (llmlite client)
- End-to-end tests (full pipeline with mock data)

### Performance Considerations
- CrewAI's sequential execution is synchronous; agents don't run in parallel (acceptable for sequential pipeline)
- Token counting happens per-call (negligible overhead)
- Context dict passed by reference (no copying overhead)
- Expect ~30-60s per optimization (3 tasks × multiple LLM calls)

---

## Success Criteria

✓ Multi-provider support: Config change switches provider (no code change)  
✓ Sequential pipeline: Tasks execute in order, outputs flow through context  
✓ Iterative loop: Quality threshold drives iterations; gap diagnosis provided  
✓ Token preservation: No truncation between tasks; full context passed  
✓ Error recovery: Provider fallback, retry logic, graceful degradation  
✓ Cost tracking: Token counts and costs accumulated and logged  
✓ Backwards compatible: Existing agent functions unchanged (wrapped, not rewritten)  

---

## Out of Scope

- Parallel agent execution (sequential only for now)
- Agent self-correction loops (loop controller handles orchestration)
- Custom model fine-tuning (use base models only)
- Frontend visualization of iteration history (API returns data; frontend decides)

---

## Appendix: Configuration Example

```yaml
# config.yaml
llm:
  provider: anthropic  # or openai, together, ollama
  model: claude-opus-4-8
  max_context_tokens: 200000
  temperature: 0.7
  timeout_seconds: 60

optimization:
  max_iterations: 3
  quality_threshold: 0.85
  
  # Provider-specific fallbacks
  fallback_provider: openai
  fallback_model: gpt-4o

logging:
  level: INFO
  include_tokens: true  # log token counts
  include_costs: true   # log cost per call
```

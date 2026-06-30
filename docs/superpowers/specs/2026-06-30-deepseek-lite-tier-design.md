# DeepSeek V4 adoption — design + measured outcomes

**Date:** 2026-06-30
**Status:** Implemented (optimizer tier); lite tier evaluated and declined
**Author:** brainstorm + benchmarking with Atharva

> This started as a plan to move the **lite tier** to DeepSeek. Benchmarking
> reversed that: DeepSeek V4 **Pro** became the optimizer; the lite tier stayed
> on Gemini Flash Lite. This doc records the design and the measured results that
> drove the decision.

## Outcome summary

| Tier | Before | After | Why |
|------|--------|-------|-----|
| **Optimizer** (`MODEL_OPTIMIZER`) | groq/openai/gpt-oss-120b | **deepseek/deepseek-v4-pro** (max) | parallel tool-calling: 2-3 turns vs 12, ~2x faster, no fabrication |
| **Lite tier** (`gemini-3.1-flash-lite`, ~12 calls) | Gemini Flash Lite | **unchanged** | V4 Flash max = 4-9x slower for no quality gain; high competitive but not a clear win + fabrication risk |

## Measured benchmarks (strategist, 1 reflection, stubbed tools)

| Model | Turns | Wall time | Cost | Note |
|-------|-------|-----------|------|------|
| gpt-oss-120b (baseline) | 12 | 58.1s | $0.0029 | sequential, one tool/turn |
| deepseek-v4-pro (max) | 2-3 | ~28s | $0.0015 | parallel tools |
| deepseek-v4-pro (high) | 3 | ~31s | $0.0024 | ≈ max (structured output bounds thinking) |
| claude-haiku-4-5 | 2 | 14.9s | $0.0066 | fastest, but 4.4x cost + needs system-msg fix |

Lite tier (free-text rewrite): Gemini Flash Lite ~5.8s/$0.00006 vs V4 Flash **max**
15-33s (variable) / ~$0.0005, **high** ~8.5s/$0.0001. Max thinking on the lite hot
loop is wasteful; even high is only a close backup, not an upgrade.

## What shipped (code)

### `config.py`
- `MODEL_OPTIMIZER = os.environ.get("MODEL_OPTIMIZER", "deepseek/deepseek-v4-pro")` (env-overridable rollback)
- `DEEPSEEK_API_KEY`, `DEEPSEEK_REASONING_EFFORT` (default `"max"`)
- Lite-tier constants unchanged (`gemini-3.1-flash-lite`)

### `llm.py`
- `_deepseek_extra_body(model)` — passes `reasoning_effort` + `thinking:enabled` via
  `extra_body` because LiteLLM strips `reasoning_effort` (litellm #27439). Applied in
  both `complete()` and `complete_with_tools()`. Remove the hack when PR #28702 lands.
- `complete()` response_format: DeepSeek folded into the groq branch (json_object,
  not json_schema).
- Hardened `cached_tok` to coerce non-int → 0 (bold-tesla caching bug).

### `orchestration/agent_loop.py`, `debate_loop.py`
- Preserve `reasoning_content` when re-appending the assistant turn — DeepSeek V4
  thinking models require it echoed back or the next turn errors (litellm #26395).

### `utils/cost.py`
- Prefer `response._hidden_params["response_cost"]` (LiteLLM's call-time cost) before
  `completion_cost()`, which fails to remap prefix-stripped names for groq/deepseek and
  was logging **$0** for all Groq calls. Type-guarded against mock responses.

## Verified facts (June 2026)

- Model ids: `deepseek/deepseek-v4-flash` (13B), `deepseek/deepseek-v4-pro` (49B).
  Legacy `deepseek-chat`/`deepseek-reasoner` hard-retire **2026-07-24 15:59 UTC**.
- `extra_body` max-thinking workaround confirmed: 2,720→7,891 reasoning chars vs plain.
- On the optimizer, max ≈ high (structured tool-call output bounds the thinking);
  on free-text lite tasks, max balloons (2,630 tokens for one bullet).

## Infrastructure / secret plumbing (Terraform) — TODO (not yet done)

To reach the deployed Azure app, mirror the Groq secret path (not yet implemented):
- `infra/variables.tf`: `deepseek_api_key` (sensitive)
- `infra/key_vault.tf`: secret `DEEPSEEK-API-KEY`
- `infra/app_service.tf`: `DEEPSEEK_API_KEY` KV reference + `MODEL_OPTIMIZER` /
  `DEEPSEEK_REASONING_EFFORT` app settings
- `.github/workflows/terraform.yml`: `TF_VAR_deepseek_api_key` in plan + apply jobs
- GitHub secret `TF_VAR_DEEPSEEK_API_KEY` (operator action)

## Known issues / follow-ups

- **Anthropic optimizer is broken** in the loop: `agent_loop.py` sends a system-only
  first message, which Claude rejects ("requires at least one non-system message").
  Only matters if `MODEL_OPTIMIZER` is set to a Claude model — fix by seeding a user
  turn or `litellm.modify_params=True`. Not triggered by the DeepSeek default.
- **Data residency / PII:** direct DeepSeek API is China-hosted; resumes are PII —
  conscious operator decision. Western-host routing (Fireworks/Together) is the fallback.
- **Latency variance:** V4 Pro max ~27-31s/run is acceptable; V4 Flash max on the lite
  loop was rejected partly for 9-26s variance.
- **Gemini key:** the scorer/JD-analyzer need a real `AIza…` AI Studio key (the
  `AQ.…` OAuth-style token throttles intermittently as a 400).

## Rollback

`MODEL_OPTIMIZER` env var → any prior model. Lite tier untouched. The loop
`reasoning_content` preservation is a no-op for non-DeepSeek models, so it stays.

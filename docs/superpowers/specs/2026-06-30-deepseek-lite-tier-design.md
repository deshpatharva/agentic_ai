# DeepSeek V4 adoption — lite tier (Flash) + optimizer (Pro), max effort — design

**Date:** 2026-06-30
**Status:** Approved (design), pending implementation plan
**Author:** brainstorm with Atharva

## Problem

Two model tiers move to DeepSeek V4, both with thinking at **max** reasoning effort,
switchable via env and reversible, and reaching the **deployed Azure app** (not just
local dev) through Terraform → Key Vault → App Service:

1. **Lite tier** — the ~13 cheap/fast constants hardcoded to
   `gemini/gemini-3.1-flash-lite` → **`deepseek/deepseek-v4-flash`**.
2. **Optimizer / strategist** — `MODEL_OPTIMIZER` (`groq/openai/gpt-oss-120b`),
   the agentic Phase-2 reasoner → **`deepseek/deepseek-v4-pro`**.

The optimizer is **multi-turn tool-calling** (`complete_with_tools` looping up to
`AGENT_MAX_ITER=10` in `agent_loop.py` and `debate_loop.py`), which interacts with a
known V4 multi-turn bug — see §3.

## Goals

- Flip lite tier and optimizer to DeepSeek V4 (or back) via env vars; no regression
  for the Gemini/Groq defaults.
- Drive DeepSeek thinking at **max** effort and have it actually reach the API.
- Make the optimizer's multi-turn loop V4-Pro-safe (preserve `reasoning_content`).
- Provision `DEEPSEEK_API_KEY` end-to-end via Terraform/Key Vault to the app.

## Non-goals

- Changing the chat agent (`MODEL_CHAT_AGENT = gemini-2.5-flash`) or the groq
  critic/verifier. Not in scope.
- Western-host routing for DeepSeek. Direct DeepSeek API; data-residency noted only.

## Key facts (verified against current docs, June 2026)

- **Model ids:** `deepseek/deepseek-v4-flash` (13B active) and
  `deepseek/deepseek-v4-pro` (49B active), released 2026-04-24. Legacy
  `deepseek-chat`/`deepseek-reasoner` are **hard-retired 2026-07-24 15:59 UTC** —
  must not be used.
- **Max effort does NOT pass through stock LiteLLM** (litellm #27439): it discards
  `reasoning_effort` and always sends `thinking:{"type":"enabled"}`. No released fix
  (PR #28702 open). **Workaround:** send the field raw via `extra_body`.
- **V4 multi-turn requires `reasoning_content` echoed back** (litellm #26395): an
  assistant turn that carried reasoning must include it when re-sent, or the next
  turn errors / strips it. Our loops currently drop it (§3).
- Thinking mode **silently ignores** `temperature`/`top_p`/`presence_penalty`/
  `frequency_penalty`.

## Design

### 1. Config knobs (`config.py`)

```python
DEEPSEEK_API_KEY          = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_REASONING_EFFORT = os.environ.get("DEEPSEEK_REASONING_EFFORT", "max")

# Lite tier
MODEL_LITE = os.environ.get("MODEL_LITE", "gemini/gemini-3.1-flash-lite")
# ... all ~13 flash-lite constants default to MODEL_LITE, each still
#     individually env-overridable, e.g.:
MODEL_SCORER = os.environ.get("MODEL_SCORER", MODEL_LITE)
# (MODEL_REWRITER, MODEL_REWRITER_FAST, MODEL_HUMANIZER, MODEL_REVIEWER,
#  MODEL_JD_ANALYZER, MODEL_PROFILE_PARSER, MODEL_INTERVIEW_SYNTH,
#  MODEL_KEYWORD_INJECT, MODEL_BULLET_STRENGTHEN, MODEL_SKILLS_REWRITE,
#  MODEL_SECTION_HUMANIZE)

# Optimizer / strategist (separate tier — agentic, multi-turn)
MODEL_OPTIMIZER = os.environ.get("MODEL_OPTIMIZER", "groq/openai/gpt-oss-120b")
```
LiteLLM auto-reads `DEEPSEEK_API_KEY` for `deepseek/...` models.
A single `DEEPSEEK_REASONING_EFFORT` (default `max`) governs **every** DeepSeek
call, keeping `llm.py` model-agnostic — no per-call-site effort plumbing.
Flip tiers: `MODEL_LITE=deepseek/deepseek-v4-flash`,
`MODEL_OPTIMIZER=deepseek/deepseek-v4-pro`.

**Untouched** (not in scope): `MODEL_CRITIC`, `MODEL_VERIFIER` (groq),
`MODEL_CHAT_AGENT` (gemini-2.5-flash).

### 2. DeepSeek call handling (`llm.py`)

Add a small helper and apply it in **both** `complete()` and
`complete_with_tools()` (the optimizer uses both — single-shot in
`agents/tools.py:491`, multi-turn in the loops):

```python
def _deepseek_extra_body(model: str) -> dict | None:
    # Workaround for litellm #27439: reasoning_effort is stripped by the mapper,
    # so pass it raw via extra_body (LiteLLM forwards it untouched). Remove once
    # litellm PR #28702 ships and pass reasoning_effort natively.
    if _provider(model) != "deepseek":
        return None
    return {"reasoning_effort": DEEPSEEK_REASONING_EFFORT, "thinking": {"type": "enabled"}}
```
- In `complete()`: set `call_kwargs["extra_body"]` from the helper when present.
- In `complete_with_tools()`: same, alongside the existing `tools`/`tool_choice`.
- **Structured output** (`complete()`, currently `llm.py:116-125`): DeepSeek
  supports `json_object` not `json_schema`, so fold into the groq branch:
  ```python
  elif provider in ("groq", "deepseek"):
      if response_format.get("type") == "json_schema":
          call_kwargs["response_format"] = {"type": "json_object"}
      else:
          call_kwargs["response_format"] = response_format
  ```
  json_object requires the literal word "json" in the prompt — verified in the
  scorer (`scorer.py:140,143,163`); confirm JD analyzer too.

### 3. Optimizer multi-turn fix (`agent_loop.py`, `debate_loop.py`)

Both loops re-append the assistant message dropping `reasoning_content`
(`agent_loop.py:275-279`, `debate_loop.py:110-114`). For V4 Pro this breaks turn 2
(litellm #26395). Preserve it when present:
```python
assistant_msg = {"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls or None}
rc = getattr(msg, "reasoning_content", None)
if rc:
    assistant_msg["reasoning_content"] = rc
messages.append(assistant_msg)
```
Harmless for non-DeepSeek models (attribute absent → skipped). `complete_with_tools`
already degrades to a no-tools plain completion if a provider mishandles the tools
param — a safety net if V4 Pro + function-calling misbehaves, but verify tool calls
work under thinking mode during implementation.

### 4. Cost tracking

`resolve_cost` (`utils/cost.py`) calls `litellm.completion_cost` first; LiteLLM
ships V4 Flash + Pro pricing, so cost resolves automatically (source `litellm`),
including thinking/reasoning output tokens (billed within `completion_tokens`).
Optional `deepseek` `ProviderCost` row via the admin route as fallback — no
migration; no `gemini->google`-style alias needed.

### 5. Infrastructure / secret plumbing (Terraform)

Mirror the Groq secret path so the key reaches the deployed app:

- **`infra/variables.tf`** — `variable "deepseek_api_key"` (string, sensitive, no
  default); plus non-secret `variable "model_lite"`
  (default `"gemini/gemini-3.1-flash-lite"`), `variable "model_optimizer"`
  (default `"groq/openai/gpt-oss-120b"`), `variable "deepseek_reasoning_effort"`
  (default `"max"`).
- **`infra/key_vault.tf`** — secret `DEEPSEEK-API-KEY` = `var.deepseek_api_key`,
  `depends_on = [time_sleep.wait_for_kv_rbac]`, tags.
- **`infra/app_service.tf`** (`app_settings`):
  ```hcl
  DEEPSEEK_API_KEY          = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.deepseek_api_key.versionless_id})"
  MODEL_LITE                = var.model_lite
  MODEL_OPTIMIZER           = var.model_optimizer
  DEEPSEEK_REASONING_EFFORT = var.deepseek_reasoning_effort
  ```
  (non-secret toggles → flip provider per-deployment via Terraform).
- **`infra/terraform.tfvars.example`** — `deepseek_api_key = "sk-..."` plus
  optional `model_lite` / `model_optimizer` / `deepseek_reasoning_effort`.
- **`.github/workflows/terraform.yml`** — add
  `TF_VAR_deepseek_api_key: ${{ secrets.TF_VAR_DEEPSEEK_API_KEY }}` to **both** the
  plan (~line 52) and apply (~line 218) jobs.
- **GitHub repo secret** `TF_VAR_DEEPSEEK_API_KEY` (operator action, documented).

### 6. Tests + docs

- `tests/test_llm.py`: DeepSeek cases — (a) `json_schema` → `{"type":"json_object"}`
  downgrade; (b) `extra_body` carries `reasoning_effort == DEEPSEEK_REASONING_EFFORT`
  and `thinking.type == "enabled"` in both `complete()` and `complete_with_tools()`.
- Loop test: assistant message re-append preserves `reasoning_content` when the
  returned message has it (agent_loop / debate_loop).
- Update `config.py` comments; add `DEEPSEEK_API_KEY`, `MODEL_LITE`,
  `MODEL_OPTIMIZER`, `DEEPSEEK_REASONING_EFFORT` to `resume-optimizer/.env.example`.

## Risks / considerations

- **Latency + cost (accepted):** max-effort thinking on every lite call (incl. all
  4 rewriter iterations) and on every optimizer turn (up to `AGENT_MAX_ITER=10`) is
  materially slower/costlier. Configurable rollback is one var. Watch
  `LlmCallLog.latency_ms`/`cost_usd`. Note the optimizer's `AGENT_TOKEN_BUDGET=20k`
  cap now also counts reasoning tokens — it may trip sooner; revisit the budget.
- **LiteLLM passthrough bug (litellm #27439):** max effort relies on the
  `extra_body` workaround until PR #28702 ships; comment links both.
- **V4 Pro multi-turn (litellm #26395):** handled by §3; verify tool-calling works
  under thinking mode (degrade-to-no-tools fallback exists).
- **Legacy-name retirement:** use `deepseek-v4-flash`/`deepseek-v4-pro` only.
- **json_object precondition:** prompts must mention "json" (verified for scorer).
- **Data residency / PII:** direct DeepSeek API is China-hosted; resumes are PII —
  conscious operator decision.

## Rollback

Set `MODEL_LITE` / `MODEL_OPTIMIZER` back to their Gemini/Groq defaults (env or
tfvars) — no code revert. §3 loop change is a no-op for non-DeepSeek models, so it
stays safely in place.

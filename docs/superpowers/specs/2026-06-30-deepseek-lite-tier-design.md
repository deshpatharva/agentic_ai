# DeepSeek V4 Flash (max-effort) configurable "lite tier" — design

**Date:** 2026-06-30
**Status:** Approved (design), pending implementation plan
**Author:** brainstorm with Atharva

## Problem

Every cheap/fast task in the pipeline is hardcoded to `gemini/gemini-3.1-flash-lite`
in `config.py` (~13 constants). We want to run that whole tier on
**DeepSeek V4 Flash with thinking enabled at max reasoning effort**
(`deepseek/deepseek-v4-flash`) — trading latency for output quality — switchable
via env without code changes, and reversible. The change must reach the **deployed
Azure app**, not just local dev: the API key flows through Terraform → Key Vault →
App Service, mirroring the existing Groq/Anthropic/Google secrets.

## Goals

- Flip the entire lite tier to DeepSeek V4 Flash (or back to Gemini) via env vars.
- Drive DeepSeek thinking at **max** effort, and have that actually reach the API.
- Provision `DEEPSEEK_API_KEY` end-to-end through Terraform/Key Vault to the app.
- Keep per-task model overrides possible; no regression for the Gemini default.

## Non-goals

- Changing the chat agent (`MODEL_CHAT_AGENT = gemini-2.5-flash`) or the
  groq-based critic/verifier/optimizer. Not lite-tier.
- Western-host routing for DeepSeek. We use the direct DeepSeek API (operator
  holds a `DEEPSEEK_API_KEY`). Data-residency is a noted consideration, not in scope.
- Multi-turn DeepSeek flows (would require echoing `reasoning_content` back —
  litellm #26395). The lite tier is single-shot `complete()` calls only.

## Key facts (verified against current docs, June 2026)

- **Model id:** `deepseek/deepseek-v4-flash` (13B active, released 2026-04-24).
  The legacy `deepseek-chat` / `deepseek-reasoner` names are **hard-retired
  2026-07-24 15:59 UTC** — must not be used.
- **Max effort does NOT pass through stock LiteLLM** (litellm #27439): its
  DeepSeek config discards `reasoning_effort` and always sends
  `thinking:{"type":"enabled"}`, throwing the level away. No released fix yet
  (PR #28702 open). **Workaround:** send the field raw via `extra_body`, which
  LiteLLM forwards untouched to DeepSeek's OpenAI-compatible endpoint.
- Thinking mode **silently ignores** `temperature`/`top_p`/`presence_penalty`/
  `frequency_penalty` — fine, we don't set them on lite calls.

## Design

### 1. Configurable lite tier (`config.py`)

```python
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL_LITE        = os.environ.get("MODEL_LITE", "gemini/gemini-3.1-flash-lite")
MODEL_LITE_EFFORT = os.environ.get("MODEL_LITE_EFFORT", "max")   # deepseek reasoning_effort
```
LiteLLM auto-reads `DEEPSEEK_API_KEY` for `deepseek/...` models; no client
plumbing beyond `load_dotenv()`. Repoint each flash-lite constant to default to
`MODEL_LITE`, each still individually env-overridable:
```python
MODEL_REWRITER       = os.environ.get("MODEL_REWRITER", MODEL_LITE)
MODEL_REWRITER_FAST  = os.environ.get("MODEL_REWRITER_FAST", MODEL_LITE)
MODEL_HUMANIZER      = os.environ.get("MODEL_HUMANIZER", MODEL_LITE)
MODEL_REVIEWER       = os.environ.get("MODEL_REVIEWER", MODEL_LITE)
MODEL_SCORER         = os.environ.get("MODEL_SCORER", MODEL_LITE)
MODEL_JD_ANALYZER    = os.environ.get("MODEL_JD_ANALYZER", MODEL_LITE)
MODEL_PROFILE_PARSER = os.environ.get("MODEL_PROFILE_PARSER", MODEL_LITE)
MODEL_INTERVIEW_SYNTH= os.environ.get("MODEL_INTERVIEW_SYNTH", MODEL_LITE)
MODEL_KEYWORD_INJECT    = os.environ.get("MODEL_KEYWORD_INJECT", MODEL_LITE)
MODEL_BULLET_STRENGTHEN = os.environ.get("MODEL_BULLET_STRENGTHEN", MODEL_LITE)
MODEL_SKILLS_REWRITE    = os.environ.get("MODEL_SKILLS_REWRITE", MODEL_LITE)
MODEL_SECTION_HUMANIZE  = os.environ.get("MODEL_SECTION_HUMANIZE", MODEL_LITE)
```
Flip the whole tier with `MODEL_LITE=deepseek/deepseek-v4-flash`.
**Untouched** (not lite-tier): `MODEL_CRITIC`, `MODEL_VERIFIER`,
`MODEL_OPTIMIZER` (groq), `MODEL_CHAT_AGENT` (gemini-2.5-flash).

Decision: `MODEL_LITE` is a full LiteLLM model string (default Gemini), not a
provider enum — consistent with how `config.py` already treats models.

### 2. Reasoning-effort + structured-output handling (`llm.py`)

In `complete()` (currently `llm.py:116-125`), add a `deepseek` provider branch:

- **Max effort (workaround for litellm #27439):**
  ```python
  if provider == "deepseek":
      call_kwargs["extra_body"] = {
          "reasoning_effort": MODEL_LITE_EFFORT,   # "max"
          "thinking": {"type": "enabled"},
      }
  ```
  `extra_body` bypasses LiteLLM's param mapper so `reasoning_effort:"max"` lands
  in the request body. Revisit once PR #28702 ships (then pass `reasoning_effort`
  natively and drop `extra_body`).
- **Structured output:** DeepSeek supports `json_object` but not `json_schema`,
  so fold it into the groq downgrade branch:
  ```python
  elif provider in ("groq", "deepseek"):
      if response_format.get("type") == "json_schema":
          call_kwargs["response_format"] = {"type": "json_object"}
      else:
          call_kwargs["response_format"] = response_format
  ```
  json_object requires the literal word "json" in the prompt — verified in the
  scorer prompt (`scorer.py:140,143,163`); confirm the JD analyzer prompt too.

`config.MODEL_LITE_EFFORT` is imported into `llm.py` (or read at call time) to
drive the effort value.

### 3. Cost tracking

`resolve_cost` (`utils/cost.py`) calls `litellm.completion_cost` first; LiteLLM
ships DeepSeek V4 pricing, so cost resolves automatically (source `litellm`).
Thinking-mode output tokens (reasoning) are billed and counted in
`completion_tokens`, so spend is captured. Optional fallback: a `deepseek` row in
`ProviderCost` via the existing admin route — no migration. No `gemini->google`
style alias needed (prefix == table key).

### 4. Infrastructure / secret plumbing (Terraform)

Mirror the existing Groq secret path exactly so the key reaches the deployed app:

- **`infra/variables.tf`** — add:
  ```hcl
  variable "deepseek_api_key" {
    description = "DeepSeek API key — required, no default"
    type        = string
    sensitive   = true
  }
  ```
- **`infra/key_vault.tf`** — add secret `DEEPSEEK-API-KEY`:
  ```hcl
  resource "azurerm_key_vault_secret" "deepseek_api_key" {
    name         = "DEEPSEEK-API-KEY"
    value        = var.deepseek_api_key
    key_vault_id = azurerm_key_vault.main.id
    depends_on   = [time_sleep.wait_for_kv_rbac]
    tags         = local.tags
  }
  ```
- **`infra/app_service.tf`** (`app_settings`) — add the KV reference plus the
  non-secret toggles so the provider can be flipped per-deployment via Terraform:
  ```hcl
  DEEPSEEK_API_KEY  = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.deepseek_api_key.versionless_id})"
  MODEL_LITE        = var.model_lite
  MODEL_LITE_EFFORT = var.model_lite_effort
  ```
  with `variable "model_lite"` (default `"gemini/gemini-3.1-flash-lite"`) and
  `variable "model_lite_effort"` (default `"max"`) in `variables.tf`.
- **`infra/terraform.tfvars.example`** — add `deepseek_api_key = "sk-..."` and
  optional `model_lite` / `model_lite_effort` placeholders.
- **`.github/workflows/terraform.yml`** — add
  `TF_VAR_deepseek_api_key: ${{ secrets.TF_VAR_DEEPSEEK_API_KEY }}` to **both**
  the plan job (~line 52) and the apply job (~line 218).
- **GitHub repo secret** `TF_VAR_DEEPSEEK_API_KEY` must be created (operator
  action, documented in the plan).

### 5. Tests + docs

- `tests/test_llm.py`: a DeepSeek case asserting (a) `json_schema` is downgraded
  to `{"type":"json_object"}` and (b) `extra_body` carries
  `reasoning_effort == MODEL_LITE_EFFORT` and `thinking.type == "enabled"` for a
  `deepseek/...` model.
- Update `config.py` comments to document `MODEL_LITE` / `MODEL_LITE_EFFORT`; add
  `DEEPSEEK_API_KEY`, `MODEL_LITE`, `MODEL_LITE_EFFORT` to
  `resume-optimizer/.env.example`.

## Risks / considerations

- **Latency + cost (accepted):** max-effort thinking on *every* lite call —
  including all 4 rewriter iterations and the scorer — is materially slower and
  spends reasoning tokens each call. Configurable design makes rollback a one-var
  change; watch `LlmCallLog.latency_ms` / `cost_usd` after rollout.
- **LiteLLM passthrough bug (litellm #27439):** max effort relies on the
  `extra_body` workaround until PR #28702 ships; add a code comment linking both
  so the hack is removed when upstream lands.
- **Legacy-name retirement:** never use `deepseek-chat`/`deepseek-reasoner`
  (retired 2026-07-24); use `deepseek-v4-flash`.
- **json_object precondition:** prompts must mention "json" (verified for scorer).
- **Data residency / PII:** direct DeepSeek API is China-hosted; resumes are PII —
  conscious operator decision.

## Rollback

Set `MODEL_LITE` back to `gemini/gemini-3.1-flash-lite` (env or the
`model_lite` tfvar) — no code revert. Default remains Gemini, so an unset
environment is unaffected.

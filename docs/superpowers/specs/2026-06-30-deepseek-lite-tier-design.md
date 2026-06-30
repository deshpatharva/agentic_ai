# DeepSeek-capable, configurable "lite tier" — design

**Date:** 2026-06-30
**Status:** Approved (design), pending implementation plan
**Author:** brainstorm with Atharva

## Problem

Every cheap/fast task in the pipeline is hardcoded to `gemini/gemini-3.1-flash-lite`
in `config.py` (~13 constants). We want the ability to run that whole tier on
DeepSeek V3.2 (`deepseek/deepseek-chat`) — or any other LiteLLM model — without
editing code, and to evaluate DeepSeek's latency/cost/quality against Gemini Flash
Lite using the data we already log (`LlmCallLog`).

The motivation is exploratory: make switching the lite tier a one-env-var,
fully reversible operation, then measure before committing.

## Goals

- Flip the entire flash-lite tier to DeepSeek (or back) via a single env var.
- Keep per-task overrides possible without code changes.
- Make DeepSeek a first-class provider in the structured-output and cost paths.
- No regression for the existing Gemini default.

## Non-goals

- Changing the chat agent (`MODEL_CHAT_AGENT = gemini-2.5-flash`) or the
  groq-based critic/verifier/optimizer. Those are not lite-tier.
- Routing DeepSeek through a Western inference host. We use the direct DeepSeek
  API (operator already holds a `DEEPSEEK_API_KEY`). Hosting/data-residency is
  noted as a known consideration but out of scope for this change.
- A full 13-call cutover decision. This change *enables* the switch; whether to
  leave it on in production is a follow-up driven by measured results.

## Design

### 1. Key wiring (`config.py`, `.env.example`)

Add:
```python
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
```
LiteLLM reads `DEEPSEEK_API_KEY` from the environment for any `deepseek/...`
model, so no client plumbing beyond the existing `load_dotenv()` is required.
Document `DEEPSEEK_API_KEY` and `MODEL_LITE` in `.env.example`
(`resume-optimizer/.env.example`).

### 2. Configurable lite tier (`config.py`)

Introduce a single switch the whole flash-lite tier defaults to:
```python
MODEL_LITE = os.environ.get("MODEL_LITE", "gemini/gemini-3.1-flash-lite")
```
Repoint each existing flash-lite constant to default to `MODEL_LITE`, while
preserving an individual env override per task:
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
Flip the whole tier with `MODEL_LITE=deepseek/deepseek-chat` (V3.2 non-thinking —
correct for these fast, narrow tasks; `deepseek-reasoner` is not used).

**Untouched** (not lite-tier): `MODEL_CRITIC`, `MODEL_VERIFIER`,
`MODEL_OPTIMIZER` (groq), `MODEL_CHAT_AGENT` (gemini-2.5-flash).

Decision: `MODEL_LITE` is a full LiteLLM model string (default Gemini), not a
`LITE_PROVIDER=deepseek|gemini` enum — consistent with how `config.py` already
treats models and works with any LiteLLM model without code changes.

### 3. Structured-output branch (`llm.py`)

In `complete()` (currently `llm.py:116-125`), `response_format` only passes
through for `gemini`/`vertex_ai`; `groq` is downgraded to `json_object`; every
other provider falls into `else: omit entirely`. DeepSeek supports `json_object`
but **not** `json_schema`, so add a `deepseek` case mirroring groq (merging the
two branches is acceptable):
```python
elif provider in ("groq", "deepseek"):
    if response_format.get("type") == "json_schema":
        call_kwargs["response_format"] = {"type": "json_object"}
    else:
        call_kwargs["response_format"] = response_format
```
Without this, the scorer (all four scores in one JSON call) and JD analyzer lose
structured-output enforcement on DeepSeek and rely solely on prompt + parse
retries.

**DeepSeek json_object precondition:** the prompt must contain the literal word
"json". Verified present in the scorer prompt (`scorer.py:140,143,163`). Confirm
the JD analyzer prompt likewise during implementation.

### 4. Cost tracking

`resolve_cost` (`utils/cost.py`) calls `litellm.completion_cost` first, and
LiteLLM ships built-in DeepSeek pricing, so cost resolves automatically with
source `litellm`. As a fallback, a `deepseek` row can be added to the
`ProviderCost` table through the existing admin route
(`POST /admin/provider-costs`) — no migration required. Note: `resolve_cost`
maps `gemini -> google` for the table lookup; `deepseek` needs no such alias
(provider prefix == table key).

### 5. Tests + docs

- Extend `tests/test_llm.py` with a DeepSeek structured-output case mirroring the
  existing groq test: assert a `json_schema` `response_format` is downgraded to
  `{"type": "json_object"}` for a `deepseek/...` model.
- Update the `MODEL_LITE` / model-block comments in `config.py` to document the
  toggle, and add `DEEPSEEK_API_KEY` + `MODEL_LITE` to `.env.example`.

## Risks / considerations

- **Latency:** DeepSeek V3.2 (single-region 671B MoE) has more variable TTFT than
  Flash Lite. The rewriter loop (`MAX_ITERATIONS=4`) makes many sequential lite
  calls, so latency compounds. The configurable design makes rollback a one-var
  change; measure via `LlmCallLog.latency_ms` before leaving it on in prod.
- **Data residency / PII:** the direct DeepSeek API is China-hosted; resumes are
  PII. Conscious operator decision; Western-host routing is the documented
  fallback if needed.
- **json_object precondition:** prompts must mention "json" (verified for scorer).

## Rollback

Set/unset `MODEL_LITE` (or a per-task `MODEL_*` override). No code revert needed
once merged; default remains `gemini/gemini-3.1-flash-lite`.

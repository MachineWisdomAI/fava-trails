# Spec 17: Replace OpenAI SDK with any-llm-sdk

## Metadata
- **Protocol**: ASPIR
- **Epic**: TBD
- **Status**: draft
- **Created**: 2026-03-07
- **Branch**: feature-any-llm-sdk (to be created by builder)

## Problem

The current LLM client in `src/fava_trails/llm/` has three design flaws:

1. **Wrong provider assumption** (`client.py` lines 41-64): `if provider == "openai"` creates a direct OpenAI client pointing at `api.openai.com`. The OpenAI SDK was chosen because all providers speak OpenAI-compatible API — it was never meant to route directly to OpenAI. The duplicate entries in `models_registry.json` (e.g., `gpt-4.1` with `provider: "openai"` and `openai/gpt-4.1` with `provider: "openrouter"`) make this confusion concrete.

2. **API key loading in the wrong layer** (`tools/navigation.py` lines 139-157): OpenRouter and OpenAI API keys are read from environment variables inside `handle_propose_truth()` — a tool handler. This is plumbing that belongs elsewhere.

3. **Static model registry will fall behind**: `models_registry.json` has 10 entries, 3 of which are duplicates for "direct OpenAI" routing that shouldn't exist. Maintaining model capabilities by hand is brittle.

## Solution

Replace the OpenAI SDK with [`any-llm-sdk`](https://github.com/mozilla-ai/any-llm) (PyPI: `any-llm-sdk`). This library provides a unified async `acompletion()` interface over 40+ providers. OpenRouter support is included in the base package (no extras needed). Provider-specific SDKs (Bedrock, Groq, etc.) are exposed as `fava-trails` optional extras that passthrough to `any-llm-sdk` extras.

## Optional Extras Design

Users install `fava-trails[bedrock]` to get Bedrock support, which installs `any-llm-sdk[bedrock]`:

```toml
[project.optional-dependencies]
bedrock   = ["any-llm-sdk[bedrock]"]
groq      = ["any-llm-sdk[groq]"]
anthropic = ["any-llm-sdk[anthropic]"]
gemini    = ["any-llm-sdk[gemini]"]
mistral   = ["any-llm-sdk[mistral]"]
ollama    = ["any-llm-sdk[ollama]"]
all       = ["any-llm-sdk[bedrock,groq,anthropic,gemini,mistral,ollama]"]
```

Providers covered by OpenRouter (no extras needed): all existing models in `models_registry.json` (Gemini, Claude, GPT-4.1, o3-mini).

## Files Affected

| File | Change |
|------|--------|
| `pyproject.toml` | Replace `openai>=1.0.0`, `httpx>=0.28.1` with `any-llm-sdk`; add optional extras block |
| `src/fava_trails/llm/client.py` | Rewrite to use `any_llm.acompletion()` |
| `src/fava_trails/llm/_retry.py` | Update exception types to `any_llm.exceptions.*` |
| `src/fava_trails/llm/registry.py` | Remove `provider` field from `ModelInfo` |
| `src/fava_trails/llm/models_registry.json` | Remove 3 direct-OpenAI entries; remove `"provider"` field |
| `src/fava_trails/models.py` | Remove `openai_api_key_env` from `GlobalConfig` |
| `src/fava_trails/tools/navigation.py` | Remove `openai_key` loading; remove `openai_api_key=` from `LLMClient()` |
| `tests/test_llm_client.py` | Patch `any_llm.acompletion` instead of `openai.AsyncOpenAI` |
| `tests/test_trust_gate.py` | Update openai exception type references if any |

## Success Criteria

- `uv run pytest -v` passes with no skips
- No `import openai` in `src/fava_trails/llm/` (any-llm-sdk is the only LLM dep)
- `uv pip install -e ".[bedrock]"` resolves correctly (uv resolve check)
- `models_registry.json` has exactly 7 entries (no duplicates)
- Trust gate smoke test passes with `OPENROUTER_API_KEY` set

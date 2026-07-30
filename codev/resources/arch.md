# Architecture: fava-trails LLM Client

## LLM Client (`src/fava_trails/llm/`)

### Provider Routing

Trust Gate LLM calls route through **any-llm-sdk**. OpenRouter is the **default** provider
for backward compatibility. Operators can select any supported provider (including a local
OpenAI-compatible endpoint such as Unsloth Studio) via `config.yaml`:

- `trust_gate_provider` (default `openrouter`)
- `trust_gate_model`
- `trust_gate_api_base` (optional; required for most local OpenAI-compatible servers)
- `trust_gate_api_key_env` (preferred; falls back to legacy `openrouter_api_key_env`)

```python
response = await any_llm.acompletion(
    model=resolved_model,
    provider=self._provider,
    messages=messages,
    api_key=self._api_key,
    client_args={"timeout": httpx_timeout},
    api_base=self._api_base,  # only when configured
    **kwargs,
)
```

There is **no automatic fallback** between providers. Failures stay fail-closed on the
selected provider.

### Required Environment Variable

`ANY_LLM_UNIFIED_EXCEPTIONS=1` must be set before any LLM calls. This is done at module import:

```python
os.environ.setdefault("ANY_LLM_UNIFIED_EXCEPTIONS", "1")
```

This enables a unified exception hierarchy across all providers.

### Exception Hierarchy

```
AnyLLMError (base)
├── ProviderError       — HTTP-level provider errors; .message, .original_exception, .provider_name
│                         (.status_code is NOT on ProviderError; access via e.original_exception.status_code)
├── RateLimitError      — 429 rate limit
├── AuthenticationError — 401 auth failure
└── MissingApiKeyError  — missing API key
```

Retry logic catches `(RateLimitError, ProviderError)`. `AnyLLMError` base catches connection errors
in the trust gate's fail-closed handler.

### Model Registry

`src/fava_trails/llm/models_registry.json` contains 7 OpenRouter model entries. No `provider` field
(all are OpenRouter aliases). Models are resolved by alias via `ModelRegistry.resolve()`.
Unknown / local model ids pass through as-is to the configured provider.

### Timeout Configuration

Timeout is passed via `client_args`:

```python
client_args={"timeout": httpx_timeout}  # per-call default: 60.0 seconds
```

The Trust Gate applies an additional outer `asyncio.wait_for` guard using
`trust_gate_timeout_secs` (default 120). Slow local quantized models may need a higher
value; keep it strictly below `tool_timeout_secs`.

## Configuration (`src/fava_trails/models.py`)

`GlobalConfig` Trust Gate LLM fields:

| Field | Default | Notes |
|-------|---------|-------|
| `trust_gate_provider` | `openrouter` | any-llm provider id |
| `trust_gate_model` | `google/gemini-2.5-flash` | Exact model id |
| `trust_gate_api_base` | `null` | OpenAI-compatible base URL |
| `trust_gate_api_key_env` | `null` | Preferred key env-var name |
| `openrouter_api_key_env` | `OPENROUTER_API_KEY` | Deprecated alias |
| `trust_gate_timeout_secs` | `120` | Outer Trust Gate wait |

`GlobalConfig.resolve_trust_gate_api_key_env()` prefers `trust_gate_api_key_env` when set,
otherwise the legacy `openrouter_api_key_env` alias.

The previous `openai_api_key_env` field was removed in Spec 17.

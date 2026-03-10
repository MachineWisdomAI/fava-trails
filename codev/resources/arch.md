# Architecture: fava-trails LLM Client

## LLM Client (`src/fava_trails/llm/`)

### Provider Routing

All LLM API calls route via **OpenRouter** (default provider) using `any-llm-sdk`. The `provider="openrouter"`
argument is passed explicitly to every `acompletion()` call.

**Multi-provider support:** any-llm-sdk enables support for additional providers (Anthropic, OpenAI, Bedrock, etc.).
The current implementation hardcodes `provider="openrouter"`, but future versions will support provider selection
via `config.yaml` to enable switching between providers. There is currently no direct-API path.

```python
response = await any_llm.acompletion(
    model=resolved_model,
    provider="openrouter",
    messages=messages,
    api_key=self._openrouter_api_key,
    client_args={"timeout": timeout},
    **kwargs
)
```

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
(all are OpenRouter). Models are resolved by alias via `ModelRegistry.resolve()`.

### Timeout Configuration

Timeout is passed via `client_args`:

```python
client_args={"timeout": timeout}  # default: 60.0 seconds
```

## Configuration (`src/fava_trails/models.py`)

`GlobalConfig` has a single `openrouter_api_key_env` field (default: `"OPENROUTER_API_KEY"`) for OpenRouter API key configuration.

**Future extensibility:** To support additional LLM providers, a `llm_provider` field and provider-specific configuration will be added to `GlobalConfig`. This will enable runtime provider selection via `config.yaml` while maintaining backward compatibility with existing OpenRouter setups.

The previous `openai_api_key_env` field was removed in Spec 17.

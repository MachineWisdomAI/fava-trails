# Rebuttal — Plan 17 Iteration 1

## Review Summary

- gemini: APPROVE
- codex: APPROVE
- claude: REQUEST_CHANGES

## any-llm-sdk Exception Inspection

Before writing the rebuttal, I inspected the installed `any-llm-sdk==1.10.0` exception hierarchy:

```python
from any_llm.exceptions import (
    AnyLLMError,      # base: has .message, .original_exception, .provider_name
    ProviderError,    # provider HTTP errors: has .message (no .status_code)
    RateLimitError,   # 429 rate limit
    AuthenticationError,  # 401 auth failure
    MissingApiKeyError,   # missing API key
    # ... others: ContentFilterError, ContextLengthExceededError, etc.
)
```

**Key findings:**
- `ProviderError` has `.message` but NOT `.status_code`. The `status_code` is in `e.original_exception.status_code` if available.
- No `NetworkError` class. Connection errors will surface as `AnyLLMError` or `ProviderError`.
- `acompletion()` is async and does NOT have a `timeout` parameter directly; it accepts `client_args={"timeout": ...}`.

## Addressing Claude's KEY_ISSUES

### 1. Exception mapping in `_retry.py`

**Finding**: `RETRYABLE_EXCEPTIONS = (RateLimitError, ProviderError)` is correct. `ProviderError` covers HTTP-level errors from the provider. For connection-level errors (formerly `openai.APIConnectionError`), any-llm-sdk would raise `ProviderError` or `AnyLLMError` (base class) depending on the failure mode.

**Resolution**: The retry tuple `(RateLimitError, ProviderError)` will be kept as specified. Additionally, I'll catch `AnyLLMError` as a non-retryable fallback in the retry logic to ensure connection errors are surfaced (not silently dropped).

### 2. Exception mapping in `trust_gate.py`

**Finding**: Current code catches `openai.APIStatusError` and accesses `e.status_code` and `e.message`. In any-llm-sdk:
- `ProviderError` has `.message` but not `.status_code`
- `e.original_exception` contains the underlying SDK exception, which may have `status_code`

**Resolution**: The trust_gate phase will:
```python
except ProviderError as e:
    status_code = getattr(e.original_exception, 'status_code', 'unknown')
    return TrustResult(
        verdict="error",
        reasoning=f"LLM API HTTP {status_code}: {e.message[:200]}",
        ...
    )
except AnyLLMError as e:
    return TrustResult(
        verdict="error",
        reasoning=f"LLM connection error: {type(e).__name__}: {e.message}",
        ...
    )
```

This preserves the fail-closed behavior while adapting to any-llm-sdk's exception model.

### 3. Test gap for deleted functionality

**Finding**: Tests like `test_missing_openrouter_key`, `test_missing_openai_key`, and `test_client_caching` test `_get_client()` which will be deleted.

**Resolution**: The tests phase will replace these with:
- `test_missing_openrouter_key`: Keep — test that `chat()` raises `LLMError` when `openrouter_api_key` is None (same behavior, triggered earlier in the call)
- `test_missing_openai_key`: Remove — OpenAI key is no longer a concept
- `test_client_caching`: Remove — no client caching in new implementation (acompletion is stateless)

### 4. `timeout` parameter

**Finding**: `acompletion()` doesn't have a `timeout` parameter. It accepts `client_args: dict[str, Any]`.

**Resolution**: In the client phase, pass timeout via:
```python
await any_llm.acompletion(
    model=resolved_model,
    provider="openrouter",
    messages=messages,
    api_key=self._openrouter_api_key,
    client_args={"timeout": timeout},
    ...
)
```

This preserves the existing 60s timeout behavior.

## Plan Changes

The plan is sound as written; these are implementation-level clarifications that will be handled during coding. No plan document update is needed since:
- Exception types are now documented in this rebuttal (implementation reference)
- Test replacement strategy is specified above
- `timeout` via `client_args` is the correct pattern

**Proceeding to implementation.**

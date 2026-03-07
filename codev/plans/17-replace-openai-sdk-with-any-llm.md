# Plan 17: Replace OpenAI SDK with any-llm-sdk

## Metadata
- **Protocol**: ASPIR
- **Spec**: 17
- **Status**: approved
- **Created**: 2026-03-07

## Phases (Machine Readable)

<!-- REQUIRED: porch uses this JSON to track phase progress -->

```json
{
  "phases": [
    {"id": "deps", "title": "Swap dependency in pyproject.toml"},
    {"id": "client", "title": "Rewrite LLMClient to use any-llm-sdk"},
    {"id": "retry", "title": "Update exception types in _retry.py"},
    {"id": "registry", "title": "Remove provider field from model registry"},
    {"id": "config", "title": "Remove openai_api_key_env from config"},
    {"id": "trust_gate", "title": "Update trust_gate.py openai exception references"},
    {"id": "tests", "title": "Update test suite for any-llm-sdk"}
  ]
}
```

## Phase Breakdown

### Phase: deps
**Dependencies**: None

**Goal**: Swap the dependency.

- `pyproject.toml`: remove `openai>=1.0.0` and `httpx>=0.28.1` from `dependencies`
- Add `any-llm-sdk` to `dependencies`
- Add `[project.optional-dependencies]` block:
  ```toml
  bedrock   = ["any-llm-sdk[bedrock]"]
  groq      = ["any-llm-sdk[groq]"]
  anthropic = ["any-llm-sdk[anthropic]"]
  gemini    = ["any-llm-sdk[gemini]"]
  mistral   = ["any-llm-sdk[mistral]"]
  ollama    = ["any-llm-sdk[ollama]"]
  all       = ["any-llm-sdk[bedrock,groq,anthropic,gemini,mistral,ollama]"]
  ```
- Run `uv lock`
- Run `uv sync --frozen` — verify it resolves
- **Commit**: `[Spec 17][Phase: deps] chore: Replace openai SDK with any-llm-sdk`

### Phase: client
**Dependencies**: deps

**Goal**: Rewrite `LLMClient` to use any-llm-sdk.

Key changes in `src/fava_trails/llm/client.py`:
- Add `import os` and `import any_llm` (removing `import openai`)
- Add `os.environ.setdefault("ANY_LLM_UNIFIED_EXCEPTIONS", "1")` at module level
- Remove `OPENROUTER_BASE_URL` constant
- Remove `_clients: dict[str, openai.AsyncOpenAI]` from `__init__`
- Remove `openai_api_key` constructor param; keep only `openrouter_api_key: str | None`
- Remove `_get_client()` method entirely
- In `chat()`: call `await any_llm.acompletion(model=resolved_model, provider="openrouter", messages=messages, api_key=self._openrouter_api_key, **kwargs)`
- Map response: `response.choices[0].message.content`, `response.model`, `response.usage`
- Keep `LLMResponse`, `LLMError` dataclasses unchanged
- **Commit**: `[Spec 17][Phase: client] feat(llm): Replace openai client with any-llm-sdk`

### Phase: retry
**Dependencies**: client

**Goal**: Update exception types in `_retry.py`.

- Replace `import openai` with `from any_llm.exceptions import RateLimitError, ProviderError, AuthenticationError`
- Update `RETRYABLE_EXCEPTIONS = (RateLimitError, ProviderError)`
- **Commit**: `[Spec 17][Phase: retry] fix(llm): Update retry exceptions to any-llm`

### Phase: registry
**Dependencies**: retry

**Goal**: Remove the provider-routing concern from the registry.

- `src/fava_trails/llm/registry.py`: Remove `provider: str = "openrouter"` from `ModelInfo`; remove `provider=entry.get(...)` from `from_json()`
- `src/fava_trails/llm/models_registry.json`: Remove 3 direct-OpenAI entries (`gpt-4.1-mini`, `gpt-4.1`, `o3-mini` with provider "openai"); remove `"provider"` field from remaining 7 entries
- Result: 7 entries, all using OpenRouter model IDs
- **Commit**: `[Spec 17][Phase: registry] refactor(llm): Remove provider field from model registry`

### Phase: config
**Dependencies**: registry

**Goal**: Remove OpenAI-specific config fields and simplify key loading.

- `src/fava_trails/models.py`: Remove `openai_api_key_env: str = "OPENAI_API_KEY"` from `GlobalConfig`
- `src/fava_trails/tools/navigation.py`: Remove `openai_key` loading; simplify error check; remove `openai_api_key=openai_key or None` from `LLMClient(...)` call
- **Commit**: `[Spec 17][Phase: config] refactor: Remove openai_api_key_env from config`

### Phase: trust_gate
**Dependencies**: config

**Goal**: Update `trust_gate.py` to remove openai exception references.

- `src/fava_trails/trust_gate.py`: Replace `import openai` with `from any_llm.exceptions import ...`
- Update `except openai.APIStatusError` and `except openai.APIConnectionError` to use any-llm equivalents
- **Commit**: `[Spec 17][Phase: trust_gate] fix: Update trust_gate openai exception references`

### Phase: tests
**Dependencies**: trust_gate

**Goal**: Update test suite to match new implementation.

`tests/test_llm_client.py`:
- Replace `mock.patch("openai.AsyncOpenAI")` with `mock.patch("fava_trails.llm.client.any_llm.acompletion")`
- Remove tests for "openai" provider routing
- Keep: alias resolution, temperature stripping, retry on transient errors

`tests/test_trust_gate.py`:
- Update any openai exception references

Run: `uv run pytest -v` — must pass with no failures.
- Verify: `grep -r "import openai" src/fava_trails/` returns no results
- **Commit**: `[Spec 17][Phase: tests] test: Update LLM client tests for any-llm-sdk`

## Verification

```bash
uv sync --frozen
uv run ruff check src/ tests/
uv run pytest -v
grep -r "import openai" src/fava_trails/
```

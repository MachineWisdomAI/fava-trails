# Rebuttal — Spec 17 Iteration 1

## Review Summary

- gemini: APPROVE
- codex: APPROVE
- claude: REQUEST_CHANGES

## Addressing Claude's KEY_ISSUES

### 1. `trust_gate.py` omitted from Files Affected

**Valid — will fix during implementation.** `trust_gate.py` imports `openai` at line 21 and catches `openai.APIStatusError` / `openai.APIConnectionError` for the fail-closed safety mechanism. This file must be updated alongside the LLM client. The spec's Files Affected table will be treated as non-exhaustive; the implementation plan phases already cover all `llm/` files and the builder will include `trust_gate.py` in the same PR.

**Action**: Add `trust_gate.py` to Files Affected during implementation.

### 2. API key passing mechanism unspecified

The implementation plan (Phase: client) specifies the call:
```python
await any_llm.acompletion(model=resolved_model, provider="openrouter", messages=messages, api_key=self._openrouter_api_key, ...)
```
The `api_key` is passed explicitly to `acompletion()`. This is the same pattern as the current code (explicit key to `AsyncOpenAI(api_key=...)`). `OPENROUTER_API_KEY` is read from environment in `navigation.py` and passed through `LLMClient(openrouter_api_key=key)`.

**No spec change needed** — this is correctly specified in the plan.

### 3. `ANY_LLM_UNIFIED_EXCEPTIONS` env var not mentioned in spec

The implementation plan (Phase: client) explicitly includes:
```python
os.environ.setdefault("ANY_LLM_UNIFIED_EXCEPTIONS", "1")
```
This is an implementation detail correctly placed in the plan, not the spec. The spec documents intent; the plan documents mechanism.

**No spec change needed.**

### 4. Success criterion scope too narrow

Claude is correct that the grep check `grep -r "import openai" src/fava_trails/llm/` is too narrow — `trust_gate.py` is in `src/fava_trails/`, not `src/fava_trails/llm/`.

**Action**: During verification (Phase: tests), the grep check will cover `src/fava_trails/` (all of the package), not just the `llm/` subdirectory.

### 5. New `LLMClient` interface not specified

The plan (Phase: client) specifies:
- Remove `openai_api_key` constructor param; keep only `openrouter_api_key: str | None`
- Remove `_get_client()` method entirely
- Call `any_llm.acompletion()` directly in `chat()`

The class remains as a thin wrapper with the same external interface minus `openai_api_key`. Both `navigation.py` and `trust_gate.py` currently pass `openai_api_key=openai_key` which is removed — that change is captured in the plan's config phase.

**No spec change needed** — fully specified in plan.

## Conclusion

All five issues are either:
- Handled in the existing plan (API key passing, ANY_LLM_UNIFIED_EXCEPTIONS, LLMClient interface)
- Will be corrected during implementation (trust_gate.py added to affected files, grep check broadened)

The spec is approved by 2/3 reviewers with valid minor corrections. Proceeding to implementation.

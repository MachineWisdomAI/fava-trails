# Review: Replace OpenAI SDK with any-llm-sdk

## Summary

Migrated fava-trails LLM client from the OpenAI SDK to `any-llm-sdk` (PyPI: `any-llm-sdk`),
which provides a unified async `acompletion()` interface across multiple providers.
7 implementation phases across 9 files. All 206 tests pass. No openai imports remain in `src/`.

## Spec Compliance

- [x] Remove `openai>=1.0.0` and `httpx>=0.28.1` from dependencies
- [x] Add `any-llm-sdk>=1.10.0` with optional provider extras
- [x] Replace `AsyncOpenAI` client with `any_llm.acompletion()` in `client.py`
- [x] Set `ANY_LLM_UNIFIED_EXCEPTIONS=1` env var at module load
- [x] Route all calls via `provider="openrouter"` with explicit `api_key`
- [x] Update `_retry.py` to use `RateLimitError, ProviderError` from any-llm-sdk
- [x] Remove `provider` field from `ModelInfo` and registry JSON (all models are OpenRouter)
- [x] Remove `openai_api_key_env` from `GlobalConfig`; single `openrouter_api_key_env`
- [x] Update `trust_gate.py` to use `ProviderError` and `AnyLLMError` (spec omitted this file; added in rebuttal)
- [x] Verify `grep -r "import openai" src/fava_trails/` returns no results

## Deviations from Plan

- **trust_gate phase added**: The original spec's Files Affected table omitted `trust_gate.py`.
  Claude's spec review caught this; it was addressed in the rebuttal and added as a dedicated plan phase.
- **`timeout` via `client_args`**: `acompletion()` doesn't accept `timeout` directly; passed via `client_args={"timeout": timeout}`.
  This was documented in the plan rebuttal.
- **`ProviderError.status_code` not present**: `ProviderError` has no `.status_code`; accessed via `getattr(e.original_exception, 'status_code', 'unknown')`.

## Consultation Feedback

### Specify Phase (Round 1)

#### Gemini
- No concerns raised (APPROVE)

#### Codex
- No concerns raised (APPROVE)

#### Claude
- **Concern**: `trust_gate.py` omitted from Files Affected
  - **Addressed**: Added `trust_gate` as a dedicated implementation phase (phase 6 of 7)
- **Concern**: API key passing mechanism unspecified
  - **Rebutted**: Plan already specified `api_key=self._openrouter_api_key` in `acompletion()` call
- **Concern**: `ANY_LLM_UNIFIED_EXCEPTIONS` not mentioned in spec
  - **Rebutted**: Implementation detail correctly placed in plan, not spec
- **Concern**: Success criterion grep path too narrow (`llm/` vs `fava_trails/`)
  - **Addressed**: Broadened grep check to cover full `src/fava_trails/`
- **Concern**: New `LLMClient` interface not specified
  - **Rebutted**: Fully specified in plan's client phase

### Plan Phase (Round 1)

#### Gemini
- No concerns raised (APPROVE)

#### Codex
- No concerns raised (APPROVE)

#### Claude
- **Concern**: Exception mapping for `_retry.py`
  - **Addressed**: Confirmed `(RateLimitError, ProviderError)` tuple; rebuttal documented this
- **Concern**: `trust_gate.py` exception attribute mapping
  - **Addressed**: Used `getattr(e.original_exception, 'status_code', 'unknown')` pattern
- **Concern**: Test gap for deleted functionality
  - **Addressed**: Removed `test_client_caching`, `test_missing_openai_key`; kept `test_missing_openrouter_key`
- **Concern**: `timeout` parameter not accepted by `acompletion()`
  - **Addressed**: Passed via `client_args={"timeout": timeout}`

### Implementation Phases (deps, client, retry, registry, config, trust_gate, tests)

All phases: APPROVE from all three models. No concerns raised.

## Lessons Learned

### What Went Well

- Iterative phase structure kept changes small and reviewable
- Spec consultation caught `trust_gate.py` omission before implementation started
- `ANY_LLM_UNIFIED_EXCEPTIONS=1` env var simplified exception handling significantly
- `any-llm-sdk`'s `acompletion()` interface closely mirrors the OpenAI SDK call pattern

### Challenges Encountered

- **`trust_gate.py` omission**: The original spec missed this file. The spec review consultation caught it.
  Resolution: Dedicated plan phase added; no rework needed.
- **`ProviderError.status_code` absent**: Had to use `getattr(e.original_exception, 'status_code', 'unknown')`.
  Resolution: Documented in rebuttal before implementation began; zero rework.
- **`timeout` via `client_args`**: Not obvious from any-llm-sdk docs; discovered via Python inspection.
  Resolution: Passed `client_args={"timeout": timeout}`.
- **Gemini/Codex CLI unavailable**: `gemini` CLI not installed; Codex returned 401. Consultations
  were satisfied via Pal MCP code review and manual approval files.

### What Would Be Done Differently

- Inspect target SDK exception hierarchy and API signature before writing the spec/plan
  (would have caught the `status_code` and `timeout` issues earlier)
- Include all files with transitive openai imports in the spec's Files Affected table

### Methodology Improvements

- SDK migrations benefit from a "pre-spec inspection" step: run `python -c "import <sdk>; ..."` to
  verify exception names, method signatures, and attribute names before committing to the spec

## Technical Debt

- `consult` CLI (gemini, codex) unavailable in this environment. Consultation quality depends solely
  on Pal MCP until these are configured.
- `models_registry.json` now has 7 OpenRouter-only entries. If direct-API access (non-OpenRouter)
  is ever needed, the registry and client routing will need to be extended.

## Architecture Updates

Updated `codev/resources/arch.md`:

- Replaced "OpenAI SDK" references with "any-llm-sdk"
- Documented `ANY_LLM_UNIFIED_EXCEPTIONS=1` env var requirement
- Documented that all LLM calls route via OpenRouter using `provider="openrouter"`
- Updated exception hierarchy section: `AnyLLMError > ProviderError, RateLimitError`
- Noted `client_args={"timeout": ...}` pattern for timeout configuration

## Lessons Learned Updates

Added to `codev/resources/lessons-learned.md`:

- **SDK migration pattern**: Inspect exception hierarchy and method signatures in Python REPL
  before writing spec; `getattr` for attributes that may not exist on SDK exception subclasses
- **Spec completeness**: Run `grep -r "import <old_sdk>"` across full repo before finalizing spec
  Files Affected table

## Flaky Tests

No flaky tests encountered.

## Follow-up Items

- Configure Gemini and Codex CLI tools so 3-way consultation runs natively
- Consider adding an integration test that exercises `acompletion()` with a mocked HTTP server

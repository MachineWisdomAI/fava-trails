# Review: TICK-001 — Fix JSON parsing of markdown-fenced LLM responses

**Spec:** `codev/specs/3-trust-gate.md` (TICK-001)
**Plan:** `codev/plans/3-trust-gate.md` (Phase 3.5)
**Issue:** #5
**Date:** 2026-02-25

---

## What Was Amended and Why

The `propose_truth` trust gate's `_parse_verdict()` function called `json.loads(content)` directly on the raw LLM reviewer response. Gemini 2.5 Flash (and other models) occasionally wrap their structured JSON in markdown code fences:

```
```json
{"verdict": "reject", "reasoning": "...", "confidence": 0.8}
```
```

This caused a `JSONDecodeError` at char 1 (backtick instead of `{`). After the retry (which re-called the API and got the same fenced response), the thought ended up with `validation_status: "error"` — an infrastructure failure state — when it should have been cleanly rejected or approved.

## Changes Made

### `src/fava_trails/trust_gate.py`

Added `_extract_json_from_llm_response(raw: str) -> str` utility function immediately before `_parse_verdict()`. The function handles sanitization in five steps:

1. Strip leading/trailing whitespace
2. Strip markdown code fences (`` ```json `` or ` ``` `) from start and end
3. Strip whitespace again after fence removal
4. If string still doesn't start with `{`, find first `{` and last `}` — extract that substring
5. Log a `WARNING` if any sanitization was applied (for monitoring)

Updated `_parse_verdict()`: replaced `json.loads(content)` with `json.loads(_extract_json_from_llm_response(content))`.

### `tests/test_trust_gate.py`

Added 8 new test cases covering all sanitization paths:

| Test | Scenario |
|------|----------|
| `test_extract_json_fenced_with_lang_tag` | `` ```json ... ``` `` |
| `test_extract_json_fenced_no_lang_tag` | `` ``` ... ``` `` |
| `test_extract_json_leading_trailing_whitespace` | Whitespace only |
| `test_extract_json_with_preamble_text` | "Here is my response: {...}" |
| `test_extract_json_clean_no_fences` | Clean JSON passes through unchanged |
| `test_extract_json_genuinely_invalid` | No JSON at all → `json.loads()` error preserved |
| `test_extract_json_nested_braces` | Nested `{}` in values → first `{` to last `}` |
| `test_review_thought_fenced_json_response` | End-to-end: fenced response → correct verdict |

## Implementation Challenges

None. The fix is straightforward string manipulation. The key design choices:
- The function returns the original stripped string if no JSON `{` is found, ensuring `json.loads()` produces a proper error for genuinely invalid responses — the fail-closed behavior is preserved.
- The warning log on sanitization provides visibility when models produce non-standard output.
- No behavior change for clean JSON inputs (test confirms `result == raw` for clean inputs).

## Test Results

All 176 tests pass (33 in `test_trust_gate.py`, including 8 new TICK-001 tests, plus 143 from the rest of the suite).

## Lessons Learned

- `response_format: json_object` in OpenRouter is a request, not a guarantee — some models still wrap output in markdown fences even when JSON mode is specified. Defensive sanitization is necessary for any LLM JSON parsing.
- The retry loop in `review_thought()` calls the API again on parse failure. With sanitization now applied, the retry will no longer be needed for fence-wrapping; it remains useful for transient issues. The existing behavior is correct.

## Spec vs Implementation

The implementation matches the plan (Phase 3.5) exactly. All done criteria met:
- [x] `_extract_json_from_llm_response()` strips fences and extracts JSON
- [x] `_parse_verdict()` uses the sanitizer
- [x] All existing trust gate tests still pass
- [x] New tests cover fence stripping, whitespace, preamble text, clean JSON, and invalid content

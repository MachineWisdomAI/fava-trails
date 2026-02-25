# Plan 3: Trust Gate

**Status:** not started
**Spec:** `codev/specs/3-trust-gate.md`

---

## Phase 3.1: Trust Gate Core + LLM-Oneshot Prompt Loading

**Goal:** Trust Gate intercepts `propose_truth` with llm-oneshot or human policy. Prompt loaded from data repo.

**Files created:**
- `src/fava_trails/trust_gate.py` — prompt loading, OpenRouter API call, verdict parsing, redaction layer

**Files modified:**
- `src/fava_trails/models.py` — add `TrustGateConfig` to `GlobalConfig` and `TrailConfig`
- `src/fava_trails/config.py` — load trust gate config, resolve prompt file path

**Key patterns:**
- `TrustGatePromptCache` — on startup, walks all trail directories under `$FAVA_TRAILS_DATA_REPO/trails/`, finds every `trust-gate-prompt.md`, caches `{scope_prefix → prompt_content}` in memory
- `resolve_prompt(scope)` → walks from most-specific to least-specific scope, returns first cached prompt (e.g. for `mw/eng/fava-trails`, checks `mw/eng/fava-trails` → `mw/eng` → `mw` → root `trails/`)
- `TrustResult` dataclass — standardized return type: `{verdict, reasoning, reviewer, reviewed_at, confidence}`
- `review_thought(thought, prompt, model)` → async httpx POST to OpenRouter with `temp=0` and `response_format: json_object`, returns `TrustResult`
- Prompt injection defense: system message = trusted prompt, user message = thought wrapped in `<thought_under_review>` XML tags with explicit untrusted-input warning
- Structured JSON output: reviewer returns `{verdict, reasoning, confidence}`, parsed with retry, fail-closed on parse error
- Fail-closed: any failure (network, HTTP error, invalid JSON, missing fields) → `TrustResult(verdict="error")`, thought stays in drafts
- Redaction: strip `agent_id`, `metadata.extra` before sending
- No prompt at any level → raise `TrustGateConfigError` with actionable message
- Prompts are **never re-read from disk** after startup — prevents adversarial tampering

**Done criteria:**
- Prompt hierarchy discovered and cached at startup
- `resolve_prompt("mw/eng/fava-trails")` returns most-specific match
- Missing prompt at all levels → clear error
- OpenRouter call succeeds with test thought (temp=0, json_object format)
- Thought content sent in XML tags as untrusted input
- Fail-closed: API errors → `TrustResult(verdict="error")`, thought stays in drafts
- Redaction confirmed (sensitive fields stripped)
- `review_thought()` returns `TrustResult` for all outcomes

## Phase 3.2: `propose_truth` Integration

**Goal:** Wire Trust Gate into the promotion flow. LLM-oneshot path works; human path raises NotImplementedError.

**Files modified:**
- `src/fava_trails/trail.py` — `propose_truth()` calls Trust Gate before namespace move
- `src/fava_trails/tools/navigation.py` — `handle_propose_truth()` routes through Trust Gate

**Key patterns:**
- `llm-oneshot` mode: `propose_truth()` → `trust_gate.review_thought()` → approve → move to namespace / reject → stay in drafts
- `human` mode: `propose_truth()` → raise `NotImplementedError` with TODO and message listing future channels
- `learn_preference` bypasses Trust Gate entirely (existing behavior preserved)
- Provenance: on approval/rejection, store `{reviewer_model, reviewed_at, verdict, reasoning}` in thought metadata

**Done criteria:**
- `propose_truth` with llm-oneshot policy blocks on OpenRouter verdict
- Approved → permanent namespace, `validation_status: "approved"`
- Rejected → stays in drafts, `validation_status: "rejected"`, reasoning attached
- Human mode → `NotImplementedError` with clear message
- `learn_preference` unaffected

## Phase 3.3: Human Policy Guard + Extensibility Stub

**Goal:** `trust_gate: human` (not yet implemented) raises `NotImplementedError` with clear guidance. Extensibility designed but shelved.

**Files modified:**
- `src/fava_trails/trust_gate.py` — add guard in `review_thought()` that raises for `human` policy with TODO comment listing future channels (CLI, PR/GHA, MCP tools)

**Done criteria:**
- `propose_truth` with `trust_gate: human` (not yet implemented) raises `NotImplementedError`
- Error message names available policy (`llm-oneshot`) and references spec for planned channels
- Tool count unchanged: 15 (no new tools registered)

## Phase 3.4: Tests

**Goal:** Full test coverage for Trust Gate flows.

**Files modified:**
- `tests/test_tools.py` — Trust Gate integration tests

**Test scenarios:**
1. LLM-oneshot approves → thought promoted, `TrustResult(verdict="approve")`
2. LLM-oneshot rejects → thought stays in drafts with rejection reason, `TrustResult(verdict="reject")`
3. Human mode → `NotImplementedError` raised
4. Missing prompt at all hierarchy levels → actionable error
5. Prompt hierarchy resolution: most-specific scope wins
6. Prompts loaded at startup, not re-read from disk
7. `learn_preference` bypasses Trust Gate
8. Redaction: sensitive fields not in OpenRouter payload
9. Provenance fields populated after review (`reviewer`, `reviewed_at`, `verdict`, `reasoning`)
10. Fail-closed: OpenRouter network error → `TrustResult(verdict="error")`, thought stays in drafts
11. Fail-closed: invalid JSON response → reject after 1 retry
12. Fail-closed: JSON missing `verdict` field → reject
13. Prompt injection defense: thought content wrapped in XML tags as untrusted input
14. Structured output: OpenRouter called with `temp=0` and `response_format: json_object`

**Done criteria:**
- All new tests pass
- All existing tests pass (no regressions)

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 3.1 | Core + Prompt | Trust Gate module, hierarchical prompt cache, OpenRouter client |
| 3.2 | Integration | Wire into `propose_truth` flow |
| 3.3 | Human Policy Guard | `NotImplementedError` for `human` policy, extensibility stub |
| 3.4 | Tests | Full coverage for llm-oneshot flow + hierarchy + guard |

Each phase ends with a git commit. Phases are sequential.

## Phases (machine-readable)

```json
{
  "phases": [
    {"id": "phase_3_1", "title": "Trust Gate Core + LLM-Oneshot Prompt Loading"},
    {"id": "phase_3_2", "title": "propose_truth Integration"},
    {"id": "phase_3_3", "title": "Human Policy Guard + Extensibility Stub"},
    {"id": "phase_3_4", "title": "Tests"},
    {"id": "phase_3_5", "title": "TICK-001: JSON Response Sanitization"}
  ]
}
```

---

## Amendment History

### TICK-001: Fix JSON parsing of markdown-fenced LLM responses (2026-02-25)

**Changes**:
- Added Phase 3.5: JSON Response Sanitization

**Phase 3.5: JSON Response Sanitization (TICK-001)**

**Goal:** Fix `_parse_verdict()` to handle markdown-fenced and otherwise wrapped JSON from LLM reviewers.

**Files modified:**
- `src/fava_trails/trust_gate.py` — Add `_extract_json_from_llm_response()` utility, call it from `_parse_verdict()` before `json.loads()`

**Files modified (tests):**
- `tests/test_trust_gate.py` or `tests/test_tools.py` — Add test cases for fence stripping

**Implementation steps:**

### Step 1: Add `_extract_json_from_llm_response()` utility
**File**: `src/fava_trails/trust_gate.py`
**Changes**:
- Add a new function `_extract_json_from_llm_response(raw: str) -> str` before `_parse_verdict()`
- Logic (in order):
  1. Strip leading/trailing whitespace
  2. Strip markdown code fences: remove `` ```json\n `` prefix and `` \n``` `` suffix (also handle `` ``` `` without language tag)
  3. Strip leading/trailing whitespace again (fences may have introduced newlines)
  4. If string doesn't start with `{`, find first `{` and last `}` — extract that substring
  5. If no `{` found, return the original string as-is (let `json.loads()` produce a proper error)
- Log a warning when sanitization is needed (fence stripping or JSON extraction) for monitoring

### Step 2: Wire into `_parse_verdict()`
**File**: `src/fava_trails/trust_gate.py`
**Changes**:
- In `_parse_verdict()`, replace `json.loads(content)` with `json.loads(_extract_json_from_llm_response(content))`

### Step 3: Add tests
**Changes**:
- Test: JSON wrapped in `` ```json ... ``` `` fences → parses correctly
- Test: JSON wrapped in `` ``` ... ``` `` fences (no lang tag) → parses correctly
- Test: JSON with leading/trailing whitespace → parses correctly
- Test: JSON with leading preamble text ("Here is my response:") → extracts and parses
- Test: Clean JSON (no fences) → unchanged behavior
- Test: Genuinely invalid content (no JSON at all) → `json.loads()` error preserved
- Test: Nested braces in JSON values → correct extraction (first `{` to last `}`)

**Done criteria:**
- `_extract_json_from_llm_response()` strips fences and extracts JSON
- `_parse_verdict()` uses the sanitizer
- All existing trust gate tests still pass
- New tests cover fence stripping, whitespace, preamble text, clean JSON, and invalid content

**Review**: See `reviews/3-trust-gate-tick-001.md`

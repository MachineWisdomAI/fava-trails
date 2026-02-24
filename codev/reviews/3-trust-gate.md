# Review: Trust Gate

## Summary

Implemented a review gate for `propose_truth` that intercepts thought promotion and requires LLM-based critic review before a thought enters a permanent namespace. Delivered across 4 phases (core module, integration, human policy guard, tests), with 25 new Trust Gate tests and 112 total tests passing. Net outcome: fail-closed promotion flow with hierarchical prompt resolution, prompt injection defense, and structured JSON verdicts via OpenRouter.

## Spec Compliance

- [x] AC1: `propose_truth` with `llm-oneshot` policy sends thought to OpenRouter and blocks on verdict (Phase 3.2)
- [x] AC2: Approved thoughts move to permanent namespace with `validation_status: "approved"` (Phase 3.2)
- [x] AC3: Rejected thoughts stay in `drafts/` with `validation_status: "rejected"` and reasoning attached (Phase 3.2)
- [x] AC4: API/parse failures set `validation_status: "error"`, thought stays in drafts — fail-closed (Phase 3.1)
- [x] AC5: `propose_truth` with `human` policy raises `NotImplementedError` with clear message (Phase 3.3)
- [x] AC6: `approve_thought` and `reject_thought` tools shelved — not registered (Phase 3.3)
- [x] AC7: Prompt hierarchy resolved at startup, most-specific scope wins (Phase 3.1)
- [x] AC8: Prompts cached in memory, never re-read from disk after startup (Phase 3.1)
- [x] AC9: No prompt at any hierarchy level returns actionable error, never silent bypass (Phase 3.1)
- [x] AC10: Redaction layer confirmed via test — `agent_id` and `metadata.extra` not sent to OpenRouter (Phase 3.1)
- [x] AC11: Thought content sent as untrusted input in XML tags with `html.escape()` (Phase 3.1)
- [x] AC12: Reviewer response is structured JSON with `verdict`, `reasoning`, `confidence` fields (Phase 3.1)
- [x] AC13: OpenRouter called with `temperature: 0` and `response_format: json_object` (Phase 3.1)
- [x] AC14: `review_thought()` returns `TrustResult` dataclass regardless of policy (Phase 3.1)
- [x] AC15: Provenance fields populated after review (reviewer, timestamp, verdict, reasoning) (Phase 3.2)
- [x] AC16: `learn_preference` still bypasses Trust Gate — user input is auto-approved (Phase 3.2)

## Deviations from Plan

- **Phase 3.1**: Added `html.escape()` for XML tag injection defense — spec mentioned XML wrapping but not escaping. Caught by Codex during implementation consultation.
- **Phase 3.1**: Parse errors classified as `verdict="error"` (infrastructure failure) rather than `verdict="reject"` (reviewer decision). Spec was ambiguous; Codex caught the misclassification during consultation.
- **Phase 3.2**: Added fail-closed guard in `navigation.py` for when `prompt_cache` is None — prevents silent bypass if server starts without prompts. Caught by Gemini during plan consultation.
- **Phase 3.3**: Merged into Phase 3.2 commit (human policy guard was a single function check). Separate consultation still ran.

## Key Metrics

- **Commits**: 8 on the branch (since diverging from main)
- **Tests**: 112 passing (87 existing + 25 new)
- **Files created**: `src/fava_trails/trust_gate.py` (321 lines), `tests/test_trust_gate.py` (612 lines)
- **Files modified**: `src/fava_trails/models.py`, `src/fava_trails/config.py`, `src/fava_trails/server.py`, `src/fava_trails/trail.py`, `src/fava_trails/tools/navigation.py`, `pyproject.toml`, `codev/protocols/aspir/protocol.json`
- **Files deleted**: none
- **Net LOC impact**: +1,296 lines (across 17 files including consultations)

## Consultation Iteration Summary

21 consultation files produced (7 rounds x 3 models). 20 APPROVE, 1 REQUEST_CHANGES.

| Phase | Iters | Who Blocked | What They Caught |
|-------|-------|-------------|------------------|
| Specify | 1 | Claude | Missing `ValidationStatus.ERROR` enum, `auto` policy default, dangling reference |
| Plan | 1 | Gemini | Fail-open bypass when `prompt_cache` is None |
| Phase 3.1 | 1 | — | All approved |
| Phase 3.2 | 1 | — | All approved |
| Phase 3.3 | 1 | — | All approved |
| Phase 3.4 | 1 | — | All approved |
| Implement | 1 | Codex | XML tag injection, parse error misclassification |

**Most frequent blocker**: Codex — blocked in 2 of 7 rounds, focused on: security (XML injection) and correctness (error classification).

### Avoidable Iterations

1. **XML escaping should have been applied from the start**: The spec explicitly called for prompt injection defense, and XML tag injection is a well-known attack vector. The builder should have applied `html.escape()` without needing reviewer feedback.

2. **Parse errors should have been classified as "error" from the start**: The spec explicitly defines fail-closed semantics with `validation_status: "error"` for infrastructure failures. The builder should have distinguished parse failures from reviewer rejections without needing reviewer feedback.

## Consultation Feedback

### Specify Phase (Round 1)

#### Claude
- **Concern**: `ValidationStatus.ERROR` enum value missing from spec
  - **Addressed**: Added `ERROR = "error"` to enum in `models.py`
- **Concern**: Default policy should not be `auto`
  - **Addressed**: Changed default to `llm-oneshot`
- **Concern**: Default `trust-gate-prompt.md` not a deliverable
  - **Rebutted**: Data-repo concern, not engine code. Engine errors with actionable message.
- **Concern**: `memory-quality-judge.md` dangling reference
  - **N/A**: Reference context for spec author, not a code dependency
- **Concern**: OpenRouter timeout unspecified
  - **Addressed**: Hardcoded 30s timeout in implementation
- **Concern**: API key validation at startup
  - **Rebutted**: Validated at call time — startup validation would prevent server starting for trails not using `llm-oneshot`

#### Codex
- No concerns raised (APPROVE)

#### Gemini
- No concerns raised (APPROVE)

### Plan Phase (Round 1)

#### Claude
- No concerns raised (APPROVE)

#### Codex
- **Concern**: `TrustGateConfig` model vs simple scalar fields
  - **N/A**: Implementation correctly uses simple fields on existing config models
- **Concern**: Default prompt not bootstrapped
  - **Rebutted**: Data-repo concern

#### Gemini
- **Concern**: Fail-open bypass when `prompt_cache` is None in `navigation.py`
  - **Addressed**: Added fail-closed guard returning error if policy is `llm-oneshot` and cache is missing

### Implementation Phase (Round 1)

#### Claude
- No concerns raised (APPROVE) — confirmed both Codex/Gemini issues were fixed

#### Codex
- **Concern**: XML tag injection in `_build_review_payload` — thought content embedded without escaping
  - **Addressed**: Added `html.escape()` for thought content and metadata
- **Concern**: Parse errors misclassified as `verdict="reject"` instead of `verdict="error"`
  - **Addressed**: Changed to `verdict="error"` for infrastructure failures

#### Gemini
- **Concern**: Blocking I/O in async methods (synchronous file reads)
  - **N/A**: Acceptable for single-user local MCP tool
- **Concern**: Hardcoded 30s timeout
  - **N/A**: Reasonable default, can be made configurable later

### Phases 3.1–3.4 (Individual Phase Consultations)

All 12 consultations (4 phases x 3 models) returned APPROVE with no concerns.

## Lessons Learned

### What Went Well
- Fail-closed architecture was the right default — every error path keeps thoughts in drafts
- Hierarchical prompt resolution mirrors CLAUDE.md pattern, making it intuitive
- `TrustResult` dataclass provides clean abstraction across all policies
- Separating `error` (infrastructure) from `rejected` (reviewer decision) in `ValidationStatus` gives agents clear retry signals
- 3-way consultation caught real security issues (XML injection) before merge

### Challenges Encountered
- **Fail-open bypass**: The initial `navigation.py` integration had a code path that silently skipped Trust Gate when `prompt_cache` was None. Cost 1 iteration to fix. Root cause: defensive coding that treated missing config as "not enabled" rather than "misconfigured".
- **XML injection**: Spec mentioned XML wrapping but not escaping. The builder embedded raw content into XML tags, creating an injection vector. Cost 1 iteration to fix.
- **Error classification**: Parse failures were initially returned as `reject` (reviewer decision), which would tell agents "don't retry" when the correct signal was "infrastructure problem, retry later". Cost 1 iteration to fix.

### What Would Be Done Differently
- Apply input escaping by default whenever untrusted content is embedded in structured output — don't wait for reviewers to catch it
- Treat "missing configuration" as an error, never as "feature disabled" — fail-closed should be the default mental model
- Distinguish infrastructure failures from semantic failures in the initial design, not as a fix

## Architecture Updates

No `codev/resources/arch.md` file exists in this project yet. Key architectural additions from this spec that should be documented when `arch.md` is created:

- **Trust Gate module** (`src/fava_trails/trust_gate.py`): review gate intercepting `propose_truth`, with `TrustGatePromptCache` (startup-loaded, anti-tampering), `TrustResult` dataclass, and fail-closed OpenRouter integration
- **Prompt hierarchy**: `trust-gate-prompt.md` files resolved most-specific-first, cached at startup, never re-read from disk
- **Configuration**: `trust_gate` policy in `config.yaml` (global) and `.fava-trails.yaml` (trail-level), `openrouter_api_key_env` and `trust_gate_model` in global config
- **Validation status**: `ValidationStatus` enum extended with `ERROR` for infrastructure failures (distinct from `REJECTED` for reviewer decisions)

## Lessons Learned Updates

No `codev/resources/lessons-learned.md` file exists in this project yet. Key lessons from this spec that should be documented when `lessons-learned.md` is created:

- **Fail-closed by default**: When a review/validation system has a "not configured" state, treat it as an error — never silently skip the check. The `prompt_cache is None` bypass was caught by consultation.
- **Escape untrusted input in all structured contexts**: XML, JSON, YAML — if untrusted content is embedded in a structured format, apply appropriate escaping. Don't assume the consumer will handle it.
- **Distinguish infrastructure errors from semantic errors**: `error` (retry later) vs `reject` (content is bad) are fundamentally different signals. Design for this from the start.

## Technical Debt

- Hardcoded 30-second timeout for OpenRouter calls — could be configurable
- Synchronous file I/O in `TrustGatePromptCache.load_from_trails_dir()` — acceptable for startup but could be async
- No default `trust-gate-prompt.md` shipped with the engine — data repo must provide one
- `learn_preference` bypass is intentional but could be abused to skip review (acknowledged in spec)

## Follow-up Items

- Create default `trust-gate-prompt.md` in data repo bootstrap script
- Implement `human` policy with CLI approval tool (`fava-trails approve <thought_id>`)
- Add prompt checksum verification at startup (anti-tampering hardening)
- Consider TTL/decay for approved thoughts (stale truth detection)
- Additive prompt mode (`trust-gate-prompt-extend.md`) to extend rather than replace parent scope prompts

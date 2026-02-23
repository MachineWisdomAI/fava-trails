# Plan 3: Trust Gate

**Status:** not started
**Spec:** `codev/specs/3-trust-gate.md`

---

## Phase 3.1: Trust Gate Core + Critic Prompt Loading

**Goal:** Trust Gate intercepts `propose_truth` with critic or human policy. Prompt loaded from data repo.

**Files created:**
- `src/fava_trail/trust_gate.py` — prompt loading, OpenRouter API call, verdict parsing, redaction layer

**Files modified:**
- `src/fava_trail/models.py` — add `TrustGateConfig` to `GlobalConfig` and `TrailConfig`
- `src/fava_trail/config.py` — load trust gate config, resolve prompt file path

**Key patterns:**
- `TrustGatePromptCache` — on startup, walks all trail directories under `$FAVA_TRAIL_DATA_REPO/trails/`, finds every `trust-gate-prompt.md`, caches `{scope_prefix → prompt_content}` in memory
- `resolve_prompt(scope)` → walks from most-specific to least-specific scope, returns first cached prompt (e.g. for `mw/eng/fava-trails`, checks `mw/eng/fava-trails` → `mw/eng` → `mw` → root `trails/`)
- `review_thought(thought, prompt, model)` → async httpx POST to OpenRouter, returns `{verdict: "approve"|"reject", reasoning: "..."}`
- Redaction: strip `agent_id`, `metadata.extra` before sending
- No prompt at any level → raise `TrustGateConfigError` with actionable message
- Prompts are **never re-read from disk** after startup — prevents adversarial tampering

**Done criteria:**
- Prompt hierarchy discovered and cached at startup
- `resolve_prompt("mw/eng/fava-trails")` returns most-specific match
- Missing prompt at all levels → clear error
- OpenRouter call succeeds with test thought
- Redaction confirmed (sensitive fields stripped)

## Phase 3.2: `propose_truth` Integration

**Goal:** Wire Trust Gate into the promotion flow. Critic path works; human path raises NotImplementedError.

**Files modified:**
- `src/fava_trail/trail.py` — `propose_truth()` calls Trust Gate before namespace move
- `src/fava_trail/tools/navigation.py` — `handle_propose_truth()` routes through Trust Gate

**Key patterns:**
- `critic` mode: `propose_truth()` → `trust_gate.review_thought()` → approve → move to namespace / reject → stay in drafts
- `human` mode: `propose_truth()` → raise `NotImplementedError` with TODO and message listing future channels
- `learn_preference` bypasses Trust Gate entirely (existing behavior preserved)
- Provenance: on approval/rejection, store `{reviewer_model, reviewed_at, verdict, reasoning}` in thought metadata

**Done criteria:**
- `propose_truth` with critic policy blocks on OpenRouter verdict
- Approved → permanent namespace, `validation_status: "approved"`
- Rejected → stays in drafts, `validation_status: "rejected"`, reasoning attached
- Human mode → `NotImplementedError` with clear message
- `learn_preference` unaffected

## Phase 3.3: Human Policy Guard + Extensibility Stub

**Goal:** `trust_gate: human` raises `NotImplementedError` with clear guidance. Extensibility designed but shelved.

**Files modified:**
- `src/fava_trail/trust_gate.py` — add guard in `review_thought()` that raises for `human` policy with TODO comment listing future channels (CLI, PR/GHA, MCP tools)

**Done criteria:**
- `propose_truth` with `trust_gate: human` raises `NotImplementedError`
- Error message names available policy (`critic`) and references spec for planned channels
- Tool count unchanged: 15 (no new tools registered)

## Phase 3.4: Tests

**Goal:** Full test coverage for Trust Gate flows.

**Files modified:**
- `tests/test_tools.py` — Trust Gate integration tests

**Test scenarios:**
1. Critic approves → thought promoted
2. Critic rejects → thought stays in drafts with rejection reason
3. Human mode → `NotImplementedError` raised
4. Missing prompt at all hierarchy levels → actionable error
5. Prompt hierarchy resolution: most-specific scope wins
6. Prompts loaded at startup, not re-read from disk
7. `learn_preference` bypasses Trust Gate
8. Redaction: sensitive fields not in OpenRouter payload
9. Provenance fields populated after review

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
| 3.4 | Tests | Full coverage for critic flow + hierarchy + guard |

Each phase ends with a git commit. Phases are sequential.

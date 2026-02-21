# Branch: main — Status

**Last updated:** 2026-02-21
**Active protocol:** SPIR Phase 2 (Hierarchical Scoping)

## Current Session

| Item | Description | Status |
|------|-------------|--------|
| Phase 2.1 | `sanitize_scope_path`, `resolve_scope_globs` in config.py | complete |
| Phase 2.2 | Server + tools: required trail_name, recall multi-scope, list_scopes, change_scope | complete |
| Phase 2.3 | Tests: 13 new tests, nested_trail_managers fixture, cross-scope prefix fix | complete |
| CLAUDE.md | Updated tool docs (trail_name required, list_scopes, change_scope, multi-scope recall) | complete |

## Phase Status

| Phase | Deliverable | Status | Spec | Plan |
|-------|-------------|--------|------|------|
| 0 | Repository separation | complete | `0-repo-separation` | `0-repo-separation` |
| 1 + 1b | Core MCP + storage substrate | complete | `1-wise-fava-trail` + `1b-storage-substrate-amendments` | same |
| TICK 1b-001 | Recall query fix | complete | (amendment to 1b) | (amendment to 1b) |
| **2** | **Hierarchical Scoping** | **complete** | `2-hierarchical-scoping` | `2-hierarchical-scoping` |
| 3 | Trust Gate | not started | `3-trust-gate` | `3-trust-gate` |
| 4 | Desktop Bridge | not started | `4-desktop-bridge` | `4-desktop-bridge` |
| 5 | Pull Daemon | not started | `5-pull-daemon` | `5-pull-daemon` |
| 6 | Recall Enhancements | not started | `6-recall-enhancements` | `6-recall-enhancements` |
| 7 | Semantic Recall | not started | `7-semantic-recall` | `7-semantic-recall` |
| 8 | Eval Framework | not started | `8-eval-framework` | `8-eval-framework` |
| 9 | Toolkit Migration | not started | `9-toolkit-migration` | `9-toolkit-migration` |
| 10 | codev Integration | not started | `10-codev-integration` | `10-codev-integration` |
| 11 | OpenClaw Memory Driver | not started | `11-openclaw-memory-driver` | `11-openclaw-memory-driver` |

## Test Status

87 tests pass (74 baseline + 13 new from Phase 2).

## Next Step: Phase 3 — Trust Gate

See `codev/specs/3-trust-gate.md`. Adds validation lifecycle (draft → proposed → approved/rejected/tombstoned) with configurable auto-approve rules.

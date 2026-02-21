# Branch: main — Status

**Last updated:** 2026-02-21
**Active protocol:** SPIR Phase 2 (Hierarchical Scoping)

## Current Session

| Item | Description | Status |
|------|-------------|--------|
| SPIR v2 | Placed at `codev/spir-v2.md` | complete |
| TICK 1b-001 fix | Recall word-level AND matching | complete |
| TICK 1b-001 tests | 4 new recall tests (multi-word, scope tags, scope branch, tag-only) | complete |
| TICK 1b-001 review | `codev/reviews/1b-storage-substrate-amendments-tick-001.md` | complete |
| Phase breakdown | Reorganized into single-deliverable phases (2-10) | complete |
| Phase renumber | Inserted Phase 2 (Hierarchical Scoping), shifted 2-10 → 3-11 | in-progress |

## Phase Status

| Phase | Deliverable | Status | Spec | Plan |
|-------|-------------|--------|------|------|
| 0 | Repository separation | complete | `0-repo-separation` | `0-repo-separation` |
| 1 + 1b | Core MCP + storage substrate | complete | `1-wise-fava-trail` + `1b-storage-substrate-amendments` | same |
| TICK 1b-001 | Recall query fix | complete | (amendment to 1b) | (amendment to 1b) |
| **2** | **Hierarchical Scoping** | **in-progress** | `2-hierarchical-scoping` | `2-hierarchical-scoping` |
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

73 tests pass (69 baseline + 4 new from TICK 1b-001).

## Next Step: Phase 2 — Hierarchical Scoping

See `codev/specs/2-hierarchical-scoping.md`. Makes `trail_name` a `/`-separated scope path, adds multi-scope `recall` with glob support, renames `list_trails` → `list_scopes`, adds `change_scope` tool for cross-scope thought elevation.

# Branch: main — Status

**Last updated:** 2026-02-20
**Active protocol:** None (between phases)

## Current Session

| Item | Description | Status |
|------|-------------|--------|
| SPIR v2 | Placed at `codev/spir-v2.md` | complete |
| TICK 1b-001 fix | Recall word-level AND matching | complete |
| TICK 1b-001 tests | 4 new recall tests (multi-word, scope tags, scope branch, tag-only) | complete |
| TICK 1b-001 review | `codev/reviews/1b-storage-substrate-amendments-tick-001.md` | complete |
| Phase breakdown | Created specs + plans for Phases 2-5 from SPIR v2 | complete |

## Phase Status

| Phase | Description | Status | Spec | Plan |
|-------|-------------|--------|------|------|
| Phase 0 | Repository separation | complete | `codev/specs/0-repo-separation.md` | `codev/plans/0-repo-separation.md` |
| Phase 1 + 1b | Core MCP server + storage substrate | complete | `codev/specs/1-wise-fava-trail.md` + `1b-storage-substrate-amendments.md` | `codev/plans/1-wise-fava-trail.md` + `1b-storage-substrate-amendments.md` |
| TICK 1b-001 | Recall query fix + scope test coverage | complete | (amendment to Spec 1b) | (amendment to Plan 1b) |
| Phase 2 | Dogfood + Desktop Bridge | not started | `codev/specs/2-dogfood-desktop-bridge.md` | `codev/plans/2-dogfood-desktop-bridge.md` |
| Phase 3 | Semantic Recall + Trust Gate | not started | `codev/specs/3-semantic-recall-trust-gate.md` | `codev/plans/3-semantic-recall-trust-gate.md` |
| Phase 4 | codev Integration | not started | `codev/specs/4-codev-integration.md` | `codev/plans/4-codev-integration.md` |
| Phase 5 | OpenClaw Memory Driver | not started | `codev/specs/5-openclaw-memory-driver.md` | `codev/plans/5-openclaw-memory-driver.md` |

## Test Status

73 tests pass (69 baseline + 4 new from TICK 1b-001).

## SPIR Artifacts

| Type | Files |
|------|-------|
| Specs | `0-repo-separation`, `1-wise-fava-trail`, `1b-storage-substrate-amendments`, `2-dogfood-desktop-bridge`, `3-semantic-recall-trust-gate`, `4-codev-integration`, `5-openclaw-memory-driver` |
| Plans | Same numbering as specs |
| Reviews | `0-repo-separation`, `1-wise-fava-trail`, `1b-storage-substrate-amendments`, `1b-storage-substrate-amendments-tick-001` |

## Next Steps (Phase 2)

See `codev/specs/2-dogfood-desktop-bridge.md` and `codev/plans/2-dogfood-desktop-bridge.md`. Priority order:
1. Desktop bridge (`scripts/mcp-fava-wrapper.sh`)
2. Pull Daemon (one daemon for monorepo)
3. `recall` enhancements (`applicable_preferences` + `include_relationships`)
4. Eval scripts (`eval/crash_recovery.py`, `eval/recall_relevance.py`)
5. Toolkit migration adapter

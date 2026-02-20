# Branch: main — Status

**Last updated:** 2026-02-20
**Active protocol:** TICK 1b-001 (completed)

## Current Session

| Item | Description | Status |
|------|-------------|--------|
| SPIR v2 | Placed at `codev/spir-v2.md` | complete |
| TICK 1b-001 fix | Recall word-level AND matching | complete |
| TICK 1b-001 tests | 4 new recall tests (multi-word, scope tags, scope branch, tag-only) | complete |
| TICK 1b-001 review | `codev/reviews/1b-storage-substrate-amendments-tick-001.md` | complete |

## Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Repository separation | complete |
| Phase 1 + 1b | Core MCP server + storage substrate | complete |
| TICK 1b-001 | Recall query fix + scope test coverage | complete |
| Phase 2 | Dogfood + Desktop Bridge | not started |

## Test Status

73 tests pass (69 baseline + 4 new from TICK 1b-001).

## Next Steps (Phase 2)

See `codev/spir-v2.md` Phase 2 section. Priority order:
1. Desktop bridge (`scripts/mcp-fava-wrapper.sh`)
2. Pull Daemon (one daemon for monorepo)
3. Eval scripts (`eval/crash_recovery.py`, `eval/recall_relevance.py`)
4. Toolkit migration adapter

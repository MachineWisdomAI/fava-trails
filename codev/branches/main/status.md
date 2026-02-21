# Branch: main — Status

**Last updated:** 2026-02-21
**Active protocol:** None (between phases)

## Current Session

| Item | Description | Status |
|------|-------------|--------|
| SPIR v2 | Placed at `codev/spir-v2.md` | complete |
| TICK 1b-001 fix | Recall word-level AND matching | complete |
| TICK 1b-001 tests | 4 new recall tests (multi-word, scope tags, scope branch, tag-only) | complete |
| TICK 1b-001 review | `codev/reviews/1b-storage-substrate-amendments-tick-001.md` | complete |
| Phase breakdown | Reorganized into single-deliverable phases (2-10) | complete |

## Phase Status

| Phase | Deliverable | Status | Spec | Plan |
|-------|-------------|--------|------|------|
| 0 | Repository separation | complete | `0-repo-separation` | `0-repo-separation` |
| 1 + 1b | Core MCP + storage substrate | complete | `1-wise-fava-trail` + `1b-storage-substrate-amendments` | same |
| TICK 1b-001 | Recall query fix | complete | (amendment to 1b) | (amendment to 1b) |
| **2** | **Trust Gate** | **not started** | `2-trust-gate` | `2-trust-gate` |
| 3 | Desktop Bridge | not started | `3-desktop-bridge` | `3-desktop-bridge` |
| 4 | Pull Daemon | not started | `4-pull-daemon` | `4-pull-daemon` |
| 5 | Recall Enhancements | not started | `5-recall-enhancements` | `5-recall-enhancements` |
| 6 | Semantic Recall | not started | `6-semantic-recall` | `6-semantic-recall` |
| 7 | Eval Framework | not started | `7-eval-framework` | `7-eval-framework` |
| 8 | Toolkit Migration | not started | `8-toolkit-migration` | `8-toolkit-migration` |
| 9 | codev Integration | not started | `9-codev-integration` | `9-codev-integration` |
| 10 | OpenClaw Memory Driver | not started | `10-openclaw-memory-driver` | `10-openclaw-memory-driver` |

## Test Status

73 tests pass (69 baseline + 4 new from TICK 1b-001).

## Next Step: Phase 2 — Trust Gate

See `codev/specs/2-trust-gate.md`. Every thought promoted via `propose_truth` must pass critic or human review. No auto-bypass. Critic prompt loaded from `$FAVA_TRAIL_DATA_REPO/trust-gate-prompt.md`.

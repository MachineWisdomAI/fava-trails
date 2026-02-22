# Spec 8: Evaluation Framework

**Status:** not started
**Epic:** 0002a-desktop-pipeline
**Source:** `codev/spir-v2.md` Phase 2 (eval sections)
**Prerequisites:** Spec 5 (Pull Daemon)

---

## Problem Statement

No automated tests exist for two critical operational properties:

1. **Crash recovery** — JJ's crash-proof snapshots should guarantee zero data loss after SIGKILL, but this is unverified
2. **Recall accuracy** — No metrics exist for recall precision/relevance against a known corpus

## Proposed Solution

Two evaluation scripts in `eval/`:

### `eval/crash_recovery.py`

SIGKILL chaos test: spawn MCP server, save thoughts, send SIGKILL mid-execution, restart, assert recovery via `jj op restore` with zero data loss.

### `eval/recall_relevance.py`

Sample-based audit: create known corpus of thoughts with expected query→result mappings, run queries, measure precision and recall.

## Done Criteria

- `crash_recovery.py` passes — zero data loss after SIGKILL
- `recall_relevance.py` produces accuracy metrics for known corpus
- Both scripts runnable standalone (`python eval/crash_recovery.py`)

## Out of Scope

- CI/CD integration (future)
- Performance benchmarking (future)

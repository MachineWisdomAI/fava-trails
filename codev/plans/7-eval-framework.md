# Plan 7: Evaluation Framework

**Status:** not started
**Spec:** `codev/specs/7-eval-framework.md`

---

## Phase 7.1: Crash Recovery Eval

**Files created:**
- `eval/crash_recovery.py` — SIGKILL chaos test

**Key patterns:**
- Spawn MCP server subprocess
- Save N thoughts via MCP client
- SIGKILL the process mid-write
- Restart server, verify all committed thoughts recovered
- Assert `jj op restore` can recover to any prior state

**Done criteria:**
- Script passes — zero data loss after SIGKILL

## Phase 7.2: Recall Relevance Eval

**Files created:**
- `eval/recall_relevance.py` — sample-based accuracy audit

**Key patterns:**
- Create known corpus (50+ thoughts with varied content, tags, namespaces)
- Define query→expected_results mappings
- Run queries, measure precision (relevant results / total results) and recall (found relevant / total relevant)
- Output metrics report

**Done criteria:**
- Script produces precision/recall metrics
- Baseline metrics documented

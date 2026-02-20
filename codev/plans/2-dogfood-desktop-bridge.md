# Plan 2: Dogfood + Desktop Bridge

**Status:** not started
**Spec:** `codev/specs/2-dogfood-desktop-bridge.md`

---

## Phase 2.1: Desktop Bridge

**Goal:** Claude Desktop on Windows can connect to FAVA Trail MCP server running in WSL2.

**Files created:**
- `scripts/mcp-fava-wrapper.sh` — wsl.exe wrapper for stdio MCP traffic

**Done criteria:**
- Claude Desktop `claude_desktop_config.json` points to wrapper script
- MCP tool calls from Desktop reach the WSL2 server and return responses
- `save_thought` from Desktop creates thought in same trail as Code

## Phase 2.2: Pull Daemon

**Goal:** Background sync loop keeps local monorepo in sync with remote.

**Files created:**
- `src/fava_trail/daemon/__init__.py`
- `src/fava_trail/daemon/pull_daemon.py` — async loop: `fetch_and_rebase()` at interval

**Key patterns:**
- One daemon for entire monorepo (not per-trail)
- On conflict: `jj op restore` to pre-rebase state, notify agent
- Configurable interval (default: 30s)
- Graceful shutdown on SIGTERM/SIGINT
- Non-blocking — daemon errors logged, never crash the server

**Done criteria:**
- Daemon runs in background, periodically syncs
- Conflict after rebase triggers automatic rollback + notification
- Daemon shutdown is clean (no orphaned processes)

## Phase 2.3: `recall` Enhancements

**Goal:** `recall` returns preferences and supports relationship traversal.

**Files modified:**
- `src/fava_trail/tools/recall.py` — add `applicable_preferences` injection and `include_relationships` traversal
- `src/fava_trail/trail.py` — `recall()` method enhanced for preference scanning and 1-hop traversal

**Key patterns:**
- `applicable_preferences`: scan `preferences/` namespace for thoughts whose scope overlaps with query scope; return alongside results
- `include_relationships`: for each matching thought, also return immediate `DEPENDS_ON` and `REVISED_BY` targets via file read by ULID
- Both features are additive — no changes to existing recall behavior

**Done criteria:**
- `recall` response includes `applicable_preferences` field (empty list if no matches)
- `recall` with `include_relationships=True` returns 1-hop related thoughts
- Existing recall tests still pass (backward compatible)

## Phase 2.4: Evaluation Scripts

**Goal:** Automated evaluation for crash recovery and recall accuracy.

**Files created:**
- `eval/crash_recovery.py` — SIGKILL chaos test
- `eval/recall_relevance.py` — sample-based recall accuracy audit

**Key patterns:**
- `crash_recovery.py`: spawns MCP server, saves thoughts, sends SIGKILL, restarts, asserts recovery via `jj op restore`
- `recall_relevance.py`: creates known corpus of thoughts, queries with expected results, measures precision/recall

**Done criteria:**
- `crash_recovery.py` passes — zero data loss after SIGKILL
- `recall_relevance.py` produces accuracy metrics for known corpus

## Phase 2.5: Toolkit Migration Adapter

**Goal:** One-time migration path from wise-agents-toolkit flat-file memory.

**Files created:**
- `src/fava_trail/adapters/__init__.py`
- `src/fava_trail/adapters/toolkit.py` — reads flat-file memory, converts to FAVA Trail thoughts

**Migration map:**

| Source | Target namespace | `source_type` | Extra metadata |
|--------|-----------------|---------------|----------------|
| `decisions.md` | `decisions/` | `decision` | `validation_status: "approved"` |
| `gotchas.md` | `observations/` | `observation` | `tags: ["gotcha"]` |
| `branches/<branch>/status.md` | `drafts/` | `observation` | `branch: "<branch>"` |

**Done criteria:**
- Migration script reads flat-file memory from specified directory
- Thoughts created with correct namespace, source_type, and metadata
- Idempotent — re-running doesn't create duplicates

## Phase 2.6: Integration Testing

**Goal:** End-to-end verification of cross-agent workflows.

**Tests:**
- Claude Code saves thought → Claude Desktop reads it (via shared monorepo)
- Pull Daemon syncs Desktop writes → Code sees them on next `recall`
- `learn_preference` from Desktop → Code's `recall` includes it in `applicable_preferences`

**Done criteria:**
- All existing tests pass (73+ baseline)
- New integration tests for cross-agent workflows pass
- Manual verification: both Code and Desktop sessions use FAVA Trail successfully

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 2.1 | Desktop Bridge | `scripts/mcp-fava-wrapper.sh` for WSL2 |
| 2.2 | Pull Daemon | Background sync loop with conflict safety |
| 2.3 | Recall Enhancements | `applicable_preferences` + `include_relationships` |
| 2.4 | Eval Scripts | Crash recovery + recall accuracy |
| 2.5 | Toolkit Migration | Flat-file → FAVA Trail converter |
| 2.6 | Integration Testing | Cross-agent e2e verification |

Each phase ends with a git commit. Phases are sequential.

# Plan 4: codev Integration

**Status:** not started
**Spec:** `codev/specs/4-codev-integration.md`

---

## Phase 4.1: codev Adapter — File Watcher

**Goal:** Monitor codev `status.yaml` and version state changes as FAVA Trail thoughts.

**Files created:**
- `src/fava_trail/adapters/codev.py` — file watcher on `status.yaml`, auto-versions as thoughts

**Key patterns:**
- Filesystem polling (or `watchfiles` if available) for `status.yaml` changes
- On change: diff against previous state, save thought with change summary
- Thought content includes full `status.yaml` snapshot for point-in-time reconstruction
- Thoughts created in `observations/` namespace with `source_type: "tool_output"`
- `metadata.tags: ["codev", "porch", "state-change"]`
- Graceful start/stop lifecycle

**Done criteria:**
- `status.yaml` change detected within polling interval
- Thought saved with correct namespace, tags, and content
- Previous state tracked for diff generation
- Watcher starts/stops cleanly

## Phase 4.2: State History Retrieval

**Goal:** Full codev project state history retrievable via FAVA Trail.

**Files modified:**
- `src/fava_trail/adapters/codev.py` — add `get_state_history()` helper
- Tests for state change versioning and history reconstruction

**Done criteria:**
- `recall(scope={"tags": ["codev", "porch"]})` returns chronological state changes
- State at any point in time reconstructible from thought content
- Rollback achievable by reading prior thought's `status.yaml` snapshot

## Phase 4.3: Integration Testing

**Goal:** End-to-end verification of codev state versioning.

**Tests:**
- SPIR phase transition (in-progress → completed) creates thought
- Multiple rapid state changes each captured individually
- `recall` returns full history in chronological order
- State reconstruction from thought content matches original `status.yaml`

**Done criteria:**
- All new tests pass
- All existing tests pass (no regressions)
- Manual verification: codev phase transition → thought appears in trail

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 4.1 | File Watcher | `status.yaml` monitoring + auto-versioning |
| 4.2 | State History | Retrieval and reconstruction helpers |
| 4.3 | Integration Testing | E2e verification |

Each phase ends with a git commit. Phases are sequential.

# Spec 4: codev Integration

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 4
**Prerequisites:** Spec 3 (semantic recall + trust gate)

---

## Problem Statement

The codev protocol (v2.0.13) manages project state via a `status.yaml` Porch file. State changes (phase transitions, status updates, blocking events) are ephemeral — they exist only in the current file state with no versioned history. When a SPIR phase transitions from `in-progress` to `completed`, the previous state is overwritten.

This means:
- No audit trail for project state transitions
- No ability to rollback project to a prior phase state
- No cross-agent visibility into codev state changes via FAVA Trail

## Proposed Solution

A file watcher adapter that monitors codev `status.yaml` changes and automatically versions them as FAVA Trail thoughts.

### File Watcher (`src/fava_trail/adapters/codev.py`)

Monitors `status.yaml` for changes (filesystem events or polling). On each change:
1. Read the new `status.yaml` content
2. Diff against the previous known state
3. Save a thought with the state change as content, tagged with `["codev", "porch", "state-change"]`
4. Include the full `status.yaml` snapshot in the thought for point-in-time reconstruction

### Integration with FAVA Trail

- Thoughts stored in `observations/` namespace (auto-promoted, not drafts)
- `metadata.project` set to the codev project name
- `metadata.tags` includes `["codev", "porch"]`
- `recall(scope={"tags": ["codev", "porch"]})` retrieves full state history

## Done Criteria

- Porch state changes auto-versioned as FAVA Trail thoughts
- Full state history retrievable via `recall`
- Can reconstruct project state at any point in time from thought history
- Can rollback project to prior state via thought content
- File watcher starts/stops cleanly (no orphaned watchers)

## Out of Scope

- Modifying codev protocol itself (this is an adapter, not a codev change)
- Real-time notifications to agents on state change (future enhancement)
- OpenClaw integration (Phase 5)

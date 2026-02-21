# Spec 9: codev Integration

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 4
**Prerequisites:** Spec 6 (Semantic Recall)

---

## Problem Statement

The codev protocol (v2.0.13) manages project state via a `status.yaml` Porch file. State changes are ephemeral — overwritten in place with no versioned history, no audit trail, and no cross-agent visibility.

## Proposed Solution

A file watcher adapter (`src/fava_trail/adapters/codev.py`) that monitors `status.yaml` changes and automatically versions them as FAVA Trail thoughts.

On each change:
1. Read the new `status.yaml` content
2. Diff against previous known state
3. Save thought with state change as content, tagged `["codev", "porch", "state-change"]`
4. Include full `status.yaml` snapshot for point-in-time reconstruction

## Done Criteria

- Porch state changes auto-versioned as FAVA Trail thoughts
- Full state history retrievable via `recall`
- State at any point reconstructible from thought content
- File watcher starts/stops cleanly

## Out of Scope

- Modifying codev protocol itself
- Real-time agent notifications on state change

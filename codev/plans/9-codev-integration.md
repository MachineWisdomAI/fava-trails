# Plan 9: codev Integration

**Status:** not started
**Spec:** `codev/specs/9-codev-integration.md`

---

## Phase 9.1: File Watcher Adapter

**Files created:**
- `src/fava_trail/adapters/codev.py` — `status.yaml` watcher, auto-versions changes

**Done criteria:**
- `status.yaml` changes detected within polling interval
- Thought saved with correct namespace and tags
- Watcher starts/stops cleanly

## Phase 9.2: State History + Tests

**Tests:**
- Phase transition creates thought
- Multiple rapid changes each captured
- `recall(scope={"tags": ["codev", "porch"]})` returns chronological history
- State reconstruction from thought content matches original

**Done criteria:**
- All new tests pass
- All existing tests pass

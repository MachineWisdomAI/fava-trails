# Spec 9: Toolkit Migration Adapter

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 2 (migration section)
**Prerequisites:** Spec 3 (Trust Gate)

---

## Problem Statement

wise-agents-toolkit's flat-file memory (`memory/shared/decisions.md`, `memory/shared/gotchas.md`, `memory/branches/<branch>/status.md`) has no automated migration path to FAVA Trail namespaces.

## Proposed Solution

A migration script (`src/fava_trail/adapters/toolkit.py`) that reads flat-file memory and creates FAVA Trail thoughts with correct namespaces and metadata.

### Migration Map

| Source | Target namespace | `source_type` | Extra metadata |
|--------|-----------------|---------------|----------------|
| `decisions.md` | `decisions/` | `decision` | `validation_status: "approved"` |
| `gotchas.md` | `observations/` | `observation` | `tags: ["gotcha"]` |
| `branches/<branch>/status.md` | `drafts/` | `observation` | `branch: "<branch>"` |

### Idempotency

Re-running the migration does not create duplicates. The adapter checks for existing thoughts with matching content hashes before creating new ones.

## Done Criteria

- Migration reads flat-file memory from specified directory
- Thoughts created with correct namespace, source_type, and metadata
- Idempotent — re-running doesn't create duplicates
- Runnable as CLI command: `uv run fava-trail-migrate --source /path/to/memory`

## Out of Scope

- Migrating from other memory systems
- Bidirectional sync

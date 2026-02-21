# Spec 10: OpenClaw Memory Driver

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 5
**Prerequisites:** Spec 6 (Semantic Recall)

---

## Problem Statement

OpenClaw's `MemorySearchManager` interface has no versioned, auditable backend. FAVA Trail can serve as one, but no adapter exists.

## Proposed Solution

An adapter (`src/fava_trail/adapters/openclaw.py`) implementing OpenClaw's `MemorySearchManager`:

| OpenClaw Method | FAVA Trail Tool |
|----------------|----------------|
| `search()` | `recall_semantic` + `recall` |
| `readFile()` | `get_thought` |
| `sync()` | `sync` |

## Done Criteria

- OpenClaw agent with `backend: "fava-trail"` works end-to-end
- Memories versioned and auditable
- Provenance fields populated (agent_id, timestamps)

## Out of Scope

- Modifying OpenClaw's interface
- Enterprise federation

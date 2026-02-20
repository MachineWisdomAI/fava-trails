# Spec 5: OpenClaw Memory Driver

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 5
**Prerequisites:** Spec 3 (semantic recall + trust gate)

---

## Problem Statement

OpenClaw (Machine Wisdom's AI agent framework) uses a `MemorySearchManager` interface for agent memory. The current implementation has no versioning, no audit trail, and no cross-agent memory sharing — the same three failures that FAVA Trail was built to solve.

FAVA Trail can serve as an alternative memory backend for OpenClaw, but there is no adapter that maps OpenClaw's `MemorySearchManager` interface to FAVA Trail's MCP tools.

## Proposed Solution

An adapter module that implements OpenClaw's `MemorySearchManager` interface using FAVA Trail as the backing store.

### Adapter (`src/fava_trail/adapters/openclaw.py`)

Maps OpenClaw memory operations to FAVA Trail tools:

| OpenClaw Method | FAVA Trail Tool | Notes |
|----------------|----------------|-------|
| `search()` | `recall_semantic` + `recall` | Semantic search first, keyword fallback |
| `readFile()` | `get_thought` | Direct ULID lookup |
| `sync()` | `sync` | Fetch + rebase from remote |

### Configuration

OpenClaw agents configure FAVA Trail as their memory backend:
```yaml
memory:
  backend: "fava-trail"
  trail_name: "openclaw-agent"
  data_repo: "/path/to/fava-trail-data"
```

## Done Criteria

- OpenClaw agent with `backend: "fava-trail"` works end-to-end
- `search()` returns relevant memories via semantic + keyword search
- `readFile()` retrieves specific thought by ID
- `sync()` syncs with remote
- Memories are versioned and auditable via FAVA Trail
- All memories have proper provenance (agent_id, timestamps, relationships)

## Out of Scope

- Modifying OpenClaw's `MemorySearchManager` interface (adapter pattern — we conform to their API)
- Enterprise federation
- Neo4j graph database integration (TKG Bridge path — data already structured for future projection)

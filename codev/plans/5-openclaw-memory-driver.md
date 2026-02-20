# Plan 5: OpenClaw Memory Driver

**Status:** not started
**Spec:** `codev/specs/5-openclaw-memory-driver.md`

---

## Phase 5.1: OpenClaw Adapter

**Goal:** Implement `MemorySearchManager` interface backed by FAVA Trail.

**Files created:**
- `src/fava_trail/adapters/openclaw.py` — maps OpenClaw memory interface to FAVA Trail tools

**Key patterns:**
- `search()` → `recall_semantic` (if Phase 3 available) with `recall` fallback
- `readFile()` → `get_thought` by ULID
- `sync()` → `sync` (fetch + rebase)
- Adapter instantiated with `trail_name` and `data_repo` config
- Uses `TrailManager` directly (not MCP — adapter runs in-process)

**Done criteria:**
- Adapter implements OpenClaw's `MemorySearchManager` interface
- `search()` returns relevant thoughts
- `readFile()` retrieves specific thought
- `sync()` syncs with remote

## Phase 5.2: Integration Testing

**Goal:** End-to-end verification of OpenClaw agent using FAVA Trail memory.

**Tests:**
- OpenClaw agent saves memory → appears as FAVA Trail thought
- OpenClaw agent searches memory → finds relevant thoughts
- Multiple agents share trail → cross-agent memory works
- Sync pulls remote changes → agent sees updated memories

**Done criteria:**
- All integration tests pass
- OpenClaw agent with `backend: "fava-trail"` completes full workflow
- Memories versioned in JJ (visible via `jj log`)
- Provenance fields populated (agent_id, timestamps)

## Phase 5.3: Documentation + Configuration

**Goal:** Document OpenClaw integration setup and configuration.

**Files modified:**
- `CLAUDE.md` — add OpenClaw adapter section
- Update `codev/spir-v2.md` SPIR Artifacts section

**Done criteria:**
- Configuration instructions documented
- Example OpenClaw config provided
- Troubleshooting section for common integration issues

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 5.1 | Adapter | `MemorySearchManager` implementation |
| 5.2 | Integration Testing | E2e verification with OpenClaw agent |
| 5.3 | Documentation | Setup and config docs |

Each phase ends with a git commit. Phases are sequential.

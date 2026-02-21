# Plan 10: OpenClaw Memory Driver

**Status:** not started
**Spec:** `codev/specs/10-openclaw-memory-driver.md`

---

## Phase 10.1: Adapter Implementation

**Files created:**
- `src/fava_trail/adapters/openclaw.py` — `MemorySearchManager` backed by FAVA Trail

**Done criteria:**
- `search()`, `readFile()`, `sync()` mapped to FAVA Trail tools
- Uses `TrailManager` directly (in-process, not MCP)

## Phase 10.2: Integration Testing + Docs

**Tests:**
- Save memory → appears as thought
- Search → finds relevant thoughts
- Multi-agent shared trail works

**Files modified:**
- `CLAUDE.md` — OpenClaw adapter section

**Done criteria:**
- E2e test passes
- Configuration documented

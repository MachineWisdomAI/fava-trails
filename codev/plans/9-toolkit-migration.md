# Plan 9: Toolkit Migration Adapter

**Status:** not started
**Spec:** `codev/specs/9-toolkit-migration.md`

---

## Phase 9.1: Migration Script

**Files created:**
- `src/fava_trail/adapters/__init__.py`
- `src/fava_trail/adapters/toolkit.py` — flat-file memory → FAVA Trail converter

**Key patterns:**
- Parse `decisions.md` (markdown sections → individual decisions)
- Parse `gotchas.md` (markdown sections → individual observations with `["gotcha"]` tag)
- Parse `branches/<branch>/status.md` → drafts with branch metadata
- Content hash check for idempotency

**Done criteria:**
- Reads flat-file memory from specified directory
- Creates thoughts with correct metadata
- Idempotent

## Phase 9.2: CLI Entry Point

**Files modified:**
- `pyproject.toml` — add `fava-trail-migrate` entry point

**Done criteria:**
- `uv run fava-trail-migrate --source /path/to/memory` works
- Progress output shows migrated thought count

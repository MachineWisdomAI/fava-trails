# Plan 7: Semantic Recall

**Status:** not started
**Spec:** `codev/specs/7-semantic-recall.md`

---

## Phase 7.1: SQLite-vec Hybrid Index

**Files created:**
- `src/fava_trails/index/__init__.py`
- `src/fava_trails/index/semantic.py` — SQLite-vec + FTS5 + thought_relationships tables

**Done criteria:**
- SQLite database created on first use
- Vector, FTS5, and relationship tables initialized
- Connection pooling for concurrent access

## Phase 7.2: Index Rebuild

**Files created:**
- `src/fava_trails/index/rebuild.py` — walk thought files, populate index

**Done criteria:**
- Full rebuild scans all namespaces
- Completes in <30s for 500 thoughts
- Malformed files → skip + log warning

## Phase 7.3: `recall_semantic` Tool

**Files modified:**
- `src/fava_trails/tools/recall.py` — add `handle_recall_semantic()`
- `src/fava_trails/server.py` — register `recall_semantic` tool

**Done criteria:**
- Semantic search returns conceptually related thoughts
- Falls back to FTS5 on low confidence
- Response includes `applicable_preferences`
- Superseded thoughts hidden by default

## Phase 7.4: Incremental Indexing

**Files modified:**
- `src/fava_trails/trail.py` — hook index updates into write operations
- `src/fava_trails/server.py` — initialize index at startup

**Done criteria:**
- New thoughts auto-indexed on save
- Updated thoughts re-indexed
- Index rebuilt on startup if missing
- All existing tests pass

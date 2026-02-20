# Plan 3: Semantic Recall + Trust Gate

**Status:** not started
**Spec:** `codev/specs/3-semantic-recall-trust-gate.md`

---

## Phase 3.1: SQLite-vec Hybrid Index

**Goal:** Local SQLite database with vector embeddings, FTS5, and relationship table.

**Files created:**
- `src/fava_trail/index/__init__.py`
- `src/fava_trail/index/semantic.py` — SQLite-vec hybrid index engine

**Key patterns:**
- Three tables: vector embeddings (SQLite-vec), FTS5 full-text, `thought_relationships` (edges from frontmatter)
- Index built incrementally on write operations
- Index is local — not committed to repo, rebuilds from thought files
- Connection pooling for concurrent access

**Dependencies added:**
- `sqlite-vec`

**Done criteria:**
- SQLite database created on first use
- `thought_relationships` table stores edges from frontmatter `relationships` field
- FTS5 table indexed on thought content + metadata
- Vector table stores embeddings for semantic search

## Phase 3.2: Index Rebuild

**Goal:** Cold-start and corruption recovery: rebuild full index from JJ history.

**Files created:**
- `src/fava_trail/index/rebuild.py` — walk thought files, extract content + relationships, populate index

**Done criteria:**
- `rebuild()` scans all thought files across all namespaces
- Populates all three tables (vector, FTS5, relationships)
- Completes in <30s for 500 thoughts
- Handles malformed thought files gracefully (skip + log warning)

## Phase 3.3: `recall_semantic` Tool

**Goal:** New MCP tool for vector-based semantic search.

**Files modified:**
- `src/fava_trail/tools/recall.py` — add `handle_recall_semantic()` handler
- `src/fava_trail/server.py` — register `recall_semantic` tool

**Key patterns:**
- Vector query for semantic similarity
- Falls back to FTS5 keyword matching if vector search returns low-confidence results
- Same response format as `recall` (includes `applicable_preferences`)
- Supersession hiding applied (same as `recall`)

**Done criteria:**
- `recall_semantic("codev upgrade rationale")` returns semantically related thoughts
- Falls back to keyword matching gracefully
- Response includes `applicable_preferences`
- Superseded thoughts hidden by default

## Phase 3.4: Trust Gate

**Goal:** Automated critic agent for thought quality control.

**Files created:**
- `src/fava_trail/daemon/trust_gate.py` — OpenRouter API integration via `httpx`

**Dependencies added:**
- `httpx`

**Key patterns:**
- Trail-level policy config in `.fava-trail.yaml`: `trust_gate: auto | critic | human`
- `critic` mode: send thought content to OpenRouter model, parse approval/rejection
- Redaction layer: strip `agent_id`, `metadata.extra`, and sensitive fields before external calls
- Provenance: record reviewer model, timestamp, and verdict in thought metadata
- `auto` mode: passthrough (no change from current behavior)
- `human` mode: mark as `proposed`, require explicit approval call

**Done criteria:**
- Trust Gate with `auto` policy: identical to current behavior
- Trust Gate with `critic` policy: rejects test hallucination, approves valid thought
- Redaction layer confirmed via test (sensitive fields not sent to OpenRouter)
- Provenance fields populated after review

## Phase 3.5: Integration + Incremental Indexing

**Goal:** Wire index updates into write operations.

**Files modified:**
- `src/fava_trail/trail.py` — hook index updates into `save_thought`, `update_thought`, `supersede`
- `src/fava_trail/server.py` — initialize index at startup, trigger rebuild if index is missing

**Done criteria:**
- New thoughts automatically indexed on save
- Updated thoughts re-indexed
- Superseded thoughts marked in index
- Index rebuilt automatically on first startup if missing
- All existing tests pass (no regressions)

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 3.1 | SQLite-vec Index | Vector + FTS5 + relationships tables |
| 3.2 | Index Rebuild | Cold-start recovery from thought files |
| 3.3 | `recall_semantic` | New MCP tool for semantic search |
| 3.4 | Trust Gate | OpenRouter critic agent with redaction |
| 3.5 | Integration | Incremental indexing on write ops |

Each phase ends with a git commit. Phases are sequential.

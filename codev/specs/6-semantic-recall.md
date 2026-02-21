# Spec 6: Semantic Recall

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 3 (semantic index sections)
**Prerequisites:** Spec 5 (Recall Enhancements)

---

## Problem Statement

Recall uses word-level AND matching — sufficient for keyword search but useless for semantic queries. "codev upgrade rationale" won't find a thought about "migrating SPIR protocol from v1.6.1 to v2.0.13" because they share no keywords.

## Proposed Solution

A local SQLite database combining vector embeddings (SQLite-vec), FTS5 full-text search, and a `thought_relationships` table for graph traversal. Exposed via a new `recall_semantic` MCP tool.

### SQLite Schema

- **Vector table** — embeddings for semantic similarity search
- **FTS5 table** — full-text index for fast keyword matching
- **`thought_relationships` table** — edges from frontmatter `relationships` field. Lightweight graph, upgradeable to Neo4j in future (TKG Bridge path)

### Index Lifecycle

- Built incrementally on `save_thought` / `update_thought` / `supersede`
- Full rebuild from thought files on cold start or corruption
- Index is local (not committed to repo) — each machine rebuilds
- Target: <30s rebuild for 500 thoughts

### New Tool: `recall_semantic`

Vector query → thought_id → fetch. Falls back to FTS5 keyword matching for low-confidence results. Same response format as `recall` (includes `applicable_preferences`).

### Dependencies

- `sqlite-vec` — SQLite extension for vector search

## Done Criteria

- `recall_semantic("codev upgrade rationale")` returns semantically related thoughts
- `thought_relationships` table queryable for graph traversal
- Index rebuilds from thought files in <30s for 500 thoughts
- Falls back to keyword matching gracefully
- Existing `recall` tool unchanged
- Tool count: 16 → 17

## Out of Scope

- Neo4j / full graph database (future TKG Bridge)
- CocoIndex-style CDC pipeline (future)

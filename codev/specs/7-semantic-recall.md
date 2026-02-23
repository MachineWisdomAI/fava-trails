# Spec 7: Semantic Recall

**Status:** not started
**Epic:** 0003a-recall-pipeline
**Source:** `codev/spir-v2.md` Phase 3 (semantic index sections)
**Prerequisites:** Spec 6 (Recall Enhancements)

---

## Problem Statement

Recall uses word-level AND matching — sufficient for keyword search but useless for semantic queries. "codev upgrade rationale" won't find a thought about "migrating SPIR protocol from v1.6.1 to v2.0.13" because they share no keywords.

## Proposed Solution

A local SQLite database combining vector embeddings (SQLite-vec), FTS5 full-text search, and a `thought_relationships` table for graph traversal. Exposed via a new `recall_semantic` MCP tool.

### SQLite Schema

Database file: `$FAVA_TRAIL_DATA_REPO/.fava-index.db` (gitignored, local to each machine).

```sql
-- Vector embeddings for semantic similarity
-- sqlite-vec virtual table (dimension = 384 for all-MiniLM-L6-v2)
CREATE VIRTUAL TABLE vec_thoughts USING vec0(
    thought_id TEXT PRIMARY KEY,
    embedding FLOAT[384]
);

-- Full-text search for keyword matching
CREATE VIRTUAL TABLE fts_thoughts USING fts5(
    thought_id,
    content,
    source_type,
    tags,
    tokenize='porter unicode61'
);

-- Relationship graph edges (from frontmatter relationships field)
CREATE TABLE thought_relationships (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,  -- DEPENDS_ON, REVISED_BY, REFERENCES, SUPERSEDES, etc.
    trail_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, rel_type)
);

-- Metadata index for fast filtering before vector search
CREATE TABLE thought_meta (
    thought_id TEXT PRIMARY KEY,
    trail_name TEXT NOT NULL,
    namespace TEXT NOT NULL,
    source_type TEXT,
    validation_status TEXT,
    created_at TEXT,
    superseded_by TEXT
);
CREATE INDEX idx_meta_trail ON thought_meta(trail_name);
CREATE INDEX idx_meta_ns ON thought_meta(namespace);
```

### Embedding Model

**Model:** `sentence-transformers/all-MiniLM-L6-v2` via the `sentence-transformers` Python package.

- Runs **locally** — no API calls, no API key needed
- 384-dimension output, ~80MB model download on first use
- Fast: ~1ms per embedding on CPU
- Well-established, Apache-2.0 licensed

The model is loaded once at server startup (lazy — only if semantic index is enabled). Embedding generation is synchronous but fast enough to run inline with save operations.

**Fallback:** If `sentence-transformers` is not installed, semantic recall degrades to FTS5-only mode with a warning. The package is an optional dependency (`uv add --optional semantic sentence-transformers sqlite-vec`).

### Index Lifecycle

- **Incremental:** `save_thought` / `update_thought` / `supersede` trigger index updates inline (embed + insert/update row)
- **Full rebuild:** On startup, if `.fava-index.db` is missing or its `schema_version` meta key doesn't match, rebuild from all thought files
- **Rebuild strategy:** Walk all `thoughts/` directories under `$FAVA_TRAIL_DATA_REPO/trails/`, parse each `.md` file, embed content, insert rows. Skip files that fail to parse (log warning).
- Index is local (not committed to repo) — each machine rebuilds from thought files
- Target: <30s rebuild for 500 thoughts (embedding is the bottleneck, ~1ms * 500 = 0.5s; file I/O dominates)
- **Corruption recovery:** Delete `.fava-index.db` and restart — full rebuild is the recovery path

### New Tool: `recall_semantic`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | **yes** | Natural language query |
| `trail_name` | string | **yes** | Scope path |
| `trail_names` | array | no | Additional scopes (supports globs) |
| `limit` | int | no | Max results (default: 10) |
| `namespace` | string | no | Restrict to namespace |

**Search strategy:**
1. Embed the query using the same model
2. Vector similarity search (cosine) in `vec_thoughts`, filtered by trail scope via `thought_meta`
3. Also run FTS5 keyword query
4. Merge results: vector results ranked by cosine similarity, FTS5 results fill gaps
5. Fetch full thought content for top results
6. Attach `applicable_preferences` (same as `recall`)
7. Return results with `score` and `match_type` ("semantic" or "keyword") fields

### Dependencies

- `sqlite-vec` — SQLite extension for vector search (pip install)
- `sentence-transformers` — local embedding model (optional dependency group)

## Done Criteria

- `recall_semantic("codev upgrade rationale")` returns semantically related thoughts
- `thought_relationships` table queryable for graph traversal
- Index rebuilds from thought files in <30s for 500 thoughts
- Falls back to keyword matching gracefully
- Existing `recall` tool unchanged
- Tool count: 17 → 18

## Out of Scope

- Neo4j / full graph database (future TKG Bridge)
- CocoIndex-style CDC pipeline (future)

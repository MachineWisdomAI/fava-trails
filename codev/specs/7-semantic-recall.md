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

-- Schema version tracking (key-value store for index metadata)
CREATE TABLE index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Seeded on creation: INSERT INTO index_meta VALUES ('schema_version', '1');
```

**Schema versioning:** The `index_meta` table stores a `schema_version` key. On startup, if the DB exists, read `schema_version` — if it doesn't match the code's `CURRENT_SCHEMA_VERSION`, delete the DB and rebuild. This avoids migration complexity; full rebuild from thought files is the upgrade path.

### Embedding Model

**Model:** `sentence-transformers/all-MiniLM-L6-v2` via the `sentence-transformers` Python package.

- Runs **locally** — no API calls, no API key needed
- 384-dimension output, ~80MB model download on first use
- Fast: ~1ms per embedding on CPU
- Well-established, Apache-2.0 licensed

The model is loaded once at server startup (lazy — only if semantic index is enabled).

**Async safety:** Despite ~1ms per embedding, `sentence-transformers` model inference is CPU-bound and holds the GIL. All embedding calls MUST use `asyncio.to_thread()` to avoid blocking the event loop:
```python
embedding = await asyncio.to_thread(model.encode, text)
```

**Text extraction:** Only the markdown body (content below the YAML frontmatter `---` delimiter) is embedded. Frontmatter fields (tags, source_type, etc.) are indexed separately in FTS5 and `thought_meta`. This keeps embeddings focused on semantic content rather than metadata noise.

**sqlite-vec loading:** The `sqlite-vec` extension is loaded via `sqlite3.Connection.enable_load_extension(True)` followed by `conn.load_extension("vec0")`. The extension is installed as a Python package (`pip install sqlite-vec`) which places the shared library on the Python path. Use `sqlite_vec.load(conn)` helper if available.

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
1. Embed the query using the same model (via `asyncio.to_thread()`)
2. Vector similarity search (cosine) in `vec_thoughts`, filtered by trail scope via `thought_meta` — return top `2 * limit` candidates
3. Also run FTS5 keyword query — return top `2 * limit` candidates
4. **Merge via Reciprocal Rank Fusion (RRF):** For each result appearing in either list, compute `score = Σ 1/(k + rank_i)` where `k=60` (standard RRF constant) and `rank_i` is the result's position in each list (absent = infinity). Sort by RRF score descending, take top `limit`.
5. Tag each result with `match_type`: `"semantic"` if it appeared in vector results, `"keyword"` if FTS5 only, `"hybrid"` if both
6. Fetch full thought content for top results
7. Attach `applicable_preferences` (same as `recall`)
8. Return results with `score` (RRF score) and `match_type` fields

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

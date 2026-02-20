# Spec 3: Semantic Recall + Trust Gate

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 3
**Prerequisites:** Spec 2 (dogfood + desktop bridge)

---

## Problem Statement

Phase 1/1b recall uses `jj log` + grep with word-level AND matching — sufficient for plumbing but inadequate for semantic search. Two gaps:

1. **No semantic recall** — Agents cannot find conceptually related thoughts unless they share exact keywords. "codev upgrade rationale" won't find a thought about "migrating SPIR protocol from v1.6.1 to v2.0.13"
2. **No automated quality gate** — All thoughts are accepted at face value. There is no mechanism to catch hallucinations, contradictions with existing decisions, or factually incorrect claims before they enter the permanent namespace

## Proposed Solution

### SQLite-vec Hybrid Index

A local SQLite database combining vector embeddings, FTS5 full-text search, and a `thought_relationships` table for graph traversal.

**Components:**
- `src/fava_trail/index/semantic.py` — SQLite-vec hybrid index engine
- `src/fava_trail/index/rebuild.py` — Rebuild index from JJ history (cold start or corruption recovery)
- New MCP tool: `recall_semantic` — vector-based search that falls back to keyword matching

**Schema includes:**
- Vector embeddings table (SQLite-vec) for semantic similarity
- FTS5 table for full-text search (fast keyword matching)
- `thought_relationships` table — stores edges extracted from thought frontmatter `relationships` field. This is the lightweight graph that can be upgraded to Neo4j in a future phase (TKG Bridge path)

**Index lifecycle:**
- Built incrementally on `save_thought` / `update_thought` / `supersede`
- Full rebuild from JJ history in <30s for 500 thoughts
- Index is local (not committed to repo) — each machine rebuilds from thought files

### Trust Gate

An automated critic agent that reviews proposed thoughts before promotion to permanent namespaces.

**Components:**
- `src/fava_trail/daemon/trust_gate.py` — critic agent via direct OpenRouter API calls (`httpx`)

**Trust Gate policies (trail-level config):**

| Policy | Behavior |
|--------|----------|
| `auto` | Always approve (current behavior, default) |
| `critic` | Send thought to OpenRouter model for review before approval |
| `human` | Require explicit human approval |

**Privacy controls:**
- Trail-level policy controls which thoughts go to external models
- Redaction layer strips sensitive metadata before OpenRouter calls
- Provenance tracking: which model reviewed, at what timestamp

### Additional Dependencies

- `sqlite-vec` — SQLite extension for vector search
- `httpx` — Async HTTP client for OpenRouter API calls

## Done Criteria

- `recall_semantic("codev upgrade rationale")` returns relevant thoughts (semantic match, not keyword)
- `thought_relationships` table queryable for graph traversal
- Trust Gate with `critic` policy rejects test hallucination
- Trust Gate with `auto` policy behaves identically to current behavior (backward compatible)
- Index rebuilds from JJ history in <30s for 500 thoughts
- Privacy: redaction layer strips metadata before external model calls
- Existing `recall` tool still works (keyword matching unchanged)

## Out of Scope

- Neo4j / full graph database (future — TKG Bridge path)
- CocoIndex-style CDC pipeline (future, Phase 3 index rebuild is precursor)
- SPIDER protocol enforcement (schema + warnings ready since Phase 1)
- Enterprise federation

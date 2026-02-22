# Spec 6: Recall Enhancements

**Status:** not started
**Epic:** 0003a-recall-pipeline
**Source:** `codev/spir-v2.md` Phase 2 (recall sections)
**Prerequisites:** Spec 3 (Trust Gate)

---

## Problem Statement

Two `recall` features specified in SPIR v2 are not yet implemented:

1. **`applicable_preferences` missing** — `recall` responses should automatically include matching preferences from `preferences/` namespace so agents always see relevant user corrections. Currently the field is absent.
2. **`include_relationships` not functional** — The parameter exists but 1-hop relationship traversal (returning `DEPENDS_ON` and `REVISED_BY` targets) is not implemented.

## Proposed Solution

### `applicable_preferences`

On every `recall` query, automatically scan `preferences/` namespace for thoughts whose metadata scope (project, tags, branch) overlaps with the query scope. Return matching preferences in an `applicable_preferences` field alongside search results.

Agents don't opt in — relevant user corrections are always surfaced. Empty list if no preferences match.

### `include_relationships`

When `include_relationships=True`, for each matching thought, also fetch and return immediate `DEPENDS_ON` and `REVISED_BY` targets by ULID file lookup. Cheap operation (no graph database).

## Done Criteria

- `recall` response always includes `applicable_preferences` field
- Matching preferences surfaced based on scope overlap
- No preferences → empty list (not missing field)
- `include_relationships=True` returns 1-hop related thoughts
- Existing recall behavior unchanged (backward compatible)
- All existing tests pass

## Out of Scope

- Semantic/vector recall (Phase 7)
- Graph database (future TKG Bridge)

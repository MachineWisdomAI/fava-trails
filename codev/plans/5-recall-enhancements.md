# Plan 5: Recall Enhancements

**Status:** not started
**Spec:** `codev/specs/5-recall-enhancements.md`

---

## Phase 5.1: `applicable_preferences` Injection

**Files modified:**
- `src/fava_trail/trail.py` — `recall()` scans `preferences/` namespace for scope-matching thoughts
- `src/fava_trail/tools/recall.py` — include `applicable_preferences` in response

**Key patterns:**
- After main recall query, scan `preferences/client/` and `preferences/firm/`
- Match by scope overlap: if preference has `metadata.project == query.scope.project` or tag intersection
- Return as separate list in response (not mixed into main results)

**Done criteria:**
- `recall` response includes `applicable_preferences` field
- Preferences matched by scope overlap
- No match → empty list

## Phase 5.2: `include_relationships` Traversal

**Files modified:**
- `src/fava_trail/trail.py` — `recall()` follows `relationships` list for 1-hop traversal

**Key patterns:**
- For each matching thought, read `relationships` from frontmatter
- For each `DEPENDS_ON` or `REVISED_BY` edge, fetch target thought by ULID
- Append related thoughts to response (deduplicated)

**Done criteria:**
- `include_relationships=True` returns related thoughts
- File-read based (no graph database)
- Missing targets handled gracefully (skip + log)

## Phase 5.3: Tests

**Test scenarios:**
1. `recall` with matching preference → appears in `applicable_preferences`
2. `recall` with no matching preference → empty list
3. Preference scope overlap: project match, tag match, branch match
4. `include_relationships=True` → related thoughts returned
5. Broken relationship target → skipped gracefully
6. Existing recall tests unchanged

**Done criteria:**
- All new tests pass
- All existing 73+ tests pass

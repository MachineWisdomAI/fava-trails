# Plan 2: Hierarchical Scoping

**Status:** in-progress
**Spec:** `codev/specs/2-hierarchical-scoping.md`

---

## Phase 2.1: `sanitize_scope_path` + `resolve_scope_globs`

**Goal:** Allow `/`-separated trail names. Validate segments individually. Resolve glob patterns.

**Files modified:**
- `src/fava_trail/config.py` — `sanitize_trail_name` → `sanitize_scope_path` (alias kept), new `_SCOPE_SEGMENT_RE`, new `resolve_scope_globs()`

**Key changes:**
- New regex: `_SCOPE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")`
- `sanitize_scope_path`: strip leading/trailing `/`, split on `/`, validate each segment, reject `..` and `\`
- `sanitize_trail_name` kept as alias for backward compat
- `resolve_scope_globs(trails_dir, patterns)`: resolve `*`/`**` globs to actual scope paths, silently drop paths outside `trails/`

**Done criteria:**
- `sanitize_scope_path("mw/eng/fava-trail")` → `"mw/eng/fava-trail"`
- `sanitize_scope_path("../etc")` → ValueError
- `sanitize_scope_path("")` → ValueError
- `sanitize_scope_path("a/b/c/")` → `"a/b/c"` (trailing slash stripped)
- Glob resolution works for `*` and `**`

## Phase 2.2: Server + Tool Definition Updates

**Goal:** `trail_name` required (no default fallback), tool definitions updated, root-level warning, `recall` handler supports `trail_names`, new `change_scope` and `list_scopes` tools.

**Files modified:**
- `src/fava_trail/server.py` — `_get_trail` uses `sanitize_scope_path`, requires `trail_name` (no default), `recall` handler resolves `trail_names`, new tool definitions for `change_scope` and `list_scopes`
- `src/fava_trail/trail.py` — `__init__` uses `sanitize_scope_path`, new `recall_multi()` module-level function
- `src/fava_trail/tools/navigation.py` — `handle_list_trails` → `handle_list_scopes` (recursive, prefix filter, stats)
- `src/fava_trail/tools/recall.py` — `handle_recall` passes `trail_names` to multi-scope recall, adds `source_trail` to results
- `src/fava_trail/tools/thought.py` — add `handle_change_scope()`, update `handle_supersede()` for optional `target_trail_name`
- `src/fava_trail/vcs/jj_backend.py` — `commit_files` gains `allowed_prefixes` parameter

**Key changes:**

### `_get_trail` (server.py)
- `trail_name=None` → error: `"trail_name is required."`
- Root-level warning: if `trail_name` has no `/`, include warning in response

### `recall_multi` (trail.py)
- Module-level async function accepting list of `TrailManager`s
- Deduplicates by `thought_id`, respects limit
- Server-side wiring resolves `trail_names` to `TrailManager`s via glob resolution

### `handle_list_scopes` (navigation.py)
- Recurse via `rglob("thoughts")` to find nested scopes
- Optional `prefix` filter, optional `include_stats` (thought count)
- `list_trails` kept as alias

### `handle_change_scope` (thought.py)
- Wraps `supersede` with `target_trail_name`
- Required: `thought_id`, `content`, `target_trail_name`, `reason`, `trail_name`

### `supersede` cross-scope (trail.py)
- New optional `target_trail_name` kwarg
- When set: find original in source scope, create new in target scope, backlink, commit with both prefixes allowed

### `commit_files` multi-prefix (jj_backend.py)
- New `allowed_prefixes: list[str] | None` parameter
- When provided, check dirty paths against any prefix in list

**Done criteria:**
- Missing `trail_name` → error on all tools (except `list_scopes`)
- Root-level trail → warning (not error)
- `recall` with `trail_names` searches multiple scopes
- `change_scope` creates thought in target scope
- `list_scopes` discovers nested scopes
- `commit_files` permits multi-prefix for cross-scope operations

## Phase 2.3: Tests

**Goal:** Full test coverage for all hierarchical scoping features.

**Files modified:**
- `tests/test_tools.py` — new tests for nested paths, multi-scope recall, globs, root-level warning, cross-scope supersede, change_scope
- `tests/test_config.py` — tests for `sanitize_scope_path` (valid segments, rejection of `..`/`\`, edge cases)
- `tests/conftest.py` — fixtures updated for required `trail_name`, add nested scope fixtures

**Test scenarios:**
1. `sanitize_scope_path` valid paths (single segment, multi-segment, with dots/hyphens)
2. `sanitize_scope_path` invalid paths (`..`, `\`, empty, empty segments)
3. `save_thought(trail_name="mw/eng/fava-trail")` creates nested directory
4. `save_thought(trail_name="scratch")` succeeds with root-level warning
5. `recall(trail_name="X", trail_names=["Y", "Z"])` returns from all scopes
6. `recall(trail_names=["mw/eng/*"])` glob one-level
7. `recall(trail_names=["mw/**"])` glob any-depth
8. `list_scopes()` discovers nested scopes
9. `list_scopes(prefix="mw/eng")` filters correctly
10. `change_scope` creates thought in target scope, marks original
11. `supersede` without `target_trail_name` — same scope (backward compat)
12. Missing `trail_name` → error
13. Path traversal → rejected
14. Glob outside `trails/` → silently dropped

**Done criteria:**
- All new tests pass
- All existing 73 tests pass (no regressions)

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 2.1 | Validation | `sanitize_scope_path`, `resolve_scope_globs` |
| 2.2 | Server + Tools | Required `trail_name`, multi-scope recall, `change_scope`, `list_scopes`, cross-scope supersede |
| 2.3 | Tests | Full coverage for hierarchical scoping |

Each phase ends with a git commit. Phases are sequential.

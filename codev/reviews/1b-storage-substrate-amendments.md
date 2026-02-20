# Review 1b: Storage Substrate Amendments

**Status:** completed
**Spec:** `codev/specs/1b-storage-substrate-amendments.md`
**Plan:** `codev/plans/1b-storage-substrate-amendments.md`
**Reviewer:** GPT-5.1 Codex via `mcp__pal__codereview`
**Continuation ID:** `9c0e9f7d-341d-40bb-ac75-585ca86fab7a`

---

## Summary

Spec 1b delivered two major changes in 5 sequential phases: (A) mutable content architecture with `update_thought` + content-freeze guards, and (B) monorepo storage substrate replacing per-trail JJ repos. Also renamed `wise-fava-trail` to `fava-trail-data`.

16 files changed, +1062/-228 lines, 64 tests pass (up from 30 at start of spec).

## What Was Done

| Phase | Description | Commit | Tests |
|-------|-------------|--------|-------|
| 1b.1 | Monorepo JjBackend rewrite — `repo_root` + `trail_path` separation, path-scoped log/diff, cross-trail pollution assertion, snapshot conflict marker config | `b432744` | 30→34 |
| 1b.2 | Shared backend + TrailManager wiring — server-level init, `_find_thought_path`/`_get_namespace_from_path` utilities, `propose_truth` persist bug fix | `02bbf5f` | 34→49 |
| 1b.3 | Mutable content — `update_thought` tool + content-freeze guards (APPROVED/REJECTED/TOMBSTONED/superseded), frontmatter tamper-proofing | `8afeefa` | 49→57 |
| 1b.4 | Conflict resolution UX — `parse_snapshot_conflict` parser, structured `side_a`/`side_b`/`base` in conflicts response, `update_thought` exception path during conflicts | `fd4edb9` | 57→61 |
| 1b.5 | Push strategy + rename — `try_push` non-throwing wrapper, server-level post-write push hook, `wise-fava-trail` → `fava-trail-data` rename, CLAUDE.md rewrite | `3251d5e` | 61 |

## Spec Compliance

| Criterion | Status |
|-----------|--------|
| `update_thought` updates content in-place (same file, same ULID) | Pass |
| Content-freeze: `update_thought` on approved/rejected/tombstoned → error | Pass |
| Content-freeze: `update_thought` on superseded thought → error | Pass |
| `update_thought` on non-existent thought → error | Pass |
| Frontmatter identity fields preserved after update (tamper-proof) | Pass |
| `save_thought` still always creates new thoughts (regression test) | Pass |
| `conflicts` tool returns structured side_a/side_b/base content | Pass |
| Conflict interception allows `update_thought` for conflicted thought IDs | Pass |
| Unparseable conflict markers → structured error with rollback hint | Pass |
| `propose_truth()` persist bug fixed (status written to disk + committed) | Pass |
| Namespace derivation works for nested dirs (preferences/firm) | Pass |
| `TOMBSTONED` status recognized by all tools | Pass |
| Monorepo: single `.jj/` + `.git/` at repo root | Pass |
| Trails are plain directories (no inner `.git/` or `.jj/`) | Pass |
| Path-scoped `jj log` shows only relevant trail's history | Pass |
| Cross-trail pollution assertion in `commit_files()` | Pass |
| GC runs at monorepo level, not per-trail | Pass |
| `list_trails` detects trails by `thoughts/` directory | Pass |
| Push after write (configurable via `push_strategy`) | Pass |
| All `wise-fava-trail` references updated to `fava-trail-data` | Pass |
| CLAUDE.md reflects monorepo architecture | Pass |

## Code Review Findings (GPT-5.1 Codex)

### CRITICAL: Namespace path traversal (trail.py + config.py)

`save_thought`'s `namespace` parameter was user-controlled but not validated. A malicious MCP client could pass `namespace="../../../../etc/ssh"` to write files outside the `thoughts/` directory.

**Fix applied:** Added `sanitize_namespace()` in `config.py` with a whitelist of valid namespaces (`drafts`, `decisions`, `observations`, `intents`, `preferences`, `preferences/client`, `preferences/firm`). Called in `trail.py:save_thought()` before any file operations. Added 3 tests.

### MEDIUM: _trail_managers keyed by unsanitized name (server.py)

`_trail_managers[name]` used the raw trail name as cache key instead of `sanitize_trail_name(name)`. Could theoretically create duplicate managers for the same on-disk trail.

**Fix applied:** Changed to key by `safe_name` (post-sanitization) throughout `_get_trail()`.

### Evaluated but not fixed: commit_files lacks repo_lock

Expert flagged that `commit_files()` doesn't acquire `repo_lock`. **Intentional design:** The spec explicitly states "per-trail JJ commands do NOT need the repo-wide lock. JJ's operation log handles concurrent writes via automatic 3-way merge." JJ was specifically designed for concurrent commits from multiple workspaces. The per-trail `asyncio.Lock` in `TrailManager` is sufficient for the single-process MCP server. True multi-process concurrent access requires JJ workspaces (Phase 2).

### Evaluated but not fixed: learn_preference not auto-approved

Expert noted `learn_preference` thoughts have `validation_status=DRAFT` despite the "auto-approved" description. **Design trade-off:** "Bypass Trust Gate" means preferences go directly to `preferences/` namespace (skipping `drafts/` + `propose_truth`), not that `validation_status` is set to `APPROVED`. Setting APPROVED would freeze the content, preventing refinement. To be revisited in Phase 2 with Trust Gate.

### LOW: _repo_locks never pruned

Class-level `_repo_locks` dict grows without cleanup. Practically, there's one `repo_root` per server instance. Non-issue for MVP.

### LOW: recall full filesystem scan

`recall()` uses `rglob("*.md")` for search. By design for MVP — Phase 3 adds SQLite-vec index.

## Positive Aspects (per reviewer)

- Conflict reporting carefully translated into structured, human-readable responses — "no raw JJ algebraic notation" requirement is met
- Content-freeze guards correctly block updates for all frozen states
- Comprehensive async test coverage (64 tests) exercises both tooling and backend
- Clean separation of concerns: VCS backend, domain logic, MCP handlers, server orchestration
- Snapshot-style conflict parser handles single, multiple, and unparseable formats gracefully

## Lessons Learned

1. **Always validate user-supplied namespace parameters** — namespace is a path component, and MCP clients are untrusted input. Same lesson as trail name sanitization in Phase 0 review. Whitelist > sanitization for path components.
2. **Key caches by sanitized values** — when caching by user input, always normalize first to prevent duplicate entries for the same underlying resource.
3. **JJ concurrency is a feature, not a bug** — JJ's operation log and automatic merge handles concurrent writes without locking. Resist the urge to add locks "for safety" around per-trail JJ commands — it would serialize all writes and negate JJ's concurrency model.
4. **Snapshot-style conflict markers are parse-friendly** — configuring `ui.conflict-marker-style = "snapshot"` during init_monorepo was critical. The `+++++++`/`-------` format produces directly extractable content, unlike diff-style (`%%%%%%%`) which requires diff application.
5. **propose_truth persist bug was subtle** — in-memory mutation without disk write is easy to miss when tests only check the returned object (not the on-disk state). Integration tests that re-read from disk catch this class of bug.

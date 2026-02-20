# Plan 1b: Storage Substrate Amendments

**Status:** plan-approval
**Spec:** `codev/specs/1b-storage-substrate-amendments.md`

---

## Phase Order Rationale

The monorepo substrate (Part B) must come first because it changes how every JJ command runs (`cwd`, path scoping, shared backend). Mutable content (Part A) builds on top. Naming rename is mechanical and comes last.

---

## Phase 1b.1: Monorepo JjBackend Rewrite + Test Fixture Update

**Goal:** JjBackend operates on a monorepo root, not per-trail repos. All existing tests still pass.

**Files modified:**
- `src/fava_trail/vcs/base.py` — `VcsBackend.__init__` accepts `repo_root: Path` alongside `trail_path: Path`. Add abstract methods: `init_monorepo()`, `push()`, `fetch()`, `add_remote()`. Add `repo_lock: asyncio.Lock` for global ops.
- `src/fava_trail/vcs/jj_backend.py` — Constructor takes `repo_root` + `trail_path`. `_run()` uses `cwd=self.repo_root`. `init_monorepo()` with three-case detection (`.git` only → colocate, both → skip, neither → fresh). `init_trail()` creates dirs only (no `jj git init`). `log()` and `diff()` pass trail-relative path for scoping. `commit_files()` uses `jj diff --name-only` for cross-trail assertion. `gc()` runs at repo root. Add `push()`, `fetch()`, `add_remote()`.
- `tests/conftest.py` — `tmp_fava_home` fixture inits a monorepo at the root (`jj git init --colocate`). `trail_manager` fixture creates trail dirs inside the monorepo. `jj_backend` fixture passes both `repo_root` and `trail_path`.

**Done criteria:**
- `JjBackend(repo_root, trail_path)` constructor works
- `init_monorepo()` three-case detection works (existing .git, both, neither)
- `init_trail()` creates directory structure without creating a new repo
- `jj log` output is scoped to trail path (no cross-trail commits visible)
- `jj diff` output is scoped to trail path
- `commit_files()` aborts if cross-trail dirty files detected
- All existing tests pass with updated fixtures
- New tests: monorepo init, path-scoped log, path-scoped diff, cross-trail pollution assertion

## Phase 1b.2: Shared Backend + TrailManager + Server Wiring

**Goal:** Server creates one shared `JjBackend`, passes it to all `TrailManager`s. Monorepo initialized once at startup.

**Files modified:**
- `src/fava_trail/trail.py` — `TrailManager.__init__` accepts `vcs` parameter (required, not optional). Remove default `JjBackend(self.trail_path)` construction. `init()` creates dirs + commits to monorepo (no repo init). Add `_find_thought_path()` and `_get_namespace_from_path()` utilities. Refactor `get_thought` and `supersede` to use them.
- `src/fava_trail/server.py` — On startup: call `get_repo_root()`, create single `JjBackend(repo_root, trails_dir)`, call `init_monorepo()`. `_get_trail()` passes shared backend to TrailManager. Trail detection: check for `thoughts/` dir instead of `.jj/`. Add startup validation: `trails_dir` is inside `repo_root`.
- `src/fava_trail/config.py` — Add `get_repo_root()` (alias for `get_fava_home()` with explicit monorepo semantics).
- `src/fava_trail/tools/navigation.py` — `handle_list_trails()` detects trails by `thoughts/` dir instead of `.jj/`.

**Done criteria:**
- Server starts with a single shared `JjBackend` instance
- `_get_trail("default")` auto-creates trail dirs in monorepo (not a new repo)
- `list_trails` detects trails by `thoughts/` directory
- Startup validation rejects `FAVA_TRAILS_DIR` pointing outside monorepo
- `_find_thought_path()` works across all namespaces
- `_get_namespace_from_path()` handles nested dirs (`preferences/firm`)
- All existing tests pass

## Phase 1b.3: Mutable Content — `update_thought` + Content Freeze

**Goal:** Agents can edit thought content in-place. Content freezes on approval/supersession.

**Files modified:**
- `src/fava_trail/models.py` — Add `TOMBSTONED` to `ValidationStatus`. Add `stale_draft_days: int = 0` to `TrailConfig`. Add `remote_url`, `push_strategy` to `GlobalConfig`.
- `src/fava_trail/trail.py` — Add `update_thought()` method with: find path, load frontmatter, check freeze guard (status-based + superseded_by), replace body only, write, commit. Fix `propose_truth()` persist bug (write to disk + commit after status change).
- `src/fava_trail/tools/thought.py` — Add `handle_update_thought()`. Update `_serialize_thought` for TOMBSTONED.
- `src/fava_trail/server.py` — Register `update_thought` tool in `TOOL_DEFINITIONS`. Update `supersede` tool description (conceptual replacement, not the only way to update).

**Done criteria:**
- `update_thought` modifies content in-place (same file, same ULID)
- `jj diff` shows actual content changes after `update_thought`
- Content freeze: `update_thought` on approved thought → error
- Content freeze: `update_thought` on superseded thought → error
- `update_thought` on non-existent thought → error
- Frontmatter identity fields preserved (tamper-proof)
- `save_thought` still always creates new thoughts (regression test)
- `propose_truth()` persist bug fixed — status written to disk
- `TOMBSTONED` status recognized
- New tests: update_thought happy path, content-freeze guards, tamper-proofing, propose_truth persist

## Phase 1b.4: Conflict Resolution UX + Exception Path

**Goal:** Conflicts produce structured side_a/side_b/base content. `update_thought` can resolve conflicts.

**Files modified:**
- `src/fava_trail/vcs/base.py` — Extend `VcsConflict` with `side_a`, `side_b`, `base` fields.
- `src/fava_trail/vcs/jj_backend.py` — Add `get_conflict_content()` that parses JJ conflict markers from working copy files. Extract sides from JJ's `<<<<<<<`/`%%%%%%%`/`>>>>>>>`  marker format.
- `src/fava_trail/tools/navigation.py` — `handle_conflicts()` returns structured conflict payloads with content sides.
- `src/fava_trail/server.py` — Conflict interception exception: allow `update_thought` when target `thought_id` matches a conflicted file. All other write ops remain blocked during conflicts.

**Done criteria:**
- `conflicts` tool returns `side_a`, `side_b`, `base` content when available
- `update_thought` is permitted for conflicted thought IDs during conflict state
- Other write ops still blocked during conflicts
- Fallback when conflict markers are unparseable: structured error with rollback hint
- New tests: conflict content extraction, update_thought exception path, unparseable fallback

## Phase 1b.5: Push Strategy + Rename Propagation + CLAUDE.md

**Goal:** Immediate push after writes (configurable). All `wise-fava-trail` references updated to `fava-trail-data`.

**Files modified:**
- `src/fava_trail/vcs/jj_backend.py` — `push()` called after commit in write operations when `push_strategy == "immediate"`. Push failure returns warning, doesn't fail write.
- `src/fava_trail/server.py` — After `save_thought`, `update_thought`, `supersede`, `propose_truth`: call `push()` if strategy is immediate. Include push status in response.
- `src/fava_trail/models.py` — Verify `push_strategy` field exists on `GlobalConfig`.
- `CLAUDE.md` — Update: monorepo architecture, `update_thought` vs `supersede` guidance, `fava-trail-data` naming, remove per-trail `.jj/` references.
- `codev/specs/0-repo-separation.md` — Update `wise-fava-trail` → `fava-trail-data`.
- `codev/plans/0-repo-separation.md` — Same rename.
- `codev/reviews/0-repo-separation.md` — Same rename.

**Done criteria:**
- Push after write works (test with mock remote or `--dry-run`)
- Push failure doesn't fail the write operation
- `push_strategy: "on_sync"` skips automatic push
- All `wise-fava-trail` references in codebase updated to `fava-trail-data`
- CLAUDE.md reflects monorepo architecture and new tool guidance
- All tests pass

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 1b.1 | Monorepo JjBackend | JJ commands run at repo root, path-scoped, cross-trail assertion |
| 1b.2 | Shared backend wiring | Server → shared backend → TrailManagers, startup monorepo init |
| 1b.3 | Mutable content | `update_thought`, content freeze, TOMBSTONED, propose_truth fix |
| 1b.4 | Conflict UX | Structured conflict content, update_thought exception path |
| 1b.5 | Push + rename | Immediate push, `wise-fava-trail` → `fava-trail-data`, CLAUDE.md |

Each phase ends with a git commit. Phases are sequential — each builds on the previous.

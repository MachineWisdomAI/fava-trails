# Plan 1b: Storage Substrate Amendments

**Status:** integrated
**Spec:** `codev/specs/1b-storage-substrate-amendments.md`

---

## Phase Order Rationale

The monorepo substrate (Part B) must come first because it changes how every JJ command runs (`cwd`, path scoping, shared backend). Mutable content (Part A) builds on top. Naming rename is mechanical and comes last.

---

## Phase 1b.1: Monorepo JjBackend Rewrite + Test Fixture Update

**Goal:** JjBackend operates on a monorepo root, not per-trail repos. All existing tests still pass.

**Files modified:**

- `src/fava_trails/vcs/base.py` — `VcsBackend.__init__` accepts `repo_root: Path` alongside `trail_path: Path`. Add abstract methods: `init_monorepo()`, `push()`, `fetch()`, `add_remote()`. Add `repo_lock: asyncio.Lock` for global ops.

- `src/fava_trails/vcs/jj_backend.py` — Constructor takes `repo_root` + `trail_path`. `_run()` uses `cwd=self.repo_root`. `init_monorepo()` with three-case detection (`.git` only → colocate, both → skip, neither → fresh). **During `init_monorepo()`, configure `jj config set --repo ui.conflict-marker-style "snapshot"` — this produces snapshot-style conflict markers (`+++++++`/`-------`) which are directly extractable as content, unlike the default diff-style (`%%%%%%%`) which requires diff application.** `init_trail()` creates dirs only (no `jj git init`). `log()` and `diff()` pass trail-relative path for scoping. `gc()` runs at repo root (both `jj util gc` and `git gc` use `cwd=self.repo_root`, not `trail_path`). Add `push()`, `fetch()`, `add_remote()`.

- `src/fava_trails/vcs/jj_backend.py` `commit_files()` rewrite — **The current implementation ignores its `paths` parameter.** It just does `jj describe` + `jj status` + `jj new`, committing everything dirty in the working copy. This is the critical cross-trail pollution bug identified by all 3 consensus models. Fix: use `jj diff --name-only` to get dirty paths, assert they all fall under the expected trail prefix, then proceed. **Note:** The spec's `commit_files(self, message, paths)` flips the parameter order from the current `commit_files(self, paths, description)`. Update the ABC signature and all call sites in `trail.py` to match.

- `src/fava_trails/trail.py` — **Temporary bridge (replaced in 1b.2):** Update `TrailManager.__init__` default backend construction from `vcs or JjBackend(self.trail_path)` to `vcs or JjBackend(repo_root=get_data_repo_root(), trail_path=self.trail_path)`. This keeps phases independent — 1b.1 can be tested before the shared backend wiring in 1b.2.

- `src/fava_trails/config.py` — Rename `get_fava_home()` to `get_data_repo_root()`. This is the monorepo root path where `.jj/` and `.git/` live. No alias, no backwards compatibility shim — `get_fava_home()` is removed entirely (it was just written in Phase 0, no external consumers). Update all call sites.

- `tests/conftest.py` — Rewrite fixtures for monorepo model:
  ```python
  @pytest.fixture
  def tmp_fava_home(tmp_path):
      home = tmp_path / "fava-trails-data"
      home.mkdir()
      (home / "trails").mkdir()
      os.environ["FAVA_TRAILS_DATA_REPO"] = str(home)
      # Init monorepo at root (not per-trail)
      subprocess.run(["jj", "git", "init", "--colocate"], cwd=str(home), check=True)
      yield home
      os.environ.pop("FAVA_TRAILS_DATA_REPO", None)

  @pytest_asyncio.fixture
  async def jj_backend(tmp_fava_home):
      trail_path = tmp_fava_home / "trails" / "test-jj"
      trail_path.mkdir(parents=True)
      backend = JjBackend(repo_root=tmp_fava_home, trail_path=trail_path)
      await backend.init_trail()  # Creates dirs only, no repo init
      return backend

  @pytest_asyncio.fixture
  async def trail_manager(tmp_fava_home):
      manager = TrailManager("test")  # Uses bridge default from get_data_repo_root()
      await manager.init()
      return manager
  ```

- `tests/test_jj_backend.py` — Update `test_init_trail` to assert `.jj` exists at `jj_backend.repo_root` (not `jj_backend.trail_path`). Add tests for: monorepo init three-case detection, path-scoped log, path-scoped diff, cross-trail pollution assertion, `commit_files` parameter order.

**Done criteria:**
- `JjBackend(repo_root, trail_path)` constructor works
- `init_monorepo()` three-case detection works (existing .git, both, neither)
- `init_monorepo()` sets `ui.conflict-marker-style = "snapshot"` on the repo
- `init_trail()` creates directory structure without creating a new repo
- `jj log` output is scoped to trail path (no cross-trail commits visible)
- `jj diff` output is scoped to trail path
- `commit_files()` uses its `paths` parameter — aborts if cross-trail dirty files detected
- `gc()` runs at `repo_root`, not `trail_path`
- `get_fava_home()` removed, replaced by `get_data_repo_root()`
- All existing tests pass with updated fixtures
- New tests: monorepo init, path-scoped log, path-scoped diff, cross-trail pollution assertion

## Phase 1b.2: Shared Backend + TrailManager + Server Wiring

**Goal:** Server creates one shared `JjBackend`, passes it to all `TrailManager`s. Monorepo initialized once at startup.

**Files modified:**

- `src/fava_trails/trail.py` — `TrailManager.__init__` now requires `vcs` parameter (remove the temporary bridge default from 1b.1). Add `_find_thought_path()` and `_get_namespace_from_path()` utilities. Refactor `get_thought` and `supersede` to use them. **Fix `propose_truth()` persist bug** (`trail.py:296-307`): when a thought already exists outside drafts, write updated `validation_status` to disk and commit via JJ (currently mutates in memory only).

- `src/fava_trails/server.py` — Module-level shared backend pattern:
  ```python
  _shared_backend: Optional[JjBackend] = None

  async def _init_server():
      """Called once at startup."""
      global _shared_backend
      repo_root = get_data_repo_root()
      trails_dir = get_trails_dir()
      _shared_backend = JjBackend(repo_root=repo_root, trail_path=trails_dir)
      await _shared_backend.init_monorepo()

  async def _get_trail(trail_name: str | None = None) -> TrailManager:
      config = load_global_config()
      name = trail_name or config.default_trail
      if name not in _trail_managers:
          manager = TrailManager(name, vcs=_shared_backend)
          if not (manager.trail_path / "thoughts").exists():
              await manager.init()
          _trail_managers[name] = manager
      return _trail_managers[name]
  ```
  Add startup validation: assert `get_trails_dir()` is inside `get_data_repo_root()`.

- `src/fava_trails/config.py` — `get_data_repo_root()` already added in 1b.1. Note: `get_data_repo_root()` and `get_trails_dir()` return different paths — root returns the monorepo root containing `.jj/`, trails_dir returns `{root}/trails/`. The distinction is functional, not just semantic.

- `src/fava_trails/tools/navigation.py` — `handle_list_trails()` detects trails by `(p / "thoughts").exists()` instead of `(p / ".jj").exists()`.

- `src/fava_trails/trail.py` — **GC centralization:** `_maybe_gc()` on TrailManager delegates to the shared backend. The backend tracks its own GC counter/timer and deduplicates — multiple TrailManagers calling `_maybe_gc()` don't trigger redundant GC runs.

**Done criteria:**
- Server starts with a single shared `JjBackend` instance stored at module level
- `_get_trail("default")` auto-creates trail dirs in monorepo (not a new repo)
- `list_trails` detects trails by `thoughts/` directory
- Startup validation rejects `FAVA_TRAILS_DIR` pointing outside monorepo
- `_find_thought_path()` works across all namespaces
- `_get_namespace_from_path()` handles nested dirs (`preferences/firm`)
- `propose_truth()` persist bug fixed — status written to disk and committed
- GC runs once globally via shared backend (not once per TrailManager)
- All existing tests pass

## Phase 1b.3: Mutable Content — `update_thought` + Content Freeze

**Goal:** Agents can edit thought content in-place. Content freezes on approval/supersession.

**Files modified:**

- `src/fava_trails/models.py` — Add `TOMBSTONED` to `ValidationStatus`. Add `stale_draft_days: int = 0` to `TrailConfig`. Add `remote_url`, `push_strategy` to `GlobalConfig`. (These config fields are used in 1b.5 — adding them here keeps model changes in one commit.)

- `src/fava_trails/trail.py` — Add `update_thought()` method: find path via `_find_thought_path()`, load frontmatter from disk, check content-freeze guard (status-based: reject if APPROVED/REJECTED/TOMBSTONED; reject if `superseded_by` is set), replace markdown body only (frontmatter loaded from existing file and re-serialized verbatim = tamper-proofing), write file, commit via JJ.

- `src/fava_trails/tools/thought.py` — Add `handle_update_thought()`. Update `_serialize_thought` for TOMBSTONED status.

- `src/fava_trails/server.py` — Register `update_thought` tool in `TOOL_DEFINITIONS`. **Update `supersede` tool description:** change from "The superseded_by field is the ONLY permitted exception to immutability" to "Replace a thought with a corrected version. Use for conceptual replacement when the conclusion is wrong. For refining wording, use update_thought instead."

**Done criteria:**
- `update_thought` modifies content in-place (same file, same ULID)
- `jj diff` shows actual content changes after `update_thought`
- Content freeze: `update_thought` on approved thought → error
- Content freeze: `update_thought` on superseded thought → error
- `update_thought` on non-existent thought → error
- Frontmatter identity fields preserved after update (tamper-proof)
- `save_thought` still always creates new thoughts (regression test)
- `TOMBSTONED` status recognized by `_serialize_thought`
- `supersede` tool description updated
- New tests: update_thought happy path, content-freeze guards (approved, rejected, tombstoned, superseded), tamper-proofing, save_thought regression

## Phase 1b.4: Conflict Resolution UX + Exception Path

**Goal:** Conflicts produce structured side_a/side_b/base content. `update_thought` can resolve conflicts.

**Files modified:**

- `src/fava_trails/vcs/base.py` — Extend `VcsConflict` with `side_a: Optional[str]`, `side_b: Optional[str]`, `base: Optional[str]` fields.

- `src/fava_trails/vcs/jj_backend.py` — Add `get_conflict_content()` that reads conflicted working copy files and parses JJ **snapshot-style** conflict markers (configured in `init_monorepo()` during Phase 1b.1):
  ```
  <<<<<<< Conflict 1 of 1
  +++++++ Contents of side #1
  content from side A
  ------- Contents of base
  base content
  +++++++ Contents of side #2
  content from side B
  >>>>>>> Conflict 1 of 1
  ```
  Parser must handle: single conflict per file (most common), multiple conflicts per file (frontmatter AND content both conflict), and unparseable format → return `None` for all sides with fallback hint.

- `src/fava_trails/tools/navigation.py` — `handle_conflicts()` returns structured conflict payloads with `side_a`/`side_b`/`base` content when available, `null` when unparseable (with `"resolution_hint": "Manual intervention required. Use rollback to restore pre-conflict state."`).

- `src/fava_trails/server.py` — Conflict interception exception: allow `update_thought` when target `thought_id` matches one of the conflicted files. All other write ops remain blocked during conflicts.

**Done criteria:**
- `conflicts` tool returns `side_a`, `side_b`, `base` content when available
- `update_thought` is permitted for conflicted thought IDs during conflict state
- Other write ops still blocked during conflicts
- Unparseable conflict markers → structured error with rollback hint (not crash)
- New tests: conflict content extraction (snapshot-style markers), update_thought exception path, unparseable fallback

## Phase 1b.5: Push Strategy + Rename Propagation + CLAUDE.md

**Goal:** Immediate push after writes (configurable). All `wise-fava-trails` references updated to `fava-trails-data`.

**Files modified:**

- `src/fava_trails/vcs/jj_backend.py` — Implement `push()` and `try_push()` (non-throwing wrapper). `try_push()` returns `{"status": "pushed"}` on success or `{"status": "warning", "message": "..."}` on failure.

- `src/fava_trails/server.py` — **Push as server-level post-write hook** (matches existing conflict interception pattern which already has a `write_ops` set):
  ```python
  # In handle_call_tool, after handler returns successfully for write ops:
  if name in write_ops and result.get("status") == "ok":
      config = load_global_config()
      if config.push_strategy == "immediate":
          push_result = await _shared_backend.try_push()
          if push_result.get("status") == "warning":
              result["push_warning"] = push_result["message"]
  ```
  Push is NOT inside TrailManager or JjBackend.commit_files() — the server orchestrates it, matching the existing pattern where server.py controls cross-cutting concerns.

- `CLAUDE.md` — Update: monorepo architecture description, `update_thought` vs `supersede` guidance, `fava-trails-data` naming, remove all per-trail `.jj/` references.

- `codev/specs/0-repo-separation.md` — Update `wise-fava-trails` → `fava-trails-data`.
- `codev/plans/0-repo-separation.md` — Same rename.
- `codev/reviews/0-repo-separation.md` — Same rename.

**No data migration.** The data in `wise-fava-trails` is all test data (save/promote/supersede exercises). None needs preservation. Instead:
1. Create `fava-trails-data` repo on GitHub (`MachineWisdomAI/fava-trails-data`)
2. Delete `wise-fava-trails` repo from GitHub
3. `init_monorepo()` handles fresh repo creation — `jj git init --colocate`, add remote
4. Leave local `wise-fava-trails/` directory intact until owner deletes manually

**Done criteria:**
- Push after write works (test with mock remote or `--dry-run`)
- Push failure doesn't fail the write operation — returns warning
- `push_strategy: "on_sync"` skips automatic push
- All `wise-fava-trails` references in codebase updated to `fava-trails-data`
- CLAUDE.md reflects monorepo architecture and new tool guidance
- No migration logic — fresh `fava-trails-data` repo
- All tests pass

---

## Phase Summary

| Phase | Focus | Key Deliverable |
|-------|-------|-----------------|
| 1b.1 | Monorepo JjBackend | JJ commands run at repo root, path-scoped, cross-trail assertion, snapshot-style conflicts configured |
| 1b.2 | Shared backend wiring | Server → shared backend → TrailManagers, startup monorepo init, propose_truth persist fix, GC centralization |
| 1b.3 | Mutable content | `update_thought`, content freeze, TOMBSTONED, supersede description update |
| 1b.4 | Conflict UX | Structured conflict content (snapshot-style), update_thought exception path |
| 1b.5 | Push + rename | Server-level post-write push hook, `wise-fava-trails` → `fava-trails-data`, CLAUDE.md, fresh repo (no migration) |

Each phase ends with a git commit. Phases are sequential — each builds on the previous.

---

## Amendment History

### TICK 1b-001: Recall Query Word-Level Matching (2026-02-20)

**Commits:**
- `aeebd8e` — `[TICK 1b-001] Fix: recall uses word-level AND matching instead of exact substring`
- `2afb276` — `[TICK 1b-001] Test: multi-word query, scope-by-tags, scope-by-branch, tag-only search`

**Implementation:** Single-line change to `trail.py:333`. Split query into words, require all present via `all(word in searchable for word in query_words)`. Added 4 test functions covering the bug and scope filter gaps.

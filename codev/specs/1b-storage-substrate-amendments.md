# Spec 1b: Storage Substrate Amendments

**Status:** integrated
**Author:** Claude (SPIR with 3-way consensus)
**Amends:** Spec 0 (`0-repo-separation.md`), Spec 1 (`1-wise-fava-trail.md`)
**Mutability Consensus:** GPT 5.2 (8/10 FOR), Gemini 3 Pro (9/10 AGAINST), Grok (8/10 NEUTRAL) — Unanimous support
**Mutability Consensus Continuation ID:** `437211f0-0754-4002-b29a-25f42b63bdb9`
**Monorepo Consensus:** GPT 5.2 (8/10 FOR), Gemini 3 Pro (9/10 AGAINST), Grok (8/10 NEUTRAL) — Unanimous support
**Monorepo Consensus Continuation ID:** `d45a264b-60fe-40ba-ada7-a3b664fe390b`
**Research Basis:** `JJ Storage Models for Trail Data.md`, `JJ workspaces can isolate concurrent agents, with caveats.md`

---

## Problem Statement

The current FAVA Trail implementation underutilizes JJ at two levels. Both problems share the same root cause: the original per-trail repo design treats JJ as a glorified filesystem rather than exploiting its VCS primitives. This spec fixes both in a single pass.

### Problem 1: Immutable Files Waste JJ's Diff/Conflict Engine

Every thought is a new file. Files are never modified (except `superseded_by`). To "update" a thought, you create a new file via `supersede`. JJ never sees a file modification — only file additions. Therefore:

1. **`jj diff` only ever shows new files added** — no content diffs, no evolution visible
2. **`jj log` shows a sequence of file creations** — no revision history for individual ideas
3. **Conflicts are impossible** — no two agents ever write to the same file path
4. **The conflict interception layer has nothing to intercept** — JJ's core value proposition (first-class algebraic conflicts) is completely unused

You could replace JJ with `mkdir` + `cp` + a timestamp and get the same behavior. That's a problem when the entire architectural thesis is "JJ's VCS primitives are the right foundation for agent memory."

**Quantifying the waste:** Refining one idea over 5 iterations produces 5 `.md` files (4 superseded + 1 current), 5 file-creation commits, 0 content diffs, 0 conflicts. With mutable content: 1 file, 5 commits showing evolution, real diffs, potential conflicts.

### Problem 2: Per-Trail Repos Have No Remote Storage

Every trail at `wise-fava-trail/trails/{name}/` (being renamed to `fava-trail-data/` — see Naming section) is currently an independent JJ colocated repo with its own `.git/` and `.jj/`. None have a git remote configured. The data is entirely local — 20+ changes in the default trail with zero backup. Machine death = total data loss.

Three approaches were evaluated for trail remote storage:

| Approach | Verdict | Fatal Flaw |
|----------|---------|------------|
| **One GitHub repo per trail** | Rejected | Repo sprawl, no central discovery, no finalization path |
| **Single repo, orphan branches per trail** | Rejected | JJ "Global DAG Pollution" — `jj git fetch` in one trail downloads ALL other trails' objects into its `.git/`. `jj log` then shows every trail's history, breaking isolation. |
| **Monorepo with JJ workspaces** | **Accepted** | None fatal. DAG pollution mitigated by path-filtered `jj log`. This is the pattern the JJ community has converged on for AI agent parallelism. |

### Naming: `wise-fava-trail` -> `fava-trail-data`

As part of this spec, the internal data repo is renamed from `wise-fava-trail` to `fava-trail-data`. This makes the naming pattern generic: `fava-trail` (engine) + `fava-trail-data` (fuel) — any organization can follow this without wondering what "wise" means. The rename propagates to: GitHub repo name, `FAVA_TRAIL_DATA_REPO` env var references, MCP registration JSON, and all spec/doc references.

---

## Part A: Mutable Content Architecture

### Three-Layer Mutability

Split mutability rules into three layers based on the nature of each field:

#### Layer 1: Identity Fields (Immutable)

These fields are the thought's birth certificate. They never change after creation.

| Field | Rationale |
|-------|-----------|
| `thought_id` | Stable identity for references |
| `parent_id` | Lineage must never change |
| `agent_id` | Provenance — who created this |
| `source_type` | Classification is set at birth |
| `created_at` | Timestamp is historical fact |
| `confidence` | Initial assessment is historical fact |
| `schema_version` | Format identifier |

#### Layer 2: Lifecycle Fields (System-Mutable)

These fields are modified only by specific tools during lifecycle transitions. They are NOT freely editable by agents.

| Field | Modified By | Transitions |
|-------|------------|-------------|
| `validation_status` | `propose_truth`, Trust Gate | draft -> proposed -> approved/rejected |
| `superseded_by` | `supersede` | null -> ULID (one-time, irreversible) |
| `relationships` | `supersede`, `update_thought` (future: `add_relationship`) | Append-only — new edges can be added, existing edges never removed or modified. Agents frequently discover dependencies after creation. Initial set is preserved; new `DEPENDS_ON`, `REFERENCES`, etc. edges are appended by specific tools. |

#### Layer 3: Content (Mutable)

The markdown body after the YAML frontmatter is freely editable by agents. JJ tracks every state. Diffs show evolution.

**Guard rail (status-based, not directory-based):** Content mutability is controlled by `validation_status`, not by which directory the file lives in. Content is mutable when `validation_status` is `DRAFT` or `PROPOSED`. Content freezes when:
- `validation_status` is `APPROVED`, `REJECTED`, or `TOMBSTONED`
- `superseded_by` is set (even if status is still DRAFT/PROPOSED)

To update frozen content, you must `supersede` it, which creates the explicit lineage that the audit trail requires.

### What Mutable Content Enables

1. **Meaningful Diffs** — `jj diff` shows actual content evolution (what was added, reworded, removed). This is the "temporal recall" the PRD envisions.
2. **Real Conflicts** — Two agents editing the same thought produces a JJ algebraic conflict. The conflict interception layer now has actual work: surface both versions, ask which to keep or how to merge. This is "cognitive dissonance" made concrete.
3. **Fewer Files, Richer History** — Instead of 5 superseded files for iterative refinement, 1 file with 5 JJ commits showing evolution. Supersession reserved for conceptual replacement.
4. **Diffs as Signal for Knowledge Graph** — Edit frequency and conflict resolution become signal sources for the Phase 3 Temporal Knowledge Graph.

### New `update_thought` Tool (Consensus Decision)

All three models in the mutability consensus recommended a **separate `update_thought` tool** rather than overloading `save_thought`. Rationale: LLMs may hallucinate thought IDs, and a separate tool reduces accidental overwrites. `save_thought` remains "create only."

**`update_thought` parameters:**
- `thought_id` (required): ULID of the thought to update
- `content` (required): New markdown body content
- `trail_name` (optional): Trail to use

**Validation:**
- Thought must exist (fail hard if not found — never create with a supplied ID)
- `validation_status` must be `DRAFT` or `PROPOSED` (status-based check)
- `superseded_by` must be null (content frozen if already superseded)
- Only content (markdown body) is modified — frontmatter is loaded from existing file and re-serialized verbatim (tamper-proofing)
- JJ commit message: `"Update thought {id[:8]} [{source_type}] in {namespace}/"`

**`save_thought` is unchanged** — always creates a new thought with a new ULID. No `thought_id` parameter.

### `_find_thought_path` Utility (Consensus Refinement)

Extract the "find thought file path by ULID" logic into a reusable private method on `TrailManager`. Currently duplicated in `supersede` (`trail.py:169-175`) and `get_thought` (`trail.py:141-146`). The new `update_thought` method also needs it.

```python
def _find_thought_path(self, thought_id: str) -> Optional[Path]:
    """Find the file path for a thought by its ULID. Searches all namespaces."""
    for p in self.trail_path.glob("thoughts/**/*.md"):
        if p.stem == thought_id:
            return p
    return None
```

### `_get_namespace_from_path` Utility (Consensus Bug Fix)

Fix namespace derivation for nested directories. Current code in `supersede` uses `original_path.parent.name` which returns `"firm"` for `thoughts/preferences/firm/`, losing the `preferences/` prefix.

```python
def _get_namespace_from_path(self, path: Path) -> str:
    """Get the namespace relative to thoughts/ directory."""
    thoughts_dir = self.trail_path / "thoughts"
    return str(path.parent.relative_to(thoughts_dir))
```

### `supersede` Role Narrows

`supersede` is no longer "the only way to update a thought." It becomes the tool for **conceptual replacement** — when the conclusion itself is wrong, not when the articulation needs improvement.

- **Edit-in-place** (via `update_thought`): Refining an idea. Same thought, better content.
- **Supersede**: Replacing a conclusion. New thought with `parent_id` pointing to the original. Clean break in thought lineage.

### `ValidationStatus` Expansion

Current: `DRAFT` | `PROPOSED` | `APPROVED` | `REJECTED`

Proposed: `DRAFT` | `PROPOSED` | `APPROVED` | `REJECTED` | `TOMBSTONED`

- `TOMBSTONED`: Content stripped (replaced with tombstone message), metadata preserved. Used when approved thoughts are superseded or when stale drafts are cleaned up. Full content recoverable from JJ/git history. **Not secure deletion** — for privacy-grade redaction, use `git filter-branch` or BFG.

### Stale Draft Handling

Drafts unpromoted for a configurable period are auto-promoted to `proposed` (Trust Gate decides their fate). This preserves good information that might otherwise be lost to procedural lousiness.

- Configurable per trail via `TrailConfig.stale_draft_days` (default: **0 = disabled**). Enable after usage data shows stale drafts are worth auto-promoting. Conservative default prevents noise in the proposed namespace.
- When enabled (e.g., `stale_draft_days: 30`), auto-promotion sets `metadata.extra.promotion_reason = "stale_timer"` — not a separate state, just metadata
- Trust Gate can still reject auto-promoted thoughts

### Content Freeze on Approval

When `propose_truth` promotes a thought to `approved`, or when the Trust Gate approves it, the content becomes immutable from that point forward. Any `update_thought` call targeting a frozen thought returns an error:

```json
{
  "status": "error",
  "message": "Thought {id} is content-frozen (status: approved). Use supersede to create a replacement."
}
```

Content is also frozen when `superseded_by` is set, even if the thought is still in DRAFT/PROPOSED status:

```json
{
  "status": "error",
  "message": "Thought {id} is content-frozen (already superseded by {superseded_by}). Edit the replacement thought instead."
}
```

### Conflict Interception Exception Path (Consensus Refinement)

The current conflict interception layer blocks ALL write operations when any conflict exists (`server.py:304-320`). This prevents the conflict resolution UX from working, since `update_thought` needs to write to resolve a conflict.

**Change:** When conflicts exist, `update_thought` is permitted if and only if the target `thought_id` matches one of the conflicted files. All other write operations remain blocked.

### Conflict Resolution UX

With mutable content, real conflicts will occur. The conflict interception layer provides actionable resolution:

**Current:** Blocks all write operations when any conflict exists. Resolution hint says "use supersede."

**Proposed:** When a conflict is detected on a specific thought file:
1. Extract both sides of the conflict from JJ (parse conflict markers from working copy)
2. Return structured payload with: base content, side A content, side B content
3. Agent resolves by calling `update_thought` with `thought_id` and merged content
4. JJ records the resolution as a normal commit
5. If conflict markers are unparseable, fall back to: `"Manual intervention required. Use rollback to restore pre-conflict state."`

The `conflicts` tool response gains richer structure. **Note:** `file_path` is always monorepo-root-relative (includes `trails/{name}/` prefix). The `thought_id` is extracted from the filename stem (the ULID), not from the directory structure. The `_find_thought_path` utility searches by ULID stem and handles both formats correctly.

```json
{
  "status": "conflict",
  "conflicts": [
    {
      "thought_id": "01JMKR3V...",
      "file_path": "trails/default/thoughts/drafts/01JMKR3V....md",
      "description": "Two agents edited this thought concurrently",
      "side_a": "Content from agent claude-code...",
      "side_b": "Content from agent claude-desktop...",
      "base": "Original content before divergence..."
    }
  ]
}
```

### Bug Fix: `propose_truth()` Persist (Included)

`trail.py:304-307` — when a thought already exists outside drafts, `propose_truth()` mutates `validation_status` in memory but does NOT write to disk or commit via JJ. Fix: write the updated record to disk and commit.

---

## Part B: Monorepo Storage Substrate

### Architecture: Before and After

**Before (current — per-trail repos):**
```
wise-fava-trail/              <- outer git repo (config only)
├── .git/
├── config.yaml
└── trails/
    ├── default/              <- independent JJ colocated repo
    │   ├── .git/             <- its own git history
    │   ├── .jj/              <- its own JJ state
    │   └── thoughts/...
    └── project-x/            <- another independent repo
        ├── .git/
        ├── .jj/
        └── thoughts/...
```

**After (proposed — monorepo):**
```
fava-trail-data/              <- single JJ colocated repo (ALL data)
├── .git/                     <- one git backend for everything
├── .jj/                      <- one JJ state (op log, index)
├── config.yaml
├── CLAUDE.md
├── Makefile
└── trails/
    ├── default/
    │   ├── .fava-trail.yaml  <- trail-specific config
    │   └── thoughts/...      <- trail content (just directories, no inner .git/.jj)
    └── project-x/
        ├── .fava-trail.yaml
        └── thoughts/...
```

**One remote:** `git@github.com:MachineWisdomAI/fava-trail-data.git`
**One push:** `jj git push` syncs everything.
**One DAG:** All trail history in a unified graph, scoped per trail via path-filtered `jj log`.

### Concurrent Agent Access via JJ Workspaces

When two agents need to work simultaneously on different trails:

```bash
# Primary working copy (already exists)
fava-trail-data/              <- default workspace

# Agent A gets a workspace scoped to default trail
jj workspace add ../agent-a-ws --name agent-a
cd ../agent-a-ws
jj sparse set --clear --add trails/default/

# Agent B gets a workspace scoped to project-x
jj workspace add ../agent-b-ws --name agent-b
cd ../agent-b-ws
jj sparse set --clear --add trails/project-x/
```

Each workspace gets its own filesystem directory with an independent `@` commit. JJ's concurrency model is lock-free — concurrent commits from different workspaces succeed without contention (operations merge automatically via 3-way merge of the operation log).

Sparse patterns restrict file materialization: Agent A's workspace literally only contains `trails/default/` files on disk.

### Why This Works with JJ

1. **Lock-free concurrency:** JJ uses content-addressed storage + automatic operation merging instead of file locks. Two agents running `jj commit` simultaneously both succeed. Non-conflicting changes (different trail directories) merge cleanly with zero intervention.

2. **Sparse checkout is native:** `jj sparse set --clear --add trails/{name}/` restricts what an agent sees on disk. Not access control (agent could change patterns), but sufficient for FAVA Trail where the MCP server controls all JJ operations.

3. **Path-filtered history:** `jj log trails/default/` shows only commits touching that trail's files. This is how the semantic translation layer must invoke `jj log` — always with the trail path as argument.

4. **Single remote = instant backup:** `jj git push` after any write operation. No per-trail remote management.

### JjBackend Rewrite

The `JjBackend` is rewritten once with all changes — monorepo root as cwd, trail path as file prefix, path-scoped log, and mutable content support.

**Constructor change:** The `JjBackend` constructor must accept both `repo_root` (where `.jj/` lives — the monorepo root) and `trail_path` (where thoughts live — the trail subdirectory). These are different paths in the monorepo model:
- `repo_root`: `/path/to/fava-trail-data/` (where `.jj/` lives, where JJ commands run)
- `trail_path`: `/path/to/fava-trail-data/trails/default/` (where thoughts live)

**Modified: `_run()` method** — Currently runs JJ commands with `cwd=self.trail_path` (the per-trail directory). In the monorepo, JJ commands must run with `cwd=self.repo_root` (where `.jj/` lives).

**New: `init_monorepo()`** — Called once on first server start. Three-case detection:
- If `.git/` exists but `.jj/` doesn't → `jj git init --colocate` (wraps existing git history — the current `fava-trail-data` repo already has git history from config.yaml commits, CLAUDE.md, etc. This history is intentionally preserved in the monorepo DAG as initial history.)
- If both `.git/` and `.jj/` exist → already initialized, skip
- If neither exists → `jj git init --colocate` (fresh repo)

**Modified: `init_trail()`** — Creates the `trails/{name}/` directory structure and namespace subdirectories. Does NOT create a new JJ/Git repo. Commits the new directory structure as a JJ change in the existing monorepo.

**Modified: `log()`** — Must pass trail path as argument: `jj log trails/{name}/` to scope DAG output to this trail only. This is the DAG pollution mitigation. A bare `jj log` without a path filter should be guarded against (either add the current trail's path automatically or raise an error).

**Modified: `diff()`** — Same path scoping.

**Modified: `commit_files()`** — File paths passed to JJ must be relative to the monorepo root, not the trail directory. **Critical consensus fix (all 3 models):** The current implementation ignores its `paths` parameter — it just does `jj describe` + `jj status` + `jj new`, committing whatever is dirty in the working copy. In the monorepo, this accidentally commits cross-trail changes. Fix: add a pre-commit assertion that only files under the intended trail's path changed. If other paths are dirty, abort with an error. This is the correct MVP fix before workspaces.

```python
async def commit_files(self, message: str, paths: list[str]) -> str:
    """Commit specific files, asserting no cross-trail pollution."""
    # Get list of changed files using jj diff --name-only (one path per line,
    # no decoration — most parseable format, analogous to git diff --name-only)
    name_only_output = await self._run("diff", "--name-only")
    dirty_paths = [line.strip() for line in name_only_output.splitlines() if line.strip()]
    # Assert only intended paths are dirty
    expected_prefix = str(self.trail_path.relative_to(self.repo_root))
    unexpected = [p for p in dirty_paths if not p.startswith(expected_prefix)]
    if unexpected:
        raise RuntimeError(
            f"Cross-trail pollution detected. Expected only changes under "
            f"{expected_prefix}/, but found: {unexpected}"
        )
    await self._run("describe", "-m", message)
    result = await self._run("new")
    return result
```

**New: `push()`** — `jj git push` (pushes to configured remote). Wraps `--allow-new` on first push. **Push timing (consensus resolution):** Push after every write operation (`save_thought`, `update_thought`, `supersede`, `propose_truth`) by default — the whole point of the monorepo is remote backup, so immediate push is the safest default. Configurable via `push_strategy` in config.yaml: `"immediate"` (default) or `"on_sync"` (manual control). Push failures do NOT fail the write — local durability still holds, but a warning is returned so the operator knows backup is behind.

**New: `fetch()`** — `jj git fetch` (pulls from remote).

**New: `add_remote(name, url)`** — `jj git remote add`.

**Modified: `gc()`** — Runs once at the monorepo level, not per trail.

### VcsBackend ABC Changes

The `VcsBackend` base class gains a `repo_root` property alongside the existing `trail_path`. New abstract methods: `init_monorepo()`, `push()`, `fetch()`, `add_remote()`.

### TrailManager Changes

**Shared VcsBackend instance:** In the monorepo model, all trails share one `.jj/` repo. The server should create one `JjBackend` instance for the monorepo and share it across all TrailManagers. Each TrailManager knows its trail path prefix for file operations.

**`TrailManager.__init__()`** — The VCS backend is passed in (shared), not created per-trail. `trail_path` is still used for file operations (reading/writing thought `.md` files).

**`TrailManager.init()`** — Creates `trails/{name}/thoughts/{namespace}/` directories with `.gitkeep` files. Commits as a change in the monorepo. Does NOT create a new repo.

**Two-tier locking (consensus refinement):**
- **Per-trail asyncio.Lock** — Still needed. Concurrent writes to the same trail need serialization at the application level.
- **Repo-wide asyncio.Lock** — New. Required for global operations (push, fetch, rebase, gc) that affect the entire monorepo. Held by the shared `JjBackend` instance. Per-trail operations acquire only the trail lock; global operations acquire the repo-wide lock.

**Important: per-trail JJ commands (commit, describe, new) do NOT need the repo-wide lock.** JJ's operation log handles concurrent writes from multiple processes via automatic 3-way merge of divergent operation heads. Two `jj describe` + `jj new` sequences in the same repo from different processes will both succeed, and the next JJ command will auto-merge the operation heads. The repo-wide lock is ONLY for operations that must see a consistent global state (push, fetch, rebase, gc). This is validated by the JJ Workspaces research — see "Concurrent commits succeed without locking." The implementing agent should NOT add a global lock around per-trail JJ commands "for safety" — it would serialize all writes and negate JJ's concurrency model.

**Startup validation (consensus refinement):** On server startup, validate that `trails_dir` is inside the monorepo root (the JJ colocated repo). Prevents misconfiguration where `FAVA_TRAILS_DIR` points outside the repo.

### `list_trails` Change

Currently checks for `(p / ".jj").exists()` to detect trails (`navigation.py:28`). In the monorepo, trails are just directories — check for `(p / "thoughts").exists()` or `(p / ".fava-trail.yaml").exists()` instead.

### `_get_trail()` in server.py

Currently auto-initializes by checking `(manager.trail_path / ".jj").exists()` (`server.py:46`). In the monorepo, the check becomes: does `trails/{name}/` directory exist? The monorepo itself must be initialized separately (once, at server start).

### config.py Changes

**Rename `get_fava_home()` to `get_data_repo_root()`** — Returns the monorepo root path (`FAVA_TRAIL_DATA_REPO`). This is the directory containing `.jj/` and `.git/`. `get_fava_home()` is removed entirely — no alias, no backwards compatibility shim (it was just written in Phase 0, no external consumers).

**`get_trails_dir()`** — Still returns `{data_repo_root}/trails/`. No change in semantics.

The existing `FAVA_TRAIL_DATA_REPO` env var already points to the right place. No new env vars needed.

### models.py Changes

**`TrailConfig`** — Add `remote_url: Optional[str] = None` for per-trail remote override (future). Not used in MVP — monorepo has one remote.

**`GlobalConfig`** — Add `remote_url: str = ""` for the monorepo's git remote URL. Add `push_strategy: str = "immediate"` (`"immediate"` | `"on_sync"`).

### Remote Sync Simplification

The `sync` tool implementation simplifies dramatically in the monorepo:

```python
async def handle_sync(self, trail_name: str) -> dict:
    """Sync with remote. In monorepo, this syncs ALL trails at once."""
    async with self._lock:
        await self.vcs.fetch()
        result = await self.vcs.rebase_on_remote()
        if result.has_conflicts:
            await self.vcs.op_restore(result.pre_rebase_op_id)
            return {"status": "conflict", "details": result.conflict_details}
        await self.vcs.push()
        return {"status": "synced"}
```

No per-trail bookmark management. No orphan branch creation. No refspec hacking. One fetch, one rebase, one push.

Pull Daemon also simplifies: one background loop for the entire monorepo, not one per trail.

### Fresh Repo (No Migration)

The data in `wise-fava-trail` is all test data (save/promote/supersede exercises during Phase 1 development). None needs preservation. Instead of a complex migration:

1. Create `fava-trail-data` repo on GitHub (`MachineWisdomAI/fava-trail-data`)
2. Delete `wise-fava-trail` repo from GitHub
3. `init_monorepo()` handles fresh repo creation: `jj git init --colocate` at `fava-trail-data/` root, add remote `git@github.com:MachineWisdomAI/fava-trail-data.git`
4. Leave local `wise-fava-trail/` directory intact until owner deletes manually

**Note:** If future users of FAVA Trail need to migrate real data from per-trail repos to a monorepo, the migration path would be: export `jj log --patch` as text, copy thought files, delete inner VCS dirs, init monorepo, restore files, commit. But this is not needed for the current deployment.

### Trail Lifecycle in the Monorepo

**Creating a trail:**
```
trails/new-project/
├── .fava-trail.yaml
└── thoughts/
    ├── decisions/.gitkeep
    ├── observations/.gitkeep
    ├── intents/.gitkeep
    ├── preferences/client/.gitkeep
    ├── preferences/firm/.gitkeep
    └── drafts/.gitkeep
```

**Archiving/finalizing a trail:**
1. Tag the final state: `jj bookmark set archive/trail-name -r @`
2. Optionally move trail directory to `trails/_archived/trail-name/`
3. `jj sparse set` on any workspace to exclude archived trails from materialization

**Discovery:**
- `ls trails/` — list all trails (they're just directories)
- `jj log trails/{name}/` — scoped history for one trail
- `jj log` (unscoped) — full monorepo history (useful for cross-trail queries in Phase 3+)

### Caveats from Research (Important for Implementation)

1. **Secondary workspaces lack `.git/`** — `jj workspace add` creates a directory with `.jj/` but no `.git/`. Git-aware tools won't work in workspace directories. For FAVA Trail this is fine — the MCP server interacts with JJ directly.

2. **Stale working copy** — If one workspace modifies another workspace's working-copy commit, the affected workspace becomes stale (requires `jj workspace update-stale`). In FAVA Trail's design where each agent works on different trail directories, this should be rare. The MCP server should handle this gracefully (detect + auto-resolve).

3. **DAG pollution is cosmetic, not functional** — All workspaces see all commits in `jj log` (unfiltered). The semantic translation layer MUST always invoke `jj log` with the trail path argument. A bare `jj log` would dump the entire monorepo history into the agent's context window. Add a guard: if `jj log` is called without a path filter, the translation layer should either add the current trail's path automatically or raise an error.

4. **Directory enforcement is convention-only** — JJ has no ACL. An agent could theoretically write to another trail's directory. The MCP server already controls all file operations, so enforce at the application layer: `save_thought(trail_name="default")` only writes to `trails/default/thoughts/`.

5. **Operation log is still local** — `jj op log` doesn't sync to remote. The per-agent audit trail of undos, restores, and workspace operations is local to the machine. Thought provenance (in frontmatter) does sync.

---

## What Doesn't Change

- **Thought file format** — Unchanged. Frontmatter + markdown body.
- **Namespace directories** — Unchanged. `thoughts/{namespace}/{id}.md`.
- **MCP tool interfaces** — Unchanged. All tools still accept `trail_name`, return structured JSON.
- **Recall, save_thought, get_thought** — File operations are the same. Only the JJ invocation paths change.
- **Engine vs. Fuel split** — Unchanged. `fava-trail` (OSS engine) is a separate repo. `fava-trail-data` (internal fuel, renamed from `wise-fava-trail`) is the monorepo.
- **Two-tier locking** — Per-trail asyncio.Lock still needed. Repo-wide lock added for global ops. See TrailManager Changes for details.
- **Conflict interception layer** — Unchanged in behavior. More useful now: two agents editing the same thought file in different workspaces can produce real JJ conflicts.

---

## Files Affected

| File | Change |
|------|--------|
| `src/fava_trail/vcs/base.py` | Add `repo_root` to `VcsBackend`. Add `init_monorepo()`, `push()`, `fetch()`, `add_remote()` abstract methods. Extend `VcsConflict` with `side_a`, `side_b`, `base` fields. |
| `src/fava_trail/vcs/jj_backend.py` | **Major rewrite.** Constructor takes `repo_root` + `trail_path`. `_run()` uses `repo_root` as cwd. `init_monorepo()` replaces per-trail `init_trail()` repo creation. `log()` and `diff()` get path scoping. `commit_files()` uses monorepo-relative paths. Add `push()`, `fetch()`, `add_remote()`. `gc()` runs at monorepo level. Add `get_conflict_content()`. Mutable content support throughout. |
| `src/fava_trail/trail.py` | Accept shared VCS backend. `init()` creates dirs (no repo init). Add `update_thought()`, `_find_thought_path()`, `_get_namespace_from_path()`. Add content-freeze guard. Fix `propose_truth()` persist bug. Refactor `supersede` and `get_thought` to use new utilities. |
| `src/fava_trail/server.py` | Init monorepo once at startup. Create shared `JjBackend` instance. Register new `update_thought` tool. Update `supersede` tool description. Update conflict interception for `update_thought` exception path. |
| `src/fava_trail/config.py` | Add `get_repo_root()`. No new env vars needed (`FAVA_TRAIL_DATA_REPO` already correct). |
| `src/fava_trail/models.py` | Add `TOMBSTONED` to `ValidationStatus`. Add `stale_draft_days` to `TrailConfig`. Add `remote_url` to `TrailConfig` and `GlobalConfig`. |
| `src/fava_trail/tools/thought.py` | Add `handle_update_thought()`. Update `_serialize_thought` for `TOMBSTONED` status. |
| `src/fava_trail/tools/navigation.py` | `handle_list_trails()` detects trails by `thoughts/` dir (not `.jj/`). Enhance `handle_conflicts()` to return content sides. |
| `tests/conftest.py` | Update fixtures: monorepo init instead of per-trail repo init. |
| `tests/test_tools.py` | Tests for update_thought, content-freeze, conflict resolution flow. |
| `tests/test_jj_backend.py` | Tests for monorepo init, path-scoped log, path-scoped diff, push/fetch. |
| `tests/test_models.py` | Tests for `TOMBSTONED` status, new config fields. |
| `CLAUDE.md` | Update: monorepo architecture description, `update_thought` vs `supersede` guidance, `fava-trail-data` naming. Remove references to per-trail `.jj/` repos. |

### Rename Propagation (`wise-fava-trail` -> `fava-trail-data`)

| Location | Old | New |
|----------|-----|-----|
| GitHub repo | `MachineWisdomAI/wise-fava-trail` | `MachineWisdomAI/fava-trail-data` |
| `~/.claude.json` MCP env | `FAVA_TRAIL_DATA_REPO: .../wise-fava-trail` | `FAVA_TRAIL_DATA_REPO: .../fava-trail-data` |
| `codev/specs/0-repo-separation.md` | References to `wise-fava-trail` | Update to `fava-trail-data` |
| `codev/plans/0-repo-separation.md` | References to `wise-fava-trail` | Update to `fava-trail-data` |
| `codev/reviews/0-repo-separation.md` | References to `wise-fava-trail` | Update to `fava-trail-data` |
| `CLAUDE.md` (fava-trail) | Any `wise-fava-trail` references | Update to `fava-trail-data` |
| `~/.claude/CLAUDE.md` | MCP config examples | Update to `fava-trail-data` |
| `CLAUDE.md` (data repo) | Repo self-references | Update to `fava-trail-data` |

---

## Success Criteria

### Mutability (Part A)

1. `update_thought` updates existing thought content in-place (same file, same ULID)
2. `jj diff` shows actual content changes after `update_thought` (not just new file)
3. `jj log` shows revision history for a single thought file
4. `update_thought` on an `approved` thought returns content-freeze error
5. `update_thought` on a superseded thought returns content-freeze error
6. `update_thought` on a non-existent thought returns error
7. `update_thought` preserves all frontmatter identity fields (tamper-proof)
8. `save_thought` still always creates new thoughts (no regression)
9. `supersede` still works as before (creates new file, backlinks original)
10. `ValidationStatus.TOMBSTONED` is recognized by all tools
11. `conflicts` tool returns structured side_a/side_b/base content when available
12. Conflict interception allows `update_thought` for conflicted thought IDs
13. `propose_truth()` bug fixed — persists `validation_status` change to disk and commits
14. Namespace derivation works for nested dirs (preferences/client, preferences/firm)

### Monorepo (Part B)

15. `fava-trail-data/` is a single JJ colocated repo (one `.jj/`, one `.git/` at root)
16. `trails/{name}/` are plain directories (no `.git/`, no `.jj/` inside)
17. `jj git remote list` shows the GitHub remote
18. `jj git push` succeeds — trail data is backed up to GitHub
19. `jj log trails/default/` shows only default trail history (path scoping works)
20. `jj log trails/project-x/` shows only project-x history
21. All existing MCP tools work unchanged from agent perspective
22. Trail creation (`init`) creates a directory + commits to the monorepo, not a new repo
23. GC runs once at monorepo level, not per-trail

### Naming

24. All references to `wise-fava-trail` updated to `fava-trail-data`
25. `FAVA_TRAIL_DATA_REPO` env var works correctly with renamed repo

### Cross-cutting

26. All existing tests continue to pass (with fixture updates for monorepo init)
27. New tests cover: update_thought, content-freeze guard, tombstoned status, conflict content extraction, namespace derivation, frontmatter tamper-proofing, monorepo init, path-scoped log/diff

## Consensus Summary (Mutability — Complete)

| Model | Stance | Score | Key Contribution |
|-------|--------|-------|-----------------|
| GPT 5.2 | FOR | 8/10 | Status-based mutability check, conflict interception exception path, namespace derivation bug, separate update_thought tool |
| Gemini 3 Pro | AGAINST | 9/10 | "Immutable file was anti-pattern for VCS-backed system." Freeze-on-approval is non-negotiable. Robust conflict parser with fallback. |
| Grok | NEUTRAL | 8/10 | Config flag for mutable states, end-to-end conflict testing, recovery hints in TOMBSTONED metadata |

## Consensus Summary (Monorepo — Complete)

| Model | Stance | Score | Key Contribution |
|-------|--------|-------|-----------------|
| GPT 5.2 | FOR | 8/10 | Shared repo-scoped backend + repo-wide lock. Async debounced push. `commit_files()` path-assertion is critical blocker. Defer workspace automation but design for it. Validate `trails_dir` inside repo root. |
| Gemini 3 Pro | AGAINST | 9/10 | Critical concurrency flaw: single working copy means cross-trail writes entangle. Push immediately after every write. Export old JJ history as text before migration. Workspace-per-agent or global write serialization. |
| Grok | NEUTRAL | 8/10 | Shared backend with monorepo-level locking. Push on explicit sync or interval. Defer workspaces to Phase 2. Migration export safety. Enforce trail isolation at app layer. |

**Consensus Resolutions:**

1. **Shared backend** — Unanimous. One `JjBackend` instance shared across all `TrailManager`s.
2. **`commit_files()` fix** — Unanimous critical blocker. Pre-commit assertion that only intended trail paths are dirty. Abort with error if cross-trail pollution detected.
3. **Push timing** — Resolved toward Gemini: push after every write by default (immediate backup). Configurable to `"on_sync"` for manual control. Push failures don't fail writes — return warning.
4. **Migration safety** — Gemini's recommendation accepted: export `jj log --patch` and `jj op log` as text before deleting per-trail VCS. Low cost, preserves searchable history.
5. **Two-tier locking** — GPT 5.2 + Gemini: per-trail lock for trail ops, repo-wide lock for global ops (push/fetch/gc).
6. **Workspace automation** — Unanimous: defer to Phase 2. Design for it now (shared backend is compatible).
7. **Startup validation** — GPT 5.2: validate `trails_dir` is inside monorepo root.

## Out of Scope

- Workspace lifecycle management automation (Phase 2 — when sync/Pull Daemon ships)
- Cross-trail queries (Phase 3 — when TKG ships)
- Per-trail access control (not needed for 1-person consultancy)
- Data migration from `wise-fava-trail` (test data only — fresh repo instead)
- Stale draft auto-promotion daemon — Phase 2 implementation
- Trust Gate integration — Phase 3
- Semantic search over content diffs — Phase 3

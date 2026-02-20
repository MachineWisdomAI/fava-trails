# SPIR: FAVA Trail — Versioned Audit Trail for AI Agents

## Context

AI agents across Machine Wisdom's toolchain (wise-agents-toolkit, codev, OpenClaw) suffer from three compounding memory failures: **no versioning** (flat markdown files with no rollback), **no shared ground truth** (Claude Code and Desktop operate in isolation), and **no audit trail** (no provenance tracking, no hallucination detection).

FAVA Trail solves this by treating versioned data persistence as a first-class foundation. Reference documents:
- **FAVA Trail PRD v2** (`codev/resources/prd-v2.md`) — Product requirements, substrate-agnostic
- **Architectural Choices** (`codev/resources/architectural-choices.md`) — Technology comparison analysis
- **FAVA Trail spec v1** (`/home/younes/git/MachineWisdomAI/fava_trail.md`) — 377 lines, 8.2/10 consensus confidence

**Ambition:** Real product prototype — dogfood immediately, evolve into something sellable from Machine Wisdom, contributable to codev upstream, and usable as an OpenClaw memory backend.

## Review History

| Reviewer | Score | Key Feedback |
|----------|-------|-------------|
| GPT 5.2 (FOR) | 8/10 | Plan sound, add stable IDs + concurrency mutex + branch lifecycle |
| Gemini 3 Pro (AGAINST) | 8/10 | Kill log.jsonl, start with JJ, harden Pull Daemon |
| Claude Opus 4.6 (adversarial) | — | SPIR delivers ~40% of PRD. 5 must-do schema changes bring it to ~55-60%. JJ is correct substrate choice. |
| Claude Opus 4.6 (v2 feedback) | — | 8 concrete recommendations: atomic supersede, namespace routing, conflict interception, semantic jj log translation, GC automation, chaos testing, TKG bridge docs. |
| **Repo Separation Consensus** | 8.3/10 avg | GPT-5.1 Codex (8/10 FOR), Gemini 3 Pro (9/10), O3 (8/10 NEUTRAL): Unanimous support for Engine vs. Fuel split. |
| **Spec 1b Mutability Consensus** | 8.3/10 avg | GPT 5.2 (8/10 FOR), Gemini 3 Pro (9/10 AGAINST), Grok (8/10 NEUTRAL): Unanimous support for three-layer mutability + `update_thought` tool. |
| **Spec 1b Monorepo Consensus** | 8.3/10 avg | GPT 5.2 (8/10 FOR), Gemini 3 Pro (9/10 AGAINST), Grok (8/10 NEUTRAL): Unanimous support for monorepo + shared backend + push-after-write. |

**User decision:** JJ-first. Trail repos remain git repos (JJ colocated mode).

Consensus Continuation ID: `16cf1bcf-6d6c-41fc-98ee-3da62dd1a011`

## Repos (Engine vs. Fuel Split)

### Repo 1: `fava-trail` (Engine — Open Source)

**`/home/younes/git/MachineWisdomAI/fava-trail/`** — pip-installable Python MCP server

- GitHub: `MachineWisdomAI/fava-trail` (public)
- License: Apache-2.0
- Distribution: PyPI (`pip install fava-trail`)
- Contains: All Python source, tests, SPIR docs (`codev/`), scripts, PRD, architectural analysis

### Repo 2: `fava-trail-data` (Fuel — Internal)

**`/home/younes/git/MachineWisdomAI/fava-trail-data/`** — MachineWisdomAI's versioned agentic memory

- GitHub: `MachineWisdomAI/fava-trail-data` (private)
- **Single JJ colocated monorepo** (one `.jj/`, one `.git/` at root)
- One remote: `git@github.com:MachineWisdomAI/fava-trail-data.git`
- Contains: `config.yaml`, `Makefile`, `CLAUDE.md`, `trails/` (plain directories — no inner VCS repos)
- NOT a Python package — pure data/config
- Eventually FAVA Trail itself will store SPIR docs (self-hosting)

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Matches pal-mcp-server pattern (mcp SDK, Pydantic, uv, stdio). |
| VCS engine | **JJ-first** (colocated mode — git repos underneath) | First-class conflicts, Change-IDs, op log, crash-proof snapshots. Pre-built binaries available. |
| Repo location | Standalone under MachineWisdomAI org | Independent release cycle. Separate MCP server in `~/.claude.json`. |
| Trust Gate | Direct OpenRouter API (not Pal MCP) | Background reviewer, not interactive. `httpx` to OpenRouter. |
| Semantic index | Phase 3 (SQLite-vec) | MVP uses `jj log` + grep. Phase 3 adds SQLite-vec + relationship table. |
| Storage | **Monorepo** — `fava-trail-data/trails/{trail-name}/` | Single JJ colocated repo at root. Trails are plain directories (no inner `.jj/`/`.git/`). Path-filtered `jj log` for per-trail history. Single `jj git push` backs up everything. |
| Monorepo model | Single JJ colocated repo for all trails | Eliminates per-trail repo sprawl, avoids orphan-branch DAG pollution. Path-filtered `jj log` preserves isolation. |
| Conflict marker style | JJ snapshot-style (`+++++++`/`-------`) | Direct content extraction for conflict resolution UX. Configured via `jj config set --repo ui.conflict-marker-style "snapshot"` in `init_monorepo()`. |
| Thought IDs | ULID in frontmatter | Stable across rebases, independent of commit/Change-IDs. |
| Thought mutability | **Three-layer mutability** | Layer 1 (identity fields): immutable. Layer 2 (lifecycle: `validation_status`, `superseded_by`, `relationships`): system-mutable by specific tools only. Layer 3 (markdown content): mutable via `update_thought` when DRAFT/PROPOSED; freezes on APPROVED/REJECTED/TOMBSTONED/superseded. |
| Audit trail | `jj op log` + `git log` (no shared log.jsonl) | VCS history IS the audit trail. |
| Namespace separation | **Directory-based** — `thoughts/{namespace}/` | Filesystem-level isolation prevents cross-contamination (PRD requirement). |
| Supersession | Two update paths: `update_thought` for refinement, `supersede` for replacement | `update_thought` edits in-place (same file, same ULID, JJ tracks diffs). `supersede` creates new thought + backlink for conceptual replacement. `recall` hides superseded by default. |
| Relationship tracking | `relationships` list in frontmatter | Structural prerequisite for future knowledge graph (PRD requirement). Append-only — new edges added, never removed. |
| VCS output handling | **Semantic translation layer** — never raw VCS stdout | All `jj log`/`jj op log` output parsed and distilled into token-optimized summaries before returning to agent. |
| Namespace routing | `save_thought` defaults to `drafts/`; `propose_truth` promotes | Agents don't manage directories. `source_type` determines target namespace on promotion. |
| Conflict handling | **Conflict interception layer** in MCP server | Raw JJ algebraic conflicts never exposed to agents. Conflicts trigger structured resolution mode. `update_thought` permitted on conflicted files for resolution. |
| Garbage collection | Automated `jj util gc` + `git gc` at intervals | Runs once at monorepo level (not per-trail). Prevents object bloat from JJ's "working copy as commit" paradigm. |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ fava-trail (OSS, PyPI)                                      │
│                                                             │
│ Claude Code CLI ──┐                  ┌── codev adapter (P4) │
│                   │   MCP (stdio)    │                      │
│ Claude Desktop ───┼──> MCP Server ───┼── OpenClaw (P5)     │
│                   │                  │                      │
│ Any MCP client ───┘     │            └── toolkit (P2)      │
│                         │                                   │
│                   TrailManager (per-trail mutex)             │
│                   (shared JjBackend instance)                │
│                         │                                   │
│                   VcsBackend ABC                            │
│                         │                                   │
│                   JjBackend (repo_root + trail_path)        │
│                   (repo-wide lock for global ops)           │
│                                                             │
└─────────────────────┼───────────────────────────────────────┘
                      │
                FAVA_TRAIL_DATA_REPO env var
                      │
┌─────────────────────▼───────────────────────────────────────┐
│ fava-trail-data (internal, MachineWisdomAI)                 │
│ Single JJ colocated monorepo                                │
│                                                             │
│ ├── .git/              (one git backend for everything)     │
│ ├── .jj/               (one JJ state — op log, index)      │
│ ├── config.yaml        (global config)                      │
│ ├── Makefile           (bootstrap + ops)                    │
│ ├── CLAUDE.md          (company-specific agent instructions)│
│ └── trails/                                                 │
│     ├── default/       (plain directory — no inner VCS)     │
│     │   ├── .fava-trail.yaml                                │
│     │   └── thoughts/...                                    │
│     └── project-x/     (plain directory)                    │
│         ├── .fava-trail.yaml                                │
│         └── thoughts/...                                    │
└─────────────────────────────────────────────────────────────┘
```

## Thought File Format

File: `thoughts/{namespace}/{thought-id}.md`

```yaml
---
schema_version: 1
thought_id: "01JMKR3V8GQZX4N7P2WDCB5HYT"     # ULID, stable across rebases
parent_id: null                                   # ULID of parent thought (null for root)
superseded_by: null                               # ULID of thought that replaces this one
agent_id: "claude-code-main"
confidence: 0.9
source_type: "decision"       # observation | inference | user_input | tool_output | decision
validation_status: "draft"    # draft | proposed | approved | rejected | tombstoned
intent_ref: null              # ULID of intent thought this decision implements (SPIDER prep)
created_at: "2026-02-19T12:00:00Z"
relationships:
  - type: "DEPENDS_ON"
    target_id: "01JMKQ8W7FNRY3K6P1VDBA4GXS"
  - type: "REVISED_BY"
    target_id: "01JMKS7Y2HPQW5M8R3XECF6JZV"
metadata:
  project: "wise-agents-toolkit"
  branch: "main"
  tags: ["architecture", "codev-upgrade"]
---
Decided to upgrade codev from v1.6.1 to v2.0.13 because SPIR protocol
replaces SPIDER, ASPIR enables autonomous operation, and TICK is now
an amendment workflow.
```

**Mutability model (three layers):**

**Layer 1 — Identity (immutable):** `thought_id`, `parent_id`, `agent_id`, `source_type`, `created_at`, `confidence`, `schema_version`. Never change after creation.

**Layer 2 — Lifecycle (system-mutable):** `validation_status` (modified by `propose_truth`, Trust Gate: draft → proposed → approved/rejected), `superseded_by` (modified by `supersede`, one-time, irreversible), `relationships` (append-only — new edges added by specific tools, existing edges never removed).

**Layer 3 — Content (mutable when draft/proposed):** The markdown body is editable via `update_thought` when `validation_status` is DRAFT or PROPOSED. Content freezes when APPROVED, REJECTED, TOMBSTONED, or when `superseded_by` is set.

**Two update paths:**
- **`update_thought`** — refine wording in-place (same file, same ULID). JJ tracks every edit as a content diff. Use when the idea is right but the articulation needs work.
- **`supersede`** — conceptual replacement (new thought with `parent_id` pointing to original, atomically sets `superseded_by` on original). Clean break in lineage. Use when the conclusion itself is wrong.

`recall` hides superseded thoughts by default (`include_superseded=False`).

## Trail Repo Layout

```
fava-trail-data/                       # Single JJ colocated monorepo
├── .git/                              # One git backend for everything
├── .jj/                               # One JJ state (op log, index)
├── config.yaml                        # Global config (default trail, push strategy)
├── CLAUDE.md                          # Company-specific agent instructions
├── Makefile                           # Bootstrap + ops
└── trails/
    └── {trail-name}/                  # Plain directory (no inner .git/.jj)
        ├── .fava-trail.yaml           # Trail-specific config
        └── thoughts/
            ├── decisions/             # Approved architectural decisions
            ├── observations/          # Runtime observations and tool outputs
            ├── intents/               # Architectural intent documents (SPIDER prep)
            ├── preferences/
            │   ├── client/            # Client-specific stylistic preferences
            │   └── firm/              # Firm architectural standards
            └── drafts/                # Working thoughts not yet classified
```

No `provenance/log.jsonl` — `jj op log` provides complete audit trail.

## MCP Tools (14 total, phased delivery)

All tools accept `trail_name` parameter (defaults to config default trail).
All tools return structured JSON responses.

### Phase 1 + 1b Tools (14 tools — All Registered)

| Tool | JJ Operation | Purpose |
|------|-------------|---------|
| `start_thought` | `jj new main` | Begin new reasoning branch from current truth |
| `save_thought` | write `.md` to `drafts/` + `jj describe` + `jj new` | Checkpoint mental state (defaults to `drafts/` namespace) |
| `get_thought` | read file by ULID | Deterministic retrieval of a specific thought |
| `update_thought` | modify `.md` in-place + `jj describe` + `jj new` | Edit thought content (same file, same ULID). Content-freeze guard enforced. |
| `propose_truth` | promote namespace + `jj describe` + `jj new` | Promote from `drafts/` to permanent namespace based on `source_type` |
| `recall` | `jj log` + grep, namespace/scope filtering | Search thoughts (hides superseded by default) |
| `forget` | `jj abandon` | Discard current reasoning line |
| `sync` | `jj git fetch && jj rebase -d main` | Sync with shared truth |
| `conflicts` | `jj log -r 'conflicts()'` + interception layer | Surface cognitive dissonance (structured summary, never raw algebraic notation) |
| `rollback` | `jj op restore` | Return trail to historical state |
| `diff` | `jj diff -r` | Compare thought states |
| `list_trails` | enumerate `trails/` subdirectories | Show available trails |
| `learn_preference` | save to `preferences/` namespace | Capture user correction (bypasses Trust Gate) |
| `supersede` | create new thought + backlink original (atomic) | Replace a thought with corrected version |

**Note:** The original SPIR gated tools across Phase 1 (9 tools) and Phase 2 (4 tools). Spec 1b collapsed this boundary — all 14 tools are now registered and functional. Phase 2 focuses on infrastructure (Pull Daemon, Desktop bridge, eval) not tool implementation.

### Phase 3 Tools (+1 tool — Semantic Recall)

| Tool | JJ Operation | Purpose |
|------|-------------|---------|
| `recall_semantic` | Vector query -> thought_id -> fetch | Semantic search via SQLite-vec |

**`save_thought` namespace routing:**
- `namespace` parameter defaults to `drafts/`
- Agents never need to manage directory structures directly
- `propose_truth` acts as promotion engine: moves thought from `drafts/` to permanent namespace based on `source_type`

**`propose_truth` promotion mapping (exhaustive):**

| `source_type` | Target namespace | Notes |
|---------------|-----------------|-------|
| `decision` | `decisions/` | Architectural decisions |
| `observation` | `observations/` | Runtime observations |
| `inference` | `observations/` | Agent-derived conclusions → same as observations |
| `tool_output` | `observations/` | Tool results → same as observations |
| `user_input` | `preferences/` | User corrections and preferences |
| *(unknown)* | **Rejection** | Returns error: `"Unknown source_type '{value}'. Cannot determine promotion target."` |

All source_types defined in `SourceType` enum are covered. Any thought with an unrecognized `source_type` (which cannot happen via Pydantic validation, but is defended against) is rejected with an actionable error message.

**`update_thought` behavior:**
- Only content (markdown body) is modified — frontmatter is loaded from existing file and re-serialized verbatim (tamper-proofing)
- Thought must exist (fail hard if not found — never create with a supplied ID)
- `validation_status` must be `DRAFT` or `PROPOSED` (status-based check)
- `superseded_by` must be null (content frozen if already superseded)
- JJ commit message: `"Update thought {id[:8]} [{source_type}] in {namespace}/"`
- Returns content-freeze error for APPROVED/REJECTED/TOMBSTONED/superseded thoughts

**`supersede` atomicity:**
- Both the new thought creation AND the original's `superseded_by` backlink occur in a **single JJ change**
- If process crashes mid-operation, either both writes exist or neither does
- The `supersede` payload includes `supersedes_thought_id` and a `reason` field explaining *why* the thought changed

**`supersede` test scenarios (mandatory):**

| # | Scenario | Assertion |
|---|----------|-----------|
| 1 | Happy path: supersede a draft thought | New thought exists, original's `superseded_by` set, both in same JJ change |
| 2 | Supersede an already-superseded thought | Error: "Thought X is already superseded by Y" |
| 3 | Supersede with non-existent `thought_id` | Error: "Thought X not found" |
| 4 | `recall` after supersede (default) | Original hidden, replacement returned |
| 5 | `recall` after supersede (`include_superseded=True`) | Both original and replacement returned |
| 6 | Verify atomicity: both files written in single JJ change | `jj log -r @` shows both file modifications in one change (not two separate changes) |
| 7 | `update_thought` on a superseded thought | Error: content-freeze ("already superseded by {id}") |

**`recall` parameters:**
- `query: str` — search terms
- `namespace: Optional[str]` — restrict to subdirectory (decisions, observations, etc.)
- `scope: Optional[dict]` — filter by `metadata.project`, `metadata.tags`, `metadata.branch`
- `include_superseded: bool = False` — show superseded thoughts (for archaeology)
- `include_relationships: bool = False` — 1-hop traversal (return related thoughts)
- `trail_name: Optional[str]` — which trail to search

**`recall` response format:**
```json
{
  "thoughts": [...],
  "applicable_preferences": [...]
}
```
- `applicable_preferences` is **always-on** — no opt-in flag required
- On every `recall`, the server automatically scans `preferences/` namespace for thoughts whose `metadata.scope` (project, tags, branch) overlaps with the query scope
- Matching preferences are returned alongside search results so agents always see relevant user corrections
- If no preferences match, the field is an empty list
- This ensures the HITL feedback loop is passive: agents don't need to know about the preference system to benefit from it

## Implementation Phases

### Phase 0: Repository Separation (COMPLETE — Spec 0)

**Goal:** Split into Engine (OSS) + Fuel (internal) repos.

**Status:** COMPLETE — `fava-trail/` and `fava-trail-data/` are separate repos.

**SPIR Spec:** `codev/specs/0-repo-separation.md`

**VCS per repo:**
- `fava-trail/` (OSS) uses **standard Git** — external contributors fork and PR normally
- `fava-trail-data/` (internal) is a **single JJ colocated monorepo** — one `.jj/` + `.git/` at root, trails are plain directories inside

**Done criteria:** ✅ All met.

---

### Phase 1 + 1b: Core MCP Server + JJ Backend + Storage Substrate (COMPLETE — debugging)

**Goal:** Working MCP server with JJ monorepo that Claude Code can connect to. Schema supports future knowledge graph. Three-layer mutability. Remote backup via push.

**Status:** COMPLETE (debugging) — 14 tools registered. Spec 1b (monorepo + mutable content) implemented. Tests being stabilized.

**SPIR Specs:**
- `codev/specs/1-wise-fava-trail.md` — Original Phase 1
- `codev/specs/1b-storage-substrate-amendments.md` — Monorepo + mutable content amendments

**Files (actual codebase):**
```
fava-trail/
├── pyproject.toml                     # uv project: mcp, pydantic, pyyaml, python-ulid
├── scripts/
│   ├── install-jj.sh                 # Download JJ pre-built binary to ~/.local/bin/
│   └── bootstrap-data-repo.sh        # Bootstrap fava-trail-data with remote
├── src/fava_trail/
│   ├── __init__.py
│   ├── server.py                      # MCP entry point — 14 tools, shared JjBackend, monorepo init at startup
│   ├── config.py                      # get_data_repo_root() (FAVA_TRAIL_DATA_REPO env), get_trails_dir(), namespace/trail sanitization
│   ├── models.py                      # Pydantic: ThoughtRecord, Relationship, TrailConfig, GlobalConfig, ValidationStatus (incl. TOMBSTONED)
│   ├── trail.py                       # TrailManager: VCS + models + per-trail mutex + update_thought + content-freeze guard
│   ├── vcs/
│   │   ├── __init__.py
│   │   ├── base.py                    # VcsBackend ABC (repo_root + trail_path), VcsConflict (side_a/side_b/base), repo_lock for global ops
│   │   └── jj_backend.py             # JjBackend — monorepo commands, init_monorepo(), path-scoped log/diff, push/fetch, cross-trail assertion
│   └── tools/
│       ├── __init__.py
│       ├── thought.py                 # start_thought, save_thought, get_thought, update_thought, forget, supersede, learn_preference
│       ├── recall.py                  # recall (jj log + grep, namespace/scope filtering, supersession hiding, preference injection)
│       └── navigation.py             # diff, list_trails, conflicts, propose_truth, rollback, sync
├── tests/
│   ├── conftest.py                    # Fixtures: monorepo init, tmp trail dirs, jj binary check
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_jj_backend.py
│   └── test_tools.py
├── CLAUDE.md                          # Agent instructions (tool reference, mutability model, monorepo architecture)
└── AGENTS.md
```

**Key patterns:**
- `server.py`: `Server`, `stdio_server`, `@server.list_tools()`, `@server.call_tool()`. Shared `_shared_backend: JjBackend` initialized at startup via `_init_server()`. Per-trail `JjBackend` instances created in `_get_trail()` with same `repo_root`, different `trail_path`. Post-write push hook for immediate backup.
- `VcsBackend` ABC: `__init__(repo_root, trail_path)`, `init_monorepo()`, `init_trail()`, `new_change()`, `describe()`, `log()`, `diff()`, `commit_files()` (with cross-trail assertion), `abandon()`, `op_log()`, `op_restore()`, `conflicts()`, `current_change()`, `push()`, `fetch()`, `add_remote()`, `gc()`, `fetch_and_rebase()`, `git_push()`
- `JjBackend`: subprocess calls to `jj` with `--color=never`. `_run()` uses `cwd=self.repo_root` (monorepo root). Path-scoped `jj log` and `jj diff`. `commit_files()` asserts no cross-trail pollution. `init_monorepo()` detects existing state (`.git/` only → colocate, both exist → skip, neither → fresh init). Sets `ui.conflict-marker-style = "snapshot"` for parseable conflicts.
- `TrailManager`: VcsBackend + trail config + **per-trail asyncio.Lock**. `init()` creates namespace subdirectories with `.gitkeep` files, commits to monorepo. `update_thought()` with status-based content-freeze guard. `_find_thought_path()` and `_get_namespace_from_path()` utilities shared by `get_thought`, `supersede`, and `update_thought`.
- **Conflict interception layer**: Server checks for active conflicts before write operations. If conflicts exist, all writes blocked EXCEPT `update_thought` when `thought_id` matches a conflicted file (enables resolution). Structured `VcsConflict` with `side_a`/`side_b`/`base` for snapshot-style conflict parsing.
- **Two-tier locking**: Per-trail `asyncio.Lock` for trail operations. Repo-wide `asyncio.Lock` (on `VcsBackend.repo_lock`) for global operations (push, fetch, rebase, gc). Per-trail JJ commands do NOT acquire the repo-wide lock — JJ's operation log auto-merges concurrent writes.
- **Startup validation**: `_init_server()` validates `trails_dir` is inside `repo_root`.
- All tool responses: structured JSON dicts (semantic summaries, not VCS output)
- Thought files: mutable `.md` with ULID filenames, YAML frontmatter, namespace subdirectories
- `list_trails`: detects trails by `thoughts/` directory existence (not `.jj/`)
- Validation warning (not error) when `decision` thought has no `intent_ref`

**JJ installation:**
- `scripts/install-jj.sh` downloads pre-built binary for linux-x86_64 to `~/.local/bin/jj`
- Server startup verifies `jj version`; fails with actionable error if missing

**Automated garbage collection:**
- Background routine runs `jj util gc` + `git gc --prune=now` at configurable intervals (default: every 500 JJ snapshots or 1 hour, whichever comes first)
- Runs once at monorepo level (not per-trail)
- Logged but non-blocking — GC failures don't halt operations

**MCP registration for testing:**
```json
{
  "fava-trail": {
    "type": "stdio",
    "command": "uv",
    "args": ["run", "--directory", "/home/younes/git/MachineWisdomAI/fava-trail", "--python", "3.12", "fava-trail-server"],
    "env": { "FAVA_TRAIL_DATA_REPO": "/home/younes/git/MachineWisdomAI/fava-trail-data" }
  }
}
```

**Done criteria:**
- JJ pre-built binary installed, `jj version` succeeds
- `uv run fava-trail-server` starts, responds to `list_tools` (14 tools)
- All 14 tools work e2e: `start_thought`, `save_thought`, `update_thought`, `get_thought`, `propose_truth`, `recall`, `forget`, `sync`, `conflicts`, `rollback`, `diff`, `list_trails`, `learn_preference`, `supersede`
- `save_thought` defaults to `drafts/` namespace; optional `namespace` parameter works
- `update_thought` edits content in-place; `jj diff` shows actual content changes
- Content-freeze guards: `update_thought` on approved/rejected/tombstoned/superseded thought returns error
- `supersede` is atomic — crash mid-operation leaves no orphaned thoughts
- `conflicts` returns structured summary with `side_a`/`side_b`/`base` content, never raw algebraic notation
- Conflict interception allows `update_thought` on conflicted files for resolution
- All tool responses are token-optimized JSON summaries (no raw `jj` stdout)
- Monorepo: single `.jj/` + `.git/` at `fava-trail-data/` root, trails are plain directories
- `jj git push` succeeds — trail data backed up to GitHub
- Path-scoped `jj log trails/{name}/` shows only trail-specific history
- Cross-trail pollution assertion: `commit_files()` aborts if dirty paths outside intended trail
- `recall` hides superseded thoughts by default, shows them with `include_superseded=True`
- `recall` filters by namespace and scope
- `save_thought` on a `decision` with no `intent_ref` logs a warning
- `jj op log` shows complete operation history
- GC automation runs at monorepo level without blocking operations
- `ValidationStatus.TOMBSTONED` recognized by all tools
- `uv run pytest` passes

---

### Phase 2: Dogfood + Desktop Bridge

**Goal:** Replace wise-agents-toolkit flat-file memory; bridge Code and Desktop; close HITL feedback loop.

**Files to create:**
- `src/fava_trail/daemon/pull_daemon.py` — background rebase loop (one daemon for entire monorepo, not per-trail)
- `src/fava_trail/adapters/toolkit.py` — migration helper from flat-file memory
- `scripts/mcp-fava-wrapper.sh` — Claude Desktop wsl.exe wrapper
- `eval/crash_recovery.py` — **SIGKILL chaos test**: kill agent process mid-execution, initialize new session, assert watchdog uses `jj op restore` to recover exact state without data loss
- `eval/recall_relevance.py` — sample-based audit of recall accuracy

**Note:** `propose_truth`, `sync`, `rollback`, and `learn_preference` are already implemented and registered (done in Phase 1/1b). Phase 2's tool work is complete — focus is infrastructure, eval, and Desktop bridge.

**Pull Daemon safety (monorepo — one loop for all trails):**
```python
while running:
    try:
        result = jj_backend.fetch_and_rebase()
        if result.has_conflicts:
            log.warning("Conflict after rebase, restoring pre-rebase state")
            jj_backend.op_restore(result.pre_rebase_op_id)
            notify_agent("conflict", result.conflict_details)
    except Exception as e:
        log.error(f"Pull daemon error: {e}")
    await asyncio.sleep(interval)
```

**`learn_preference` tool:**
- Captures user correction as thought with `source_type: "user_input"`
- Stores in `preferences/client/` or `preferences/firm/` namespace
- Automatically approved (user input bypasses Trust Gate)
- Injected into agent context via `recall`'s always-on `applicable_preferences` field — agents don't opt in, they automatically receive matching preferences on every `recall` query

**`recall` with 1-hop relationship traversal:**
- When `include_relationships=True`, also return immediate `DEPENDS_ON` and `REVISED_BY` targets
- Cheap (file reads by ULID) — no graph database needed

**Migration map (wise-agents-toolkit):**

| Current | FAVA Trail |
|---------|-----------|
| `memory/shared/decisions.md` | `decisions/` namespace, `validation_status: "approved"` |
| `memory/shared/gotchas.md` | `observations/` namespace, `metadata.tags: ["gotcha"]` |
| `memory/branches/<branch>/status.md` | `drafts/` namespace, `metadata.branch: "<n>"` |

**Done criteria:**
- Both Claude Code and Desktop configured with fava-trail MCP
- Both share `fava-trail-data/trails/toolkit/` trail via monorepo
- `propose_truth` merges to main; `rollback` restores via `jj op restore`
- Pull Daemon rebases safely, aborts on conflict (one daemon for monorepo)
- Push after write delivers remote backup — GitHub shows trail data
- `learn_preference` stores corrections in preference namespace
- `recall` with `include_relationships=True` returns 1-hop related thoughts
- `eval/crash_recovery.py` SIGKILL chaos test confirms zero data loss and `jj op restore` recovery
- `propose_truth` promotes thoughts from `drafts/` to correct namespace based on `source_type`
- `conflicts` surfaces structured conflict summaries (never raw algebraic notation)

---

### Phase 3: Semantic Recall + Trust Gate

**Goal:** Vector-based search with relationship table; automated hallucination filtering.

**Files to create:**
- `src/fava_trail/index/semantic.py` — SQLite-vec hybrid index (vector + FTS5 + `thought_relationships` table)
- `src/fava_trail/index/rebuild.py` — rebuild index from JJ history
- `src/fava_trail/tools/recall.py` (extend) — `recall_semantic` tool
- `src/fava_trail/daemon/trust_gate.py` — critic agent via OpenRouter API
- Additional deps: `sqlite-vec`, `httpx`

**SQLite schema includes `thought_relationships` table** — stores edges extracted from thought frontmatter `relationships` field. This is the lightweight graph that can be upgraded to Neo4j in a future phase.

**Trust Gate policies:** `auto` (always approve), `critic` (require model approval), `human` (require explicit approval)

**Trust Gate privacy:** Trail-level policy controls external model access. Redaction layer strips sensitive metadata before OpenRouter calls.

**Done criteria:**
- `recall_semantic("codev upgrade rationale")` returns relevant thoughts
- `thought_relationships` table queryable for graph traversal
- Trust Gate with `critic` policy rejects test hallucination
- Index rebuilds from JJ history in <30s for 500 thoughts

---

### Phase 4: codev Integration

**Goal:** Version codev Porch state changes through FAVA Trail.

**Files to create:**
- `src/fava_trail/adapters/codev.py` — file watcher on `status.yaml`, auto-versions as thoughts

**Done criteria:**
- Porch state changes auto-versioned in trail
- Full state history retrievable via `recall`
- Can rollback project to prior state

---

### Phase 5: OpenClaw Memory Driver

**Goal:** FAVA Trail as alternative memory backend for OpenClaw.

**Files to create:**
- `src/fava_trail/adapters/openclaw.py` — maps `MemorySearchManager` interface to FAVA Trail

**Interface mapping:**
- `search()` → `recall_semantic` + `recall`
- `readFile()` → `get_thought`
- `sync()` → `sync`

**Done criteria:**
- OpenClaw agent with `backend: "fava-trail"` works end-to-end
- Memories versioned and auditable

## PRD Coverage Tracking

| PRD Requirement | Phase | Status |
|----------------|-------|--------|
| VCS-backed audit trail | 1 | ✅ Implemented |
| Immutable thoughts with lineage | 1 + 1b | ✅ Three-layer mutability (Spec 1b) — identity immutable, lifecycle system-mutable, content mutable when draft/proposed |
| Pydantic schema enforcement | 1 | ✅ Implemented |
| Crash-proof persistence (JJ native) | 1 + 1b | ✅ Implemented (monorepo + immediate push to GitHub) |
| Mutable content with audit trail | 1b | ✅ `update_thought` + JJ diffs |
| Content-freeze on approval | 1b | ✅ Status-based guard in `update_thought` |
| Remote backup / disaster recovery | 1b | ✅ Monorepo + `jj git push` to GitHub |
| Conflict resolution UX | 1b | ✅ Structured side_a/side_b/base extraction, `update_thought` exception path |
| Supersession hiding (`hg-evolve` equivalent) | 1 | ✅ `superseded_by` + recall filtering |
| Relationship tracking (graph prerequisite) | 1 | ✅ `relationships` list in frontmatter (append-only) |
| SPIDER protocol prep (`intent_ref`) | 1 | ✅ Field present, validation warnings |
| Namespace separation (Client vs Firm) | 1 | ✅ Directory-based namespaces |
| Scope filtering (sparse checkout lite) | 1 | ✅ `recall` scope parameter |
| Multi-agent sync (Pull Daemon) | 2 | Simplified in monorepo — one fetch/rebase/push for all trails |
| HITL feedback loop | 1b | ✅ `learn_preference` tool implemented and registered |
| 1-hop relationship traversal | 2 | `recall` with include_relationships |
| Evaluation framework | 2 | `eval/` directory |
| Temporal Knowledge Graph (Neo4j + GraphRAG) | Deferred | **TKG Bridge:** Phase 1 `relationships` field + Phase 3 `thought_relationships` SQLite table creates a lightweight graph. Data can be projected directly to Neo4j or Graphiti without migration or LLM re-processing. |
| CocoIndex-style CDC pipeline | Deferred | Phase 3 index rebuild is precursor |
| SPIDER protocol enforcement | Deferred | Schema + warnings ready in Phase 1 |
| Enterprise federation | Deferred | — |

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| JJ binary not available | `scripts/install-jj.sh` pins version. Server verifies on startup. |
| Concurrency (two agents, same trail) | Two-tier locking: per-trail `asyncio.Lock` for trail ops, repo-wide lock for global ops (push/fetch/gc). Per-trail JJ commands do NOT need repo-wide lock — JJ op log auto-merges. |
| Scope creep (5 phases) | Phases 1-2 deliver dogfood value. Strict SPIR discipline. |
| Pull Daemon rebase conflicts | Aborts immediately via `jj op restore`. Surfaces conflict to agent. One daemon for monorepo. |
| MCP server crashes | JJ crash-proof snapshots = no data loss. Watchdog in wrapper. |
| Trust Gate privacy | Trail-level policy. Redaction layer. Provenance tracking. |
| Change proliferation | `jj abandon` merged changes. Periodic `jj git export`. |
| Object bloat (JJ snapshots) | Automated `jj util gc` + `git gc --prune=now` at monorepo level. Non-blocking. |
| Superseded thoughts resurface | `recall` hides by default. `include_superseded` flag for archaeology. |
| Orphaned thoughts (crash during supersede) | Atomic: new thought + backlink in single JJ change. Both exist or neither. |
| Raw VCS output confuses agents | Semantic translation layer. All output token-optimized summaries. |
| Algebraic conflicts confuse agents | Conflict interception layer. Structured resolution mode with side_a/side_b/base, never raw notation. `update_thought` permitted on conflicted files for resolution. |
| Cross-trail pollution (monorepo) | `commit_files()` pre-commit assertion: aborts if dirty paths outside intended trail prefix. |
| DAG pollution (monorepo) | Semantic translation layer always invokes `jj log` with trail path argument. Bare `jj log` without path filter is guarded against. |
| Machine death = total data loss | Immediate push to GitHub after every write (default `push_strategy`). Push failures return warning, don't fail writes — local durability still holds. |
| Content-freeze bypass | Status-based guard in `update_thought` — checks `validation_status` AND `superseded_by`. Frontmatter loaded from disk and re-serialized verbatim (tamper-proofing). |

## Verification

After each phase:
1. `uv run pytest` — all tests pass
2. Manual test: Claude Code session using FAVA Trail tools
3. `jj log trails/{name}/` and `jj op log` confirm proper change graph and audit trail (path-scoped)
4. `jj git push` confirms remote backup
5. After Phase 2: Desktop can access same trail; eval scripts pass

## SPIR Artifacts

- Spec 0: `codev/specs/0-repo-separation.md`
- Plan 0: `codev/plans/0-repo-separation.md`
- Review 0: `codev/reviews/0-repo-separation.md`
- Spec 1: `codev/specs/1-wise-fava-trail.md`
- Plan 1: `codev/plans/1-wise-fava-trail.md`
- Review 1: `codev/reviews/1-wise-fava-trail.md`
- Spec 1b: `codev/specs/1b-storage-substrate-amendments.md`
- Plan 1b: `codev/plans/1b-storage-substrate-amendments.md`
- Review 1b: `codev/reviews/1b-storage-substrate-amendments.md`

## Critical Reference Files

- `codev/resources/prd-v2.md` — FAVA Trail PRD v2 (substrate-agnostic requirements)
- `codev/resources/architectural-choices.md` — Technology comparison analysis
- `codev/specs/0-repo-separation.md` — Spec for Engine vs. Fuel repo split
- `codev/specs/1b-storage-substrate-amendments.md` — Spec for monorepo + mutable content
- `/home/younes/git/MachineWisdomAI/fava_trail.md` — FAVA Trail technical spec v1
- `/home/younes/git/vendor/pal-mcp-server/server.py` — MCP server pattern reference
- `/home/younes/git/vendor/pal-mcp-server/pyproject.toml` — Package structure pattern

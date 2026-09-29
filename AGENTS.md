# FAVA Trails — Agent Reference 🫛👣

Agent-facing reference for FAVA Trails MCP tools. For project setup and configuration, see [README.md](README.md). For the full session protocol with examples, see [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md).

## Repository Workflow

- **Development**: `~/git/MachineWisdomAI/fava-trails/` (this repo)
- **Never modify**: `~/git/vendor/fava-trails/` (read-only, pinned for running MCP servers)
- Feature branches use worktrees: `~/git/MachineWisdomAI/fava-trails-{slug}/`
- Never commit directly to `main` — always use a feature branch and PR
- Pre-flight before starting work:
  ```bash
  git worktree list && git branch -r
  ```
- If another agent or branch is active on this repo, coordinate or use a separate worktree.

## Governed recall

FAVA is the governed institutional record for decisions, observations, validation,
and lineage. It is not the operational working-context store. Default `recall`
and `get_thought` expose current approved records only. Explicit `mode="authoring"`
retrieves only the server-configured agent's draft/proposed records; operator-only
`mode="history"` selects lifecycle statuses and superseded records. Neither a
namespace nor a supplied `agent_id` grants access. See [governed-recall.md](docs/governed-recall.md)
for identity setup, compatibility, approval provenance, and interrupted-write recovery.

The operator configures `FAVA_TRAILS_AGENT_ID` on a dedicated process; caller
`agent_id` must match it. A shared endpoint is one identity boundary. Configure
`FAVA_TRAILS_OPERATOR=1` only on a separate operator-controlled endpoint.

## Scope Discovery

Every tool call requires `trail_name` — a slash-separated scope path (e.g. `mw/eng/fava-trails`). Resolve in priority order:

| Priority | Source | Set where |
|----------|--------|-----------|
| 1 | `FAVA_TRAILS_SCOPE` env var | Process environment (optional) — per-worktree override |
| 2 | `.fava-trails.yaml` `scope` | Project root (committed) — default for all clones |
| 3 | `FAVA_TRAILS_SCOPE_HINT` | MCP server `env` block — broad fallback |

**If `FAVA_TRAILS_SCOPE` is not set** but `.fava-trails.yaml` exists, read its `scope` field and use that value as `trail_name`. Agents must not silently create or edit application-owned `.env` files. Operators may export `FAVA_TRAILS_SCOPE` as an optional process override. If neither source exists, use the scope hint from tool descriptions and prompt the user to create a `.fava-trails.yaml`.

See [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md) for full scope discovery protocol with examples.

## Session Start Protocol

Before starting work, recall existing context:

```
recall(trail_name="<scope>", query="status")
recall(trail_name="<scope>", query="decisions")
recall(trail_name="<scope>", query="gotcha", scope={"tags": ["gotcha"]})
```

Use `trail_names` with globs for broader context: `recall(trail_name="<scope>", query="architecture", trail_names=["mw/eng/*"])`

## Scope Lookup Discipline

Read-only calls do not create missing scopes. If you are unsure where a thought
lives, call `list_scopes(prefix="<likely-prefix>", include_stats=true)` and use
an exact returned `path` as `trail_name`. Do not probe root/umbrella guesses
such as `mw`, `headspace`, or `mw/headspace`.

For a full 26-character ULID, call `get_thought`. If the thought is unique in a
different existing scope, the tool returns it with `source_trail`; use that
`source_trail` for follow-up calls.

## Tools Reference

All tools accept a **required** `trail_name` parameter — the scope path (e.g. `mw/eng/fava-trails`). Scope paths are `/`-separated, with each segment validated as a safe slug. Root-level names (no `/`) trigger a non-blocking warning suggesting a scoped path.

### `start_thought`

Begin a new reasoning branch from current truth. Creates a fresh JJ change.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | no | Brief description of reasoning intent |

### `save_thought`

Save a thought to the trail. Defaults to `drafts/` namespace. Always creates a **new** thought file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | **yes** | The thought content (markdown) |
| `source_type` | enum | no | `observation` \| `inference` \| `user_input` \| `tool_output` \| `decision` (default: `observation`) |
| `confidence` | float | no | 0.0 to 1.0 (default: 0.5) |
| `namespace` | string | no | Override namespace (default: `drafts/`) |
| `agent_id` | string | no | ID of the agent saving this thought |
| `parent_id` | string | no | ULID of parent thought |
| `intent_ref` | string | no | ULID of intent document this implements |
| `relationships` | array | no | List of `{type, target_id}` relationships |
| `metadata` | object | no | `{project, branch, tags}` for filtering |

### `update_thought`

Update thought content in-place (same file, same ULID). Use for refining wording or adding detail. Frontmatter is preserved (tamper-proof). Content is frozen once approved, rejected, tombstoned, or superseded.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | **yes** | ULID of the thought to update |
| `content` | string | **yes** | The new content (replaces existing body) |

**When to use `update_thought` vs `supersede`:**
- `update_thought` — Refine wording, add detail, fix typos. Same ULID, same file. **Use for edits.**
- `supersede` — Replace a thought when the conclusion is wrong. Creates a draft successor; approval later backlinks the original. **Use for corrections.**

### `get_thought`

Retrieve a specific thought by its ULID. Returns full content and metadata.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | **yes** | ULID of the thought to retrieve |

### `recall`

Search thoughts by query, namespace, and scope. Hides superseded thoughts by default. Supports multi-scope search via `trail_names`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | no | Search terms |
| `namespace` | string | no | Restrict to namespace (`decisions`, `observations`, `drafts`, etc.) |
| `scope` | object | no | Filter by `{project, branch, tags}` |
| `mode` | string | no | `governed` (default), own `authoring`, or operator `history` |
| `statuses` | array | no | Lifecycle statuses in authoring/history mode |
| `include_superseded` | bool | no | Historical predecessors; requires history mode |
| `include_relationships` | bool | no | Include 1-hop related thoughts (default: false) |
| `limit` | int | no | Max results (default: 20) |
| `trail_names` | array | no | Additional scope paths to search. Supports globs: `mw/eng/*` (one level), `mw/**` (any depth) |

Each result includes a `source_trail` field indicating which scope it came from. Results are deduplicated by `thought_id`.

### `propose_truth`

Promote a draft thought to its permanent namespace based on `source_type`. Moves from `drafts/` to the target namespace.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | **yes** | ULID of the draft thought to promote |

### `supersede`

Propose a corrected draft successor. The original remains current until successor approval atomically persists both the approved replacement and the original backlink. For wording refinements use `update_thought` on mutable authoring records.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | **yes** | ULID of the thought to supersede |
| `content` | string | **yes** | Content of the replacement thought |
| `reason` | string | **yes** | Why this thought is being superseded |
| `agent_id` | string | no | ID of the agent |
| `confidence` | float | no | 0.0 to 1.0 |

### `change_scope`

Elevate a thought to a different scope. Wraps `supersede` with cross-scope arguments — a draft successor lands in the target scope. The original becomes historical only after durable successor approval.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | **yes** | ULID of the thought to elevate |
| `content` | string | **yes** | Content for the new scope (may be rewritten for broader audience) |
| `target_trail_name` | string | **yes** | Target scope path where the new thought lands |
| `reason` | string | **yes** | Why this thought is being elevated |
| `trail_name` | string | **yes** | Source scope (where the original lives) |
| `agent_id` | string | no | ID of the agent |
| `confidence` | float | no | 0.0 to 1.0 |

### `forget`

Discard current reasoning line. Abandons the current JJ change.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `revision` | string | no | Specific revision to abandon (default: current) |

### `sync`

Sync with shared truth. Fetches from remote and rebases. Aborts automatically on conflict.
Also blocks (status `blocked`) before fetching if the data repo has a dirty working copy or
tracked paths that collide by case — repair or commit the offending paths, then retry.

### `conflicts`

Surface cognitive dissonance. Returns structured conflict summaries with `side_a`/`side_b`/`base` content when available — never raw VCS algebraic notation.

### `rollback`

Return trail to a historical state using JJ operation restore.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `op_id` | string | no | Operation ID to restore to (shows recent ops if omitted) |

### `diff`

Compare thought states. Shows what changed in a revision.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `revision` | string | no | Revision to diff (default: current working change) |

### `list_scopes`

Discover all available scopes recursively. Finds any directory containing a `thoughts/` subdirectory at any depth under `trails/`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prefix` | string | no | Filter scopes under this prefix (e.g. `mw/eng`) |
| `include_stats` | bool | no | Include `thought_count` per scope (default: false) |

`list_trails` is kept as a backward-compatible alias.

### `learn_preference`

Capture a draft user correction on an operator endpoint. Use `propose_truth` for review or explicit human approval; source type alone does not establish approval.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | **yes** | The preference or correction |
| `preference_type` | enum | no | `client` \| `firm` (default: `firm`) |
| `agent_id` | string | no | ID of the agent |
| `metadata` | object | no | Metadata for filtering |

## Thought Lifecycle

```
start_thought  →  save_thought (drafts/)  →  propose_truth  →  permanent namespace
                      ↓                          ↑                     ↓
                  update_thought          (promotion)           decisions/
                  (refine wording)                              observations/
                      ↓                                         preferences/
                  supersede
                  (if conclusion is wrong)
```

1. **Start**: `start_thought` creates a new JJ change for your reasoning line
2. **Save**: `save_thought` writes a thought to `drafts/` by default
3. **Refine**: `update_thought` edits content in-place (same ULID)
4. **Promote**: `propose_truth` moves from `drafts/` to permanent namespace:
   - `decision` → `decisions/`
   - `observation` / `inference` / `tool_output` → `observations/`
   - `user_input` → `preferences/`
5. **Correct**: `supersede` proposes a corrected successor; approval atomically activates it

## Namespace Conventions

| Namespace | Contains | Written by |
|-----------|----------|------------|
| `drafts/` | Working thoughts not yet classified | `save_thought` (default) |
| `decisions/` | Approved architectural decisions | `propose_truth` |
| `observations/` | Runtime observations, inferences, tool outputs | `propose_truth` |
| `intents/` | Architectural intent documents | `save_thought` (explicit namespace) |
| `preferences/client/` | Client-specific stylistic preferences | `learn_preference` |
| `preferences/firm/` | Firm architectural standards | `learn_preference` |

## Agent Conventions

### Agent Identity

`agent_id` is a **stable role identifier**, not a runtime fingerprint. Runtime context belongs in `metadata.extra`.

| Field | Contains | Example |
|-------|----------|---------|
| `agent_id` | Role only | `"claude-code"`, `"claude-desktop"`, `"builder-42"` |
| `metadata.extra` | Runtime context | `{"host": "WiseMachine0002", "session_id": "abc-123", "cwd": "/home/user/project"}` |

### Mandatory Promotion

Drafts are private authoring material. Approved current thoughts are shared institutional records.

- **Always call `propose_truth`** when work is finalized — treat it as a mandatory "commit" step
- Do NOT leave finalized work as drafts — other agents and sessions cannot distinguish "in progress" from "done" without promotion
- `learn_preference` captures a draft preference; approval provenance must identify the review or explicit human action.
- In-progress work stays in `drafts/` — that's fine, drafts are meant for working state

## Key Rules

### Content Mutability

Thoughts can be edited in-place via `update_thought` while in `draft` or `proposed` status. Content is **frozen** when:
- `validation_status` is `approved`, `rejected`, or `tombstoned`
- `superseded_by` is set (thought has been replaced)

The `supersede` tool creates a new draft with predecessor lineage. Only durable successor approval installs the original backlink atomically.

### Conflict Interception

Raw JJ conflict notation is **never** exposed to agents. The MCP server intercepts conflicts and returns structured summaries with `side_a`/`side_b`/`base` content (parsed from JJ snapshot-style conflict markers). Write operations are blocked during conflicts **except** `update_thought` on the conflicted thought — this is the conflict resolution path.

### Semantic Translation

All VCS output goes through a semantic translation layer. Raw `jj log` / `jj op log` stdout is never returned. All responses are token-optimized JSON summaries.

### Recall + Preferences

Preferences obey the same lifecycle and identity rules as other records. Default recall includes matching approved current preferences; draft or proposed preferences require explicit authoring/history retrieval.

## Thought File Format

File: `thoughts/{namespace}/{thought-id}.md`

```yaml
---
schema_version: 1
thought_id: "01JMKR3V8GQZX4N7P2WDCB5HYT"
parent_id: null
superseded_by: null
agent_id: "claude-code"
confidence: 0.9
source_type: "decision"
validation_status: "draft"
intent_ref: null
created_at: "2026-02-19T12:00:00Z"
relationships:
  - type: "DEPENDS_ON"
    target_id: "01JMKQ8W7FNRY3K6P1VDBA4GXS"
metadata:
  project: "my-project"
  branch: "main"
  tags: ["architecture"]
---
The actual thought content in markdown.
```

## Development

PRs must pass:
- `test` — pytest suite (`uv sync --frozen && uv run pytest -v`)
- Semantic PR title — Conventional Commits format, such as `feat:`, `fix:`, or `chore:`

```bash
# Run all tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_tools.py -v

# Run with coverage
uv run pytest --cov=fava_trails
```

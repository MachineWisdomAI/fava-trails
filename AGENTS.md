# FAVA Trail — Agent Reference 🫛👣

Agent-facing reference for FAVA Trail MCP tools. For project setup and configuration, see [README.md](README.md). For the full session protocol with examples, see [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md).

## Scope Discovery

Every tool call requires `trail_name` — a slash-separated scope path (e.g. `mw/eng/fava-trail`). Resolve in priority order:

| Priority | Source | Set where |
|----------|--------|-----------|
| 1 | `FAVA_TRAIL_SCOPE` env var | `.env` (gitignored) — per-worktree override |
| 2 | `.fava-trail.yaml` `scope` | Project root (committed) — default for all clones |
| 3 | `FAVA_TRAIL_SCOPE_HINT` | MCP server `env` block — broad fallback |

**If `FAVA_TRAIL_SCOPE` is not set** but `.fava-trail.yaml` exists, read the `scope` field and write it to `.env` as `FAVA_TRAIL_SCOPE=<scope>`. If neither exists, use the scope hint from tool descriptions and prompt the user to create a `.fava-trail.yaml`.

See [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md) for full scope discovery protocol with examples.

## Session Start Protocol

Before starting work, recall existing context:

```
recall(trail_name="<scope>", query="status")
recall(trail_name="<scope>", query="decisions")
recall(trail_name="<scope>", query="gotcha", scope={"tags": ["gotcha"]})
```

Use `trail_names` with globs for broader context: `recall(trail_name="<scope>", query="architecture", trail_names=["mw/eng/*"])`

## Tools Reference

All tools accept a **required** `trail_name` parameter — the scope path (e.g. `mw/eng/fava-trail`). Scope paths are `/`-separated, with each segment validated as a safe slug. Root-level names (no `/`) trigger a non-blocking warning suggesting a scoped path.

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
- `supersede` — Replace a thought when the conclusion is wrong. Creates a new ULID, backlinks the original. **Use for corrections.**

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
| `include_superseded` | bool | no | Show superseded thoughts (default: false) |
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

Replace a thought with a corrected version. **Atomic**: creates new thought + backlinks original in a single JJ change. Use for conceptual replacement when the conclusion is wrong. For refining wording, use `update_thought` instead.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | **yes** | ULID of the thought to supersede |
| `content` | string | **yes** | Content of the replacement thought |
| `reason` | string | **yes** | Why this thought is being superseded |
| `agent_id` | string | no | ID of the agent |
| `confidence` | float | no | 0.0 to 1.0 |

### `change_scope`

Elevate a thought to a different scope. Wraps `supersede` with cross-scope arguments — the new thought lands in the target scope while the original is marked superseded in the source scope. Both operations are atomic (single JJ change).

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

Capture a user correction or preference. Stored in `preferences/` namespace. Bypasses Trust Gate — user input is auto-approved.

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
5. **Correct**: `supersede` atomically replaces a thought with a corrected version

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

Drafts are **working memory**. Promoted thoughts are **institutional memory**.

- **Always call `propose_truth`** when work is finalized — treat it as a mandatory "commit" step
- Do NOT leave finalized work as drafts — other agents and sessions cannot distinguish "in progress" from "done" without promotion
- **Exception:** `learn_preference` bypasses drafts entirely (user input is auto-approved truth)
- In-progress work stays in `drafts/` — that's fine, drafts are meant for working state

### SPIR Meta-Layer Pattern

When using the SPIR protocol (codev/), FAVA Trail thoughts **link to** `codev/` artifacts — they don't duplicate content.

- Use `source_type: observation` with tags like `["spir", "status", "phase-N"]`
- Content is a broadcast: "Phase 0 Complete — see `codev/reviews/0-repo-separation.md`"
- This gives cross-agent visibility: agents can see project status via `recall` without reading git

## Key Rules

### Content Mutability

Thoughts can be edited in-place via `update_thought` while in `draft` or `proposed` status. Content is **frozen** when:
- `validation_status` is `approved`, `rejected`, or `tombstoned`
- `superseded_by` is set (thought has been replaced)

The `supersede` tool creates a **new** thought with a `parent_id` linking to the original, and sets `superseded_by` on the original — both in a single JJ change (atomic).

### Conflict Interception

Raw JJ conflict notation is **never** exposed to agents. The MCP server intercepts conflicts and returns structured summaries with `side_a`/`side_b`/`base` content (parsed from JJ snapshot-style conflict markers). Write operations are blocked during conflicts **except** `update_thought` on the conflicted thought — this is the conflict resolution path.

### Semantic Translation

All VCS output goes through a semantic translation layer. Raw `jj log` / `jj op log` stdout is never returned. All responses are token-optimized JSON summaries.

### Recall + Preferences

Every `recall` query automatically includes matching preferences from the `preferences/` namespace in the `applicable_preferences` field. Agents don't need to opt in — relevant user corrections are always surfaced.

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

```bash
# Run all tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_tools.py -v

# Run with coverage
uv run pytest --cov=fava_trail
```

## SPIR Protocol

This project follows the SPIR protocol (Specify, Plan, Implement, Review) from codev v2.0.13. SPIR artifacts live in `codev/`.

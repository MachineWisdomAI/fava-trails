# FAVA Trail — Versioned Agent Memory via MCP

FAVA Trail (Federated Agents Versioned Audit Trail) is a Python MCP server that provides versioned, auditable memory for AI agents. Every thought, decision, and observation is stored as a markdown file with YAML frontmatter, tracked in a Jujutsu (JJ) colocated git monorepo.

## Quick Start

```bash
# Install JJ (required)
bash scripts/install-jj.sh

# Install dependencies
uv sync

# Run tests
uv run pytest -v

# Run server
FAVA_TRAIL_DATA_REPO=/path/to/fava-trail-data uv run fava-trail-server
```

## MCP Registration

Add to Claude Desktop `claude_desktop_config.json` or `~/.claude.json`:

```json
{
  "mcpServers": {
    "fava-trail": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fava-trail", "fava-trail-server"],
      "env": {
        "FAVA_TRAIL_DATA_REPO": "/path/to/fava-trail-data"
      }
    }
  }
}
```

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `FAVA_TRAIL_DATA_REPO` | Root directory for trail data (monorepo root) | `~/.fava-trail` |
| `FAVA_TRAILS_DIR` | Override trails directory location (absolute path) | `$FAVA_TRAIL_DATA_REPO/trails` |

The server reads `$FAVA_TRAIL_DATA_REPO/config.yaml` for global settings and manages trails under `$FAVA_TRAIL_DATA_REPO/trails/`.

### Global Config (`config.yaml`)

```yaml
default_trail: default
trails_dir: trails          # relative to FAVA_TRAIL_DATA_REPO
remote_url: null            # git remote URL (optional)
push_strategy: manual       # manual | immediate
```

When `push_strategy: immediate`, the server pushes to remote after every successful write operation. Push failures are non-fatal — the write succeeds and a warning is returned.

## Data Repo Setup (One-Time)

The data repo is a plain git repository that the MCP server JJ-colocates on first use.

### Automated (recommended)

```bash
# 1. Create an empty repo on GitHub, then clone it
git clone https://github.com/YOUR-ORG/fava-trail-data.git

# 2. Run the bootstrap script
bash scripts/bootstrap-data-repo.sh fava-trail-data
```

The script validates the repo is empty, creates `config.yaml` + `.gitignore`, commits via git (once), initializes JJ colocated mode, and tracks the remote bookmark.

### Manual (if you prefer)

```bash
git clone https://github.com/YOUR-ORG/fava-trail-data.git
cd fava-trail-data
```

Create exactly **two files** — nothing else:

**`config.yaml`:**
```yaml
default_trail: default
trails_dir: trails
remote_url: "https://github.com/YOUR-ORG/fava-trail-data.git"
push_strategy: immediate
```

**`.gitignore`:**
```
.jj/
__pycache__/
*.pyc
.venv/
```

> **CRITICAL — do NOT add `trails/` to `.gitignore`.** Trails are plain subdirectories of the monorepo tracked by the same git/JJ repo. Gitignoring `trails/` means thought files are never committed and never pushed to remote.

Do not add a README, CLAUDE.md, Makefile, or any other files. The MCP server creates `trails/` on first use.

```bash
# Commit and push (git — bootstrap only, LAST time you use git push)
git add config.yaml .gitignore
git commit -m "Bootstrap fava-trail-data"
git push origin main

# Initialize JJ colocated mode
jj git init --colocate
jj bookmark track main@origin
```

`jj bookmark track main@origin` is **required once** for auto-push to work. The MCP server calls `jj git init --colocate` automatically if `.jj/` is missing, but it does not set up bookmark tracking.

### After setup

Register the MCP server (see MCP Registration above), then use MCP tools (`save_thought`, `recall`, etc.) for all trail operations. Do not use `git` commands to manage thought files.

## Pushing to Remote

**NEVER use `git push origin main`** after JJ colocates. In JJ colocated mode:
- HEAD is always **detached** — JJ manages commits, not git
- Thought commits live on the detached HEAD chain, not on the `main` git branch
- `git push origin main` only pushes the git `main` bookmark — it misses all thought commits

**If `push_strategy: immediate` is set** (recommended), the server auto-pushes via `jj git push --all` after every write. No manual action needed.

**If you need to push manually:**
```bash
# From within fava-trail-data:
jj bookmark set main -r @-     # advance main bookmark to latest committed change
jj git push --bookmark main    # push to remote
```

## Architecture

**Monorepo model:** A single JJ colocated repo (`.jj/` + `.git/`) lives at `FAVA_TRAIL_DATA_REPO` root. Each trail is a subdirectory — NOT a separate repo. This provides:
- Single atomic history across all trails
- One `jj op log` for complete audit trail
- Cross-trail pollution detection (commit_files asserts all dirty paths are within the expected trail prefix)

```
FAVA_TRAIL_DATA_REPO/           # Monorepo root (.jj/ + .git/)
├── config.yaml                 # Global config
└── trails/
    ├── default/                # Trail (subdirectory, NOT a repo)
    │   └── thoughts/
    │       ├── drafts/
    │       ├── decisions/
    │       ├── observations/
    │       ├── intents/
    │       └── preferences/
    │           ├── client/
    │           └── firm/
    └── project-x/
        └── thoughts/...
```

**Engine vs. Fuel split:**
- `fava-trail` (this repo) — OSS Python MCP server, Apache-2.0
- `fava-trail-data` (separate repo) — Your organization's trail data, config, conventions

## Tools Reference

All tools accept an optional `trail_name` parameter (defaults to the trail configured in `config.yaml`).

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

Search thoughts by query, namespace, and scope. Hides superseded thoughts by default.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | no | Search terms |
| `namespace` | string | no | Restrict to namespace (`decisions`, `observations`, `drafts`, etc.) |
| `scope` | object | no | Filter by `{project, branch, tags}` |
| `include_superseded` | bool | no | Show superseded thoughts (default: false) |
| `include_relationships` | bool | no | Include 1-hop related thoughts (default: false) |
| `limit` | int | no | Max results (default: 20) |

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

### `list_trails`

Show all available FAVA trails.

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

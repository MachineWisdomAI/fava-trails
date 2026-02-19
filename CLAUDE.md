# FAVA Trail — Versioned Agent Memory via MCP

FAVA Trail (Federated Agents Versioned Audit Trail) is a Python MCP server that provides versioned, auditable memory for AI agents. Every thought, decision, and observation is stored as an immutable markdown file with YAML frontmatter, tracked in a Jujutsu (JJ) colocated git repo.

## Quick Start

```bash
# Install JJ (required)
bash scripts/install-jj.sh

# Install dependencies
uv sync

# Run tests
uv run pytest -v

# Run server
FAVA_TRAIL_DATA_REPO=/path/to/trail-data uv run fava-trail-server
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
        "FAVA_TRAIL_DATA_REPO": "/path/to/your/trail-data"
      }
    }
  }
}
```

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `FAVA_TRAIL_DATA_REPO` | Root directory for trail data | `~/.fava-trail` |
| `FAVA_TRAILS_DIR` | Override trails directory location (absolute path) | `$FAVA_TRAIL_DATA_REPO/trails` |

The server reads `$FAVA_TRAIL_DATA_REPO/config.yaml` for global settings and manages trails under `$FAVA_TRAIL_DATA_REPO/trails/`.

## Architecture

- **MCP Server**: stdio transport
- **VCS Backend**: JJ colocated mode (`.jj/` + `.git/` in each trail)
- **Storage**: `$FAVA_TRAIL_DATA_REPO/trails/{trail-name}/thoughts/{namespace}/{ulid}.md`
- **All responses**: Structured JSON — raw VCS output is never returned

## Tools Reference

All tools accept an optional `trail_name` parameter (defaults to the trail configured in `config.yaml`).

### `start_thought`

Begin a new reasoning branch from current truth. Creates a fresh JJ change.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | no | Brief description of reasoning intent |
| `trail_name` | string | no | Trail to use |

### `save_thought`

Save a thought to the trail. Defaults to `drafts/` namespace.

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

**Response format:**
```json
{
  "thoughts": [...],
  "applicable_preferences": [...]
}
```
The `applicable_preferences` field is always populated — matching user preferences from the `preferences/` namespace are automatically included on every recall.

### `forget`

Discard current reasoning line. Abandons the current JJ change.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `revision` | string | no | Specific revision to abandon (default: current) |

### `conflicts`

Surface cognitive dissonance. Returns structured conflict summaries — never raw VCS algebraic notation.

### `diff`

Compare thought states. Shows what changed in a revision.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `revision` | string | no | Revision to diff (default: current working change) |

### `list_trails`

Show all available FAVA trails.

### `supersede`

Replace a thought with a corrected version. **Atomic**: creates new thought + backlinks original in a single JJ change.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `thought_id` | string | **yes** | ULID of the thought to supersede |
| `content` | string | **yes** | Content of the replacement thought |
| `reason` | string | **yes** | Why this thought is being superseded |
| `agent_id` | string | no | ID of the agent |
| `confidence` | float | no | 0.0 to 1.0 |

### Phase 2+ Tools (not yet active)

- `propose_truth` — Promote a draft thought to permanent namespace based on `source_type`
- `sync` — Sync with shared truth (fetch + rebase)
- `rollback` — Return trail to a historical state via JJ operation restore
- `learn_preference` — Capture a user correction or preference

## Thought Lifecycle

```
start_thought  →  save_thought (drafts/)  →  propose_truth  →  permanent namespace
                      ↓                                              ↓
                  supersede (if correction needed)            decisions/
                                                             observations/
                                                             preferences/
```

1. **Start**: `start_thought` creates a new JJ change for your reasoning line
2. **Save**: `save_thought` writes a thought to `drafts/` by default
3. **Promote**: `propose_truth` moves from `drafts/` to permanent namespace:
   - `decision` → `decisions/`
   - `observation` / `inference` / `tool_output` → `observations/`
   - `user_input` → `preferences/`
4. **Correct**: `supersede` atomically replaces a thought with a corrected version

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

**Rationale:** OpenTelemetry Resource vs Attributes pattern. Stable IDs enable cross-session queries ("show me all decisions by claude-code"). High-cardinality IDs (model names, session IDs baked in) destroy aggregation.

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

### Immutability
All thoughts are immutable after creation. The **single permitted exception** is `superseded_by`, which may only be written by the `supersede` tool during an atomic transaction (both the new thought and the backlink are written in a single JJ change).

### Conflict Interception
Raw JJ algebraic conflict notation is **never** exposed to agents. The MCP server intercepts conflicts and returns structured summaries. Write operations (`start_thought`, `save_thought`, `supersede`, etc.) are blocked when conflicts are active — use `conflicts` to inspect and `rollback` to recover.

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

This project follows the SPIR protocol (Specify → Plan → Implement → Review) from codev v2.0.13. SPIR artifacts live in `codev/`.

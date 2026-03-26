# FAVA Trails Data Repo

This directory is a **FAVA Trails** versioned memory store — a git-backed
knowledge base that AI agents read from and write to via MCP tools.

## Core Workflow

```
save_thought  →  creates a draft (invisible to other agents)
propose_truth →  promotes draft to permanent namespace (visible to all)
recall        →  semantic search across promoted thoughts
```

**The propose_truth mandate**: drafts are invisible until promoted.
Always promote finalized work so other agents and sessions can find it.

## Scope Discovery

Every tool call requires a `trail_name` (scope path, e.g. `myorg/eng/my-project`).
Resolve in priority order:

1. `FAVA_TRAILS_SCOPE` env var (per-worktree override via `.env`)
2. `.fava-trails.yaml` `scope` field (committed project default)
3. Ask the user

## Agent Identity

Set `agent_id` to a stable role identifier that describes what you are:

- `"codex-cli"`, `"claude-code"`, `"claude-desktop"`, `"builder-42"`

Do **not** use model names, session IDs, or hostnames — put runtime
context in `metadata.extra` instead.

## Useful Tools

| Tool | Purpose |
|------|---------|
| `save_thought` | Save a new thought (defaults to `drafts/` namespace) |
| `propose_truth` | Promote a draft to permanent namespace |
| `recall` | Search thoughts by query, namespace, scope |
| `get_thought` | Retrieve a specific thought by ULID |
| `update_thought` | Refine wording in-place (drafts only) |
| `supersede` | Replace a thought with a corrected version |
| `sync` | Pull/push latest from remote |
| `get_usage_guide` | Full protocol reference with examples |

## Getting Started

1. Call `get_usage_guide` for the full protocol with examples and trust
   calibration details.
2. Use `recall` to search for existing context before starting work.
3. Use `save_thought` + `propose_truth` to persist your findings.
4. Call `sync` when done to push changes to remote.

## Directory Structure

- `trails/` — thought files organized by namespace and scope
- `config.yaml` — data repo configuration (trust gate model, etc.)
- `trust-gate-prompt.md` — prompt template for the Trust Gate reviewer

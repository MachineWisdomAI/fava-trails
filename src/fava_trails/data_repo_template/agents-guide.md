# FAVA Trails Data Repo

This directory is a **FAVA Trails** versioned memory store — a git-backed
knowledge base that AI agents read from and write to via MCP tools.

> Bootstrap installs this file as `AGENTS.md` in new data repositories.
> Source name is `agents-guide.md` so agent workspaces can edit the packaged
> template without colliding with Hermes-protected `AGENTS.md` basenames.

## Core Workflow

```
save_thought  →  creates a draft (out of default governed recall)
propose_truth →  promotes draft; approved current records enter governed recall
recall        →  lexical whitespace-token substring AND search (not semantic)
```

**The propose_truth mandate**: drafts stay out of default governed recall until
promoted. The same process-configured identity can still read its own drafts via
`mode="authoring"` (shared endpoint = shared identity; filesystem is
operator-trusted). Always promote finalized work so other agents and sessions
can find it through default recall.

Promotion commits locally only. Publishing to a remote requires either
`push_strategy: immediate` (auto-push after successful writes) or the full
manual protocol:

```bash
jj bookmark set main -r @-     # completed writes sit at @-
jj git push --bookmark main
```

Writers must publish before peers can fetch. The `sync` tool only fetches and
rebases shared truth; it does **not** push local commits.

## Scope Discovery

Every tool call requires a `trail_name` (scope path, e.g. `myorg/eng/my-project`).
Resolve in priority order:

1. `FAVA_TRAILS_SCOPE` env var (per-worktree override via `.env`)
2. `.fava-trails.yaml` `scope` field (committed project default)
3. Ask the user

Read-only lookups do not create missing scopes. If a scope is uncertain, call
`list_scopes` first and use an exact returned path. If you have a full ULID,
`get_thought` can find the unique matching thought in another existing scope and
returns `source_trail` for follow-up calls.

## Agent Identity

The operator configures `FAVA_TRAILS_AGENT_ID` on the MCP process; caller
`agent_id` must match it. Use a stable role identifier:

- `"codex-cli"`, `"claude-code"`, `"claude-desktop"`, `"builder-42"`

Do **not** use model names, session IDs, or hostnames — put runtime
context in `metadata.extra` instead.

## Useful Tools

| Tool | Purpose |
|------|---------|
| `save_thought` | Save a new thought (defaults to `drafts/` namespace) |
| `propose_truth` | Promote a draft to permanent namespace (local commit) |
| `recall` | Lexical substring-AND search by query, namespace, scope |
| `get_thought` | Retrieve a specific thought by ULID |
| `update_thought` | Refine wording in-place (draft/proposed only) |
| `supersede` | Propose a corrected draft successor |
| `sync` | Fetch/rebase shared truth from remote (does not push) |
| `get_usage_guide` | Full protocol reference with examples |

## Getting Started

1. Call `get_usage_guide` for the full protocol with examples and trust
   calibration details.
2. Use `recall` to search for existing context before starting work.
3. Use `save_thought` + `propose_truth` to persist your findings.
4. Publish local commits (`push_strategy: immediate`, or manual
   `jj bookmark set main -r @-` then `jj git push --bookmark main`).
5. On peer machines, call `sync` to fetch/rebase shared truth (sync does not
   publish).

## Directory Structure

- `trails/` — thought files organized by namespace and scope
- `config.yaml` — data repo configuration (trust gate model, etc.)
- `trust-gate-prompt.md` — prompt template for the Trust Gate reviewer

# Using FAVA Trail

Canonical usage instructions for AI agents using FAVA Trail MCP tools. Other docs reference this file — keep it up to date.

## Scope Discovery (Three-Layer)

Every FAVA Trail tool call requires a `trail_name` parameter — a slash-separated scope path (e.g. `mwai/eng/fava-trails`). Three sources are checked in priority order:

| Priority | Source | Set where | Purpose |
|----------|--------|-----------|---------|
| 1 | `FAVA_TRAIL_SCOPE` env var | `.env` file (gitignored) | Per-worktree override for epic/branch work |
| 2 | `.fava-trail.yaml` `scope` | Project root (committed) | Default project scope, shared across clones |
| 3 | `FAVA_TRAIL_SCOPE_HINT` | MCP server `env` block | Broad org/team fallback baked into tool descriptions |

**How to determine your trail_name:**

1. Check env vars for `FAVA_TRAIL_SCOPE` (loaded from project `.env`) — use that if set
2. If not set, read `.fava-trail.yaml` at the project root for `scope`
3. If in a different directory, check that directory's `.fava-trail.yaml` or `.env`
4. Otherwise, use the scope shown in tool descriptions (from `FAVA_TRAIL_SCOPE_HINT`)
5. If none found, ask the user

**Per-worktree `.env` convention:** Use `.env` only for overrides (epic work, branch-specific scope):
```
FAVA_TRAIL_SCOPE=mwai/eng/fava-trails/0001a-my-epic
```

**Committed default:** `.fava-trail.yaml` provides the project scope for all clones:
```yaml
scope: mwai/eng/fava-trails
```

## At Session Start

1. **Determine your trail_name** — follow the three-layer resolution above
2. **Check FAVA Trail first** — use `recall`:
   ```
   recall(trail_name="<scope>", query="status", scope={"project": "<project-name>"})
   recall(trail_name="<scope>", query="decisions", scope={"project": "<project-name>"})
   recall(trail_name="<scope>", query="gotcha", scope={"tags": ["gotcha"]})
   ```
   For broader context, search multiple scopes with `trail_names` (supports globs):
   ```
   recall(trail_name="<scope>", query="architecture", trail_names=["mwai/eng/*"])
   ```
3. **If FAVA Trail has thoughts** — use them as your primary context. Decisions, observations, and preferences from other agents are all here.
4. **If FAVA Trail is empty** — fall back to legacy files:
   - `memory/shared/decisions.md`, `memory/shared/gotchas.md`
   - `memory/branches/<current-branch>/status.md`
   - `codev/branches/<current-branch>/status.md` (if `codev/` exists)
5. Detect current branch: `git branch --show-current`

## During Work

Save working thoughts to FAVA Trail as you go:

```
save_thought(
  trail_name="<scope>",
  content="What I found or decided",
  source_type="observation",    # or "decision", "inference"
  agent_id="claude-code",
  metadata={"project": "my-project", "branch": "main", "tags": ["relevant-tag"]}
)
```

- Use `source_type` appropriately: `observation` for findings, `decision` for choices, `inference` for conclusions
- Working thoughts go to `drafts/` by default — that's correct for in-progress work
- **Refine wording** on a draft: `update_thought(trail_name="...", thought_id="<ULID>", content="updated text")`
- **Elevate to broader scope**: `change_scope(trail_name="<source>", thought_id="<ULID>", content="...", target_trail_name="<target>", reason="team-relevant finding")`

## On Task Completion

1. **Promote finalized thoughts** — call `propose_truth(trail_name="...", thought_id="<ULID>")` on any draft thoughts that represent completed work. This is mandatory; other agents cannot see your work otherwise.
2. **Save decisions** as `source_type: "decision"` and promote them
3. **Save gotchas** as `source_type: "observation"` with `tags: ["gotcha"]` and promote them
4. **Sync** — call `sync(trail_name="...")` to push your thoughts so other agents/machines can see them
5. **Legacy fallback**: If FAVA Trail is unavailable, update `memory/branches/<branch>/status.md`

## Agent Identity

`agent_id` is a **stable role identifier**, not a runtime fingerprint:

| Field | Contains | Example |
|-------|----------|---------|
| `agent_id` | Role only | `"claude-code"`, `"claude-desktop"`, `"builder-42"` |
| `metadata.extra` | Runtime context | `{"host": "WiseMachine0002", "session_id": "abc-123", "cwd": "/home/user/project"}` |

Do NOT put model names, session IDs, or hostnames in `agent_id`.

## SPIR Meta-Layer

When working under the SPIR protocol, FAVA Trail thoughts **link to** `codev/` artifacts — they don't duplicate content:

- Use `source_type: observation` with `tags: ["spir", "status", "phase-N"]`
- Content broadcasts state changes: "Phase 1 Complete — see `codev/reviews/1-name.md`"
- Thoughts are scoped to the epic: `trail_name="mwai/eng/project/0001a-epic-name"`
- This gives cross-agent visibility without requiring git access

# FAVA Trail — Agent Onboarding

Cheat sheet for AI agents using FAVA Trail MCP tools. For scope discovery and full session protocol, see [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md). For tool reference, see [CLAUDE.md](CLAUDE.md).

## At Session Start

```
recall(trail_name="<scope>", query="status", scope={"project": "<project-name>"})
recall(trail_name="<scope>", query="decisions", scope={"project": "<project-name>"})
recall(trail_name="<scope>", query="gotcha", scope={"tags": ["gotcha"]})
```

Read the results. They contain decisions, observations, and context from previous sessions and other agents.

## During Work

Save thoughts as you go:

```
save_thought(
  trail_name="<scope>",
  content="What I found or decided",
  source_type="observation",    # or "decision", "inference"
  agent_id="claude-code",       # stable role ID, not model name
  metadata={"project": "my-project", "branch": "main", "tags": ["relevant-tag"]}
)
```

Thoughts go to `drafts/` by default. That's correct for in-progress work.

## At Session End

**Promote finalized thoughts** — this is mandatory. Other agents cannot see your work otherwise:

```
propose_truth(trail_name="<scope>", thought_id="<ULID>")
```

This moves the thought from `drafts/` to its permanent namespace (`decisions/`, `observations/`, etc.) based on `source_type`.

### What to promote

| What | source_type | Tags |
|------|-------------|------|
| Completed work status | `observation` | `["status"]` |
| Architectural decisions | `decision` | `["architecture"]` |
| Lessons learned / gotchas | `observation` | `["gotcha"]` |
| Bug root causes | `observation` | `["debugging"]` |

### What NOT to promote

- In-progress work (leave in `drafts/`)
- Speculative thoughts that may change
- Duplicate information already in promoted thoughts

## Correcting Mistakes

**Refine wording** (same thought, same ULID):
```
update_thought(trail_name="<scope>", thought_id="<ULID>", content="Updated content")
```

**Replace a wrong conclusion** (new thought, backlinks original):
```
supersede(trail_name="<scope>", thought_id="<ULID>", content="Corrected content", reason="Why it was wrong")
```

## User Corrections

When a user corrects you, capture it immediately:
```
learn_preference(trail_name="<scope>", content="Always use uv, not pip", preference_type="firm")
```

Preferences bypass drafts — they're saved directly to `preferences/`. Every `recall` query automatically surfaces matching preferences.

## Agent Identity

Use a **stable role identifier** for `agent_id`:
- `"claude-code"`, `"claude-desktop"`, `"builder-42"`

Do NOT use model names, session IDs, or hostnames. Put runtime context in `metadata`:
```
metadata={"project": "...", "extra": {"host": "machine-name", "cwd": "/path"}}
```

## Sync

To pull the latest thoughts from other agents/machines:
```
sync(trail_name="<scope>")
```

This fetches from the git remote and rebases. Conflicts are surfaced as structured data via `conflicts()`.

## Key Rules

1. **Always promote finalized work** — `propose_truth` is your "commit" step
2. **Never touch git/jj directly** — use MCP tools for all trail operations
3. **Preferences auto-surface** — `recall` includes matching preferences automatically
4. **Superseded thoughts are hidden** — `recall` hides them by default; pass `include_superseded=True` to see history
5. **Content freezes after approval** — `update_thought` works on drafts only; use `supersede` for approved thoughts

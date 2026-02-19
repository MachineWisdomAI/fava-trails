# Spec 1: Core MCP Server + JJ Backend

**Status:** integrated
**Author:** Claude (with 3-way consensus: GPT-5.1 Codex, Gemini 3 Pro, O3)
**Consensus Continuation ID:** `16cf1bcf-6d6c-41fc-98ee-3da62dd1a011`

---

## Problem Statement

AI agents across Machine Wisdom's toolchain suffer from three compounding memory failures:
1. **No versioning** — flat markdown files (`memory/shared/decisions.md`) with no rollback
2. **No shared ground truth** — Claude Code and Desktop operate in isolated sessions
3. **No audit trail** — no provenance tracking, no hallucination detection

## Proposed Solution

A Python MCP server that provides versioned, auditable memory for AI agents using Jujutsu (JJ) VCS in colocated mode. Thoughts are immutable `.md` files with YAML frontmatter, stored in namespace directories, tracked in JJ colocated git repos.

## Architecture

```
Claude Code CLI ──┐                  ┌── codev adapter (P4)
                  │   MCP (stdio)    │
Claude Desktop ───┼──> MCP Server ───┼── OpenClaw (P5)
                  │                  │
Any MCP client ───┘     │            └── toolkit (P2)
                        │
                  TrailManager
                  (per-trail mutex)
                        │
                  VcsBackend ABC
                   /          \
             JjBackend    GitBackend
                   \          /
              FAVA_TRAIL_HOME env var
                        │
                   trails/ dir
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Matches pal-mcp-server pattern (mcp SDK, Pydantic, uv, stdio) |
| VCS engine | JJ-first (colocated mode) | First-class conflicts, Change-IDs, op log, crash-proof snapshots |
| Trust Gate | Direct OpenRouter API (not Pal MCP) | Background reviewer, not interactive |
| Thought IDs | ULID in frontmatter | Stable across rebases, independent of commit/Change-IDs |
| Thought mutability | Immutable with one exception: `superseded_by` | Append-only prevents merge conflicts. Atomic via single JJ change |
| Namespace separation | Directory-based (`thoughts/{namespace}/`) | Filesystem-level isolation |
| VCS output handling | Semantic translation layer | Raw VCS stdout never returned to agents |
| Conflict handling | Conflict interception layer | Raw algebraic notation never exposed to agents |
| GC | Automated `jj util gc` + `git gc` at intervals | Prevents object bloat |

## Thought File Format

```yaml
---
schema_version: 1
thought_id: "01JMKR3V8GQZX4N7P2WDCB5HYT"
parent_id: null
superseded_by: null
agent_id: "claude-code-main"
confidence: 0.9
source_type: "decision"
validation_status: "draft"
intent_ref: null
created_at: "2026-02-19T12:00:00Z"
relationships:
  - type: "DEPENDS_ON"
    target_id: "01JMKQ8W7FNRY3K6P1VDBA4GXS"
metadata:
  project: "wise-agents-toolkit"
  branch: "main"
  tags: ["architecture"]
---
```

## MCP Tools — Phase 1 (9 tools)

| Tool | Purpose |
|------|---------|
| `start_thought` | Begin new reasoning branch from current truth |
| `save_thought` | Checkpoint mental state (defaults to `drafts/` namespace) |
| `get_thought` | Deterministic retrieval by ULID |
| `recall` | Search thoughts with namespace/scope filtering, supersession hiding |
| `forget` | Discard current reasoning line |
| `conflicts` | Surface cognitive dissonance (structured, never raw) |
| `diff` | Compare thought states |
| `list_trails` | Show available trails |
| `supersede` | Atomic replacement: new thought + backlink in single JJ change |

## Supersede Atomicity

Both the new thought creation AND the original's `superseded_by` backlink occur in a single JJ change. If process crashes mid-operation, either both writes exist or neither does.

**Required test scenarios:**

| # | Scenario | Assertion |
|---|----------|-----------|
| 1 | Happy path: supersede a draft thought | New thought exists, original's `superseded_by` set, both in same JJ change |
| 2 | Supersede an already-superseded thought | Error: "Thought X is already superseded by Y" |
| 3 | Supersede with non-existent `thought_id` | Error: "Thought X not found" |
| 4 | `recall` after supersede (default) | Original hidden, replacement returned |
| 5 | `recall` after supersede (`include_superseded=True`) | Both original and replacement returned |
| 6 | Verify atomicity: both files in single JJ change | `jj log -r @` shows both files in one change |

## Recall Response Format

```json
{
  "thoughts": [...],
  "applicable_preferences": [...]
}
```

`applicable_preferences` is always-on — no opt-in flag required. On every `recall`, the server scans `preferences/` for matching scope overlap.

## Namespace Routing (`propose_truth`)

| `source_type` | Target namespace |
|---------------|-----------------|
| `decision` | `decisions/` |
| `observation` | `observations/` |
| `inference` | `observations/` |
| `tool_output` | `observations/` |
| `user_input` | `preferences/` |
| *(unknown)* | **Rejection** with error message |

## Success Criteria

1. JJ binary installed, `jj version` succeeds
2. `uv run fava-trail-server` starts and responds to `list_tools` (9 Phase 1 tools)
3. All 9 Phase 1 tools work end-to-end
4. `save_thought` defaults to `drafts/` namespace
5. `supersede` is atomic — crash mid-operation leaves no orphans
6. `conflicts` returns structured summaries, never raw notation
7. All tool responses are token-optimized JSON
8. `recall` hides superseded thoughts by default
9. `recall` filters by namespace and scope
10. Decision without `intent_ref` logs a warning
11. GC runs without blocking operations
12. `uv run pytest` passes

## Out of Scope (Phase 2+)

- `propose_truth`, `sync`, `rollback`, `learn_preference` (Phase 2)
- Semantic search / SQLite-vec (Phase 3)
- codev integration (Phase 4)
- OpenClaw memory driver (Phase 5)

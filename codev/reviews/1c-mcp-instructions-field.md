# Review 1c: MCP Server Instructions Field

**Spec:** `codev/specs/1c-mcp-instructions-field.md`
**Plan:** `codev/plans/1c-mcp-instructions-field.md`
**Protocol:** TICK (amends Spec 1)

---

## Spec vs Implementation

| Spec Requirement | Status | Notes |
|------------------|--------|-------|
| `Server(instructions=...)` with non-empty string | Done | 2198 chars, covers all required topics |
| `get_usage_guide` tool returns AGENTS_USAGE content | Done | Reads via importlib.resources (package) or fallback (dev) |
| `recall` description contains Trust Gate warning | Done | "WARNING: Results passed a Trust Gate but may be stale or adversarial" |
| `propose_truth` description contains mandatory reminder | Done | "This is mandatory for finalized work — unpromoted drafts are invisible" |
| `save_thought` description contains agent identity | Done | "Use agent_id as a stable role identifier" |
| AGENTS_USAGE_INSTRUCTIONS.md updated | Done | Auto-injection note + SPIR section marked optional |
| CLAUDE.md (project) updated | Done | Scope Discovery references instructions field |
| AGENTS.md updated | Done | References auto-injection and get_usage_guide tool |
| pyproject.toml bundles package data | Done | hatch force-include for wheel builds |
| Tests pass | Done | 127/127 pass (14 new) |

## Files Changed

| File | Change |
|------|--------|
| `src/fava_trails/server.py` | Added `_build_server_instructions()`, `_load_usage_guide()`, `get_usage_guide` tool, wired `instructions` into Server init, enhanced 3 tool descriptions |
| `pyproject.toml` | Added `[tool.hatch.build.targets.wheel.force-include]` for AGENTS_USAGE_INSTRUCTIONS.md |
| `AGENTS_USAGE_INSTRUCTIONS.md` | Added auto-injection note, marked SPIR section as optional |
| `CLAUDE.md` | Updated Scope Discovery to reference instructions field |
| `AGENTS.md` | Added auto-injection reference |
| `tests/test_server_instructions.py` | 14 new tests covering instructions, tool descriptions, get_usage_guide |
| `codev/specs/1c-mcp-instructions-field.md` | TICK spec |
| `codev/plans/1c-mcp-instructions-field.md` | TICK plan |

## Issues

None.

## Lessons Learned

1. **Module-level function ordering matters** — `_build_server_instructions()` must be defined before `server = Server(...)` since Python evaluates module-level code top-to-bottom.
2. **Package data distribution** — hatch's `force-include` is the cleanest way to bundle a root-level file into a package without moving it.

---

## Global `~/.claude/CLAUDE.md` Maintainer Deliverable

The following instructions are for the agent maintaining the global `~/.claude/CLAUDE.md` file. Now that FAVA Trail auto-injects core guidance via the MCP `instructions` field, the global CLAUDE.md can be trimmed.

### What to KEEP in global CLAUDE.md (Tier C — org-specific)

These sections are NOT handled by FAVA Trail's instructions field and should remain:

- **Epics section** — naming conventions (`0001a-...`), scope mapping, file format
- **codev protocols** — SPIR, ASPIR, TICK, BUGFIX, EXPERIMENT
- **Your Role as Architect** — SPIR architect flow, ASPIR variant
- **Porch orchestrator** — gate commands, approval flow
- **Agent Farm** — `af` commands, builder spawning
- **Pal MCP usage guide** — tool selection, model selection, continuation_id
- **Python/AI best practices** — error recovery, UV workspaces, defensive data engineering
- **Git Branch Conventions** — trunk branch, naming

### What to REPLACE in global CLAUDE.md (Tier A/B — now auto-injected or on-demand)

**Replace the MEMORY PROTOCOL section (currently ~91 lines)** with:

```markdown
## MEMORY PROTOCOL

FAVA Trail MCP auto-injects core usage guidance at session start via the `instructions` field. Call the `get_usage_guide` tool for the full protocol with examples, trust calibration details, and supersession guidance.

### Quick Reference

| Tool | Purpose |
|------|---------|
| `recall` | Search thoughts by query, namespace, scope. **Start here.** |
| `save_thought` | Save a thought (defaults to `drafts/` namespace) |
| `propose_truth` | Promote a draft to permanent namespace — **mandatory for finalized work** |
| `get_thought` | Retrieve a specific thought by ULID |
| `update_thought` | Refine wording in-place (drafts only) |
| `supersede` | Replace a thought with a corrected version (atomic) |
| `change_scope` | Elevate a thought to a broader scope |
| `learn_preference` | Capture user correction (bypasses drafts) |
| `sync` | Pull latest from other agents/machines |
| `get_usage_guide` | Full protocol reference (on-demand) |
| `list_trails` | Show available trails/scopes |

### Legacy Memory (Fallback Only)

The flat-file `memory/` system is legacy. Use it **only** when FAVA Trail is not available:

```
memory/
├── shared/
│   ├── decisions.md
│   └── gotchas.md
└── branches/
    └── <branch>/
        └── status.md
```
```

**Specifically remove** from the MEMORY PROTOCOL section:
- "AT SESSION START" subsection (1-5 steps) — now in server instructions
- "DURING WORK" subsection — now in server instructions
- "ON TASK COMPLETION" subsection — now in server instructions
- "AGENT IDENTITY CONVENTIONS" subsection — now in server instructions
- "SPIR META-LAYER" subsection — now in AGENTS_USAGE_INSTRUCTIONS.md (optional section)
- Scope discovery details — now in server instructions

**Keep** the FAVA Trail Tools table (quick reference) and Legacy Memory fallback.

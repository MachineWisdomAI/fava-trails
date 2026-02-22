# Spec 10: codev Integration

**Status:** not started
**Epic:** 0005a-adoption
**Source:** Spec 2 (Hierarchical Scoping) codev Integration section
**Prerequisites:** Spec 2 (Hierarchical Scoping), Spec 12 (Rebrand)
**Supersedes:** Old Spec 9 (codev file watcher — dropped)

---

## Problem Statement

codev builders and architects need FAVA Trail scope awareness. The original approach (Spec 9: file watcher on `status.yaml`) was dropped — hierarchical scoping (Spec 2) provides the foundation, but builders still need to know their scope and use it.

## Proposed Solution

Configuration-only integration. No codev source changes, no file watcher. Three pieces:

### 1. `FAVA_TRAIL_SCOPE` Environment Variable

Each repo's working directory contains a `.env` (cwd only, no walk-up) with:

```env
FAVA_TRAIL_SCOPE=mw/eng/fava-trail
```

Builders read this and pass it as `trail_name` on every FAVA Trail tool call.

### 2. `CLAUDE.md` Template

Project `CLAUDE.md` instructs the builder to use FAVA Trail with its scope:

```markdown
## Institutional Memory (FAVA Trail)

Your scope is defined in .env as FAVA_TRAIL_SCOPE. Read it and pass as trail_name.
Parent scopes: mw/eng, mw

Before starting work, check for relevant context:
- `recall(query="gotchas", trail_name="$FAVA_TRAIL_SCOPE", trail_names=["mw/eng", "mw"])`
- `recall(query="decisions", trail_name="$FAVA_TRAIL_SCOPE", trail_names=["mw/eng", "mw"])`

If recall is unavailable (MCP error), proceed without it — supplementary, not a gate.
```

### 3. `af spawn` Integration

Pass `FAVA_TRAIL_SCOPE` in builder environment:

```bash
af spawn --project 0003 --env FAVA_TRAIL_SCOPE=mw/eng/fava-trail/0003-auth-epic
```

The builder's `CLAUDE.md` tells it to read this env var and use it as `trail_name`.

### Architect Visibility

The Tower (architect) at `mw/eng/fava-trail` uses glob reads to see all work:

```python
recall(query="blocking issues", trail_name="mw/eng/fava-trail", trail_names=["mw/eng/fava-trail/**"])
```

## Done Criteria

- `.env` template with `FAVA_TRAIL_SCOPE` documented
- `CLAUDE.md` template with recall instructions documented
- `af spawn` integration with `--env FAVA_TRAIL_SCOPE=...` documented
- Architect glob read pattern documented
- No code changes to FAVA Trail server (configuration only)

## Out of Scope

- File watcher on `status.yaml` (dropped)
- Modifying codev protocol itself
- Automatic scope discovery (agent's responsibility)

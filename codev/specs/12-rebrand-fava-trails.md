# Spec 12: Rebrand to FAVA Trails (Plural) 🫛👣

**Status:** not started
**Epic:** 0004a-rebrand
**Prerequisites:** Specs 3-8 (core pipeline complete)

---

## Problem Statement

The project is currently named `fava-trails` (singular), but with hierarchical scoping the system inherently manages multiple trails. The plural form `fava-trails` better reflects the architecture and user mental model.

Additionally, the current `CLAUDE.md` serves as both project documentation and agent usage guide. It should be split into `README.md` (human-facing) and `AGENTS.md` (agent-facing). `AGENTS.md` is not Claude-specific — it documents how *any* AI agent should use FAVA Trails (scope discovery, thought lifecycle, conventions). Humans read `README.md`.

## Scope

### Package Rename
- Rename Python package: `fava_trails` → `fava_trails`
- Rename repo: `fava-trails` → `fava-trails`
- Rename CLI entry point: `fava-trails-server` → `fava-trails-server`
- Update PyPI package name (if published)
- Update all imports, references, docs
- Adopt 🫛👣 (FAVA Trails) as project icon/flare in docs and branding
- Update MCP server registration examples
- No changes to data repo storage layer — `fava-trails-data` path remains stable

### Documentation Split
- Create `README.md` (human-facing): project intro, quick start, installation, MCP registration, architecture overview, full configuration reference (all env vars with "Read by" column), data repo setup, pushing to remote
- Rename `CLAUDE.md` → `AGENTS.md` (agent-facing): scope discovery (two-layer), thought lifecycle, agent conventions (identity, mandatory promotion, SPIR meta-layer), namespace conventions, key rules (content mutability, conflict interception, semantic translation), dev commands
- `AGENTS.md` references `README.md` for canonical docs (no duplication)
- Keep a minimal `CLAUDE.md` stub that points to `AGENTS.md` (for Claude Code/Desktop auto-loading)

### Configuration Table (in README.md)
Single authoritative env var reference with "Read by" column:

| Variable | Read by | Purpose | Default |
|----------|---------|---------|---------|
| `FAVA_TRAILS_DATA_REPO` | Server | Root directory for trail data | `~/.fava-trails` |
| `FAVA_TRAILS_DIR` | Server | Override trails directory location | `$FAVA_TRAILS_DATA_REPO/trails` |
| `FAVA_TRAILS_SCOPE_HINT` | Server | Broad scope hint baked into tool descriptions | *(none)* |
| `FAVA_TRAILS_SCOPE` | Agent | Project-specific scope from `.env` | *(none)* |

## Non-Goals

- No functional changes — this is purely cosmetic/naming/docs
- No protocol or API changes

## Success Criteria

- All tests pass with new package name
- MCP registration works with new entry point
- No references to old singular name remain (except git history)
- `README.md` exists and is the GitHub landing page
- `AGENTS.md` exists with agent-focused docs
- `CLAUDE.md` is a stub pointing to `AGENTS.md`
- No duplicated configuration tables between files

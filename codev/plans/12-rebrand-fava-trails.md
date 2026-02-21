# Plan 12: Rebrand to FAVA Trails (Plural) 🫛

**Status:** not started
**Spec:** `codev/specs/12-rebrand-fava-trails.md`

---

## Phase 1: Documentation split

- Create `README.md` from human-facing sections of current `CLAUDE.md` (intro, quick start, MCP registration, architecture, config reference with "Read by" column, data repo setup, pushing to remote)
- Rename `CLAUDE.md` → `AGENTS.md` (keep agent-facing sections: scope discovery, thought lifecycle, agent conventions, namespace conventions, key rules, dev commands)
- `AGENTS.md` references `README.md` for canonical config/setup docs
- Create minimal `CLAUDE.md` stub: "See AGENTS.md for agent instructions and README.md for project documentation."
- Verify no duplicated content between files

## Phase 2: Rename package internals

- Rename `src/fava_trail/` → `src/fava_trails/`
- Update all internal imports
- Update `pyproject.toml` (package name, entry points)
- Update all test imports
- Run tests — all must pass

## Phase 3: Rename external references

- Update `AGENTS.md`, `README.md`, `CLAUDE.md` stub
- Update MCP registration examples in all files
- Update codev docs and status files
- Update `.env-example`
- Rename GitHub repo (coordinate with org)
- Update `wise-fava-trail` references

## Done Criteria

- `uv run fava-trails-server` starts the MCP server
- All tests pass
- No stale `fava_trail` (singular) imports remain
- `README.md` is the GitHub landing page (human docs)
- `AGENTS.md` has agent-facing docs (scope, lifecycle, conventions)
- `CLAUDE.md` stub points to `AGENTS.md`
- 🫛 emoji appears in project branding

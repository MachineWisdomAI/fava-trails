# Plan 10: codev Integration

**Status:** not started
**Spec:** `codev/specs/10-codev-integration.md`

---

## Phase 10.1: Templates and Documentation

**Goal:** Provide `.env`, `CLAUDE.md`, and `af spawn` templates for codev builders to use FAVA Trail with hierarchical scoping.

**Files created/modified:**
- `templates/codev-env.example` — `.env` template with `FAVA_TRAILS_SCOPE`
- `templates/codev-claude-md.example` — `CLAUDE.md` snippet for builder scope awareness
- `CLAUDE.md` — Document codev integration pattern

**Done criteria:**
- Templates are clear and self-contained
- `af spawn --env FAVA_TRAILS_SCOPE=...` pattern documented
- Architect glob read pattern documented
- No server code changes (configuration only)

# Review: Spec 12 — Rebrand to FAVA Trails (Plural) 🫛👣

## Spec vs Implementation

**Phase 1 — Documentation split:** Complete. README.md is now human-facing with full configuration table. AGENTS.md is the comprehensive agent reference (tools, scope discovery, thought lifecycle, conventions). CLAUDE.md is the minimal stub. No content duplication.

**Phase 2 — Package rename:** Complete. `fava_trail` → `fava_trails`, `fava-trail-server` → `fava-trails-server`, `FAVA_TRAIL_DATA_REPO` → `FAVA_TRAILS_DATA_REPO`. All imports and test fixtures updated. uv.lock updated.

**Phase 3 — External references:** Complete. README MCP registration examples, architecture diagram, cross-machine setup, doc headings and body text, scope examples in AGENTS.md, pytest coverage target, AGENTS_SETUP_INSTRUCTIONS.md layout diagrams.

**Architect review comments (inline in spec):** All addressed.
- Removed wise-fava-trail reference — data repo `fava-trail-data` unchanged
- FAVA_TRAIL_DATA_REPO → FAVA_TRAILS_DATA_REPO
- FAVA_TRAIL_SCOPE kept singular (confirmed by architect)

**Backwards compatibility:** FAVA_TRAIL_DATA_REPO shim added to config.py with deprecation warning. Existing deployments continue working. Priority chain: FAVA_TRAILS_DATA_REPO > FAVA_TRAIL_DATA_REPO (deprecated) > FAVA_TRAIL_HOME (legacy) > default.

## Issues Review

| Phase | Issue | Resolution |
|-------|-------|-----------|
| 2 | FAVA_TRAIL_DATA_REPO silently dropped (found by all 3 reviewers) | Fixed: backwards-compat shim in config.py |
| 3 | Product name headings still said "FAVA Trail" (5 files) | Fixed: all headings/body text updated to "FAVA Trails" |
| 3 | AGENTS.md scope examples still `mw/eng/fava-trail` | Fixed: updated to `mw/eng/fava-trails` |
| 3 | AGENTS.md `--cov=fava_trail` functionally broken | Fixed: updated to `--cov=fava_trails` |
| 3 | README.md Engine label said `fava-trail` | Fixed: updated to `fava-trails` |
| 1 | README JSON examples used old FAVA_TRAIL_DATA_REPO | Fixed: replaced all occurrences |

## Architecture Updates

Package is now `fava_trails` (plural). Entry point is `fava-trails-server`. Config env var is `FAVA_TRAILS_DATA_REPO`.

Backwards-compat chain in `config.get_data_repo_root()`:
```
FAVA_TRAILS_DATA_REPO (new) > FAVA_TRAIL_DATA_REPO (deprecated, warns) > FAVA_TRAIL_HOME (legacy, warns) > ~/.fava-trail (default)
```

Documentation split:
- `README.md` — humans (quickstart, architecture, configuration)
- `AGENTS.md` — agents (tools ref, scope discovery, conventions) — replaces old AGENTS.md cheat sheet
- `AGENTS_USAGE_INSTRUCTIONS.md` — agents (session protocol, canonical usage)
- `AGENTS_SETUP_INSTRUCTIONS.md` — operators (data repo setup)
- `CLAUDE.md` — minimal stub (redirects to README + AGENTS)

Data repo (`fava-trail-data`) and default home (`~/.fava-trail`) paths intentionally unchanged per architect directive. `.fava-trail.yaml` config filename and `FAVA_TRAIL_SCOPE` env var intentionally kept singular per architect spec review comment.

## Lessons Learned Updates

**Backwards compat first:** When renaming env vars, always check what existing deployments use. Add deprecation shims with warnings before cutting over entirely.

**Title propagation:** When rebranding, grep for the brand name in headings AND body text — they can diverge. The machine-readable path/import checks miss prose references.

**Phase scoping:** External reference docs (README, AGENTS.md) correctly deferred to Phase 3, keeping Phase 2 focused on the package internals. Correct scoping prevented phase bloat.

**Porch env (WSL):** The `spawn /bin/sh ENOENT` and `import fava_trail` porch build check issues are WSL environment limitations. Documented in this review so future builders know to expect architect to run `porch done` from outside in this environment.

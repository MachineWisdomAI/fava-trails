## Phase 2 Review — Rebuttal

### Issue: FAVA_TRAIL_DATA_REPO backwards compatibility [HIGH] — FIXED

All three reviewers (Gemini, Codex, Claude) independently flagged that the `FAVA_TRAIL_DATA_REPO` env var was silently dropped, causing existing deployments to fall back to `~/.fava-trail` without warning.

**Fix applied in `src/fava_trails/config.py`:**
- Priority chain: `FAVA_TRAILS_DATA_REPO` > `FAVA_TRAIL_DATA_REPO` (deprecated, emits `logger.warning`) > `FAVA_TRAIL_HOME` (legacy, emits `logger.warning`) > default `~/.fava-trail`
- New test `test_fava_home_old_env_var_compat` verifies the shim works
- Updated `test_fava_home_default` to also `delenv("FAVA_TRAIL_DATA_REPO", raising=False)` to prevent cross-test pollution
- Updated `test_fava_home_new_env_takes_precedence` to test full three-way priority

**Deferred to Phase 3 (external references — correct scope):**
- README MCP registration examples: `fava-trail-server` → `fava-trails-server`
- README architecture diagram: `fava_trail/` → `fava_trails/`
- `server.py` scope examples: `mw/eng/fava-trail` → `mw/eng/fava-trails`

All reviewers approved for phase advancement. 128 tests pass (127 pre-existing + 1 new compat test).

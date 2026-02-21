# Plan 5: Pull Daemon

**Status:** not started
**Spec:** `codev/specs/5-pull-daemon.md`

---

## Phase 5.1: Daemon Implementation

**Files created:**
- `src/fava_trail/daemon/__init__.py`
- `src/fava_trail/daemon/pull_daemon.py` — async loop with fetch/rebase/rollback

**Key patterns:**
- `PullDaemon(jj_backend, interval)` — takes shared backend, configurable interval
- `start()` / `stop()` — lifecycle management
- Conflict detection → `jj op restore` → log warning
- Graceful shutdown on SIGTERM/SIGINT

**Done criteria:**
- Daemon starts and stops cleanly
- Fetches from remote at configured interval
- Conflict triggers automatic rollback

## Phase 5.2: Server Integration

**Files modified:**
- `src/fava_trail/server.py` — start daemon after `_init_server()`, stop on shutdown
- `src/fava_trail/config.py` — load daemon config

**Done criteria:**
- Daemon starts automatically with server (if `enabled: true`)
- Daemon stops when server shuts down
- Daemon disabled by config → no background loop

## Phase 5.3: Tests

**Tests:**
- Daemon starts and stops without errors
- Daemon handles fetch failure gracefully (log, continue)
- Conflict after rebase → rollback verified

**Done criteria:**
- All new tests pass
- All existing tests pass

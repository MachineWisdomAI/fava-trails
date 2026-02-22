# Spec 5: Pull Daemon

**Status:** not started
**Epic:** 0002a-desktop-pipeline
**Source:** `codev/spir-v2.md` Phase 2 (Pull Daemon section)
**Prerequisites:** Spec 4 (Desktop Bridge)

---

## Problem Statement

Multi-agent sync currently requires manual `sync` calls. Without a background rebase loop, agents work on stale state — Code doesn't see Desktop's writes until someone explicitly syncs.

## Proposed Solution

A background async loop (`src/fava_trail/daemon/pull_daemon.py`) that periodically runs `fetch_and_rebase()` on the monorepo. One daemon instance for the entire monorepo (not per-trail).

### Safety

On conflict after rebase, immediately restores pre-rebase state via `jj op restore` and notifies the agent:

```python
while running:
    try:
        result = jj_backend.fetch_and_rebase()
        if result.has_conflicts:
            log.warning("Conflict after rebase, restoring pre-rebase state")
            jj_backend.op_restore(result.pre_rebase_op_id)
            notify_agent("conflict", result.conflict_details)
    except Exception as e:
        log.error(f"Pull daemon error: {e}")
    await asyncio.sleep(interval)
```

### Configuration

```yaml
# config.yaml
pull_daemon:
  enabled: true
  interval_seconds: 30
```

## Done Criteria

- Daemon runs in background, periodically fetches and rebases
- Conflict after rebase triggers automatic rollback + warning
- Daemon shutdown is clean (SIGTERM/SIGINT handling)
- Daemon errors logged, never crash the server
- One daemon for monorepo (not per-trail)

## Out of Scope

- Real-time push notifications (future)
- Webhook-based sync triggers (future)

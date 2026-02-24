# Spec 5: Pull Daemon

**Status:** not started
**Epic:** 0002a-desktop-pipeline
**Source:** `codev/spir-v2.md` Phase 2 (Pull Daemon section)
**Prerequisites:** Spec 4 (Desktop Bridge)

---

## Problem Statement

Multi-agent sync currently requires manual `sync` calls. Without a background rebase loop, agents work on stale state — Code doesn't see Desktop's writes until someone explicitly syncs.

## Proposed Solution

A background async loop (`src/fava_trails/daemon/pull_daemon.py`) that periodically runs `fetch_and_rebase()` on the monorepo. One daemon instance for the entire monorepo (not per-trail).

### Concurrency Model

The daemon runs as an `asyncio.Task` created during server startup — **not** a separate thread or process. It shares the server's event loop.

```python
class PullDaemon:
    def __init__(self, jj_backend: JJBackend, interval: int = 30):
        self._jj = jj_backend
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """Start the background pull loop as an asyncio task."""
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        """Cancel the task and wait for clean exit."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self):
        while self._running:
            await self._pull_once()
            await asyncio.sleep(self._interval)

    async def _pull_once(self):
        try:
            async with self._jj.repo_lock:
                result = await self._jj.fetch_and_rebase()
            if result.has_conflicts:
                log.warning("Conflict after rebase, restoring pre-rebase state")
                async with self._jj.repo_lock:
                    await self._jj.op_restore(result.pre_rebase_op_id)
                # Log conflict details — no agent callback needed,
                # conflicts surface via the existing conflicts tool
        except Exception as e:
            log.error(f"Pull daemon error: {e}")
            # Never re-raise — daemon must not crash the server
```

**Key design decisions:**
- `asyncio.create_task`, not `threading.Thread` — the JJ backend is already async (`async def fetch_and_rebase() -> RebaseResult`) so no thread needed
- `_pull_once()` catches all exceptions — daemon errors are logged, never propagated
- `stop()` uses `task.cancel()` + suppress `CancelledError` — standard asyncio cleanup
- **Must acquire `repo_lock`** — `fetch_and_rebase()` does NOT hold the shared `repo_lock` internally, but `try_push()` does. Without the lock, the daemon's fetch/rebase can race with auto-push after write operations. The daemon acquires `self._jj.repo_lock` around both `fetch_and_rebase()` and `op_restore()` calls.
- **Signal handling:** The daemon runs as an `asyncio.Task` — when the server receives SIGTERM/SIGINT, the event loop's shutdown sequence cancels all tasks. The `stop()` method's `task.cancel()` + `CancelledError` suppression handles this cleanly. No separate signal handler is needed.

### Server Integration

The daemon starts after `_init_server()` in the server's `main()`, and stops when the `stdio_server()` context manager exits:

```python
async def main():
    await _init_server()
    daemon = None
    if config.pull_daemon.enabled:
        daemon = PullDaemon(jj_backend, config.pull_daemon.interval_seconds)
        await daemon.start()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, ...)
    finally:
        if daemon:
            await daemon.stop()
```

### Configuration

```yaml
# config.yaml
pull_daemon:
  enabled: true
  interval_seconds: 30
```

Default: `enabled: false` (opt-in). Builders and Desktop sessions enable it; the server doesn't sync by default.

## Done Criteria

- Daemon runs in background, periodically fetches and rebases
- Conflict after rebase triggers automatic rollback + warning
- Daemon shutdown is clean (SIGTERM/SIGINT handling)
- Daemon errors logged, never crash the server
- One daemon for monorepo (not per-trail)

## Out of Scope

- Real-time push notifications (future)
- Webhook-based sync triggers (future)

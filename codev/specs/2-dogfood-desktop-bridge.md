# Spec 2: Dogfood + Desktop Bridge

**Status:** not started
**Source:** `codev/spir-v2.md` Phase 2
**Prerequisites:** Spec 1b (storage substrate amendments) — integrated

---

## Problem Statement

FAVA Trail's 14 MCP tools are functional (Phase 1 + 1b), but three infrastructure gaps prevent real-world dogfooding:

1. **No Desktop bridge** — Claude Desktop on Windows cannot connect to the MCP server running under WSL2 without a wrapper script
2. **No Pull Daemon** — Multi-agent sync requires a background rebase loop; without it, agents work on stale state until manual `sync` calls
3. **No evaluation framework** — No automated tests for crash recovery (SIGKILL resilience) or recall accuracy (relevance auditing)
4. **No migration path** — wise-agents-toolkit's flat-file memory (`memory/shared/decisions.md`, `memory/shared/gotchas.md`, `memory/branches/`) has no automated migration to FAVA Trail namespaces

## Proposed Solution

Build the infrastructure layer that enables daily dogfooding across Claude Code and Claude Desktop:

### Desktop Bridge (`scripts/mcp-fava-wrapper.sh`)

A `wsl.exe` wrapper script that Claude Desktop's MCP configuration on Windows can invoke. Routes stdio MCP traffic from native Windows to the WSL2 `fava-trail-server` process.

### Pull Daemon (`src/fava_trail/daemon/pull_daemon.py`)

A background async loop that periodically runs `fetch_and_rebase()` on the monorepo. One daemon instance for the entire monorepo (not per-trail). On conflict after rebase, immediately restores pre-rebase state via `jj op restore` and notifies the agent.

Safety pattern:
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

### Evaluation Scripts

- `eval/crash_recovery.py` — SIGKILL chaos test: kill agent process mid-execution, initialize new session, assert watchdog uses `jj op restore` to recover exact state without data loss
- `eval/recall_relevance.py` — Sample-based audit of recall accuracy against known thought corpus

### Toolkit Migration Adapter (`src/fava_trail/adapters/toolkit.py`)

Migration helper that reads wise-agents-toolkit flat-file memory and converts to FAVA Trail thoughts:

| Source | Target |
|--------|--------|
| `memory/shared/decisions.md` | `decisions/` namespace, `validation_status: "approved"` |
| `memory/shared/gotchas.md` | `observations/` namespace, `metadata.tags: ["gotcha"]` |
| `memory/branches/<branch>/status.md` | `drafts/` namespace, `metadata.branch: "<branch>"` |

### `recall` Enhancements

- `applicable_preferences` field — Every `recall` query automatically includes matching preferences from `preferences/` namespace. Agents don't opt in; relevant user corrections are always surfaced.
- `include_relationships=True` — 1-hop traversal: return immediate `DEPENDS_ON` and `REVISED_BY` targets. Cheap (file reads by ULID), no graph database needed.

## Done Criteria

- Both Claude Code and Desktop configured with fava-trail MCP
- Both share `fava-trail-data/trails/` via monorepo
- Pull Daemon rebases safely, aborts on conflict (one daemon for monorepo)
- Push after write delivers remote backup — GitHub shows trail data
- `learn_preference` stores corrections in preference namespace
- `recall` with `include_relationships=True` returns 1-hop related thoughts
- `recall` returns `applicable_preferences` field on every query
- `eval/crash_recovery.py` SIGKILL chaos test confirms zero data loss and `jj op restore` recovery
- `eval/recall_relevance.py` produces accuracy metrics for known corpus
- Toolkit migration adapter converts flat-file memory to FAVA Trail thoughts
- Desktop bridge wrapper enables Claude Desktop on Windows to connect via WSL2

## Out of Scope

- Semantic search / vector indexing (Phase 3)
- Trust Gate automated reviewer (Phase 3)
- codev Porch integration (Phase 4)
- OpenClaw adapter (Phase 5)
- PyPI publishing
- CI/CD pipelines

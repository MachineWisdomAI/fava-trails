# Spec 11: OpenClaw Memory Plugin

**Status:** not started
**Epic:** 0005a-adoption
**Source:** Claude Desktop research + consensus (GPT-5.2 FOR 7/10, Gemini 3 Pro AGAINST 8/10)
**Prerequisites:** Spec 2 (Hierarchical Scoping — complete), Spec 7 (Semantic Recall), Spec 12 (Rebrand)
**Supersedes:** Previous Spec 11 (OpenClaw Memory Driver — thin adapter stub)

---

## Review History

| Reviewer | Stance | Score | Key Feedback |
|----------|--------|-------|--------------|
| GPT-5.2 | FOR | 7/10 | Architecture correct. Add: token budget for prependContext, explicit sync policy, memory_sync tool, write guardrails, memory_get virtual path scheme, idempotency for auto-capture retries, merge precedence for multi-scope reads. |
| Gemini 3 Pro | AGAINST | 8/10 | Subprocess fragility, context pollution via unbounded auto-recall, hidden LLM cost at agent_end, argues for standalone MCP sidecar over plugin wrapper. |
| Claude Desktop (synthesis) | — | 7.5/10 | Plugin path is correct (matches Mem0/Supermemory pattern, required for memory slot + lifecycle hooks). Gemini's sidecar alternative loses the exclusive slot and transparent auto-recall. Adopted: token budget, auto-capture opt-in, installation requirements, subprocess supervision, concurrency docs. Rejected: native MCP instead of plugin (loses slot + hooks). |

---

## Problem Statement

OpenClaw's memory is flat Markdown files (`MEMORY.md` + daily `memory/YYYY-MM-DD.md` logs) with hybrid BM25+vector search over SQLite. This architecture has three structural gaps that FAVA Trail addresses:

1. **No versioning.** Memories are append-only daily logs. No diff, rollback, supersession, or audit trail. When an agent captures a wrong fact, the only remedy is manual file editing.
2. **No hierarchy.** The `memory/` directory is flat and date-keyed. No project scoping, no topic organization, no way to give agent A access to agent B's learnings about a shared codebase without giving it everything.
3. **No cross-agent memory.** Each OpenClaw agent is fully isolated — own workspace, own memory index, own `MEMORY.md`. Agents communicate via `sessions_send` messages, not shared state. A researcher agent's findings are invisible to a coder agent unless explicitly forwarded in-session.

The community is already building around these gaps: Mem0, Supermemory, and Cognee all ship OpenClaw memory plugins. GitHub issue #13676 requests first-class project scoping. FAVA Trail enters this space with a differentiated architecture — versioned monorepo with hierarchical directory-path addressing — that none of the existing alternatives provide.

## Proposed Solution

An **OpenClaw Plugin** (TypeScript, distributed via npm) that claims the `plugins.slots.memory` slot and bridges to FAVA Trail's MCP server over stdio transport. The plugin presents an OpenClaw-native API externally while using MCP as internal plumbing.

This is a Plugin, not a Skill. Skills are Markdown files injected into the system prompt — they cannot register tools, modify the memory backend, or hook lifecycle events. The plugin ships a bundled `SKILL.md` via `openclaw.plugin.json` to teach the agent about FAVA-specific capabilities beyond the standard memory interface.

### Why Plugin + MCP Bridge (not native MCP client)

OpenClaw has evolving native MCP client support (issues #4834, #8188, #13248), but the plugin path is superior for a memory backend because:

- **Exclusive slot assignment.** Only one memory plugin can be active. Claiming the slot guarantees FAVA Trail handles all memory operations. A native MCP connection provides tools but cannot claim the memory slot.
- **Lifecycle hooks.** `before_agent_start` and `agent_end` enable transparent auto-recall and auto-capture without requiring the agent to call tools explicitly. Native MCP has no equivalent — the agent would need to remember to call `recall` manually every session, which is the failure mode this integration solves.
- **CLI/slash commands.** The plugin can register `/memory-history`, `/memory-scope` etc. for user-facing operations.
- **Proven pattern.** Supermemory and Mem0 both ship exactly this way — npm plugin claiming the memory slot.

The plugin spawns the FAVA Trail MCP server as a subprocess via `api.registerService()` and communicates over stdio. This decouples the TypeScript plugin surface from the Python MCP server implementation, preserving FAVA Trail's reusability across Claude Code, Claude Desktop, and any other MCP client.

### Why Not a Standalone Sidecar

A sidecar architecture (FAVA Trail running independently, OpenClaw connecting via native MCP) is architecturally cleaner for multi-client scenarios. However, it cannot claim the memory slot, cannot hook lifecycle events, and requires the agent to drive all memory operations explicitly. The plugin path is correct for **replacing** the memory backend; a sidecar is correct for **augmenting** it. This spec targets replacement.

Users who want both can run FAVA Trail as a sidecar for other clients (IDE, CLI) while the OpenClaw plugin manages the OpenClaw-specific integration surface. The underlying trail repository is the same.

---

## Prerequisites and Installation

The npm package depends on external tooling that must be present on the host:

| Dependency | Required | Install |
|-----------|----------|---------|
| `fava-trail` CLI | Yes | `uvx install fava-trail` or `pipx install fava-trail` |
| JJ (Jujutsu) | Yes | Platform binary — `brew install jj`, `cargo install jj-cli`, or pre-built release |
| Git | Yes | System package manager |
| Python >= 3.11 | Yes (for fava-trail) | System or managed via `uv` |

The npm `postinstall` script verifies all prerequisites and prints actionable error messages:

```typescript
// postinstall.ts
const checks = [
  { cmd: "fava-trail --version", name: "fava-trail", install: "uvx install fava-trail" },
  { cmd: "jj --version", name: "jj", install: "https://jj-vcs.github.io/jj/latest/install/" },
  { cmd: "git --version", name: "git", install: "https://git-scm.com/downloads" },
];
// For each: spawn, check exit code, print:
// "[OK] fava-trail v0.5.0" or "[FAIL] fava-trail not found — install: uvx install fava-trail"
```

This is an explicit trade-off: FAVA Trail is not "npm install and go." The Python + JJ dependency chain is the cost of versioned, VCS-backed memory. The `postinstall` check makes the requirement visible immediately rather than failing silently at runtime.

---

## Architecture

```
OpenClaw Gateway
├── Agent Workspace (per-agent)
│   ├── MEMORY.md          ← replaced by FAVA Trail reads
│   ├── memory/            ← replaced by FAVA Trail writes
│   └── skills/
│       └── fava-trail/    ← bundled SKILL.md (teaches agent FAVA capabilities)
│
├── Plugin: openclaw-fava-trail (claims plugins.slots.memory)
│   ├── lifecycle hooks
│   │   ├── before_agent_start → recall scoped thoughts → prependContext (bounded)
│   │   ├── before_compaction → extract & save facts before context flush
│   │   └── agent_end → extract facts → save_thought (opt-in)
│   ├── registered tools
│   │   ├── memory_search    → recall (standard OpenClaw interface)
│   │   ├── memory_store     → save_thought (write-guarded to configured scope)
│   │   ├── memory_get       → get_thought (by ULID, not file path)
│   │   ├── memory_history   → jj log over scope path (FAVA-specific)
│   │   ├── memory_scope     → list_scopes (FAVA-specific)
│   │   ├── memory_supersede → supersede with audit trail (FAVA-specific)
│   │   ├── memory_conflicts → cross-agent contradictions (FAVA-specific)
│   │   └── memory_sync      → Git push/pull (FAVA-specific)
│   ├── subprocess supervisor
│   │   └── health check, auto-restart, graceful degradation
│   └── MCP bridge (stdio subprocess)
│       └── fava-trail serve --transport stdio
│
└── FAVA Trail Monorepo (~/.fava-trail/trails/)
    ├── agents/openclaw/researcher/     ← agent A scope
    ├── agents/openclaw/coder/          ← agent B scope
    ├── agents/openclaw/                ← shared agent scope
    └── mw/eng/                         ← org-wide (if desired)
```

### MCP Subprocess Supervision

The child process is the single point of failure for all memory operations. The plugin implements robust lifecycle management:

- **Startup:** Spawn `fava-trail serve --transport stdio` via `api.registerService()`. Send a health-check ping (`list_trails`). If no response within 5s, retry up to 3 times with exponential backoff (1s, 2s, 4s).
- **Runtime:** Periodic health-check ping every 60s. If the process dies, auto-restart with the same backoff strategy. Log all restarts.
- **Graceful degradation:** If the subprocess is unavailable after all retries, memory tools return empty results and log a warning rather than crashing the agent. The agent continues working without memory — degraded but functional.
- **Shutdown:** On Gateway shutdown, send SIGTERM to the subprocess and wait up to 5s for clean exit before SIGKILL.
- **Error boundary:** All MCP calls are wrapped in try/catch with structured error logging. JJ lock contention, filesystem errors, and MCP protocol failures surface as typed error objects, not opaque timeouts.

### Concurrency Model

FAVA Trail handles concurrent access through two mechanisms:

1. **Per-trail `asyncio.Lock`** in the MCP server serializes all write operations to a given trail. Two agents writing to `agents/openclaw/researcher` and `agents/openclaw/coder` respectively operate on different trails with independent locks — no contention.
2. **Per-agent JJ changes.** Each write creates its own JJ change (commit), and JJ's first-class conflict model captures concurrent modifications as algebraic conflicts rather than failing. The `conflicts()` tool surfaces these for resolution.

Two agents writing to the **same** trail (e.g., both writing to `agents/openclaw`) are serialized by the trail mutex. This is safe but adds latency under high write concurrency. For multi-agent setups, assign each agent its own write scope and share via `readScopes`.

### Scope Mapping

Each OpenClaw agent maps to a FAVA Trail scope via plugin config:

```json
{
  "plugins": {
    "entries": {
      "openclaw-fava-trail": {
        "enabled": true,
        "config": {
          "trailHome": "~/.fava-trail",
          "agents": {
            "researcher": {
              "scope": "agents/openclaw/researcher",
              "readScopes": ["agents/openclaw", "mw"]
            },
            "coder": {
              "scope": "agents/openclaw/coder",
              "readScopes": ["agents/openclaw", "mw/eng"]
            }
          },
          "defaultScope": "agents/openclaw",
          "autoRecall": true,
          "autoCapture": false,
          "maxRecallResults": 10,
          "maxRecallTokens": 2000,
          "captureMinConfidence": 0.6,
          "syncOnEnd": false
        }
      }
    },
    "slots": { "memory": "openclaw-fava-trail" }
  }
}
```

| Config Key | Default | Purpose |
|-----------|---------|---------|
| `scope` | (required per agent) | `trail_name` for writes. Each agent writes exclusively to its own scope. |
| `readScopes` | `[]` | Additional `trail_names` for `recall`. Supports Spec 2 globs: `"agents/openclaw/*"`, `"mw/eng/**"`. |
| `defaultScope` | (required) | Fallback scope if an agent ID has no explicit mapping. |
| `autoRecall` | `true` | Inject relevant memories at session start via `prependContext`. |
| `autoCapture` | **`false`** | Extract and save session facts at `agent_end`. **Opt-in.** Requires an LLM call that adds ~2-5s latency and ~500 tokens per session end. |
| `maxRecallResults` | `10` | Maximum thoughts returned by auto-recall before token budget is applied. |
| `maxRecallTokens` | `2000` | Hard ceiling on total tokens injected by `prependContext`. Prevents context window pollution. |
| `captureMinConfidence` | `0.6` | Minimum confidence for auto-captured facts to be persisted. |
| `syncOnEnd` | `false` | Run Git push/pull after auto-capture on `agent_end`. Enable for multi-machine setups. |

**Write guardrails:** The plugin validates that all `save_thought` calls (from tools and lifecycle hooks) use the agent's configured `scope`. Writes to scopes outside the configured path are rejected with an error. This prevents accidental cross-scope pollution from agent tool misuse.

This maps directly to Spec 2's design: the plugin reads scope from its config (client-side responsibility), passes `trail_name` explicitly on every MCP call (server is a database), and uses `trail_names` for multi-scope reads.

---

## Interface Mapping

### Standard OpenClaw Memory Interface

These tools replace the builtin `memory_search` and `memory_get` that OpenClaw's default `MemoryIndexManager` provides:

| OpenClaw Tool | FAVA Trail MCP Call | Notes |
|--------------|---------------------|-------|
| `memory_search(query, maxResults?, minScore?)` | `recall(query, trail_name, trail_names, limit)` | `minScore` maps to confidence filter. Results include `source_trail` metadata. |
| `memory_get(thoughtId)` | `get_thought(thought_id)` | **Deliberate divergence from builtin:** accepts ULID thought IDs, not file paths with line ranges. FAVA Trail thoughts are versioned objects, not files. The SKILL.md documents this. |
| `memory_store(content)` | `save_thought(content, trail_name, source_type, agent_id)` | `source_type` inferred from context: `observation` for auto-capture, `user_input` for explicit stores. Write-guarded to configured scope. |

**Why `memory_get` diverges from builtin:** OpenClaw's builtin `memory_get(path, startLine?, endLine?)` assumes a filesystem with line-addressable files. FAVA Trail thoughts are Markdown documents with YAML frontmatter identified by ULIDs. Maintaining a path-to-ULID compatibility index adds persistent state and maintenance burden for no user value — the agent already receives thought IDs from `memory_search` results. This is a clean break documented in the SKILL.md.

### FAVA-Specific Tools (beyond standard interface)

Registered as additional tools and documented in the bundled SKILL.md:

| Tool | MCP Call | Purpose |
|------|----------|---------|
| `memory_history(query?, scope?)` | `jj log` over scope path | Version timeline — what changed, when, by which agent. No equivalent in OpenClaw's builtin memory. |
| `memory_scope(prefix?)` | `list_scopes(prefix)` | Navigate the hierarchy. Discover what scopes exist, thought counts, last write timestamps. |
| `memory_supersede(thoughtId, content, reason)` | `supersede(thought_id, content, reason)` | Correct a previous memory with full audit trail. Original preserved, new version linked. |
| `memory_conflicts()` | `conflicts()` | Surface cross-agent contradictions after sync. Structured summaries, not raw VCS output. |
| `memory_sync()` | `sync()` | Git push/pull to synchronize with remote. Manual invocation by default. Optionally automated via `syncOnEnd` config. |

### Lifecycle Hooks

**`before_agent_start`** — transparent auto-recall with token budget:

```typescript
api.on("before_agent_start", async (ctx) => {
  if (!config.autoRecall) return {};

  const agentConfig = config.agents[ctx.agentId]
    ?? { scope: config.defaultScope, readScopes: [] };

  const thoughts = await mcpClient.recall({
    query: ctx.sessionContext,
    trail_name: agentConfig.scope,
    trail_names: agentConfig.readScopes,
    limit: config.maxRecallResults,
  });

  if (thoughts.length === 0) return {};

  // Merge precedence: confidence → recency → scope specificity (narrower wins)
  const ranked = thoughts.sort((a, b) => {
    if (b.confidence !== a.confidence) return b.confidence - a.confidence;
    if (b.created_at !== a.created_at)
      return b.created_at.localeCompare(a.created_at);
    return b.source_trail.length - a.source_trail.length;
  });

  // Enforce token budget — truncate to maxRecallTokens
  let tokenCount = 0;
  const budgeted: typeof ranked = [];
  for (const t of ranked) {
    const estimate = Math.ceil(t.content.length / 4); // rough char→token
    if (tokenCount + estimate > config.maxRecallTokens) break;
    budgeted.push(t);
    tokenCount += estimate;
  }

  const formatted = budgeted
    .map(t => `[${t.source_trail}] (${t.source_type}, ${t.confidence}) ${t.content}`)
    .join("\n\n");

  return { prependContext: `## Relevant memories\n\n${formatted}` };
});
```

**`before_compaction`** — save memories before context window flush:

```typescript
api.on("before_compaction", async (ctx) => {
  // Mirrors OpenClaw's pre-compaction memory flush pattern.
  // Always runs regardless of autoCapture — compaction is destructive.
  const facts = await extractSessionFacts(ctx.messages, { urgency: "compaction" });

  for (const fact of facts) {
    if (fact.confidence < config.captureMinConfidence) continue;

    // Idempotency: hash-based dedup prevents duplicates on retry
    const contentHash = sha256(fact.content);
    const existing = await mcpClient.recall({
      query: fact.content, trail_name: agentConfig.scope, limit: 1
    });
    if (existing.length > 0 && sha256(existing[0].content) === contentHash) continue;

    await mcpClient.save_thought({
      content: fact.content,
      trail_name: agentConfig.scope,
      source_type: "observation",
      agent_id: `openclaw-${ctx.agentId}`,
      confidence: fact.confidence,
      metadata: { tags: ["auto-capture", "compaction", "openclaw"] },
    });
  }
});
```

**`agent_end`** — opt-in auto-capture of session learnings:

```typescript
api.on("agent_end", async (ctx) => {
  // OPT-IN: autoCapture defaults to false.
  // Cost: ~500 tokens + ~2-5s latency using OpenClaw's configured model.
  if (!config.autoCapture) return;

  const facts = await extractSessionFacts(ctx.messages);

  for (const fact of facts) {
    if (fact.confidence < config.captureMinConfidence) continue;

    // Idempotency: hash-based dedup
    const contentHash = sha256(fact.content);
    const existing = await mcpClient.recall({
      query: fact.content, trail_name: agentConfig.scope, limit: 1
    });
    if (existing.length > 0 && sha256(existing[0].content) === contentHash) continue;

    await mcpClient.save_thought({
      content: fact.content,
      trail_name: agentConfig.scope,
      source_type: "observation",
      agent_id: `openclaw-${ctx.agentId}`,
      confidence: fact.confidence,
      metadata: { tags: ["auto-capture", "openclaw"] },
    });
  }

  // Optional: sync to remote after capture
  if (config.syncOnEnd) {
    await mcpClient.sync({ trail_name: agentConfig.scope });
  }
});
```

**Note on `before_compaction`:** This lifecycle event may not be a public plugin API in current OpenClaw versions. If unavailable, the plugin falls back to `agent_end` only. The pre-compaction flush is a significant value differentiator; if the hook doesn't exist, file an upstream feature request.

---

## Distribution

### npm Package: `openclaw-fava-trail`

The plugin itself. TypeScript module loaded by OpenClaw Gateway via `jiti`.

Contains:
- Plugin entry point implementing `OpenClawPluginApi`
- MCP client bridge with subprocess supervisor
- Session fact extraction logic (uses OpenClaw's configured model)
- `postinstall` script verifying prerequisites

### Bundled Skill via `openclaw.plugin.json`

```json
{
  "name": "openclaw-fava-trail",
  "version": "0.1.0",
  "description": "Versioned, hierarchically scoped agent memory backed by FAVA Trail",
  "kind": "memory",
  "skills": ["skills/fava-trail"]
}
```

The `skills/fava-trail/SKILL.md` teaches the agent:
- When to use `memory_history` (investigating how a decision evolved)
- When to use `memory_scope` (understanding what knowledge exists at each level)
- When to use `memory_supersede` (correcting a previous memory vs. adding a new one)
- When to use `memory_sync` (after making changes you want shared across machines)
- That memories are scoped and versioned (the agent should think about what scope to read from)
- That `memory_search` results include `source_trail` indicating which scope each result came from
- That `memory_get` accepts thought IDs (ULIDs), not file paths — IDs come from `memory_search` results

```yaml
---
name: fava-trail-memory
description: Versioned, hierarchically scoped memory with audit trail
version: 0.1.0
metadata:
  openclaw:
    emoji: "🧠"
    requires:
      bins: ["jj", "fava-trail"]
      config: ["plugins.entries.openclaw-fava-trail"]
---
```

### ClawHub Listing

Published via `clawhub publish` with metadata pointing to the npm package. Users discover it on ClawHub, install via npm, configure in `openclaw.json`.

---

## What This Gives OpenClaw That Nothing Else Does

**vs. Builtin memory:** Version history, rollback, supersession with audit trail, hierarchical scoping, cross-agent memory sharing.

**vs. Mem0/Supermemory:** Both are cloud-hosted vector stores. No versioning, no hierarchy, no offline operation, no self-hosted option that doesn't depend on external APIs. FAVA Trail runs entirely local with Git remote for optional sync.

**vs. Cognee:** Knowledge graph approach — powerful but heavyweight. Requires graph database infrastructure. FAVA Trail is files in a directory with a VCS layer.

**vs. QMD (OpenClaw experimental):** QMD adds allow/deny scope rules but no hierarchy, no versioning, no cross-agent sharing. It improves query quality within the existing flat-file paradigm.

The unique positioning: **the only OpenClaw memory backend that gives you `jj log` over your agent's institutional memory, hierarchical scoping so the right context surfaces at the right level, and a Git remote so agents on different machines share the same versioned store.**

---

## Done Criteria

- [ ] npm package `openclaw-fava-trail` installable
- [ ] `postinstall` verifies fava-trail, jj, git — prints clear errors if missing
- [ ] Plugin claims `plugins.slots.memory` successfully
- [ ] MCP subprocess spawns with health check and stays alive for Gateway lifetime
- [ ] Subprocess auto-restarts on crash (max 3 retries, exponential backoff)
- [ ] Graceful degradation: memory tools return empty results if subprocess unavailable
- [ ] `memory_search` returns results from configured `scope` + `readScopes`
- [ ] `memory_search` results ranked by confidence -> recency -> scope specificity
- [ ] `memory_store` writes to agent's configured `scope` only (write guardrail rejects others)
- [ ] `memory_get` accepts ULID thought IDs and returns full thought content
- [ ] `memory_sync` triggers Git push/pull on configured trail
- [ ] `before_agent_start` hook injects memories via `prependContext` within `maxRecallTokens` budget
- [ ] `agent_end` hook captures session facts when `autoCapture: true` (opt-in)
- [ ] Auto-capture is idempotent — hash-based dedup prevents duplicate thoughts on retry
- [ ] `memory_history` returns version timeline for a scope
- [ ] `memory_scope` lists available scopes with stats
- [ ] `memory_supersede` creates linked replacement with audit trail
- [ ] `memory_conflicts` surfaces contradictions in structured format
- [ ] Multi-agent: agent A writes to scope A, agent B reads from scope A via `readScopes`
- [ ] Write guardrail: agent cannot write outside its configured scope
- [ ] Bundled SKILL.md teaches agent about all tools including ULID-based `memory_get`
- [ ] `openclaw.plugin.json` valid and loadable
- [ ] ClawHub listing published

## Out of Scope

- Modifying OpenClaw core or its plugin SDK
- Replacing OpenClaw's embedding pipeline (FAVA Trail uses its own recall; if semantic recall via Spec 7 is available, the plugin uses it; otherwise falls back to keyword matching)
- OpenClaw Gateway multi-tenancy or auth (FAVA Trail scope handles isolation)
- Real-time sync between OpenClaw agents (Git push/pull is the sync mechanism, not live pub/sub)
- Migration from existing OpenClaw `memory/` directory to FAVA Trail (users start fresh or manually import)
- Hybrid memory (local vector + FAVA Trail simultaneously) — the exclusive memory slot precludes this by design; users who want both should run FAVA Trail as a sidecar for the secondary use case

## Resolved Questions

1. **~~Path-to-ULID index persistence~~** -> Resolved: drop file/line semantics entirely. `memory_get` accepts ULIDs. No compatibility index needed. Clean break documented in SKILL.md.
2. **~~Fact extraction model~~** -> Resolved: use OpenClaw's configured model. Simpler (no separate API key), and the cost is visible in the user's existing token tracking. Auto-capture is opt-in so users control whether this cost is incurred.

## Open Questions

1. **Pre-compaction hook availability.** The `before_compaction` lifecycle event may not be a public plugin API yet. If not, pre-compaction flush is unavailable and auto-capture only fires on `agent_end`. File an upstream feature request if needed. Compaction-triggered memory save is a significant value differentiator — worth pushing for.

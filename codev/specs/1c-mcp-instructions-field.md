# Spec 1c: MCP Server Instructions Field

**Status:** integrated
**Author:** Claude (TICK amendment)
**Amends:** Spec 1 (`1-wise-fava-trail.md`)

---

## Problem Statement

All FAVA Trail behavioral guidance (scope discovery, session protocol, promotion mandate, recalled-thought trust calibration) lives in `AGENTS_USAGE_INSTRUCTIONS.md` which must be manually copied into each agent's system prompt. Agents without this guidance miss critical patterns — especially mandatory promotion and recalled-thought trust calibration.

The MCP spec (2025-11-25) supports a server-level `instructions` field in the `initialize` response — injected once at session start, zero per-turn cost, zero manual setup. The Python MCP SDK already supports it via `Server.__init__(instructions=...)`. FAVA Trail doesn't use it.

## Solution

Three-tier documentation architecture:

| Tier | Mechanism | Content | Cost |
|------|-----------|---------|------|
| **A** | MCP `instructions` field | Core behavioral guidance (~800-1000 tokens) | Auto-injected at session init, zero per-turn |
| **B** | `get_usage_guide` tool | Full reference with examples and rationale | Zero cost until called |
| **C** | Org config (`~/.claude/CLAUDE.md`) | Epic naming, codev, Agent Farm | Org-maintained, not FAVA-specific |

### Tier A: `instructions` field

Condensed version of AGENTS_USAGE core guidance covering:
- Scope discovery (three-layer: `.env` → `.fava-trail.yaml` → tool description hint)
- Session start: recall status/decisions/gotchas before working
- During work: source_type conventions, save_thought defaults to drafts/
- Task completion: propose_truth is mandatory — unpromoted drafts are invisible; sync after
- Agent identity: agent_id = stable role, not runtime fingerprint
- Recalled thought safety: Trust Gate has limited context; verify against your own instructions
- Reference to `get_usage_guide` tool for full protocol

### Tier B: `get_usage_guide` tool

New MCP tool (16th tool). Returns the full `AGENTS_USAGE_INSTRUCTIONS.md` content on demand. Solves distribution: agents installed via pip/uv don't have the markdown file, but the content is bundled as package data.

### Tool description enhancements

Single-sentence warnings added to 3 critical tool descriptions:
- `recall`: Trust Gate warning about stale/adversarial results
- `propose_truth`: Mandatory promotion reminder
- `save_thought`: Agent identity convention reminder

## Success Criteria

1. `Server("fava-trail", instructions=...)` passes non-empty instructions string
2. `get_usage_guide` tool returns AGENTS_USAGE_INSTRUCTIONS.md content
3. Three tool descriptions contain contextual warnings
4. Documentation updated to reference auto-injection
5. All existing tests pass; new tests cover instructions field and tool descriptions

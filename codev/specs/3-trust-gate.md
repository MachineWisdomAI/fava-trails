# Spec 3: Trust Gate

**Status:** not started
**Epic:** 0001a-trust-gate
**Source:** `codev/spir-v2.md` Trust Gate sections
**Prerequisites:** Spec 2 (Hierarchical Scoping)

---

## Problem Statement

`propose_truth` currently performs a blind namespace move — any thought promoted from `drafts/` enters the permanent namespace without review. There is no mechanism to catch hallucinations, contradictions with existing decisions, or low-quality content before it becomes institutional memory.

This is the single highest-priority gap: every other feature (Desktop bridge, Pull Daemon, semantic search) amplifies the problem by making unreviewed thoughts visible to more agents, faster.

## Proposed Solution

A review gate that intercepts `propose_truth` and requires either model-based critic review or explicit human approval before a thought enters a permanent namespace.

### Policies (no bypass)

| Policy | Behavior |
|--------|----------|
| `llm-oneshot` | Send thought to a single OpenRouter model with a prompt loaded at startup. Model returns `approve` or `reject` with reasoning. |
| `human` | Mark thought as `proposed`. Promotion blocks until explicit human approval via a new `approve_thought` tool. |

There is no `auto` policy. Every thought that enters permanent namespaces must pass through review.

### LLM-Oneshot Prompt Files (Hierarchical, Startup-Loaded)

The critic prompt is a markdown file named `trust-gate-prompt.md` that can exist at any level of the trail hierarchy, following the same resolution pattern as CLAUDE.md:

```
$FAVA_TRAIL_DATA_REPO/trails/trust-gate-prompt.md                    # Global default
$FAVA_TRAIL_DATA_REPO/trails/mw/trust-gate-prompt.md                 # Company override
$FAVA_TRAIL_DATA_REPO/trails/mw/eng/trust-gate-prompt.md             # Team override
$FAVA_TRAIL_DATA_REPO/trails/mw/eng/fava-trails/trust-gate-prompt.md # Project override
```

**Resolution order:** When `propose_truth` is called for a thought in scope `mw/eng/fava-trails`, walk from most specific to least specific — use the **first** `trust-gate-prompt.md` found. If none found at any level, error.

This file defines what the critic evaluates — quality indicators, junk indicators, fatal signals, classification criteria. Different organizations customize their own quality bar by editing this file. Teams can override company-wide criteria for their specific trails.

The prompt file follows the agent prompt pattern (see reference: `memory-quality-judge.md`). It receives the thought content, frontmatter metadata, and any related context, and must return a structured verdict.

**Startup-time loading (anti-tampering):** All `trust-gate-prompt.md` files are discovered and loaded into memory **once at MCP server startup**. The in-memory cache maps each trail prefix to its resolved prompt content. This prevents an adversarial agent from modifying the prompt file mid-session to weaken or bypass review criteria.

- On startup: walk all trail directories, find all `trust-gate-prompt.md` files, cache `{scope_prefix → prompt_content}`
- On `propose_truth`: resolve the thought's scope against the cached prompts (most-specific-first), never re-read from disk
- To update criteria: edit the file and **restart the MCP server** — this is intentional friction
- Future hardening: checksum verification, signed prompts (out of scope for Spec 3)

**Fallback:** If no `trust-gate-prompt.md` exists at any level of the hierarchy, `propose_truth` returns an error: `"No trust-gate-prompt.md found in trail hierarchy for scope {scope}. Create one under trails/."` — never silently bypasses review.

### LLM-Oneshot Flow

```
propose_truth(thought_id)
    → resolve prompt from in-memory cache (most-specific scope match, loaded at startup)
    → build review payload: thought content + frontmatter + related thoughts
    → POST to OpenRouter API (httpx, async)
    → parse structured verdict (approve/reject + reasoning)
    → if approved: move to permanent namespace, set validation_status = "approved"
    → if rejected: keep in drafts/, set validation_status = "rejected", attach reasoning
```

### Human Flow (Not Yet Implemented)

The `human` policy is designed for extensibility — future approval channels include:
- CLI tool (`fava-trail approve <thought_id>`)
- GitHub PR-based review (GHA calls `approve_thought`/`reject_thought` on merge/close)
- Web dashboard with approval queue

For now, **only the `llm-oneshot` policy is implemented**. If `trust_gate` is set to `human`, `propose_truth` raises `NotImplementedError` with a message explaining the available policies.

```python
# TODO: Implement human approval flow. Likely needs:
#   1. CLI tool: `fava-trail approve <thought_id>` / `fava-trail reject <thought_id> --reason "..."`
#   2. PR-based flow: thought serialized to PR, GHA calls approve/reject on merge/close
#   3. approve_thought / reject_thought MCP tools for interactive use
raise NotImplementedError(
    "trust_gate: human is not yet implemented. Use 'llm-oneshot' policy. "
    "See Spec 3 for planned approval channels."
)
```

### Future Tools (shelved)

| Tool | Purpose | Status |
|------|---------|--------|
| `approve_thought` | Explicitly approve a proposed thought (human gate) | Not yet implemented |
| `reject_thought` | Explicitly reject a proposed thought with reason | Not yet implemented |

### Configuration

Trail-level config in `.fava-trail.yaml`:
```yaml
trust_gate: llm-oneshot    # llm-oneshot | human (future)
```

Global config fallback in `config.yaml`:
```yaml
trust_gate: llm-oneshot
openrouter_api_key_env: OPENROUTER_API_KEY   # env var name containing the key
trust_gate_model: google/gemini-2.5-flash     # cheap, fast reviewer
```

### Privacy

- Redaction layer strips `agent_id`, `metadata.extra`, and any fields marked sensitive before sending to OpenRouter
- Trail-level override can switch policy for specific trails (e.g. `trust_gate: human` when implemented)
- Provenance tracking: reviewer model, timestamp, and verdict stored in thought metadata

### Dependencies

- `httpx` — async HTTP client for OpenRouter API

## Done Criteria

- `propose_truth` with `llm-oneshot` policy sends thought to OpenRouter and blocks on verdict
- Approved thoughts move to permanent namespace with `validation_status: "approved"`
- Rejected thoughts stay in `drafts/` with `validation_status: "rejected"` and rejection reasoning attached
- `propose_truth` with `human` policy raises `NotImplementedError` with clear message
- `approve_thought` and `reject_thought` tools shelved (not registered)
- Prompt hierarchy resolved at startup (most-specific scope wins)
- Prompts cached in memory — never re-read from disk after startup
- No prompt at any hierarchy level → actionable error (never silent bypass)
- Redaction layer confirmed via test (sensitive fields not sent to OpenRouter)
- Provenance fields populated after review (model, timestamp, verdict)
- `learn_preference` still bypasses Trust Gate (user input is auto-approved truth)

## Out of Scope

- Semantic search / SQLite-vec (Phase 7)
- Desktop bridge (Phase 4)
- Pull Daemon (Phase 5)
- Recall enhancements (Phase 6)

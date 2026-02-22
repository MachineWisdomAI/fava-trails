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
| `critic` | Send thought to OpenRouter model with a prompt loaded from the working directory. Model returns `approve` or `reject` with reasoning. |
| `human` | Mark thought as `proposed`. Promotion blocks until explicit human approval via a new `approve_thought` tool. |

There is no `auto` policy. Every thought that enters permanent namespaces must pass through review.

### Critic Prompt File

The critic prompt is a markdown file in the data repo root, loaded at runtime:

```
$FAVA_TRAIL_DATA_REPO/trust-gate-prompt.md
```

This file defines what the critic evaluates — quality indicators, junk indicators, fatal signals, classification criteria. Different organizations customize their own quality bar by editing this file.

The prompt file follows the agent prompt pattern (see reference: `memory-quality-judge.md`). It receives the thought content, frontmatter metadata, and any related context, and must return a structured verdict.

**Fallback:** If the prompt file is missing, `propose_truth` returns an error: `"Trust Gate prompt not found at {path}. Create trust-gate-prompt.md in your data repo."` — never silently bypasses review.

### Critic Flow

```
propose_truth(thought_id)
    → load trust-gate-prompt.md from FAVA_TRAIL_DATA_REPO
    → build review payload: thought content + frontmatter + related thoughts
    → POST to OpenRouter API (httpx, async)
    → parse structured verdict (approve/reject + reasoning)
    → if approved: move to permanent namespace, set validation_status = "approved"
    → if rejected: keep in drafts/, set validation_status = "rejected", attach reasoning
```

### Human Flow

```
propose_truth(thought_id)
    → set validation_status = "proposed"
    → return {status: "pending_approval", thought_id: "..."}
    → (agent or human later calls approve_thought or reject_thought)
```

### New Tools

| Tool | Purpose |
|------|---------|
| `approve_thought` | Explicitly approve a proposed thought (human gate) |
| `reject_thought` | Explicitly reject a proposed thought with reason |

### Configuration

Trail-level config in `.fava-trail.yaml`:
```yaml
trust_gate: critic    # critic | human
```

Global config fallback in `config.yaml`:
```yaml
trust_gate: critic
openrouter_api_key_env: OPENROUTER_API_KEY   # env var name containing the key
trust_gate_model: google/gemini-2.5-flash     # cheap, fast reviewer
```

### Privacy

- Redaction layer strips `agent_id`, `metadata.extra`, and any fields marked sensitive before sending to OpenRouter
- Trail-level override can disable critic for specific trails (`trust_gate: human`)
- Provenance tracking: reviewer model, timestamp, and verdict stored in thought metadata

### Dependencies

- `httpx` — async HTTP client for OpenRouter API

## Done Criteria

- `propose_truth` with `critic` policy sends thought to OpenRouter and blocks on verdict
- Approved thoughts move to permanent namespace with `validation_status: "approved"`
- Rejected thoughts stay in `drafts/` with `validation_status: "rejected"` and rejection reasoning attached
- `propose_truth` with `human` policy sets `validation_status: "proposed"` and returns pending status
- `approve_thought` and `reject_thought` tools work for human gate
- Missing prompt file → actionable error (never silent bypass)
- Redaction layer confirmed via test (sensitive fields not sent to OpenRouter)
- Provenance fields populated after review (model, timestamp, verdict)
- `learn_preference` still bypasses Trust Gate (user input is auto-approved truth)

## Out of Scope

- Semantic search / SQLite-vec (Phase 7)
- Desktop bridge (Phase 4)
- Pull Daemon (Phase 5)
- Recall enhancements (Phase 6)

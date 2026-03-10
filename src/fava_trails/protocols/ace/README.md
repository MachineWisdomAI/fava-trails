# ACE Playbook Hooks (Curator Pattern)

FAVA Trails' reference implementation of the [ACE (Agentic Context Engine)](https://arxiv.org/abs/2510.04618) Curator pattern (Stanford/SambaNova, ICLR 2026). ACE treats agent context as an evolving **playbook** of structured rules that grow and refine through feedback loops.

## Architecture: FAVA Trails as the Curator

FAVA Trails maps to the **Curator role** — the infrastructure that makes the Generator→Reflector→Curator loop safe and observable:

| ACE Role | FAVA Trails Equivalent |
|----------|------------------------|
| Generator | External agent using `recall` MCP tool |
| Reflector | External agent calling `save_thought` + `propose_truth` |
| Curator | These hooks (governance, scoring, telemetry) |
| Playbook bullets | Thoughts in `preferences/` with `ace-playbook` tag |

The external Reflector reads `_SAVE_TELEMETRY` and `_SUPERSEDE_STATS` (or queries via MCP `recall`), analyzes patterns, and proposes new rules via `save_thought` into `drafts/`. Rules pass through the Trust Gate via `propose_truth` before becoming active.

## Quick Start

### Option A: Module Reference (zero-friction, no copying)

Add to the `hooks:` section of your `config.yaml`:

```yaml
# config.yaml (at data repo root)
hooks:
  - module: fava_trails.protocols.ace
    points: [on_startup, on_recall, before_save, after_save, after_propose, after_supersede]
    order: 10
    fail_mode: open
    config:
      playbook_namespace: preferences
```

### Option B: Local Copy (for customization)

```bash
cp -r "$(python -c 'import fava_trails.protocols.ace as p; import os; print(os.path.dirname(p.__file__))')" ./my-hooks/ace/
```

Then in `config.yaml`:
```yaml
hooks:
  - path: ./my-hooks/ace/
    points: [on_startup, on_recall, before_save, after_save, after_propose, after_supersede]
    order: 10
    fail_mode: open
    config:
      playbook_namespace: preferences
```

### Optional Dependencies

None. ACE hooks are pure Python. The external Reflector is a separate agent or process.

## Config Contract

The protocol receives its config as a plain `dict` via `configure()`. It never reads files directly.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `playbook_namespace` | `str` | `"preferences"` | Namespace to load playbook rules from |

## Lifecycle Hooks (6 points)

### `on_startup` — Lazy Cache Warmup

Returns `StartupOk`. The playbook cache warms lazily on the first `on_recall` call.

### `on_recall` — Playbook-Driven Reranking

Applies playbook rules to score and reorder recall results. Rules are lazy-loaded from `preferences/` (or configured namespace) with a 5-minute TTL as a stale-cache backstop.

**Returns:** `RecallSelect` (reorder only — provenance-safe, cannot inject) + `Annotate`.

**Scoring:** ACE-style multiplicative — each matching rule multiplies the base confidence score by its Laplace-smoothed factor. Score is clamped to `[0.5, 2.0]` to prevent runaway ranking.

### `before_save` — Anti-Pattern Guardian + Quality Advisor

Checks cached playbook anti-pattern rules. Adds a brevity-bias advisory for terse decisions (< 80 chars) per ACE research findings.

**Returns:** `Warn` for anti-pattern matches, `Advise` for brevity bias.

### `after_save` — Cache Invalidation + Reflector Telemetry

- Invalidates playbook cache when a thought with `ace-playbook` tag is saved.
- Accumulates save events in `_SAVE_TELEMETRY` for the external Reflector.

> **after_* hooks are at-most-once, best-effort, non-blocking. Correctness must derive from persisted thoughts queried via MCP, not from hook state.**

### `after_propose` — Promotion Cache Invalidation

Invalidates the playbook cache when a rule enters `preferences/` via `propose_truth`. Ensures newly promoted rules are picked up on the next recall without waiting for the TTL.

### `after_supersede` — Correction Telemetry

Records each supersession as structured telemetry for the external Reflector. Invalidates the playbook cache if a playbook rule was superseded.

## Playbook Rule Authoring

Rules live in `preferences/` namespace with the `ace-playbook` tag. Use standard FAVA Trails MCP tools to create and manage them.

### Rule Format

Rules are stored as FAVA Trails thoughts. Fields are read from `metadata.extra`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rule_type` | `str` | `retrieval_priority` | One of: `retrieval_priority`, `confidence_floor`, `staleness`, `anti_pattern` |
| `match` | `dict` | `{}` | Match criteria (AND logic — all must pass) |
| `action` | `dict` | `{}` | Score adjustment: `{"boost": N}` or `{"deprioritize": N}` |
| `weight` | `int` | `0` | Conflict-resolution priority (higher wins) |
| `helpful_count` | `int` | `0` | ACE-style feedback counter (increases boost effect) |
| `harmful_count` | `int` | `0` | ACE-style feedback counter (reduces boost effect) |
| `section` | `str` | `""` | Playbook section label |
| `description` | `str` | `""` | Human-readable description |

### Match Criteria

All criteria use AND logic — all specified conditions must pass:

| Key | Type | Description |
|-----|------|-------------|
| `source_type` | `str` | Must equal `decision`, `observation`, `inference`, `user_input`, or `tool_output` |
| `confidence_lt` | `float` | Thought confidence must be strictly less than this value |
| `tags_include` | `list[str]` | Thought must have ALL listed tags |
| `tags_exclude` | `list[str]` | Thought must have NONE of the listed tags |
| `age_lt_days` | `float` | Thought must have been created within N days |

### Scoring Formula

```
score_multiplier = clamp(action_base * laplace_ratio, 0.5, 2.0)

where:
  laplace_ratio = (helpful_count + 1) / (helpful_count + harmful_count + 2)
  action_base   = action["boost"] or action["deprioritize"] or 1.0
```

`anti_pattern` rules always return `1.0` (neutral) — they signal in `before_save`, not during scoring.

### Creating a Rule via MCP

```python
# Via fava-trails save_thought MCP tool
save_thought(
    trail_name="my-trail",
    content="# Boost Recent Decisions\n\nBoosts decisions made in the last 7 days.",
    source_type="user_input",
    metadata={
        "tags": ["ace-playbook", "retrieval-priority"],
        "extra": {
            "rule_type": "retrieval_priority",
            "match": {"source_type": "decision", "age_lt_days": 7},
            "action": {"boost": 1.5},
            "weight": 10,
            "helpful_count": 0,
            "harmful_count": 0,
            "section": "task_guidance",
            "description": "Recent decisions rank higher than older ones",
        }
    }
)

# Then promote through Trust Gate
propose_truth(trail_name="my-trail", thought_id="<ULID>")
```

## What ACE Adds vs. Flat Storage

| Capability | ACE (flat list) | FAVA Trails ACE Hooks |
|------------|----------------|----------------------|
| Delta updates | ✓ | ✓ (save_thought/supersede) |
| Feedback counters | ✓ (helpful/harmful) | ✓ (in rule metadata.extra) |
| Correction lineage | ✗ | ✓ (supersession chain with reasons) |
| Quality gate on rules | ✗ | ✓ (Trust Gate on promotion) |
| Staging area | ✗ | ✓ (drafts/ → preferences/) |
| Atomic multi-rule updates | ✗ | ✓ (single JJ commit) |
| Rule rollback | ✗ | ✓ (JJ op restore) |
| Human-editable rules | Partial | ✓ (markdown + standard MCP tools) |

## Performance

- `on_recall`: < 50ms for 100 thoughts with 10 rules (in-memory cache hit)
- `before_save`: < 20ms for anti-pattern check (cached playbook)
- Playbook cache TTL: 5 minutes (configurable via `_CACHE_TTL_SECONDS`)
- Cache invalidation: immediate on `after_save`, `after_propose`, `after_supersede` for `ace-playbook` tagged thoughts

## Literature

- Stanford/SambaNova [arXiv:2510.04618](https://arxiv.org/abs/2510.04618) (ICLR 2026)
- ACL 2025 Reflective Memory Management
- Reference implementations: [ace-agent/ace](https://github.com/ace-agent/ace) (Apache-2.0), [kayba-ai/agentic-context-engine](https://github.com/kayba-ai/agentic-context-engine) (MIT)

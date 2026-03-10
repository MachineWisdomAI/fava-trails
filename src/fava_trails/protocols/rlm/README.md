# RLM MapReduce Hooks

Implements a **MapReduce-on-FAVA-Trails** orchestration pattern based on:

- **MIT RLM** ([arXiv:2512.24601](https://alexzhang13.github.io/rlm/)): Recursive Language Models — root LLM decomposes inputs via code, worker LLMs extract, root reduces.

FAVA Trails turns ephemeral execution state into a **persistent, auditable context graph**: mapper outputs survive crashes, the reducer can reference findings by ULID, and dead-end investigations are explicitly superseded.

## Quick Start

### Option A: Module Reference (zero-friction)

Add to the `hooks:` section of your `config.yaml` (at data repo root):

```yaml
hooks:
  - module: fava_trails.protocols.rlm
    points: [before_save, after_save, on_recall]
    order: 15
    fail_mode: closed
    config:
      expected_mappers: 5
      min_mapper_output_chars: 20
```

### Option B: Local Copy (for customization)

```bash
cp -r "$(python -c 'import fava_trails.protocols.rlm as p; import os; print(os.path.dirname(p.__file__))')" ./my-hooks/rlm/
```

Then in `config.yaml`:

```yaml
hooks:
  - path: ./my-hooks/rlm/
    points: [before_save, after_save, on_recall]
    order: 15
    fail_mode: closed
    config:
      expected_mappers: 5
      min_mapper_output_chars: 20
```

## Config Contract

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `expected_mappers` | `int` | `0` | Number of distinct mapper_ids expected per batch. `0` disables "REDUCE READY" signaling. |
| `min_mapper_output_chars` | `int` | `20` | Minimum content length for mapper outputs. Below this, `before_save` rejects. |

### Note on `fail_mode: closed`

RLM uses closed mode because malformed mapper outputs corrupt the reduce phase. Invalid mapper saves are rejected, not silently passed through.

## Architecture

```
Orchestrator (root LLM) decomposes question into N sub-tasks
  │
  ├─ Mapper 1: save_thought(content=extraction, tags=["rlm-mapper"],
  │             metadata={mapper_id: "m1", batch_id: "batch-001"})
  ├─ Mapper 2: save_thought(...)
  └─ Mapper N: save_thought(...)
        │
        │  [after_save hook tracks progress → signals REDUCE READY]
        │
  Orchestrator: recall(scope={tags: ["rlm-mapper"]})
        │        [on_recall sorts by (mapper_id, created_at)]
        │
  Reducer: synthesize N extractions → save_thought(tags=["rlm-reducer"])
        │
  propose_truth(reducer_ulid) → permanent namespace
        │
  [Optional] supersede mapper drafts as subsumed
```

## Mapper Thought Requirements

Mapper agents must save thoughts with:

```python
# Required fields
tags=["rlm-mapper"]
metadata.extra = {
    "mapper_id": "mapper-1",   # Required: unique per mapper per batch
    "batch_id":  "batch-uuid", # Recommended: groups mappers for one reduce pass
}
content = "..."                # Must be >= min_mapper_output_chars (default 20)
```

Missing `mapper_id` → **Reject** (blocks save)
Missing `batch_id` → **Advise** (non-blocking warning)
Content too short  → **Reject** (blocks save)

## Hooks Reference

### `before_save`

Validates mapper outputs before commit. Sequential guards:

1. No thought or no `rlm-mapper` tag → pass through (None)
2. Missing `mapper_id` → `Reject(code="rlm_missing_mapper_id")`
3. Missing `batch_id` → `Advise(code="rlm_missing_batch_id")` (non-blocking)
4. Content `< min_mapper_output_chars` → `Reject(code="rlm_mapper_too_short")`

### `after_save`

Observer-only batch progress counter:

- Tracks distinct `mapper_id` per `(trail_name, batch_id)` using sets (deduplication)
- When count reaches `expected_mappers` → logs `REDUCE READY`, resets counter, returns `Advise(code="rlm_reduce_ready")`
- Always returns `Annotate` with `{rlm_batch_id, rlm_mapper_id, rlm_batch_count, rlm_expected_mappers, rlm_reduce_ready}`
- Advisory only — the reducer should verify via `recall` before reducing

### `on_recall`

Deterministic mapper ordering for reducer consumption:

- Only activates when `scope.tags` includes `"rlm-mapper"` (non-invasive)
- Sorts mapper results by `(mapper_id, created_at)` — stable across concurrent saves
- Non-mapper results appended after sorted mappers in original order
- Returns `RecallSelect(reason="rlm_mapper_deterministic_order")` + `Annotate` with counts

## Literature

- Zhang, Kraska, Khattab (2024). *Recursive Language Models*. [arXiv:2512.24601](https://arxiv.org/abs/2512.24601) / [Blog](https://alexzhang13.github.io/rlm/)

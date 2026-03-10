"""RLM MapReduce Hooks (Orchestration Pattern).

Based on MIT RLM (arXiv:2512.24601): Recursive Language Models — root LLM
decomposes large inputs via code, worker LLMs extract, root reduces results.
Reference: https://alexzhang13.github.io/rlm/

Four lifecycle hooks:
  - before_save:    Validate mapper outputs (mapper_id required, min content length)
  - after_save:     Track batch progress, signal "REDUCE READY" when all mappers done
  - on_recall:      Sort mapper results deterministically for reducer consumption
  - on_recall_mix:  Same deterministic sort applied to cross-trail merged results

Configure via config.yaml hooks entry or test harness::

    hooks:
      - module: fava_trails.protocols.rlm
        points: [before_save, after_save, on_recall, on_recall_mix]
        order: 15
        fail_mode: closed
        config:
          expected_mappers: 5
          min_mapper_output_chars: 20
"""

from __future__ import annotations

import logging
from typing import Any

from fava_trails.hook_types import (
    Advise,
    AfterSaveEvent,
    Annotate,
    BeforeSaveEvent,
    OnRecallEvent,
    RecallSelect,
    Reject,
)

logger = logging.getLogger(__name__)

# Default hook entry for `fava-trails rlm setup --write`
DEFAULT_HOOK_ENTRY: dict = {
    "module": "fava_trails.protocols.rlm",
    "points": ["before_save", "after_save", "on_recall", "on_recall_mix"],
    "order": 15,
    "fail_mode": "closed",
    "config": {
        "expected_mappers": 5,
        "min_mapper_output_chars": 20,
    },
}

# Module-level state.  Reset on configure().
_CONFIG: dict[str, Any] = {}
# scope (trail_name) -> {batch_id -> set(mapper_ids)}
_BATCH_COUNTS: dict[str, dict[str, set[str]]] = {}


def configure(config: dict[str, Any]) -> None:
    """Receive hook config from HookRegistry at load time."""
    global _CONFIG, _BATCH_COUNTS
    _CONFIG = dict(config)  # copy to prevent external mutation
    _BATCH_COUNTS = {}


# --- Lifecycle Hooks ---


async def before_save(event: BeforeSaveEvent) -> list[Any] | None:
    """Validate mapper outputs before they are saved.

    Runs sequential validation for thoughts tagged with 'rlm-mapper':
      1. Guard: no thought or no rlm-mapper tag -> None (pass through)
      2. Missing mapper_id in extra -> Reject(code="rlm_missing_mapper_id")
      3. Missing batch_id in extra -> Advise(code="rlm_missing_batch_id") (non-blocking)
      4. Content < min_mapper_output_chars -> Reject(code="rlm_mapper_too_short")

    Uses fail_mode: closed — invalid mapper saves are rejected to prevent
    corrupt reduce phases.
    """
    if not event.thought:
        return None

    tags = event.thought.frontmatter.metadata.tags or []
    if "rlm-mapper" not in tags:
        return None

    extra = event.thought.frontmatter.metadata.extra or {}
    actions: list[Any] = []

    # mapper_id is required — reducer uses it to deduplicate and reference findings
    if not extra.get("mapper_id"):
        return [Reject(
            reason="Mapper output missing required 'mapper_id' in metadata.extra",
            code="rlm_missing_mapper_id",
        )]

    # batch_id is recommended but not blocking — warn the agent
    if not extra.get("batch_id"):
        actions.append(Advise(
            message=(
                "Mapper output is missing 'batch_id' in metadata.extra. "
                "Without batch_id, the after_save progress counter cannot track "
                "batch completion. Set batch_id to group mapper outputs for a "
                "single reduce pass."
            ),
            code="rlm_missing_batch_id",
        ))

    # Content must meet minimum length — short outputs indicate incomplete extraction
    min_chars = _CONFIG.get("min_mapper_output_chars", 20)
    content = event.thought.content or ""
    if len(content) < min_chars:
        return [Reject(
            reason=(
                f"Mapper output is too short ({len(content)} chars < {min_chars} "
                f"min). Ensure the mapper has extracted meaningful content."
            ),
            code="rlm_mapper_too_short",
        )]

    return actions if actions else None


async def after_save(event: AfterSaveEvent) -> list[Any] | None:
    """Track batch progress and signal when all mappers have reported.

    Observer-only: tracks distinct mapper_id per (trail_name, batch_id).
    When the count reaches expected_mappers, logs "REDUCE READY" and resets
    the per-batch counter.

    Returns Advise + Annotate with current progress.  The Advise is advisory
    only — the reducer must verify via recall before starting reduction.
    """
    if not event.thought:
        return None

    tags = event.thought.frontmatter.metadata.tags or []
    if "rlm-mapper" not in tags:
        return None

    extra = event.thought.frontmatter.metadata.extra or {}
    mapper_id = extra.get("mapper_id")
    batch_id = extra.get("batch_id")

    # Both are needed for progress tracking; skip if either is missing
    if not mapper_id or not batch_id:
        return None

    scope = event.trail_name

    # GIL-safe update (single process): add mapper_id to the set for this (scope, batch_id)
    scope_counts = _BATCH_COUNTS.setdefault(scope, {})
    batch_set = scope_counts.setdefault(batch_id, set())
    batch_set.add(mapper_id)

    current_count = len(batch_set)
    expected = _CONFIG.get("expected_mappers", 0)

    actions: list[Any] = []

    if expected > 0 and current_count >= expected:
        logger.info(
            "RLM REDUCE READY: scope=%s batch=%s mappers=%d/%d",
            scope, batch_id, current_count, expected,
        )
        # Reset for next batch cycle
        scope_counts[batch_id] = set()
        actions.append(Advise(
            message=(
                f"REDUCE READY: All {expected} mappers have reported for "
                f"batch '{batch_id}'. Start the reducer now. "
                "Verify via recall(tags=['rlm-mapper'], ...) before reducing."
            ),
            code="rlm_reduce_ready",
        ))
    else:
        advice_msg = (
            f"Mapper '{mapper_id}' saved for batch '{batch_id}'. "
            f"Progress: {current_count}/{expected} mappers reported."
            if expected > 0
            else f"Mapper '{mapper_id}' saved for batch '{batch_id}'. "
                 f"Total mappers so far: {current_count}."
        )
        actions.append(Advise(
            message=advice_msg,
            code="rlm_mapper_progress",
        ))

    actions.append(Annotate({
        "rlm_batch_id": batch_id,
        "rlm_mapper_id": mapper_id,
        "rlm_batch_count": current_count,
        "rlm_expected_mappers": expected,
        "rlm_reduce_ready": expected > 0 and current_count >= expected,
    }))

    return actions


async def on_recall(event: OnRecallEvent) -> list[Any] | None:
    """Sort mapper results deterministically for reducer consumption.

    Guards:
      - No results -> None
      - 'rlm-mapper' not in scope filter tags -> None (don't interfere with
        non-mapper recalls)

    Sorts by (mapper_id, created_at) so the reducer receives results in a
    stable, predictable order regardless of storage insertion order.

    Returns RecallSelect + Annotate with mapper_ids list and counts.
    """
    if not event.results:
        return None

    # Only activate when the caller is explicitly filtering for rlm-mapper thoughts
    scope = event.scope if isinstance(event.scope, dict) else {}
    raw_tags = scope.get("tags", [])
    scope_tags = raw_tags if isinstance(raw_tags, list) else []
    if "rlm-mapper" not in scope_tags:
        return None

    # Filter to only rlm-mapper thoughts and sort deterministically
    mapper_thoughts = [
        t for t in event.results
        if "rlm-mapper" in (t.frontmatter.metadata.tags or [])
    ]

    if not mapper_thoughts:
        return None

    def _sort_key(thought: Any) -> tuple[str, Any]:
        extra = thought.frontmatter.metadata.extra or {}
        mapper_id = extra.get("mapper_id") or ""
        created_at = thought.frontmatter.created_at
        return (str(mapper_id), created_at)

    mapper_thoughts.sort(key=_sort_key)

    # Non-mapper results keep their original relative order (appended after mappers)
    non_mapper_thoughts = [
        t for t in event.results
        if "rlm-mapper" not in (t.frontmatter.metadata.tags or [])
    ]

    ordered = mapper_thoughts + non_mapper_thoughts
    ordered_ulids = [t.thought_id for t in ordered]

    mapper_ids = [
        (t.frontmatter.metadata.extra or {}).get("mapper_id")
        for t in mapper_thoughts
    ]

    return [
        RecallSelect(
            ordered_ulids=ordered_ulids,
            reason="rlm_mapper_deterministic_order",
        ),
        Annotate({
            "rlm_mapper_count": len(mapper_thoughts),
            "rlm_mapper_ids": mapper_ids,
            "rlm_total_count": len(ordered),
        }),
    ]


async def on_recall_mix(event: OnRecallEvent) -> list[Any] | None:
    """Apply deterministic mapper ordering to cross-trail merged results.

    Delegates to on_recall so the same sort logic applies to both single-trail
    and multi-trail (recall_multi) result sets. Useful when mappers span
    multiple trails in a distributed MapReduce pipeline.
    """
    return await on_recall(event)

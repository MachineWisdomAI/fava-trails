"""ACE Playbook Hooks (Curator Pattern).

Implements FAVA Trails' adaptation of the ACE (Agentic Context Engine) Curator
pattern, based on:
  Stanford/SambaNova arXiv:2510.04618 (ICLR 2026)
  ACL 2025 Reflective Memory Management

Six lifecycle hooks provide:
  - on_startup:     Lazy cache warmup signal
  - on_recall:      Playbook-driven reranking via RecallSelect
  - before_save:    Anti-pattern Warn + brevity-bias Advise
  - after_save:     Cache invalidation + Reflector telemetry accumulation
  - after_propose:  Cache invalidation when a rule enters preferences/
  - after_supersede: Correction telemetry + cache invalidation

The external Reflector (another agent, a batch job, or a human) reads
_SAVE_TELEMETRY and _SUPERSEDE_STATS (or queries via MCP recall), analyzes
patterns, and proposes new playbook rules via save_thought into drafts/.
Draft rules pass through the Trust Gate via propose_truth before becoming
active in preferences/. Hooks provide signal — the Reflector acts on it.

Configure via config.yaml hooks entry or test harness::

    hooks:
      - module: fava_trails.protocols.ace
        points: [on_startup, on_recall, before_save, after_save, after_propose, after_supersede]
        order: 10
        fail_mode: open
        config:
          playbook_namespace: preferences
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fava_trails.hook_types import (
    Advise,
    AfterProposeEvent,
    AfterSaveEvent,
    AfterSupersedeEvent,
    Annotate,
    BeforeSaveEvent,
    OnRecallEvent,
    OnStartupEvent,
    RecallSelect,
    StartupOk,
    Warn,
)

from .rules import PlaybookRule, _parse_rules

logger = logging.getLogger(__name__)

# --- Module-level state ---

_CONFIG: dict[str, Any] = {}

# Playbook cache: scope_key (trail_name) -> list[PlaybookRule]
_PLAYBOOK_CACHE: dict[str, list[PlaybookRule]] = {}

# Cache timestamp: scope_key -> monotonic time of last load
_CACHE_TIMESTAMPS: dict[str, float] = {}

# 5-minute TTL as stale-cache backstop
_CACHE_TTL_SECONDS: float = 300.0

# Telemetry accumulators for the external Reflector
_SAVE_TELEMETRY: dict[str, list[dict[str, Any]]] = {}
_SUPERSEDE_STATS: dict[str, list[dict[str, Any]]] = {}


# --- Configuration ---


def configure(config: dict[str, Any]) -> None:
    """Receive hook config from HookRegistry at load time."""
    global _CONFIG, _PLAYBOOK_CACHE, _CACHE_TIMESTAMPS
    _CONFIG = config
    # Clear cache so new config takes effect immediately
    _PLAYBOOK_CACHE.clear()
    _CACHE_TIMESTAMPS.clear()


# --- Lifecycle Hooks ---


async def on_startup(event: OnStartupEvent) -> StartupOk:
    """Signal startup; playbook cache warms lazily on first recall."""
    ns = _CONFIG.get("playbook_namespace", "preferences")
    return StartupOk(
        f"ACE hooks initialized (playbook_namespace={ns!r}). "
        "Cache warms lazily on first recall."
    )


async def on_recall(event: OnRecallEvent) -> list[Any] | None:
    """Apply playbook rules to rerank recall results.

    Lazy-loads rules from preferences/ (or configured namespace) with a
    5-minute TTL. Uses multiplicative ACE-style scoring. Returns RecallSelect
    for provenance safety — can only reorder existing results, never inject.
    """
    if not event.results:
        return None

    ns = _CONFIG.get("playbook_namespace", "preferences")
    scope_key = event.trail_name
    now = time.monotonic()

    # Lazy-load and cache playbook rules per scope, with TTL
    cached_at = _CACHE_TIMESTAMPS.get(scope_key, 0.0)
    if scope_key not in _PLAYBOOK_CACHE or (now - cached_at) > _CACHE_TTL_SECONDS:
        if event.context:
            raw_rules = await event.context.recall("ace-playbook", namespace=ns, limit=50)
            _PLAYBOOK_CACHE[scope_key] = _parse_rules(raw_rules)
            _CACHE_TIMESTAMPS[scope_key] = now
        else:
            _PLAYBOOK_CACHE[scope_key] = []
            _CACHE_TIMESTAMPS[scope_key] = now

    playbook = _PLAYBOOK_CACHE[scope_key]
    if not playbook:
        return None

    # Score each result using ACE-style multiplicative scoring
    scored: list[tuple[Any, float]] = []
    for thought in event.results:
        confidence = thought.frontmatter.confidence
        score = 0.5 if confidence is None else confidence
        for rule in playbook:
            score *= rule.evaluate(thought)
        scored.append((thought, score))

    # Stable sort: primary by score, secondary by thought_id (deterministic tiebreak)
    scored.sort(key=lambda x: (x[1], x[0].thought_id), reverse=True)
    ordered_ulids = [t.thought_id for t, _ in scored]

    return [
        RecallSelect(ordered_ulids=ordered_ulids, reason="ace_playbook_rerank"),
        Annotate({"recall_policy": "ace_rerank_v1", "rules_applied": len(playbook)}),
    ]


async def before_save(event: BeforeSaveEvent) -> list[Any] | None:
    """Anti-pattern guardian and quality advisor.

    Checks cached playbook anti-pattern rules. Adds a brevity-bias advisory
    for terse decisions (< 80 chars) per ACE research findings.
    """
    if not event.thought:
        return None

    scope_key = event.trail_name
    playbook = _PLAYBOOK_CACHE.get(scope_key, [])
    actions: list[Any] = []

    # Check anti-pattern rules (ACE's "harmful" detection)
    for rule in playbook:
        if rule.rule_type == "anti_pattern" and rule.matches(event.thought):
            actions.append(Warn(
                message=f"Matches anti-pattern '{rule.name}': {rule.description}",
                code="ace_anti_pattern",
            ))

    # Quality advisory: terse decisions (maps to ACE's brevity-bias finding)
    thought = event.thought
    if (
        thought.frontmatter.source_type.value == "decision"
        and len(thought.content.strip()) < 80
    ):
        actions.append(Advise(
            message=(
                "Decision is terse — ACE research shows brevity bias degrades "
                "future recall quality. Add rationale."
            ),
            code="ace_brevity_bias",
            suggested_patch={"metadata": {"quality": "needs_expansion"}},
        ))

    return actions if actions else None


async def after_save(event: AfterSaveEvent) -> None:
    """Cache invalidation + Reflector telemetry accumulation.

    after_* hooks are at-most-once, best-effort, non-blocking. Telemetry is
    advisory — correctness derives from persisted thoughts queried via MCP.
    """
    if not event.thought:
        return None

    tags = event.thought.frontmatter.metadata.tags or []
    scope_key = event.trail_name

    # Cache invalidation: new ace-playbook thought → force reload on next recall
    if "ace-playbook" in tags:
        _PLAYBOOK_CACHE.pop(scope_key, None)
        _CACHE_TIMESTAMPS.pop(scope_key, None)
        logger.info("ACE: playbook cache invalidated for %s (after_save)", scope_key)

    # Telemetry accumulation for external Reflector
    _SAVE_TELEMETRY.setdefault(scope_key, []).append({
        "thought_id": event.thought.thought_id,
        "source_type": event.thought.frontmatter.source_type.value,
        "tags": list(tags),
        "confidence": event.thought.frontmatter.confidence,
    })
    return None


async def after_propose(event: AfterProposeEvent) -> None:
    """Cache invalidation when a rule enters preferences/ via propose_truth.

    Ensures newly promoted ace-playbook rules are picked up on the next recall
    without waiting for the 5-minute TTL.
    """
    if not event.thought:
        return None

    tags = event.thought.frontmatter.metadata.tags or []
    scope_key = event.trail_name

    if "ace-playbook" in tags:
        _PLAYBOOK_CACHE.pop(scope_key, None)
        _CACHE_TIMESTAMPS.pop(scope_key, None)
        logger.info("ACE: playbook cache invalidated for %s (after_propose)", scope_key)
    return None


async def after_supersede(event: AfterSupersedeEvent) -> None:
    """Correction telemetry + cache invalidation.

    Records each supersession as structured telemetry for the external
    Reflector. Invalidates playbook cache if a rule was superseded.
    """
    if not event.new_thought or not event.original_thought:
        return None

    scope_key = event.trail_name
    entry: dict[str, Any] = {
        "original_id": event.original_thought.thought_id,
        "new_id": event.new_thought.thought_id,
        "source_type": event.original_thought.frontmatter.source_type.value,
        "tags": list(event.original_thought.frontmatter.metadata.tags or []),
    }
    _SUPERSEDE_STATS.setdefault(scope_key, []).append(entry)

    logger.info(
        "ACE telemetry: %s superseded %s in %s (type=%s)",
        event.new_thought.thought_id[:8],
        event.original_thought.thought_id[:8],
        scope_key,
        entry["source_type"],
    )

    # Invalidate cache if a playbook rule was involved
    old_tags = set(event.original_thought.frontmatter.metadata.tags or [])
    new_tags = set(event.new_thought.frontmatter.metadata.tags or [])
    if "ace-playbook" in old_tags or "ace-playbook" in new_tags:
        _PLAYBOOK_CACHE.pop(scope_key, None)
        _CACHE_TIMESTAMPS.pop(scope_key, None)
        logger.info("ACE: playbook cache invalidated for %s (after_supersede)", scope_key)
    return None

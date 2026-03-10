"""Pipeline execution engine for lifecycle hooks.

- run_pipeline(): synchronous gating pipeline for before_*/on_recall
- dispatch_observer(): async fire-and-forget for after_* hooks
"""

from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass, field, replace
from typing import Any

from .hook_manifest import HookRegistry, HookSpec
from .hook_types import (
    Advise,
    Annotate,
    HookEvent,
    HookFeedback,
    Mutate,
    Proceed,
    RecallSelect,
    Redirect,
    Reject,
    Warn,
    validate_action,
)

logger = logging.getLogger(__name__)

# Guard against runaway mutation chains
MAX_MUTATIONS_PER_PIPELINE = 5


class HookExecutionError(Exception):
    """Raised when a hook with fail_mode='closed' fails."""


class HookTimeoutError(HookExecutionError):
    """Raised when a hook with fail_mode='closed' times out."""


@dataclass
class PipelineResult:
    """Result of running the hook pipeline for a lifecycle point."""
    feedback: HookFeedback = field(default_factory=HookFeedback)
    event: HookEvent | None = None
    rejected: bool = False
    redirect_namespace: str | None = None
    recall_selection: list[str] | None = None


async def run_pipeline(
    registry: HookRegistry,
    event: HookEvent,
) -> PipelineResult:
    """Execute the hook pipeline for a lifecycle event.

    Runs hooks in order, composing actions:
    - Reject: halt immediately
    - Redirect: terminal, depth=1
    - Mutate: apply patch eagerly, later hooks see mutated state
    - Warn/Advise/Annotate: accumulate in feedback
    - Proceed/None: continue
    - RecallSelect: validate subset, store selection
    """
    hooks = registry.get_hooks(event.lifecycle_point)
    if not hooks:
        return PipelineResult(event=event)

    result = PipelineResult(event=event)
    mutation_count = 0

    for hook in hooks:
        # Execute hook with timeout
        try:
            raw = await asyncio.wait_for(hook.fn(event), timeout=hook.timeout)
        except TimeoutError as exc:
            logger.warning(
                "Hook %s:%s timed out after %.1fs (fail_mode=%s)",
                hook.source, hook.name, hook.timeout, hook.fail_mode,
            )
            if hook.fail_mode == "closed":
                raise HookTimeoutError(
                    f"Hook '{hook.source}:{hook.name}' timed out after {hook.timeout}s"
                ) from exc
            continue
        except Exception as e:
            logger.warning(
                "Hook %s:%s failed: %s: %s (fail_mode=%s)",
                hook.source, hook.name, type(e).__name__, e, hook.fail_mode,
            )
            if hook.fail_mode == "closed":
                raise HookExecutionError(
                    f"Hook '{hook.source}:{hook.name}' failed: {type(e).__name__}: {e}"
                ) from e
            continue

        # Normalize return to list of actions
        actions = _normalize_actions(raw)

        for action in actions:
            # Validate action is allowed for this lifecycle point
            if not validate_action(event.lifecycle_point, action):
                logger.warning(
                    "Hook %s:%s returned invalid action %s for %s — skipping",
                    hook.source, hook.name, type(action).__name__, event.lifecycle_point,
                )
                continue

            # Apply action
            if isinstance(action, Reject):
                result.feedback.merge(action)
                result.rejected = True
                logger.info(
                    "Hook %s:%s rejected operation: %s",
                    hook.source, hook.name, action.reason,
                )
                return result  # Terminal

            elif isinstance(action, Redirect):
                result.feedback.merge(action)
                result.redirect_namespace = action.namespace
                logger.info(
                    "Hook %s:%s redirected to namespace: %s",
                    hook.source, hook.name, action.namespace,
                )
                return result  # Terminal

            elif isinstance(action, Mutate):
                mutation_count += 1
                if mutation_count > MAX_MUTATIONS_PER_PIPELINE:
                    msg = (
                        f"Max mutations ({MAX_MUTATIONS_PER_PIPELINE}) exceeded "
                        f"by hook {hook.source}:{hook.name}"
                    )
                    logger.warning(msg)
                    if hook.fail_mode == "closed":
                        raise HookExecutionError(msg)
                    continue

                # Apply patch to event's thought — replace event immutably
                if hasattr(event, "thought") and event.thought is not None:
                    patched = action.patch.apply(event.thought)
                    event = replace(event, thought=patched)
                    result.event = event
                    logger.debug(
                        "Hook %s:%s mutated thought (mutation %d/%d)",
                        hook.source, hook.name, mutation_count, MAX_MUTATIONS_PER_PIPELINE,
                    )

                result.feedback.merge(action)

            elif isinstance(action, RecallSelect):
                # Validate: subset-only, no duplicates
                if hasattr(event, "results") and event.results:
                    valid_ulids = {
                        r.thought_id for r in event.results
                        if hasattr(r, "thought_id")
                    }
                    seen: set[str] = set()
                    filtered: list[str] = []
                    for ulid in action.ordered_ulids:
                        if ulid in valid_ulids and ulid not in seen:
                            filtered.append(ulid)
                            seen.add(ulid)
                        elif ulid not in valid_ulids:
                            logger.debug("RecallSelect: dropping invalid ULID %s", ulid)
                    result.recall_selection = filtered
                result.feedback.merge(action)

            elif isinstance(action, (Warn, Advise, Annotate)):
                result.feedback.merge(action)

            # Proceed is a no-op

    return result


def _normalize_actions(raw: Any) -> list:
    """Normalize hook return value to a list of actions."""
    if raw is None:
        return [Proceed()]
    if isinstance(raw, list):
        return raw
    return [raw]


async def dispatch_observer(
    registry: HookRegistry,
    event: HookEvent,
) -> PipelineResult | None:
    """Run after_* hooks inline on the caller's task.

    Runs each hook sequentially with timeout and error handling.
    Returns a PipelineResult so feedback (Annotate, Advise, etc.)
    is reachable via consume_feedback() on the same asyncio task.

    At-most-once delivery — no retry on failure.
    """
    hooks = registry.get_hooks(event.lifecycle_point)
    if not hooks:
        return None

    feedback = HookFeedback()
    for hook in hooks:
        result = await _run_observer_hook(hook, copy.deepcopy(event))
        if result is not None:
            for action in result:
                if isinstance(action, Annotate):
                    feedback.merge(action)
                elif isinstance(action, Advise):
                    feedback.merge(action)
                elif isinstance(action, Warn):
                    feedback.merge(action)

    if feedback.is_empty():
        return None
    return PipelineResult(feedback=feedback)


async def _run_observer_hook(hook: HookSpec, event: HookEvent) -> list[Any] | None:
    """Run a single observer hook with timeout and error handling.

    Returns the hook's action list (if any) so dispatch_observer can
    accumulate feedback on the caller's task.
    """
    try:
        result = await asyncio.wait_for(hook.fn(event), timeout=hook.timeout)
        if result is None:
            return None
        return _normalize_actions(result)
    except TimeoutError:
        logger.warning(
            "Observer hook %s:%s timed out after %.1fs",
            hook.source, hook.name, hook.timeout,
        )
        return None
    except Exception:
        logger.warning(
            "Observer hook %s:%s failed",
            hook.source, hook.name,
            exc_info=True,
        )
        return None

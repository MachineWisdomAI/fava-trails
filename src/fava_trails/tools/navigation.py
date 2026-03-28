"""Navigation and lifecycle tools: diff, list_scopes, conflicts, propose_truth, rollback, sync."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from ..config import ConfigStore, get_trails_dir, get_trust_gate_policy
from ..trail import AmbiguousThoughtID
from ..trust_gate import TrustGateConfigError, TrustGatePromptCache, review_thought

logger = logging.getLogger(__name__)


async def handle_diff(trail, arguments: dict) -> dict[str, Any]:
    """Compare thought states."""
    revision = arguments.get("revision", "")
    diff = await trail.get_diff(revision)
    return {
        "status": "ok",
        "summary": diff.summary,
        "files_changed": diff.files_changed,
    }


async def handle_list_scopes(arguments: dict) -> dict[str, Any]:
    """Discover all scopes (trails) recursively. Supports prefix filter and optional stats."""
    trails_dir = get_trails_dir()
    prefix = arguments.get("prefix", "")
    include_stats = arguments.get("include_stats", False)
    scopes = []

    if trails_dir.exists():
        search_root = trails_dir / prefix if prefix else trails_dir
        if search_root.exists():
            for thoughts_dir in search_root.rglob("thoughts"):
                if thoughts_dir.is_dir():
                    scope_dir = thoughts_dir.parent
                    # Ensure scope_dir is under trails_dir
                    try:
                        scope_name = str(scope_dir.relative_to(trails_dir))
                    except ValueError:
                        continue
                    entry: dict[str, Any] = {"path": scope_name}
                    if include_stats:
                        md_count = sum(
                            1 for _ in thoughts_dir.rglob("*.md")
                            if _.name != ".gitkeep"
                        )
                        entry["thought_count"] = md_count
                    scopes.append(entry)

    return {
        "status": "ok",
        "count": len(scopes),
        "scopes": sorted(scopes, key=lambda s: s["path"]),
    }


# Backward compatibility alias
handle_list_trails = handle_list_scopes


async def handle_conflicts(trail, arguments: dict) -> dict[str, Any]:
    """Surface cognitive dissonance. Structured summary, NEVER raw algebraic notation."""
    conflicts = await trail.get_conflicts()
    if not conflicts:
        return {
            "status": "ok",
            "has_conflicts": False,
            "message": "No conflicts detected. Trail is consistent.",
        }

    conflict_list = []
    for c in conflicts:
        entry: dict = {"file": c.file_path, "description": c.description}
        if c.side_a is not None or c.side_b is not None or c.base is not None:
            entry["side_a"] = c.side_a
            entry["side_b"] = c.side_b
            entry["base"] = c.base
            entry["resolution_hint"] = (
                "Use update_thought on the conflicted thought ID to resolve. "
                "Choose side_a, side_b, or write a merged version."
            )
        else:
            entry["resolution_hint"] = (
                "Manual intervention required. Use rollback to restore pre-conflict state."
            )
        conflict_list.append(entry)

    return {
        "status": "conflict",
        "has_conflicts": True,
        "count": len(conflicts),
        "conflicts": conflict_list,
        "message": (
            f"{len(conflicts)} conflict(s) detected. "
            "Standard operations are halted. "
            "Use update_thought on conflicted thoughts to resolve, "
            "or rollback to restore a previous state."
        ),
    }


async def handle_propose_truth(
    trail,
    arguments: dict,
    prompt_cache: TrustGatePromptCache | None = None,
) -> dict[str, Any]:
    """Promote thought from drafts/ to permanent namespace, gated by Trust Gate review."""
    thought_id = arguments.get("thought_id", "")
    if not thought_id:
        return {"status": "error", "message": "thought_id is required"}

    try:
        from .thought import _serialize_thought

        # Resolve trust gate policy
        policy = get_trust_gate_policy(trail.trail_name)

        trust_result = None
        if policy == "llm-oneshot" and prompt_cache is None:
            return {
                "status": "error",
                "message": "Trust Gate enabled (llm-oneshot) but prompt cache not initialized",
            }

        if prompt_cache is not None:
            # Get the thought to review
            record = await trail.get_thought(thought_id)
            if record is None:
                return {"status": "error", "message": f"Thought {thought_id} not found"}

            try:
                prompt = prompt_cache.resolve_prompt(trail.trail_name)
            except TrustGateConfigError as e:
                return {"status": "error", "message": str(e)}

            global_config = ConfigStore.get().global_config
            openrouter_key = os.environ.get(global_config.openrouter_api_key_env, "")
            if not openrouter_key:
                return {
                    "status": "error",
                    "message": (
                        f"No LLM API key found. "
                        f"Set {global_config.openrouter_api_key_env} environment variable."
                    ),
                }

            from ..llm import LLMClient

            llm_client = LLMClient(
                openrouter_api_key=openrouter_key,
            )

            tg_timeout = global_config.trust_gate_timeout_secs
            _review_coro = review_thought(
                record=record,
                prompt=prompt,
                model=global_config.trust_gate_model,
                client=llm_client,
                policy=policy,
                trail_name=trail.trail_name,
            )
            if tg_timeout > 0:
                try:
                    trust_result = await asyncio.wait_for(
                        _review_coro, timeout=float(tg_timeout)
                    )
                except TimeoutError:
                    logger.error(
                        "Trust Gate LLM call timed out after %ds for thought %s",
                        tg_timeout,
                        thought_id,
                    )
                    return {
                        "status": "error",
                        "message": (
                            f"Trust Gate timed out after {tg_timeout}s reviewing thought {thought_id[:8]}. "
                            "The LLM provider did not respond. Retry propose_truth to try again."
                        ),
                    }
            else:
                trust_result = await _review_coro

        promoted = await trail.propose_truth(thought_id, trust_result=trust_result)
        result = {
            "status": "ok",
            "thought": _serialize_thought(promoted),
            "message": f"Promoted {thought_id[:8]} to {promoted.frontmatter.validation_status.value}",
        }

        if trust_result is not None:
            result["trust_gate"] = {
                "verdict": trust_result.verdict,
                "reasoning": trust_result.reasoning,
                "reviewer": trust_result.reviewer,
            }
            if trust_result.verdict in ("reject", "error"):
                result["status"] = "rejected" if trust_result.verdict == "reject" else "error"
                result["message"] = (
                    f"Thought {thought_id[:8]} {trust_result.verdict}ed by trust gate: "
                    f"{trust_result.reasoning}"
                )

        return result

    except AmbiguousThoughtID as e:
        return {"status": "error", "message": str(e), "candidates": e.candidates}
    except NotImplementedError as e:
        return {"status": "error", "message": str(e)}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


async def handle_rollback(trail, arguments: dict) -> dict[str, Any]:
    """Return trail to historical state via jj op restore."""
    op_id = arguments.get("op_id", "")
    if not op_id:
        # Show available operations
        ops = await trail.get_op_log(limit=10)
        return {
            "status": "error",
            "message": "op_id is required. Recent operations:",
            "operations": [
                {"op_id": op.op_id, "description": op.description, "timestamp": op.timestamp}
                for op in ops
            ],
        }

    result = await trail.rollback(op_id)
    return {"status": "ok", "message": result}


async def handle_sync(trail, arguments: dict) -> dict[str, Any]:
    """Sync with shared truth. Aborts on conflict."""
    result = await trail.sync()
    if result.has_conflicts:
        return {
            "status": "conflict",
            "message": f"Sync aborted: {result.summary}. Pre-sync state restored.",
            "conflicts": [
                {"file": c.file_path, "description": c.description}
                for c in result.conflict_details
            ],
        }
    return {
        "status": "ok",
        "message": result.summary,
    }

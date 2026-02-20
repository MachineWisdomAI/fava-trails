"""Navigation and lifecycle tools: diff, list_trails, conflicts, propose_truth, rollback, sync."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import get_trails_dir


async def handle_diff(trail, arguments: dict) -> dict[str, Any]:
    """Compare thought states."""
    revision = arguments.get("revision", "")
    diff = await trail.get_diff(revision)
    return {
        "status": "ok",
        "summary": diff.summary,
        "files_changed": diff.files_changed,
    }


async def handle_list_trails(arguments: dict) -> dict[str, Any]:
    """Show available trails."""
    trails_dir = get_trails_dir()
    trails = []
    if trails_dir.exists():
        for p in sorted(trails_dir.iterdir()):
            if p.is_dir() and (p / "thoughts").exists():
                trails.append({
                    "name": p.name,
                    "path": str(p),
                })
    return {
        "status": "ok",
        "count": len(trails),
        "trails": trails,
    }


async def handle_conflicts(trail, arguments: dict) -> dict[str, Any]:
    """Surface cognitive dissonance. Structured summary, NEVER raw algebraic notation."""
    conflicts = await trail.get_conflicts()
    if not conflicts:
        return {
            "status": "ok",
            "has_conflicts": False,
            "message": "No conflicts detected. Trail is consistent.",
        }

    return {
        "status": "conflict",
        "has_conflicts": True,
        "count": len(conflicts),
        "conflicts": [
            {"file": c.file_path, "description": c.description}
            for c in conflicts
        ],
        "message": (
            f"{len(conflicts)} conflict(s) detected. "
            "Standard operations are halted. "
            "Resolve each conflict before continuing."
        ),
        "resolution_hint": "Review the conflicting thoughts and use supersede to create a resolved version.",
    }


async def handle_propose_truth(trail, arguments: dict) -> dict[str, Any]:
    """Promote thought from drafts/ to permanent namespace based on source_type."""
    thought_id = arguments.get("thought_id", "")
    if not thought_id:
        return {"status": "error", "message": "thought_id is required"}

    try:
        from .thought import _serialize_thought
        record = await trail.propose_truth(thought_id)
        return {
            "status": "ok",
            "thought": _serialize_thought(record),
            "message": f"Promoted {thought_id[:8]} to {record.frontmatter.validation_status.value}",
        }
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

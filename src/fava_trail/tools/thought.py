"""Thought lifecycle tools: start_thought, save_thought, get_thought, forget, supersede, learn_preference."""

from __future__ import annotations

from typing import Any

from ..models import SourceType


def _serialize_thought(record) -> dict[str, Any]:
    """Convert ThoughtRecord to token-optimized JSON summary."""
    fm = record.frontmatter
    result = {
        "thought_id": fm.thought_id,
        "source_type": fm.source_type.value,
        "validation_status": fm.validation_status.value,
        "confidence": fm.confidence,
        "agent_id": fm.agent_id,
        "created_at": fm.created_at.isoformat() if fm.created_at else None,
        "content_preview": record.content[:200] + ("..." if len(record.content) > 200 else ""),
    }
    if fm.parent_id:
        result["parent_id"] = fm.parent_id
    if fm.superseded_by:
        result["superseded_by"] = fm.superseded_by
    if fm.intent_ref:
        result["intent_ref"] = fm.intent_ref
    if fm.relationships:
        result["relationships"] = [
            {"type": r.type.value, "target_id": r.target_id}
            for r in fm.relationships
        ]
    if fm.metadata and (fm.metadata.project or fm.metadata.branch or fm.metadata.tags):
        result["metadata"] = {}
        if fm.metadata.project:
            result["metadata"]["project"] = fm.metadata.project
        if fm.metadata.branch:
            result["metadata"]["branch"] = fm.metadata.branch
        if fm.metadata.tags:
            result["metadata"]["tags"] = fm.metadata.tags
    return result


async def handle_start_thought(trail, arguments: dict) -> dict[str, Any]:
    """Begin new reasoning branch from current truth."""
    description = arguments.get("description", "")
    change = await trail.start_thought(description)
    return {
        "status": "ok",
        "change_id": change.change_id,
        "description": change.description,
        "message": f"Started new reasoning branch: {change.change_id}",
    }


async def handle_save_thought(trail, arguments: dict) -> dict[str, Any]:
    """Checkpoint mental state. Defaults to drafts/ namespace."""
    content = arguments.get("content", "")
    if not content:
        return {"status": "error", "message": "content is required"}

    source_type_str = arguments.get("source_type", "observation")
    try:
        source_type = SourceType(source_type_str)
    except ValueError:
        return {"status": "error", "message": f"Invalid source_type: {source_type_str}. Valid: {[s.value for s in SourceType]}"}

    record = await trail.save_thought(
        content=content,
        agent_id=arguments.get("agent_id", "unknown"),
        source_type=source_type,
        confidence=arguments.get("confidence", 0.5),
        namespace=arguments.get("namespace"),
        parent_id=arguments.get("parent_id"),
        intent_ref=arguments.get("intent_ref"),
        relationships=arguments.get("relationships"),
        metadata=arguments.get("metadata"),
    )
    return {
        "status": "ok",
        "thought": _serialize_thought(record),
        "message": f"Saved thought {record.thought_id[:8]} [{source_type.value}]",
    }


async def handle_get_thought(trail, arguments: dict) -> dict[str, Any]:
    """Deterministic retrieval of a specific thought."""
    thought_id = arguments.get("thought_id", "")
    if not thought_id:
        return {"status": "error", "message": "thought_id is required"}

    record = await trail.get_thought(thought_id)
    if record is None:
        return {"status": "error", "message": f"Thought {thought_id} not found"}

    result = _serialize_thought(record)
    result["content"] = record.content  # Full content for get
    return {"status": "ok", "thought": result}


async def handle_forget(trail, arguments: dict) -> dict[str, Any]:
    """Discard current reasoning line."""
    revision = arguments.get("revision", "")
    result = await trail.forget(revision)
    return {"status": "ok", "message": result}


async def handle_supersede(trail, arguments: dict) -> dict[str, Any]:
    """Replace a thought with corrected version. Atomic: new thought + backlink in single JJ change."""
    original_id = arguments.get("thought_id", "")
    if not original_id:
        return {"status": "error", "message": "thought_id (of original thought) is required"}

    new_content = arguments.get("content", "")
    if not new_content:
        return {"status": "error", "message": "content (for new thought) is required"}

    reason = arguments.get("reason", "")
    if not reason:
        return {"status": "error", "message": "reason is required (explain why the thought changed)"}

    try:
        record = await trail.supersede(
            original_id=original_id,
            new_content=new_content,
            reason=reason,
            agent_id=arguments.get("agent_id", "unknown"),
            confidence=arguments.get("confidence"),
        )
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    return {
        "status": "ok",
        "new_thought": _serialize_thought(record),
        "supersedes_thought_id": original_id,
        "reason": reason,
        "message": f"Superseded {original_id[:8]} with {record.thought_id[:8]}: {reason}",
    }


async def handle_learn_preference(trail, arguments: dict) -> dict[str, Any]:
    """Capture user correction. Bypasses Trust Gate — user input is auto-approved."""
    content = arguments.get("content", "")
    if not content:
        return {"status": "error", "message": "content is required"}

    preference_type = arguments.get("preference_type", "firm")
    if preference_type not in ("client", "firm"):
        return {"status": "error", "message": "preference_type must be 'client' or 'firm'"}

    record = await trail.learn_preference(
        content=content,
        preference_type=preference_type,
        agent_id=arguments.get("agent_id", "unknown"),
        metadata=arguments.get("metadata"),
    )
    return {
        "status": "ok",
        "thought": _serialize_thought(record),
        "message": f"Learned preference {record.thought_id[:8]} [{preference_type}]",
    }

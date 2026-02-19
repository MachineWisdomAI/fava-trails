"""Recall tools: recall (search with namespace/scope filtering + supersession hiding)."""

from __future__ import annotations

from typing import Any

from .thought import _serialize_thought


async def handle_recall(trail, arguments: dict) -> dict[str, Any]:
    """Search thoughts by query, namespace, and scope. Hides superseded by default."""
    results = await trail.recall(
        query=arguments.get("query", ""),
        namespace=arguments.get("namespace"),
        scope=arguments.get("scope"),
        include_superseded=arguments.get("include_superseded", False),
        include_relationships=arguments.get("include_relationships", False),
        limit=arguments.get("limit", 20),
    )

    thoughts = [_serialize_thought(r) for r in results]
    return {
        "status": "ok",
        "count": len(thoughts),
        "thoughts": thoughts,
        "filters": {
            "query": arguments.get("query", ""),
            "namespace": arguments.get("namespace"),
            "include_superseded": arguments.get("include_superseded", False),
            "include_relationships": arguments.get("include_relationships", False),
        },
    }

"""Recall tools: recall (search with namespace/scope filtering + supersession hiding)."""

from __future__ import annotations

from typing import Any

from .thought import _serialize_thought


async def handle_recall(trail, arguments: dict, additional_trails=None) -> dict[str, Any]:
    """Search thoughts by query, namespace, and scope. Hides superseded by default.

    When additional_trails is provided, searches across multiple scopes.
    Each result includes source_trail indicating which scope it came from.
    """
    query = arguments.get("query", "")
    namespace = arguments.get("namespace")
    scope = arguments.get("scope")
    include_superseded = arguments.get("include_superseded", False)
    include_relationships = arguments.get("include_relationships", False)
    limit = arguments.get("limit", 20)

    if additional_trails:
        # Multi-scope recall
        from ..trail import recall_multi
        all_trails = [trail] + additional_trails
        multi_results = await recall_multi(
            trail_managers=all_trails,
            query=query,
            namespace=namespace,
            scope=scope,
            include_superseded=include_superseded,
            include_relationships=include_relationships,
            limit=limit,
        )
        thoughts = []
        for record, source_trail_name in multi_results:
            serialized = _serialize_thought(record)
            serialized["source_trail"] = source_trail_name
            thoughts.append(serialized)
    else:
        # Single-scope recall (backward compatible)
        results = await trail.recall(
            query=query,
            namespace=namespace,
            scope=scope,
            include_superseded=include_superseded,
            include_relationships=include_relationships,
            limit=limit,
        )
        thoughts = []
        for r in results:
            serialized = _serialize_thought(r)
            serialized["source_trail"] = trail.trail_name
            thoughts.append(serialized)

    return {
        "status": "ok",
        "count": len(thoughts),
        "thoughts": thoughts,
        "filters": {
            "query": query,
            "namespace": namespace,
            "include_superseded": include_superseded,
            "include_relationships": include_relationships,
        },
    }

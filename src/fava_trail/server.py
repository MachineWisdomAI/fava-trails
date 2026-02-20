"""FAVA Trail MCP Server — Federated Agents Versioned Audit Trail.

Provides 14 MCP tools for versioned agent memory via JJ (Jujutsu) VCS.
All tool responses are token-optimized JSON summaries — no raw VCS output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import (
    ensure_data_repo_root,
    get_data_repo_root,
    get_trails_dir,
    load_global_config,
    sanitize_trail_name,
)
from .trail import TrailManager
from .vcs.jj_backend import JjBackend

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

server = Server("fava-trail")

# Trail manager cache: trail_name -> TrailManager
_trail_managers: dict[str, TrailManager] = {}

# Shared backend for monorepo init, GC, push, fetch
_shared_backend: JjBackend | None = None


async def _init_server() -> None:
    """Initialize monorepo at startup. Called once before server starts."""
    global _shared_backend
    repo_root = get_data_repo_root()
    trails_dir = get_trails_dir()

    # Validate trails_dir is inside repo_root
    try:
        trails_dir.resolve().relative_to(repo_root.resolve())
    except ValueError:
        raise RuntimeError(
            f"FAVA_TRAILS_DIR ({trails_dir}) must be inside data repo root ({repo_root}). "
            "Check your FAVA_TRAIL_DATA_REPO and FAVA_TRAILS_DIR environment variables."
        )

    _shared_backend = JjBackend(repo_root=repo_root, trail_path=trails_dir)
    await _shared_backend.init_monorepo()
    logger.info(f"Monorepo initialized at {repo_root}")


async def _get_trail(trail_name: str | None = None) -> TrailManager:
    """Get or create a TrailManager for the given trail."""
    config = load_global_config()
    name = trail_name or config.default_trail

    if name not in _trail_managers:
        repo_root = get_data_repo_root()
        safe_name = sanitize_trail_name(name)
        trail_path = get_trails_dir() / safe_name
        backend = JjBackend(repo_root=repo_root, trail_path=trail_path)
        manager = TrailManager(name, vcs=backend)
        # Auto-initialize if trail doesn't exist (detect by thoughts/ dir, not .jj)
        if not (manager.trail_path / "thoughts").exists():
            await manager.init()
        _trail_managers[name] = manager

    return _trail_managers[name]


# --- Tool Definitions ---

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "start_thought",
        "description": "Begin a new reasoning branch from current truth. Creates a fresh JJ change for capturing a line of thought.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Brief description of reasoning intent"},
                "trail_name": {"type": "string", "description": "Trail to use (defaults to config default)"},
            },
        },
    },
    {
        "name": "save_thought",
        "description": "Save a thought to the trail. Defaults to drafts/ namespace. Use propose_truth to promote to permanent namespace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The thought content (markdown)"},
                "source_type": {
                    "type": "string",
                    "enum": ["observation", "inference", "user_input", "tool_output", "decision"],
                    "description": "Type of thought",
                    "default": "observation",
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "namespace": {"type": "string", "description": "Override namespace (default: drafts/)"},
                "agent_id": {"type": "string", "description": "ID of the agent saving this thought"},
                "parent_id": {"type": "string", "description": "ULID of parent thought"},
                "intent_ref": {"type": "string", "description": "ULID of intent document this implements"},
                "relationships": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["DEPENDS_ON", "REVISED_BY", "AUTHORED_BY", "REFERENCES", "SUPERSEDES"]},
                            "target_id": {"type": "string"},
                        },
                        "required": ["type", "target_id"],
                    },
                    "description": "Relationships to other thoughts",
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "branch": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "description": "Thought metadata for filtering",
                },
                "trail_name": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "get_thought",
        "description": "Retrieve a specific thought by its ULID. Returns full content and metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thought_id": {"type": "string", "description": "ULID of the thought to retrieve"},
                "trail_name": {"type": "string"},
            },
            "required": ["thought_id"],
        },
    },
    {
        "name": "propose_truth",
        "description": "Promote a draft thought to its permanent namespace based on source_type. Moves from drafts/ to decisions/, observations/, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thought_id": {"type": "string", "description": "ULID of the draft thought to promote"},
                "trail_name": {"type": "string"},
            },
            "required": ["thought_id"],
        },
    },
    {
        "name": "recall",
        "description": "Search thoughts by query, namespace, and scope. Hides superseded thoughts by default. Supports 1-hop relationship traversal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "namespace": {"type": "string", "description": "Restrict to namespace (decisions, observations, intents, preferences, drafts)"},
                "scope": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "branch": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "description": "Filter by metadata scope",
                },
                "include_superseded": {"type": "boolean", "default": False, "description": "Show superseded thoughts (for archaeology)"},
                "include_relationships": {"type": "boolean", "default": False, "description": "Include 1-hop related thoughts"},
                "limit": {"type": "integer", "default": 20},
                "trail_name": {"type": "string"},
            },
        },
    },
    {
        "name": "forget",
        "description": "Discard current reasoning line. Abandons the current JJ change.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "revision": {"type": "string", "description": "Specific revision to abandon (default: current)"},
                "trail_name": {"type": "string"},
            },
        },
    },
    {
        "name": "sync",
        "description": "Sync with shared truth. Fetches from remote and rebases. Aborts automatically on conflict.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trail_name": {"type": "string"},
            },
        },
    },
    {
        "name": "conflicts",
        "description": "Surface cognitive dissonance. Returns structured conflict summaries — never raw VCS algebraic notation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trail_name": {"type": "string"},
            },
        },
    },
    {
        "name": "rollback",
        "description": "Return trail to a historical state using JJ operation restore.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "op_id": {"type": "string", "description": "Operation ID to restore to"},
                "trail_name": {"type": "string"},
            },
        },
    },
    {
        "name": "diff",
        "description": "Compare thought states. Shows what changed in a revision.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "revision": {"type": "string", "description": "Revision to diff (default: current working change)"},
                "trail_name": {"type": "string"},
            },
        },
    },
    {
        "name": "list_trails",
        "description": "Show all available FAVA trails.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "learn_preference",
        "description": "Capture a user correction or preference. Stored in preferences/ namespace. Bypasses Trust Gate — user input is auto-approved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The preference or correction"},
                "preference_type": {
                    "type": "string",
                    "enum": ["client", "firm"],
                    "default": "firm",
                    "description": "Client-specific or firm-wide preference",
                },
                "agent_id": {"type": "string"},
                "metadata": {"type": "object"},
                "trail_name": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "supersede",
        "description": "Replace a thought with a corrected version. ATOMIC: creates new thought + backlinks original in a single JJ change. The superseded_by field is the ONLY permitted exception to immutability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thought_id": {"type": "string", "description": "ULID of the thought to supersede"},
                "content": {"type": "string", "description": "Content of the replacement thought"},
                "reason": {"type": "string", "description": "Why this thought is being superseded"},
                "agent_id": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "trail_name": {"type": "string"},
            },
            "required": ["thought_id", "content", "reason"],
        },
    },
]


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List all FAVA Trail tools."""
    return [
        Tool(
            name=td["name"],
            description=td["description"],
            inputSchema=td["inputSchema"],
        )
        for td in TOOL_DEFINITIONS
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Route tool calls to handlers. All responses are structured JSON."""
    from .tools.thought import (
        handle_forget,
        handle_get_thought,
        handle_learn_preference,
        handle_save_thought,
        handle_start_thought,
        handle_supersede,
    )
    from .tools.recall import handle_recall
    from .tools.navigation import (
        handle_conflicts,
        handle_diff,
        handle_list_trails,
        handle_propose_truth,
        handle_rollback,
        handle_sync,
    )

    try:
        # list_trails doesn't need a trail
        if name == "list_trails":
            result = await handle_list_trails(arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        # All other tools need a trail
        trail = await _get_trail(arguments.get("trail_name"))

        # Check for conflicts before WRITE operations (conflict interception layer)
        # Read-only operations (get_thought, recall, diff) skip this check for performance
        write_ops = {"start_thought", "save_thought", "propose_truth", "forget", "supersede", "learn_preference", "sync"}
        if name in write_ops:
            active_conflicts = await trail.get_conflicts()
            if active_conflicts:
                conflict_result = {
                    "status": "blocked",
                    "message": (
                        f"Operation '{name}' blocked: {len(active_conflicts)} active conflict(s). "
                        "Resolve conflicts before continuing. Use the 'conflicts' tool to see details, "
                        "or 'rollback' to restore a previous state."
                    ),
                    "conflicts": [
                        {"file": c.file_path, "description": c.description}
                        for c in active_conflicts
                    ],
                }
                return [TextContent(type="text", text=json.dumps(conflict_result, indent=2, default=str))]

        # Route to handler
        handlers = {
            "start_thought": lambda: handle_start_thought(trail, arguments),
            "save_thought": lambda: handle_save_thought(trail, arguments),
            "get_thought": lambda: handle_get_thought(trail, arguments),
            "propose_truth": lambda: handle_propose_truth(trail, arguments),
            "recall": lambda: handle_recall(trail, arguments),
            "forget": lambda: handle_forget(trail, arguments),
            "sync": lambda: handle_sync(trail, arguments),
            "conflicts": lambda: handle_conflicts(trail, arguments),
            "rollback": lambda: handle_rollback(trail, arguments),
            "diff": lambda: handle_diff(trail, arguments),
            "learn_preference": lambda: handle_learn_preference(trail, arguments),
            "supersede": lambda: handle_supersede(trail, arguments),
        }

        handler = handlers.get(name)
        if handler is None:
            result = {"status": "error", "message": f"Unknown tool: {name}"}
        else:
            result = await handler()

    except Exception as e:
        logger.exception(f"Tool {name} failed")
        result = {"status": "error", "message": f"Tool '{name}' failed: {str(e)}"}

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


def run():
    """Entry point for fava-trail-server."""
    async def main():
        # Verify JJ installation
        try:
            JjBackend._find_jj()
        except FileNotFoundError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            sys.exit(1)

        # Ensure home directory and initialize monorepo
        ensure_data_repo_root()
        await _init_server()

        logger.info("FAVA Trail MCP Server starting...")
        logger.info(f"Tools: {len(TOOL_DEFINITIONS)}")

        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(main())

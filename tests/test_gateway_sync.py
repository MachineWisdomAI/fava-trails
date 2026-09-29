"""Configured gateway identities can sync without gaining private history access."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from fava_trails import server
from fava_trails.config import ConfigStore
from fava_trails.http_runtime import create_streamable_http_app
from fava_trails.vcs.base import RebaseResult, VcsConflict

PRIVATE = "synthetic-private-bob-draft-not-a-real-secret"


def rpc_result(response):
    assert response.status_code == 200, response.text
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))


@pytest.mark.asyncio
async def test_non_operator_gateway_lists_and_syncs_real_local_remote(trail_manager, tmp_path, monkeypatch):
    private = await trail_manager.save_thought(PRIVATE, agent_id="bob")
    remote = tmp_path / "synthetic-remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    await trail_manager.vcs.add_remote("origin", str(remote))
    await trail_manager.vcs._run("bookmark", "set", "main", "-r", "@-")
    # Seed the bare remote with local bookmarks. Prefer --all over --allow-new:
    # --allow-new was removed in JJ 0.42+; --all still creates new remote bookmarks
    # on both the supported floor (0.28) and current stable.
    await trail_manager.vcs._run("git", "push", "--allow-empty-description", "--all")
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "chatgpt-gateway")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    monkeypatch.setattr(server, "_trail_managers", {trail_manager.trail_name: trail_manager})
    monkeypatch.setattr(server, "_shared_backend", trail_manager.vcs)
    monkeypatch.setattr(server, "_init_server", AsyncMock())

    with TestClient(create_streamable_http_app()) as client:
        headers = {"Accept": "application/json, text/event-stream"}
        response = client.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-gateway", "version": "1"},
                },
            },
        )
        initialized = rpc_result(response)
        assert "tools" in initialized["result"]["capabilities"]
        headers.update({"Mcp-Session-Id": response.headers["mcp-session-id"], "MCP-Protocol-Version": "2025-11-25"})
        notified = client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert notified.status_code == 202
        listed = rpc_result(
            client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        )
        assert "sync" in {tool["name"] for tool in listed["result"]["tools"]}

        def call_tool(name, arguments, request_id):
            payload = rpc_result(
                client.post(
                    "/mcp/",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    },
                )
            )
            assert "result" in payload, payload
            assert PRIVATE not in json.dumps(payload)
            return payload["result"]

        synced = call_tool("sync", {"trail_name": trail_manager.trail_name}, 3)
        assert synced["structuredContent"]["status"] == "ok"
        assert synced["structuredContent"]["message"] == "Sync complete."
        missing = call_tool("sync", {}, 4)
        assert "trail_name" in json.dumps(missing)
        for index, name in enumerate(("rollback", "forget", "diff", "conflicts"), 5):
            blocked = call_tool(name, {"trail_name": trail_manager.trail_name}, index)
            assert blocked["structuredContent"]["status"] == "error"
            assert "operator" in blocked["structuredContent"]["message"]
        hidden = call_tool(
            "get_thought", {"trail_name": trail_manager.trail_name, "thought_id": private.thought_id}, 10
        )
        assert hidden["structuredContent"]["status"] == "error"
        history = call_tool("recall", {"trail_name": trail_manager.trail_name, "mode": "history"}, 11)
        assert history["structuredContent"]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,expected",
    [
        (RebaseResult(success=False, has_dirty_working_copy=True, dirty_paths=[PRIVATE], summary=PRIVATE), "blocked"),
        (
            RebaseResult(
                success=False, has_case_collisions=True, case_collisions=[[PRIVATE, PRIVATE.upper()]], summary=PRIVATE
            ),
            "blocked",
        ),
        (
            RebaseResult(
                success=False, has_conflicts=True, conflict_details=[VcsConflict(PRIVATE, PRIVATE)], summary=PRIVATE
            ),
            "conflict",
        ),
        (RebaseResult(success=False, summary=PRIVATE), "error"),
        (RuntimeError(PRIVATE), "error"),
    ],
)
async def test_gateway_sync_withholds_private_repository_diagnostics(trail_manager, monkeypatch, outcome, expected):
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "chatgpt-gateway")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    monkeypatch.setattr(server, "_trail_managers", {trail_manager.trail_name: trail_manager})
    monkeypatch.setattr(trail_manager, "get_conflicts", AsyncMock(return_value=[]))
    sync = AsyncMock(side_effect=outcome) if isinstance(outcome, Exception) else AsyncMock(return_value=outcome)
    monkeypatch.setattr(trail_manager, "sync", sync)
    result = await server.handle_call_tool("sync", {"trail_name": trail_manager.trail_name})
    sync.assert_awaited_once()
    assert result["status"] == expected
    assert PRIVATE not in json.dumps(result)
    assert not {"conflicts", "dirty_paths", "case_collisions"}.intersection(result)


@pytest.mark.asyncio
async def test_gateway_sync_preexisting_conflicts_and_push_warnings_are_private(trail_manager, monkeypatch):
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "chatgpt-gateway")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    monkeypatch.setattr(server, "_trail_managers", {trail_manager.trail_name: trail_manager})
    conflicts = AsyncMock(return_value=[VcsConflict(PRIVATE, PRIVATE)])
    monkeypatch.setattr(trail_manager, "get_conflicts", conflicts)
    sync = AsyncMock(return_value=RebaseResult(success=True))
    monkeypatch.setattr(trail_manager, "sync", sync)
    result = await server.handle_call_tool("sync", {"trail_name": trail_manager.trail_name})
    assert result["status"] == "blocked"
    assert PRIVATE not in json.dumps(result)
    sync.assert_not_awaited()

    conflicts.return_value = []
    monkeypatch.setattr(server, "_shared_backend", trail_manager.vcs)
    monkeypatch.setattr(
        trail_manager.vcs, "try_push", AsyncMock(return_value={"status": "warning", "message": PRIVATE})
    )
    ConfigStore.get().global_config.push_strategy = "immediate"
    result = await server.handle_call_tool("sync", {"trail_name": trail_manager.trail_name})
    assert result["status"] == "ok"
    assert "push_warning" in result
    assert PRIVATE not in json.dumps(result)


@pytest.mark.asyncio
async def test_unconfigured_gateway_cannot_sync(trail_manager, monkeypatch):
    monkeypatch.delenv("FAVA_TRAILS_AGENT_ID", raising=False)
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    sync = AsyncMock()
    monkeypatch.setattr(trail_manager, "sync", sync)
    result = await server.handle_call_tool("sync", {"trail_name": trail_manager.trail_name})
    assert result["status"] == "error"
    assert "FAVA_TRAILS_AGENT_ID" in result["message"]
    sync.assert_not_awaited()

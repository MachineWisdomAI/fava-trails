"""Exercise ordinary gateway governance over real HTTP, storage and local Git sync."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from fava_trails import server
from fava_trails.http_runtime import create_streamable_http_app
from fava_trails.tools import navigation
from fava_trails.trust_gate import TrustResult


@pytest.fixture
def gateway_repo(tmp_fava_home, tmp_path, monkeypatch):
    """Keep all storage and sync real; only the external LLM response is synthetic."""
    monkeypatch.setenv("FAVA_TRAILS_DIR", str(tmp_fava_home / "trails"))
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "synthetic-gateway")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    monkeypatch.setenv("FAVA_TRAILS_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SYNTHETIC_TRUST_GATE_KEY", "test-only-key")
    (tmp_fava_home / "config.yaml").write_text(
        "trails_dir: trails\ntrust_gate: llm-oneshot\npush_strategy: manual\n"
        "trust_gate_api_key_env: SYNTHETIC_TRUST_GATE_KEY\n"
    )
    (tmp_fava_home / "trails" / "trust-gate-prompt.md").write_text("Synthetic review policy.\n")
    (tmp_fava_home / ".gitignore").write_text(".jj/\n")

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_fava_home, check=True, capture_output=True, text=True,
        )

    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    git("add", ".")
    git("-c", "user.name=Synthetic Gateway", "-c", "user.email=synthetic@example.invalid",
        "commit", "-m", "Synthetic gateway fixture")
    git("remote", "add", "origin", str(remote))
    git("push", "origin", "HEAD:refs/heads/main")
    review = AsyncMock(return_value=TrustResult(
        verdict="approve", reasoning="Synthetic evaluator result", reviewer="synthetic-reviewer",
    ))
    monkeypatch.setattr(navigation, "review_thought", review)
    monkeypatch.setattr(server, "_trail_managers", {})
    monkeypatch.setattr(server, "_trail_init_lock", None)
    return tmp_fava_home, review


def http_rpc(client, version):
    headers = {"Accept": "application/json, text/event-stream"}
    next_id = 0

    def rpc(method, params=None, *, notification=False):
        nonlocal next_id
        next_id += 1
        request = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        if not notification:
            request["id"] = next_id
        response = client.post("/mcp/", json=request, headers=headers)
        if "mcp-session-id" in response.headers:
            headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        if notification:
            assert response.status_code == 202, response.text
            return None
        assert response.status_code == 200, response.text
        if "text/event-stream" in response.headers["content-type"]:
            payload = json.loads(next(
                line[6:] for line in response.text.splitlines() if line.startswith("data: ")
            ))
        else:
            payload = response.json()
        assert payload["id"] == next_id
        assert "result" in payload, payload
        return payload["result"]

    initialized = rpc("initialize", {
        "protocolVersion": version, "capabilities": {},
        "clientInfo": {"name": "synthetic-http-gateway", "version": "1"},
    })
    assert initialized["protocolVersion"] == version
    headers["MCP-Protocol-Version"] = version
    rpc("notifications/initialized", notification=True)
    return rpc


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-11-25"])
def test_http_discover_draft_review_sync_and_governed_readback(gateway_repo, version):
    repo, review = gateway_repo
    scope = "synthetic/gateway"
    with TestClient(create_streamable_http_app()) as client:
        rpc = http_rpc(client, version)
        listed = rpc("tools/list")
        assert {"list_scopes", "save_thought", "propose_truth", "sync", "get_thought", "recall"} <= {
            tool["name"] for tool in listed["tools"]
        }

        def call(name, arguments):
            result = rpc("tools/call", {"name": name, "arguments": arguments})
            assert not result.get("isError", False), result
            assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
            return result["structuredContent"]

        invalid = rpc("tools/call", {"name": "save_thought", "arguments": {"content": "missing scope"}})
        assert invalid["isError"] is True
        assert not (repo / "trails" / scope).exists()
        assert call("list_scopes", {})["scopes"] == []
        assert call("recall", {"trail_name": scope})["status"] == "error"
        assert not (repo / "trails" / scope).exists()
        saved = call("save_thought", {"trail_name": scope, "content": "Synthetic gateway acceptance."})
        thought_id = saved["thought"]["thought_id"]
        assert saved["thought"]["agent_id"] == "synthetic-gateway"
        assert call("list_scopes", {"prefix": "synthetic"})["scopes"] == [{"path": scope}]
        assert call("recall", {"trail_name": scope})["count"] == 0
        assert call("get_thought", {"trail_name": scope, "thought_id": thought_id})["status"] == "error"
        owned = call("get_thought", {"trail_name": scope, "thought_id": thought_id, "mode": "authoring"})
        assert owned["thought"]["validation_status"] == "draft"
        for name, arguments in (
            ("recall", {"mode": "history"}),
            ("save_thought", {"content": "spoof", "agent_id": "another-agent"}),
            ("rollback", {"op_id": "must-not-run"}),
            ("forget", {}),
            ("propose_truth", {"thought_id": thought_id, "approval": "human"}),
        ):
            denied = call(name, {"trail_name": scope, **arguments})
            assert denied["status"] == "error", denied
        review.assert_not_awaited()
        proposed = call("propose_truth", {"trail_name": scope, "thought_id": thought_id})
        assert proposed["status"] == "ok", proposed
        assert proposed["thought"]["validation_status"] == "approved"
        review.assert_awaited_once()
        assert call("sync", {"trail_name": scope}) == {"status": "ok", "message": "Sync complete."}
        recalled = call("recall", {"trail_name": scope})
        assert [thought["thought_id"] for thought in recalled["thoughts"]] == [thought_id]
        assert call("get_thought", {"trail_name": scope, "thought_id": thought_id})["thought"]["validation_status"] == "approved"


def test_http_sync_refuses_dirty_repository_without_disclosing_paths(gateway_repo):
    repo, _ = gateway_repo
    with TestClient(create_streamable_http_app()) as client:
        rpc = http_rpc(client, "2025-03-26")
        saved = rpc("tools/call", {"name": "save_thought", "arguments": {
            "trail_name": "synthetic/gateway", "content": "Synthetic sync fixture",
        }})
        assert saved["structuredContent"]["status"] == "ok"
        private_path = repo / "operator-private-fixture.txt"
        private_path.write_text("Synthetic uncommitted bytes")
        blocked = rpc("tools/call", {"name": "sync", "arguments": {"trail_name": "synthetic/gateway"}})
        assert not blocked.get("isError", False)
        assert blocked["structuredContent"] == {
            "status": "blocked",
            "message": "Sync blocked by uncommitted repository changes. Operator attention is required.",
        }
        assert "operator-private-fixture" not in json.dumps(blocked)
        assert private_path.read_text() == "Synthetic uncommitted bytes"

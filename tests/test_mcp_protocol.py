"""SDK upgrades must preserve the real executable and both protocol generations."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import jsonschema
import pytest
import pytest_asyncio
from mcp import Client

from fava_trails import server


def _server_executable() -> Path:
    executable = Path(sys.executable).parent / "fava-trails-server"
    assert executable.is_file(), "The installed package must provide its console entrypoint"
    if os.environ.get("FAVA_EXPECT_WHEEL") == "1":
        assert "site-packages" in Path(server.__file__).parts
    return executable


def _base_server_env(tmp_fava_home: Path, tmp_path: Path, agent_id: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("FAVA_TRAILS_")}
    env.update(
        {
            "FAVA_TRAILS_DATA_REPO": str(tmp_fava_home),
            "FAVA_TRAILS_DIR": str(tmp_fava_home / "trails"),
            "FAVA_TRAILS_LOG_DIR": str(tmp_path / "logs" / agent_id),
            "FAVA_TRAILS_AGENT_ID": agent_id,
            "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
            # Ensure registration command resolution finds the installed entrypoint.
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
        }
    )
    return env


class _StdioRpc:
    """JSON-RPC helper over a live stdio MCP process."""

    def __init__(self, process: asyncio.subprocess.Process, stderr_path: Path):
        self.process = process
        self.stderr_path = stderr_path
        self._next_id = 0

    async def rpc(self, method, params=None, *, notification=False):
        self._next_id += 1
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            message["id"] = self._next_id
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()
        if notification:
            return None
        async with asyncio.timeout(30):
            while True:
                line = await self.process.stdout.readline()
                assert line, self.stderr_path.read_text()
                response = json.loads(line)
                if response.get("id") == self._next_id:
                    assert "result" in response, response
                    return response["result"]

    async def call_tool(self, name: str, arguments: dict):
        return await self.rpc("tools/call", {"name": name, "arguments": arguments})

    async def close(self):
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await asyncio.wait_for(self.process.wait(), 5)


async def _spawn_stdio_rpc(
    *,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str],
    cwd: Path,
    stderr_path: Path,
) -> _StdioRpc:
    """Start an MCP server process the same way a native client would."""
    resolved = shutil.which(command, path=env.get("PATH"))
    assert resolved, f"native registration command not found on PATH: {command}"
    argv = [resolved, *(args or [])]
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stderr_path.open("wb") as stderr:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr,
        )
    return _StdioRpc(process, stderr_path)


@pytest_asyncio.fixture
async def stdio_rpc(tmp_fava_home, tmp_path):
    """Direct stdio probe: launch the installed console script by absolute path.

    This is intentionally *not* a native-client registration load. Prefer
    ``test_native_client_registration_loads_and_initializes`` for the
    config-driven path issue #99 distinguishes from this probe.
    """
    executable = _server_executable()
    env = _base_server_env(tmp_fava_home, tmp_path, "synthetic-wire-agent")
    rpc = await _spawn_stdio_rpc(
        command=str(executable),
        env=env,
        cwd=tmp_path,
        stderr_path=tmp_path / "server-stderr.log",
    )
    try:
        yield rpc.rpc
    finally:
        await rpc.close()


@pytest.mark.asyncio
async def test_installed_stdio_initialize_list_and_call(stdio_rpc, tmp_fava_home):
    initialized = await stdio_rpc(
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "synthetic-legacy-client", "version": "1"},
        },
    )
    assert initialized["protocolVersion"] == "2025-11-25"
    assert "tools" in initialized["capabilities"]
    assert "Governed Visibility" in initialized["instructions"]
    # Handshake serverInfo.version is the FAVA product version, not the MCP SDK.
    server_info = initialized["serverInfo"]
    assert server_info["name"] == "fava-trails"
    assert server_info["version"] == server.server.version
    assert server_info["version"] == __import__("fava_trails").__version__
    import importlib.metadata as _md

    assert server_info["version"] != _md.version("mcp")
    await stdio_rpc("notifications/initialized", notification=True)
    listed = await stdio_rpc("tools/list")
    by_name = {tool["name"]: tool for tool in listed["tools"]}
    assert len(by_name) == 17
    for definition in server.TOOL_DEFINITIONS:
        tool = by_name[definition["name"]]
        assert tool["inputSchema"] == definition["inputSchema"]
        assert tool["outputSchema"] == definition["outputSchema"]
        assert tool["outputSchema"]["type"] == "object"
        for key, value in definition["annotations"].items():
            assert tool["annotations"][key] == value
        jsonschema.Draft202012Validator.check_schema(tool["inputSchema"])
        jsonschema.Draft202012Validator.check_schema(tool["outputSchema"])

    async def call(name, arguments):
        return await stdio_rpc("tools/call", {"name": name, "arguments": arguments})

    guide = await call("get_usage_guide", {})
    assert not guide.get("isError", False)
    assert guide["content"][0]["text"] == guide["structuredContent"]["content"]
    assert guide["content"][0]["text"].startswith("# Using FAVA Trails")

    # Missing required content and wrong types must fail before creating a scope.
    scope = "synthetic/wire"
    for arguments in ({"trail_name": scope}, {"trail_name": scope, "content": 123}):
        invalid = await call("save_thought", arguments)
        assert invalid["isError"] is True
        assert not invalid.get("structuredContent")
        assert "Input validation error" in invalid["content"][0]["text"]
        assert not (tmp_fava_home / "trails" / scope).exists()

    saved = await call("save_thought", {"trail_name": scope, "content": "Synthetic wire draft"})
    assert not saved.get("isError", False)
    assert saved["structuredContent"]["status"] == "ok"
    assert json.loads(saved["content"][0]["text"]) == saved["structuredContent"]
    governed = await call("recall", {"trail_name": scope})
    assert governed["structuredContent"]["count"] == 0
    authoring = await call("recall", {"trail_name": scope, "mode": "authoring"})
    assert authoring["structuredContent"]["count"] == 1
    assert authoring["structuredContent"]["thoughts"][0]["agent_id"] == "synthetic-wire-agent"
    missing = await call("recall", {"trail_name": "synthetic/missing"})
    assert not missing.get("isError", False)
    assert missing["structuredContent"]["status"] == "error"


@pytest.mark.asyncio
async def test_native_client_registration_loads_and_initializes(tmp_fava_home, tmp_path):
    """Issue #99: a real native-client config is loaded, then the registration is launched.

    Distinct from ``test_installed_stdio_initialize_list_and_call``, which probes the
    entrypoint binary directly. Here the client config is the source of truth for
    command/env, matching Claude Code / Claude Desktop ``mcpServers`` shape.
    """
    _server_executable()  # assert entrypoint exists (and wheel layout when requested)
    env = _base_server_env(tmp_fava_home, tmp_path, "native-registration-agent")
    # Claude-style registration: command name only (resolved via PATH), plus process env.
    registration = {
        "mcpServers": {
            "fava-trails": {
                "type": "stdio",
                "command": "fava-trails-server",
                "args": [],
                "env": {
                    "FAVA_TRAILS_DATA_REPO": env["FAVA_TRAILS_DATA_REPO"],
                    "FAVA_TRAILS_DIR": env["FAVA_TRAILS_DIR"],
                    "FAVA_TRAILS_LOG_DIR": env["FAVA_TRAILS_LOG_DIR"],
                    "FAVA_TRAILS_AGENT_ID": env["FAVA_TRAILS_AGENT_ID"],
                },
            }
        }
    }
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(json.dumps(registration, indent=2) + "\n")

    # Native client load step: read the registration file and resolve the server entry.
    loaded = json.loads(config_path.read_text())
    entry = loaded["mcpServers"]["fava-trails"]
    assert entry["command"] == "fava-trails-server"
    assert entry.get("type", "stdio") == "stdio"
    launch_env = dict(env)
    launch_env.update({str(k): str(v) for k, v in entry.get("env", {}).items()})

    rpc = await _spawn_stdio_rpc(
        command=entry["command"],
        args=list(entry.get("args") or []),
        env=launch_env,
        cwd=tmp_path,
        stderr_path=tmp_path / "native-registration-stderr.log",
    )
    try:
        initialized = await rpc.rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "synthetic-claude-desktop", "version": "1"},
            },
        )
        assert initialized["serverInfo"]["name"] == "fava-trails"
        assert initialized["serverInfo"]["version"] == __import__("fava_trails").__version__
        await rpc.rpc("notifications/initialized", notification=True)
        listed = await rpc.rpc("tools/list")
        assert len(listed["tools"]) == 17
        saved = await rpc.call_tool(
            "save_thought",
            {"trail_name": "synthetic/native-reg", "content": "Loaded via native registration"},
        )
        assert not saved.get("isError", False)
        assert saved["structuredContent"]["status"] == "ok"
        assert saved["structuredContent"]["thought"]["agent_id"] == "native-registration-agent"
    finally:
        await rpc.close()


@pytest.mark.asyncio
async def test_two_ordinary_server_processes_isolate_authoring(tmp_fava_home, tmp_path):
    """Issue #99 / #72: two process-scoped ordinary identities on one data repo.

    Unlike in-process monkeypatch swaps of ``FAVA_TRAILS_AGENT_ID``, each identity
    is a separately configured stdio server process (as real MCP registrations are).
    """
    _server_executable()
    scope = "synthetic/process-isolation"
    alice_env = _base_server_env(tmp_fava_home, tmp_path, "alice")
    bob_env = _base_server_env(tmp_fava_home, tmp_path, "bob")

    alice = await _spawn_stdio_rpc(
        command="fava-trails-server",
        env=alice_env,
        cwd=tmp_path,
        stderr_path=tmp_path / "alice-stderr.log",
    )
    bob = await _spawn_stdio_rpc(
        command="fava-trails-server",
        env=bob_env,
        cwd=tmp_path,
        stderr_path=tmp_path / "bob-stderr.log",
    )
    try:
        for rpc, name in ((alice, "alice-client"), (bob, "bob-client")):
            await rpc.rpc(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": name, "version": "1"},
                },
            )
            await rpc.rpc("notifications/initialized", notification=True)

        saved = await alice.call_tool(
            "save_thought",
            {"trail_name": scope, "content": "Alice private draft across process boundary"},
        )
        assert not saved.get("isError", False)
        assert saved["structuredContent"]["thought"]["agent_id"] == "alice"
        thought_id = saved["structuredContent"]["thought"]["thought_id"]

        alice_own = await alice.call_tool("recall", {"trail_name": scope, "mode": "authoring"})
        assert alice_own["structuredContent"]["count"] == 1
        assert alice_own["structuredContent"]["thoughts"][0]["thought_id"] == thought_id

        # Bob's separate process must not see Alice's draft authoring records.
        bob_authoring = await bob.call_tool("recall", {"trail_name": scope, "mode": "authoring"})
        assert bob_authoring["structuredContent"]["count"] == 0
        assert bob_authoring["structuredContent"]["thoughts"] == []

        # Default governed recall hides unapproved drafts for both processes.
        for rpc in (alice, bob):
            governed = await rpc.call_tool("recall", {"trail_name": scope})
            assert governed["structuredContent"]["count"] == 0

        # Caller identity spoofing is rejected at Bob's process boundary.
        spoof = await bob.call_tool(
            "save_thought",
            {"trail_name": scope, "content": "spoof as alice", "agent_id": "alice"},
        )
        assert not spoof.get("isError", False)
        assert spoof["structuredContent"]["status"] == "error"
        spoof_blob = json.dumps(spoof)
        assert "Alice private draft" not in spoof_blob
        assert "does not match" in spoof["structuredContent"]["message"].lower() or "agent_id" in spoof[
            "structuredContent"
        ]["message"]

        bob_get = await bob.call_tool(
            "get_thought",
            {"trail_name": scope, "thought_id": thought_id, "mode": "authoring"},
        )
        assert not bob_get.get("isError", False)
        assert bob_get["structuredContent"]["status"] == "error"
        assert "Alice private draft" not in json.dumps(bob_get)
    finally:
        await alice.close()
        await bob.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_sdk_clients_preserve_validation_and_error_shapes(mode, monkeypatch):
    handler = AsyncMock(return_value={"status": "blocked", "message": "Synthetic conflict"})
    monkeypatch.setattr(server, "handle_call_tool", handler)
    async with Client(server.server, mode=mode, read_timeout_seconds=5) as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 17
        invalid = await client.call_tool("save_thought", {"trail_name": "synthetic/wire", "content": 123})
        assert invalid.is_error
        assert invalid.structured_content is None
        handler.assert_not_awaited()
        blocked = await client.call_tool("sync", {"trail_name": "synthetic/wire"})
        assert not blocked.is_error
        assert blocked.structured_content["status"] == "blocked"
        handler.return_value = {"status": "error", "message": "Synthetic timeout"}
        failed = await client.call_tool("sync", {"trail_name": "synthetic/wire"})
        assert not failed.is_error
        assert failed.structured_content["status"] == "error"
        handler.return_value = {"unexpected": "synthetic-private-rejected-output"}
        malformed = await client.call_tool("sync", {"trail_name": "synthetic/wire"})
        assert malformed.is_error
        assert malformed.structured_content is None
        assert "synthetic-private" not in malformed.model_dump_json()
        handler.side_effect = RuntimeError("synthetic-private-adapter-exception")
        crashed = await client.call_tool("sync", {"trail_name": "synthetic/wire"})
        assert crashed.is_error
        assert crashed.structured_content is None
        assert "synthetic-private" not in crashed.model_dump_json()

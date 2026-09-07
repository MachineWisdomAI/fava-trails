"""SDK upgrades must preserve the real executable and both protocol generations."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import jsonschema
import pytest
import pytest_asyncio
from mcp import Client

from fava_trails import server


@pytest_asyncio.fixture
async def stdio_rpc(tmp_fava_home, tmp_path):
    """Run the installed console script against synthetic data with bounded I/O."""
    executable = Path(sys.executable).parent / "fava-trails-server"
    assert executable.is_file(), "The installed package must provide its console entrypoint"
    if os.environ.get("FAVA_EXPECT_WHEEL") == "1":
        assert "site-packages" in Path(server.__file__).parts
    env = {key: value for key, value in os.environ.items() if not key.startswith("FAVA_TRAILS_")}
    env.update({
        "FAVA_TRAILS_DATA_REPO": str(tmp_fava_home),
        "FAVA_TRAILS_DIR": str(tmp_fava_home / "trails"),
        "FAVA_TRAILS_LOG_DIR": str(tmp_path / "logs"),
        "FAVA_TRAILS_AGENT_ID": "synthetic-wire-agent",
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
    })
    with (tmp_path / "server-stderr.log").open("wb") as stderr:
        process = await asyncio.create_subprocess_exec(
            str(executable), cwd=tmp_path, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
        )
        next_id = 0

        async def rpc(method, params=None, *, notification=False):
            nonlocal next_id
            next_id += 1
            message = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                message["params"] = params
            if not notification:
                message["id"] = next_id
            process.stdin.write((json.dumps(message) + "\n").encode())
            await process.stdin.drain()
            if notification:
                return None
            async with asyncio.timeout(30):
                while True:
                    line = await process.stdout.readline()
                    assert line, (tmp_path / "server-stderr.log").read_text()
                    response = json.loads(line)
                    if response.get("id") == next_id:
                        assert "result" in response, response
                        return response["result"]

        try:
            yield rpc
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await asyncio.wait_for(process.wait(), 5)


@pytest.mark.asyncio
async def test_installed_stdio_initialize_list_and_call(stdio_rpc, tmp_fava_home):
    initialized = await stdio_rpc("initialize", {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "synthetic-legacy-client", "version": "1"},
    })
    assert initialized["protocolVersion"] == "2025-11-25"
    assert "tools" in initialized["capabilities"]
    assert "Governed Visibility" in initialized["instructions"]
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

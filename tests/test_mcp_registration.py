"""Onboarding must stay out of application .env files and register MCP safely."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from fava_trails.mcp_registration import (
    PermissionDenied,
    build_registration,
    format_registration_instructions,
    inspect_native_registration,
    render_diagnostics,
    verify_direct_mcp_smoke,
    verify_native_client_session,
    write_mcp_json_config,
)


def _fake_server(tmp_path: Path, marker: str = "ok") -> Path:
    script = tmp_path / f"fake-server-{marker}"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps({\n"
        "            'jsonrpc': '2.0', 'id': msg.get('id'),\n"
        "            'result': {\n"
        "                'protocolVersion': '2025-11-25',\n"
        "                'capabilities': {'tools': {}},\n"
        "                'serverInfo': {'name': 'fava-trails', 'version': 'test'},\n"
        "            },\n"
        "        }))\n"
        "        sys.stdout.flush()\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_ordinary_registration_uses_agent_id_executable_and_data_repo(tmp_path):
    entry = build_registration(
        executable="/opt/fava/bin/fava-trails-server",
        data_repo=str(tmp_path / "data"),
        agent_id="codex-cli",
    )
    assert entry["command"] == "/opt/fava/bin/fava-trails-server"
    assert entry["env"]["FAVA_TRAILS_DATA_REPO"] == str(tmp_path / "data")
    assert entry["env"]["FAVA_TRAILS_AGENT_ID"] == "codex-cli"
    assert "FAVA_TRAILS_OPERATOR" not in entry["env"]


def test_operator_registration_is_explicit_and_separate(tmp_path):
    ordinary = build_registration(
        executable="fava-trails-server",
        data_repo=str(tmp_path),
        agent_id="codex-cli",
    )
    operator = build_registration(
        executable="fava-trails-server",
        data_repo=str(tmp_path),
        agent_id="codex-cli",
        operator=True,
    )
    assert "FAVA_TRAILS_OPERATOR" not in ordinary["env"]
    assert operator["env"]["FAVA_TRAILS_OPERATOR"] == "1"


def test_instructions_keep_operator_separate_from_ordinary_snippet(tmp_path):
    text = format_registration_instructions(
        executable="/usr/bin/fava-trails-server",
        data_repo=str(tmp_path / "trails-data"),
        agent_id="claude-code",
    )
    assert "/usr/bin/fava-trails-server" in text
    assert str(tmp_path / "trails-data") in text
    assert "FAVA_TRAILS_AGENT_ID" in text
    assert "claude-code" in text
    assert "FAVA_TRAILS_OPERATOR" in text
    ordinary, _, operator = text.partition("Elevated operator")
    assert "FAVA_TRAILS_OPERATOR" not in ordinary
    assert "separate" in operator.lower()


def test_config_writer_preserves_unrelated_servers_and_writes_atomically(tmp_path):
    config = tmp_path / "claude.json"
    config.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "keep-me"}}}))
    entry = build_registration(executable="/bin/fava-trails-server", data_repo="/data", agent_id="claude-code")
    backup = write_mcp_json_config(config, server_name="fava-trails", entry=entry)
    data = json.loads(config.read_text())
    assert data["theme"] == "dark"
    assert data["mcpServers"]["other"] == {"command": "keep-me"}
    assert data["mcpServers"]["fava-trails"]["command"] == "/bin/fava-trails-server"
    assert backup is not None
    assert backup.exists()
    assert json.loads(backup.read_text())["mcpServers"]["other"]["command"] == "keep-me"
    assert not config.with_name(config.name + ".tmp").exists()


def test_config_writer_preserves_restrictive_mode_on_replacement_and_backup(tmp_path):
    config = tmp_path / "claude.json"
    config.write_text(json.dumps({"mcpServers": {}}))
    config.chmod(0o600)
    entry = build_registration(executable="/bin/fava-trails-server", data_repo="/data", agent_id="claude-code")
    backup = write_mcp_json_config(config, server_name="fava-trails", entry=entry)
    assert backup is not None
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_config_writer_creates_new_files_with_owner_only_mode(tmp_path):
    config = tmp_path / "new-client.json"
    entry = build_registration(executable="/bin/fava-trails-server", data_repo="/data", agent_id="claude-code")
    backup = write_mcp_json_config(config, server_name="fava-trails", entry=entry)
    assert backup is None
    assert config.exists()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_config_writer_caps_permissive_mode_at_owner_read_write(tmp_path):
    config = tmp_path / "claude.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "keep-me"}}}))
    config.chmod(0o644)
    entry = build_registration(executable="/bin/fava-trails-server", data_repo="/data", agent_id="claude-code")
    backup = write_mcp_json_config(config, server_name="fava-trails", entry=entry)
    assert backup is not None
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert json.loads(backup.read_text())["mcpServers"]["other"]["command"] == "keep-me"


def test_config_writer_reports_permission_denial_without_bypass(tmp_path):
    config = tmp_path / "locked.json"
    config.write_text("{}")
    config.chmod(0o000)
    entry = build_registration(executable="/bin/fava-trails-server", data_repo="/data", agent_id="claude-code")
    try:
        with pytest.raises(PermissionDenied, match="Permission denied"):
            write_mcp_json_config(config, server_name="fava-trails", entry=entry)
        assert stat.S_IMODE(config.stat().st_mode) == 0o000
    finally:
        config.chmod(0o644)
    assert config.read_text() == "{}"


def test_config_writer_refuses_non_writable_existing_config(tmp_path):
    config = tmp_path / "readonly.json"
    original = json.dumps({"keep": True})
    config.write_text(original)
    config.chmod(0o400)
    entry = build_registration(executable="/bin/fava-trails-server", data_repo="/data", agent_id="claude-code")
    try:
        with pytest.raises(PermissionDenied, match="Permission denied"):
            write_mcp_json_config(config, server_name="fava-trails", entry=entry)
        assert config.read_text() == original
        assert stat.S_IMODE(config.stat().st_mode) == 0o400
        assert not config.with_name(config.name + ".bak").exists()
    finally:
        config.chmod(0o644)


def test_config_writer_opens_secret_files_with_final_mode(tmp_path, monkeypatch):
    created: list[tuple[str, int]] = []
    real_open = os.open

    def tracking_open(path, flags, mode=0o777, *args, **kwargs):
        if flags & os.O_CREAT:
            created.append((Path(path).name, mode & 0o777))
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", tracking_open)
    old_umask = os.umask(0)
    try:
        config = tmp_path / "claude.json"
        config.write_text(json.dumps({"mcpServers": {}}))
        config.chmod(0o600)
        entry = build_registration(executable="/bin/fava-trails-server", data_repo="/data", agent_id="claude-code")
        write_mcp_json_config(config, server_name="fava-trails", entry=entry)
    finally:
        os.umask(old_umask)
    secret_creates = [(name, mode) for name, mode in created if name.endswith((".bak", ".tmp"))]
    assert secret_creates
    assert all(mode == 0o600 for _name, mode in secret_creates)
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.with_name(config.name + ".bak").stat().st_mode) == 0o600


def test_inspect_reports_registration_not_loaded(tmp_path):
    config = tmp_path / "claude.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    report = inspect_native_registration(config, current_executable="/bin/fava-trails-server")
    assert report["status"] == "registration_not_loaded"


def test_inspect_reports_stale_runtime_path(tmp_path):
    config = tmp_path / "claude.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fava-trails": {"command": "/old/runtime/fava-trails-server", "env": {"FAVA_TRAILS_AGENT_ID": "x"}}
                }
            }
        )
    )
    report = inspect_native_registration(config, current_executable="/new/runtime/fava-trails-server")
    assert report["status"] == "stale_runtime_path"
    assert report["registered_command"] == "/old/runtime/fava-trails-server"
    assert report["current_executable"] == "/new/runtime/fava-trails-server"


def test_diagnostics_do_not_expose_secret_environment_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret-do-not-leak")
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "codex-cli")
    config = tmp_path / "claude.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fava-trails": {
                        "command": "/old/fava-trails-server",
                        "env": {"OPENROUTER_API_KEY": "sk-secret-do-not-leak"},
                    }
                }
            }
        )
    )
    report = inspect_native_registration(config, current_executable="/new/fava-trails-server")
    text = render_diagnostics(
        {
            "direct_mcp_smoke": {"verified": "direct_mcp_smoke", "ok": True},
            "inspector_config_load": report,
        }
    )
    assert "sk-secret-do-not-leak" not in text
    assert "stale_runtime_path" in text
    assert "direct_mcp_smoke" in text
    assert "native_client_session" not in text


def test_direct_mcp_smoke_labels_what_was_verified(tmp_path):
    server = _fake_server(tmp_path, "direct")
    result = verify_direct_mcp_smoke(str(server), env={"FAVA_TRAILS_DATA_REPO": str(tmp_path)})
    assert result["verified"] == "direct_mcp_smoke"
    assert result["ok"] is True


def test_native_session_reports_not_loaded_without_spawning(tmp_path):
    config = tmp_path / "missing.json"
    result = verify_native_client_session(config, current_executable="/bin/fava-trails-server")
    assert result["verified"] == "inspector_config_load"
    assert result["ok"] is False
    assert result["status"] == "registration_not_loaded"


def test_native_session_does_not_spawn_registered_command_as_the_client(tmp_path):
    """Direct stdio of the registered command is not a native client session."""
    marker = tmp_path / "spawned"
    server = tmp_path / "fake-server-native"
    server.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('spawned')\n"
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps({\n"
        "            'jsonrpc': '2.0', 'id': msg.get('id'),\n"
        "            'result': {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},\n"
        "                       'serverInfo': {'name': 'fava-trails', 'version': 'test'}},\n"
        "        }))\n"
        "        sys.stdout.flush()\n"
    )
    server.chmod(server.stat().st_mode | stat.S_IEXEC)
    config = tmp_path / "claude.json"
    write_mcp_json_config(
        config,
        server_name="fava-trails",
        entry=build_registration(executable=str(server), data_repo=str(tmp_path), agent_id="claude-code"),
    )
    result = verify_native_client_session(
        config,
        current_executable=str(server),
        client_probe=lambda *_args: {"ok": False, "status": "inspector_unavailable"},
    )
    assert not marker.exists()
    assert result["verified"] == "inspector_config_load"
    assert result["ok"] is False
    assert result["status"] == "inspector_unavailable"


def test_native_session_uses_injected_client_probe(tmp_path):
    config = tmp_path / "claude.json"
    write_mcp_json_config(
        config,
        server_name="fava-trails",
        entry=build_registration(executable="/bin/fava-trails-server", data_repo=str(tmp_path), agent_id="claude-code"),
    )
    calls: list[tuple[str, str]] = []

    def probe(config_path, server_name):
        calls.append((str(config_path), server_name))
        return {"ok": True, "status": "loaded"}

    result = verify_native_client_session(
        config,
        current_executable="/bin/fava-trails-server",
        client_probe=probe,
    )
    assert calls == [(str(config), "fava-trails")]
    assert result["verified"] == "inspector_config_load"
    assert result["ok"] is True
    assert result["status"] == "loaded"
    assert result.get("client") != "claude-code"


def test_inspector_unavailable_is_not_collapsed_into_native_client(tmp_path, monkeypatch):
    config = tmp_path / "claude.json"
    write_mcp_json_config(
        config,
        server_name="fava-trails",
        entry=build_registration(executable="/bin/fava-trails-server", data_repo=str(tmp_path), agent_id="claude-code"),
    )
    monkeypatch.setattr("fava_trails.mcp_registration.shutil.which", lambda _name: None)
    result = verify_native_client_session(config, current_executable="/bin/fava-trails-server")
    assert result["verified"] == "inspector_config_load"
    assert result["ok"] is False
    assert result["status"] == "inspector_unavailable"
    assert result.get("status") != "native_client_unavailable"


def test_inspector_and_server_failures_keep_distinct_status(tmp_path, monkeypatch):
    config = tmp_path / "claude.json"
    write_mcp_json_config(
        config,
        server_name="fava-trails",
        entry=build_registration(executable="/bin/fava-trails-server", data_repo=str(tmp_path), agent_id="claude-code"),
    )
    monkeypatch.setattr("fava_trails.mcp_registration.shutil.which", lambda name: f"/usr/bin/{name}")

    class _Failed:
        returncode = 1
        stdout = ""
        stderr = "inspector exploded"

    monkeypatch.setattr("fava_trails.mcp_registration.subprocess.run", lambda *args, **kwargs: _Failed())
    failed = verify_native_client_session(config, current_executable="/bin/fava-trails-server")
    assert failed["verified"] == "inspector_config_load"
    assert failed["status"] == "inspector_failed"

    class _ServerMiss:
        returncode = 0
        stdout = json.dumps({"error": {"message": "initialize failed"}})
        stderr = ""

    monkeypatch.setattr("fava_trails.mcp_registration.subprocess.run", lambda *args, **kwargs: _ServerMiss())
    server_miss = verify_native_client_session(config, current_executable="/bin/fava-trails-server")
    assert server_miss["verified"] == "inspector_config_load"
    assert server_miss["status"] == "server_initialize_failed"


def _inspector_result(stderr: str, stdout: str = "", returncode: int = 1):
    class _Completed:
        def __init__(self):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    return _Completed()


def test_inspector_nonzero_and_non_json_keep_actionable_categories(tmp_path, monkeypatch):
    config = tmp_path / "claude.json"
    write_mcp_json_config(
        config,
        server_name="fava-trails",
        entry=build_registration(executable="/bin/fava-trails-server", data_repo=str(tmp_path), agent_id="claude-code"),
    )
    monkeypatch.setattr("fava_trails.mcp_registration.shutil.which", lambda name: f"/usr/bin/{name}")
    secret = "sk-live-not-for-output"

    cases = [
        (
            "config_load_failed",
            json.dumps({"error": {"code": "error", "message": "Error loading configuration: Config file not found"}}),
        ),
        (
            "server_spawn_failed",
            json.dumps({"error": {"code": "error", "message": "spawn /no/such/server-bin ENOENT"}}),
        ),
        (
            "server_initialize_failed",
            json.dumps({"error": {"code": "error", "message": "Connection closed"}}),
        ),
        (
            "inspector_invocation_failed",
            "npm ERR! code E404\nnpm ERR! 404 Not Found - GET https://registry.npmjs.org/@modelcontextprotocol/inspector",
        ),
        (
            "config_load_failed",
            "Downloading inspector...\n"
            + json.dumps(
                {"error": {"code": "error", "message": "Error loading configuration: Config file not found"}}
            ),
        ),
        (
            "server_spawn_failed",
            json.dumps([{"noise": True}])
            + "\n"
            + json.dumps({"error": {"code": "error", "message": "spawn /no/such/server-bin ENOENT"}}),
        ),
    ]
    for status, stderr in cases:
        monkeypatch.setattr(
            "fava_trails.mcp_registration.subprocess.run",
            lambda *args, _stderr=stderr, **kwargs: _inspector_result(stderr=_stderr + f"\n{secret}"),
        )
        result = verify_native_client_session(config, current_executable="/bin/fava-trails-server")
        assert result["verified"] == "inspector_config_load"
        assert result["ok"] is False
        assert result["status"] == status
        dumped = json.dumps(result)
        assert secret not in dumped
        assert "ENOENT" not in dumped
        assert "Config file not found" not in dumped
        assert "npm ERR" not in dumped


def test_register_cli_prints_instructions_without_writing(tmp_path, capsys, monkeypatch):
    from fava_trails.cli import cmd_register

    monkeypatch.setattr("fava_trails.cli.resolve_server_executable", lambda: "/opt/bin/fava-trails-server")
    with patch("fava_trails.cli.get_data_repo_root", return_value=tmp_path / "data"):
        rc = cmd_register(
            type("Args", (), {"write": False, "config": str(tmp_path / "claude.json"), "agent_id": "codex-cli", "verify": False, "operator": False, "client": "claude-code"})()
        )
    assert rc == 0
    assert not (tmp_path / "claude.json").exists()
    out = capsys.readouterr().out
    assert "/opt/bin/fava-trails-server" in out
    assert "FAVA_TRAILS_AGENT_ID" in out
    assert "codex-cli" in out


def test_register_fails_when_executable_cannot_be_resolved(tmp_path, capsys, monkeypatch):
    from fava_trails.cli import cmd_register

    monkeypatch.setattr("fava_trails.cli.resolve_server_executable", lambda: None)
    config = tmp_path / "claude.json"
    with patch("fava_trails.cli.get_data_repo_root", return_value=tmp_path / "data"):
        rc = cmd_register(
            type(
                "Args",
                (),
                {
                    "write": True,
                    "config": str(config),
                    "agent_id": "codex-cli",
                    "verify": False,
                    "operator": False,
                    "client": "claude-code",
                    "executable": None,
                },
            )()
        )
    assert rc == 1
    assert not config.exists()
    err = capsys.readouterr().err
    assert "fava-trails-server" in err
    assert "--executable" in err


def test_register_uses_explicit_executable_when_unresolved(tmp_path, capsys, monkeypatch):
    from fava_trails.cli import cmd_register

    monkeypatch.setattr("fava_trails.cli.resolve_server_executable", lambda: None)
    executable = _fake_server(tmp_path, "explicit")
    with patch("fava_trails.cli.get_data_repo_root", return_value=tmp_path / "data"):
        rc = cmd_register(
            type(
                "Args",
                (),
                {
                    "write": False,
                    "config": str(tmp_path / "claude.json"),
                    "agent_id": "codex-cli",
                    "verify": False,
                    "operator": False,
                    "client": "claude-code",
                    "executable": str(executable),
                },
            )()
        )
    assert rc == 0
    out = capsys.readouterr().out
    assert str(executable.resolve()) in out


def test_register_rejects_missing_explicit_executable(tmp_path, capsys, monkeypatch):
    from fava_trails.cli import cmd_register

    monkeypatch.setattr("fava_trails.cli.resolve_server_executable", lambda: None)
    missing = tmp_path / "missing-server"
    config = tmp_path / "claude.json"
    with patch("fava_trails.cli.get_data_repo_root", return_value=tmp_path / "data"):
        rc = cmd_register(
            type(
                "Args",
                (),
                {
                    "write": True,
                    "config": str(config),
                    "agent_id": "codex-cli",
                    "verify": False,
                    "operator": False,
                    "client": "claude-code",
                    "executable": str(missing),
                },
            )()
        )
    assert rc == 1
    assert not config.exists()
    captured = capsys.readouterr()
    assert "existing executable" in captured.err
    assert str(missing) not in captured.out
    assert str(missing) not in captured.err


def test_register_rejects_non_executable_explicit_path(tmp_path, capsys, monkeypatch):
    from fava_trails.cli import cmd_register

    monkeypatch.setattr("fava_trails.cli.resolve_server_executable", lambda: None)
    not_exec = tmp_path / "not-exec"
    not_exec.write_text("#!/bin/sh\n")
    config = tmp_path / "claude.json"
    with patch("fava_trails.cli.get_data_repo_root", return_value=tmp_path / "data"):
        rc = cmd_register(
            type(
                "Args",
                (),
                {
                    "write": False,
                    "config": str(config),
                    "agent_id": "codex-cli",
                    "verify": False,
                    "operator": False,
                    "client": "claude-code",
                    "executable": str(not_exec),
                },
            )()
        )
    assert rc == 1
    captured = capsys.readouterr()
    assert "existing executable" in captured.err
    assert str(not_exec) not in captured.out


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_data_repo_template_does_not_route_overrides_through_env_files():
    template_dir = _REPO_ROOT / "src" / "fava_trails" / "data_repo_template"
    content = (template_dir / "agents-guide.md").read_text()
    assert "via `.env`" not in content
    assert "write it to `.env`" not in content
    assert "write it to .env" not in content


@pytest.mark.xfail(
    reason="Root AGENTS.md still instructs writing FAVA_TRAILS_SCOPE to .env; agent workspaces cannot edit AGENTS.md basenames.",
    strict=True,
)
def test_authoritative_agents_md_does_not_instruct_writing_env():
    content = (_REPO_ROOT / "AGENTS.md").read_text()
    assert "write it to `.env`" not in content
    assert "write it to .env" not in content
    assert "FAVA_TRAILS_SCOPE=<scope>" not in content

"""Onboarding must stay out of application .env files and register MCP safely."""

from __future__ import annotations

import json
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
            "native_client_session": report,
        }
    )
    assert "sk-secret-do-not-leak" not in text
    assert "stale_runtime_path" in text
    assert "direct_mcp_smoke" in text


def test_direct_mcp_smoke_labels_what_was_verified(tmp_path):
    server = _fake_server(tmp_path, "direct")
    result = verify_direct_mcp_smoke(str(server), env={"FAVA_TRAILS_DATA_REPO": str(tmp_path)})
    assert result["verified"] == "direct_mcp_smoke"
    assert result["ok"] is True


def test_native_session_reports_not_loaded_without_spawning(tmp_path):
    config = tmp_path / "missing.json"
    result = verify_native_client_session(config, current_executable="/bin/fava-trails-server")
    assert result["verified"] == "native_client_session"
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
        client_probe=lambda *_args: {"ok": False, "status": "native_client_unavailable"},
    )
    assert not marker.exists()
    assert result["verified"] == "native_client_session"
    assert result["ok"] is False
    assert result["status"] == "native_client_unavailable"


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
    assert result["verified"] == "native_client_session"
    assert result["ok"] is True
    assert result["status"] == "loaded"


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


_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_data_repo_template_does_not_route_overrides_through_env_files():
    template_dir = _REPO_ROOT / "src" / "fava_trails" / "data_repo_template"
    content = (template_dir / "agents-guide.md").read_text()
    assert "via `.env`" not in content
    assert "write it to `.env`" not in content
    assert "write it to .env" not in content

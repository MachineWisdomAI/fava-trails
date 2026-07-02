"""Tests for the fava-trails-tunnel CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from fava_trails import tunnel_cli
from fava_trails.config import ConfigStore
from fava_trails.http_runtime import create_streamable_http_app
from fava_trails.tunnel_cli import (
    DEFAULT_HOST,
    DEFAULT_MCP_PATH,
    DEFAULT_PORT,
    DEFAULT_PROFILE,
    _load_gateway_config,
    _runtime_env,
    cmd_run,
    cmd_start,
    cmd_status,
    cmd_stop,
)


def _args(**overrides):
    values = {
        "data_repo": None,
        "profile": DEFAULT_PROFILE,
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "mcp_path": DEFAULT_MCP_PATH,
        "tunnel_client": "tunnel-client",
        "ready_timeout": 0.1,
        "tunnel_doctor": False,
        "state_dir": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _make_data_repo(tmp_path: Path, *, openrouter_env: str = "OPENROUTER_API_KEY") -> Path:
    data_repo = tmp_path / "fava-trails-data"
    data_repo.mkdir()
    (data_repo / "trails").mkdir()
    (data_repo / "config.yaml").write_text(
        f"trails_dir: trails\nopenrouter_api_key_env: {openrouter_env}\n"
    )
    return data_repo


def test_load_gateway_config_requires_explicit_data_repo(monkeypatch):
    monkeypatch.delenv("FAVA_TRAILS_DATA_REPO", raising=False)

    with pytest.raises(ValueError, match="FAVA_TRAILS_DATA_REPO is required"):
        _load_gateway_config(_args())


def test_load_gateway_config_validates_trust_gate_env(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                _load_gateway_config(_args(data_repo=str(data_repo)))


def test_load_gateway_config_builds_loopback_mcp_url(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            config = _load_gateway_config(_args(data_repo=str(data_repo)))

    assert config.data_repo == data_repo.resolve()
    assert config.trails_dir == data_repo / "trails"
    assert config.mcp_url == "http://127.0.0.1:8765/mcp"
    assert config.profile == "fava-trails"


def test_load_gateway_config_rejects_non_loopback_host(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with pytest.raises(ValueError, match="loopback"):
                _load_gateway_config(_args(data_repo=str(data_repo), host="0.0.0.0"))


def test_runtime_env_uses_user_log_dir_by_default(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("FAVA_TRAILS_LOG_DIR", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            config = _load_gateway_config(_args(data_repo=str(data_repo)))

    env = _runtime_env(config)

    assert env["FAVA_TRAILS_DATA_REPO"] == str(data_repo.resolve())
    assert env["FAVA_TRAILS_LOG_DIR"] == str(Path.home() / ".fava-trails" / "logs")


def test_run_starts_http_and_runs_tunnel_without_doctor_by_default(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    args = _args(data_repo=str(data_repo))

    http_process = MagicMock()
    http_process.poll.return_value = None
    http_process.pid = 111
    tunnel_process = MagicMock()
    tunnel_process.wait.return_value = 0
    tunnel_process.poll.return_value = 0
    tunnel_process.pid = 222

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("fava_trails.tunnel_cli._start_http_runtime", return_value=http_process) as start_http:
                    with patch("fava_trails.tunnel_cli._wait_for_health") as wait_health:
                        with patch("subprocess.run") as run:
                            with patch("fava_trails.tunnel_cli._start_tunnel_client", return_value=tunnel_process) as start_tunnel:
                                rc = cmd_run(args)

    assert rc == 0
    start_http.assert_called_once()
    wait_health.assert_called_once()
    run.assert_not_called()
    start_tunnel.assert_called_once()


def test_run_checks_doctor_when_requested(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    args = _args(data_repo=str(data_repo), tunnel_doctor=True)

    http_process = MagicMock()
    http_process.poll.return_value = None
    http_process.pid = 111
    tunnel_process = MagicMock()
    tunnel_process.wait.return_value = 0
    tunnel_process.poll.return_value = 0
    tunnel_process.pid = 222

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("fava_trails.tunnel_cli._start_http_runtime", return_value=http_process):
                    with patch("fava_trails.tunnel_cli._wait_for_health"):
                        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as run:
                            with patch("fava_trails.tunnel_cli._start_tunnel_client", return_value=tunnel_process):
                                rc = cmd_run(args)

    assert rc == 0
    run.assert_called_once()


def test_start_writes_state_and_pid(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    args = _args(data_repo=str(data_repo))

    process = MagicMock()
    process.pid = 4321
    process.poll.return_value = None

    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)

    def fake_popen(*args, **kwargs):
        state_dir.mkdir(parents=True, exist_ok=True)
        tunnel_cli._ready_file(state_dir).write_text('{"status":"ready"}\n')
        return process

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("subprocess.Popen", side_effect=fake_popen):
                    rc = cmd_start(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "OpenAI Secure MCP Tunnel" in out
    assert "Supervisor PID: 4321" in out
    state_dirs = list((tmp_path / "state" / "fava-trails" / "tunnel").iterdir())
    assert len(state_dirs) == 1
    assert (state_dirs[0] / "supervisor.pid").read_text() == "4321\n"
    assert "http://127.0.0.1:8765/mcp" in (state_dirs[0] / "metadata.json").read_text()


def test_start_passes_tunnel_doctor_to_supervisor_when_requested(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    args = _args(data_repo=str(data_repo), tunnel_doctor=True)

    process = MagicMock()
    process.pid = 4321
    process.poll.return_value = None

    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)

    def fake_popen(command, *args, **kwargs):
        state_dir.mkdir(parents=True, exist_ok=True)
        tunnel_cli._ready_file(state_dir).write_text('{"status":"ready"}\n')
        assert "--tunnel-doctor" in command
        return process

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("subprocess.Popen", side_effect=fake_popen):
                    rc = cmd_start(args)

    assert rc == 0


def test_status_reports_not_running_for_missing_pid(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    with patch("fava_trails.tunnel_cli._load_gateway_config", side_effect=AssertionError):
        rc = cmd_status(_args(data_repo=str(data_repo)))

    assert rc == 1
    assert "not running" in capsys.readouterr().out


def test_stop_does_not_require_startup_only_environment(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)
    state_dir.mkdir(parents=True)
    tunnel_cli._pid_file(state_dir).write_text("4321\n")

    with patch("fava_trails.tunnel_cli._load_gateway_config", side_effect=AssertionError):
        with patch("fava_trails.tunnel_cli._is_pid_running", side_effect=[True, False, False]):
            with patch("fava_trails.tunnel_cli._terminate_pid_group") as terminate_pid_group:
                rc = cmd_stop(_args(data_repo=str(data_repo), timeout=0.01))

    assert rc == 0
    terminate_pid_group.assert_called_once_with(4321, timeout=0.01)
    assert "Stopped gateway pid 4321" in capsys.readouterr().out


def test_stop_terminates_recorded_child_process_groups(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)
    state_dir.mkdir(parents=True)
    tunnel_cli._pid_file(state_dir).write_text("4321\n")
    tunnel_cli._metadata_file(state_dir).write_text('{"pid":4321,"http_pid":111,"tunnel_pid":222}\n')
    tunnel_cli._ready_file(state_dir).write_text('{"status":"ready","http_pid":111,"tunnel_pid":222}\n')

    with patch("fava_trails.tunnel_cli._is_pid_running", side_effect=[True, False, False]):
        with patch("fava_trails.tunnel_cli._terminate_pid_group") as terminate_pid_group:
            rc = cmd_stop(_args(data_repo=str(data_repo), timeout=0.01))

    assert rc == 0
    assert [call.args[0] for call in terminate_pid_group.call_args_list] == [4321, 222, 111]
    assert not tunnel_cli._ready_file(state_dir).exists()


def test_run_cleans_children_when_interrupted(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    args = _args(data_repo=str(data_repo))

    http_process = MagicMock()
    http_process.poll.return_value = None
    http_process.pid = 111
    tunnel_process = MagicMock()
    tunnel_process.wait.side_effect = KeyboardInterrupt
    tunnel_process.poll.return_value = None
    tunnel_process.pid = 222

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("fava_trails.tunnel_cli._start_http_runtime", return_value=http_process):
                    with patch("fava_trails.tunnel_cli._wait_for_health"):
                        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                            with patch("fava_trails.tunnel_cli._start_tunnel_client", return_value=tunnel_process):
                                with patch("fava_trails.tunnel_cli._terminate_process") as terminate_process:
                                    rc = cmd_run(args)

    assert rc == 0
    assert [call.args[0] for call in terminate_process.call_args_list] == [
        tunnel_process,
        http_process,
    ]


def test_tunnel_cli_help_mentions_start():
    parser = tunnel_cli.build_parser()
    help_text = parser.format_help()
    assert "start" in help_text
    assert "run" in help_text


def test_http_runtime_healthz_reports_data_repo(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(data_repo))
    ConfigStore.reset()

    async def noop_init_server():
        return None

    with patch("fava_trails.server._init_server", new=noop_init_server):
        app = create_streamable_http_app()
        with TestClient(app) as client:
            response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runtime"] == "fava-trails-tunnel"
    assert payload["data_repo"] == str(data_repo)
    assert payload["trails_dir"] == str(data_repo / "trails")

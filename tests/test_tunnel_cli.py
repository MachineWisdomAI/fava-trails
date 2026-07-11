"""Tests for the fava-trails-tunnel CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from fava_trails import tunnel_cli
from fava_trails.config import ConfigStore
from fava_trails.http_runtime import create_streamable_http_app
from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
from fava_trails.readiness import ReadinessFailure, probe_data_repository
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
        "sync_interval_seconds": 0.0,
        "sync_timeout_seconds": 30.0,
        "json": False,
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


def _write_thought(data_repo: Path, *, thought_id: str = "01KXREADINESS00000000000000") -> Path:
    thought_path = data_repo / "trails" / "mwai" / "eng" / "thoughts" / "drafts" / f"{thought_id}.md"
    thought_path.parent.mkdir(parents=True)
    thought_path.write_text(
        ThoughtRecord(
            frontmatter=ThoughtFrontmatter(thought_id=thought_id),
            content="private representative content",
        ).to_markdown()
    )
    return thought_path


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
    assert config.mcp_url == "http://127.0.0.1:8765/mcp/"
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


def test_runtime_env_passes_health_file(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    health_file = tmp_path / "health.json"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            config = _load_gateway_config(_args(data_repo=str(data_repo)))

    env = _runtime_env(config, health_file=health_file)

    assert env["FAVA_TRAILS_TUNNEL_HEALTH_FILE"] == str(health_file)


def test_startup_wait_requires_strengthened_readiness_result():
    process = MagicMock()
    process.poll.return_value = None

    with patch(
        "fava_trails.tunnel_cli._request_health",
        side_effect=[
            (503, {"status": "not_ready", "reason": "trails_unreadable"}),
            (200, {"status": "ok", "data": {"empty": True}}),
        ],
    ) as request_health:
        with patch("fava_trails.tunnel_cli.time.sleep"):
            tunnel_cli._wait_for_health("http://127.0.0.1:8765/healthz", process, timeout=1.0)

    assert request_health.call_count == 2


def test_repo_revision_state_uses_jj_bookmarks_not_git_head(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            config = _load_gateway_config(_args(data_repo=str(data_repo)))

    def fake_jj_output(_data_repo, *args):
        rev = args[args.index("-r") + 1]
        return {
            "main": "local-main-commit",
            "main@origin": "remote-main-commit",
        }[rev]

    with patch("fava_trails.tunnel_cli._jj_output", side_effect=fake_jj_output) as jj_output:
        state = tunnel_cli._repo_revision_state(config)

    assert state == {
        "local_main": "local-main-commit",
        "remote_main": "remote-main-commit",
        "stale": True,
    }
    assert [call.args[1:] for call in jj_output.call_args_list] == [
        ("log", "--no-graph", "-r", "main", "-T", 'commit_id ++ "\n"'),
        ("log", "--no-graph", "-r", "main@origin", "-T", 'commit_id ++ "\n"'),
    ]


def test_disabled_sync_health_does_not_query_revision_state(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    health_file = tmp_path / "health.json"
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            config = _load_gateway_config(_args(data_repo=str(data_repo)))

    with patch("fava_trails.tunnel_cli._repo_revision_state", side_effect=AssertionError):
        worker = tunnel_cli._start_sync_worker(
            config,
            health_file,
            interval=0.0,
            timeout=30.0,
            stop_event=MagicMock(),
        )

    assert worker is None
    payload = json.loads(health_file.read_text())
    assert payload["status"] == "disabled"
    assert payload["message"] == "tunnel-managed sync disabled"
    assert "stale" not in payload
    assert "local_main" not in payload
    assert "remote_main" not in payload


def test_run_starts_http_and_runs_tunnel_without_doctor_or_autosync_by_default(tmp_path, monkeypatch):
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
                        with patch("fava_trails.tunnel_cli._sync_data_repo", return_value={"status": "ok"}) as sync:
                            with patch("subprocess.run") as run:
                                with patch("fava_trails.tunnel_cli._start_tunnel_client", return_value=tunnel_process) as start_tunnel:
                                    rc = cmd_run(args)

    assert rc == 0
    start_http.assert_called_once()
    wait_health.assert_called_once()
    run.assert_not_called()
    start_tunnel.assert_called_once()
    sync.assert_not_called()


def test_run_autosyncs_when_interval_positive(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    args = _args(data_repo=str(data_repo), sync_interval_seconds=60.0)

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
                        with patch("fava_trails.tunnel_cli._sync_data_repo", return_value={"status": "ok"}) as sync:
                            with patch("fava_trails.tunnel_cli._start_sync_worker", return_value=None) as start_worker:
                                with patch("subprocess.run"):
                                    with patch("fava_trails.tunnel_cli._start_tunnel_client", return_value=tunnel_process):
                                        rc = cmd_run(args)

    assert rc == 0
    sync.assert_called_once()
    start_worker.assert_called_once()


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
                        with patch("fava_trails.tunnel_cli._sync_data_repo", return_value={"status": "ok"}):
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
    assert "http://127.0.0.1:8765/mcp/" in (state_dirs[0] / "metadata.json").read_text()


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


def test_detached_startup_timeout_includes_sync_budget_and_grace():
    enabled = _args(ready_timeout=2.0, sync_interval_seconds=60.0, sync_timeout_seconds=3.0)
    disabled = _args(ready_timeout=2.0, sync_interval_seconds=0.0, sync_timeout_seconds=3.0)

    assert tunnel_cli._detached_startup_timeout(enabled) == 2.0 + 3.0 + tunnel_cli.DETACHED_STARTUP_GRACE_SECONDS
    assert tunnel_cli._detached_startup_timeout(disabled) == 2.0 + tunnel_cli.DETACHED_STARTUP_GRACE_SECONDS


def test_start_waits_for_startup_sync_before_ready_timeout(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    args = _args(data_repo=str(data_repo), ready_timeout=0.1, sync_interval_seconds=60.0, sync_timeout_seconds=0.5)

    process = MagicMock()
    process.pid = 4321
    process.poll.return_value = None
    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)
    clock = {"now": 0.0}

    def fake_popen(*args, **kwargs):
        state_dir.mkdir(parents=True, exist_ok=True)
        return process

    def fake_sleep(seconds):
        clock["now"] += 0.06
        if clock["now"] > 0.1:
            tunnel_cli._ready_file(state_dir).write_text('{"status":"ready"}\n')

    monkeypatch.setattr(tunnel_cli.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(tunnel_cli.time, "sleep", fake_sleep)

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("subprocess.Popen", side_effect=fake_popen):
                    rc = cmd_start(args)

    assert rc == 0
    assert "Supervisor PID: 4321" in capsys.readouterr().out


def test_start_cleans_state_when_supervisor_exits_during_startup(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    args = _args(data_repo=str(data_repo))

    process = MagicMock()
    process.pid = 4321
    process.poll.return_value = 1
    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)

    def fake_popen(*args, **kwargs):
        state_dir.mkdir(parents=True, exist_ok=True)
        tunnel_cli._ready_file(state_dir).write_text('{"status":"stale"}\n')
        return process

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("subprocess.Popen", side_effect=fake_popen):
                    with patch("fava_trails.tunnel_cli._terminate_pid_group") as terminate:
                        rc = cmd_start(args)

    assert rc == 1
    terminate.assert_not_called()
    assert not tunnel_cli._pid_file(state_dir).exists()
    assert not tunnel_cli._ready_file(state_dir).exists()
    assert "gateway exited during startup" in capsys.readouterr().err


def test_start_timeout_terminates_supervisor_and_cleans_stale_state(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    args = _args(data_repo=str(data_repo), ready_timeout=0.1, sync_timeout_seconds=0.2)

    process = MagicMock()
    process.pid = 4321
    process.poll.return_value = None
    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)
    clock = {"now": 0.0}

    def fake_popen(*args, **kwargs):
        state_dir.mkdir(parents=True, exist_ok=True)
        return process

    def fake_sleep(seconds):
        clock["now"] += 0.2

    monkeypatch.setattr(tunnel_cli.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(tunnel_cli.time, "sleep", fake_sleep)

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("subprocess.Popen", side_effect=fake_popen):
                    with patch("fava_trails.tunnel_cli._terminate_pid_group") as terminate:
                        rc = cmd_start(args)

    assert rc == 1
    terminate.assert_called_once_with(4321)
    assert not tunnel_cli._pid_file(state_dir).exists()
    assert not tunnel_cli._ready_file(state_dir).exists()
    assert tunnel_cli._metadata_file(state_dir).exists()
    assert "timed out waiting for gateway startup" in capsys.readouterr().err


def test_start_post_launch_failure_terminates_supervisor_and_cleans_state(tmp_path, monkeypatch, capsys):
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
        tunnel_cli._ready_file(state_dir).write_text('{"status":"stale"}\n')
        return process

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("shutil.which", return_value="/usr/bin/tunnel-client"):
            with patch("fava_trails.tunnel_cli._check_port_available"):
                with patch("subprocess.Popen", side_effect=fake_popen):
                    with patch("fava_trails.tunnel_cli._write_metadata", side_effect=OSError("metadata failed")):
                        with patch("fava_trails.tunnel_cli._terminate_pid_group") as terminate:
                            rc = cmd_start(args)

    assert rc == 1
    terminate.assert_called_once_with(4321)
    assert not tunnel_cli._pid_file(state_dir).exists()
    assert not tunnel_cli._ready_file(state_dir).exists()
    assert "metadata failed" in capsys.readouterr().err


def test_status_reports_not_running_for_missing_pid(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    with patch("fava_trails.tunnel_cli._load_gateway_config", side_effect=AssertionError):
        rc = cmd_status(_args(data_repo=str(data_repo)))

    assert rc == 1
    assert "not running" in capsys.readouterr().out


def test_status_json_reports_health(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)
    state_dir.mkdir(parents=True)
    tunnel_cli._pid_file(state_dir).write_text("4321\n")
    tunnel_cli._health_file(state_dir).write_text('{"status":"blocked","message":"dirty working copy"}\n')

    with patch("fava_trails.tunnel_cli._is_pid_running", return_value=True):
        with patch(
            "fava_trails.tunnel_cli._status_readiness",
            return_value={"status": "ok", "data": {"empty": True}},
        ):
            rc = cmd_status(_args(data_repo=str(data_repo), json=True))

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["running"] is True
    assert payload["ready"] is True
    assert payload["health"]["status"] == "blocked"
    assert payload["readiness"]["status"] == "ok"


def test_status_returns_failure_when_runtime_is_running_but_data_is_not_ready(tmp_path, monkeypatch, capsys):
    data_repo = _make_data_repo(tmp_path)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    state_dir = tunnel_cli._state_dir(data_repo.resolve(), DEFAULT_PROFILE)
    state_dir.mkdir(parents=True)
    tunnel_cli._pid_file(state_dir).write_text("4321\n")

    with patch("fava_trails.tunnel_cli._is_pid_running", return_value=True):
        with patch(
            "fava_trails.tunnel_cli._status_readiness",
            return_value={
                "status": "not_ready",
                "reason": "trails_unreadable",
                "message": "trails directory is not accessible",
            },
        ):
            rc = cmd_status(_args(data_repo=str(data_repo), json=True))

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_ready"
    assert payload["running"] is True
    assert payload["ready"] is False
    assert payload["readiness"]["reason"] == "trails_unreadable"


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
                                    with patch("fava_trails.tunnel_cli._sync_data_repo", return_value={"status": "ok"}):
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


def _health_response(data_repo: Path, monkeypatch):
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(data_repo))
    ConfigStore.reset()

    async def noop_init_server():
        return None

    with patch("fava_trails.server._init_server", new=noop_init_server):
        app = create_streamable_http_app()
        with TestClient(app) as client:
            return client.get("/healthz")


def test_http_runtime_healthz_reports_valid_empty_repository_ready(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runtime"] == "fava-trails-tunnel"
    assert payload["data"] == {
        "status": "ok",
        "scopes": 0,
        "records": 0,
        "empty": True,
        "representative_read": False,
    }
    assert str(data_repo) not in response.text


def test_http_runtime_healthz_traverses_scopes_and_parses_representative_record(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    _write_thought(data_repo)
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["scopes"] == 1
    assert payload["data"]["records"] == 1
    assert payload["data"]["empty"] is False
    assert payload["data"]["representative_read"] is True
    assert "private representative content" not in response.text
    assert str(data_repo) not in response.text


def test_http_runtime_healthz_does_not_treat_prior_sync_state_as_readiness(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    health_file = tmp_path / "health.json"
    health_file.write_text('{"status":"blocked","message":"dirty working copy"}\n')
    monkeypatch.setenv("FAVA_TRAILS_TUNNEL_HEALTH_FILE", str(health_file))
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "dirty working copy" not in response.text
    assert "sync" not in response.json()


def test_http_runtime_healthz_reports_missing_structure_without_path(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    (data_repo / "trails").rmdir()
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "runtime": "fava-trails-tunnel",
        "reason": "trails_missing",
        "message": "trails directory is missing",
    }
    assert str(data_repo) not in response.text


def test_http_runtime_healthz_reports_malformed_config_without_loading_cached_config(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    (data_repo / "config.yaml").write_text("trails_dir: [not-a-path]\n")
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 503
    assert response.json()["reason"] == "config_malformed"
    assert str(data_repo) not in response.text


def test_http_runtime_healthz_probes_the_trails_directory_named_by_config(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    (data_repo / "config.yaml").write_text("trails_dir: missing-trails\n")
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 503
    assert response.json()["reason"] == "trails_missing"


def test_http_runtime_healthz_reports_inaccessible_scope_tree(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    with patch("fava_trails.readiness.os.scandir", side_effect=PermissionError("private path")):
        response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 503
    assert response.json()["reason"] == "scope_tree_unreadable"
    assert "private path" not in response.text
    assert str(data_repo) not in response.text


def test_http_runtime_healthz_reports_malformed_representative_without_content(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    thought_path = _write_thought(data_repo)
    thought_path.write_text("---\nvalidation_status: definitely-invalid\n---\nsecret body")
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 503
    assert response.json()["reason"] == "thought_malformed"
    assert "secret body" not in response.text
    assert str(thought_path) not in response.text


def test_data_readiness_probe_has_explicit_time_bound(tmp_path):
    data_repo = _make_data_repo(tmp_path)

    with pytest.raises(ReadinessFailure, match="time limit") as exc_info:
        probe_data_repository(data_repo, timeout_seconds=0)

    assert exc_info.value.reason == "probe_timeout"


def test_http_runtime_healthz_reports_tree_bound(tmp_path, monkeypatch):
    data_repo = _make_data_repo(tmp_path)
    (data_repo / "trails" / "scope").mkdir()
    monkeypatch.setattr("fava_trails.readiness.MAX_TREE_ENTRIES", 0)
    response = _health_response(data_repo, monkeypatch)

    assert response.status_code == 503
    assert response.json()["reason"] == "scope_tree_too_large"

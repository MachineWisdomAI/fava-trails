"""CLI for running a FAVA Trails MCP runtime behind OpenAI Secure MCP Tunnel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import yaml

from .cli import _find_jj_bin
from .config import ConfigStore

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_PROFILE = "fava-trails"
DEFAULT_MCP_PATH = "/mcp"


@dataclass(frozen=True)
class GatewayConfig:
    data_repo: Path
    trails_dir: Path
    host: str
    port: int
    mcp_path: str
    profile: str
    tunnel_client: str
    trust_gate_env: str

    @property
    def mcp_url(self) -> str:
        return f"http://{self.host}:{self.port}{self.mcp_path}"

    @property
    def health_url(self) -> str:
        return f"http://{self.host}:{self.port}/healthz"


@dataclass(frozen=True)
class GatewayIdentity:
    data_repo: Path
    profile: str


def _state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))


def _state_dir(data_repo: Path, profile: str) -> Path:
    digest = hashlib.sha256(f"{data_repo.resolve()}|{profile}".encode()).hexdigest()[:12]
    safe_profile = "".join(c if c.isalnum() or c in "._-" else "-" for c in profile).strip("-") or "default"
    return _state_home() / "fava-trails" / "tunnel" / f"{safe_profile}-{digest}"


def _pid_file(state_dir: Path) -> Path:
    return state_dir / "supervisor.pid"


def _metadata_file(state_dir: Path) -> Path:
    return state_dir / "metadata.json"


def _ready_file(state_dir: Path) -> Path:
    return state_dir / "ready.json"


def _log_file(state_dir: Path) -> Path:
    return state_dir / "gateway.log"


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _validate_loopback_host(host: str) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("fava-trails-tunnel only binds the private MCP runtime to a loopback host")


def _check_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET6 if host == "::1" else socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise ValueError(f"port {port} is not available on {host}") from exc


def _resolve_data_repo(args: argparse.Namespace) -> Path:
    value = getattr(args, "data_repo", None) or os.environ.get("FAVA_TRAILS_DATA_REPO")
    if not value:
        raise ValueError("FAVA_TRAILS_DATA_REPO is required; pass --data-repo for tunnel mode")
    return Path(value).expanduser().resolve()


def _resolve_gateway_identity(args: argparse.Namespace) -> GatewayIdentity:
    data_repo = _resolve_data_repo(args)
    if not data_repo.is_dir():
        raise ValueError(f"data repo not found: {data_repo}")
    return GatewayIdentity(
        data_repo=data_repo,
        profile=getattr(args, "profile", DEFAULT_PROFILE),
    )


def _load_gateway_config(args: argparse.Namespace, *, require_tunnel_client: bool = True) -> GatewayConfig:
    identity = _resolve_gateway_identity(args)
    data_repo = identity.data_repo

    config_path = data_repo / "config.yaml"
    if not config_path.is_file():
        raise ValueError(f"missing data repo config.yaml: {config_path}")

    try:
        config_data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid data repo config.yaml: {exc}") from exc

    trails_value = config_data.get("trails_dir", "trails")
    trails_dir = Path(trails_value)
    if not trails_dir.is_absolute():
        trails_dir = data_repo / trails_dir
    if not trails_dir.is_dir():
        raise ValueError(f"trails directory not found: {trails_dir}")

    if _find_jj_bin() is None:
        raise ValueError("jj not found. Install with: fava-trails install-jj")

    trust_gate = config_data.get("trust_gate", "llm-oneshot")
    trust_gate_env = config_data.get("openrouter_api_key_env", "OPENROUTER_API_KEY")
    if trust_gate == "llm-oneshot" and not os.environ.get(trust_gate_env):
        raise ValueError(f"Trust Gate provider config missing: set {trust_gate_env}")

    host = getattr(args, "host", DEFAULT_HOST)
    port = getattr(args, "port", DEFAULT_PORT)
    mcp_path = getattr(args, "mcp_path", DEFAULT_MCP_PATH)
    profile = identity.profile
    tunnel_client_arg = getattr(args, "tunnel_client", None) or "tunnel-client"
    tunnel_client = shutil.which(tunnel_client_arg) or (
        str(Path(tunnel_client_arg).expanduser()) if Path(tunnel_client_arg).expanduser().is_file() else ""
    )
    if require_tunnel_client and not tunnel_client:
        raise ValueError("tunnel-client not found on PATH; install OpenAI tunnel-client or pass --tunnel-client")

    _validate_loopback_host(host)

    return GatewayConfig(
        data_repo=data_repo,
        trails_dir=trails_dir,
        host=host,
        port=port,
        mcp_path=mcp_path,
        profile=profile,
        tunnel_client=tunnel_client or tunnel_client_arg,
        trust_gate_env=trust_gate_env,
    )


def _runtime_env(config: GatewayConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["FAVA_TRAILS_DATA_REPO"] = str(config.data_repo)
    env.setdefault("FAVA_TRAILS_SCOPE_HINT", "")
    env.setdefault("FAVA_TRAILS_LOG_DIR", str(config.data_repo / "logs"))
    return env


def _wait_for_health(url: str, process: subprocess.Popen, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise subprocess.SubprocessError("private MCP runtime exited before becoming ready")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for private MCP runtime at {url}: {last_error}")


def _start_http_runtime(config: GatewayConfig, *, stdout=None, stderr=None) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "fava_trails.tunnel_cli",
        "_serve-http",
        "--data-repo",
        str(config.data_repo),
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--mcp-path",
        config.mcp_path,
    ]
    return subprocess.Popen(
        command,
        env=_runtime_env(config),
        stdout=stdout,
        stderr=stderr,
        start_new_session=os.name != "nt",
    )


def _run_tunnel_doctor(config: GatewayConfig) -> None:
    result = subprocess.run(
        [config.tunnel_client, "doctor", "--profile", config.profile, "--explain"],
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise subprocess.SubprocessError(
            f"tunnel-client doctor failed for profile {config.profile!r}"
        )


def _start_tunnel_client(config: GatewayConfig) -> subprocess.Popen:
    return subprocess.Popen(
        [config.tunnel_client, "run", "--profile", config.profile],
        start_new_session=os.name != "nt",
    )


def _terminate_process(process: subprocess.Popen, *, timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    pid = process.pid
    if os.name != "nt":
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            process.wait(timeout=timeout)
        else:
            process.kill()
            process.wait(timeout=timeout)


def _terminate_pid_group(pid: int, *, timeout: float = 5.0) -> None:
    if not _is_pid_running(pid):
        return
    if os.name != "nt":
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_pid_running(pid):
            return
        time.sleep(0.1)

    if os.name != "nt":
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        os.kill(pid, signal.SIGTERM)


def _read_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_metadata(
    state_dir: Path,
    config: GatewayConfig,
    *,
    pid: int,
    http_pid: int | None = None,
    tunnel_pid: int | None = None,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": pid,
        "data_repo": str(config.data_repo),
        "trails_dir": str(config.trails_dir),
        "mcp_url": config.mcp_url,
        "health_url": config.health_url,
        "profile": config.profile,
        "log_file": str(_log_file(state_dir)),
    }
    if http_pid is not None:
        payload["http_pid"] = http_pid
    if tunnel_pid is not None:
        payload["tunnel_pid"] = tunnel_pid
    _metadata_file(state_dir).write_text(json.dumps(payload, indent=2) + "\n")


def _write_ready(state_dir: Path, config: GatewayConfig, *, http_pid: int, tunnel_pid: int) -> None:
    payload = {
        "status": "ready",
        "http_pid": http_pid,
        "tunnel_pid": tunnel_pid,
        "mcp_url": config.mcp_url,
        "profile": config.profile,
        "ready_at": time.time(),
    }
    _ready_file(state_dir).write_text(json.dumps(payload, indent=2) + "\n")


def _print_startup(config: GatewayConfig, *, state_dir: Path | None = None) -> None:
    print("FAVA Trails ChatGPT tunnel gateway")
    print(f"  Data repo:  {config.data_repo}")
    print(f"  Trails dir: {config.trails_dir}")
    print(f"  MCP URL:    {config.mcp_url}")
    print(f"  Tunnel:     OpenAI Secure MCP Tunnel profile {config.profile!r}")
    if state_dir:
        print(f"  State:      {state_dir}")
        print(f"  Log:        {_log_file(state_dir)}")


def cmd_run(args: argparse.Namespace) -> int:
    http_process: subprocess.Popen | None = None
    tunnel_process: subprocess.Popen | None = None
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def handle_shutdown(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)
        config = _load_gateway_config(args)
        _check_port_available(config.host, config.port)
        state_dir = Path(args.state_dir).expanduser().resolve() if getattr(args, "state_dir", None) else None
        if state_dir:
            try:
                _ready_file(state_dir).unlink()
            except FileNotFoundError:
                pass
            _write_metadata(state_dir, config, pid=os.getpid())
            _pid_file(state_dir).write_text(f"{os.getpid()}\n")
        _print_startup(config, state_dir=state_dir)

        http_process = _start_http_runtime(config)
        if state_dir:
            _write_metadata(state_dir, config, pid=os.getpid(), http_pid=http_process.pid)
        _wait_for_health(config.health_url, http_process, timeout=args.ready_timeout)
        print("  Private MCP runtime: ready")

        if not getattr(args, "skip_tunnel_doctor", False):
            _run_tunnel_doctor(config)
            print("  tunnel-client doctor: ok")

        tunnel_process = _start_tunnel_client(config)
        if state_dir:
            _write_metadata(
                state_dir,
                config,
                pid=os.getpid(),
                http_pid=http_process.pid,
                tunnel_pid=tunnel_process.pid,
            )
            _write_ready(state_dir, config, http_pid=http_process.pid, tunnel_pid=tunnel_process.pid)
        print(f"  tunnel-client: running (pid {tunnel_process.pid})")
        return tunnel_process.wait()
    except KeyboardInterrupt:
        print("\nStopping FAVA Trails tunnel gateway.")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, TimeoutError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if tunnel_process is not None:
            _terminate_process(tunnel_process)
        if http_process is not None:
            _terminate_process(http_process)
        state_dir_value = getattr(args, "state_dir", None)
        if state_dir_value:
            state_dir = Path(state_dir_value).expanduser().resolve()
            try:
                _pid_file(state_dir).unlink()
            except FileNotFoundError:
                pass
            try:
                _ready_file(state_dir).unlink()
            except FileNotFoundError:
                pass
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)


def cmd_start(args: argparse.Namespace) -> int:
    try:
        config = _load_gateway_config(args)
        _check_port_available(config.host, config.port)
        state_dir = _state_dir(config.data_repo, config.profile)
        pid_path = _pid_file(state_dir)
        existing_pid = _read_pid(pid_path)
        if existing_pid and _is_pid_running(existing_pid):
            print(f"Gateway already running (pid {existing_pid})")
            return 0

        state_dir.mkdir(parents=True, exist_ok=True)
        try:
            _ready_file(state_dir).unlink()
        except FileNotFoundError:
            pass
        log_path = _log_file(state_dir)
        log = log_path.open("ab")
        command = [
            sys.executable,
            "-m",
            "fava_trails.tunnel_cli",
            "run",
            "--data-repo",
            str(config.data_repo),
            "--profile",
            config.profile,
            "--host",
            config.host,
            "--port",
            str(config.port),
            "--mcp-path",
            config.mcp_path,
            "--tunnel-client",
            config.tunnel_client,
            "--ready-timeout",
            str(args.ready_timeout),
            "--state-dir",
            str(state_dir),
        ]
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=_runtime_env(config),
            start_new_session=os.name != "nt",
        )
        log.close()
        pid_path.write_text(f"{process.pid}\n")
        _write_metadata(state_dir, config, pid=process.pid)

        deadline = time.monotonic() + args.ready_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                print(f"Error: gateway exited during startup; see {log_path}", file=sys.stderr)
                return 1
            if _ready_file(state_dir).is_file():
                _print_startup(config, state_dir=state_dir)
                print(f"  Supervisor PID: {process.pid}")
                return 0
            time.sleep(0.1)
        print(f"Error: timed out waiting for gateway startup; see {log_path}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    try:
        identity = _resolve_gateway_identity(args)
        state_dir = _state_dir(identity.data_repo, identity.profile)
        pid = _read_pid(_pid_file(state_dir))
        if pid and _is_pid_running(pid):
            print(f"Gateway running (pid {pid})")
            print(f"  State: {state_dir}")
            print(f"  Log:   {_log_file(state_dir)}")
            return 0
        print("Gateway not running")
        print(f"  State: {state_dir}")
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    try:
        identity = _resolve_gateway_identity(args)
        state_dir = _state_dir(identity.data_repo, identity.profile)
        pid_path = _pid_file(state_dir)
        pid = _read_pid(pid_path)
        if not pid or not _is_pid_running(pid):
            print("Gateway not running")
            return 0
        metadata = _read_json_file(_metadata_file(state_dir))
        ready = _read_json_file(_ready_file(state_dir))
        child_pids = [
            value
            for value in (
                metadata.get("tunnel_pid"),
                metadata.get("http_pid"),
                ready.get("tunnel_pid"),
                ready.get("http_pid"),
            )
            if isinstance(value, int) and value > 0
        ]
        _terminate_pid_group(pid, timeout=args.timeout)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if not _is_pid_running(pid):
                break
            time.sleep(0.1)
        for child_pid in dict.fromkeys(child_pids):
            if child_pid != pid:
                _terminate_pid_group(child_pid, timeout=args.timeout)
        if _is_pid_running(pid):
            _terminate_pid_group(pid, timeout=0)
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass
        try:
            _ready_file(state_dir).unlink()
        except FileNotFoundError:
            pass
        print(f"Stopped gateway pid {pid}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_serve_http(args: argparse.Namespace) -> int:
    try:
        _validate_loopback_host(args.host)
        os.environ["FAVA_TRAILS_DATA_REPO"] = str(_resolve_data_repo(args))
        ConfigStore.reset()
        from .http_runtime import run_streamable_http_server

        run_streamable_http_server(host=args.host, port=args.port)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-repo", default=None, help="FAVA Trails data repo path (required if env is unset)")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help=f"tunnel-client profile (default: {DEFAULT_PROFILE})")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Loopback host for private MCP runtime (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port for private MCP runtime (default: {DEFAULT_PORT})")
    parser.add_argument("--mcp-path", default=DEFAULT_MCP_PATH, help=f"MCP path (default: {DEFAULT_MCP_PATH})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fava-trails-tunnel",
        description="Run FAVA Trails behind OpenAI Secure MCP Tunnel.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    p_run = subparsers.add_parser("run", help="Run the gateway in the foreground")
    _add_common_args(p_run)
    p_run.add_argument("--tunnel-client", default="tunnel-client", help="Path to tunnel-client binary")
    p_run.add_argument("--ready-timeout", type=float, default=20.0, help="Seconds to wait for local MCP readiness")
    p_run.add_argument("--skip-tunnel-doctor", action="store_true", help="Skip tunnel-client doctor before run")
    p_run.add_argument("--state-dir", default=None, help=argparse.SUPPRESS)
    p_run.set_defaults(func=cmd_run)

    p_start = subparsers.add_parser("start", help="Start the gateway as a detached daemon")
    _add_common_args(p_start)
    p_start.add_argument("--tunnel-client", default="tunnel-client", help="Path to tunnel-client binary")
    p_start.add_argument("--ready-timeout", type=float, default=20.0, help="Seconds to wait for local MCP readiness")
    p_start.set_defaults(func=cmd_start)

    p_stop = subparsers.add_parser("stop", help="Stop a detached gateway")
    _add_common_args(p_stop)
    p_stop.add_argument("--timeout", type=float, default=5.0, help="Seconds to wait before forcing stop")
    p_stop.set_defaults(func=cmd_stop)

    p_status = subparsers.add_parser("status", help="Show gateway status")
    _add_common_args(p_status)
    p_status.set_defaults(func=cmd_status)

    return parser


def _build_serve_http_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fava-trails-tunnel _serve-http")
    _add_common_args(parser)
    parser.set_defaults(func=cmd_serve_http)
    return parser


def main(argv: list[str] | None = None) -> NoReturn:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "_serve-http":
        parser = _build_serve_http_parser()
        args = parser.parse_args(argv[1:])
        sys.exit(args.func(args))

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

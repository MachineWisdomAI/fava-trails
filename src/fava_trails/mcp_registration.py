"""Native MCP client registration and onboarding diagnostics."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_SERVER_NAME = "fava-trails"
DEFAULT_CLIENT = "claude-code"
NEW_FILE_MODE = 0o600
NATIVE_MCP_CLIENT_PACKAGE = "@modelcontextprotocol/inspector@2.6.0"
_SECRET_KEY_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")
_CONFIG_LOAD_MARKERS = (
    "config file",
    "loading configuration",
    "not valid json",
    "available servers",
    "server '",
)
_SPAWN_MARKERS = ("spawn ", " enoent", "eacces")
_INIT_MARKERS = ("connection closed", "initialize", "mcp error")
_INVOCATION_MARKERS = ("npm err", "e404", "cannot find package", "failed to fetch", "enoent")


class PermissionDenied(Exception):
    """Client config could not be read or written because permission was denied."""


def _usable_executable(path: Path) -> str | None:
    if path.is_file() and os.access(path, os.X_OK):
        return str(path.resolve())
    return None


def resolve_explicit_executable(value: str) -> str | None:
    """Return a real executable path, or None if ``value`` is missing or not executable."""
    explicit = Path(value).expanduser()
    found = _usable_executable(explicit)
    if found:
        return found
    which = shutil.which(value)
    if which:
        return _usable_executable(Path(which))
    return None


def resolve_server_executable() -> str | None:
    found = shutil.which("fava-trails-server")
    if found:
        usable = _usable_executable(Path(found))
        if usable:
            return usable
    sibling = Path(sys.executable).parent / "fava-trails-server"
    return _usable_executable(sibling)


def default_client_config_path(client: str = DEFAULT_CLIENT) -> Path:
    if client == "claude-code":
        return Path.home() / ".claude.json"
    if client == "claude-desktop":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    raise ValueError(f"Unsupported client {client!r}. Use --config PATH.")


def build_registration(
    *,
    executable: str,
    data_repo: str,
    agent_id: str,
    operator: bool = False,
) -> dict[str, Any]:
    env = {
        "FAVA_TRAILS_DATA_REPO": data_repo,
        "FAVA_TRAILS_AGENT_ID": agent_id,
    }
    if operator:
        env["FAVA_TRAILS_OPERATOR"] = "1"
    return {"command": executable, "env": env}


def format_registration_instructions(
    *,
    executable: str,
    data_repo: str,
    agent_id: str,
) -> str:
    ordinary = build_registration(executable=executable, data_repo=data_repo, agent_id=agent_id)
    snippet = {
        "mcpServers": {
            DEFAULT_SERVER_NAME: ordinary,
        }
    }
    return (
        "Ordinary native registration (shared endpoint):\n"
        "Use a server-configured agent identity, the actual executable, and the intended data repository.\n"
        f"{json.dumps(snippet, indent=2)}\n"
        "\n"
        "Elevated operator configuration is separate. Do not set FAVA_TRAILS_OPERATOR on the shared "
        "endpoint. Run a dedicated operator-controlled process with FAVA_TRAILS_OPERATOR=1 if history "
        "access is required. Direct stdio testing is not a substitute for native client registration.\n"
    )


def _write_text_with_mode(path: Path, text: str, mode: int) -> None:
    """Create ``path`` with ``mode`` before any secret-bearing content is written."""
    path.unlink(missing_ok=True)
    previous_umask = os.umask(0)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    finally:
        os.umask(previous_umask)
    try:
        with os.fdopen(fd, "w") as handle:
            fd = -1
            handle.write(text)
    except Exception:
        if fd != -1:
            os.close(fd)
        path.unlink(missing_ok=True)
        raise


def write_mcp_json_config(
    path: Path,
    *,
    server_name: str,
    entry: dict[str, Any],
) -> Path | None:
    """Merge a server entry into an MCP JSON client config.

    Preserves unrelated keys. Writes atomically and makes a ``.bak`` backup of an
    existing file. Replacement and backup modes never exceed owner-only
    ``0o600``; already-stricter modes are preserved. New files use ``0o600``.
    Permission errors are reported; this never chmods the target to loosen
    access or bypass denial.
    """
    path = Path(path)
    existing_text: str | None = None
    existing_mode: int | None = None
    if path.exists():
        existing_mode = stat.S_IMODE(path.stat().st_mode)
        if not os.access(path, os.W_OK):
            raise PermissionDenied(f"Permission denied writing {path}")
        try:
            existing_text = path.read_text()
        except PermissionError as exc:
            raise PermissionDenied(f"Permission denied reading {path}") from exc
        except OSError as exc:
            if getattr(exc, "errno", None) == 13:
                raise PermissionDenied(f"Permission denied reading {path}") from exc
            raise

    data: dict[str, Any]
    if existing_text:
        loaded = json.loads(existing_text)
        if not isinstance(loaded, dict):
            raise ValueError(f"{path} is not a JSON object")
        data = loaded
    else:
        data = {}

    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
        data["mcpServers"] = servers
    if not isinstance(servers, dict):
        raise ValueError(f"{path} mcpServers is not an object")
    servers[server_name] = entry

    target_mode = NEW_FILE_MODE if existing_mode is None else (existing_mode & NEW_FILE_MODE)
    backup_path: Path | None = None
    if existing_text is not None:
        backup_path = path.with_name(path.name + ".bak")
        try:
            _write_text_with_mode(backup_path, existing_text, target_mode)
        except PermissionError as exc:
            raise PermissionDenied(f"Permission denied writing backup {backup_path}") from exc

    serialized = json.dumps(data, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    try:
        _write_text_with_mode(tmp, serialized, target_mode)
        os.replace(tmp, path)
    except PermissionError as extra:
        tmp.unlink(missing_ok=True)
        raise PermissionDenied(f"Permission denied writing {path}") from extra
    except OSError as extra:
        tmp.unlink(missing_ok=True)
        if getattr(extra, "errno", None) == 13:
            raise PermissionDenied(f"Permission denied writing {path}") from extra
        raise
    return backup_path


def inspect_native_registration(
    config_path: Path,
    *,
    current_executable: str,
    server_name: str = DEFAULT_SERVER_NAME,
) -> dict[str, Any]:
    config_path = Path(config_path)
    report: dict[str, Any] = {
        "verified": "client_config",
        "config_path": str(config_path),
        "current_executable": current_executable,
        "env_names": [],
    }
    if not config_path.exists():
        report["status"] = "registration_not_loaded"
        report["ok"] = False
        return report
    try:
        loaded = json.loads(config_path.read_text())
    except PermissionError as exc:
        raise PermissionDenied(f"Permission denied reading {config_path}") from exc
    except (OSError, json.JSONDecodeError):
        report["status"] = "registration_not_loaded"
        report["ok"] = False
        return report
    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    entry = servers.get(server_name) if isinstance(servers, dict) else None
    if not isinstance(entry, dict) or not entry.get("command"):
        report["status"] = "registration_not_loaded"
        report["ok"] = False
        return report
    command = str(entry["command"])
    report["registered_command"] = command
    raw_env = entry.get("env")
    env: dict[str, Any] = raw_env if isinstance(raw_env, dict) else {}
    report["env_names"] = sorted(str(key) for key in env)
    if Path(command).resolve() != Path(current_executable).resolve() and command != current_executable:
        report["status"] = "stale_runtime_path"
        report["ok"] = False
        return report
    report["status"] = "loaded"
    report["ok"] = True
    return report


def _redact(value: str, secrets: list[str]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def collect_secret_values(env: dict[str, str] | None = None) -> list[str]:
    source = env if env is not None else os.environ
    secrets: list[str] = []
    for key, value in source.items():
        upper = key.upper()
        if any(marker in upper for marker in _SECRET_KEY_MARKERS) and value:
            secrets.append(value)
    return secrets


def render_diagnostics(sections: dict[str, Any], *, secrets: list[str] | None = None) -> str:
    payload = {
        "direct_mcp_smoke": sections.get("direct_mcp_smoke"),
        "client_config": sections.get("client_config"),
        "inspector_config_load": sections.get("inspector_config_load"),
    }
    text = json.dumps(payload, indent=2)
    return _redact(text, secrets if secrets is not None else collect_secret_values())


def _initialize_stdio(command: str, env: dict[str, str], *, timeout: float = 10.0) -> dict[str, Any]:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "fava-trails-register", "version": "1"},
        },
    }
    spawn_env = os.environ.copy()
    spawn_env.update(env)
    try:
        completed = subprocess.run(
            [command],
            input=json.dumps(message) + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
            env=spawn_env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": exc.__class__.__name__}
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if parsed.get("id") == 1 and "result" in parsed:
            return {"ok": True, "protocolVersion": parsed["result"].get("protocolVersion")}
    return {"ok": False, "error": "initialize_failed"}


def verify_direct_mcp_smoke(executable: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    result = _initialize_stdio(executable, env or {})
    result["verified"] = "direct_mcp_smoke"
    result["executable"] = executable
    return result


def _last_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    try:
        loaded = json.loads(stripped)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass
    start = stripped.rfind("{")
    while start >= 0:
        try:
            loaded = json.loads(stripped[start:])
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
        start = stripped.rfind("{", 0, start)
    return None


def _inspector_error_message(*blobs: str) -> str:
    for blob in blobs:
        payload = _last_json_object(blob)
        if not isinstance(payload, dict):
            continue
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
    return "\n".join(blob for blob in blobs if blob)


def _classify_inspector_failure(text: str) -> str:
    lower = text.lower()
    if any(marker in lower for marker in _SPAWN_MARKERS):
        return "server_spawn_failed"
    if any(marker in lower for marker in _CONFIG_LOAD_MARKERS):
        return "config_load_failed"
    if any(marker in lower for marker in _INIT_MARKERS):
        return "server_initialize_failed"
    if any(marker in lower for marker in _INVOCATION_MARKERS):
        return "inspector_invocation_failed"
    return "inspector_failed"


def _inspector_success_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    result = payload.get("result")
    return isinstance(result, dict) or bool(payload.get("serverInfo"))


def _default_native_client_probe(config_path: Path, server_name: str) -> dict[str, Any]:
    """Load registration through MCP Inspector, not a native Claude session."""
    npx = shutil.which("npx")
    node = shutil.which("node")
    if not npx or not node:
        return {"ok": False, "status": "inspector_unavailable"}
    cmd = [
        npx,
        "--yes",
        NATIVE_MCP_CLIENT_PACKAGE,
        "--cli",
        "--config",
        str(config_path),
        "--server",
        server_name,
        "--method",
        "initialize",
        "--format",
        "json",
    ]
    env = os.environ.copy()
    env.setdefault("MCP_INSPECTOR_SECRET_STORE", "memory")
    env.setdefault("NO_UPDATE_NOTIFIER", "1")
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env, check=False)
    except OSError as exc:
        return {"ok": False, "status": "inspector_unavailable", "error": exc.__class__.__name__}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "status": "inspector_invocation_failed", "error": exc.__class__.__name__}
    stdout_payload = _last_json_object(completed.stdout)
    if _inspector_success_payload(stdout_payload):
        return {"ok": True, "status": "loaded"}
    failure_text = _inspector_error_message(completed.stderr, completed.stdout)
    status = _classify_inspector_failure(failure_text)
    if status == "inspector_failed" and stdout_payload and stdout_payload.get("error"):
        status = "server_initialize_failed"
    return {"ok": False, "status": status}


def verify_native_client_session(
    config_path: Path,
    *,
    current_executable: str,
    server_name: str = DEFAULT_SERVER_NAME,
    client_probe: Callable[[Path, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inspection = inspect_native_registration(
        config_path,
        current_executable=current_executable,
        server_name=server_name,
    )
    inspection["verified"] = "inspector_config_load"
    if inspection.get("status") != "loaded":
        inspection["ok"] = False
        return inspection
    probe = client_probe if client_probe is not None else _default_native_client_probe
    probed = probe(Path(config_path), server_name)
    inspection["ok"] = bool(probed.get("ok"))
    inspection["status"] = str(probed.get("status") or ("loaded" if inspection["ok"] else "inspector_failed"))
    if probed.get("error"):
        inspection["error"] = probed["error"]
    return inspection

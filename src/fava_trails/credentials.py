"""Trust Gate credential resolution without secret-bearing diagnostics."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .models import GlobalConfig


def _load_owner_only_key_file(configured_path: str) -> str:
    path = Path(configured_path).expanduser()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("Trust Gate credential file is not readable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("Trust Gate credential file must not be a symlink")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None or not hasattr(os, "getuid"):
        raise ValueError("Trust Gate credential files require owner-checking platform support")
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0))
        opened_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(opened_metadata.st_mode):
            raise ValueError("Trust Gate credential file must be a regular file")
        if opened_metadata.st_uid != os.getuid():
            raise ValueError("Trust Gate credential file must be owned by the current user")
        if stat.S_IMODE(opened_metadata.st_mode) & 0o077:
            raise ValueError("Trust Gate credential file must be owner-only")
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            descriptor = None
            value = handle.read().strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Trust Gate credential file is not readable") from exc
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError("Trust Gate credential file is not readable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not value:
        raise ValueError("Trust Gate credential file is empty")
    return value


def load_trust_gate_api_key(config: GlobalConfig) -> str:
    """Load the configured key, preferring a strict file over the legacy env source."""
    if config.trust_gate_api_key_file:
        return _load_owner_only_key_file(config.trust_gate_api_key_file)
    env_name = config.resolve_trust_gate_api_key_env()
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise ValueError(f"No LLM API key found. Set {env_name} environment variable.")
    return value


def trust_gate_credential_description(config: GlobalConfig) -> str:
    """Return a non-secret, path-free description for diagnostics."""
    if config.trust_gate_api_key_file:
        return "credential file"
    return config.resolve_trust_gate_api_key_env()

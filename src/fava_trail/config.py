"""Configuration loading for FAVA Trail."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml

from .models import GlobalConfig, TrailConfig

logger = logging.getLogger(__name__)

DEFAULT_FAVA_HOME = os.path.expanduser("~/.fava-trail")

# Scope path segment: alphanumeric + hyphens/dots/underscores, starts with alphanumeric
_SCOPE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")

# Allowed thought namespaces — prevents path traversal via namespace parameter
VALID_NAMESPACES = frozenset({
    "drafts",
    "decisions",
    "observations",
    "intents",
    "preferences",
    "preferences/client",
    "preferences/firm",
})


def sanitize_scope_path(name: str) -> str:
    """Validate scope path: slash-separated segments, each a safe slug.

    Accepts both single-segment ('default') and multi-segment ('mw/eng/fava-trail') paths.
    Rejects path traversal attempts (.., \\) and invalid characters.
    """
    if not name:
        raise ValueError("Scope path cannot be empty.")
    if "\\" in name or ".." in name:
        raise ValueError(f"Invalid scope path: {name!r}. Path traversal not allowed.")
    name = name.strip("/")
    if not name:
        raise ValueError("Scope path cannot be empty.")
    segments = name.split("/")
    for seg in segments:
        if not seg or not _SCOPE_SEGMENT_RE.match(seg):
            raise ValueError(
                f"Invalid scope segment: {seg!r} in {name!r}. "
                "Segments must be alphanumeric with hyphens/dots/underscores, "
                "starting with an alphanumeric character."
            )
    return name


# Backward compatibility alias
sanitize_trail_name = sanitize_scope_path


def sanitize_namespace(namespace: str) -> str:
    """Validate namespace is in the allowed set. Prevents path traversal via namespace parameter."""
    if namespace not in VALID_NAMESPACES:
        raise ValueError(
            f"Invalid namespace: {namespace!r}. "
            f"Valid namespaces: {sorted(VALID_NAMESPACES)}"
        )
    return namespace


def get_data_repo_root() -> Path:
    """Get the FAVA Trail data repo root directory (monorepo root where .jj/ and .git/ live).

    Checks FAVA_TRAIL_DATA_REPO first, falls back to deprecated FAVA_TRAIL_HOME.
    """
    data_repo = os.environ.get("FAVA_TRAIL_DATA_REPO")
    if data_repo:
        return Path(data_repo)
    legacy = os.environ.get("FAVA_TRAIL_HOME")
    if legacy:
        logger.warning(
            "FAVA_TRAIL_HOME is deprecated, use FAVA_TRAIL_DATA_REPO instead"
        )
        return Path(legacy)
    return Path(DEFAULT_FAVA_HOME)


def get_trails_dir() -> Path:
    """Get the directory containing all trails.

    Priority:
    1. FAVA_TRAILS_DIR env var (highest — absolute path override, tilde-expanded)
    2. config.yaml trails_dir (absolute path used directly, relative resolved from FAVA_TRAIL_DATA_REPO)
    3. Default: $FAVA_TRAIL_DATA_REPO/trails
    """
    env_override = os.environ.get("FAVA_TRAILS_DIR")
    if env_override:
        return Path(os.path.expanduser(env_override))

    home = get_data_repo_root()
    config = load_global_config()
    trails_path = Path(config.trails_dir)
    if trails_path.is_absolute():
        return trails_path
    return home / config.trails_dir


def load_global_config() -> GlobalConfig:
    """Load global configuration from config.yaml."""
    config_path = get_data_repo_root() / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return GlobalConfig(**data)
    return GlobalConfig()


def save_global_config(config: GlobalConfig) -> None:
    """Save global configuration to config.yaml."""
    config_path = get_data_repo_root() / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)


def load_trail_config(trail_name: str) -> TrailConfig:
    """Load trail-specific configuration."""
    safe_name = sanitize_trail_name(trail_name)
    trail_dir = get_trails_dir() / safe_name
    config_path = trail_dir / ".fava-trail.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("name", trail_name)
        return TrailConfig(**data)
    return TrailConfig(name=trail_name)


def save_trail_config(trail_name: str, config: TrailConfig) -> None:
    """Save trail-specific configuration."""
    safe_name = sanitize_trail_name(trail_name)
    trail_dir = get_trails_dir() / safe_name
    config_path = trail_dir / ".fava-trail.yaml"
    trail_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)


def resolve_scope_globs(trails_dir: Path, patterns: list[str]) -> list[str]:
    """Resolve glob patterns to actual scope paths under trails/.

    * matches one level, ** matches any depth (standard Path.glob semantics).
    Silently drops anything resolving outside trails/.
    """
    resolved = set()
    trails_dir_resolved = trails_dir.resolve()
    for pattern in patterns:
        if "*" in pattern:
            for match in trails_dir.glob(pattern):
                try:
                    match.resolve().relative_to(trails_dir_resolved)
                except ValueError:
                    continue  # outside trails/ — silently drop
                if match.is_dir() and (match / "thoughts").exists():
                    resolved.add(str(match.relative_to(trails_dir)))
        else:
            candidate = trails_dir / pattern
            try:
                candidate.resolve().relative_to(trails_dir_resolved)
            except ValueError:
                continue  # outside trails/ — silently drop
            if candidate.is_dir() and (candidate / "thoughts").exists():
                resolved.add(pattern)
    return sorted(resolved)


def ensure_data_repo_root() -> Path:
    """Ensure the FAVA Trail data repo root and trails directories exist."""
    home = get_data_repo_root()
    home.mkdir(parents=True, exist_ok=True)
    trails_dir = get_trails_dir()
    trails_dir.mkdir(parents=True, exist_ok=True)
    return home


def get_trust_gate_policy(trail_name: str) -> str:
    """Resolve the trust gate policy for a given trail.

    Priority: trail-level .fava-trail.yaml > global config.yaml > default ("llm-oneshot").
    """
    trail_config = load_trail_config(trail_name)
    if trail_config.trust_gate_policy != "llm-oneshot":
        return trail_config.trust_gate_policy

    global_config = load_global_config()
    return global_config.trust_gate

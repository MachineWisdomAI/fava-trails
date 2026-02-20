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

# Trail names must be simple slugs: lowercase alphanumeric + hyphens
_TRAIL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def sanitize_trail_name(name: str) -> str:
    """Validate trail name is a safe filesystem slug.

    Rejects path traversal attempts (../, /, \\) and non-slug characters.
    """
    if not name or not _TRAIL_NAME_RE.match(name):
        raise ValueError(
            f"Invalid trail name: {name!r}. "
            "Trail names must be alphanumeric with hyphens/dots/underscores, "
            "starting with an alphanumeric character."
        )
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid trail name: {name!r}. Path traversal not allowed.")
    return name


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


def ensure_data_repo_root() -> Path:
    """Ensure the FAVA Trail data repo root and trails directories exist."""
    home = get_data_repo_root()
    home.mkdir(parents=True, exist_ok=True)
    trails_dir = get_trails_dir()
    trails_dir.mkdir(parents=True, exist_ok=True)
    return home

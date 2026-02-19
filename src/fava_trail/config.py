"""Configuration loading for FAVA Trail."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from .models import GlobalConfig, TrailConfig

logger = logging.getLogger(__name__)

DEFAULT_FAVA_HOME = os.path.expanduser("~/.fava-trail")


def get_fava_home() -> Path:
    """Get the FAVA Trail home directory from env or default."""
    return Path(os.environ.get("FAVA_TRAIL_HOME", DEFAULT_FAVA_HOME))


def get_trails_dir() -> Path:
    """Get the directory containing all trails.

    Priority:
    1. FAVA_TRAILS_DIR env var (highest — absolute path override)
    2. config.yaml trails_dir (absolute path used directly, relative resolved from FAVA_TRAIL_HOME)
    3. Default: $FAVA_TRAIL_HOME/trails
    """
    env_override = os.environ.get("FAVA_TRAILS_DIR")
    if env_override:
        return Path(env_override)

    home = get_fava_home()
    config = load_global_config()
    trails_path = Path(config.trails_dir)
    if trails_path.is_absolute():
        return trails_path
    return home / config.trails_dir


def load_global_config() -> GlobalConfig:
    """Load global configuration from config.yaml."""
    config_path = get_fava_home() / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return GlobalConfig(**data)
    return GlobalConfig()


def save_global_config(config: GlobalConfig) -> None:
    """Save global configuration to config.yaml."""
    config_path = get_fava_home() / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)


def load_trail_config(trail_name: str) -> TrailConfig:
    """Load trail-specific configuration."""
    trail_dir = get_trails_dir() / trail_name
    config_path = trail_dir / ".fava-trail.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("name", trail_name)
        return TrailConfig(**data)
    return TrailConfig(name=trail_name)


def save_trail_config(trail_name: str, config: TrailConfig) -> None:
    """Save trail-specific configuration."""
    trail_dir = get_trails_dir() / trail_name
    config_path = trail_dir / ".fava-trail.yaml"
    trail_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)


def ensure_fava_home() -> Path:
    """Ensure the FAVA Trail home directory exists."""
    home = get_fava_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "trails").mkdir(exist_ok=True)
    return home

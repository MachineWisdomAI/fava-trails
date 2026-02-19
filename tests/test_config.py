"""Tests for config.py path resolution."""

import os
from pathlib import Path

import pytest

from fava_trail.config import get_fava_home, get_trails_dir


def test_fava_home_default(monkeypatch, tmp_path):
    """Default home is ~/.fava-trail when no env var set."""
    monkeypatch.delenv("FAVA_TRAIL_HOME", raising=False)
    home = get_fava_home()
    assert home == Path(os.path.expanduser("~/.fava-trail"))


def test_fava_home_env_override(monkeypatch, tmp_path):
    """FAVA_TRAIL_HOME env var overrides default."""
    monkeypatch.setenv("FAVA_TRAIL_HOME", str(tmp_path / "custom"))
    home = get_fava_home()
    assert home == tmp_path / "custom"


def test_trails_dir_relative(monkeypatch, tmp_path):
    """Relative trails_dir in config resolves from FAVA_TRAIL_HOME."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FAVA_TRAIL_HOME", str(home))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    # No config.yaml means default trails_dir = "trails"
    result = get_trails_dir()
    assert result == home / "trails"


def test_trails_dir_absolute_in_config(monkeypatch, tmp_path):
    """Absolute trails_dir in config.yaml is used directly."""
    import yaml

    home = tmp_path / "home"
    home.mkdir()
    absolute_trails = tmp_path / "absolute-trails"

    config_path = home / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"trails_dir": str(absolute_trails)}, f)

    monkeypatch.setenv("FAVA_TRAIL_HOME", str(home))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    result = get_trails_dir()
    assert result == absolute_trails


def test_trails_dir_env_override(monkeypatch, tmp_path):
    """FAVA_TRAILS_DIR env var takes highest priority."""
    home = tmp_path / "home"
    home.mkdir()
    env_trails = tmp_path / "env-trails"

    monkeypatch.setenv("FAVA_TRAIL_HOME", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", str(env_trails))
    result = get_trails_dir()
    assert result == env_trails


def test_trails_dir_env_overrides_config(monkeypatch, tmp_path):
    """FAVA_TRAILS_DIR env var overrides even absolute config.yaml trails_dir."""
    import yaml

    home = tmp_path / "home"
    home.mkdir()
    config_trails = tmp_path / "config-trails"
    env_trails = tmp_path / "env-trails"

    config_path = home / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({"trails_dir": str(config_trails)}, f)

    monkeypatch.setenv("FAVA_TRAIL_HOME", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", str(env_trails))
    result = get_trails_dir()
    assert result == env_trails

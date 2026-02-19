"""Tests for config.py path resolution and trail name sanitization."""

import os
from pathlib import Path

import pytest

from fava_trail.config import (
    ensure_fava_home,
    get_fava_home,
    get_trails_dir,
    sanitize_trail_name,
)


def test_fava_home_default(monkeypatch, tmp_path):
    """Default home is ~/.fava-trail when no env var set."""
    monkeypatch.delenv("FAVA_TRAIL_DATA_REPO", raising=False)
    monkeypatch.delenv("FAVA_TRAIL_HOME", raising=False)
    home = get_fava_home()
    assert home == Path(os.path.expanduser("~/.fava-trail"))


def test_fava_home_env_override(monkeypatch, tmp_path):
    """FAVA_TRAIL_DATA_REPO env var overrides default."""
    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(tmp_path / "custom"))
    monkeypatch.delenv("FAVA_TRAIL_HOME", raising=False)
    home = get_fava_home()
    assert home == tmp_path / "custom"


def test_fava_home_legacy_env_compat(monkeypatch, tmp_path):
    """Deprecated FAVA_TRAIL_HOME still works as fallback."""
    monkeypatch.delenv("FAVA_TRAIL_DATA_REPO", raising=False)
    monkeypatch.setenv("FAVA_TRAIL_HOME", str(tmp_path / "legacy"))
    home = get_fava_home()
    assert home == tmp_path / "legacy"


def test_fava_home_new_env_takes_precedence(monkeypatch, tmp_path):
    """FAVA_TRAIL_DATA_REPO takes precedence over deprecated FAVA_TRAIL_HOME."""
    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(tmp_path / "new"))
    monkeypatch.setenv("FAVA_TRAIL_HOME", str(tmp_path / "old"))
    home = get_fava_home()
    assert home == tmp_path / "new"


def test_trails_dir_relative(monkeypatch, tmp_path):
    """Relative trails_dir in config resolves from FAVA_TRAIL_DATA_REPO."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(home))
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

    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(home))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    result = get_trails_dir()
    assert result == absolute_trails


def test_trails_dir_env_override(monkeypatch, tmp_path):
    """FAVA_TRAILS_DIR env var takes highest priority."""
    home = tmp_path / "home"
    home.mkdir()
    env_trails = tmp_path / "env-trails"

    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(home))
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

    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", str(env_trails))
    result = get_trails_dir()
    assert result == env_trails


# --- Trail name sanitization ---


def test_sanitize_valid_names():
    """Valid trail names pass sanitization."""
    assert sanitize_trail_name("default") == "default"
    assert sanitize_trail_name("my-project") == "my-project"
    assert sanitize_trail_name("wise-agents-toolkit") == "wise-agents-toolkit"
    assert sanitize_trail_name("project_v2") == "project_v2"
    assert sanitize_trail_name("project.name") == "project.name"


def test_sanitize_rejects_path_traversal():
    """Path traversal attempts are rejected."""
    with pytest.raises(ValueError, match="Invalid trail name"):
        sanitize_trail_name("../../.ssh")
    with pytest.raises(ValueError, match="Invalid trail name"):
        sanitize_trail_name("../etc/passwd")
    with pytest.raises(ValueError, match="Invalid trail name"):
        sanitize_trail_name("foo/bar")
    with pytest.raises(ValueError, match="Invalid trail name"):
        sanitize_trail_name("foo\\bar")


def test_sanitize_rejects_empty_and_special():
    """Empty strings and special characters are rejected."""
    with pytest.raises(ValueError, match="Invalid trail name"):
        sanitize_trail_name("")
    with pytest.raises(ValueError, match="Invalid trail name"):
        sanitize_trail_name("-starts-with-dash")
    with pytest.raises(ValueError, match="Invalid trail name"):
        sanitize_trail_name(".hidden")


def test_trails_dir_tilde_expansion(monkeypatch, tmp_path):
    """FAVA_TRAILS_DIR with tilde is expanded to user home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", "~/my-trails")
    result = get_trails_dir()
    expected = Path(os.path.expanduser("~/my-trails"))
    assert result == expected


def test_ensure_fava_home_creates_custom_trails_dir(monkeypatch, tmp_path):
    """ensure_fava_home creates the actual configured trails directory."""
    home = tmp_path / "home"
    custom_trails = tmp_path / "custom-trails"

    monkeypatch.setenv("FAVA_TRAIL_DATA_REPO", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", str(custom_trails))

    assert not home.exists()
    assert not custom_trails.exists()

    ensure_fava_home()

    assert home.exists()
    assert custom_trails.exists()

"""Tests for config.py path resolution and trail name sanitization."""

import os
from pathlib import Path

import pytest
import yaml

from fava_trails.config import (
    ConfigStore,
    ensure_data_repo_root,
    get_data_repo_root,
    get_trails_dir,
    load_global_config,
    sanitize_namespace,
    sanitize_scope_path,
)
from fava_trails.models import GlobalConfig


def test_fava_home_default(monkeypatch, tmp_path):
    """Default home is ~/.fava-trails when no env var set."""
    monkeypatch.delenv("FAVA_TRAILS_DATA_REPO", raising=False)
    home = get_data_repo_root()
    assert home == Path(os.path.expanduser("~/.fava-trails"))


def test_fava_home_env_override(monkeypatch, tmp_path):
    """FAVA_TRAILS_DATA_REPO env var overrides default."""
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path / "custom"))
    home = get_data_repo_root()
    assert home == tmp_path / "custom"


def test_trails_dir_relative(monkeypatch, tmp_path):
    """Relative trails_dir in config resolves from FAVA_TRAILS_DATA_REPO."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(home))
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

    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(home))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    result = get_trails_dir()
    assert result == absolute_trails


def test_trails_dir_env_override(monkeypatch, tmp_path):
    """FAVA_TRAILS_DIR env var takes highest priority."""
    home = tmp_path / "home"
    home.mkdir()
    env_trails = tmp_path / "env-trails"

    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(home))
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

    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", str(env_trails))
    result = get_trails_dir()
    assert result == env_trails


# --- Trail name sanitization ---


def test_sanitize_valid_names():
    """Valid trail names pass sanitization."""
    assert sanitize_scope_path("default") == "default"
    assert sanitize_scope_path("my-project") == "my-project"
    assert sanitize_scope_path("wise-agents-toolkit") == "wise-agents-toolkit"
    assert sanitize_scope_path("project_v2") == "project_v2"
    assert sanitize_scope_path("project.name") == "project.name"


def test_sanitize_rejects_path_traversal():
    """Path traversal attempts are rejected."""
    with pytest.raises(ValueError, match="Path traversal not allowed"):
        sanitize_scope_path("../../.ssh")
    with pytest.raises(ValueError, match="Path traversal not allowed"):
        sanitize_scope_path("../etc/passwd")
    with pytest.raises(ValueError, match="Path traversal not allowed"):
        sanitize_scope_path("foo\\bar")


def test_sanitize_accepts_scoped_paths():
    """Slash-separated scope paths are valid."""
    assert sanitize_scope_path("foo/bar") == "foo/bar"
    assert sanitize_scope_path("mw/eng/fava-trail") == "mw/eng/fava-trail"
    assert sanitize_scope_path("mw/eng/fava-trail/auth-epic") == "mw/eng/fava-trail/auth-epic"
    # Leading/trailing slashes are stripped
    assert sanitize_scope_path("/mw/eng/") == "mw/eng"
    assert sanitize_scope_path("mw/eng/") == "mw/eng"


def test_sanitize_rejects_empty_and_special():
    """Empty strings and special characters are rejected."""
    with pytest.raises(ValueError, match="cannot be empty"):
        sanitize_scope_path("")
    with pytest.raises(ValueError, match="Invalid scope segment"):
        sanitize_scope_path("-starts-with-dash")
    with pytest.raises(ValueError, match="Invalid scope segment"):
        sanitize_scope_path(".hidden")
    # Empty segments (double slash) rejected
    with pytest.raises(ValueError, match="Invalid scope segment"):
        sanitize_scope_path("a//b")


def test_trails_dir_tilde_expansion(monkeypatch, tmp_path):
    """FAVA_TRAILS_DIR with tilde is expanded to user home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", "~/my-trails")
    result = get_trails_dir()
    expected = Path(os.path.expanduser("~/my-trails"))
    assert result == expected


# --- Namespace sanitization ---


def test_sanitize_namespace_valid():
    """Valid namespaces pass sanitization."""
    assert sanitize_namespace("drafts") == "drafts"
    assert sanitize_namespace("decisions") == "decisions"
    assert sanitize_namespace("observations") == "observations"
    assert sanitize_namespace("preferences/client") == "preferences/client"
    assert sanitize_namespace("preferences/firm") == "preferences/firm"


def test_sanitize_namespace_rejects_traversal():
    """Path traversal via namespace is rejected."""
    with pytest.raises(ValueError, match="Invalid namespace"):
        sanitize_namespace("../../../../etc/ssh")
    with pytest.raises(ValueError, match="Invalid namespace"):
        sanitize_namespace("../../../.ssh")
    with pytest.raises(ValueError, match="Invalid namespace"):
        sanitize_namespace("/tmp/evil")


def test_sanitize_namespace_rejects_unknown():
    """Unknown namespaces are rejected."""
    with pytest.raises(ValueError, match="Invalid namespace"):
        sanitize_namespace("custom-namespace")
    with pytest.raises(ValueError, match="Invalid namespace"):
        sanitize_namespace("")


def test_ensure_data_repo_root_creates_custom_trails_dir(monkeypatch, tmp_path):
    """ensure_data_repo_root creates the actual configured trails directory."""
    home = tmp_path / "home"
    custom_trails = tmp_path / "custom-trails"

    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(home))
    monkeypatch.setenv("FAVA_TRAILS_DIR", str(custom_trails))

    assert not home.exists()
    assert not custom_trails.exists()

    ensure_data_repo_root()

    assert home.exists()
    assert custom_trails.exists()


# ─── ConfigStore ───


def test_config_store_singleton(monkeypatch, tmp_path):
    """ConfigStore.get() returns the same instance on repeated calls."""
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    a = ConfigStore.get()
    b = ConfigStore.get()
    assert a is b


def test_config_store_reset(monkeypatch, tmp_path):
    """ConfigStore.reset() clears cache; next get() re-reads disk."""
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    a = ConfigStore.get()
    ConfigStore.reset()
    b = ConfigStore.get()
    assert a is not b


def test_config_store_override(monkeypatch, tmp_path):
    """ConfigStore.override() injects a pre-built instance."""
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    injected = ConfigStore(
        global_config=GlobalConfig(push_strategy="immediate"),
        data_repo_root=tmp_path,
        trails_dir=tmp_path / "trails",
    )
    ConfigStore.override(injected)
    assert ConfigStore.get() is injected
    assert ConfigStore.get().global_config.push_strategy == "immediate"


def test_config_store_data_repo_root(monkeypatch, tmp_path):
    """ConfigStore.data_repo_root matches FAVA_TRAILS_DATA_REPO."""
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    store = ConfigStore.get()
    assert store.data_repo_root == tmp_path


def test_config_store_trails_dir_default(monkeypatch, tmp_path):
    """ConfigStore.trails_dir defaults to data_repo_root/trails."""
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    store = ConfigStore.get()
    assert store.trails_dir == tmp_path / "trails"


def test_load_global_config_delegates_to_store(monkeypatch, tmp_path):
    """load_global_config() returns ConfigStore.get().global_config."""
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    config = load_global_config()
    assert config is ConfigStore.get().global_config


def test_config_store_reads_hooks_from_config_yaml(monkeypatch, tmp_path):
    """ConfigStore parses hooks: key from config.yaml into GlobalConfig."""
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump({
            "hooks": [{"path": "./my_hook.py", "points": ["before_save"]}]
        }, f)
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(tmp_path))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    store = ConfigStore.get()
    assert len(store.global_config.hooks) == 1
    assert store.global_config.hooks[0].path == "./my_hook.py"


# --- Timeout config validation ---

def test_global_config_timeout_defaults():
    """Default timeout values are sane and satisfy the ordering constraint."""
    config = GlobalConfig()
    assert config.trust_gate_timeout_secs == 120
    assert config.tool_timeout_secs == 300
    assert config.trust_gate_timeout_secs < config.tool_timeout_secs


def test_global_config_timeout_validator_rejects_inversion():
    """trust_gate_timeout_secs >= tool_timeout_secs (both > 0) is rejected."""
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="must be less than tool_timeout_secs"):
        GlobalConfig(trust_gate_timeout_secs=300, tool_timeout_secs=120)


def test_global_config_timeout_validator_equal_values_rejected():
    """Equal values are also rejected — inner must fire strictly before outer."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="must be less than tool_timeout_secs"):
        GlobalConfig(trust_gate_timeout_secs=120, tool_timeout_secs=120)


def test_global_config_timeout_validator_allows_zero_trust_gate():
    """trust_gate_timeout_secs=0 disables the inner guard — no ordering constraint."""
    config = GlobalConfig(trust_gate_timeout_secs=0, tool_timeout_secs=120)
    assert config.trust_gate_timeout_secs == 0


def test_global_config_timeout_validator_allows_zero_tool():
    """tool_timeout_secs=0 disables the outer guard — no ordering constraint."""
    config = GlobalConfig(trust_gate_timeout_secs=120, tool_timeout_secs=0)
    assert config.tool_timeout_secs == 0


def test_global_config_timeout_validator_allows_both_zero():
    """Both disabled is valid (no hang protection, but user asked for it)."""
    config = GlobalConfig(trust_gate_timeout_secs=0, tool_timeout_secs=0)
    assert config.trust_gate_timeout_secs == 0
    assert config.tool_timeout_secs == 0


def test_global_config_timeout_rejects_negative():
    """Negative timeout values are rejected by NonNegativeInt."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GlobalConfig(trust_gate_timeout_secs=-1)
    with pytest.raises(ValidationError):
        GlobalConfig(tool_timeout_secs=-1)

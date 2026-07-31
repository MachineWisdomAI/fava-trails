"""Per-machine Trust Gate configuration and credential contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fava_trails.config import ConfigStore, load_effective_global_config, save_global_config
from fava_trails.credentials import load_trust_gate_api_key
from fava_trails.models import GlobalConfig
from fava_trails.readiness import ReadinessFailure, probe_data_repository


def _write_data_config(data_repo: Path) -> None:
    data_repo.mkdir()
    (data_repo / "config.yaml").write_text(
        "\n".join(
            (
                "trails_dir: trails",
                "remote_url: git@github.com:MachineWisdomAI/fava-trails-data.git",
                "trust_gate: llm-oneshot",
                "trust_gate_provider: openrouter",
                "trust_gate_model: google/gemini-2.5-flash",
                "openrouter_api_key_env: OPENROUTER_API_KEY",
                "trust_gate_timeout_secs: 120",
                "tool_timeout_secs: 300",
            )
        )
        + "\n"
    )


def test_machine_config_overrides_only_trust_gate_runtime_fields(tmp_path, monkeypatch):
    data_repo = tmp_path / "data"
    _write_data_config(data_repo)
    config_home = tmp_path / "config"
    machine_dir = config_home / "fava-trails"
    machine_dir.mkdir(parents=True)
    key_file = tmp_path / "local-api-key"
    (machine_dir / "config.yaml").write_text(
        "\n".join(
            (
                "trust_gate_provider: openai",
                "trust_gate_model: unsloth/Qwen3.6-27B-GGUF",
                "trust_gate_api_base: http://127.0.0.1:8888/v1",
                f'trust_gate_api_key_file: "{key_file}"',
                "trust_gate_timeout_secs: 240",
                "trust_gate_extra_body:",
                "  enable_thinking: false",
            )
        )
        + "\n"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    config = load_effective_global_config(data_repo)

    assert config.trails_dir == "trails"
    assert config.remote_url == "git@github.com:MachineWisdomAI/fava-trails-data.git"
    assert config.tool_timeout_secs == 300
    assert config.trust_gate_provider == "openai"
    assert config.trust_gate_model == "unsloth/Qwen3.6-27B-GGUF"
    assert config.trust_gate_api_base == "http://127.0.0.1:8888/v1"
    assert config.trust_gate_api_key_file == str(key_file)
    assert config.trust_gate_timeout_secs == 240
    assert config.trust_gate_extra_body == {"enable_thinking": False}


def test_absent_machine_config_preserves_data_repo_behavior(tmp_path, monkeypatch):
    data_repo = tmp_path / "data"
    _write_data_config(data_repo)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing-config-home"))

    config = load_effective_global_config(data_repo)

    assert config.trust_gate_provider == "openrouter"
    assert config.trust_gate_model == "google/gemini-2.5-flash"
    assert config.resolve_trust_gate_api_key_env() == "OPENROUTER_API_KEY"
    assert config.trust_gate_api_key_file is None
    assert config.trust_gate_extra_body == {}


def test_machine_config_rejects_non_runtime_keys(tmp_path, monkeypatch):
    data_repo = tmp_path / "data"
    _write_data_config(data_repo)
    machine_dir = tmp_path / "config" / "fava-trails"
    machine_dir.mkdir(parents=True)
    (machine_dir / "config.yaml").write_text("trails_dir: private-trails\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(ValueError, match="unsupported per-machine configuration key"):
        load_effective_global_config(data_repo)


def test_readiness_validates_effective_machine_config(tmp_path, monkeypatch):
    """Readiness cannot report healthy when the effective machine overlay is invalid."""
    data_repo = tmp_path / "data"
    _write_data_config(data_repo)
    (data_repo / "trails").mkdir()
    machine_dir = tmp_path / "config" / "fava-trails"
    machine_dir.mkdir(parents=True)
    (machine_dir / "config.yaml").write_text("trust_gate_timeout_secs: 300\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(ReadinessFailure, match="effective configuration is malformed"):
        probe_data_repository(data_repo)


def test_saving_global_config_does_not_persist_machine_overrides(tmp_path, monkeypatch):
    """Protocol setup must never leak machine model or credential paths into shared config."""
    data_repo = tmp_path / "data"
    _write_data_config(data_repo)
    config_home = tmp_path / "config"
    machine_dir = config_home / "fava-trails"
    machine_dir.mkdir(parents=True)
    (machine_dir / "config.yaml").write_text(
        "\n".join(
            (
                "trust_gate_provider: openai",
                "trust_gate_model: local-model",
                "trust_gate_api_key_file: /private/runtime/api-key",
                "trust_gate_extra_body:",
                "  enable_thinking: false",
            )
        )
        + "\n"
    )
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(data_repo))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    ConfigStore.reset()

    save_global_config(ConfigStore.get().global_config)

    persisted = yaml.safe_load((data_repo / "config.yaml").read_text())
    assert persisted["trust_gate_provider"] == "openrouter"
    assert persisted["trust_gate_model"] == "google/gemini-2.5-flash"
    assert "trust_gate_api_key_file" not in persisted
    assert "trust_gate_extra_body" not in persisted


def test_key_file_takes_precedence_and_requires_owner_only_regular_file(tmp_path, monkeypatch):
    key_file = tmp_path / "api-key"
    key_file.write_text("file-key\n")
    key_file.chmod(0o600)
    monkeypatch.setenv("FALLBACK_API_KEY", "env-key")
    config = GlobalConfig(
        trust_gate_api_key_file=str(key_file),
        trust_gate_api_key_env="FALLBACK_API_KEY",
    )

    assert load_trust_gate_api_key(config) == "file-key"

    key_file.chmod(0o640)
    with pytest.raises(ValueError, match="owner-only"):
        load_trust_gate_api_key(config)


def test_key_file_rejects_symlink_and_does_not_expose_path(tmp_path):
    target = tmp_path / "actual-secret"
    target.write_text("secret\n")
    target.chmod(0o600)
    link = tmp_path / "linked-secret"
    link.symlink_to(target)
    config = GlobalConfig(trust_gate_api_key_file=str(link))

    with pytest.raises(ValueError) as exc_info:
        load_trust_gate_api_key(config)

    assert "symlink" in str(exc_info.value).lower()
    assert str(link) not in str(exc_info.value)
    assert str(target) not in str(exc_info.value)


def test_key_file_is_read_each_time_for_safe_rotation(tmp_path):
    key_file = tmp_path / "api-key"
    key_file.write_text("old-key\n")
    key_file.chmod(0o600)
    config = GlobalConfig(trust_gate_api_key_file=str(key_file))

    assert load_trust_gate_api_key(config) == "old-key"
    key_file.write_text("new-key\n")
    assert load_trust_gate_api_key(config) == "new-key"


def test_key_file_invalid_utf8_uses_safe_generic_error(tmp_path):
    key_file = tmp_path / "api-key"
    key_file.write_bytes(b"\xff\xfe")
    key_file.chmod(0o600)
    config = GlobalConfig(trust_gate_api_key_file=str(key_file))

    with pytest.raises(ValueError, match="credential file is not readable") as exc_info:
        load_trust_gate_api_key(config)

    assert str(key_file) not in str(exc_info.value)
    assert "codec" not in str(exc_info.value)


def test_env_key_remains_backward_compatible(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    assert load_trust_gate_api_key(GlobalConfig()) == "openrouter-key"

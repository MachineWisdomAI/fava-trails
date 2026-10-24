"""Local review as the new-install default (tracking issue fava-trails.org#33).

Fixture-level evidence only: an in-process OpenAI-compatible server stands in for
the local reviewer. Nothing here shows that any real model reviews well, and no
test contacts a hosted provider, probes localhost, or downloads a model.
"""

from __future__ import annotations

import json
import socket
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from fava_trails import cli
from fava_trails.config import ConfigStore, get_machine_config_path, load_effective_global_config
from fava_trails.decisions import DEFAULT_DECISIONS_MODEL, NoulAnswer
from fava_trails.llm.client import LLMClient
from fava_trails.models import (
    DECISIONS_ONLY_MODELS,
    DEFAULT_TRUST_GATE_MODEL,
    GlobalConfig,
    SourceType,
)
from fava_trails.tools.navigation import handle_propose_truth
from fava_trails.trust_gate import TrustGatePromptCache

# Reuse the fixture OpenAI-compatible server from the local-provider tests.
from tests.test_trust_gate_local_provider import openai_server as _openai_server_fixture

openai_server = _openai_server_fixture

ENDPOINT = "http://127.0.0.1:8080/v1"
MODEL = "my-served-model"
KEY_ENV = "LOCAL_REVIEW_KEY"


def _args(path: Path, **kwargs) -> Namespace:
    base = {"path": str(path), "remote": None, "review_endpoint": None, "review_model": None, "review_key_env": None}
    base.update(kwargs)
    return Namespace(**base)


def _write_machine_config(data: dict) -> None:
    path = get_machine_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))


def _written(target: Path) -> dict:
    return yaml.safe_load((target / "config.yaml").read_text())


@pytest.fixture
def no_network(monkeypatch):
    """Bootstrap must never contact the endpoint (or anything else)."""

    def refuse(*args, **kwargs):
        raise AssertionError("bootstrap attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ─── bootstrap: complete selection ───────────────────────────────────────────


def test_bootstrap_with_all_options_writes_complete_selection(tmp_path, capsys, no_network):
    target = tmp_path / "repo"
    rc = cli.cmd_bootstrap(
        _args(target, review_endpoint=ENDPOINT, review_model=MODEL, review_key_env=KEY_ENV)
    )
    out = capsys.readouterr().out

    assert rc == 0
    config = _written(target)
    assert config["trust_gate"] == "llm-oneshot"
    assert config["trust_gate_provider"] == "openai"
    assert config["trust_gate_api_base"] == ENDPOINT
    assert config["trust_gate_model"] == MODEL
    assert config["trust_gate_api_key_env"] == KEY_ENV
    # Only the key *name* is stored, never a credential value.
    assert "api_key_file" not in json.dumps(config)
    # Machine config is never written by bootstrap.
    assert not get_machine_config_path().exists()
    assert "loopback endpoint" in out
    assert "FAVA did not contact the endpoint" in out

    effective = load_effective_global_config(target)
    effective.validate_trust_gate_runtime()
    assert (effective.trust_gate, effective.trust_gate_provider) == ("llm-oneshot", "openai")


def test_bootstrap_normalizes_trailing_slash_and_accepts_bare_host(tmp_path):
    rc = cli.cmd_bootstrap(
        _args(tmp_path / "a", review_endpoint="https://review.internal:9443/v1/", review_model=MODEL, review_key_env=KEY_ENV)
    )
    assert rc == 0
    assert _written(tmp_path / "a")["trust_gate_api_base"] == "https://review.internal:9443/v1"
    rc = cli.cmd_bootstrap(
        _args(tmp_path / "b", review_endpoint="http://localhost:11434", review_model=MODEL, review_key_env=KEY_ENV)
    )
    assert rc == 0
    assert _written(tmp_path / "b")["trust_gate_api_base"] == "http://localhost:11434"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://user:secret@127.0.0.1:8080/v1",
        "http://:secret@127.0.0.1:8080/v1",
        "http://127.0.0.1:8080/v1?api_key=secret",
        "http://127.0.0.1:8080/v1#secret",
        "http://127.0.0.1:8080/gateway-token-abc/v1",
        "http://127.0.0.1:8080/v1/extra",
        "http://127.0.0.1:8080/v1;params",
        "ftp://127.0.0.1/v1",
        "127.0.0.1:8080/v1",
        "http://",
        "http://127.0.0.1:notaport/v1",
        "http://127.0.0.1 :8080/v1",
        "",
    ],
)
def test_bootstrap_refuses_unsafe_endpoints_without_creating_anything(tmp_path, capsys, endpoint):
    target = tmp_path / "repo"
    rc = cli.cmd_bootstrap(_args(target, review_endpoint=endpoint, review_model=MODEL, review_key_env=KEY_ENV))
    captured = capsys.readouterr()

    assert rc != 0
    assert not target.exists()
    assert "--review-endpoint" in captured.err
    # The refused value may hold a credential and must never be echoed.
    assert "secret" not in captured.err + captured.out
    assert "gateway-token-abc" not in captured.err + captured.out


@pytest.mark.parametrize("model", list(DECISIONS_ONLY_MODELS) + ["has space", "", "x" * 201])
def test_bootstrap_refuses_decisions_only_or_malformed_model(tmp_path, capsys, model):
    rc = cli.cmd_bootstrap(_args(tmp_path / "r", review_endpoint=ENDPOINT, review_model=model, review_key_env=KEY_ENV))
    assert rc != 0
    assert not (tmp_path / "r").exists()
    assert "--review-model" in capsys.readouterr().err


@pytest.mark.parametrize("key_env", ["sk-or-v1-abc123", "has space", "", "1STARTS_WITH_DIGIT", "KEY=value"])
def test_bootstrap_refuses_key_env_that_is_not_a_variable_name(tmp_path, capsys, key_env):
    rc = cli.cmd_bootstrap(_args(tmp_path / "r", review_endpoint=ENDPOINT, review_model=MODEL, review_key_env=key_env))
    captured = capsys.readouterr()
    assert rc != 0
    assert not (tmp_path / "r").exists()
    assert "--review-key-env" in captured.err
    assert key_env == "" or key_env not in captured.err + captured.out


def test_bootstrap_warns_when_loopback_endpoint_meets_remote(tmp_path, capsys):
    cli.cmd_bootstrap(
        _args(
            tmp_path / "r",
            remote="git@example.com:org/data.git",
            review_endpoint=ENDPOINT,
            review_model=MODEL,
            review_key_env=KEY_ENV,
        )
    )
    assert "loopback" in capsys.readouterr().err
    cli.cmd_bootstrap(
        _args(
            tmp_path / "s",
            remote="git@example.com:org/data.git",
            review_endpoint="https://review.example.com/v1",
            review_model=MODEL,
            review_key_env=KEY_ENV,
        )
    )
    assert "loopback" not in capsys.readouterr().err


# ─── bootstrap: incomplete selection ─────────────────────────────────────────


@pytest.mark.parametrize(
    "given,missing_flags",
    [
        ({}, ["--review-endpoint", "--review-model", "--review-key-env"]),
        ({"review_model": MODEL}, ["--review-endpoint", "--review-key-env"]),
        ({"review_endpoint": ENDPOINT, "review_key_env": KEY_ENV}, ["--review-model"]),
    ],
)
def test_bootstrap_with_missing_options_writes_policy_only_and_says_what_to_supply(
    tmp_path, capsys, no_network, given, missing_flags
):
    target = tmp_path / "repo"
    rc = cli.cmd_bootstrap(_args(target, **given))
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    config = _written(target)
    assert config["trust_gate"] == "llm-oneshot"
    for key in ("trust_gate_provider", "trust_gate_api_base", "trust_gate_model", "trust_gate_api_key_env"):
        assert key not in config
    for flag in missing_flags:
        assert flag in captured.out
    assert "fail closed" in captured.out
    assert "does not probe localhost" in captured.out
    assert "0.8.x" in captured.err and "0.7" in captured.err  # release-compatibility warning
    assert not get_machine_config_path().exists()

    effective = load_effective_global_config(target)
    with pytest.raises(ValueError, match="trust_gate_model"):
        effective.validate_trust_gate_runtime()


@pytest.mark.parametrize(
    "machine,given,expect_rc,expect_in_out",
    [
        # Machine file supplies a hosted model: partial selection can now transmit.
        ({"trust_gate_model": "google/gemini-2.5-flash"}, {"review_model": MODEL}, 1, "trust_gate_model"),
        # Machine file redirects the base URL of a complete local selection.
        (
            {"trust_gate_api_base": "https://hosted.example.com/v1"},
            {"review_endpoint": ENDPOINT, "review_model": MODEL, "review_key_env": KEY_ENV},
            1,
            "trust_gate_api_base",
        ),
        # Machine file switches the policy to decisions.
        (
            {"trust_gate": "decisions"},
            {"review_endpoint": ENDPOINT, "review_model": MODEL, "review_key_env": KEY_ENV},
            1,
            "trust_gate",
        ),
        # Machine file replaces the model of a complete selection.
        (
            {"trust_gate_model": "other-model"},
            {"review_endpoint": ENDPOINT, "review_model": MODEL, "review_key_env": KEY_ENV},
            1,
            "trust_gate_model",
        ),
        # A key file changes the credential source, not the destination: reported, exit 0.
        (
            {"trust_gate_api_key_file": "/nonexistent/key"},
            {"review_endpoint": ENDPOINT, "review_model": MODEL, "review_key_env": KEY_ENV},
            0,
            "trust_gate_api_key_file",
        ),
        # A machine file that supplies a *loopback* completion of a partial selection stays local.
        (
            {"trust_gate_api_base": "http://127.0.0.1:9000/v1", "trust_gate_model": "m", "trust_gate_provider": "openai"},
            {},
            0,
            "trust_gate_api_base",
        ),
    ],
)
def test_bootstrap_reports_machine_overrides_and_exit_status(tmp_path, capsys, machine, given, expect_rc, expect_in_out):
    _write_machine_config(machine)
    machine_before = get_machine_config_path().read_text()

    target = tmp_path / "repo"
    rc = cli.cmd_bootstrap(_args(target, **given))
    captured = capsys.readouterr()

    assert rc == expect_rc, captured.out + captured.err
    assert target.exists() and (target / ".jj").exists()  # repository is created either way
    assert "per-machine config overrides" in captured.out
    assert expect_in_out in captured.out.split("per-machine config overrides")[1]
    if expect_rc:
        assert "differs from the one requested" in captured.err
    # Bootstrap never rewrites the shared per-machine file.
    assert get_machine_config_path().read_text() == machine_before


def test_bootstrap_with_broken_machine_config_reports_and_exits_nonzero(tmp_path, capsys):
    _write_machine_config({"trails_dir": "elsewhere"})  # not a Trust Gate key
    rc = cli.cmd_bootstrap(_args(tmp_path / "r", review_endpoint=ENDPOINT, review_model=MODEL, review_key_env=KEY_ENV))
    out = capsys.readouterr().out
    assert rc == 1
    assert "Could not evaluate the effective configuration" in out
    assert (tmp_path / "r" / ".jj").exists()


# ─── configuration precedence and legacy configurations ──────────────────────


def _load(tmp_path: Path, data: dict, machine: dict | None = None) -> GlobalConfig:
    repo = tmp_path / "data-repo"
    repo.mkdir(exist_ok=True)
    (repo / "config.yaml").write_text(yaml.dump({"trails_dir": "trails", **data}))
    if machine is not None:
        _write_machine_config(machine)
    return load_effective_global_config(repo)


LOCAL_DECISIONS = {
    "trust_gate_provider": "openai",
    "trust_gate_model": "laya-typed-decisions",
    "trust_gate_api_base": "http://127.0.0.1:8888/v1",
}


@pytest.mark.parametrize(
    "stated,effective,blocked,note",
    [
        # (stated keys) -> (policy, provider, model); row-for-row from the Blueprint table.
        ({}, ("decisions", "openrouter", DEFAULT_TRUST_GATE_MODEL), False, False),
        (
            {"trust_gate": "decisions", "trust_gate_provider": "openrouter", "trust_gate_model": DEFAULT_TRUST_GATE_MODEL},
            ("decisions", "openrouter", DEFAULT_TRUST_GATE_MODEL),
            False,
            False,
        ),
        (
            {"trust_gate": "decisions", "trust_gate_model": "typesafe/jev-1.13"},
            ("decisions", "openrouter", "typesafe/jev-1.13"),
            False,
            False,
        ),
        (
            {"trust_gate": "llm-oneshot", "trust_gate_model": "google/gemini-2.5-flash"},
            ("llm-oneshot", "openrouter", "google/gemini-2.5-flash"),
            False,
            False,
        ),
        # Local Decisions form without a stated policy: unchanged, note emitted.
        (LOCAL_DECISIONS, ("decisions", "openai", "laya-typed-decisions"), False, True),
        # Pre-0.8 chat configurations without a policy: still resolve as before, note emitted.
        (
            {"trust_gate_provider": "openai", "trust_gate_model": "qwen3-8b", "trust_gate_api_base": "http://127.0.0.1:8888/v1"},
            ("decisions", "openai", "qwen3-8b"),
            False,
            True,
        ),
        ({"trust_gate_model": "google/gemini-2.5-flash"}, ("decisions", "openrouter", "google/gemini-2.5-flash"), False, True),
        # llm-oneshot with no model: the Decisions-only default is refused.
        ({"trust_gate": "llm-oneshot"}, ("llm-oneshot", "openrouter", DEFAULT_TRUST_GATE_MODEL), True, False),
        (
            {"trust_gate": "llm-oneshot", "trust_gate_provider": "openai", "trust_gate_api_base": ENDPOINT},
            ("llm-oneshot", "openai", DEFAULT_TRUST_GATE_MODEL),
            True,
            False,
        ),
        (
            {"trust_gate": "llm-oneshot", "trust_gate_model": "typesafe/jev-1.13"},
            ("llm-oneshot", "openrouter", "typesafe/jev-1.13"),
            True,
            False,
        ),
    ],
)
def test_legacy_and_partial_configurations_resolve_unchanged(tmp_path, stated, effective, blocked, note):
    config = _load(tmp_path, stated)

    # Resolution is exactly the per-key fallback; nothing is reinterpreted or rewritten.
    assert (config.trust_gate, config.trust_gate_provider, config.trust_gate_model) == effective
    assert config.model_dump(exclude_unset=True).keys() - {"trails_dir"} == stated.keys()

    if blocked:
        with pytest.raises(ValueError, match="trust_gate_model"):
            config.check_review_model_for_policy()
        with pytest.raises(ValueError, match="trust_gate_model"):
            config.validate_trust_gate_runtime()
    else:
        config.check_review_model_for_policy()
        config.validate_trust_gate_runtime()

    assert (config.trust_gate_policy_note() is not None) is note


def test_decisions_constants_match_the_decisions_client_default():
    assert DEFAULT_DECISIONS_MODEL in DECISIONS_ONLY_MODELS
    assert DEFAULT_TRUST_GATE_MODEL in DECISIONS_ONLY_MODELS


def test_machine_config_overrides_data_repo_key_by_key(tmp_path):
    data = {
        "trust_gate": "llm-oneshot",
        "trust_gate_provider": "openai",
        "trust_gate_api_base": ENDPOINT,
        "trust_gate_model": MODEL,
        "trust_gate_api_key_env": KEY_ENV,
    }
    config = _load(tmp_path, data, machine={"trust_gate_model": "machine-model"})
    assert config.trust_gate_model == "machine-model"  # machine wins
    assert config.trust_gate_api_base == ENDPOINT  # untouched keys come from the data repo
    assert config.trust_gate_api_key_env == KEY_ENV
    assert config.trust_gate == "llm-oneshot"

    # With no machine file the data repository states the whole selection.
    get_machine_config_path().unlink()
    bare = _load(tmp_path, data, machine=None)
    assert bare.trust_gate_model == MODEL


def test_machine_file_can_complete_a_policy_only_repository(tmp_path):
    config = _load(
        tmp_path,
        {"trust_gate": "llm-oneshot"},
        machine={
            "trust_gate_provider": "openai",
            "trust_gate_api_base": ENDPOINT,
            "trust_gate_model": MODEL,
            "trust_gate_api_key_env": KEY_ENV,
        },
    )
    config.validate_trust_gate_runtime()
    assert config.trust_gate_model == MODEL


@pytest.mark.parametrize(
    "explicit",
    [
        {"trust_gate": "decisions"},
        {"trust_gate": "decisions", "trust_gate_model": "typesafe/jev-1.13"},
        {"trust_gate": "decisions", "trust_gate_provider": "openrouter", "trust_gate_model": DEFAULT_TRUST_GATE_MODEL},
        {"trust_gate": "decisions", **LOCAL_DECISIONS},
    ],
)
def test_explicit_decisions_selections_survive_without_error_or_note(tmp_path, explicit):
    config = _load(tmp_path, explicit)
    assert config.trust_gate == "decisions"
    config.check_review_model_for_policy()  # Jev is valid under decisions
    config.validate_trust_gate_runtime()
    assert config.trust_gate_policy_note() is None


def test_trail_pinned_policy_is_not_second_guessed(tmp_path):
    config = _load(tmp_path, {"trust_gate_model": "google/gemini-2.5-flash"})
    assert config.trust_gate_policy_note("decisions") is not None
    # A trail that pins a different policy is an explicit operator choice.
    assert config.trust_gate_policy_note("some-other-policy") is None
    # The model check applies to the trail's effective policy.
    jev = _load(tmp_path, {})
    jev.check_review_model_for_policy("decisions")
    with pytest.raises(ValueError, match="trust_gate_model"):
        jev.check_review_model_for_policy("llm-oneshot")


def test_rewritten_config_with_defaults_made_explicit_silences_note(tmp_path):
    config = _load(tmp_path, LOCAL_DECISIONS)
    assert config.trust_gate_policy_note() is not None
    rewritten = _load(tmp_path, config.model_dump(mode="json", exclude={"trails", "hooks"}))
    assert rewritten.trust_gate_policy_note() is None
    # The comparison is against FAVA's constants, so an explicit default is still caught.
    defaults = _load(tmp_path, {}).model_dump(mode="json", exclude={"trails", "hooks"})
    again = _load(tmp_path, {**defaults, "trust_gate": "llm-oneshot"})
    assert again.trust_gate_model == DEFAULT_TRUST_GATE_MODEL
    with pytest.raises(ValueError, match="trust_gate_model"):
        again.check_review_model_for_policy()


# ─── promotion: model check, guidance, explanations, fail-closed ─────────────


def _install_config(tmp_fava_home: Path, **fields) -> GlobalConfig:
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(**fields)
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)
    return cfg.global_config


def _cache() -> MagicMock:
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer. Reply with JSON."
    return cache


async def _draft(trail_manager, text="A candidate worth reviewing."):
    return await trail_manager.save_thought(content=text, agent_id="test-agent", source_type=SourceType.OBSERVATION)


@pytest.mark.asyncio
@pytest.mark.parametrize("jev_model", sorted(DECISIONS_ONLY_MODELS))
async def test_llm_oneshot_with_decisions_model_errors_before_any_call(trail_manager, tmp_fava_home, openai_server, jev_model):
    base_url, handler = openai_server
    record = await _draft(trail_manager)
    _install_config(
        tmp_fava_home,
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_api_base=base_url,
        trust_gate_model=jev_model,
        trust_gate_api_key_env=KEY_ENV,
    )
    review = AsyncMock()
    with patch.dict("os.environ", {KEY_ENV: "test-local-key"}), patch("fava_trails.tools.navigation.review_thought", review):
        result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())

    assert result["status"] == "error"
    assert "trust_gate_model" in result["message"]
    assert "trust_gate_api_base" in result["message"]  # actionable guidance
    assert "trust_gate_api_key_env" in result["message"]
    review.assert_not_awaited()
    assert handler.call_count == 0
    assert "trust_gate_egress" not in result  # nothing was disclosed because nothing was sent
    still = await trail_manager.get_thought(record.thought_id)
    assert still.frontmatter.validation_status.value == "draft"


@pytest.mark.asyncio
async def test_policy_only_repository_fails_closed_without_contacting_anything(trail_manager, tmp_fava_home, openai_server):
    base_url, handler = openai_server
    record = await _draft(trail_manager)
    _install_config(tmp_fava_home, trust_gate="llm-oneshot")  # what bootstrap writes when options are missing
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "would-be-hosted-key"}), patch.object(
        LLMClient, "chat", new=AsyncMock()
    ) as chat:
        result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())

    assert result["status"] == "error"
    assert "trust_gate_model" in result["message"]
    chat.assert_not_awaited()  # no hosted fallback even though a hosted credential exists
    assert handler.call_count == 0


@pytest.mark.asyncio
async def test_explicit_human_approval_is_unaffected_by_the_model_check(trail_manager, tmp_fava_home, monkeypatch):
    monkeypatch.setenv("FAVA_TRAILS_OPERATOR", "1")
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "operator-test")
    record = await trail_manager.save_thought(content="Operator-approved.", agent_id="operator-test", source_type=SourceType.DECISION)
    _install_config(tmp_fava_home, trust_gate="llm-oneshot")  # default Jev model under the chat policy
    result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id, "approval": "human"}, prompt_cache=_cache())
    assert result["status"] == "ok"
    assert "trust_gate_policy_note" not in result


@pytest.mark.asyncio
async def test_new_install_style_config_approves_and_local_explanation_reaches_caller(trail_manager, tmp_fava_home, openai_server):
    base_url, handler = openai_server
    _install_config(
        tmp_fava_home,
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_api_base=base_url,
        trust_gate_model="fixture-local-model",
        trust_gate_api_key_env=KEY_ENV,
    )
    approved = await _draft(trail_manager, "Solid observation.")
    rejected = await _draft(trail_manager, "Weak claim.")

    with patch.dict("os.environ", {KEY_ENV: "test-local-key"}):
        handler.response_mode = "approve"
        ok = await handle_propose_truth(trail_manager, {"thought_id": approved.thought_id}, prompt_cache=_cache())
        handler.response_mode = "reject"
        no = await handle_propose_truth(trail_manager, {"thought_id": rejected.thought_id}, prompt_cache=_cache())

    assert ok["status"] == "ok"
    assert ok["trust_gate"]["verdict"] == "approve"
    assert ok["trust_gate"]["reasoning"] == "Solid observation."
    assert ok["thought"]["validation_status"] == "approved"
    # Reviewer explanation reaches the caller in the structured field and the message.
    assert no["status"] == "rejected"
    assert no["trust_gate"]["reasoning"] == "Not suitable for promotion."
    assert "Not suitable for promotion." in no["message"]
    assert "noul_probability" not in no["trust_gate"]
    assert handler.call_count == 2


@pytest.mark.asyncio
async def test_explicit_jev_reports_probability_and_threshold_without_fabricated_reasoning(trail_manager, tmp_fava_home):
    _install_config(tmp_fava_home, trust_gate="decisions")
    record = await _draft(trail_manager)
    answer = NoulAnswer(probability=0.2, provider="openrouter", model="typesafe/jev-1.13-20260917")
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-only-key"}), patch(
        "fava_trails.decisions.DecisionsClient.ask_noul", new=AsyncMock(return_value=answer)
    ):
        result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())

    assert result["status"] == "rejected"
    info = result["trust_gate"]
    assert info["policy"] == "decisions"
    assert info["noul_probability"] == 0.2
    assert info["threshold"] == 0.45
    assert "0.2" in info["reasoning"] and "0.45" in info["reasoning"]
    assert "none is fabricated" in info["reasoning"]
    assert "trust_gate_policy_note" not in result or "decisions" in result["trust_gate_policy_note"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unauthorized", "malformed"])
async def test_local_unauthorized_and_malformed_fail_closed_without_hosted_fallback(trail_manager, tmp_fava_home, openai_server, mode):
    base_url, handler = openai_server
    handler.response_mode = mode
    record = await _draft(trail_manager)
    _install_config(
        tmp_fava_home,
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_api_base=base_url,
        trust_gate_model="fixture-local-model",
        trust_gate_api_key_env=KEY_ENV,
    )
    seen: list[dict] = []
    import any_llm

    real = any_llm.acompletion

    async def spy(*args, **kwargs):
        seen.append({"provider": kwargs.get("provider"), "api_base": kwargs.get("api_base")})
        return await real(*args, **kwargs)

    with patch.dict("os.environ", {KEY_ENV: "test-local-key", "OPENROUTER_API_KEY": "hosted"}), patch.object(any_llm, "acompletion", spy):
        result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())

    assert result["status"] == "error"
    assert result["trust_gate"]["verdict"] == "error"
    assert seen and all(call == {"provider": "openai", "api_base": base_url} for call in seen)
    still = await trail_manager.get_thought(record.thought_id)
    assert still.frontmatter.validation_status.value != "approved"


@pytest.mark.asyncio
async def test_unavailable_local_server_fails_closed_without_hosted_fallback(trail_manager, tmp_fava_home):
    with socket.socket() as probe:  # a loopback port with nothing listening
        probe.bind(("127.0.0.1", 0))
        dead_url = f"http://127.0.0.1:{probe.getsockname()[1]}/v1"
    record = await _draft(trail_manager)
    _install_config(
        tmp_fava_home,
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_api_base=dead_url,
        trust_gate_model="fixture-local-model",
        trust_gate_api_key_env=KEY_ENV,
    )
    with patch.dict("os.environ", {KEY_ENV: "test-local-key", "OPENROUTER_API_KEY": "hosted"}):
        result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())

    assert result["status"] == "error"
    assert result["trust_gate"]["provider"] == "openai"
    assert result["trust_gate_egress"]["destination_kind"] == "local_endpoint"
    still = await trail_manager.get_thought(record.thought_id)
    assert still.frontmatter.validation_status.value != "approved"


@pytest.mark.asyncio
async def test_missing_credential_for_local_review_names_the_variable(trail_manager, tmp_fava_home, openai_server, monkeypatch):
    base_url, handler = openai_server
    monkeypatch.delenv(KEY_ENV, raising=False)
    record = await _draft(trail_manager)
    _install_config(
        tmp_fava_home,
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_api_base=base_url,
        trust_gate_model="fixture-local-model",
        trust_gate_api_key_env=KEY_ENV,
    )
    result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())
    assert result["status"] == "error"
    assert KEY_ENV in result["message"]
    assert handler.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("configured,expected", [(200, 200.0), (0, 60.0)])
async def test_configured_timeout_reaches_every_chat_request(trail_manager, tmp_fava_home, openai_server, configured, expected):
    base_url, _ = openai_server
    record = await _draft(trail_manager)
    _install_config(
        tmp_fava_home,
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_api_base=base_url,
        trust_gate_model="fixture-local-model",
        trust_gate_api_key_env=KEY_ENV,
        trust_gate_timeout_secs=configured,
        tool_timeout_secs=300,
    )
    chat = AsyncMock(return_value=MagicMock(content='{"verdict": "approve", "reasoning": "ok"}', model="m", provider="openai"))
    with patch.dict("os.environ", {KEY_ENV: "test-local-key"}), patch.object(LLMClient, "chat", chat):
        result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())

    assert result["status"] == "ok"
    assert chat.await_args.kwargs["timeout"] == expected


@pytest.mark.asyncio
async def test_slow_local_reviewer_succeeds_when_timeout_exceeds_the_client_default(trail_manager, tmp_fava_home, openai_server):
    """The configured value must be what the HTTP layer honours, not the 60 s default."""
    base_url, handler = openai_server
    handler.delay_secs = 1.5
    record = await _draft(trail_manager)
    _install_config(
        tmp_fava_home,
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_api_base=base_url,
        trust_gate_model="fixture-local-model",
        trust_gate_api_key_env=KEY_ENV,
        trust_gate_timeout_secs=20,
        tool_timeout_secs=60,
    )
    with patch.dict("os.environ", {KEY_ENV: "test-local-key"}):
        result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())
    assert result["status"] == "ok"
    assert handler.call_count == 1


# ─── informational policy note on failed promotion ───────────────────────────


@pytest.mark.asyncio
async def test_failed_promotion_with_unstated_policy_carries_note_but_same_behavior(trail_manager, tmp_fava_home, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    record = await _draft(trail_manager)
    # A pre-0.8 style configuration: model stated, policy not.
    _install_config(tmp_fava_home, trust_gate_model="google/gemini-2.5-flash")
    result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())

    assert result["status"] == "error"  # credential missing: behavior unchanged, still decisions policy
    note = result["trust_gate_policy_note"]
    assert "'decisions'" in note and "trust_gate: llm-oneshot" in note
    assert "trust_gate_egress" in result and result["trust_gate_egress"]["policy"] == "decisions"


@pytest.mark.asyncio
async def test_failed_promotion_with_stated_policy_has_no_note(trail_manager, tmp_fava_home, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    record = await _draft(trail_manager)
    _install_config(tmp_fava_home, trust_gate="decisions", trust_gate_model="typesafe/jev-1.13")
    result = await handle_propose_truth(trail_manager, {"thought_id": record.thought_id}, prompt_cache=_cache())
    assert result["status"] == "error"
    assert "trust_gate_policy_note" not in result


# ─── doctor ──────────────────────────────────────────────────────────────────


def _doctor(tmp_path: Path, monkeypatch, config: dict, capsys) -> tuple[int, str]:
    repo = tmp_path / "doctor-repo"
    (repo / "trails").mkdir(parents=True)
    (repo / "config.yaml").write_text(yaml.dump({"trails_dir": "trails", **config}))
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(repo))
    monkeypatch.setenv(KEY_ENV, "placeholder")
    ConfigStore.reset()
    rc = cli.cmd_doctor(Namespace())
    return rc, capsys.readouterr().out


def test_doctor_reports_policy_only_repository_with_actionable_guidance(tmp_path, monkeypatch, capsys):
    rc, out = _doctor(tmp_path, monkeypatch, {"trust_gate": "llm-oneshot"}, capsys)
    assert rc == 1
    assert "Trust Gate:   INVALID" in out
    assert "trust_gate_model" in out and "trust_gate_api_base" in out


def test_doctor_accepts_a_complete_local_selection_and_shows_local_destination(tmp_path, monkeypatch, capsys):
    rc, out = _doctor(
        tmp_path,
        monkeypatch,
        {
            "trust_gate": "llm-oneshot",
            "trust_gate_provider": "openai",
            "trust_gate_api_base": ENDPOINT,
            "trust_gate_model": MODEL,
            "trust_gate_api_key_env": KEY_ENV,
        },
        capsys,
    )
    assert "INVALID" not in out.split("Trust Gate:")[1].split("\n")[0]
    assert "local_endpoint" in out
    assert f"{KEY_ENV} is set" in out


def test_doctor_prints_policy_note_for_unstated_policy(tmp_path, monkeypatch, capsys):
    _, out = _doctor(tmp_path, monkeypatch, {"trust_gate_model": "qwen3-8b"}, capsys)
    assert "trust_gate is not stated" in out


# ─── tunnel preflight ────────────────────────────────────────────────────────


def test_tunnel_preflight_refuses_llm_oneshot_with_decisions_model(tmp_path, monkeypatch):
    from fava_trails.tunnel_cli import _load_gateway_config

    repo = tmp_path / "tunnel-repo"
    (repo / "trails").mkdir(parents=True)
    (repo / "config.yaml").write_text(yaml.dump({"trails_dir": "trails", "trust_gate": "llm-oneshot"}))
    monkeypatch.setenv(KEY_ENV, "placeholder")

    with patch("fava_trails.tunnel_cli._find_jj_bin", return_value="/usr/bin/jj"), patch(
        "shutil.which", return_value="/usr/bin/tunnel-client"
    ):
        with pytest.raises(ValueError, match="trust_gate_model"):
            _load_gateway_config(Namespace(data_repo=str(repo), profile="fava-trails", tunnel_client=None))

"""Trust Gate data-egress disclosure and local-only verification (issue #101)."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from any_llm.exceptions import AnyLLMError, ProviderError

from fava_trails.config import ConfigStore
from fava_trails.llm import LLMClient
from fava_trails.models import GlobalConfig, SourceType
from fava_trails.tools.navigation import handle_propose_truth
from fava_trails.trust_gate import (
    TrustGatePromptCache,
    describe_trust_gate_egress,
    format_trust_gate_egress_notice,
    log_trust_gate_egress_notice,
    mark_trust_gate_egress_disclosed,
    redact_trust_gate_api_base_for_disclosure,
    reset_trust_gate_egress_disclosure_state,
    review_thought,
)
from tests.test_trust_gate_local_provider import _OpenAICompatibleHandler


@pytest.fixture
def openai_server():
    """In-process OpenAI-compatible HTTP server for intercepted outbound checks."""
    import threading
    from http.server import HTTPServer

    handler = _OpenAICompatibleHandler
    handler.expected_api_key = "test-local-key"
    handler.response_mode = "approve"
    handler.delay_secs = 0.0
    handler.last_auth = None
    handler.last_body = None
    handler.call_count = 0

    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/v1", handler
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_describe_openrouter_default_is_remote_egress_without_secrets():
    notice = describe_trust_gate_egress(GlobalConfig())
    assert notice["policy"] == "llm-oneshot"
    assert notice["provider"] == "openrouter"
    assert notice["model"] == "google/gemini-2.5-flash"
    assert notice["destination_kind"] == "remote_provider"
    assert "openrouter" in notice["destination"].lower()
    assert "candidate thought content" in notice["data_sent_summary"].lower()
    assert "redacted metadata" in notice["data_sent_summary"].lower()
    assert notice["rejection_happens_after_transmission"] is True
    assert notice["cloud_fallback"] is False
    text = format_trust_gate_egress_notice(notice)
    assert "data-egress" in text.lower() or "data egress" in text.lower()
    assert "after transmission" in text.lower()
    assert "sk-" not in text
    assert "api key" not in text.lower() or "credential" in text.lower()
    blob = json.dumps(notice)
    assert "OPENROUTER_API_KEY" in blob  # env *name* is OK
    assert "sk-" not in blob


def test_describe_local_endpoint_marks_local_destination():
    notice = describe_trust_gate_egress(
        GlobalConfig(
            trust_gate_provider="openai",
            trust_gate_model="fixture-local-model",
            trust_gate_api_base="http://127.0.0.1:8888/v1",
            trust_gate_api_key_env="LOCAL_TG_KEY",
        )
    )
    assert notice["destination_kind"] == "local_endpoint"
    assert notice["destination"] == "http://127.0.0.1:8888/v1"
    assert notice["provider"] == "openai"
    assert notice["model"] == "fixture-local-model"
    assert notice["cloud_fallback"] is False
    text = format_trust_gate_egress_notice(notice)
    assert "127.0.0.1:8888" in text
    assert "no automatic fallback" in text.lower() or "never silently fall back" in text.lower()


def test_describe_never_includes_key_file_path_or_secret(tmp_path):
    key_file = tmp_path / "secret-key-path"
    key_file.write_text("super-secret-key-value\n")
    key_file.chmod(0o600)
    notice = describe_trust_gate_egress(
        GlobalConfig(
            trust_gate_provider="openai",
            trust_gate_model="local-model",
            trust_gate_api_base="http://127.0.0.1:9/v1",
            trust_gate_api_key_file=str(key_file),
        )
    )
    blob = json.dumps(notice) + format_trust_gate_egress_notice(notice)
    assert "super-secret-key-value" not in blob
    assert str(key_file) not in blob
    assert notice["credential_source"] == "credential file"


def test_redact_api_base_strips_userinfo_query_and_fragment():
    dirty = "http://operator:supersecret@127.0.0.1:8888/v1?token=alsosecret#frag"
    clean = redact_trust_gate_api_base_for_disclosure(dirty)
    assert clean == "http://127.0.0.1:8888/v1"
    assert "supersecret" not in clean
    assert "alsosecret" not in clean
    assert "operator" not in clean
    assert "token=" not in clean
    assert "#frag" not in clean


def test_redact_api_base_redacts_non_v1_path_segments():
    dirty = "https://api.example/v1/secret-token"
    clean = redact_trust_gate_api_base_for_disclosure(dirty)
    assert clean == "https://api.example/[redacted]"
    assert "secret-token" not in clean
    notice = describe_trust_gate_egress(
        GlobalConfig(
            trust_gate_provider="openai",
            trust_gate_model="m",
            trust_gate_api_base=dirty,
            trust_gate_api_key_env="K",
        )
    )
    blob = json.dumps(notice) + format_trust_gate_egress_notice(notice)
    assert "secret-token" not in blob
    assert notice["destination"] == "https://api.example/[redacted]"


def test_redact_api_base_malformed_port_does_not_raise():
    clean = redact_trust_gate_api_base_for_disclosure("http://localhost:bogus/v1")
    assert clean == "http://[invalid-api-base]"
    assert "bogus" not in clean


def test_describe_redacts_url_embedded_secrets_in_destination_and_text():
    dirty = "http://operator:supersecret@127.0.0.1:8888/v1?token=alsosecret"
    notice = describe_trust_gate_egress(
        GlobalConfig(
            trust_gate_provider="openai",
            trust_gate_model="fixture-local-model",
            trust_gate_api_base=dirty,
            trust_gate_api_key_env="LOCAL_TG_KEY",
        )
    )
    assert notice["destination_kind"] == "local_endpoint"
    assert notice["destination"] == "http://127.0.0.1:8888/v1"
    blob = json.dumps(notice) + format_trust_gate_egress_notice(notice)
    assert "supersecret" not in blob
    assert "alsosecret" not in blob
    assert "operator:" not in blob
    assert "token=" not in blob


def test_adversarial_127_prefix_hostname_is_not_local_endpoint():
    notice = describe_trust_gate_egress(
        GlobalConfig(
            trust_gate_provider="openai",
            trust_gate_model="remote-looking-model",
            trust_gate_api_base="https://127.evil.example/v1",
            trust_gate_api_key_env="LOCAL_TG_KEY",
        )
    )
    assert notice["destination_kind"] == "custom_endpoint"
    assert notice["destination"] == "https://127.evil.example/v1"


@pytest.mark.parametrize(
    ("api_base", "kind"),
    [
        ("http://127.0.0.1:8888/v1", "local_endpoint"),
        ("http://localhost:8888/v1", "local_endpoint"),
        ("http://[::1]:8888/v1", "local_endpoint"),
        ("http://127.0.0.2:9/v1", "local_endpoint"),
        ("https://example.com/v1", "custom_endpoint"),
        ("https://127.0.0.1.nip.io/v1", "custom_endpoint"),
        ("https://not-localhost.example/v1", "custom_endpoint"),
    ],
)
def test_loopback_classification_uses_ip_literals_and_localhost(api_base: str, kind: str):
    notice = describe_trust_gate_egress(
        GlobalConfig(
            trust_gate_provider="openai",
            trust_gate_model="m",
            trust_gate_api_base=api_base,
            trust_gate_api_key_env="K",
        )
    )
    assert notice["destination_kind"] == kind
    assert notice["destination"] == redact_trust_gate_api_base_for_disclosure(api_base)


def test_doctor_redacts_url_secrets_from_api_base_line(tmp_path, monkeypatch, capsys):
    from fava_trails.cli import cmd_doctor

    dirty = "http://operator:supersecret@127.0.0.1:8888/v1?token=alsosecret"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_TG_KEY", "test-key-not-a-real-secret")
    data_repo = tmp_path / "data-repo"
    data_repo.mkdir()
    (data_repo / "config.yaml").write_text("trails_dir: trails\n")
    (data_repo / "trails").mkdir()
    (tmp_path / ".env").write_text("FAVA_TRAILS_SCOPE=mw/eng/test\n")
    cfg = GlobalConfig(
        trust_gate_provider="openai",
        trust_gate_model="local-model",
        trust_gate_api_base=dirty,
        trust_gate_api_key_env="LOCAL_TG_KEY",
    )

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.load_global_config", return_value=cfg):
            with patch("shutil.which", return_value="/usr/bin/jj"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="jj 0.25.0\n", stderr="")
                    rc = cmd_doctor(MagicMock())

    assert rc == 0
    out = capsys.readouterr().out
    assert "api_base=http://127.0.0.1:8888/v1" in out
    assert "supersecret" not in out
    assert "alsosecret" not in out
    assert "operator:" not in out
    assert "token=" not in out


def test_doctor_prints_egress_notice_before_promotion_use(tmp_path, monkeypatch, capsys):
    from fava_trails.cli import cmd_doctor

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-real-secret")
    data_repo = tmp_path / "data-repo"
    data_repo.mkdir()
    (data_repo / "config.yaml").write_text("trails_dir: trails\n")
    (data_repo / "trails").mkdir()
    (tmp_path / ".env").write_text("FAVA_TRAILS_SCOPE=mw/eng/test\n")

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.load_global_config", return_value=GlobalConfig()):
            with patch("shutil.which", return_value="/usr/bin/jj"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="jj 0.25.0\n", stderr="")
                    rc = cmd_doctor(MagicMock())

    assert rc == 0
    out = capsys.readouterr().out
    assert "Data egress:" in out
    assert "provider=openrouter" in out
    assert "google/gemini-2.5-flash" in out
    assert "test-key-not-a-real-secret" not in out
    assert "candidate" in out.lower()
    assert "after transmission" in out.lower()


@pytest.mark.asyncio
async def test_propose_truth_includes_egress_notice_and_discloses_before_network(
    trail_manager, tmp_fava_home, caplog
):
    reset_trust_gate_egress_disclosure_state()
    record = await trail_manager.save_thought(
        content="Synthetic candidate for egress disclosure.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."

    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(
        trust_gate="llm-oneshot",
        trust_gate_provider="openrouter",
        trust_gate_model="google/gemini-2.5-flash",
        trust_gate_timeout_secs=30,
        tool_timeout_secs=60,
    )
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    call_order: list[str] = []

    async def fake_review(**kwargs):
        call_order.append("review")
        from fava_trails.trust_gate import TrustResult

        return TrustResult(
            verdict="approve",
            reasoning="ok",
            reviewer="llm-oneshot:google/gemini-2.5-flash",
            provider="openrouter",
            model="google/gemini-2.5-flash",
        )

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test-key"}, clear=False):
        with patch("fava_trails.tools.navigation.review_thought", side_effect=fake_review):
            with caplog.at_level("INFO"):
                result = await handle_propose_truth(
                    trail_manager,
                    {"thought_id": record.thought_id},
                    prompt_cache=cache,
                )

    assert "review" in call_order
    assert "trust_gate_egress" in result
    egress = result["trust_gate_egress"]
    assert egress["provider"] == "openrouter"
    assert egress["model"] == "google/gemini-2.5-flash"
    assert egress["first_in_process"] is True
    assert "or-test-key" not in json.dumps(result)
    # Disclosure must appear in logs (before/around the review path).
    assert any("Trust Gate data egress" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_first_promotion_notice_only_once(trail_manager, tmp_fava_home):
    reset_trust_gate_egress_disclosure_state()
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(trust_gate_timeout_secs=30, tool_timeout_secs=60)
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    async def fake_review(**kwargs):
        from fava_trails.trust_gate import TrustResult

        return TrustResult(
            verdict="approve",
            reasoning="ok",
            reviewer="llm-oneshot:google/gemini-2.5-flash",
            provider="openrouter",
            model="google/gemini-2.5-flash",
        )

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test-key"}, clear=False):
        with patch("fava_trails.tools.navigation.review_thought", side_effect=fake_review):
            r1 = await trail_manager.save_thought(content="one", agent_id="a", source_type=SourceType.OBSERVATION)
            first = await handle_propose_truth(trail_manager, {"thought_id": r1.thought_id}, prompt_cache=cache)
            r2 = await trail_manager.save_thought(content="two", agent_id="a", source_type=SourceType.OBSERVATION)
            second = await handle_propose_truth(trail_manager, {"thought_id": r2.thought_id}, prompt_cache=cache)

    assert first["trust_gate_egress"]["first_in_process"] is True
    assert second["trust_gate_egress"]["first_in_process"] is False


@pytest.mark.asyncio
async def test_startup_disclosure_makes_first_promotion_not_first(trail_manager, tmp_fava_home, caplog):
    """MCP startup logs egress and marks the process flag before any promotion."""
    reset_trust_gate_egress_disclosure_state()
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(trust_gate_timeout_secs=30, tool_timeout_secs=60)
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    # Mirror server._init_server: mark then log before any propose_truth.
    first_startup = mark_trust_gate_egress_disclosed()
    assert first_startup is True
    with caplog.at_level("INFO"):
        log_trust_gate_egress_notice(
            describe_trust_gate_egress(cfg.global_config, first_in_process=first_startup)
        )
    assert any("Trust Gate data egress" in rec.message for rec in caplog.records)

    async def fake_review(**kwargs):
        from fava_trails.trust_gate import TrustResult

        return TrustResult(
            verdict="approve",
            reasoning="ok",
            reviewer="llm-oneshot:google/gemini-2.5-flash",
            provider="openrouter",
            model="google/gemini-2.5-flash",
        )

    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test-key"}, clear=False):
        with patch("fava_trails.tools.navigation.review_thought", side_effect=fake_review):
            record = await trail_manager.save_thought(
                content="after startup",
                agent_id="a",
                source_type=SourceType.OBSERVATION,
            )
            result = await handle_propose_truth(
                trail_manager,
                {"thought_id": record.thought_id},
                prompt_cache=cache,
            )

    assert result["status"] == "ok"
    assert result["trust_gate_egress"]["first_in_process"] is False


@pytest.mark.asyncio
async def test_missing_cloud_credentials_fail_closed_no_auto_approve(trail_manager, tmp_fava_home):
    reset_trust_gate_egress_disclosure_state()
    record = await trail_manager.save_thought(
        content="Must not auto-approve without credentials.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
    )
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(trust_gate_timeout_secs=30, tool_timeout_secs=60)
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENROUTER_API_KEY", None)
        review = AsyncMock()
        with patch("fava_trails.tools.navigation.review_thought", review):
            result = await handle_propose_truth(
                trail_manager,
                {"thought_id": record.thought_id},
                prompt_cache=cache,
            )

    assert result["status"] == "error"
    assert "OPENROUTER_API_KEY" in result["message"]
    review.assert_not_awaited()
    still = await trail_manager.get_thought(record.thought_id)
    assert still.frontmatter.validation_status.value == "draft"
    assert "trust_gate_egress" in result


@pytest.mark.asyncio
async def test_local_only_intercepts_outbound_and_never_hits_cloud(
    trail_manager, tmp_fava_home, openai_server
):
    """Local api_base path: only the fixture host is contacted (retries included)."""
    reset_trust_gate_egress_disclosure_state()
    base_url, handler = openai_server
    handler.response_mode = "approve"

    record = await trail_manager.save_thought(
        content="Local-only synthetic candidate.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer. Reply JSON."

    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_model="fixture-local-model",
        trust_gate_api_base=base_url,
        trust_gate_api_key_env="LOCAL_ONLY_KEY",
        trust_gate_timeout_secs=30,
        tool_timeout_secs=60,
    )
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    contacted: list[str] = []
    real_acompletion = None

    import any_llm

    real_acompletion = any_llm.acompletion

    async def tracking_acompletion(*args, **kwargs):
        api_base = kwargs.get("api_base") or (kwargs.get("client_args") or {}).get("base_url")
        provider = kwargs.get("provider")
        contacted.append(f"provider={provider};api_base={api_base}")
        # Fail closed if anything tries to use openrouter defaults without local base
        if provider == "openrouter" and not api_base:
            raise AssertionError("local-only path attempted OpenRouter cloud default")
        if api_base and "openrouter.ai" in str(api_base):
            raise AssertionError(f"local-only path contacted cloud host: {api_base}")
        return await real_acompletion(*args, **kwargs)

    with patch.dict(os.environ, {"LOCAL_ONLY_KEY": "test-local-key"}, clear=False):
        with patch("any_llm.acompletion", side_effect=tracking_acompletion):
            result = await handle_propose_truth(
                trail_manager,
                {"thought_id": record.thought_id},
                prompt_cache=cache,
            )

    assert result["status"] == "ok"
    assert result["trust_gate"]["provider"] == "openai"
    assert result["trust_gate_egress"]["destination_kind"] == "local_endpoint"
    assert result["trust_gate_egress"]["destination"] == base_url
    assert contacted, "expected at least one LLM call"
    assert all("openrouter" not in c for c in contacted)
    assert "test-local-key" not in json.dumps(result)


@pytest.mark.asyncio
async def test_local_retry_error_path_stays_on_configured_endpoint(
    trail_manager, tmp_fava_home, openai_server
):
    reset_trust_gate_egress_disclosure_state()
    base_url, handler = openai_server
    handler.response_mode = "malformed"

    record = await trail_manager.save_thought(
        content="Retry/error path must stay local.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."

    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(
        trust_gate_provider="openai",
        trust_gate_model="fixture-local-model",
        trust_gate_api_base=base_url,
        trust_gate_api_key_env="LOCAL_ONLY_KEY",
        trust_gate_timeout_secs=30,
        tool_timeout_secs=60,
    )
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    calls_seen: list[dict[str, str | None]] = []

    import any_llm

    real = any_llm.acompletion

    async def track(*args, **kwargs):
        api_base = kwargs.get("api_base") or (kwargs.get("client_args") or {}).get("base_url")
        calls_seen.append(
            {
                "provider": None if kwargs.get("provider") is None else str(kwargs.get("provider")),
                "api_base": None if api_base is None else str(api_base),
            }
        )
        return await real(*args, **kwargs)

    with patch.dict(os.environ, {"LOCAL_ONLY_KEY": "test-local-key"}, clear=False):
        with patch("any_llm.acompletion", side_effect=track):
            result = await handle_propose_truth(
                trail_manager,
                {"thought_id": record.thought_id},
                prompt_cache=cache,
            )

    assert result["status"] == "error"
    assert result["trust_gate"]["provider"] == "openai"
    assert calls_seen, "expected at least one LLM call on the retry/error path"
    assert all(c["provider"] == "openai" for c in calls_seen)
    assert all(c["api_base"] == base_url for c in calls_seen)
    still = await trail_manager.get_thought(record.thought_id)
    # Fail-closed: not approved into a permanent namespace.
    assert still.frontmatter.validation_status.value in {"draft", "error", "rejected"}
    assert still.frontmatter.validation_status.value != "approved"


@pytest.mark.asyncio
async def test_operator_human_approval_skips_llm_egress(trail_manager, tmp_fava_home, monkeypatch):
    reset_trust_gate_egress_disclosure_state()
    monkeypatch.setenv("FAVA_TRAILS_OPERATOR", "1")
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "operator-test")
    record = await trail_manager.save_thought(
        content="Operator path — no LLM transmission.",
        agent_id="operator-test",
        source_type=SourceType.DECISION,
    )
    review = AsyncMock()
    with patch("fava_trails.tools.navigation.review_thought", review):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id, "approval": "human"},
            prompt_cache=MagicMock(spec=TrustGatePromptCache),
        )
    assert result["status"] == "ok"
    review.assert_not_awaited()
    assert result["trust_gate_egress"]["destination_kind"] == "operator_human"
    assert result["trust_gate_egress"]["rejection_happens_after_transmission"] is False
    explanation = result["trust_gate_egress"]["explanation"].lower()
    assert "not sent" in explanation
    assert "llm" in explanation
    assert "operator" in explanation


def _secret_fragments() -> tuple[str, ...]:
    return (
        "supersecret",
        "path-token-xyz",
        "api_key=alsosecret",
        "alsosecret",
        "operator:supersecret",
        "https://api.example/v1?api_key=alsosecret",
        "https://operator:supersecret@api.example/v1",
        "https://api.example/v1/path-token-xyz",
    )


def _assert_secret_free(text: str) -> None:
    lowered = text.lower()
    for fragment in _secret_fragments():
        assert fragment.lower() not in lowered, f"secret leaked in {text!r}"
    assert "api.example" not in lowered
    assert "input_value" not in lowered


@pytest.mark.asyncio
async def test_connection_error_query_secret_not_in_reasoning():
    """AnyLLMError URL query tokens must not appear in TrustResult.reasoning."""
    client = MagicMock(spec=LLMClient)
    client.chat = AsyncMock(
        side_effect=AnyLLMError("request failed at https://api.example/v1?api_key=alsosecret")
    )
    client.provider = "openai"
    from fava_trails.models import ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord

    record = ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            thought_id="01TESTSECRET00000000000001",
            agent_id="test-agent",
            source_type=SourceType.OBSERVATION,
            metadata=ThoughtMetadata(),
        ),
        content="Candidate must not leak provider secrets on error.",
    )
    result = await review_thought(
        record=record,
        prompt="You are a reviewer.",
        model="fixture-local-model",
        client=client,
    )
    assert result.verdict == "error"
    assert "connection error" in result.reasoning.lower()
    assert "AnyLLMError" in result.reasoning
    _assert_secret_free(result.reasoning)
    assert "request failed at" not in result.reasoning


@pytest.mark.asyncio
async def test_provider_error_userinfo_and_path_secrets_not_in_reasoning():
    """ProviderError userinfo/path secrets must not appear in TrustResult.reasoning."""
    client = MagicMock(spec=LLMClient)
    orig = MagicMock()
    orig.status_code = 401
    client.chat = AsyncMock(
        side_effect=ProviderError(
            "auth failed at https://operator:supersecret@api.example/v1/path-token-xyz",
            original_exception=orig,
            provider_name="openai",
        )
    )
    client.provider = "openai"
    from fava_trails.models import ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord

    record = ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            thought_id="01TESTSECRET00000000000002",
            agent_id="test-agent",
            source_type=SourceType.OBSERVATION,
            metadata=ThoughtMetadata(),
        ),
        content="HTTP errors must stay secret-free.",
    )
    result = await review_thought(
        record=record,
        prompt="You are a reviewer.",
        model="fixture-local-model",
        client=client,
    )
    assert result.verdict == "error"
    assert "401" in result.reasoning
    _assert_secret_free(result.reasoning)
    assert "auth failed at" not in result.reasoning


@pytest.mark.asyncio
async def test_propose_truth_error_does_not_persist_provider_exception_secrets(
    trail_manager, tmp_fava_home
):
    """Tool JSON and durable trust_gate metadata must not store provider exception text."""
    reset_trust_gate_egress_disclosure_state()
    record = await trail_manager.save_thought(
        content="Persist path must not store API keys from exceptions.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(
        trust_gate_provider="openai",
        trust_gate_model="fixture-local-model",
        trust_gate_api_base="http://127.0.0.1:9/v1",
        trust_gate_api_key_env="LOCAL_ONLY_KEY",
        trust_gate_timeout_secs=30,
        tool_timeout_secs=60,
    )
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    async def exploding_chat(*_args, **_kwargs):
        raise AnyLLMError("request failed at https://api.example/v1?api_key=alsosecret")

    with patch.dict(os.environ, {"LOCAL_ONLY_KEY": "test-local-key"}, clear=False):
        with patch("fava_trails.llm.client.any_llm.acompletion", side_effect=exploding_chat):
            result = await handle_propose_truth(
                trail_manager,
                {"thought_id": record.thought_id},
                prompt_cache=cache,
            )

    assert result["status"] == "error"
    blob = json.dumps(result)
    _assert_secret_free(blob)
    stored = await trail_manager.get_thought(record.thought_id)
    extra = stored.frontmatter.metadata.extra.get("trust_gate") or {}
    _assert_secret_free(json.dumps(extra))
    assert stored.frontmatter.validation_status.value in {"draft", "error", "rejected"}
    assert stored.frontmatter.validation_status.value != "approved"

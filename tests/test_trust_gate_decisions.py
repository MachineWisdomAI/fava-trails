"""End-to-end Trust Gate tests for the explicit OpenRouter Decisions policy.

Uses synthetic credentials and an in-process Decisions HTTP fixture — no live
OpenRouter credential, private corpus, or GPU required. Demonstrates draft
review through ``propose_truth``: approval with durable provenance, rejection
without promotion, threshold boundaries, metadata selection, credentials,
configuration precedence, and fail-closed error paths.
"""

from __future__ import annotations

import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from pydantic import ValidationError

from fava_trails.config import ConfigStore, load_effective_global_config
from fava_trails.decisions import (
    DEFAULT_DECISIONS_API_BASE,
    DecisionsClient,
    DecisionsError,
    decisions_endpoint,
    describe_trust_gate_egress,
)
from fava_trails.models import GlobalConfig, SourceType, ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord
from fava_trails.tools.navigation import handle_propose_truth
from fava_trails.trust_gate import (
    TrustGateConfigError,
    TrustGatePromptCache,
    review_thought_decisions,
)

JEV_MODEL = "typesafe/jev-1.13"
JEV_SNAPSHOT = "typesafe/jev-1.13-20260917"
NOUL_QUESTION = "Does this thought belong in the permanent institutional record?"


@pytest.fixture
def sample_thought():
    return ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            thought_id="01TESTDECISIONS00000000000",
            agent_id="test-agent",
            source_type=SourceType.DECISION,
            confidence=0.8,
            metadata=ThoughtMetadata(
                project="fava-trails",
                branch="main",
                tags=["architecture"],
                extra={"host": "test-machine"},
            ),
        ),
        content="We should review promotions through OpenRouter Decisions.",
    )


class _DecisionsHandler(BaseHTTPRequestHandler):
    """Minimal authenticated fixture for POST /api/alpha/decisions."""

    expected_api_key: str = "test-decisions-key"
    response_mode: str = "ok"  # ok | malformed | missing_answer | wrong_type | out_of_range | nan | unauthorized | slow
    noul_value: float = 0.93
    delay_secs: float = 0.0
    last_auth: str | None = None
    last_body: dict[str, Any] | None = None
    last_path: str | None = None
    call_count: int = 0

    def do_POST(self) -> None:  # noqa: N802 — stdlib handler API
        type(self).call_count += 1
        type(self).last_path = self.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            type(self).last_body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            type(self).last_body = None

        auth = self.headers.get("Authorization", "")
        type(self).last_auth = auth

        if self.delay_secs:
            time.sleep(self.delay_secs)

        if self.response_mode == "unauthorized" or auth != f"Bearer {self.expected_api_key}":
            self._json(401, {"error": {"message": "invalid api key"}})
            return

        if self.path != "/api/alpha/decisions":
            self._json(404, {"error": {"message": f"unknown path {self.path}"}})
            return

        if self.response_mode == "malformed":
            body = b"this is not json at all {{"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        answers: dict[str, Any] = {"trust": {"type": "noul", "noul": self.noul_value}}
        if self.response_mode == "missing_answer":
            answers = {}
        elif self.response_mode == "wrong_type":
            answers = {"trust": {"type": "choice", "choice": "yes"}}
        elif self.response_mode == "out_of_range":
            answers = {"trust": {"type": "noul", "noul": 1.5}}
        elif self.response_mode == "nan":
            answers = {"trust": {"type": "noul", "noul": float("nan")}}

        payload = {
            "model": JEV_SNAPSHOT,
            "answers": answers,
            "usage": {"input_tokens": 120, "output_tokens": 20, "cost": 0.000005},
            "id": "gen-dec-fixture",
            "provider": "TypeSafe",
        }
        raw_body = json.dumps(payload, allow_nan=True).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw_body)))
        self.end_headers()
        self.wfile.write(raw_body)

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return  # silence fixture noise


@pytest.fixture
def decisions_server():
    """Start an in-process Decisions HTTP fixture; yield (api_base, handler_cls)."""
    handler = _DecisionsHandler
    handler.expected_api_key = "test-decisions-key"
    handler.response_mode = "ok"
    handler.noul_value = 0.93
    handler.delay_secs = 0.0
    handler.last_auth = None
    handler.last_body = None
    handler.last_path = None
    handler.call_count = 0

    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/api", handler
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture
def decisions_client(decisions_server):
    api_base, _ = decisions_server
    return DecisionsClient(
        api_key="test-decisions-key",
        api_base=api_base,
        provider="openrouter",
    )


# ─── Configuration contracts ──────────────────────────────────────────────────


def test_default_policy_remains_llm_oneshot():
    config = GlobalConfig()
    assert config.trust_gate == "llm-oneshot"
    assert config.trust_gate_decisions_config.trust_gate_noul_question == ""


def test_decisions_policy_requires_non_empty_question():
    with pytest.raises(ValidationError, match="trust_gate_noul_question"):
        GlobalConfig(trust_gate="decisions")


def test_decisions_threshold_must_be_finite_and_in_range():
    for bad in (1.5, -0.01, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            GlobalConfig(
                trust_gate="decisions",
                trust_gate_decisions_config={
                    "trust_gate_noul_question": NOUL_QUESTION,
                    "trust_gate_noul_threshold": bad,
                },
            )
    assert not math.isfinite(float("nan"))


def test_validate_trust_gate_runtime_covers_decisions():
    config = GlobalConfig(
        trust_gate="decisions",
        trust_gate_model=JEV_MODEL,
        trust_gate_decisions_config={
            "trust_gate_noul_question": NOUL_QUESTION,
            "trust_gate_noul_threshold": 0.9,
        },
    )
    assert config.validate_trust_gate_runtime() == "OPENROUTER_API_KEY"


def test_machine_config_may_override_decisions_block(tmp_path, monkeypatch):
    """Machine-versus-data-repo ownership: machine overlay wins for the block."""
    data_repo = tmp_path / "data"
    data_repo.mkdir()
    (data_repo / "config.yaml").write_text(
        yaml.dump(
            {
                "trails_dir": "trails",
                "trust_gate": "llm-oneshot",
                "trust_gate_decisions_config": {
                    "trust_gate_noul_question": "data repo question",
                    "trust_gate_noul_threshold": 0.6,
                },
            }
        )
    )
    machine_dir = tmp_path / "config" / "fava-trails"
    machine_dir.mkdir(parents=True)
    (machine_dir / "config.yaml").write_text(
        yaml.dump(
            {
                "trust_gate": "decisions",
                "trust_gate_model": JEV_MODEL,
                "trust_gate_decisions_config": {
                    "trust_gate_noul_question": "machine question",
                    "trust_gate_noul_threshold": 0.9,
                },
            }
        )
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    config = load_effective_global_config(data_repo)
    assert config.trust_gate == "decisions"
    assert config.trust_gate_decisions_config.trust_gate_noul_question == "machine question"
    assert config.trust_gate_decisions_config.trust_gate_noul_threshold == 0.9
    # Data-repo ownership of non-trust-gate settings is preserved.
    assert config.trails_dir == "trails"


def test_endpoint_and_egress_disclosure():
    assert decisions_endpoint(None) == "https://openrouter.ai/api/alpha/decisions"
    assert decisions_endpoint("http://127.0.0.1:9/api/") == "http://127.0.0.1:9/api/alpha/decisions"

    remote = describe_trust_gate_egress(None)
    assert "remote OpenRouter" in remote
    assert DEFAULT_DECISIONS_API_BASE in remote

    local = describe_trust_gate_egress("http://127.0.0.1:9/api")
    assert "remote OpenRouter" not in local
    assert "http://127.0.0.1:9/api/alpha/decisions" in local


# ─── Review-level behavior against the fixture ───────────────────────────────


@pytest.mark.asyncio
async def test_decisions_approve_at_threshold_boundary(decisions_client, decisions_server, sample_thought):
    """Probability exactly at the threshold approves (at-or-above semantics)."""
    _, handler = decisions_server
    handler.noul_value = 0.9

    result = await review_thought_decisions(
        record=sample_thought,
        prompt="You are the trust gate reviewer.",
        model=JEV_MODEL,
        client=decisions_client,
        question=NOUL_QUESTION,
        threshold=0.9,
        trail_name="mw/eng/fava-trails",
    )

    assert result.verdict == "approve"
    assert result.policy == "decisions"
    assert result.noul_probability == 0.9
    assert result.threshold == 0.9
    assert result.reviewer == f"decisions:{JEV_MODEL}"
    assert result.provider == "openrouter"
    assert result.model == JEV_SNAPSHOT
    assert result.approval_kind == "llm_advisory"
    assert handler.call_count == 1


@pytest.mark.asyncio
async def test_decisions_reject_below_threshold(decisions_client, decisions_server, sample_thought):
    _, handler = decisions_server
    handler.noul_value = 0.89

    result = await review_thought_decisions(
        record=sample_thought,
        prompt="You are the trust gate reviewer.",
        model=JEV_MODEL,
        client=decisions_client,
        question=NOUL_QUESTION,
        threshold=0.9,
    )

    assert result.verdict == "reject"
    assert result.noul_probability == 0.89
    assert "below" in result.reasoning
    assert handler.call_count == 1


@pytest.mark.asyncio
async def test_decisions_request_payload_and_credentials(decisions_client, decisions_server, sample_thought):
    """One typed Noul question; full prompt, body, selected metadata; no agent_id/extra."""
    _, handler = decisions_server
    handler.noul_value = 0.95
    prompt = "Full scope-resolved trust gate prompt text."

    await review_thought_decisions(
        record=sample_thought,
        prompt=prompt,
        model=JEV_MODEL,
        client=decisions_client,
        question=NOUL_QUESTION,
        threshold=0.9,
        trail_name="mw/eng/fava-trails",
    )

    assert handler.last_path == "/api/alpha/decisions"
    assert handler.last_auth == "Bearer test-decisions-key"
    body = handler.last_body
    assert body is not None
    # Exact supported model identifier — no alias rewriting.
    assert body["model"] == JEV_MODEL
    assert body["questions"] == {"trust": {"type": "noul", "instructions": NOUL_QUESTION}}
    state = body["state"]
    assert state["review_instructions"] == prompt
    assert "OpenRouter Decisions" in state["thought_under_review"]
    metadata = state["thought_metadata"]
    assert "fava-trails" in metadata
    assert "architecture" in metadata
    assert "mw/eng/fava-trails" in metadata
    # Same exclusions as llm-oneshot: agent_id and metadata.extra never sent.
    assert "test-agent" not in json.dumps(body)
    assert "test-machine" not in json.dumps(body)


@pytest.mark.asyncio
async def test_decisions_invalid_question_or_threshold_fail_before_transmission(
    decisions_client, decisions_server, sample_thought
):
    _, handler = decisions_server
    for question, threshold in (("", 0.9), ("   ", 0.9), (NOUL_QUESTION, 1.5), (NOUL_QUESTION, float("nan"))):
        with pytest.raises(TrustGateConfigError):
            await review_thought_decisions(
                record=sample_thought,
                prompt="Reviewer prompt.",
                model=JEV_MODEL,
                client=decisions_client,
                question=question,
                threshold=threshold,
            )
    assert handler.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ["malformed", "missing_answer", "wrong_type", "out_of_range", "nan", "unauthorized"],
)
async def test_decisions_error_paths_fail_closed(decisions_client, decisions_server, sample_thought, mode):
    _, handler = decisions_server
    handler.response_mode = mode

    result = await review_thought_decisions(
        record=sample_thought,
        prompt="Reviewer prompt.",
        model=JEV_MODEL,
        client=decisions_client,
        question=NOUL_QUESTION,
        threshold=0.9,
    )

    assert result.verdict == "error"
    assert result.policy == "decisions"
    assert result.threshold == 0.9
    assert "test-decisions-key" not in result.reasoning
    # Fail closed without contacting another reviewer and without retrying.
    assert handler.call_count == 1


@pytest.mark.asyncio
async def test_decisions_connection_failure_fail_closed(sample_thought):
    client = DecisionsClient(
        api_key="test-decisions-key",
        api_base="http://127.0.0.1:1/api",  # nothing listening
        provider="openrouter",
    )
    result = await review_thought_decisions(
        record=sample_thought,
        prompt="Reviewer prompt.",
        model=JEV_MODEL,
        client=client,
        question=NOUL_QUESTION,
        threshold=0.9,
    )
    assert result.verdict == "error"
    assert result.provider == "openrouter"
    assert "llm-oneshot" not in result.reasoning


@pytest.mark.asyncio
async def test_decisions_client_requires_credential():
    with pytest.raises(DecisionsError, match="credential"):
        DecisionsClient(api_base="http://127.0.0.1:1/api")


# ─── End-to-end promotion through propose_truth ──────────────────────────────


def _decisions_trust_gate_config(
    tmp_fava_home: Path,
    *,
    api_base: str,
    threshold: float = 0.9,
    timeout_secs: int = 30,
    tool_timeout_secs: int = 60,
) -> ConfigStore:
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(
        trust_gate="decisions",
        trust_gate_provider="openrouter",
        trust_gate_model=JEV_MODEL,
        trust_gate_api_base=api_base,
        trust_gate_api_key_env="DECISIONS_API_KEY",
        trust_gate_timeout_secs=timeout_secs,
        tool_timeout_secs=tool_timeout_secs,
        trust_gate_decisions_config={
            "trust_gate_noul_question": NOUL_QUESTION,
            "trust_gate_noul_threshold": threshold,
        },
    )
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)
    return cfg


@pytest.mark.asyncio
async def test_propose_truth_decisions_approve_persists_provenance(
    trail_manager, tmp_fava_home, decisions_server
):
    """Draft review approves through the fixture and persists durable provenance."""
    api_base, handler = decisions_server
    handler.response_mode = "ok"
    handler.noul_value = 0.93

    record = await trail_manager.save_thought(
        content="Decisions review should approve this observation.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base)
    with patch.dict("os.environ", {"DECISIONS_API_KEY": "test-decisions-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "ok"
    assert result["trust_gate"]["verdict"] == "approve"
    assert result["trust_gate"]["policy"] == "decisions"
    assert result["trust_gate"]["reviewer"] == f"decisions:{JEV_MODEL}"
    assert result["trust_gate"]["provider"] == "openrouter"
    assert result["trust_gate"]["model"] == JEV_SNAPSHOT
    assert result["trust_gate"]["noul_probability"] == 0.93
    assert result["trust_gate"]["threshold"] == 0.9
    assert "test-decisions-key" not in json.dumps(result)

    promoted = await trail_manager.get_thought(record.thought_id)
    meta = promoted.frontmatter.metadata.extra["trust_gate"]
    assert meta["policy"] == "decisions"
    assert meta["provider"] == "openrouter"
    assert meta["model"] == JEV_SNAPSHOT
    assert meta["noul_probability"] == 0.93
    assert meta["threshold"] == 0.9
    assert meta["kind"] == "llm_advisory"
    assert meta["reviewed_at"]
    assert "no reasoning" in meta["reasoning"].lower()
    assert "api_key" not in meta
    approval = promoted.frontmatter.metadata.extra["approval"]
    assert approval["kind"] == "llm_advisory"
    assert approval["actor"] == f"decisions:{JEV_MODEL}"


@pytest.mark.asyncio
async def test_propose_truth_decisions_reject_does_not_promote(
    trail_manager, tmp_fava_home, decisions_server
):
    api_base, handler = decisions_server
    handler.response_mode = "ok"
    handler.noul_value = 0.2

    record = await trail_manager.save_thought(
        content="Decisions review should reject this thought.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base)
    with patch.dict("os.environ", {"DECISIONS_API_KEY": "test-decisions-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "rejected"
    assert result["trust_gate"]["verdict"] == "reject"
    assert result["trust_gate"]["noul_probability"] == 0.2

    reviewed = await trail_manager.get_thought(record.thought_id)
    assert reviewed.frontmatter.validation_status.value == "rejected"
    assert "approval" not in reviewed.frontmatter.metadata.extra


@pytest.mark.asyncio
async def test_propose_truth_decisions_error_fails_closed(
    trail_manager, tmp_fava_home, decisions_server
):
    api_base, handler = decisions_server
    handler.response_mode = "missing_answer"

    record = await trail_manager.save_thought(
        content="Decisions review cannot parse this response.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base)
    with patch.dict("os.environ", {"DECISIONS_API_KEY": "test-decisions-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "error"
    assert handler.call_count == 1
    reviewed = await trail_manager.get_thought(record.thought_id)
    assert reviewed.frontmatter.validation_status.value == "error"
    assert "approval" not in reviewed.frontmatter.metadata.extra


@pytest.mark.asyncio
async def test_propose_truth_decisions_timeout(trail_manager, tmp_fava_home, decisions_server):
    api_base, handler = decisions_server
    handler.response_mode = "ok"
    handler.delay_secs = 2.0

    record = await trail_manager.save_thought(
        content="A decision reviewed by a slow Decisions endpoint.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base, timeout_secs=1, tool_timeout_secs=30)
    with patch.dict("os.environ", {"DECISIONS_API_KEY": "test-decisions-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "error"
    assert "timed out" in result["message"].lower()


@pytest.mark.asyncio
async def test_propose_truth_decisions_missing_key_fails_closed(
    trail_manager, tmp_fava_home, decisions_server
):
    api_base, handler = decisions_server

    record = await trail_manager.save_thought(
        content="Missing key should fail closed.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base)
    import os

    os.environ.pop("DECISIONS_API_KEY", None)
    result = await handle_propose_truth(
        trail_manager,
        {"thought_id": record.thought_id},
        prompt_cache=cache,
    )

    assert result["status"] == "error"
    assert "DECISIONS_API_KEY" in result["message"]
    assert handler.call_count == 0


# ─── Doctor diagnostics ───────────────────────────────────────────────────────


def _doctor_run(tmp_path, monkeypatch, capsys, *, cfg_overrides: dict[str, Any]):
    from argparse import Namespace

    from fava_trails.cli import cmd_doctor

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    data_repo = tmp_path / "data-repo"
    data_repo.mkdir()
    (data_repo / "config.yaml").write_text("trails_dir: trails\n")
    (data_repo / "trails").mkdir()
    (tmp_path / ".env").write_text("FAVA_TRAILS_SCOPE=mw/eng/test\n")

    jj_mock = MagicMock()
    jj_mock.returncode = 0
    jj_mock.stdout = ""
    jj_mock.stderr = ""

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.load_global_config") as mock_config:
            cfg = mock_config.return_value
            cfg.validate_trust_gate_runtime.return_value = "OPENROUTER_API_KEY"
            cfg.resolve_trust_gate_api_key_env.return_value = "OPENROUTER_API_KEY"
            cfg.trust_gate_provider = "openrouter"
            cfg.trust_gate_model = JEV_MODEL
            cfg.trust_gate_api_base = None
            cfg.trust_gate_api_key_file = None
            cfg.trust_gate = "decisions"
            for name, value in cfg_overrides.items():
                setattr(cfg, name, value)
            with patch("shutil.which", return_value="/usr/bin/jj"):
                with patch("subprocess.run", return_value=jj_mock) as mock_run:
                    mock_run.return_value.stdout = "jj 0.25.0\n"
                    rc = cmd_doctor(Namespace())
    return rc, capsys.readouterr().out


def test_doctor_decisions_diagnostics_are_secret_free(tmp_path, monkeypatch, capsys):
    rc, out = _doctor_run(tmp_path, monkeypatch, capsys, cfg_overrides={})

    assert rc == 0
    assert "policy=decisions" in out
    assert f"model={JEV_MODEL}" in out
    assert "https://openrouter.ai/api/alpha/decisions" in out
    assert "remote_provider" in out
    # Structured egress disclosure enumerates the transmitted data categories.
    assert "full scope-resolved Trust Gate prompt" in out
    assert "full candidate thought content" in out
    assert "thought_id, source_type, confidence, validation_status" in out
    # Secret-free: neither the key value nor a credential path is disclosed.
    assert "test-key" not in out


def test_doctor_decisions_custom_api_base_discloses_configured_destination(
    tmp_path, monkeypatch, capsys
):
    rc, out = _doctor_run(
        tmp_path,
        monkeypatch,
        capsys,
        cfg_overrides={"trust_gate_api_base": "http://127.0.0.1:9/api"},
    )

    assert rc == 0
    # Shipped redaction policy: operator-configured path segments are redacted;
    # only the well-known constant Decisions path suffix is disclosed.
    assert "http://127.0.0.1:9/[redacted]/alpha/decisions" in out
    assert "http://127.0.0.1:9/api/alpha/decisions" not in out
    assert "local_endpoint" in out
    assert "remote_provider" not in out


# ─── Structured egress disclosure for the decisions policy ───────────────────
#
# Regression coverage for the current-main structured Trust Gate egress path:
# the decisions policy reuses the trust_gate_egress object, first-in-process
# disclosure, and secret-free destination redaction shipped for llm-oneshot,
# and its disclosure enumerates the full scope-resolved Trust Gate prompt, the
# full candidate body, and the exact selected metadata fields sent.

from fava_trails.trust_gate import (  # noqa: E402
    describe_trust_gate_egress as describe_structured_egress,
    format_trust_gate_egress_notice,
    reset_trust_gate_egress_disclosure_state,
)


def _decisions_global_config(**overrides: Any) -> GlobalConfig:
    base: dict[str, Any] = {
        "trust_gate": "decisions",
        "trust_gate_provider": "openrouter",
        "trust_gate_model": JEV_MODEL,
        "trust_gate_api_key_env": "DECISIONS_API_KEY",
        "trust_gate_decisions_config": {
            "trust_gate_noul_question": NOUL_QUESTION,
            "trust_gate_noul_threshold": 0.9,
        },
    }
    base.update(overrides)
    return GlobalConfig(**base)


def test_decisions_egress_notice_enumerates_prompt_body_metadata_and_question():
    notice = describe_structured_egress(_decisions_global_config())

    assert notice["policy"] == "decisions"
    assert notice["provider"] == "openrouter"
    assert notice["model"] == JEV_MODEL
    assert notice["destination"] == (
        "openrouter Decisions API (https://openrouter.ai/api/alpha/decisions)"
    )
    assert notice["destination_kind"] == "remote_provider"
    assert notice["cloud_fallback"] is False
    assert notice["rejection_happens_after_transmission"] is True

    data_sent = "\n".join(notice["data_sent"])
    assert "full scope-resolved Trust Gate prompt" in data_sent
    assert "full candidate thought content" in data_sent
    assert "thought_id, source_type, confidence, validation_status" in data_sent
    assert "trail_name, parent_id, project, branch, tags" in data_sent
    assert "Noul question" in data_sent
    # The summary names the exclusions explicitly.
    assert "agent_id and metadata.extra are not sent" in notice["data_sent_summary"]

    # Secret-free: credential source is a name only.
    assert notice["credential_source"] == "DECISIONS_API_KEY"
    formatted = format_trust_gate_egress_notice(notice)
    assert "Trust Gate data egress" in formatted
    assert "decisions" in formatted


def test_decisions_egress_notice_policy_override_wins_over_global_default():
    """A trail-level 'decisions' override is disclosed even when the global config defaults."""
    notice = describe_structured_egress(GlobalConfig(), policy="decisions")
    assert notice["policy"] == "decisions"
    assert "Decisions API" in notice["destination"]


def test_decisions_egress_notice_redacts_custom_api_base_secrets():
    secret_base = "https://operator:hunter2@gw.example.com:8443/gateway-token"
    notice = describe_structured_egress(
        _decisions_global_config(trust_gate_api_base=secret_base)
    )

    assert notice["destination_kind"] == "custom_endpoint"
    assert notice["destination"].endswith("/alpha/decisions")
    assert "hunter2" not in notice["destination"]
    assert "operator" not in notice["destination"]
    assert "gateway-token" not in notice["destination"]
    assert "/[redacted]" in notice["destination"]
    serialized = json.dumps(notice)
    assert "hunter2" not in serialized
    assert "gateway-token" not in serialized


def test_decisions_egress_notice_marks_loopback_local_endpoint():
    notice = describe_structured_egress(
        _decisions_global_config(trust_gate_api_base="http://127.0.0.1:8080")
    )
    assert notice["destination_kind"] == "local_endpoint"
    assert notice["destination"] == "http://127.0.0.1:8080/alpha/decisions"


def test_decisions_egress_notice_carries_first_in_process_flag():
    notice = describe_structured_egress(_decisions_global_config(), first_in_process=True)
    assert notice["first_in_process"] is True
    notice_without = describe_structured_egress(_decisions_global_config())
    assert "first_in_process" not in notice_without


# ─── Secret-bearing unexpected exceptions cannot escape (review finding 2) ───


@pytest.mark.asyncio
async def test_review_thought_decisions_unexpected_exception_secret_cannot_escape(
    sample_thought,
):
    """The catch-all path sanitizes through the provider-exception boundary."""
    secret = "sk-or-v1-9f3a2c1e7b4d8560abcdef1234567890"
    client = MagicMock(spec=DecisionsClient)
    client.provider = "openrouter"
    client.ask_noul = AsyncMock(
        side_effect=RuntimeError(
            f"request to https://user:{secret}@openrouter.ai/api/alpha/decisions"
            f"?api_key={secret} failed"
        )
    )

    result = await review_thought_decisions(
        record=sample_thought,
        prompt="You are the trust gate reviewer.",
        model=JEV_MODEL,
        client=client,
        question=NOUL_QUESTION,
        threshold=0.9,
    )

    assert result.verdict == "error"
    assert result.policy == "decisions"
    assert result.threshold == 0.9
    # The sanitized diagnostic keeps the exception type but never its text.
    assert "RuntimeError" in result.reasoning
    assert secret not in result.reasoning
    assert "api_key" not in result.reasoning
    assert "user:" not in result.reasoning


@pytest.mark.asyncio
async def test_propose_truth_decisions_unexpected_exception_provenance_is_secret_free(
    trail_manager, tmp_fava_home, decisions_server
):
    """Durable provenance from the catch-all path carries no exception secrets."""
    api_base, handler = decisions_server
    secret = "sk-or-v1-deadbeefcafe4242feedface12345678"

    record = await trail_manager.save_thought(
        content="A thought whose review hits an unexpected provider failure.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base)
    boom = RuntimeError(
        f"connection reset by https://proxy:{secret}@gw.internal:9443"
    )
    with patch.dict("os.environ", {"DECISIONS_API_KEY": "test-decisions-key"}, clear=False):
        with patch(
            "fava_trails.decisions.DecisionsClient.ask_noul",
            new=AsyncMock(side_effect=boom),
        ):
            result = await handle_propose_truth(
                trail_manager,
                {"thought_id": record.thought_id},
                prompt_cache=cache,
            )

    assert result["status"] == "error"
    assert secret not in json.dumps(result)

    reviewed = await trail_manager.get_thought(record.thought_id)
    meta = reviewed.frontmatter.metadata.extra["trust_gate"]
    assert meta["verdict"] == "error"
    assert meta["policy"] == "decisions"
    assert "RuntimeError" in meta["reasoning"]
    assert secret not in meta["reasoning"]
    persisted_blob = json.dumps(reviewed.model_dump(mode="json"))
    assert secret not in persisted_blob
    assert handler.call_count <= 1


# ─── decisions egress object across success, credential failure, timeout ─────


@pytest.mark.asyncio
async def test_propose_truth_decisions_success_includes_structured_egress_notice(
    trail_manager, tmp_fava_home, decisions_server
):
    api_base, handler = decisions_server
    handler.response_mode = "ok"
    handler.noul_value = 0.95

    reset_trust_gate_egress_disclosure_state()
    record = await trail_manager.save_thought(
        content="Egress disclosure should ride with a successful decisions review.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base)
    with patch.dict("os.environ", {"DECISIONS_API_KEY": "test-decisions-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "ok"
    egress = result["trust_gate_egress"]
    assert egress["policy"] == "decisions"
    assert egress["destination_kind"] == "local_endpoint"
    assert egress["destination"].endswith("/alpha/decisions")
    assert egress["first_in_process"] is True
    data_sent = "\n".join(egress["data_sent"])
    assert "full scope-resolved Trust Gate prompt" in data_sent
    assert "full candidate thought content" in data_sent
    assert "thought_id, source_type, confidence, validation_status" in data_sent
    assert "test-decisions-key" not in json.dumps(result)


@pytest.mark.asyncio
async def test_propose_truth_decisions_credential_failure_includes_egress_notice(
    trail_manager, tmp_fava_home, decisions_server
):
    api_base, handler = decisions_server

    reset_trust_gate_egress_disclosure_state()
    record = await trail_manager.save_thought(
        content="Credential failure must still disclose the egress choice.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base)
    import os

    os.environ.pop("DECISIONS_API_KEY", None)
    result = await handle_propose_truth(
        trail_manager,
        {"thought_id": record.thought_id},
        prompt_cache=cache,
    )

    assert result["status"] == "error"
    assert "DECISIONS_API_KEY" in result["message"]
    egress = result["trust_gate_egress"]
    assert egress["policy"] == "decisions"
    assert egress["first_in_process"] is True
    assert handler.call_count == 0


@pytest.mark.asyncio
async def test_propose_truth_decisions_timeout_includes_egress_notice(
    trail_manager, tmp_fava_home, decisions_server
):
    api_base, handler = decisions_server
    handler.response_mode = "ok"
    handler.delay_secs = 2.0

    reset_trust_gate_egress_disclosure_state()
    record = await trail_manager.save_thought(
        content="A timeout must still carry the egress disclosure.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are the trust gate reviewer."

    _decisions_trust_gate_config(tmp_fava_home, api_base=api_base, timeout_secs=1, tool_timeout_secs=30)
    with patch.dict("os.environ", {"DECISIONS_API_KEY": "test-decisions-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "error"
    assert "timed out" in result["message"].lower()
    egress = result["trust_gate_egress"]
    assert egress["policy"] == "decisions"
    assert egress["destination"].endswith("/alpha/decisions")

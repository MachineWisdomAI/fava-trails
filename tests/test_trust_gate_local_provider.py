"""End-to-end Trust Gate tests against a fixture OpenAI-compatible HTTP server.

Uses synthetic credentials and an in-process HTTP server — no real OpenRouter
account, Unsloth install, model download, or GPU required.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fava_trails.config import ConfigStore
from fava_trails.llm.client import LLMClient, LLMError
from fava_trails.models import GlobalConfig, SourceType, ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord
from fava_trails.tools.navigation import handle_propose_truth
from fava_trails.trust_gate import TrustGatePromptCache, review_thought


@pytest.fixture
def sample_thought():
    return ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            thought_id="01TESTLOCAL000000000000000",
            agent_id="test-agent",
            source_type=SourceType.DECISION,
            confidence=0.8,
            metadata=ThoughtMetadata(
                project="fava-trail",
                branch="main",
                tags=["architecture"],
                extra={"host": "test-machine"},
            ),
        ),
        content="We should use JJ for version control of thoughts.",
    )


class _OpenAICompatibleHandler(BaseHTTPRequestHandler):
    """Minimal authenticated OpenAI-compatible /v1/chat/completions fixture."""

    # Class-level knobs mutated per test via the fixture.
    expected_api_key: str = "test-local-key"
    response_mode: str = "approve"  # approve | reject | malformed | slow | unauthorized
    delay_secs: float = 0.0
    last_auth: str | None = None
    last_body: dict[str, Any] | None = None
    call_count: int = 0

    def do_POST(self) -> None:  # noqa: N802 — stdlib handler API
        type(self).call_count += 1
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
            self._json(401, {"error": {"message": "invalid api key", "type": "auth_error"}})
            return

        if self.path not in ("/v1/chat/completions", "/chat/completions"):
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

        if self.response_mode == "reject":
            content = json.dumps({"verdict": "reject", "reasoning": "Not suitable for promotion.", "confidence": 0.8})
        else:
            content = json.dumps({"verdict": "approve", "reasoning": "Solid observation.", "confidence": 0.91})

        payload = {
            "id": "chatcmpl-fixture",
            "object": "chat.completion",
            "created": 1,
            "model": "fixture-local-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        }
        self._json(200, payload)

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
def openai_server():
    """Start an in-process OpenAI-compatible HTTP server; yield (base_url, handler_cls)."""
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


@pytest.fixture
def local_client(openai_server):
    base_url, _ = openai_server
    return LLMClient(
        api_key="test-local-key",
        provider="openai",
        api_base=base_url,
    )


@pytest.mark.asyncio
async def test_local_client_authenticated_approve(local_client, openai_server, sample_thought):
    """Authenticated local endpoint produces approve TrustResult with provenance."""
    _, handler = openai_server
    handler.response_mode = "approve"

    result = await review_thought(
        record=sample_thought,
        prompt="You are a reviewer. Reply with JSON verdict.",
        model="fixture-local-model",
        client=local_client,
    )

    assert result.verdict == "approve"
    assert "Solid observation" in result.reasoning
    assert result.provider == "openai"
    assert result.model == "fixture-local-model"
    assert result.reviewer == "llm-oneshot:fixture-local-model"
    assert handler.last_auth == "Bearer test-local-key"
    assert "test-local-key" not in result.reasoning
    assert "test-local-key" not in (result.provider or "")


@pytest.mark.asyncio
async def test_local_client_authenticated_reject(local_client, openai_server, sample_thought):
    _, handler = openai_server
    handler.response_mode = "reject"

    result = await review_thought(
        record=sample_thought,
        prompt="You are a reviewer.",
        model="fixture-local-model",
        client=local_client,
    )

    assert result.verdict == "reject"
    assert "Not suitable" in result.reasoning
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_local_client_missing_key_raises():
    client = LLMClient(api_key=None, provider="openai", api_base="http://127.0.0.1:1/v1")
    with pytest.raises(LLMError, match="API key required"):
        await client.chat(messages=[{"role": "user", "content": "hi"}], model="x")


@pytest.mark.asyncio
async def test_local_client_bad_endpoint_fail_closed(sample_thought):
    """Unreachable endpoint stays fail-closed — no OpenRouter fallback."""
    client = LLMClient(
        api_key="test-local-key",
        provider="openai",
        api_base="http://127.0.0.1:1/v1",  # nothing listening
    )
    result = await review_thought(
        record=sample_thought,
        prompt="You are a reviewer.",
        model="fixture-local-model",
        client=client,
    )
    assert result.verdict == "error"
    assert result.provider == "openai"
    # Must not silently switch providers
    assert "openrouter" not in result.reasoning.lower()


@pytest.mark.asyncio
async def test_local_client_malformed_json_fail_closed(local_client, openai_server, sample_thought):
    _, handler = openai_server
    handler.response_mode = "malformed"

    result = await review_thought(
        record=sample_thought,
        prompt="You are a reviewer.",
        model="fixture-local-model",
        client=local_client,
    )
    assert result.verdict == "error"
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_local_client_auth_failure_fail_closed(local_client, openai_server, sample_thought):
    _, handler = openai_server
    handler.expected_api_key = "different-key"

    result = await review_thought(
        record=sample_thought,
        prompt="You are a reviewer.",
        model="fixture-local-model",
        client=local_client,
    )
    assert result.verdict == "error"
    assert result.provider == "openai"


def _local_trust_gate_config(
    tmp_fava_home: Path,
    *,
    api_base: str,
    model: str = "fixture-local-model",
    key_env: str = "UNSLOTH_API_KEY",
    timeout_secs: int = 30,
    tool_timeout_secs: int = 60,
) -> ConfigStore:
    """Shared ConfigStore scaffold for local OpenAI-compatible Trust Gate tests."""
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_model=model,
        trust_gate_api_base=api_base,
        trust_gate_api_key_env=key_env,
        trust_gate_timeout_secs=timeout_secs,
        tool_timeout_secs=tool_timeout_secs,
    )
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)
    return cfg


@pytest.mark.asyncio
async def test_local_client_timeout_via_propose_truth(trail_manager, tmp_fava_home, openai_server):
    """handle_propose_truth times out against a slow local endpoint (fail-closed)."""
    base_url, handler = openai_server
    handler.response_mode = "approve"
    handler.delay_secs = 2.0

    record = await trail_manager.save_thought(
        content="A decision reviewed by a slow local model.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer. Reply JSON."

    _local_trust_gate_config(tmp_fava_home, api_base=base_url, timeout_secs=1, tool_timeout_secs=30)

    with patch.dict("os.environ", {"UNSLOTH_API_KEY": "test-local-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "error"
    assert "timed out" in result["message"].lower()


@pytest.mark.asyncio
async def test_propose_truth_local_approve_and_provenance(trail_manager, tmp_fava_home, openai_server):
    """Full propose_truth approve path through authenticated local OpenAI-compatible endpoint."""
    base_url, handler = openai_server
    handler.response_mode = "approve"

    record = await trail_manager.save_thought(
        content="Local review should approve this observation.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer. Reply with JSON verdict."

    _local_trust_gate_config(tmp_fava_home, api_base=base_url)

    with patch.dict("os.environ", {"UNSLOTH_API_KEY": "test-local-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "ok"
    assert result["trust_gate"]["verdict"] == "approve"
    assert result["trust_gate"]["provider"] == "openai"
    assert result["trust_gate"]["model"] == "fixture-local-model"
    assert result["trust_gate"]["reviewer"] == "llm-oneshot:fixture-local-model"
    assert "test-local-key" not in json.dumps(result)

    # Provenance persisted on the thought
    promoted = await trail_manager.get_thought(record.thought_id)
    meta = promoted.frontmatter.metadata.extra["trust_gate"]
    assert meta["provider"] == "openai"
    assert meta["model"] == "fixture-local-model"
    assert "api_key" not in meta


@pytest.mark.asyncio
async def test_propose_truth_local_reject(trail_manager, tmp_fava_home, openai_server):
    base_url, handler = openai_server
    handler.response_mode = "reject"

    record = await trail_manager.save_thought(
        content="Should be rejected by local reviewer.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."

    _local_trust_gate_config(tmp_fava_home, api_base=base_url)

    with patch.dict("os.environ", {"UNSLOTH_API_KEY": "test-local-key"}, clear=False):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "rejected"
    assert result["trust_gate"]["verdict"] == "reject"
    assert result["trust_gate"]["provider"] == "openai"


@pytest.mark.asyncio
async def test_propose_truth_uses_key_file_and_provider_extra_body(
    trail_manager,
    tmp_fava_home,
    tmp_path,
    openai_server,
):
    """The production promotion path reads the file and disables Qwen thinking."""
    base_url, handler = openai_server
    key_file = tmp_path / "runtime-api-key"
    key_file.write_text("test-local-key\n")
    key_file.chmod(0o600)
    record = await trail_manager.save_thought(
        content="A concrete local-provider observation.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."
    cfg = ConfigStore.__new__(ConfigStore)
    cfg.global_config = GlobalConfig(
        trust_gate="llm-oneshot",
        trust_gate_provider="openai",
        trust_gate_model="fixture-local-model",
        trust_gate_api_base=base_url,
        trust_gate_api_key_file=str(key_file),
        trust_gate_extra_body={"enable_thinking": False},
        trust_gate_timeout_secs=30,
        tool_timeout_secs=60,
    )
    cfg.data_repo_root = tmp_fava_home
    cfg.trails_dir = tmp_fava_home / "trails"
    ConfigStore.override(cfg)

    result = await handle_propose_truth(
        trail_manager,
        {"thought_id": record.thought_id},
        prompt_cache=cache,
    )

    assert result["status"] == "ok"
    assert handler.last_auth == "Bearer test-local-key"
    assert handler.last_body is not None
    assert handler.last_body["enable_thinking"] is False
    assert str(key_file) not in json.dumps(result)


@pytest.mark.asyncio
async def test_propose_truth_missing_configured_key(trail_manager, tmp_fava_home, openai_server):
    base_url, _ = openai_server

    record = await trail_manager.save_thought(
        content="Missing key should fail closed.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )

    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."

    _local_trust_gate_config(tmp_fava_home, api_base=base_url)

    with patch.dict("os.environ", {}, clear=False):
        # Ensure the configured key is absent
        import os

        os.environ.pop("UNSLOTH_API_KEY", None)
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": record.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "error"
    assert "UNSLOTH_API_KEY" in result["message"]


@pytest.mark.asyncio
async def test_local_client_forwards_registry_colliding_model_id(local_client, openai_server):
    """End-to-end: bare gpt-4.1-mini is sent to the local server, not openai/gpt-4.1-mini."""
    _, handler = openai_server
    handler.response_mode = "approve"

    await local_client.chat(
        messages=[{"role": "user", "content": "ping"}],
        model="gpt-4.1-mini",
    )

    assert handler.last_body is not None
    assert handler.last_body.get("model") == "gpt-4.1-mini"


@pytest.mark.asyncio
async def test_openrouter_backward_compat_default_client_kwargs():
    """Default LLMClient still targets OpenRouter with no api_base."""
    client = LLMClient(api_key="or-key")
    assert client.provider == "openrouter"
    assert client.api_base is None


def test_config_yaml_roundtrip_omitted_provider_fields(tmp_path: Path, monkeypatch):
    """Existing configs with only openrouter_api_key_env load as OpenRouter defaults."""
    import yaml

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        yaml.dump(
            {
                "trails_dir": "trails",
                "trust_gate_model": "google/gemini-2.5-flash",
                "openrouter_api_key_env": "OPENROUTER_API_KEY",
            }
        )
    )
    monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(home))
    monkeypatch.delenv("FAVA_TRAILS_DIR", raising=False)
    ConfigStore.reset()
    store = ConfigStore.get()
    assert store.global_config.trust_gate_provider == "openrouter"
    assert store.global_config.trust_gate_api_base is None
    assert store.global_config.resolve_trust_gate_api_key_env() == "OPENROUTER_API_KEY"

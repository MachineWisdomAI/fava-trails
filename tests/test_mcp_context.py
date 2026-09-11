"""MCP context surface, measurement, and compact vs full workflow."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from fava_trails.mcp_context import (
    COMMON_WORKFLOW_TOOLS,
    COMPACT_SESSION_INIT_BUDGET_RATIO,
    DEFAULT_TOKENIZER,
    MCP_SURFACE_ENV,
    measure_mcp_context,
    resolve_mcp_surface,
    serialize_initialize_instructions,
    serialize_tools_list,
    session_init_payload,
)
from fava_trails.server import TOOL_DEFINITIONS, handle_list_tools

COMMON_WORKFLOW = ("recall", "save_thought", "propose_truth", "get_usage_guide", "list_scopes")


def test_resolve_mcp_surface_defaults_to_full(monkeypatch):
    monkeypatch.delenv(MCP_SURFACE_ENV, raising=False)
    assert resolve_mcp_surface() == "full"


def test_resolve_mcp_surface_accepts_compact(monkeypatch):
    monkeypatch.setenv(MCP_SURFACE_ENV, "compact")
    assert resolve_mcp_surface() == "compact"


def test_resolve_mcp_surface_rejects_unknown(monkeypatch):
    monkeypatch.setenv(MCP_SURFACE_ENV, "tiny")
    with pytest.raises(ValueError, match="FAVA_TRAILS_MCP_SURFACE"):
        resolve_mcp_surface()


def test_resolve_mcp_surface_default_on_error_stays_full(monkeypatch, caplog):
    monkeypatch.setenv(MCP_SURFACE_ENV, "tiny")
    assert resolve_mcp_surface(default_on_error=True) == "full"
    assert "using full" in caplog.text


def test_full_instructions_keep_existing_protocol_hooks():
    text = serialize_initialize_instructions("full")
    assert "Scope Discovery" in text
    assert "FAVA_TRAILS_SCOPE" in text
    assert "propose_truth" in text
    assert "get_usage_guide" in text
    assert "Governed Visibility" in text


def test_compact_instructions_are_shorter_and_on_demand():
    full = serialize_initialize_instructions("full")
    compact = serialize_initialize_instructions("compact")
    assert len(compact) < len(full)
    assert "get_usage_guide" in compact
    assert "recall" in compact
    assert "save_thought" in compact
    assert "propose_truth" in compact
    assert "FAVA_TRAILS_SCOPE" in compact
    assert "does not enforce" in compact.lower() or "prompt" in compact.lower()


def test_compact_instructions_keep_scope_hint_fallback_before_ask():
    compact = serialize_initialize_instructions("compact")
    assert "FAVA_TRAILS_SCOPE_HINT" in compact
    scope_idx = compact.find("`FAVA_TRAILS_SCOPE`")
    yaml_idx = compact.find(".fava-trails.yaml")
    hint_idx = compact.find("FAVA_TRAILS_SCOPE_HINT")
    ask_idx = compact.lower().rfind("ask")
    assert 0 <= scope_idx < yaml_idx < hint_idx < ask_idx


def test_compact_instructions_do_not_claim_instruction_sharing():
    compact = serialize_initialize_instructions("compact")
    lowered = compact.lower()
    assert "cross-session" not in lowered or "not" in lowered
    assert "merely because" not in lowered


@pytest.mark.asyncio
async def test_compact_list_tools_keeps_all_tools_and_schemas():
    full_tools = await handle_list_tools(surface="full")
    compact_tools = await handle_list_tools(surface="compact")
    full_by_name = {tool.name: tool for tool in full_tools}
    compact_by_name = {tool.name: tool for tool in compact_tools}
    assert set(full_by_name) == set(compact_by_name) == {td["name"] for td in TOOL_DEFINITIONS}
    assert len(compact_tools) == 17
    for name in COMMON_WORKFLOW:
        assert name in compact_by_name
    for name, tool in compact_by_name.items():
        assert tool.input_schema == full_by_name[name].input_schema
        assert tool.output_schema is None
        assert full_by_name[name].output_schema is not None
        assert len(tool.description) <= len(full_by_name[name].description)


@pytest.mark.asyncio
async def test_compact_tool_descriptions_drop_duplicated_workflow_prose():
    compact_tools = await handle_list_tools(surface="compact")
    by_name = {tool.name: tool.description for tool in compact_tools}
    assert "WARNING" not in by_name["recall"]
    assert "session start" not in by_name["recall"].lower()
    assert "FAVA_TRAILS_SCOPE" not in by_name["recall"]
    assert "invisible" not in by_name["propose_truth"]
    assert "get_usage_guide" in by_name["get_usage_guide"]


def test_measure_mcp_context_records_method_not_a_universal_figure():
    report = measure_mcp_context(surface="full")
    assert report["surface"] == "full"
    assert report["tokenizer"]["name"] == DEFAULT_TOKENIZER
    assert report["lazy_loading"] is False
    assert report["tool_count"] == 17
    assert set(report["enabled_tools"]) == {td["name"] for td in TOOL_DEFINITIONS}
    assert report["serialization"]["mcp_sdk_version"]
    assert report["recurrence"]["instructions"] == "once per initialize"
    assert "tools/list" in report["recurrence"]["tools_list"]
    assert report["instructions"]["chars"] > 0
    assert report["tools_list"]["chars"] > 0
    assert report["session_init"]["chars"] == (
        report["instructions"]["chars"] + report["tools_list"]["chars"]
    )
    assert "universal" not in json.dumps(report).lower() or report["tokenizer"]["not_universal"] is True
    assert report["tokenizer"]["not_universal"] is True


def test_compact_session_init_meets_budget_from_full_baseline():
    full = measure_mcp_context(surface="full")
    compact = measure_mcp_context(surface="compact")
    full_tokens = full["session_init"]["tokens"]
    compact_tokens = compact["session_init"]["tokens"]
    ratio = compact_tokens / full_tokens
    assert compact_tokens < full_tokens
    assert ratio <= COMPACT_SESSION_INIT_BUDGET_RATIO
    assert COMMON_WORKFLOW_TOOLS <= set(compact["enabled_tools"])


def test_session_init_payload_is_instructions_plus_tools_json():
    payload = session_init_payload("full")
    assert serialize_initialize_instructions("full") in payload
    tools_json = serialize_tools_list("full")
    assert json.loads(tools_json)
    assert tools_json in payload


def test_measure_records_candidate_provenance_not_server_as_client():
    report = measure_mcp_context(surface="full")
    dumped = json.dumps(report)
    assert "fava-trails-server serialization" not in dumped
    assert report["subject"]["package"] == "fava-trails"
    assert report["subject"]["version"]
    assert report["subject"]["git_commit"]
    assert report["subject"]["role"] == "candidate"
    assert report["client"]["name"] == "mcp.Client"
    assert report["client"]["version"]
    assert report["client"]["name"] != report["subject"]["package"]


def test_compare_surfaces_includes_tested_release_and_candidate():
    from fava_trails import mcp_context

    payload = mcp_context.compare_surfaces()
    release = payload["tested_release"]
    assert mcp_context.ISSUE_104_TESTED_RELEASE_COMMIT.startswith("6c5278a")
    assert release["git_commit"] == mcp_context.ISSUE_104_TESTED_RELEASE_COMMIT
    assert release["role"] == "release"
    assert release["package"] == "fava-trails"
    assert release["session_init"]["tokens"] > 0
    assert release["tokenizer"]["name"] == DEFAULT_TOKENIZER
    assert payload["full"]["subject"]["role"] == "candidate"
    assert payload["compact"]["subject"]["role"] == "candidate"
    assert payload["full"]["subject"]["git_commit"] != release["git_commit"]


def test_docs_usage_guide_and_session_init_match_current_head():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "mcp-context-overhead.md").read_text()
    full = measure_mcp_context(surface="full")
    compact = measure_mcp_context(surface="compact")
    guide = full["usage_guide_on_demand"]
    assert str(guide["chars"]) in doc
    assert str(guide["tokens"]) in doc
    assert str(full["session_init"]["tokens"]) in doc
    assert str(compact["session_init"]["tokens"]) in doc
    assert "6c5278a" in doc
    assert full["client"]["name"] in doc
    assert full["subject"]["version"] in doc


def test_cmd_measure_mcp_context_prints_json(capsys, monkeypatch):
    from fava_trails.cli import cmd_measure_mcp_context
    from fava_trails.mcp_context import ISSUE_104_TESTED_RELEASE_COMMIT

    monkeypatch.delenv(MCP_SURFACE_ENV, raising=False)
    rc = cmd_measure_mcp_context(Namespace(surface="both"))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) >= {"full", "compact", "reduction", "budget", "tested_release"}
    assert payload["budget"]["ratio"] == COMPACT_SESSION_INIT_BUDGET_RATIO
    assert payload["reduction"]["session_init_token_ratio"] <= COMPACT_SESSION_INIT_BUDGET_RATIO
    assert payload["tested_release"]["git_commit"] == ISSUE_104_TESTED_RELEASE_COMMIT


@pytest.mark.asyncio
async def test_recall_save_promote_is_executed_on_both_surfaces(tmp_fava_home, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from fava_trails import server
    from fava_trails.config import ConfigStore
    from fava_trails.mcp_context import run_recall_save_promote_comparison
    from fava_trails.tools import navigation
    from fava_trails.trust_gate import TrustResult

    monkeypatch.setenv("FAVA_TRAILS_DIR", str(tmp_fava_home / "trails"))
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "synthetic-mcp-context")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    monkeypatch.setenv("FAVA_TRAILS_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SYNTHETIC_TRUST_GATE_KEY", "test-only-key")
    (tmp_fava_home / "config.yaml").write_text(
        "trails_dir: trails\ntrust_gate: llm-oneshot\npush_strategy: manual\n"
        "trust_gate_api_key_env: SYNTHETIC_TRUST_GATE_KEY\n"
    )
    (tmp_fava_home / "trails" / "trust-gate-prompt.md").write_text("Synthetic review policy.\n")
    (tmp_fava_home / ".gitignore").write_text(".jj/\n")

    def git(*args):
        import subprocess

        return subprocess.run(
            ["git", *args], cwd=tmp_fava_home, check=True, capture_output=True, text=True,
        )

    git("add", ".")
    git("-c", "user.name=Synthetic MCP Context", "-c", "user.email=synthetic@example.invalid",
        "commit", "-m", "Synthetic mcp-context fixture")
    review = AsyncMock(return_value=TrustResult(
        verdict="approve", reasoning="Synthetic evaluator result", reviewer="synthetic-reviewer",
    ))
    monkeypatch.setattr(navigation, "review_thought", review)
    monkeypatch.setattr(server, "_trail_managers", {})
    monkeypatch.setattr(server, "_trail_init_lock", None)
    ConfigStore.reset()
    server._prompt_cache.load_from_trails_dir(tmp_fava_home / "trails")

    payload = await run_recall_save_promote_comparison()
    assert payload["task"] == "recall/save/promote"
    assert payload["executed"] is True
    for surface in ("full", "compact"):
        side = payload[surface]
        assert side["executed"] is True
        assert set(side["discoverability"]["present"]) >= set(COMMON_WORKFLOW)
        assert side["session_init"]["tokens"] > 0
        assert side["save"]["status"] == "ok"
        assert side["recall_authoring"]["count"] == 1
        assert side["propose"]["status"] == "ok"
        assert side["error_recovery"]["missing_scope"]["status"] == "error"
        assert side["error_recovery"]["invalid_save"]["failed"] is True
        assert side["permissions"]["read_and_authoring_unchanged"] is True
    full_skip = payload["full"]["skipped_step_risk"]
    compact_skip = payload["compact"]["skipped_step_risk"]
    assert full_skip["session_start_recall_in_instructions"] is True
    assert compact_skip["session_start_recall_in_instructions"] is False
    assert "Compact omits" not in full_skip["note"]
    assert "Compact omits" in compact_skip["note"]
    assert payload["full"]["propose"]["status"] == payload["compact"]["propose"]["status"]
    assert payload["transport"] == "mcp.Client"
    assert payload["client"]["instantiated"] is True
    for surface in ("full", "compact"):
        side = payload[surface]
        assert side["session_started"] is True
        assert side["client_class"] == "mcp.Client"
        assert "scripted_steps" in side
        assert "observed_skips" in side
        assert "invalid_save" in side["scripted_steps"]
        assert "retry_save_with_content" in side["scripted_steps"]
        assert "propose_truth" in side["scripted_steps"]
        recovery = side["error_recovery"]
        assert recovery["invalid_save"]["recovered"] is True
        assert recovery["invalid_save"]["retry_status"] == "ok"
        assert recovery["missing_scope"]["recovered"] is True
        assert recovery["missing_scope"]["recovery_action"]
        naive = side["naive_initialize_only"]
        assert "skipped" in naive
        assert "called" in naive
        assert naive["get_usage_guide_called"] is False
    assert "session_start_recall" not in payload["full"]["observed_skips"]
    assert "session_start_recall" in payload["compact"]["observed_skips"]
    assert "session_start_recall" in payload["compact"]["naive_initialize_only"]["skipped"]
    assert "session_start_recall" not in payload["full"]["naive_initialize_only"]["skipped"]
    assert "propose_truth" in payload["compact"]["naive_initialize_only"]["skipped"]


def test_tested_release_is_frozen_and_not_relabeled(monkeypatch):
    from fava_trails import mcp_context

    monkeypatch.setattr("fava_trails.runtime_info.mcp_sdk_version", lambda: "99.99.99")
    monkeypatch.setattr(mcp_context, "_client_info", lambda: {
        "name": "mcp.Client",
        "package": "mcp",
        "version": "99.99.99",
    })
    release = mcp_context.measure_tested_release()
    assert release["frozen"] is True
    assert release["relabeling_forbidden"] is True
    assert release["git_commit"] == mcp_context.ISSUE_104_TESTED_RELEASE_COMMIT
    assert release["enabled_tools"]
    assert len(release["enabled_tools"]) == 17
    assert "recall" in release["enabled_tools"]
    assert release["recurrence"]["instructions"] == "once per initialize"
    assert "tools/list" in release["recurrence"]["tools_list"]
    assert release["lazy_loading"] is False
    assert release["client"]["version"] != "99.99.99"
    assert release["client"]["frozen"] is True
    assert release["client"]["version"] == "2.2.0"
    compared = mcp_context.compare_surfaces()
    assert compared["tested_release"]["client"]["version"] == "2.2.0"
    assert compared["full"]["client"]["version"] == "99.99.99"


def test_full_instructions_include_canonical_session_start_recalls():
    canonical = (Path(__file__).resolve().parents[1] / "AGENTS_USAGE_INSTRUCTIONS.md").read_text()
    runtime = serialize_initialize_instructions("full")
    lines = (
        'recall(trail_name="<scope>", query="status", scope={"project": "<project-name>"})',
        'recall(trail_name="<scope>", query="decisions", scope={"project": "<project-name>"})',
        'recall(trail_name="<scope>", query="gotcha", scope={"tags": ["gotcha"]})',
    )
    for line in lines:
        assert line in canonical
        assert line in runtime


def test_canonical_guide_states_subset_not_verbatim_inject():
    canonical = (Path(__file__).resolve().parents[1] / "AGENTS_USAGE_INSTRUCTIONS.md").read_text()
    lowered = canonical.lower()
    assert "verbatim inject" in lowered or "not a verbatim" in lowered or "maintained subset" in lowered
    assert "this file is the canonical source" in lowered
    assert "get_usage_guide" in lowered
    assert "core guidance from this file is injected" not in lowered

"""MCP context surface, measurement, and compact vs full workflow."""

from __future__ import annotations

import json
from argparse import Namespace

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
    assert "mcp_sdk_version" in report
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


def test_recall_save_promote_comparison_records_regressions():
    comparison = measure_mcp_context(surface="compact")["workflow_comparison"]
    assert comparison["task"] == "recall/save/promote"
    assert set(comparison["discoverable_tools"]) >= set(COMMON_WORKFLOW)
    assert comparison["skipped_step_risk"]["get_usage_guide_optional"] is True
    assert comparison["error_recovery"]["same_handlers"] is True
    assert comparison["permissions"]["read_and_authoring_unchanged"] is True
    assert comparison["server_enforced"]
    assert comparison["client_or_prompt"]
    assert "cross-session sharing" in comparison["not_claimed"].lower()


def test_cmd_measure_mcp_context_prints_json(capsys, monkeypatch):
    from fava_trails.cli import cmd_measure_mcp_context

    monkeypatch.delenv(MCP_SURFACE_ENV, raising=False)
    rc = cmd_measure_mcp_context(Namespace(surface="both"))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) >= {"full", "compact", "reduction", "budget"}
    assert payload["budget"]["ratio"] == COMPACT_SESSION_INIT_BUDGET_RATIO
    assert payload["reduction"]["session_init_token_ratio"] <= COMPACT_SESSION_INIT_BUDGET_RATIO

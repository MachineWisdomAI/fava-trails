"""Tests for MCP server instructions field and tool description enhancements."""

import json

import pytest
from mcp.types import TextContent

from fava_trails.server import (
    TOOL_DEFINITIONS,
    _build_server_instructions,
    _load_usage_guide,
    server,
    with_tool_timeout,
)


def _get_tool_desc(name: str) -> str:
    """Get the description for a tool by name."""
    for td in TOOL_DEFINITIONS:
        if td["name"] == name:
            return td["description"]
    raise KeyError(f"Tool '{name}' not found in TOOL_DEFINITIONS")


class TestServerInstructions:
    """Tests for the MCP server instructions field."""

    def test_server_has_instructions(self):
        """Server must have a non-empty instructions string."""
        assert server.instructions
        assert len(server.instructions) > 100

    def test_instructions_contain_scope_discovery(self):
        """Instructions must cover scope discovery protocol."""
        instructions = _build_server_instructions()
        assert "Scope Discovery" in instructions
        assert "FAVA_TRAILS_SCOPE" in instructions
        assert ".fava-trails.yaml" in instructions

    def test_instructions_contain_session_protocol(self):
        """Instructions must cover session start protocol."""
        instructions = _build_server_instructions()
        assert "recall" in instructions
        assert "Session Start" in instructions

    def test_instructions_contain_promotion_mandate(self):
        """Instructions must emphasize mandatory promotion."""
        instructions = _build_server_instructions()
        assert "propose_truth" in instructions
        assert "mandatory" in instructions.lower()

    def test_instructions_contain_agent_identity(self):
        """Instructions must cover agent identity conventions."""
        instructions = _build_server_instructions()
        assert "agent_id" in instructions
        assert "stable role" in instructions

    def test_instructions_contain_trust_calibration(self):
        """Instructions must cover recalled thought safety."""
        instructions = _build_server_instructions()
        assert "Trust Gate" in instructions
        assert "staleness" in instructions.lower() or "stale" in instructions.lower()

    def test_instructions_reference_usage_guide(self):
        """Instructions must reference the get_usage_guide tool."""
        instructions = _build_server_instructions()
        assert "get_usage_guide" in instructions


class TestToolDescriptionEnhancements:
    """Tests for enhanced tool descriptions."""

    def test_recall_contains_warning(self):
        """recall description must contain Trust Gate warning."""
        desc = _get_tool_desc("recall")
        assert "WARNING" in desc
        assert "Trust Gate" in desc

    def test_propose_truth_contains_mandatory(self):
        """propose_truth description must mention mandatory promotion."""
        desc = _get_tool_desc("propose_truth")
        assert "mandatory" in desc
        assert "invisible" in desc

    def test_save_thought_contains_agent_identity(self):
        """save_thought description must mention stable role identifier."""
        desc = _get_tool_desc("save_thought")
        assert "stable role" in desc

    def test_save_thought_contains_promote_guidance(self):
        """save_thought description must remind agents to promote when finalized."""
        desc = _get_tool_desc("save_thought")
        assert "propose_truth" in desc
        assert "finalized" in desc

    def test_propose_truth_contains_sync_guidance(self):
        """propose_truth description must advise calling sync after promoting."""
        desc = _get_tool_desc("propose_truth")
        assert "sync" in desc

    def test_recall_contains_scope_discovery(self):
        """recall description must include scope discovery priority order."""
        desc = _get_tool_desc("recall")
        assert "FAVA_TRAILS_SCOPE" in desc
        assert ".fava-trails.yaml" in desc

    def test_recall_contains_session_start_hint(self):
        """recall description must hint at session start usage."""
        desc = _get_tool_desc("recall")
        assert "session" in desc.lower()

    def test_get_usage_guide_entry_point_language(self):
        """get_usage_guide description must be positioned as entry point for new agents."""
        desc = _get_tool_desc("get_usage_guide")
        assert "new to fava-trails" in desc or "unsure how to use" in desc


class TestGetUsageGuide:
    """Tests for the get_usage_guide tool."""

    def test_tool_exists_in_definitions(self):
        """get_usage_guide must be in TOOL_DEFINITIONS."""
        names = [td["name"] for td in TOOL_DEFINITIONS]
        assert "get_usage_guide" in names

    def test_load_usage_guide_returns_content(self):
        """_load_usage_guide must return non-empty content."""
        content = _load_usage_guide()
        assert len(content) > 100
        assert "FAVA Trail" in content

    def test_load_usage_guide_contains_key_sections(self):
        """Usage guide must contain expected sections."""
        content = _load_usage_guide()
        assert "Scope Discovery" in content
        assert "Session Start" in content or "At Session Start" in content
        assert "Task Completion" in content or "On Task Completion" in content
        assert "Trust Calibration" in content or "Handling Recalled Thoughts" in content

    def test_tool_count(self):
        """TOOL_DEFINITIONS should have 17 tools (15 original + list_trails alias + get_usage_guide)."""
        assert len(TOOL_DEFINITIONS) == 17


class TestWithToolTimeout:
    """Tests for the @with_tool_timeout decorator."""

    @pytest.mark.asyncio
    async def test_passes_through_on_success(self):
        """Decorated handler returns normally when it completes within the timeout."""
        async def _fast_handler(name, arguments):
            return [TextContent(type="text", text='{"status":"ok"}')]

        from fava_trails.config import ConfigStore
        from fava_trails.models import GlobalConfig

        config = ConfigStore.__new__(ConfigStore)
        config.global_config = GlobalConfig(tool_timeout_secs=5, trust_gate_timeout_secs=0)
        config.data_repo_root = None
        config.trails_dir = None
        ConfigStore.override(config)

        wrapped = with_tool_timeout(_fast_handler)
        result = await wrapped("save_thought", {})
        assert result[0].text == '{"status":"ok"}'

    @pytest.mark.asyncio
    async def test_timeout_returns_error_dict(self):
        """Decorated handler returns a structured error when the timeout fires."""
        import asyncio

        async def _hanging_handler(name, arguments):
            await asyncio.sleep(9999)

        from fava_trails.config import ConfigStore
        from fava_trails.models import GlobalConfig

        config = ConfigStore.__new__(ConfigStore)
        config.global_config = GlobalConfig(tool_timeout_secs=1, trust_gate_timeout_secs=0)
        config.data_repo_root = None
        config.trails_dir = None
        ConfigStore.override(config)

        wrapped = with_tool_timeout(_hanging_handler)
        result = await wrapped("sync", {})
        payload = json.loads(result[0].text)
        assert payload["status"] == "error"
        assert "timed out" in payload["message"].lower()
        assert "sync" in payload["message"]

    @pytest.mark.asyncio
    async def test_disabled_when_zero(self):
        """Timeout is skipped entirely when tool_timeout_secs is 0."""
        calls = []

        async def _handler(name, arguments):
            calls.append(name)
            return [TextContent(type="text", text='{"status":"ok"}')]

        from fava_trails.config import ConfigStore
        from fava_trails.models import GlobalConfig

        config = ConfigStore.__new__(ConfigStore)
        config.global_config = GlobalConfig(tool_timeout_secs=0)
        config.data_repo_root = None
        config.trails_dir = None
        ConfigStore.override(config)

        wrapped = with_tool_timeout(_handler)
        await wrapped("recall", {})
        assert calls == ["recall"]

"""Tests for MCP server instructions field and tool description enhancements."""

import jsonschema
import pytest
from mcp.types import TextContent

from fava_trails.config import ConfigStore
from fava_trails.server import (
    TOOL_DEFINITIONS,
    _build_server_instructions,
    _load_usage_guide,
    handle_call_tool,
    handle_list_tools,
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


class TestToolMetadata:
    """Tests for ChatGPT-facing tool schemas and annotations."""

    def test_all_tools_have_output_schema(self):
        """Every advertised tool must declare an output schema."""
        for td in TOOL_DEFINITIONS:
            assert "outputSchema" in td, td["name"]
            assert td["outputSchema"]["type"] == "object"

    def test_all_tools_have_annotations(self):
        """Every advertised tool must include MCP tool annotations."""
        for td in TOOL_DEFINITIONS:
            annotations = td.get("annotations")
            assert isinstance(annotations, dict), td["name"]
            assert "readOnlyHint" in annotations
            assert "destructiveHint" in annotations
            assert "openWorldHint" in annotations

    def test_read_only_tools_are_annotated(self):
        """Read-only query tools must be marked read-only for ChatGPT."""
        read_only = {
            "conflicts",
            "diff",
            "get_thought",
            "get_usage_guide",
            "list_scopes",
            "list_trails",
            "recall",
        }
        for td in TOOL_DEFINITIONS:
            if td["name"] in read_only:
                assert td["annotations"]["readOnlyHint"] is True
                assert td["annotations"]["idempotentHint"] is True

    def test_destructive_tools_are_annotated(self):
        """Mutation tools with replacement/rollback semantics must be flagged."""
        destructive = {"change_scope", "forget", "rollback", "supersede", "update_thought"}
        for td in TOOL_DEFINITIONS:
            if td["name"] in destructive:
                assert td["annotations"]["destructiveHint"] is True

    @pytest.mark.asyncio
    async def test_handle_list_tools_passes_metadata_to_mcp_tool(self):
        """ListTools responses must expose schemas and annotations."""
        tools = await handle_list_tools()
        by_name = {tool.name: tool for tool in tools}

        recall = by_name["recall"]
        assert recall.outputSchema
        assert recall.outputSchema["required"] == ["status", "count", "thoughts", "filters"]
        assert recall.annotations
        assert recall.annotations.readOnlyHint is True

        save_thought = by_name["save_thought"]
        assert save_thought.outputSchema
        assert save_thought.annotations
        assert save_thought.annotations.readOnlyHint is False
        assert save_thought.annotations.openWorldHint is True

    @pytest.mark.asyncio
    async def test_list_scopes_returns_structured_schema_valid_result(self, tmp_path, monkeypatch):
        """JSON tools return structured dicts matching their output schema."""
        data_repo = tmp_path / "fava-trails-data"
        thoughts_dir = data_repo / "trails" / "mwai" / "eng" / "demo" / "thoughts"
        thoughts_dir.mkdir(parents=True)
        monkeypatch.setenv("FAVA_TRAILS_DATA_REPO", str(data_repo))
        ConfigStore.reset()

        result = await handle_call_tool("list_scopes", {"prefix": "mwai/eng"})

        assert result["status"] == "ok"
        assert result["scopes"] == [{"path": "mwai/eng/demo"}]
        jsonschema.validate(
            result,
            next(td["outputSchema"] for td in TOOL_DEFINITIONS if td["name"] == "list_scopes"),
        )

    @pytest.mark.asyncio
    async def test_usage_guide_returns_text_and_structured_content(self):
        """Markdown guide keeps text content and adds structured content."""
        content, structured = await handle_call_tool("get_usage_guide", {})

        assert len(content) == 1
        assert isinstance(content[0], TextContent)
        assert structured["status"] == "ok"
        assert structured["content"] == content[0].text
        jsonschema.validate(
            structured,
            next(td["outputSchema"] for td in TOOL_DEFINITIONS if td["name"] == "get_usage_guide"),
        )


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
        assert result["status"] == "error"
        assert "timed out" in result["message"].lower()
        assert "sync" in result["message"]

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

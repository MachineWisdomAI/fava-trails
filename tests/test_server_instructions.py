"""Tests for MCP server instructions field and tool description enhancements."""

from fava_trails.server import (
    TOOL_DEFINITIONS,
    _build_server_instructions,
    _load_usage_guide,
    server,
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
        assert "FAVA_TRAIL_SCOPE" in instructions
        assert ".fava-trail.yaml" in instructions

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

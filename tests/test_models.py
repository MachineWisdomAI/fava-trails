"""Tests for Pydantic models and markdown serialization."""

import pytest

from fava_trails.models import (
    DEFAULT_NAMESPACE,
    KNOWN_HOOKS,
    NAMESPACE_ROUTES,
    GlobalConfig,
    HookEntry,
    Relationship,
    RelationshipType,
    SourceType,
    ThoughtFrontmatter,
    ThoughtMetadata,
    ThoughtRecord,
    TrailConfig,
    ValidationStatus,
)


def test_thought_frontmatter_defaults():
    fm = ThoughtFrontmatter()
    assert fm.schema_version == 1
    assert fm.thought_id  # ULID auto-generated
    assert len(fm.thought_id) == 26  # ULID is 26 chars
    assert fm.parent_id is None
    assert fm.superseded_by is None
    assert fm.source_type == SourceType.OBSERVATION
    assert fm.validation_status == ValidationStatus.DRAFT
    assert fm.confidence == 0.5
    assert fm.relationships == []


def test_thought_record_to_markdown():
    record = ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            thought_id="01JMKR3V8GQZX4N7P2WDCB5HYT",
            agent_id="test-agent",
            source_type=SourceType.DECISION,
            confidence=0.9,
            metadata=ThoughtMetadata(project="test", tags=["arch"]),
        ),
        content="This is a test decision.",
    )
    md = record.to_markdown()
    assert md.startswith("---\n")
    assert "thought_id: 01JMKR3V8GQZX4N7P2WDCB5HYT" in md
    assert "source_type: decision" in md
    assert "This is a test decision." in md


def test_thought_record_from_markdown():
    md = """---
schema_version: 1
thought_id: "01JMKR3V8GQZX4N7P2WDCB5HYT"
agent_id: test-agent
source_type: decision
confidence: 0.9
validation_status: draft
created_at: "2026-02-19T12:00:00Z"
metadata:
  project: test
  tags:
    - arch
---
This is a test decision."""

    record = ThoughtRecord.from_markdown(md)
    assert record.thought_id == "01JMKR3V8GQZX4N7P2WDCB5HYT"
    assert record.frontmatter.source_type == SourceType.DECISION
    assert record.frontmatter.confidence == 0.9
    assert record.content == "This is a test decision."
    assert record.frontmatter.metadata.project == "test"
    assert "arch" in record.frontmatter.metadata.tags


def test_thought_record_roundtrip():
    original = ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            thought_id="01JMKR3V8GQZX4N7P2WDCB5HYT",
            agent_id="roundtrip-test",
            source_type=SourceType.INFERENCE,
            confidence=0.7,
            relationships=[
                Relationship(type=RelationshipType.DEPENDS_ON, target_id="01JMKQ8W7FNRY3K6P1VDBA4GXS")
            ],
        ),
        content="Testing round-trip serialization.",
    )
    md = original.to_markdown()
    recovered = ThoughtRecord.from_markdown(md)
    assert recovered.thought_id == original.thought_id
    assert recovered.frontmatter.agent_id == "roundtrip-test"
    assert recovered.frontmatter.source_type == SourceType.INFERENCE
    assert len(recovered.frontmatter.relationships) == 1
    assert recovered.frontmatter.relationships[0].type == RelationshipType.DEPENDS_ON


def test_is_superseded():
    record = ThoughtRecord(frontmatter=ThoughtFrontmatter())
    assert not record.is_superseded

    record.frontmatter.superseded_by = "01JMKS7Y2HPQW5M8R3XECF6JZV"
    assert record.is_superseded


def test_namespace_routes():
    assert NAMESPACE_ROUTES[SourceType.DECISION] == "decisions"
    assert NAMESPACE_ROUTES[SourceType.OBSERVATION] == "observations"
    assert NAMESPACE_ROUTES[SourceType.USER_INPUT] == "preferences"
    assert DEFAULT_NAMESPACE == "drafts"


# ─── HookEntry ───


def test_hook_entry_path():
    entry = HookEntry(path="./my_hook.py", points=["before_save"])
    assert entry.path == "./my_hook.py"
    assert entry.module is None
    assert entry.order == 50
    assert entry.fail_mode == "open"
    assert entry.config == {}


def test_hook_entry_module():
    entry = HookEntry(module="my_hooks.plugin", points=["after_save", "on_recall"])
    assert entry.module == "my_hooks.plugin"
    assert entry.path is None


def test_hook_entry_mutable_default_not_shared():
    """Each HookEntry gets its own config dict (Field(default_factory=dict))."""
    a = HookEntry(path="./a.py", points=["before_save"])
    b = HookEntry(path="./b.py", points=["before_save"])
    a.config["key"] = "value"
    assert b.config == {}


def test_hook_entry_both_sources_rejected():
    with pytest.raises(ValueError, match="not both"):
        HookEntry(module="foo", path="./bar.py", points=["before_save"])


def test_hook_entry_no_source_rejected():
    with pytest.raises(ValueError, match="must have either"):
        HookEntry(points=["before_save"])


def test_hook_entry_unknown_point_rejected():
    with pytest.raises(ValueError, match="Unknown lifecycle point"):
        HookEntry(path="./x.py", points=["not_a_hook"])


def test_hook_entry_invalid_fail_mode():
    with pytest.raises(ValueError, match="fail_mode"):
        HookEntry(path="./x.py", points=["before_save"], fail_mode="maybe")


def test_known_hooks_contains_expected():
    expected = {"before_save", "after_save", "before_propose", "after_propose",
                "after_supersede", "on_recall", "on_startup"}
    assert KNOWN_HOOKS == expected


# ─── GlobalConfig.hooks ───


def test_global_config_defaults_no_hooks():
    config = GlobalConfig()
    assert config.hooks == []


def test_global_config_with_hooks():
    config = GlobalConfig(hooks=[
        {"path": "./my_hook.py", "points": ["before_save"]},
    ])
    assert len(config.hooks) == 1
    assert isinstance(config.hooks[0], HookEntry)
    assert config.hooks[0].path == "./my_hook.py"


def test_global_config_hooks_mutable_default_not_shared():
    a = GlobalConfig()
    b = GlobalConfig()
    a.hooks.append(HookEntry(path="./x.py", points=["before_save"]))
    assert b.hooks == []


# ─── TrailConfig.hooks ───


def test_trail_config_defaults_no_hooks():
    config = TrailConfig(name="my-trail")
    assert config.hooks == []


def test_trail_config_hooks_raises_valueerror():
    """Non-empty hooks in TrailConfig raises ValueError at parse time."""
    with pytest.raises(ValueError, match="Per-trail hook overrides not yet supported"):
        TrailConfig(name="my-trail", hooks=[
            {"path": "./hook.py", "points": ["before_save"]},
        ])

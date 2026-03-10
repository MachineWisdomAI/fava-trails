"""Integration tests for MCP tool handlers via TrailManager."""

import pytest

from fava_trails.models import SourceType
from fava_trails.trail import recall_multi


@pytest.mark.asyncio
async def test_save_and_get_thought(trail_manager):
    """Save a thought and retrieve it by ID."""
    record = await trail_manager.save_thought(
        content="Test observation about architecture.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
        confidence=0.8,
    )
    assert record.thought_id
    assert record.content == "Test observation about architecture."
    assert record.frontmatter.source_type == SourceType.OBSERVATION

    # Retrieve
    retrieved = await trail_manager.get_thought(record.thought_id)
    assert retrieved is not None
    assert retrieved.thought_id == record.thought_id
    assert retrieved.content == record.content


@pytest.mark.asyncio
async def test_save_thought_defaults_to_drafts(trail_manager):
    """save_thought should default to drafts/ namespace."""
    record = await trail_manager.save_thought(
        content="Draft thought.",
        agent_id="test-agent",
    )
    drafts_path = trail_manager.trail_path / "thoughts" / "drafts" / f"{record.thought_id}.md"
    assert drafts_path.exists()


@pytest.mark.asyncio
async def test_save_thought_custom_namespace(trail_manager):
    """save_thought with explicit namespace should store there."""
    record = await trail_manager.save_thought(
        content="Decision thought.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
        namespace="decisions",
    )
    decisions_path = trail_manager.trail_path / "thoughts" / "decisions" / f"{record.thought_id}.md"
    assert decisions_path.exists()


@pytest.mark.asyncio
async def test_propose_truth_promotes_namespace(trail_manager):
    """propose_truth should move from drafts/ to permanent namespace based on source_type."""
    # Save as draft decision
    record = await trail_manager.save_thought(
        content="Architecture decision to use JJ.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
    )
    drafts_path = trail_manager.trail_path / "thoughts" / "drafts" / f"{record.thought_id}.md"
    assert drafts_path.exists()

    # Promote
    promoted = await trail_manager.propose_truth(record.thought_id)
    assert promoted.frontmatter.validation_status.value == "proposed"

    # Should be in decisions/ now, not drafts/
    decisions_path = trail_manager.trail_path / "thoughts" / "decisions" / f"{record.thought_id}.md"
    assert decisions_path.exists()
    assert not drafts_path.exists()


@pytest.mark.asyncio
async def test_supersede_atomic(trail_manager):
    """supersede should create new thought + backlink original atomically."""
    original = await trail_manager.save_thought(
        content="Original decision.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
        namespace="decisions",
    )
    assert not original.is_superseded

    # Supersede
    new = await trail_manager.supersede(
        original_id=original.thought_id,
        new_content="Updated decision after review.",
        reason="Incorporated feedback from consensus review",
        agent_id="test-agent",
    )
    assert new.thought_id != original.thought_id
    assert new.frontmatter.parent_id == original.thought_id

    # Original should now have superseded_by
    refreshed = await trail_manager.get_thought(original.thought_id)
    assert refreshed is not None
    assert refreshed.frontmatter.superseded_by == new.thought_id


@pytest.mark.asyncio
async def test_recall_hides_superseded(trail_manager):
    """recall should hide superseded thoughts by default."""
    original = await trail_manager.save_thought(
        content="Old observation.",
        agent_id="test-agent",
        namespace="observations",
    )
    new = await trail_manager.supersede(
        original_id=original.thought_id,
        new_content="Updated observation.",
        reason="Corrected error",
        agent_id="test-agent",
    )

    # Default: hide superseded
    results = await trail_manager.recall(namespace="observations")
    ids = [r.thought_id for r in results]
    assert new.thought_id in ids
    assert original.thought_id not in ids

    # With include_superseded
    results_all = await trail_manager.recall(namespace="observations", include_superseded=True)
    ids_all = [r.thought_id for r in results_all]
    assert new.thought_id in ids_all
    assert original.thought_id in ids_all


@pytest.mark.asyncio
async def test_recall_by_query(trail_manager):
    """recall should filter by text query."""
    await trail_manager.save_thought(content="JJ is great for versioning.", agent_id="test")
    await trail_manager.save_thought(content="Python is the best language.", agent_id="test")

    results = await trail_manager.recall(query="JJ")
    assert len(results) >= 1
    assert any("JJ" in r.content for r in results)


@pytest.mark.asyncio
async def test_recall_multi_word_query(trail_manager):
    """recall should match multi-word queries using word-level AND (not exact substring)."""
    await trail_manager.save_thought(
        content="JJ is great for versioning.", agent_id="test"
    )
    await trail_manager.save_thought(
        content="Python is the best language.", agent_id="test"
    )

    # "JJ versioning" — both words present but not contiguous
    results = await trail_manager.recall(query="JJ versioning")
    assert len(results) >= 1
    assert any("JJ" in r.content and "versioning" in r.content for r in results)

    # Non-matching multi-word query
    results_none = await trail_manager.recall(query="nonexistent stuff here")
    assert len(results_none) == 0


@pytest.mark.asyncio
async def test_recall_by_scope(trail_manager):
    """recall should filter by metadata scope."""
    await trail_manager.save_thought(
        content="Scoped thought.",
        agent_id="test",
        metadata={"project": "fava-trail", "tags": ["arch"]},
    )
    await trail_manager.save_thought(
        content="Other thought.",
        agent_id="test",
        metadata={"project": "other-project"},
    )

    results = await trail_manager.recall(scope={"project": "fava-trail"})
    assert len(results) >= 1
    assert all(r.frontmatter.metadata.project == "fava-trail" for r in results)


@pytest.mark.asyncio
async def test_recall_by_scope_tags(trail_manager):
    """recall should filter by metadata scope tags (subset match)."""
    await trail_manager.save_thought(
        content="Architecture overview.",
        agent_id="test",
        metadata={"tags": ["arch", "codebase-state"]},
    )
    await trail_manager.save_thought(
        content="Untagged thought.",
        agent_id="test",
        metadata={"project": "fava-trail"},
    )
    await trail_manager.save_thought(
        content="Different tag thought.",
        agent_id="test",
        metadata={"tags": ["gotcha"]},
    )

    # Single tag filter
    results = await trail_manager.recall(scope={"tags": ["codebase-state"]})
    assert len(results) >= 1
    assert all("codebase-state" in r.frontmatter.metadata.tags for r in results)

    # Multi-tag subset match — all required tags must be present
    results_multi = await trail_manager.recall(scope={"tags": ["arch", "codebase-state"]})
    assert len(results_multi) >= 1
    assert all(
        {"arch", "codebase-state"}.issubset(set(r.frontmatter.metadata.tags))
        for r in results_multi
    )

    # Non-matching tag returns empty
    results_none = await trail_manager.recall(scope={"tags": ["nonexistent-tag"]})
    assert len(results_none) == 0


@pytest.mark.asyncio
async def test_recall_by_scope_branch(trail_manager):
    """recall should filter by metadata scope branch."""
    await trail_manager.save_thought(
        content="Main branch thought.",
        agent_id="test",
        metadata={"project": "fava-trail", "branch": "main"},
    )
    await trail_manager.save_thought(
        content="Feature branch thought.",
        agent_id="test",
        metadata={"project": "fava-trail", "branch": "feature-xyz"},
    )

    results = await trail_manager.recall(scope={"branch": "main"})
    assert len(results) >= 1
    assert all(r.frontmatter.metadata.branch == "main" for r in results)

    # Feature branch isolated
    results_feature = await trail_manager.recall(scope={"branch": "feature-xyz"})
    assert len(results_feature) >= 1
    assert all(r.frontmatter.metadata.branch == "feature-xyz" for r in results_feature)

    # Combined scope: project + branch
    results_combined = await trail_manager.recall(
        scope={"project": "fava-trail", "branch": "main"}
    )
    assert all(
        r.frontmatter.metadata.project == "fava-trail"
        and r.frontmatter.metadata.branch == "main"
        for r in results_combined
    )


@pytest.mark.asyncio
async def test_recall_query_finds_tags_in_searchable(trail_manager):
    """recall query should find thoughts via tag even when content doesn't contain the tag string."""
    await trail_manager.save_thought(
        content="This content has no mention of the tag value.",
        agent_id="test",
        metadata={"tags": ["needle-tag"]},
    )

    results = await trail_manager.recall(query="needle-tag")
    assert len(results) >= 1
    assert any("needle-tag" in r.frontmatter.metadata.tags for r in results)


@pytest.mark.asyncio
async def test_recall_query_searches_metadata_tags(trail_manager):
    """recall query should match metadata tags, not just content."""
    await trail_manager.save_thought(
        content="Some unrelated content body.",
        agent_id="test",
        metadata={"tags": ["cross-agent-test", "sync"]},
    )

    results = await trail_manager.recall(query="cross-agent-test")
    assert len(results) >= 1
    assert any("cross-agent-test" in r.frontmatter.metadata.tags for r in results)


@pytest.mark.asyncio
async def test_recall_query_searches_metadata_project(trail_manager):
    """recall query should match metadata project."""
    await trail_manager.save_thought(
        content="A thought with no mention of the project in body.",
        agent_id="test",
        metadata={"project": "wise-agents-toolkit"},
    )

    results = await trail_manager.recall(query="wise-agents-toolkit")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_recall_query_searches_agent_id(trail_manager):
    """recall query should match agent_id."""
    await trail_manager.save_thought(
        content="Content that does not mention the agent.",
        agent_id="claude-desktop",
    )

    results = await trail_manager.recall(query="claude-desktop")
    assert len(results) >= 1
    assert any(r.frontmatter.agent_id == "claude-desktop" for r in results)


@pytest.mark.asyncio
async def test_recall_with_relationships(trail_manager):
    """recall with include_relationships=True should return 1-hop related thoughts."""
    parent = await trail_manager.save_thought(
        content="Parent thought.",
        agent_id="test",
        namespace="decisions",
    )
    child = await trail_manager.save_thought(
        content="Child thought depends on parent.",
        agent_id="test",
        namespace="decisions",
        relationships=[{"type": "DEPENDS_ON", "target_id": parent.thought_id}],
    )

    # Search for child, include relationships
    results = await trail_manager.recall(
        query="Child",
        namespace="decisions",
        include_relationships=True,
    )
    ids = [r.thought_id for r in results]
    assert child.thought_id in ids
    assert parent.thought_id in ids  # 1-hop traversal


@pytest.mark.asyncio
async def test_learn_preference(trail_manager):
    """learn_preference should store in preferences/ namespace."""
    record = await trail_manager.learn_preference(
        content="Always use snake_case for Python.",
        preference_type="firm",
        agent_id="test-agent",
    )
    assert record.frontmatter.source_type == SourceType.USER_INPUT
    assert record.frontmatter.confidence == 1.0

    pref_path = trail_manager.trail_path / "thoughts" / "preferences" / "firm" / f"{record.thought_id}.md"
    assert pref_path.exists()


@pytest.mark.asyncio
async def test_decision_without_intent_ref_warns(trail_manager, caplog):
    """Saving a decision without intent_ref should log a warning."""
    import logging
    with caplog.at_level(logging.WARNING):
        await trail_manager.save_thought(
            content="Decision without intent.",
            agent_id="test",
            source_type=SourceType.DECISION,
        )
    assert any("intent_ref" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_op_log(trail_manager):
    """Operation log should return semantic summaries."""
    ops = await trail_manager.get_op_log(limit=5)
    assert len(ops) > 0
    for op in ops:
        assert op.op_id
        assert op.description


@pytest.mark.asyncio
async def test_start_and_forget(trail_manager):
    """start_thought + forget should create and discard a reasoning line."""
    change = await trail_manager.start_thought("Exploring approach A")
    assert change.change_id

    result = await trail_manager.forget()
    assert "abandon" in result.lower()


# --- Phase 1b.3: update_thought + content freeze ---


@pytest.mark.asyncio
async def test_update_thought_happy_path(trail_manager):
    """update_thought should modify content in-place (same file, same ULID)."""
    record = await trail_manager.save_thought(
        content="Original wording.",
        agent_id="test-agent",
    )
    path = trail_manager.trail_path / "thoughts" / "drafts" / f"{record.thought_id}.md"
    assert path.exists()

    updated = await trail_manager.update_thought(record.thought_id, "Refined wording.")
    assert updated.thought_id == record.thought_id
    assert updated.content == "Refined wording."

    # Same file, same path
    assert path.exists()
    retrieved = await trail_manager.get_thought(record.thought_id)
    assert retrieved.content == "Refined wording."


@pytest.mark.asyncio
async def test_update_thought_preserves_frontmatter(trail_manager):
    """update_thought must preserve all frontmatter identity fields (tamper-proof)."""
    record = await trail_manager.save_thought(
        content="Original content.",
        agent_id="original-agent",
        source_type=SourceType.DECISION,
        confidence=0.9,
        metadata={"project": "fava-trail", "tags": ["arch"]},
    )

    updated = await trail_manager.update_thought(record.thought_id, "New content.")

    # Frontmatter preserved
    assert updated.frontmatter.agent_id == "original-agent"
    assert updated.frontmatter.source_type == SourceType.DECISION
    assert updated.frontmatter.confidence == 0.9
    assert updated.frontmatter.metadata.project == "fava-trail"
    assert updated.frontmatter.metadata.tags == ["arch"]
    assert updated.frontmatter.created_at == record.frontmatter.created_at


@pytest.mark.asyncio
async def test_update_thought_content_freeze_approved(trail_manager):
    """update_thought on approved thought should raise ValueError."""
    from fava_trails.models import ValidationStatus

    record = await trail_manager.save_thought(content="Decision.", agent_id="test")
    # Manually set to approved by writing to disk
    path = trail_manager._find_thought_path(record.thought_id)
    from fava_trails.models import ThoughtRecord
    loaded = ThoughtRecord.from_markdown(path.read_text())
    loaded.frontmatter.validation_status = ValidationStatus.APPROVED
    path.write_text(loaded.to_markdown())

    with pytest.raises(ValueError, match="frozen"):
        await trail_manager.update_thought(record.thought_id, "Should fail.")


@pytest.mark.asyncio
async def test_update_thought_content_freeze_rejected(trail_manager):
    """update_thought on rejected thought should raise ValueError."""
    from fava_trails.models import ValidationStatus

    record = await trail_manager.save_thought(content="Rejected idea.", agent_id="test")
    path = trail_manager._find_thought_path(record.thought_id)
    from fava_trails.models import ThoughtRecord
    loaded = ThoughtRecord.from_markdown(path.read_text())
    loaded.frontmatter.validation_status = ValidationStatus.REJECTED
    path.write_text(loaded.to_markdown())

    with pytest.raises(ValueError, match="frozen"):
        await trail_manager.update_thought(record.thought_id, "Should fail.")


@pytest.mark.asyncio
async def test_update_thought_content_freeze_tombstoned(trail_manager):
    """update_thought on tombstoned thought should raise ValueError."""
    from fava_trails.models import ValidationStatus

    record = await trail_manager.save_thought(content="Old stale draft.", agent_id="test")
    path = trail_manager._find_thought_path(record.thought_id)
    from fava_trails.models import ThoughtRecord
    loaded = ThoughtRecord.from_markdown(path.read_text())
    loaded.frontmatter.validation_status = ValidationStatus.TOMBSTONED
    path.write_text(loaded.to_markdown())

    with pytest.raises(ValueError, match="frozen"):
        await trail_manager.update_thought(record.thought_id, "Should fail.")


@pytest.mark.asyncio
async def test_update_thought_content_freeze_superseded(trail_manager):
    """update_thought on superseded thought should raise ValueError."""
    record = await trail_manager.save_thought(
        content="Will be superseded.",
        agent_id="test",
        namespace="observations",
    )
    await trail_manager.supersede(
        original_id=record.thought_id,
        new_content="Replacement.",
        reason="Corrected",
        agent_id="test",
    )

    with pytest.raises(ValueError, match="frozen.*superseded"):
        await trail_manager.update_thought(record.thought_id, "Should fail.")


@pytest.mark.asyncio
async def test_update_thought_not_found(trail_manager):
    """update_thought on non-existent thought should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await trail_manager.update_thought("01NONEXISTENT000000000000", "Should fail.")


@pytest.mark.asyncio
async def test_save_thought_still_creates_new(trail_manager):
    """save_thought must still always create NEW thoughts (regression test)."""
    r1 = await trail_manager.save_thought(content="First thought.", agent_id="test")
    r2 = await trail_manager.save_thought(content="Second thought.", agent_id="test")
    assert r1.thought_id != r2.thought_id

    # Both exist as separate files
    p1 = trail_manager._find_thought_path(r1.thought_id)
    p2 = trail_manager._find_thought_path(r2.thought_id)
    assert p1 is not None
    assert p2 is not None
    assert p1 != p2


# --- Phase 2: Hierarchical Scoping ---


@pytest.mark.asyncio
async def test_nested_trail_save_and_recall(nested_trail_managers):
    """save_thought on nested trail creates correct directory structure."""
    project = nested_trail_managers["project"]
    record = await project.save_thought(
        content="Project-level decision about auth flow.",
        agent_id="test-agent",
        source_type=SourceType.DECISION,
    )
    path = project.trail_path / "thoughts" / "drafts" / f"{record.thought_id}.md"
    assert path.exists()
    # Verify nested path: trails/mw/eng/fava-trail/thoughts/drafts/
    assert "mw/eng/fava-trail" in str(path) or "mw\\eng\\fava-trail" in str(path)

    # Recall finds it
    results = await project.recall(query="auth flow")
    assert len(results) == 1
    assert results[0].thought_id == record.thought_id


@pytest.mark.asyncio
async def test_recall_multi_across_scopes(nested_trail_managers):
    """recall_multi searches across multiple scopes and deduplicates."""
    company = nested_trail_managers["company"]
    team = nested_trail_managers["team"]
    project = nested_trail_managers["project"]

    # Save different thoughts in different scopes
    c_record = await company.save_thought(
        content="Company coding standards: use black formatter.",
        agent_id="test-agent",
    )
    t_record = await team.save_thought(
        content="Team convention: use pytest for all tests.",
        agent_id="test-agent",
    )
    p_record = await project.save_thought(
        content="Project decision: use asyncio throughout.",
        agent_id="test-agent",
    )

    # Multi-scope recall
    results = await recall_multi(
        trail_managers=[project, team, company],
        query="",  # match all
        limit=50,
    )

    # Should find all three thoughts
    ids = [r[0].thought_id for r in results]
    assert p_record.thought_id in ids
    assert t_record.thought_id in ids
    assert c_record.thought_id in ids

    # Each result has source trail name
    sources = {r[1] for r in results}
    assert "mw" in sources
    assert "mw/eng" in sources
    assert "mw/eng/fava-trail" in sources


@pytest.mark.asyncio
async def test_recall_multi_deduplicates(nested_trail_managers):
    """recall_multi should not return duplicate thoughts."""
    project = nested_trail_managers["project"]

    record = await project.save_thought(
        content="Unique thought.",
        agent_id="test-agent",
    )

    # Pass same manager twice
    results = await recall_multi(
        trail_managers=[project, project],
        query="Unique",
    )

    ids = [r[0].thought_id for r in results]
    assert ids.count(record.thought_id) == 1


@pytest.mark.asyncio
async def test_cross_scope_supersede(nested_trail_managers):
    """supersede with target_trail elevates thought to a different scope."""
    epic = nested_trail_managers["epic"]
    project = nested_trail_managers["project"]

    # Save a finding in the epic scope
    original = await epic.save_thought(
        content="Auth tokens expire too quickly for CI.",
        agent_id="test-agent",
        namespace="observations",
    )

    # Elevate to project scope
    elevated = await epic.supersede(
        original_id=original.thought_id,
        new_content="Auth tokens expire too quickly — affects all services, not just auth-epic.",
        reason="Applies to entire project, not just auth epic",
        agent_id="test-agent",
        target_trail=project,
    )

    # New thought is in project scope
    found_in_project = await project.get_thought(elevated.thought_id)
    assert found_in_project is not None
    assert "all services" in found_in_project.content

    # Original is marked as superseded in epic scope
    original_updated = await epic.get_thought(original.thought_id)
    assert original_updated.is_superseded
    assert original_updated.frontmatter.superseded_by == elevated.thought_id


@pytest.mark.asyncio
async def test_supersede_same_scope_default(trail_manager):
    """supersede without target_trail stays in same scope (backward compat)."""
    record = await trail_manager.save_thought(
        content="Original finding.",
        agent_id="test-agent",
        namespace="observations",
    )

    new_record = await trail_manager.supersede(
        original_id=record.thought_id,
        new_content="Corrected finding.",
        reason="Was wrong about X",
        agent_id="test-agent",
    )

    # New thought in same trail
    found = await trail_manager.get_thought(new_record.thought_id)
    assert found is not None
    assert found.content == "Corrected finding."


@pytest.mark.asyncio
async def test_list_scopes_recursive(nested_trail_managers, tmp_fava_home):
    """list_scopes discovers nested scopes recursively."""
    from fava_trails.tools.navigation import handle_list_scopes

    result = await handle_list_scopes({})
    assert result["status"] == "ok"
    paths = [s["path"] for s in result["scopes"]]
    assert "mw" in paths
    assert "mw/eng" in paths
    assert "mw/eng/fava-trail" in paths
    assert "mw/eng/fava-trail/auth-epic" in paths


@pytest.mark.asyncio
async def test_list_scopes_prefix_filter(nested_trail_managers, tmp_fava_home):
    """list_scopes with prefix filters results."""
    from fava_trails.tools.navigation import handle_list_scopes

    result = await handle_list_scopes({"prefix": "mw/eng/fava-trail"})
    paths = [s["path"] for s in result["scopes"]]
    assert "mw/eng/fava-trail" in paths
    assert "mw/eng/fava-trail/auth-epic" in paths
    assert "mw" not in paths
    assert "mw/eng" not in paths


@pytest.mark.asyncio
async def test_list_scopes_include_stats(nested_trail_managers, tmp_fava_home):
    """list_scopes with include_stats returns thought counts."""
    from fava_trails.tools.navigation import handle_list_scopes

    project = nested_trail_managers["project"]
    await project.save_thought(content="A thought.", agent_id="test")

    result = await handle_list_scopes({"include_stats": True})
    project_scope = next(s for s in result["scopes"] if s["path"] == "mw/eng/fava-trail")
    assert "thought_count" in project_scope
    assert project_scope["thought_count"] >= 1


@pytest.mark.asyncio
async def test_resolve_scope_globs_star(nested_trail_managers, tmp_fava_home):
    """Glob * matches one level only."""
    from fava_trails.config import resolve_scope_globs

    trails_dir = tmp_fava_home / "trails"
    resolved = resolve_scope_globs(trails_dir, ["mw/eng/*"])
    assert "mw/eng/fava-trail" in resolved
    # Should NOT match mw/eng/fava-trail/auth-epic (that's two levels)
    assert "mw/eng/fava-trail/auth-epic" not in resolved


@pytest.mark.asyncio
async def test_resolve_scope_globs_double_star(nested_trail_managers, tmp_fava_home):
    """Glob ** matches any depth."""
    from fava_trails.config import resolve_scope_globs

    trails_dir = tmp_fava_home / "trails"
    resolved = resolve_scope_globs(trails_dir, ["mw/**"])
    assert "mw/eng" in resolved
    assert "mw/eng/fava-trail" in resolved
    assert "mw/eng/fava-trail/auth-epic" in resolved


@pytest.mark.asyncio
async def test_root_level_trail_warning(tmp_fava_home):
    """Writing to a root-level trail should succeed but include a warning."""
    from fava_trails.server import _is_root_level

    assert _is_root_level("scratch")
    assert not _is_root_level("mw/scratch")


@pytest.mark.asyncio
async def test_trail_name_required():
    """_get_trail with None trail_name should raise ValueError."""
    from fava_trails.server import _get_trail

    with pytest.raises(ValueError, match="trail_name is required"):
        await _get_trail(None)

    with pytest.raises(ValueError, match="trail_name is required"):
        await _get_trail("")


@pytest.mark.asyncio
async def test_serialize_thought_includes_metadata_extra():
    """_serialize_thought should include metadata.extra in MCP responses."""
    from fava_trails.models import ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord
    from fava_trails.tools.thought import _serialize_thought

    fm = ThoughtFrontmatter(
        metadata=ThoughtMetadata(
            tags=["test"],
            extra={"quality_score": 0.85, "reviewed": True},
        ),
    )
    record = ThoughtRecord(frontmatter=fm, content="Test content.")
    result = _serialize_thought(record)

    assert "metadata" in result
    assert "extra" in result["metadata"]
    assert result["metadata"]["extra"]["quality_score"] == 0.85
    assert result["metadata"]["extra"]["reviewed"] is True
    assert result["metadata"]["tags"] == ["test"]


@pytest.mark.asyncio
async def test_serialize_thought_omits_empty_metadata():
    """_serialize_thought should omit metadata when all sub-fields are empty."""
    from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
    from fava_trails.tools.thought import _serialize_thought

    fm = ThoughtFrontmatter()
    record = ThoughtRecord(frontmatter=fm, content="Minimal thought.")
    result = _serialize_thought(record)

    assert "metadata" not in result


@pytest.mark.asyncio
async def test_path_traversal_rejected():
    """Path traversal attempts should be rejected."""
    from fava_trails.config import sanitize_scope_path

    with pytest.raises(ValueError, match="Path traversal"):
        sanitize_scope_path("../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal"):
        sanitize_scope_path("mw/../../../etc")

    with pytest.raises(ValueError, match="Path traversal"):
        sanitize_scope_path("mw\\eng")


# ─── on_recall_mix hook ───


def _make_hook_registry_with_on_recall_mix(hooks_dir, reorder=None):
    """Build a HookRegistry with an on_recall_mix hook.

    reorder: if provided, a list of thought_ids to return as the new order.
    """
    import textwrap

    from fava_trails.hook_manifest import HookRegistry
    from fava_trails.models import HookEntry

    if reorder is not None:
        ids_repr = repr(reorder)
        code = f"""
            from fava_trails.hook_types import RecallSelect, Annotate
            async def on_recall_mix(event):
                ordered = {ids_repr}
                # Return only IDs that are in the results
                result_ids = {{t.thought_id for t in event.results}}
                filtered = [uid for uid in ordered if uid in result_ids]
                if filtered:
                    return [RecallSelect(ordered_ulids=filtered, reason="test_reorder"), Annotate({{"mix_fired": True}})]
                return None
        """
    else:
        code = """
            from fava_trails.hook_types import Annotate
            async def on_recall_mix(event):
                return [Annotate({"mix_fired": True, "count": len(event.results)})]
        """

    hook_file = hooks_dir / "mix_hook.py"
    hook_file.write_text(textwrap.dedent(code))

    registry = HookRegistry()
    entry = HookEntry(path="./mix_hook.py", points=["on_recall_mix"])
    registry.load_from_entries([entry], base_dir=hooks_dir)
    return registry


@pytest.mark.asyncio
async def test_recall_multi_fires_on_recall_mix(nested_trail_managers, tmp_path):
    """on_recall_mix hook fires when recall_multi searches multiple trails."""
    from fava_trails.trail import TrailManager
    from fava_trails.vcs.jj_backend import JjBackend

    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()

    company = nested_trail_managers["company"]
    team = nested_trail_managers["team"]

    # Attach hook registry to primary trail (company)
    registry = _make_hook_registry_with_on_recall_mix(hooks_dir)
    company._hooks = registry

    await company.save_thought(content="Company standard A", agent_id="test")
    await team.save_thought(content="Team convention B", agent_id="test")

    results = await recall_multi(
        trail_managers=[company, team],
        query="",
        limit=50,
    )

    pipeline = company.consume_feedback()
    assert pipeline is not None
    assert pipeline.feedback.annotations.get("mix_fired") is True
    assert len(results) >= 2


@pytest.mark.asyncio
async def test_recall_multi_on_recall_mix_reorders(nested_trail_managers, tmp_path):
    """on_recall_mix RecallSelect reorders the merged result list."""
    from fava_trails.trail import TrailManager

    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()

    company = nested_trail_managers["company"]
    team = nested_trail_managers["team"]

    r1 = await company.save_thought(content="First thought", agent_id="test")
    r2 = await team.save_thought(content="Second thought", agent_id="test")

    # Register hook that puts r2 before r1
    registry = _make_hook_registry_with_on_recall_mix(hooks_dir, reorder=[r2.thought_id, r1.thought_id])
    company._hooks = registry

    results = await recall_multi(
        trail_managers=[company, team],
        query="",
        limit=50,
    )

    ids = [r[0].thought_id for r in results]
    assert ids.index(r2.thought_id) < ids.index(r1.thought_id)


@pytest.mark.asyncio
async def test_recall_multi_no_on_recall_mix_hooks(nested_trail_managers):
    """recall_multi works fine when no on_recall_mix hooks are registered."""
    company = nested_trail_managers["company"]
    team = nested_trail_managers["team"]

    await company.save_thought(content="Standard C", agent_id="test")
    results = await recall_multi(trail_managers=[company, team], query="")
    assert any(r[0].content == "Standard C" for r in results)


@pytest.mark.asyncio
async def test_recall_multi_single_trail_skips_mix(nested_trail_managers, tmp_path):
    """on_recall_mix does NOT fire when only a single trail is searched."""
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()

    company = nested_trail_managers["company"]
    registry = _make_hook_registry_with_on_recall_mix(hooks_dir)
    company._hooks = registry

    await company.save_thought(content="Solo thought", agent_id="test")

    await recall_multi(trail_managers=[company], query="")

    # Feedback should NOT have mix_fired (on_recall_mix skipped for single trail)
    pipeline = company.consume_feedback()
    if pipeline is not None:
        assert not pipeline.feedback.annotations.get("mix_fired")

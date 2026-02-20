"""Integration tests for MCP tool handlers via TrailManager."""

import pytest

from fava_trail.models import SourceType


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
    from fava_trail.models import ValidationStatus

    record = await trail_manager.save_thought(content="Decision.", agent_id="test")
    # Manually set to approved by writing to disk
    path = trail_manager._find_thought_path(record.thought_id)
    from fava_trail.models import ThoughtRecord
    loaded = ThoughtRecord.from_markdown(path.read_text())
    loaded.frontmatter.validation_status = ValidationStatus.APPROVED
    path.write_text(loaded.to_markdown())

    with pytest.raises(ValueError, match="frozen"):
        await trail_manager.update_thought(record.thought_id, "Should fail.")


@pytest.mark.asyncio
async def test_update_thought_content_freeze_rejected(trail_manager):
    """update_thought on rejected thought should raise ValueError."""
    from fava_trail.models import ValidationStatus

    record = await trail_manager.save_thought(content="Rejected idea.", agent_id="test")
    path = trail_manager._find_thought_path(record.thought_id)
    from fava_trail.models import ThoughtRecord
    loaded = ThoughtRecord.from_markdown(path.read_text())
    loaded.frontmatter.validation_status = ValidationStatus.REJECTED
    path.write_text(loaded.to_markdown())

    with pytest.raises(ValueError, match="frozen"):
        await trail_manager.update_thought(record.thought_id, "Should fail.")


@pytest.mark.asyncio
async def test_update_thought_content_freeze_tombstoned(trail_manager):
    """update_thought on tombstoned thought should raise ValueError."""
    from fava_trail.models import ValidationStatus

    record = await trail_manager.save_thought(content="Old stale draft.", agent_id="test")
    path = trail_manager._find_thought_path(record.thought_id)
    from fava_trail.models import ThoughtRecord
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

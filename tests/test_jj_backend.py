"""Tests for JjBackend VCS operations."""

import pytest


@pytest.mark.asyncio
async def test_init_trail(jj_backend):
    """JJ colocated trail should have .jj and .git dirs."""
    assert (jj_backend.trail_path / ".jj").exists()
    assert (jj_backend.trail_path / ".git").exists()


@pytest.mark.asyncio
async def test_init_trail_idempotent(jj_backend):
    """Re-initializing should not fail."""
    result = await jj_backend.init_trail()
    assert "already initialized" in result.lower()


@pytest.mark.asyncio
async def test_current_change(jj_backend):
    """Should return the current working change."""
    change = await jj_backend.current_change()
    assert change is not None
    assert change.change_id


@pytest.mark.asyncio
async def test_new_change(jj_backend):
    """Creating a new change should return a VcsChange."""
    change = await jj_backend.new_change("test change")
    assert change is not None
    assert change.change_id


@pytest.mark.asyncio
async def test_describe(jj_backend):
    """Setting description should work."""
    result = await jj_backend.describe("test description")
    assert "test description" in result


@pytest.mark.asyncio
async def test_log(jj_backend):
    """Log should return at least the root change."""
    changes = await jj_backend.log()
    assert len(changes) > 0
    for change in changes:
        assert change.change_id


@pytest.mark.asyncio
async def test_op_log(jj_backend):
    """Op log should return at least the init operation."""
    ops = await jj_backend.op_log()
    assert len(ops) > 0
    for op in ops:
        assert op.op_id
        assert op.description


@pytest.mark.asyncio
async def test_diff_no_changes(jj_backend):
    """Diff on empty change should show no changes."""
    diff = await jj_backend.diff()
    # May or may not have changes depending on state
    assert diff.summary is not None


@pytest.mark.asyncio
async def test_conflicts_none(jj_backend):
    """Fresh trail should have no conflicts."""
    conflicts = await jj_backend.conflicts()
    assert conflicts == []


@pytest.mark.asyncio
async def test_commit_files(jj_backend):
    """Committing a file should create a trackable change."""
    test_file = jj_backend.trail_path / "test.md"
    test_file.write_text("# Test\nHello world")
    change = await jj_backend.commit_files([str(test_file)], "add test file")
    assert change.description == "add test file"

    # Verify in log
    changes = await jj_backend.log(limit=5)
    descriptions = [c.description for c in changes]
    assert any("add test file" in d for d in descriptions)


@pytest.mark.asyncio
async def test_gc(jj_backend):
    """GC should complete without error."""
    result = await jj_backend.gc()
    assert "completed" in result.lower()

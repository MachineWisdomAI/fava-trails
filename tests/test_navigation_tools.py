"""Tests for navigation/lifecycle tool handlers."""

from types import SimpleNamespace

import pytest

from fava_trails.tools.navigation import handle_sync


class _SyncTrail:
    def __init__(self, result):
        self._result = result

    async def sync(self):
        return self._result


@pytest.mark.asyncio
async def test_handle_sync_blocks_dirty_working_copy():
    """sync should tell agents local files remain dirty instead of saying ok."""
    result = SimpleNamespace(
        success=False,
        has_conflicts=False,
        has_dirty_working_copy=True,
        dirty_paths=["trails/mwai/eng/WisdomLoop/thoughts/drafts/dirty.md"],
        has_case_collisions=False,
        case_collisions=[],
        summary="Local working copy has uncommitted changes",
    )

    payload = await handle_sync(_SyncTrail(result), {})

    assert payload["status"] == "blocked"
    assert "dirty" in payload["message"].lower()
    assert payload["dirty_paths"] == result.dirty_paths


@pytest.mark.asyncio
async def test_handle_sync_blocks_case_collisions():
    """sync should surface tracked path case collisions as a repair blocker."""
    result = SimpleNamespace(
        success=False,
        has_conflicts=False,
        has_dirty_working_copy=False,
        dirty_paths=[],
        has_case_collisions=True,
        case_collisions=[
            [
                "trails/mwai/eng/WisdomLoop/.fava-trails.yaml",
                "trails/mwai/eng/wisdomloop/.fava-trails.yaml",
            ]
        ],
        summary="Tracked paths differ only by case",
    )

    payload = await handle_sync(_SyncTrail(result), {})

    assert payload["status"] == "blocked"
    assert "case" in payload["message"].lower()
    assert payload["case_collisions"] == result.case_collisions

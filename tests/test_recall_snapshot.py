"""A read response must not mix committed versions across selected scopes."""

from __future__ import annotations

import pytest

from fava_trails import governance
from fava_trails.hook_manifest import HookRegistry, HookSpec
from fava_trails.models import SourceType
from fava_trails.rich_views import generate_reader_for_scopes
from fava_trails.trail import recall_multi
from fava_trails.trust_gate import TrustResult


def approval():
    return TrustResult(verdict="approve", reasoning="Synthetic acceptance", reviewer="fixture")


async def replacement_pair(managers):
    first, second = managers["team"], managers["project"]
    original = await first.save_thought("Original decision", source_type=SourceType.DECISION, agent_id="alice")
    await first.propose_truth(original.thought_id, approval())
    successor = await first.supersede(
        original.thought_id,
        "Replacement decision",
        reason="Synthetic correction",
        agent_id="alice",
        target_trail=second,
    )
    return first, second, original, successor


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_recall_keeps_one_current_version_when_approval_lands_between_scopes(
    nested_trail_managers, monkeypatch, reverse
):
    first, second, original, successor = await replacement_pair(nested_trail_managers)
    selected = [second, first] if reverse else [first, second]
    first_recall = selected[0].recall

    async def approve_between_scope_reads(**kwargs):
        result = await first_recall(**kwargs)
        await second.propose_truth(successor.thought_id, approval())
        return result

    monkeypatch.setattr(selected[0], "recall", approve_between_scope_reads)
    result = await recall_multi(selected)
    assert [(record.thought_id, scope) for record, scope in result] == [(original.thought_id, first.trail_name)]

    # The next request observes the completed transaction, not a cached old view.
    monkeypatch.setattr(selected[0], "recall", first_recall)
    result = await recall_multi(selected)
    assert [(record.thought_id, scope) for record, scope in result] == [(successor.thought_id, second.trail_name)]


@pytest.mark.asyncio
async def test_per_scope_and_mix_hooks_share_the_response_snapshot(nested_trail_managers):
    first, second, original, successor = await replacement_pair(nested_trail_managers)
    observed = []
    committed = False

    async def inspect_during_recall(event):
        nonlocal committed
        if not committed:
            committed = True
            await second.propose_truth(successor.thought_id, approval())
        nested = await event.context.recall()
        observed.append((event.lifecycle_point, event.trail_name, [record.thought_id for record in nested]))

    registry = HookRegistry()
    registry._hooks = {
        point: [HookSpec(name=point, fn=inspect_during_recall, timeout=10)] for point in ("on_recall", "on_recall_mix")
    }
    first._hooks = second._hooks = registry
    result = await recall_multi([first, second])

    assert [record.thought_id for record, _ in result] == [original.thought_id]
    assert observed == [
        ("on_recall", first.trail_name, [original.thought_id]),
        ("on_recall", second.trail_name, []),
        ("on_recall_mix", first.trail_name, [original.thought_id]),
    ]


@pytest.mark.asyncio
async def test_reader_uses_one_committed_view_for_all_scopes(nested_trail_managers, monkeypatch, tmp_path):
    first, second, original, successor = await replacement_pair(nested_trail_managers)
    trails_dir = first.vcs.repo_root / "trails"
    before = governance.snapshot_texts(trails_dir)
    await second.propose_truth(successor.thought_id, approval())
    after = governance.snapshot_texts(trails_dir)
    reads = 0

    def capture_committed_version(_trails_dir):
        nonlocal reads
        reads += 1
        return before if reads == 1 else after

    monkeypatch.setattr(governance, "snapshot_texts", capture_committed_version)
    result = generate_reader_for_scopes(
        trails_dir=trails_dir,
        scopes=[first.trail_name, second.trail_name],
        output_dir=tmp_path / "reader",
    )
    assert result.thought_count == 1
    assert result.routes == (f"/{first.trail_name}/original-decision/",)
    assert (tmp_path / "reader/src/pages/id" / f"{original.thought_id}.md").is_file()
    assert not (tmp_path / "reader/src/pages/id" / f"{successor.thought_id}.md").exists()
    assert reads == 1

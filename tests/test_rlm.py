"""Tests for RLM MapReduce Hooks (protocols/rlm).

Coverage:
  - configure(): stores config, resets _BATCH_COUNTS
  - before_save(): validation for rlm-mapper tagged thoughts
  - after_save(): batch progress counter, REDUCE READY signaling
  - on_recall(): deterministic mapper ordering
  - Pipeline integration via HookRegistry + run_pipeline
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import fava_trails.protocols.rlm as rlm
from fava_trails.hook_types import (
    Advise,
    AfterSaveEvent,
    Annotate,
    BeforeSaveEvent,
    OnRecallEvent,
    RecallSelect,
    Reject,
)
from fava_trails.models import ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord

# --- Helpers ---


def _make_thought(
    content: str = "This is mapper output with enough text.",
    thought_id: str = "ULID1",
    tags: list[str] | None = None,
    confidence: float = 0.5,
    extra: dict | None = None,
    created_at: datetime | None = None,
) -> ThoughtRecord:
    """Create a ThoughtRecord for testing."""
    meta = ThoughtMetadata(tags=tags or [], extra=extra or {})
    fm_kwargs: dict = {"thought_id": thought_id, "confidence": confidence, "metadata": meta}
    if created_at is not None:
        fm_kwargs["created_at"] = created_at
    fm = ThoughtFrontmatter(**fm_kwargs)
    return ThoughtRecord(frontmatter=fm, content=content)


@pytest.fixture(autouse=True)
def _reset_rlm():
    """Reset RLM module state between tests."""
    rlm._CONFIG = {}
    rlm._BATCH_COUNTS = {}
    yield
    rlm._CONFIG = {}
    rlm._BATCH_COUNTS = {}


def _configure(**overrides):
    """Configure RLM with defaults + overrides."""
    config = {
        "expected_mappers": 3,
        "min_mapper_output_chars": 20,
    }
    config.update(overrides)
    rlm.configure(config)


# --- TestConfigure ---


class TestConfigure:
    def test_stores_config(self):
        """configure() stores config in _CONFIG."""
        rlm.configure({"expected_mappers": 5, "min_mapper_output_chars": 50})
        assert rlm._CONFIG["expected_mappers"] == 5
        assert rlm._CONFIG["min_mapper_output_chars"] == 50

    def test_resets_batch_counts(self):
        """configure() resets _BATCH_COUNTS to empty."""
        rlm._BATCH_COUNTS = {"trail": {"batch1": {"mapper1"}}}
        rlm.configure({"expected_mappers": 3})
        assert rlm._BATCH_COUNTS == {}

    def test_defaults_applied(self):
        """Default values: expected_mappers=0, min_mapper_output_chars=20."""
        rlm.configure({})
        assert rlm._CONFIG.get("expected_mappers", 0) == 0
        assert rlm._CONFIG.get("min_mapper_output_chars", 20) == 20

    def test_reconfigure_resets_existing_counts(self):
        """Calling configure() again resets accumulated batch counts."""
        _configure(expected_mappers=3)
        rlm._BATCH_COUNTS = {"trail/a": {"b1": {"m1", "m2"}}}
        rlm.configure({"expected_mappers": 5})
        assert rlm._BATCH_COUNTS == {}


# --- TestBeforeSave ---


class TestBeforeSave:
    @pytest.mark.asyncio
    async def test_no_thought_returns_none(self):
        """Event without thought passes through."""
        _configure()
        event = BeforeSaveEvent(trail_name="t")
        result = await rlm.before_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_mapper_thought_passes_through(self):
        """Thoughts without rlm-mapper tag are not validated."""
        _configure()
        thought = _make_thought(tags=["some-other-tag"], extra={"mapper_id": "m1"})
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await rlm.before_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_mapper_thought_passes(self):
        """Valid mapper thought with mapper_id, batch_id, and sufficient content passes."""
        _configure(min_mapper_output_chars=10)
        thought = _make_thought(
            content="x" * 30,
            tags=["rlm-mapper"],
            extra={"mapper_id": "m1", "batch_id": "b1"},
        )
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await rlm.before_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_mapper_id_rejects(self):
        """Mapper thought missing mapper_id is rejected."""
        _configure()
        thought = _make_thought(
            content="x" * 30,
            tags=["rlm-mapper"],
            extra={"batch_id": "b1"},  # no mapper_id
        )
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await rlm.before_save(event)
        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Reject)
        assert result[0].code == "rlm_missing_mapper_id"

    @pytest.mark.asyncio
    async def test_missing_batch_id_advises(self):
        """Mapper thought missing batch_id gets a non-blocking advisory."""
        _configure(min_mapper_output_chars=10)
        thought = _make_thought(
            content="x" * 30,
            tags=["rlm-mapper"],
            extra={"mapper_id": "m1"},  # no batch_id
        )
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await rlm.before_save(event)
        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Advise)
        assert result[0].code == "rlm_missing_batch_id"

    @pytest.mark.asyncio
    async def test_content_too_short_rejects(self):
        """Mapper output below min_mapper_output_chars is rejected."""
        _configure(min_mapper_output_chars=50)
        thought = _make_thought(
            content="short",
            tags=["rlm-mapper"],
            extra={"mapper_id": "m1", "batch_id": "b1"},
        )
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await rlm.before_save(event)
        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Reject)
        assert result[0].code == "rlm_mapper_too_short"

    @pytest.mark.asyncio
    async def test_mapper_id_checked_before_content_length(self):
        """mapper_id check takes priority over content length check."""
        _configure(min_mapper_output_chars=5)
        thought = _make_thought(
            content="x",  # too short
            tags=["rlm-mapper"],
            extra={"batch_id": "b1"},  # no mapper_id
        )
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await rlm.before_save(event)
        assert result is not None
        assert isinstance(result[0], Reject)
        assert result[0].code == "rlm_missing_mapper_id"


# --- TestAfterSave ---


class TestAfterSave:
    @pytest.mark.asyncio
    async def test_no_thought_returns_none(self):
        """Event without thought returns None."""
        _configure()
        event = AfterSaveEvent(trail_name="t")
        result = await rlm.after_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_mapper_thought_returns_none(self):
        """Non-mapper thoughts are ignored."""
        _configure()
        thought = _make_thought(tags=["reducer"], extra={"mapper_id": "m1", "batch_id": "b1"})
        event = AfterSaveEvent(trail_name="t", thought=thought)
        result = await rlm.after_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_mapper_id_returns_none(self):
        """Mapper thought without mapper_id is silently skipped."""
        _configure()
        thought = _make_thought(tags=["rlm-mapper"], extra={"batch_id": "b1"})
        event = AfterSaveEvent(trail_name="t", thought=thought)
        result = await rlm.after_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_batch_id_returns_none(self):
        """Mapper thought without batch_id is silently skipped."""
        _configure()
        thought = _make_thought(tags=["rlm-mapper"], extra={"mapper_id": "m1"})
        event = AfterSaveEvent(trail_name="t", thought=thought)
        result = await rlm.after_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_progress_tracked(self):
        """Mapper saves increment batch count and return progress advisory."""
        _configure(expected_mappers=3)
        thought = _make_thought(
            tags=["rlm-mapper"],
            extra={"mapper_id": "m1", "batch_id": "b1"},
        )
        event = AfterSaveEvent(trail_name="trail/a", thought=thought)
        result = await rlm.after_save(event)

        assert result is not None
        advise = [a for a in result if isinstance(a, Advise)][0]
        assert advise.code == "rlm_mapper_progress"

        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_batch_count"] == 1
        assert annotate.values["rlm_expected_mappers"] == 3
        assert annotate.values["rlm_reduce_ready"] is False

    @pytest.mark.asyncio
    async def test_reduce_ready_signaled(self):
        """REDUCE READY is signaled when all expected mappers have reported."""
        _configure(expected_mappers=2)

        for mapper_id in ["m1", "m2"]:
            thought = _make_thought(
                tags=["rlm-mapper"],
                extra={"mapper_id": mapper_id, "batch_id": "b1"},
            )
            event = AfterSaveEvent(trail_name="t", thought=thought)
            result = await rlm.after_save(event)

        # Result from the last mapper
        assert result is not None
        advise = [a for a in result if isinstance(a, Advise)][0]
        assert advise.code == "rlm_reduce_ready"
        assert "REDUCE READY" in advise.message

        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_reduce_ready"] is True

    @pytest.mark.asyncio
    async def test_batch_reset_after_reduce_ready(self):
        """After REDUCE READY, the batch counter resets for the next cycle."""
        _configure(expected_mappers=2)

        for mapper_id in ["m1", "m2"]:
            thought = _make_thought(
                tags=["rlm-mapper"],
                extra={"mapper_id": mapper_id, "batch_id": "b1"},
            )
            event = AfterSaveEvent(trail_name="t", thought=thought)
            await rlm.after_save(event)

        # Batch should be reset; add m1 again for a new reduce cycle
        thought = _make_thought(
            tags=["rlm-mapper"],
            extra={"mapper_id": "m1", "batch_id": "b1"},
        )
        event = AfterSaveEvent(trail_name="t", thought=thought)
        result = await rlm.after_save(event)

        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_batch_count"] == 1  # reset and started again
        assert annotate.values["rlm_reduce_ready"] is False

    @pytest.mark.asyncio
    async def test_duplicate_mapper_id_not_double_counted(self):
        """Same mapper_id in same batch is deduplicated."""
        _configure(expected_mappers=3)

        for _ in range(3):
            thought = _make_thought(
                tags=["rlm-mapper"],
                extra={"mapper_id": "m1", "batch_id": "b1"},
            )
            event = AfterSaveEvent(trail_name="t", thought=thought)
            result = await rlm.after_save(event)

        # Should still be count=1 (deduped), not REDUCE READY
        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_batch_count"] == 1
        assert annotate.values["rlm_reduce_ready"] is False

    @pytest.mark.asyncio
    async def test_expected_mappers_zero_no_reduce_ready(self):
        """When expected_mappers=0, REDUCE READY is never signaled."""
        _configure(expected_mappers=0)
        thought = _make_thought(
            tags=["rlm-mapper"],
            extra={"mapper_id": "m1", "batch_id": "b1"},
        )
        event = AfterSaveEvent(trail_name="t", thought=thought)
        result = await rlm.after_save(event)

        assert result is not None
        advise = [a for a in result if isinstance(a, Advise)]
        assert all(a.code != "rlm_reduce_ready" for a in advise)

    @pytest.mark.asyncio
    async def test_separate_scopes_tracked_independently(self):
        """Batches in different scopes (trail_names) are independent."""
        _configure(expected_mappers=2)

        for trail, mapper in [("trail/a", "m1"), ("trail/b", "m1")]:
            thought = _make_thought(
                tags=["rlm-mapper"],
                extra={"mapper_id": mapper, "batch_id": "b1"},
            )
            event = AfterSaveEvent(trail_name=trail, thought=thought)
            result = await rlm.after_save(event)

        # Each trail only has 1 mapper — not REDUCE READY
        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_batch_count"] == 1
        assert annotate.values["rlm_reduce_ready"] is False

    @pytest.mark.asyncio
    async def test_concurrent_saves_via_asyncio(self):
        """Concurrent mapper saves are handled without data loss."""
        _configure(expected_mappers=5)

        async def _save_mapper(mapper_id: str) -> list[Any] | None:
            thought = _make_thought(
                tags=["rlm-mapper"],
                extra={"mapper_id": mapper_id, "batch_id": "concurrent-batch"},
            )
            event = AfterSaveEvent(trail_name="t", thought=thought)
            return await rlm.after_save(event)

        results = await asyncio.gather(*[_save_mapper(f"m{i}") for i in range(5)])

        # All 5 should have produced results
        assert all(r is not None for r in results)

        # Final batch count should be 5 (reset after REDUCE READY)
        reduce_ready_count = sum(
            1 for r in results
            if any(
                isinstance(a, Advise) and a.code == "rlm_reduce_ready"
                for a in r
            )
        )
        assert reduce_ready_count == 1

    @pytest.mark.asyncio
    async def test_separate_batches_tracked_independently(self):
        """Different batch_ids are tracked independently within same scope."""
        _configure(expected_mappers=2)

        for batch_id in ["batch-A", "batch-B"]:
            thought = _make_thought(
                tags=["rlm-mapper"],
                extra={"mapper_id": "m1", "batch_id": batch_id},
            )
            event = AfterSaveEvent(trail_name="t", thought=thought)
            result = await rlm.after_save(event)

        # batch-B has only 1 mapper — not REDUCE READY
        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_batch_id"] == "batch-B"
        assert annotate.values["rlm_batch_count"] == 1
        assert annotate.values["rlm_reduce_ready"] is False


# --- TestOnRecall ---


class TestOnRecall:
    @pytest.mark.asyncio
    async def test_no_results_returns_none(self):
        """Empty results returns None."""
        _configure()
        event = OnRecallEvent(trail_name="t", results=[])
        result = await rlm.on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_rlm_mapper_in_scope_tags_returns_none(self):
        """When scope tags don't include rlm-mapper, hook is inactive."""
        _configure()
        t1 = _make_thought(tags=["rlm-mapper"], extra={"mapper_id": "m1"})
        event = OnRecallEvent(
            trail_name="t",
            results=[t1],
            scope={"tags": ["some-other-filter"]},
        )
        result = await rlm.on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_scope_returns_none(self):
        """When scope is None (no filter), hook is inactive."""
        _configure()
        t1 = _make_thought(tags=["rlm-mapper"], extra={"mapper_id": "m1"})
        event = OnRecallEvent(trail_name="t", results=[t1], scope=None)
        result = await rlm.on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_scope_tags_returns_none(self):
        """When scope tags is empty list, hook is inactive."""
        _configure()
        t1 = _make_thought(tags=["rlm-mapper"], extra={"mapper_id": "m1"})
        event = OnRecallEvent(trail_name="t", results=[t1], scope={"tags": []})
        result = await rlm.on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_mapper_results_sorted_by_mapper_id(self):
        """Mapper results are sorted by (mapper_id, created_at) deterministically."""
        _configure()
        base_time = datetime(2025, 1, 1, tzinfo=UTC)
        t_c = _make_thought(
            thought_id="C", tags=["rlm-mapper"],
            extra={"mapper_id": "mapper-c"},
            created_at=base_time,
        )
        t_a = _make_thought(
            thought_id="A", tags=["rlm-mapper"],
            extra={"mapper_id": "mapper-a"},
            created_at=base_time,
        )
        t_b = _make_thought(
            thought_id="B", tags=["rlm-mapper"],
            extra={"mapper_id": "mapper-b"},
            created_at=base_time,
        )
        event = OnRecallEvent(
            trail_name="t",
            results=[t_c, t_a, t_b],
            scope={"tags": ["rlm-mapper"]},
        )
        result = await rlm.on_recall(event)
        assert result is not None

        select = [a for a in result if isinstance(a, RecallSelect)][0]
        assert select.ordered_ulids == ["A", "B", "C"]
        assert select.reason == "rlm_mapper_deterministic_order"

    @pytest.mark.asyncio
    async def test_same_mapper_id_sorted_by_created_at(self):
        """Same mapper_id: secondary sort by created_at (earlier first)."""
        _configure()
        base_time = datetime(2025, 1, 1, tzinfo=UTC)
        t_later = _make_thought(
            thought_id="LATER", tags=["rlm-mapper"],
            extra={"mapper_id": "m1"},
            created_at=base_time + timedelta(hours=1),
        )
        t_earlier = _make_thought(
            thought_id="EARLIER", tags=["rlm-mapper"],
            extra={"mapper_id": "m1"},
            created_at=base_time,
        )
        event = OnRecallEvent(
            trail_name="t",
            results=[t_later, t_earlier],
            scope={"tags": ["rlm-mapper"]},
        )
        result = await rlm.on_recall(event)
        assert result is not None

        select = [a for a in result if isinstance(a, RecallSelect)][0]
        assert select.ordered_ulids == ["EARLIER", "LATER"]

    @pytest.mark.asyncio
    async def test_annotate_includes_counts_and_mapper_ids(self):
        """Annotate includes mapper count, mapper_ids list, and total count."""
        _configure()
        base_time = datetime(2025, 1, 1, tzinfo=UTC)
        t1 = _make_thought(
            thought_id="T1", tags=["rlm-mapper"],
            extra={"mapper_id": "m1"}, created_at=base_time,
        )
        t2 = _make_thought(
            thought_id="T2", tags=["rlm-mapper"],
            extra={"mapper_id": "m2"}, created_at=base_time,
        )
        event = OnRecallEvent(
            trail_name="t",
            results=[t1, t2],
            scope={"tags": ["rlm-mapper"]},
        )
        result = await rlm.on_recall(event)
        assert result is not None

        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_mapper_count"] == 2
        assert annotate.values["rlm_total_count"] == 2
        assert set(annotate.values["rlm_mapper_ids"]) == {"m1", "m2"}

    @pytest.mark.asyncio
    async def test_non_mapper_results_appended_after_mappers(self):
        """Non-mapper results are appended after sorted mapper results."""
        _configure()
        base_time = datetime(2025, 1, 1, tzinfo=UTC)
        t_reducer = _make_thought(thought_id="REDUCER", tags=["rlm-reducer"])
        t_mapper_b = _make_thought(
            thought_id="MB", tags=["rlm-mapper"],
            extra={"mapper_id": "mapper-b"}, created_at=base_time,
        )
        t_mapper_a = _make_thought(
            thought_id="MA", tags=["rlm-mapper"],
            extra={"mapper_id": "mapper-a"}, created_at=base_time,
        )
        event = OnRecallEvent(
            trail_name="t",
            results=[t_reducer, t_mapper_b, t_mapper_a],
            scope={"tags": ["rlm-mapper"]},
        )
        result = await rlm.on_recall(event)
        assert result is not None

        select = [a for a in result if isinstance(a, RecallSelect)][0]
        # Mappers first (sorted), reducer last
        assert select.ordered_ulids == ["MA", "MB", "REDUCER"]

        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["rlm_mapper_count"] == 2
        assert annotate.values["rlm_total_count"] == 3


# --- TestPipelineIntegration ---


class TestPipelineIntegration:
    """Test RLM hooks through the actual pipeline engine."""

    @pytest.mark.asyncio
    async def test_before_save_pipeline_rejects_missing_mapper_id(self):
        """Pipeline rejects mapper thought missing mapper_id."""
        from fava_trails.hook_manifest import HookRegistry, HookSpec
        from fava_trails.hook_pipeline import run_pipeline

        _configure(min_mapper_output_chars=5)
        registry = HookRegistry()
        spec = HookSpec(
            name="before_save",
            fn=rlm.before_save,
            fail_mode="closed",
            timeout=5.0,
            order=15,
            source="fava_trails.protocols.rlm",
        )
        registry._hooks.setdefault("before_save", []).append(spec)

        thought = _make_thought(
            content="x" * 30,
            tags=["rlm-mapper"],
            extra={"batch_id": "b1"},  # missing mapper_id
        )
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await run_pipeline(registry, event)

        assert not result.feedback.accepted

    @pytest.mark.asyncio
    async def test_after_save_pipeline_tracks_progress(self):
        """Pipeline runs after_save and accumulates Advise + Annotate."""
        from fava_trails.hook_manifest import HookRegistry, HookSpec
        from fava_trails.hook_pipeline import run_pipeline

        _configure(expected_mappers=3)
        registry = HookRegistry()
        spec = HookSpec(
            name="after_save",
            fn=rlm.after_save,
            fail_mode="open",
            timeout=5.0,
            order=15,
            source="fava_trails.protocols.rlm",
        )
        registry._hooks.setdefault("after_save", []).append(spec)

        thought = _make_thought(
            tags=["rlm-mapper"],
            extra={"mapper_id": "m1", "batch_id": "b1"},
        )
        event = AfterSaveEvent(trail_name="t", thought=thought)
        result = await run_pipeline(registry, event)

        assert result.feedback.accepted
        assert result.feedback.annotations.get("rlm_batch_count") == 1

    @pytest.mark.asyncio
    async def test_on_recall_pipeline_reorders_results(self):
        """Pipeline runs on_recall and RecallSelect reorders thoughts."""
        from fava_trails.hook_manifest import HookRegistry, HookSpec
        from fava_trails.hook_pipeline import run_pipeline

        _configure()
        registry = HookRegistry()
        spec = HookSpec(
            name="on_recall",
            fn=rlm.on_recall,
            fail_mode="open",
            timeout=5.0,
            order=15,
            source="fava_trails.protocols.rlm",
        )
        registry._hooks.setdefault("on_recall", []).append(spec)

        base_time = datetime(2025, 1, 1, tzinfo=UTC)
        t_b = _make_thought(
            thought_id="B", tags=["rlm-mapper"],
            extra={"mapper_id": "mapper-b"}, created_at=base_time,
        )
        t_a = _make_thought(
            thought_id="A", tags=["rlm-mapper"],
            extra={"mapper_id": "mapper-a"}, created_at=base_time,
        )
        event = OnRecallEvent(
            trail_name="t",
            results=[t_b, t_a],
            scope={"tags": ["rlm-mapper"]},
        )
        result = await run_pipeline(registry, event)

        assert result.feedback.accepted
        # Annotations should show mapper count
        assert result.feedback.annotations.get("rlm_mapper_count") == 2

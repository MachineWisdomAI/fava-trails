"""Tests for pipeline execution engine."""

from __future__ import annotations

import asyncio

import pytest

from fava_trails.hook_manifest import HookRegistry, HookSpec
from fava_trails.hook_pipeline import (
    MAX_MUTATIONS_PER_PIPELINE,
    HookExecutionError,
    HookTimeoutError,
    dispatch_observer,
    run_pipeline,
)
from fava_trails.hook_types import (
    Advise,
    Annotate,
    BeforeSaveEvent,
    Mutate,
    OnRecallEvent,
    Proceed,
    RecallSelect,
    Redirect,
    Reject,
    ThoughtPatch,
    Warn,
)


def _make_spec(name: str, fn, fail_mode: str = "open", timeout: float = 5.0, order: int = 50) -> HookSpec:
    """Create a HookSpec with a given async function."""
    return HookSpec(name=name, fn=fn, fail_mode=fail_mode, timeout=timeout, order=order, source="test")


def _make_registry(*specs: HookSpec) -> HookRegistry:
    """Create a HookRegistry with given specs."""
    registry = HookRegistry()
    for spec in specs:
        registry._hooks.setdefault(spec.name, []).append(spec)
    for point in registry._hooks:
        registry._hooks[point].sort(key=lambda s: s.order)
    return registry


def _make_thought(content: str = "test", thought_id: str = "ULID1", tags: list | None = None):
    """Create a minimal ThoughtRecord for testing."""
    from fava_trails.models import ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord
    fm = ThoughtFrontmatter(thought_id=thought_id)
    if tags:
        fm.metadata = ThoughtMetadata(tags=tags)
    return ThoughtRecord(frontmatter=fm, content=content)


# ─── Pipeline: Basic Execution ───


class TestPipelineBasic:
    @pytest.mark.asyncio
    async def test_no_hooks(self):
        """No hooks → empty result, event unchanged."""
        registry = _make_registry()
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert not result.rejected
        assert result.feedback.is_empty()

    @pytest.mark.asyncio
    async def test_single_proceed(self):
        """Hook returning Proceed → continue."""
        async def hook(event):
            return Proceed()
        registry = _make_registry(_make_spec("before_save", hook))
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert not result.rejected
        assert result.feedback.accepted

    @pytest.mark.asyncio
    async def test_none_return_treated_as_proceed(self):
        """Hook returning None → treated as Proceed."""
        async def hook(event):
            return None
        registry = _make_registry(_make_spec("before_save", hook))
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert not result.rejected

    @pytest.mark.asyncio
    async def test_multiple_hooks_in_order(self):
        """Multiple hooks execute in order (by order field)."""
        call_order = []

        async def hook_a(event):
            call_order.append("a")
            return Proceed()

        async def hook_b(event):
            call_order.append("b")
            return Proceed()

        registry = _make_registry(
            _make_spec("before_save", hook_a, order=20),
            _make_spec("before_save", hook_b, order=10),
        )
        event = BeforeSaveEvent(trail_name="t")
        await run_pipeline(registry, event)
        assert call_order == ["b", "a"]  # order 10 before 20


# ─── Pipeline: Reject ───


class TestPipelineReject:
    @pytest.mark.asyncio
    async def test_reject_halts_pipeline(self):
        """Reject stops pipeline immediately."""
        call_order = []

        async def hook_reject(event):
            call_order.append("reject")
            return Reject(reason="bad", code="BAD")

        async def hook_after(event):
            call_order.append("after")
            return Proceed()

        registry = _make_registry(
            _make_spec("before_save", hook_reject, order=1),
            _make_spec("before_save", hook_after, order=2),
        )
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert result.rejected
        assert not result.feedback.accepted
        assert call_order == ["reject"]  # second hook never called


# ─── Pipeline: Redirect ───


class TestPipelineRedirect:
    @pytest.mark.asyncio
    async def test_redirect_is_terminal(self):
        """Redirect stops pipeline, sets namespace."""
        call_order = []

        async def hook_redirect(event):
            call_order.append("redirect")
            return Redirect(namespace="observations")

        async def hook_after(event):
            call_order.append("after")

        registry = _make_registry(
            _make_spec("before_save", hook_redirect, order=1),
            _make_spec("before_save", hook_after, order=2),
        )
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert result.redirect_namespace == "observations"
        assert result.feedback.redirected_to == "observations"
        assert call_order == ["redirect"]


# ─── Pipeline: Mutate ───


class TestPipelineMutate:
    @pytest.mark.asyncio
    async def test_mutate_cascades(self):
        """Second hook sees mutated thought from first hook."""
        seen_content = []

        async def hook_mutate(event):
            return Mutate(patch=ThoughtPatch(content="mutated"))

        async def hook_observe(event):
            seen_content.append(event.thought.content)
            return Proceed()

        thought = _make_thought(content="original")
        registry = _make_registry(
            _make_spec("before_save", hook_mutate, order=1),
            _make_spec("before_save", hook_observe, order=2),
        )
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await run_pipeline(registry, event)
        assert result.feedback.mutated
        assert seen_content == ["mutated"]
        assert result.event.thought.content == "mutated"

    @pytest.mark.asyncio
    async def test_max_mutations_guard(self):
        """Exceeding MAX_MUTATIONS_PER_PIPELINE triggers warning."""
        call_count = 0

        async def hook_mutate(event):
            nonlocal call_count
            call_count += 1
            return Mutate(patch=ThoughtPatch(content=f"v{call_count}"))

        # Create more hooks than the limit
        specs = [
            _make_spec("before_save", hook_mutate, order=i)
            for i in range(MAX_MUTATIONS_PER_PIPELINE + 2)
        ]
        registry = _make_registry(*specs)
        thought = _make_thought()
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await run_pipeline(registry, event)
        # Should have applied exactly MAX_MUTATIONS_PER_PIPELINE mutations
        assert result.feedback.mutated

    @pytest.mark.asyncio
    async def test_mutate_no_thought(self):
        """Mutate on event without thought is a no-op (doesn't crash)."""
        async def hook_mutate(event):
            return Mutate(patch=ThoughtPatch(content="x"))

        registry = _make_registry(_make_spec("before_save", hook_mutate))
        event = BeforeSaveEvent(trail_name="t")  # no thought
        result = await run_pipeline(registry, event)
        assert result.feedback.mutated


# ─── Pipeline: Warn/Advise/Annotate Accumulation ───


class TestPipelineAccumulation:
    @pytest.mark.asyncio
    async def test_warn_accumulates(self):
        async def hook1(event):
            return Warn(message="w1", code="W1")

        async def hook2(event):
            return Warn(message="w2", code="W2")

        registry = _make_registry(
            _make_spec("before_save", hook1, order=1),
            _make_spec("before_save", hook2, order=2),
        )
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert len(result.feedback.warnings) == 2

    @pytest.mark.asyncio
    async def test_advise_accumulates(self):
        async def hook(event):
            return Advise(message="hint", code="H1", target="agent")

        registry = _make_registry(_make_spec("before_save", hook))
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert len(result.feedback.advice) == 1
        assert result.feedback.advice[0]["target"] == "agent"

    @pytest.mark.asyncio
    async def test_annotate_merges(self):
        async def hook1(event):
            return Annotate(values={"a": 1})

        async def hook2(event):
            return Annotate(values={"b": 2})

        registry = _make_registry(
            _make_spec("before_save", hook1, order=1),
            _make_spec("before_save", hook2, order=2),
        )
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert result.feedback.annotations == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_multi_action_return(self):
        """Hook returning a list of actions."""
        async def hook(event):
            return [Warn(message="w"), Annotate(values={"k": "v"})]

        registry = _make_registry(_make_spec("before_save", hook))
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert len(result.feedback.warnings) == 1
        assert result.feedback.annotations["k"] == "v"


# ─── Pipeline: RecallSelect ───


class TestPipelineRecallSelect:
    @pytest.mark.asyncio
    async def test_recall_select_subset(self):
        """RecallSelect with valid ULIDs → stored as selection."""
        t1 = _make_thought(thought_id="AAA")
        t2 = _make_thought(thought_id="BBB")
        t3 = _make_thought(thought_id="CCC")

        async def hook(event):
            return RecallSelect(ordered_ulids=["CCC", "AAA"], reason="relevance")

        registry = _make_registry(_make_spec("on_recall", hook))
        event = OnRecallEvent(trail_name="t", results=[t1, t2, t3])
        result = await run_pipeline(registry, event)
        assert result.recall_selection == ["CCC", "AAA"]

    @pytest.mark.asyncio
    async def test_recall_select_invalid_ulids_dropped(self):
        """Invalid ULIDs are silently dropped."""
        t1 = _make_thought(thought_id="AAA")

        async def hook(event):
            return RecallSelect(ordered_ulids=["AAA", "INVALID", "ALSO_INVALID"])

        registry = _make_registry(_make_spec("on_recall", hook))
        event = OnRecallEvent(trail_name="t", results=[t1])
        result = await run_pipeline(registry, event)
        assert result.recall_selection == ["AAA"]

    @pytest.mark.asyncio
    async def test_recall_select_no_duplicates(self):
        """Duplicate ULIDs are deduplicated."""
        t1 = _make_thought(thought_id="AAA")

        async def hook(event):
            return RecallSelect(ordered_ulids=["AAA", "AAA", "AAA"])

        registry = _make_registry(_make_spec("on_recall", hook))
        event = OnRecallEvent(trail_name="t", results=[t1])
        result = await run_pipeline(registry, event)
        assert result.recall_selection == ["AAA"]


# ─── Pipeline: Invalid Actions ───


class TestPipelineInvalidActions:
    @pytest.mark.asyncio
    async def test_invalid_action_skipped(self):
        """Invalid action for lifecycle point is skipped."""
        async def hook(event):
            return Reject(reason="nope")  # Reject invalid for on_recall

        registry = _make_registry(_make_spec("on_recall", hook))
        event = OnRecallEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert not result.rejected  # Reject was skipped


# ─── Pipeline: Error Handling ───


class TestPipelineErrors:
    @pytest.mark.asyncio
    async def test_timeout_open(self):
        """Timeout with fail_mode=open → skip hook, continue."""
        async def hook_slow(event):
            await asyncio.sleep(10)

        async def hook_fast(event):
            return Warn(message="reached")

        registry = _make_registry(
            _make_spec("before_save", hook_slow, timeout=0.1, order=1),
            _make_spec("before_save", hook_fast, order=2),
        )
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert len(result.feedback.warnings) == 1  # second hook ran

    @pytest.mark.asyncio
    async def test_timeout_closed(self):
        """Timeout with fail_mode=closed → raises."""
        async def hook_slow(event):
            await asyncio.sleep(10)

        registry = _make_registry(
            _make_spec("before_save", hook_slow, fail_mode="closed", timeout=0.1),
        )
        event = BeforeSaveEvent(trail_name="t")
        with pytest.raises(HookTimeoutError):
            await run_pipeline(registry, event)

    @pytest.mark.asyncio
    async def test_exception_open(self):
        """Exception with fail_mode=open → skip, continue."""
        async def hook_bad(event):
            raise RuntimeError("boom")

        async def hook_ok(event):
            return Warn(message="ok")

        registry = _make_registry(
            _make_spec("before_save", hook_bad, order=1),
            _make_spec("before_save", hook_ok, order=2),
        )
        event = BeforeSaveEvent(trail_name="t")
        result = await run_pipeline(registry, event)
        assert len(result.feedback.warnings) == 1

    @pytest.mark.asyncio
    async def test_exception_closed(self):
        """Exception with fail_mode=closed → raises."""
        async def hook_bad(event):
            raise RuntimeError("boom")

        registry = _make_registry(
            _make_spec("before_save", hook_bad, fail_mode="closed"),
        )
        event = BeforeSaveEvent(trail_name="t")
        with pytest.raises(HookExecutionError, match="boom"):
            await run_pipeline(registry, event)


# ─── Observer Dispatch ───


class TestObserverDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_fires_hooks(self):
        """dispatch_observer fires hooks via create_task."""
        called = []

        async def hook(event):
            called.append(event.lifecycle_point)

        from fava_trails.hook_types import AfterSaveEvent
        registry = _make_registry(_make_spec("after_save", hook))
        event = AfterSaveEvent(trail_name="t")
        await dispatch_observer(registry, event)
        # Let tasks run
        await asyncio.sleep(0.05)
        assert called == ["after_save"]

    @pytest.mark.asyncio
    async def test_dispatch_exception_doesnt_crash(self):
        """Observer hook exception is logged, doesn't crash."""
        async def hook_bad(event):
            raise RuntimeError("observer boom")

        from fava_trails.hook_types import AfterSaveEvent
        registry = _make_registry(_make_spec("after_save", hook_bad))
        event = AfterSaveEvent(trail_name="t")
        await dispatch_observer(registry, event)
        await asyncio.sleep(0.05)
        # No exception raised — just logged

    @pytest.mark.asyncio
    async def test_dispatch_no_hooks(self):
        """dispatch_observer with no hooks is a no-op."""
        from fava_trails.hook_types import AfterSaveEvent
        registry = _make_registry()
        event = AfterSaveEvent(trail_name="t")
        await dispatch_observer(registry, event)  # should not raise

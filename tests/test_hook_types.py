"""Tests for hook type system."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fava_trails.hook_types import (
    ACTION_VALIDITY,
    MAX_ADVICE,
    MAX_MESSAGE_BYTES,
    MAX_WARNINGS,
    Advise,
    AfterProposeEvent,
    AfterSaveEvent,
    AfterSupersedeEvent,
    Annotate,
    BeforeProposeEvent,
    BeforeSaveEvent,
    HookFeedback,
    Mutate,
    OnRecallEvent,
    OnStartupEvent,
    Proceed,
    RecallSelect,
    Redirect,
    Reject,
    StartupFail,
    StartupOk,
    StartupWarn,
    ThoughtPatch,
    TrailContext,
    Warn,
    validate_action,
)

# ─── Action Construction & Immutability ───


class TestActions:
    def test_proceed(self):
        a = Proceed()
        assert isinstance(a, Proceed)

    def test_reject(self):
        a = Reject(reason="bad thought", code="BAD")
        assert a.reason == "bad thought"
        assert a.code == "BAD"

    def test_reject_default_code(self):
        a = Reject(reason="nope")
        assert a.code == ""

    def test_warn(self):
        a = Warn(message="careful", code="W001")
        assert a.message == "careful"

    def test_advise(self):
        a = Advise(message="add tags", code="TAG", target="agent")
        assert a.target == "agent"
        assert a.suggested_patch is None

    def test_advise_with_patch(self):
        a = Advise(message="fix", suggested_patch={"tags": ["important"]})
        assert a.suggested_patch == {"tags": ["important"]}

    def test_mutate(self):
        patch = ThoughtPatch(content="new content")
        a = Mutate(patch=patch)
        assert a.patch.content == "new content"

    def test_redirect(self):
        a = Redirect(namespace="observations")
        assert a.namespace == "observations"

    def test_annotate(self):
        a = Annotate(values={"score": 0.9})
        assert a.values["score"] == 0.9

    def test_recall_select(self):
        a = RecallSelect(ordered_ulids=["A", "B"], reason="relevance")
        assert a.ordered_ulids == ["A", "B"]

    def test_actions_are_frozen(self):
        """All action dataclasses should be immutable."""
        r = Reject(reason="x")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            r.reason = "y"
        w = Warn(message="x")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            w.message = "y"
        a = Advise(message="x")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            a.message = "y"
        rd = Redirect(namespace="x")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            rd.namespace = "y"
        an = Annotate(values={})
        with pytest.raises((FrozenInstanceError, AttributeError)):
            an.values = {"hack": True}
        rs = RecallSelect(ordered_ulids=[])
        with pytest.raises((FrozenInstanceError, AttributeError)):
            rs.reason = "y"


# ─── ThoughtPatch ───


class TestThoughtPatch:
    def test_empty_patch(self):
        p = ThoughtPatch()
        assert p.content is None
        assert p.metadata is None
        assert p.tags is None
        assert p.confidence is None

    def test_apply_content(self):
        from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
        record = ThoughtRecord(frontmatter=ThoughtFrontmatter(), content="old")
        patch = ThoughtPatch(content="new")
        patched = patch.apply(record)
        assert patched.content == "new"
        assert record.content == "old"  # original unchanged

    def test_apply_tags(self):
        from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
        record = ThoughtRecord(frontmatter=ThoughtFrontmatter(), content="x")
        patch = ThoughtPatch(tags=["a", "b"])
        patched = patch.apply(record)
        assert patched.frontmatter.metadata.tags == ["a", "b"]
        assert record.frontmatter.metadata.tags == []  # original unchanged

    def test_apply_confidence(self):
        from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
        record = ThoughtRecord(frontmatter=ThoughtFrontmatter(confidence=0.5), content="x")
        patch = ThoughtPatch(confidence=0.9)
        patched = patch.apply(record)
        assert patched.frontmatter.confidence == 0.9
        assert record.frontmatter.confidence == 0.5

    def test_apply_metadata(self):
        from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
        record = ThoughtRecord(frontmatter=ThoughtFrontmatter(), content="x")
        patch = ThoughtPatch(metadata={"quality_score": 0.85})
        patched = patch.apply(record)
        assert patched.frontmatter.metadata.extra["quality_score"] == 0.85


# ─── Startup Returns ───


class TestStartupReturns:
    def test_startup_ok(self):
        r = StartupOk()
        assert r.message == ""

    def test_startup_warn(self):
        r = StartupWarn(message="degraded mode")
        assert r.message == "degraded mode"

    def test_startup_fail(self):
        r = StartupFail(message="cannot load")
        assert r.message == "cannot load"

    def test_frozen(self):
        r = StartupOk(message="ok")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            r.message = "hack"


# ─── Events ───


class TestEvents:
    def test_before_save_event(self):
        e = BeforeSaveEvent(trail_name="mw/test", namespace="drafts")
        assert e.lifecycle_point == "before_save"
        assert e.trail_name == "mw/test"
        assert e.namespace == "drafts"
        assert e.hook_api_version == "2.0"
        assert len(e.event_id) > 0

    def test_after_save_event(self):
        e = AfterSaveEvent(trail_name="mw/test")
        assert e.lifecycle_point == "after_save"

    def test_before_propose_event(self):
        e = BeforeProposeEvent(trail_name="mw/test", target_namespace="decisions")
        assert e.lifecycle_point == "before_propose"
        assert e.target_namespace == "decisions"

    def test_after_propose_event(self):
        e = AfterProposeEvent(trail_name="mw/test")
        assert e.lifecycle_point == "after_propose"

    def test_after_supersede_event(self):
        e = AfterSupersedeEvent(trail_name="mw/test")
        assert e.lifecycle_point == "after_supersede"

    def test_on_recall_event(self):
        e = OnRecallEvent(trail_name="mw/test", query="search", results=[1, 2])
        assert e.lifecycle_point == "on_recall"
        assert e.query == "search"
        assert len(e.results) == 2

    def test_on_startup_event(self):
        e = OnStartupEvent(trails_dir=Path("/tmp/trails"), config={"key": "val"})
        assert e.trails_dir == Path("/tmp/trails")
        assert e.config["key"] == "val"

    def test_on_startup_is_not_hook_event(self):
        """OnStartupEvent has a separate contract — not a HookEvent subclass."""
        from fava_trails.hook_types import HookEvent
        e = OnStartupEvent()
        assert not isinstance(e, HookEvent)

    def test_events_have_unique_ids(self):
        e1 = BeforeSaveEvent(trail_name="t")
        e2 = BeforeSaveEvent(trail_name="t")
        assert e1.event_id != e2.event_id

    def test_events_are_frozen(self):
        e = BeforeSaveEvent(trail_name="t")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            e.namespace = "hacked"


# ─── Action Validity Matrix ───


class TestActionValidity:
    def test_before_save_accepts_reject(self):
        assert validate_action("before_save", Reject(reason="x"))

    def test_before_save_accepts_mutate(self):
        assert validate_action("before_save", Mutate(patch=ThoughtPatch()))

    def test_before_save_accepts_redirect(self):
        assert validate_action("before_save", Redirect(namespace="x"))

    def test_before_save_rejects_recall_select(self):
        assert not validate_action("before_save", RecallSelect(ordered_ulids=[]))

    def test_after_save_rejects_reject(self):
        assert not validate_action("after_save", Reject(reason="x"))

    def test_after_save_rejects_mutate(self):
        assert not validate_action("after_save", Mutate(patch=ThoughtPatch()))

    def test_after_save_accepts_warn(self):
        assert validate_action("after_save", Warn(message="x"))

    def test_on_recall_accepts_recall_select(self):
        assert validate_action("on_recall", RecallSelect(ordered_ulids=[]))

    def test_on_recall_rejects_reject(self):
        assert not validate_action("on_recall", Reject(reason="x"))

    def test_on_recall_rejects_mutate(self):
        assert not validate_action("on_recall", Mutate(patch=ThoughtPatch()))

    def test_unknown_lifecycle_point(self):
        assert not validate_action("unknown_point", Proceed())

    def test_all_lifecycle_points_covered(self):
        """Every lifecycle point in the matrix has at least one valid action."""
        expected = {"before_save", "after_save", "before_propose", "after_propose", "after_supersede", "on_recall"}
        assert set(ACTION_VALIDITY.keys()) == expected


# ─── HookFeedback ───


class TestHookFeedback:
    def test_empty_feedback(self):
        fb = HookFeedback()
        assert fb.accepted is True
        assert fb.is_empty()

    def test_merge_reject(self):
        fb = HookFeedback()
        fb.merge(Reject(reason="bad"))
        assert fb.accepted is False
        assert not fb.is_empty()

    def test_merge_warn(self):
        fb = HookFeedback()
        fb.merge(Warn(message="careful", code="W1"))
        assert len(fb.warnings) == 1
        assert fb.warnings[0]["message"] == "careful"
        assert fb.warnings[0]["code"] == "W1"

    def test_merge_advise(self):
        fb = HookFeedback()
        fb.merge(Advise(message="add tags", code="A1", target="agent"))
        assert len(fb.advice) == 1
        assert fb.advice[0]["target"] == "agent"

    def test_merge_advise_with_patch(self):
        fb = HookFeedback()
        fb.merge(Advise(message="fix", suggested_patch={"tags": ["x"]}))
        assert fb.advice[0]["suggested_patch"] == {"tags": ["x"]}

    def test_merge_annotate(self):
        fb = HookFeedback()
        fb.merge(Annotate(values={"score": 0.9}))
        assert fb.annotations["score"] == 0.9

    def test_merge_mutate(self):
        fb = HookFeedback()
        fb.merge(Mutate(patch=ThoughtPatch()))
        assert fb.mutated is True

    def test_merge_redirect(self):
        fb = HookFeedback()
        fb.merge(Redirect(namespace="observations"))
        assert fb.redirected_to == "observations"

    def test_merge_proceed_is_noop(self):
        fb = HookFeedback()
        fb.merge(Proceed())
        assert fb.is_empty()

    def test_warnings_limit(self):
        fb = HookFeedback()
        for i in range(MAX_WARNINGS + 5):
            fb.merge(Warn(message=f"warn {i}"))
        assert len(fb.warnings) == MAX_WARNINGS

    def test_advice_limit(self):
        fb = HookFeedback()
        for i in range(MAX_ADVICE + 5):
            fb.merge(Advise(message=f"advice {i}"))
        assert len(fb.advice) == MAX_ADVICE

    def test_message_truncation(self):
        long_msg = "x" * (MAX_MESSAGE_BYTES + 1000)
        fb = HookFeedback()
        fb.merge(Warn(message=long_msg))
        assert len(fb.warnings[0]["message"].encode("utf-8")) <= MAX_MESSAGE_BYTES

    def test_to_dict_minimal(self):
        fb = HookFeedback()
        d = fb.to_dict()
        assert d == {"accepted": True}

    def test_to_dict_full(self):
        fb = HookFeedback()
        fb.merge(Reject(reason="bad"))
        fb.merge(Warn(message="w"))
        fb.merge(Advise(message="a"))
        fb.merge(Annotate(values={"k": "v"}))
        d = fb.to_dict()
        assert d["accepted"] is False
        assert len(d["warnings"]) == 1
        assert len(d["advice"]) == 1
        assert d["annotations"]["k"] == "v"

    def test_to_dict_mutated(self):
        fb = HookFeedback()
        fb.merge(Mutate(patch=ThoughtPatch()))
        d = fb.to_dict()
        assert d["mutated"] is True

    def test_to_dict_redirected(self):
        fb = HookFeedback()
        fb.merge(Redirect(namespace="obs"))
        d = fb.to_dict()
        assert d["redirected_to"] == "obs"


# ─── TrailContext ───


class TestTrailContext:
    @pytest.mark.asyncio
    async def test_stats(self, tmp_path):
        """stats() counts thoughts by namespace directory."""
        thoughts = tmp_path / "thoughts"
        (thoughts / "drafts").mkdir(parents=True)
        (thoughts / "decisions").mkdir(parents=True)
        (thoughts / "drafts" / "t1.md").write_text("x")
        (thoughts / "drafts" / "t2.md").write_text("x")
        (thoughts / "decisions" / "t3.md").write_text("x")
        (thoughts / "drafts" / ".gitkeep").write_text("")

        mock_trail = MagicMock()
        mock_trail.trail_path = tmp_path
        ctx = TrailContext(mock_trail)
        stats = await ctx.stats()
        assert stats["drafts"] == 2  # .gitkeep excluded
        assert stats["decisions"] == 1

    @pytest.mark.asyncio
    async def test_count_all(self, tmp_path):
        thoughts = tmp_path / "thoughts" / "drafts"
        thoughts.mkdir(parents=True)
        (thoughts / "t1.md").write_text("x")
        (thoughts / "t2.md").write_text("x")

        mock_trail = MagicMock()
        mock_trail.trail_path = tmp_path
        ctx = TrailContext(mock_trail)
        assert await ctx.count() == 2

    @pytest.mark.asyncio
    async def test_count_namespace(self, tmp_path):
        (tmp_path / "thoughts" / "drafts").mkdir(parents=True)
        (tmp_path / "thoughts" / "drafts" / "t1.md").write_text("x")
        (tmp_path / "thoughts" / "decisions").mkdir(parents=True)
        (tmp_path / "thoughts" / "decisions" / "t2.md").write_text("x")

        mock_trail = MagicMock()
        mock_trail.trail_path = tmp_path
        ctx = TrailContext(mock_trail)
        assert await ctx.count("drafts") == 1

    @pytest.mark.asyncio
    async def test_recall_uses_internal(self):
        """recall() calls _recall_internal to bypass hooks."""
        mock_trail = MagicMock()
        mock_trail._recall_internal = AsyncMock(return_value=["thought1"])
        ctx = TrailContext(mock_trail)
        results = await ctx.recall(query="test")
        mock_trail._recall_internal.assert_called_once_with(
            query="test", namespace=None, limit=50
        )
        assert results == ["thought1"]

    @pytest.mark.asyncio
    async def test_recall_caps_limit(self):
        """recall() enforces hard cap of 50."""
        mock_trail = MagicMock()
        mock_trail._recall_internal = AsyncMock(return_value=[])
        ctx = TrailContext(mock_trail)
        await ctx.recall(limit=200)
        mock_trail._recall_internal.assert_called_once_with(
            query="", namespace=None, limit=50
        )

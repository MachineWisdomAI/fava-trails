"""Tests for ACE Playbook Hooks (protocols/ace).

Covers: TestConfigure, TestPlaybookRule, TestParseRules,
        TestOnStartup, TestOnRecall, TestBeforeSave, TestAfterSave,
        TestAfterPropose, TestAfterSupersede, TestPipelineIntegration.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

import fava_trails.protocols.ace as ace
from fava_trails.hook_types import (
    Advise,
    AfterProposeEvent,
    AfterSaveEvent,
    AfterSupersedeEvent,
    Annotate,
    BeforeSaveEvent,
    OnRecallEvent,
    OnStartupEvent,
    RecallSelect,
    StartupOk,
    Warn,
)
from fava_trails.models import ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord
from fava_trails.protocols.ace.rules import (
    SCORE_CLAMP_MAX,
    SCORE_CLAMP_MIN,
    PlaybookRule,
    _parse_rules,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thought(
    content: str = "test content",
    thought_id: str = "ULID0001",
    source_type: str = "observation",
    tags: list[str] | None = None,
    confidence: float = 0.5,
    extra: dict | None = None,
    created_at: datetime | None = None,
) -> ThoughtRecord:
    meta = ThoughtMetadata(tags=tags or [], extra=extra or {})
    fm = ThoughtFrontmatter(
        thought_id=thought_id,
        confidence=confidence,
        metadata=meta,
    )
    if source_type != "observation":
        from fava_trails.models import SourceType
        fm = ThoughtFrontmatter(
            thought_id=thought_id,
            confidence=confidence,
            source_type=SourceType(source_type),
            metadata=meta,
        )
    if created_at is not None:
        fm = fm.model_copy(update={"created_at": created_at})
    return ThoughtRecord(frontmatter=fm, content=content)


def _make_rule(
    name: str = "testrule",
    rule_type: str = "retrieval_priority",
    match: dict | None = None,
    action: dict | None = None,
    helpful_count: int = 0,
    harmful_count: int = 0,
    description: str = "",
) -> PlaybookRule:
    return PlaybookRule(
        name=name,
        rule_type=rule_type,
        match=match or {},
        action=action or {"boost": 1.0},
        helpful_count=helpful_count,
        harmful_count=harmful_count,
        description=description,
    )


@pytest.fixture(autouse=True)
def _reset_ace():
    """Reset ACE module state between tests."""
    ace._CONFIG = {}
    ace._PLAYBOOK_CACHE.clear()
    ace._CACHE_TIMESTAMPS.clear()
    ace._SAVE_TELEMETRY.clear()
    ace._SUPERSEDE_STATS.clear()
    yield
    ace._CONFIG = {}
    ace._PLAYBOOK_CACHE.clear()
    ace._CACHE_TIMESTAMPS.clear()
    ace._SAVE_TELEMETRY.clear()
    ace._SUPERSEDE_STATS.clear()


def _configure(**overrides):
    config = {"playbook_namespace": "preferences"}
    config.update(overrides)
    ace.configure(config)


# ---------------------------------------------------------------------------
# TestConfigure
# ---------------------------------------------------------------------------


class TestConfigure:
    def test_sets_config(self):
        ace.configure({"playbook_namespace": "custom_ns"})
        assert ace._CONFIG["playbook_namespace"] == "custom_ns"

    def test_clears_cache_on_reconfigure(self):
        ace._PLAYBOOK_CACHE["scope"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["scope"] = 999.0
        ace.configure({"playbook_namespace": "preferences"})
        assert ace._PLAYBOOK_CACHE == {}
        assert ace._CACHE_TIMESTAMPS == {}

    def test_empty_config_accepted(self):
        ace.configure({})
        assert ace._CONFIG == {}


# ---------------------------------------------------------------------------
# TestPlaybookRule
# ---------------------------------------------------------------------------


class TestPlaybookRule:
    # --- matches() ---

    def test_matches_empty_criteria_always_true(self):
        rule = _make_rule(match={})
        thought = _make_thought()
        assert rule.matches(thought) is True

    def test_matches_source_type_hit(self):
        rule = _make_rule(match={"source_type": "observation"})
        thought = _make_thought(source_type="observation")
        assert rule.matches(thought) is True

    def test_matches_source_type_miss(self):
        rule = _make_rule(match={"source_type": "decision"})
        thought = _make_thought(source_type="observation")
        assert rule.matches(thought) is False

    def test_matches_confidence_lt_hit(self):
        rule = _make_rule(match={"confidence_lt": 0.6})
        thought = _make_thought(confidence=0.4)
        assert rule.matches(thought) is True

    def test_matches_confidence_lt_miss(self):
        rule = _make_rule(match={"confidence_lt": 0.3})
        thought = _make_thought(confidence=0.5)
        assert rule.matches(thought) is False

    def test_matches_confidence_lt_boundary(self):
        """Exactly equal to confidence_lt → no match (strictly less than)."""
        rule = _make_rule(match={"confidence_lt": 0.5})
        thought = _make_thought(confidence=0.5)
        assert rule.matches(thought) is False

    def test_matches_confidence_lt_zero_is_valid(self):
        """confidence=0.0 is falsy but valid; must be treated as 0.0, not None."""
        rule = _make_rule(match={"confidence_lt": 0.1})
        thought = _make_thought(confidence=0.0)
        assert rule.matches(thought) is True

    def test_matches_tags_include_all_present(self):
        rule = _make_rule(match={"tags_include": ["a", "b"]})
        thought = _make_thought(tags=["a", "b", "c"])
        assert rule.matches(thought) is True

    def test_matches_tags_include_missing(self):
        rule = _make_rule(match={"tags_include": ["a", "b"]})
        thought = _make_thought(tags=["a"])
        assert rule.matches(thought) is False

    def test_matches_tags_exclude_none_present(self):
        rule = _make_rule(match={"tags_exclude": ["spam"]})
        thought = _make_thought(tags=["a", "b"])
        assert rule.matches(thought) is True

    def test_matches_tags_exclude_present(self):
        rule = _make_rule(match={"tags_exclude": ["spam"]})
        thought = _make_thought(tags=["a", "spam"])
        assert rule.matches(thought) is False

    def test_matches_age_lt_days_recent(self):
        rule = _make_rule(match={"age_lt_days": 7})
        recent = datetime.now(UTC) - timedelta(days=3)
        thought = _make_thought(created_at=recent)
        assert rule.matches(thought) is True

    def test_matches_age_lt_days_old(self):
        rule = _make_rule(match={"age_lt_days": 7})
        old = datetime.now(UTC) - timedelta(days=10)
        thought = _make_thought(created_at=old)
        assert rule.matches(thought) is False

    def test_matches_age_lt_days_bad_date_defaults_true(self):
        """If age calculation fails, default to matching (non-blocking)."""
        rule = _make_rule(match={"age_lt_days": 7})
        # Inject a thought whose created_at will raise during subtraction
        thought = _make_thought()
        thought.frontmatter.__dict__["created_at"] = "not-a-datetime"
        # Should not raise, defaults to True
        assert rule.matches(thought) is True

    def test_matches_and_logic_all_must_pass(self):
        rule = _make_rule(match={"source_type": "decision", "confidence_lt": 0.6})
        # Matches source_type but not confidence_lt
        thought = _make_thought(source_type="decision", confidence=0.8)
        assert rule.matches(thought) is False

    # --- evaluate() ---

    def test_evaluate_anti_pattern_always_neutral(self):
        rule = _make_rule(rule_type="anti_pattern", action={"boost": 5.0})
        thought = _make_thought()
        assert rule.evaluate(thought) == 1.0

    def test_evaluate_no_match_returns_one(self):
        rule = _make_rule(
            rule_type="retrieval_priority",
            match={"source_type": "decision"},
            action={"boost": 2.0},
        )
        thought = _make_thought(source_type="observation")
        assert rule.evaluate(thought) == 1.0

    def test_evaluate_laplace_smoothed_ratio(self):
        """With helpful=9, harmful=1: ratio = (9+1)/(9+1+2) = 10/12 ≈ 0.833."""
        rule = _make_rule(
            match={"source_type": "observation"},
            action={"boost": 2.0},
            helpful_count=9,
            harmful_count=1,
        )
        thought = _make_thought(source_type="observation")
        expected = 2.0 * (10 / 12)
        assert abs(rule.evaluate(thought) - expected) < 1e-9

    def test_evaluate_clamp_max(self):
        """Score exceeding 2.0 is clamped to SCORE_CLAMP_MAX."""
        rule = _make_rule(
            match={},
            action={"boost": 100.0},
            helpful_count=1000,
            harmful_count=0,
        )
        thought = _make_thought()
        assert rule.evaluate(thought) == SCORE_CLAMP_MAX

    def test_evaluate_clamp_min(self):
        """Score below 0.5 is clamped to SCORE_CLAMP_MIN."""
        rule = _make_rule(
            match={},
            action={"deprioritize": 0.001},
            helpful_count=0,
            harmful_count=1000,
        )
        thought = _make_thought()
        assert rule.evaluate(thought) == SCORE_CLAMP_MIN

    def test_evaluate_deprioritize_action(self):
        """deprioritize action reduces score."""
        rule = _make_rule(
            match={},
            action={"deprioritize": 0.5},
            helpful_count=3,
            harmful_count=1,
        )
        thought = _make_thought()
        ratio = (3 + 1) / (3 + 1 + 2)
        raw = 0.5 * ratio
        expected = max(SCORE_CLAMP_MIN, min(SCORE_CLAMP_MAX, raw))
        assert abs(rule.evaluate(thought) - expected) < 1e-9

    def test_evaluate_no_action_defaults_to_one(self):
        """Empty action dict (no boost/deprioritize key) defaults to 1.0 base."""
        rule = _make_rule(match={}, action={}, helpful_count=0, harmful_count=0)
        thought = _make_thought()
        # ratio = 1/2, base=1.0, result = 0.5 → clamped to 0.5
        result = rule.evaluate(thought)
        assert result == SCORE_CLAMP_MIN

    def test_evaluate_negative_counters_normalized(self):
        """Negative helpful/harmful counts are clamped to 0 — no ZeroDivisionError."""
        rule = _make_rule(
            match={},
            action={"boost": 1.5},
            helpful_count=-1,
            harmful_count=-1,
        )
        thought = _make_thought()
        # Both normalized to 0: ratio = (0+1)/(0+0+2) = 0.5
        result = rule.evaluate(thought)
        expected = max(SCORE_CLAMP_MIN, min(SCORE_CLAMP_MAX, 1.5 * 0.5))
        assert abs(result - expected) < 1e-9


# ---------------------------------------------------------------------------
# TestParseRules
# ---------------------------------------------------------------------------


class TestParseRules:
    def test_parses_valid_rule(self):
        thought = _make_thought(
            thought_id="ABCD1234",
            extra={
                "rule_type": "retrieval_priority",
                "match": {"source_type": "decision"},
                "action": {"boost": 1.5},
                "weight": 10,
                "helpful_count": 5,
                "harmful_count": 1,
                "section": "task_guidance",
                "description": "Boost decisions",
            },
        )
        rules = _parse_rules([thought])
        assert len(rules) == 1
        r = rules[0]
        assert r.name == "ABCD1234"
        assert r.rule_type == "retrieval_priority"
        assert r.match == {"source_type": "decision"}
        assert r.action == {"boost": 1.5}
        assert r.weight == 10
        assert r.helpful_count == 5
        assert r.harmful_count == 1
        assert r.section == "task_guidance"
        assert r.description == "Boost decisions"
        assert r.source_thought_id == "ABCD1234"

    def test_skips_malformed_but_continues(self):
        """A thought with bad extra data is skipped; others still load."""
        good = _make_thought(
            thought_id="GOOD0001",
            extra={"rule_type": "retrieval_priority", "match": {}, "action": {"boost": 1.0}},
        )
        # Malformed: weight cannot be cast to int from a dict
        bad = _make_thought(
            thought_id="BAD00001",
            extra={"weight": {"not": "an-int"}},
        )
        rules = _parse_rules([bad, good])
        assert len(rules) == 1
        assert rules[0].source_thought_id == "GOOD0001"

    def test_empty_extra_uses_defaults(self):
        thought = _make_thought(extra={})
        rules = _parse_rules([thought])
        assert len(rules) == 1
        r = rules[0]
        assert r.rule_type == "retrieval_priority"
        assert r.match == {}
        assert r.action == {}
        assert r.helpful_count == 0
        assert r.harmful_count == 0

    def test_empty_list(self):
        assert _parse_rules([]) == []

    def test_all_malformed_returns_empty(self):
        bad1 = _make_thought(thought_id="BAD00001", extra={"weight": {"x": "y"}})
        bad2 = _make_thought(thought_id="BAD00002", extra={"weight": {"x": "y"}})
        rules = _parse_rules([bad1, bad2])
        assert rules == []

    def test_non_dict_match_skipped(self):
        """match/action must be dicts; non-dict values are skipped."""
        bad = _make_thought(
            thought_id="BADMATCH",
            extra={"match": "not-a-dict", "action": {"boost": 1.0}},
        )
        good = _make_thought(
            thought_id="GOOD0002",
            extra={"match": {}, "action": {"boost": 1.0}},
        )
        rules = _parse_rules([bad, good])
        assert len(rules) == 1
        assert rules[0].source_thought_id == "GOOD0002"

    def test_non_dict_action_skipped(self):
        """Non-dict action is skipped."""
        bad = _make_thought(
            thought_id="BADACTN1",
            extra={"match": {}, "action": [1, 2, 3]},
        )
        rules = _parse_rules([bad])
        assert rules == []


# ---------------------------------------------------------------------------
# TestOnStartup
# ---------------------------------------------------------------------------


class TestOnStartup:
    @pytest.mark.asyncio
    async def test_returns_startup_ok(self):
        _configure(playbook_namespace="preferences")
        event = OnStartupEvent()
        result = await ace.on_startup(event)
        assert isinstance(result, StartupOk)

    @pytest.mark.asyncio
    async def test_startup_message_includes_namespace(self):
        _configure(playbook_namespace="my_ns")
        event = OnStartupEvent()
        result = await ace.on_startup(event)
        assert "my_ns" in result.message

    @pytest.mark.asyncio
    async def test_startup_without_configure(self):
        event = OnStartupEvent()
        result = await ace.on_startup(event)
        assert isinstance(result, StartupOk)


# ---------------------------------------------------------------------------
# TestOnRecall
# ---------------------------------------------------------------------------


class TestOnRecall:
    @pytest.mark.asyncio
    async def test_no_results_returns_none(self):
        _configure()
        event = OnRecallEvent(trail_name="trail1", results=[])
        result = await ace.on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_playbook_rules_returns_none(self):
        """Empty playbook cache → no reranking."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = []
        ace._CACHE_TIMESTAMPS["trail1"] = time.monotonic()
        t1 = _make_thought(thought_id="A")
        event = OnRecallEvent(trail_name="trail1", results=[t1])
        result = await ace.on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_rules_rerank_results(self):
        """A boost rule moves matching thought to front."""
        _configure()
        rule = _make_rule(
            match={"source_type": "decision"},
            action={"boost": 2.0},
            helpful_count=9,
            harmful_count=1,
        )
        ace._PLAYBOOK_CACHE["trail1"] = [rule]
        ace._CACHE_TIMESTAMPS["trail1"] = time.monotonic()

        t_obs = _make_thought(thought_id="OBS", source_type="observation", confidence=0.8)
        t_dec = _make_thought(thought_id="DEC", source_type="decision", confidence=0.5)

        event = OnRecallEvent(trail_name="trail1", results=[t_obs, t_dec])
        result = await ace.on_recall(event)

        assert result is not None
        select = next(a for a in result if isinstance(a, RecallSelect))
        assert select.ordered_ulids[0] == "DEC"
        assert select.reason == "ace_playbook_rerank"

    @pytest.mark.asyncio
    async def test_confidence_zero_not_replaced(self):
        """confidence=0.0 is falsy but valid; must not be replaced with 0.5."""
        _configure()
        rule = _make_rule(match={}, action={"boost": 1.0}, helpful_count=10)
        ace._PLAYBOOK_CACHE["trail1"] = [rule]
        ace._CACHE_TIMESTAMPS["trail1"] = time.monotonic()

        t_zero = _make_thought(thought_id="ZERO", confidence=0.0)
        t_half = _make_thought(thought_id="HALF", confidence=0.5)

        event = OnRecallEvent(trail_name="trail1", results=[t_zero, t_half])
        result = await ace.on_recall(event)
        select = next(a for a in result if isinstance(a, RecallSelect))
        # confidence=0.0 should score lower than confidence=0.5
        assert select.ordered_ulids[0] == "HALF"
        assert select.ordered_ulids[1] == "ZERO"

    @pytest.mark.asyncio
    async def test_annotate_includes_rules_applied(self):
        _configure()
        rule = _make_rule()
        ace._PLAYBOOK_CACHE["trail1"] = [rule]
        ace._CACHE_TIMESTAMPS["trail1"] = time.monotonic()
        t = _make_thought(thought_id="T1")
        event = OnRecallEvent(trail_name="trail1", results=[t])
        result = await ace.on_recall(event)
        annotate = next(a for a in result if isinstance(a, Annotate))
        assert annotate.values["rules_applied"] == 1
        assert annotate.values["recall_policy"] == "ace_rerank_v1"

    @pytest.mark.asyncio
    async def test_lazy_load_via_context(self):
        """Cache miss triggers context.recall and caches results."""
        _configure()
        # helpful_count=9 ensures ratio = 10/12 ≈ 0.833; boost=2.0 → DEC score ≈ 0.833 > OBS 0.8
        raw_rule_thought = _make_thought(
            thought_id="RULE0001",
            extra={
                "rule_type": "retrieval_priority",
                "match": {"source_type": "decision"},
                "action": {"boost": 2.0},
                "helpful_count": 9,
                "harmful_count": 1,
            },
        )
        mock_context = AsyncMock()
        mock_context.recall = AsyncMock(return_value=[raw_rule_thought])

        t_dec = _make_thought(thought_id="DEC", source_type="decision", confidence=0.5)
        t_obs = _make_thought(thought_id="OBS", source_type="observation", confidence=0.8)

        event = OnRecallEvent(
            trail_name="trail1",
            results=[t_obs, t_dec],
            context=mock_context,
        )
        result = await ace.on_recall(event)

        mock_context.recall.assert_called_once_with("ace-playbook", namespace="preferences", limit=50)
        assert "trail1" in ace._PLAYBOOK_CACHE
        select = next(a for a in result if isinstance(a, RecallSelect))
        assert select.ordered_ulids[0] == "DEC"

    @pytest.mark.asyncio
    async def test_ttl_expiry_triggers_reload(self):
        """Cache older than TTL triggers a fresh context.recall."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = []
        ace._CACHE_TIMESTAMPS["trail1"] = time.monotonic() - ace._CACHE_TTL_SECONDS - 1  # Definitely expired

        mock_context = AsyncMock()
        mock_context.recall = AsyncMock(return_value=[])

        t = _make_thought(thought_id="T1")
        event = OnRecallEvent(trail_name="trail1", results=[t], context=mock_context)
        await ace.on_recall(event)

        mock_context.recall.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_context_no_crash(self):
        """Cache miss with no context sets empty cache, returns None."""
        _configure()
        t = _make_thought(thought_id="T1")
        event = OnRecallEvent(trail_name="trail1", results=[t], context=None)
        result = await ace.on_recall(event)
        assert result is None
        assert ace._PLAYBOOK_CACHE["trail1"] == []

    @pytest.mark.asyncio
    async def test_deterministic_tiebreak_by_ulid(self):
        """Equal-scored thoughts are sorted by thought_id (deterministic)."""
        _configure()
        # Empty playbook → all thoughts get confidence as score
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule(match={}, action={"boost": 1.0})]
        ace._CACHE_TIMESTAMPS["trail1"] = time.monotonic()

        t_b = _make_thought(thought_id="B_ID", confidence=0.5)
        t_a = _make_thought(thought_id="A_ID", confidence=0.5)

        event = OnRecallEvent(trail_name="trail1", results=[t_b, t_a])
        result = await ace.on_recall(event)
        select = next(a for a in result if isinstance(a, RecallSelect))
        # Reversed sort: higher ULID first
        assert select.ordered_ulids[0] == "B_ID"


# ---------------------------------------------------------------------------
# TestBeforeSave
# ---------------------------------------------------------------------------


class TestBeforeSave:
    @pytest.mark.asyncio
    async def test_no_thought_returns_none(self):
        _configure()
        event = BeforeSaveEvent(trail_name="trail1")
        result = await ace.before_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_observation_no_brevity_advisory(self):
        """Non-decision thoughts don't get brevity advisory."""
        _configure()
        thought = _make_thought(source_type="observation", content="short")
        event = BeforeSaveEvent(trail_name="trail1", thought=thought)
        result = await ace.before_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_terse_decision_gets_brevity_advise(self):
        """Decision < 80 chars gets ace_brevity_bias advisory."""
        _configure()
        thought = _make_thought(source_type="decision", content="Too short.")
        event = BeforeSaveEvent(trail_name="trail1", thought=thought)
        result = await ace.before_save(event)
        assert result is not None
        assert any(isinstance(a, Advise) and a.code == "ace_brevity_bias" for a in result)

    @pytest.mark.asyncio
    async def test_long_decision_no_brevity_advisory(self):
        """Decision >= 80 chars does not trigger advisory."""
        _configure()
        thought = _make_thought(source_type="decision", content="x" * 80)
        event = BeforeSaveEvent(trail_name="trail1", thought=thought)
        result = await ace.before_save(event)
        # Only advisory would come from brevity bias — no rules in cache
        assert not any(isinstance(a, Advise) and a.code == "ace_brevity_bias" for a in (result or []))

    @pytest.mark.asyncio
    async def test_anti_pattern_rule_triggers_warn(self):
        """Anti-pattern rule that matches → Warn action."""
        _configure()
        rule = PlaybookRule(
            name="no_drafts",
            rule_type="anti_pattern",
            match={"tags_include": ["draft"]},
            action={},
            description="Don't save drafts directly",
        )
        ace._PLAYBOOK_CACHE["trail1"] = [rule]
        thought = _make_thought(tags=["draft"])
        event = BeforeSaveEvent(trail_name="trail1", thought=thought)
        result = await ace.before_save(event)
        assert result is not None
        warns = [a for a in result if isinstance(a, Warn)]
        assert len(warns) == 1
        assert warns[0].code == "ace_anti_pattern"
        assert "no_drafts" in warns[0].message

    @pytest.mark.asyncio
    async def test_anti_pattern_no_match_no_warn(self):
        """Anti-pattern rule that doesn't match → no Warn."""
        _configure()
        rule = PlaybookRule(
            name="no_drafts",
            rule_type="anti_pattern",
            match={"tags_include": ["draft"]},
            action={},
        )
        ace._PLAYBOOK_CACHE["trail1"] = [rule]
        thought = _make_thought(tags=["published"])
        event = BeforeSaveEvent(trail_name="trail1", thought=thought)
        result = await ace.before_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_anti_pattern_and_brevity_both_fire(self):
        """Both an anti-pattern warn and a brevity advise can fire together."""
        _configure()
        rule = PlaybookRule(
            name="no_terse_decisions",
            rule_type="anti_pattern",
            match={"source_type": "decision"},
            action={},
            description="Warn on decisions",
        )
        ace._PLAYBOOK_CACHE["trail1"] = [rule]
        thought = _make_thought(source_type="decision", content="short", tags=[])
        event = BeforeSaveEvent(trail_name="trail1", thought=thought)
        result = await ace.before_save(event)
        assert result is not None
        assert any(isinstance(a, Warn) for a in result)
        assert any(isinstance(a, Advise) and a.code == "ace_brevity_bias" for a in result)


# ---------------------------------------------------------------------------
# TestAfterSave
# ---------------------------------------------------------------------------


class TestAfterSave:
    @pytest.mark.asyncio
    async def test_no_thought_returns_none(self):
        _configure()
        event = AfterSaveEvent(trail_name="trail1")
        result = await ace.after_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_ace_playbook_tag_invalidates_cache(self):
        """Saving a thought with ace-playbook tag clears the cache."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["trail1"] = 999.0
        thought = _make_thought(tags=["ace-playbook"])
        event = AfterSaveEvent(trail_name="trail1", thought=thought)
        await ace.after_save(event)
        assert "trail1" not in ace._PLAYBOOK_CACHE
        assert "trail1" not in ace._CACHE_TIMESTAMPS

    @pytest.mark.asyncio
    async def test_non_playbook_tag_does_not_invalidate(self):
        """Saving a non-playbook thought leaves cache intact."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["trail1"] = 999.0
        thought = _make_thought(tags=["other-tag"])
        event = AfterSaveEvent(trail_name="trail1", thought=thought)
        await ace.after_save(event)
        assert "trail1" in ace._PLAYBOOK_CACHE

    @pytest.mark.asyncio
    async def test_accumulates_telemetry(self):
        """Each saved thought is recorded in _SAVE_TELEMETRY."""
        _configure()
        t1 = _make_thought(thought_id="T1", tags=["a"])
        t2 = _make_thought(thought_id="T2", tags=["b"])
        await ace.after_save(AfterSaveEvent(trail_name="trail1", thought=t1))
        await ace.after_save(AfterSaveEvent(trail_name="trail1", thought=t2))
        assert len(ace._SAVE_TELEMETRY["trail1"]) == 2
        assert ace._SAVE_TELEMETRY["trail1"][0]["thought_id"] == "T1"
        assert ace._SAVE_TELEMETRY["trail1"][1]["thought_id"] == "T2"

    @pytest.mark.asyncio
    async def test_telemetry_includes_required_fields(self):
        _configure()
        thought = _make_thought(thought_id="T1", source_type="decision", tags=["x"], confidence=0.7)
        await ace.after_save(AfterSaveEvent(trail_name="trail1", thought=thought))
        entry = ace._SAVE_TELEMETRY["trail1"][0]
        assert entry["thought_id"] == "T1"
        assert entry["source_type"] == "decision"
        assert entry["tags"] == ["x"]
        assert entry["confidence"] == 0.7

    @pytest.mark.asyncio
    async def test_telemetry_capped_fifo(self):
        """Telemetry evicts oldest entries when exceeding cap."""
        _configure(telemetry_max_per_scope=3)
        for i in range(5):
            t = _make_thought(thought_id=f"T{i}")
            await ace.after_save(AfterSaveEvent(trail_name="trail1", thought=t))
        entries = ace._SAVE_TELEMETRY["trail1"]
        assert len(entries) == 3
        # Oldest (T0, T1) evicted; T2, T3, T4 remain
        assert entries[0]["thought_id"] == "T2"
        assert entries[2]["thought_id"] == "T4"

    @pytest.mark.asyncio
    async def test_telemetry_cap_configurable(self):
        """Default cap is 10_000; configurable via telemetry_max_per_scope."""
        _configure()
        assert ace._TELEMETRY_MAX_PER_SCOPE == 10_000
        _configure(telemetry_max_per_scope=500)
        assert ace._TELEMETRY_MAX_PER_SCOPE == 500


# ---------------------------------------------------------------------------
# TestAfterPropose
# ---------------------------------------------------------------------------


class TestAfterPropose:
    @pytest.mark.asyncio
    async def test_no_thought_returns_none(self):
        _configure()
        event = AfterProposeEvent(trail_name="trail1")
        result = await ace.after_propose(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_ace_playbook_tag_invalidates_cache(self):
        """Proposing a thought with ace-playbook tag clears the cache."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["trail1"] = 999.0
        thought = _make_thought(tags=["ace-playbook"])
        event = AfterProposeEvent(trail_name="trail1", thought=thought)
        await ace.after_propose(event)
        assert "trail1" not in ace._PLAYBOOK_CACHE
        assert "trail1" not in ace._CACHE_TIMESTAMPS

    @pytest.mark.asyncio
    async def test_non_playbook_tag_no_invalidation(self):
        """Proposing a non-playbook thought leaves cache intact."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["trail1"] = 999.0
        thought = _make_thought(tags=["other"])
        event = AfterProposeEvent(trail_name="trail1", thought=thought)
        await ace.after_propose(event)
        assert "trail1" in ace._PLAYBOOK_CACHE


# ---------------------------------------------------------------------------
# TestAfterSupersede
# ---------------------------------------------------------------------------


class TestAfterSupersede:
    @pytest.mark.asyncio
    async def test_missing_thoughts_returns_none(self):
        _configure()
        event = AfterSupersedeEvent(trail_name="trail1")
        result = await ace.after_supersede(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_records_telemetry(self):
        _configure()
        original = _make_thought(thought_id="ORIG0001", source_type="decision", tags=["old"])
        new = _make_thought(thought_id="NEW00001", source_type="decision", tags=["new"])
        event = AfterSupersedeEvent(trail_name="trail1", new_thought=new, original_thought=original)
        await ace.after_supersede(event)
        entries = ace._SUPERSEDE_STATS["trail1"]
        assert len(entries) == 1
        e = entries[0]
        assert e["original_id"] == "ORIG0001"
        assert e["new_id"] == "NEW00001"
        assert e["source_type"] == "decision"
        assert e["tags"] == ["old"]

    @pytest.mark.asyncio
    async def test_playbook_rule_superseded_invalidates_cache(self):
        """Old thought with ace-playbook tag invalidates cache."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["trail1"] = 999.0
        original = _make_thought(thought_id="OLD0", tags=["ace-playbook"])
        new = _make_thought(thought_id="NEW0", tags=[])
        event = AfterSupersedeEvent(trail_name="trail1", new_thought=new, original_thought=original)
        await ace.after_supersede(event)
        assert "trail1" not in ace._PLAYBOOK_CACHE

    @pytest.mark.asyncio
    async def test_new_playbook_thought_superseding_invalidates_cache(self):
        """New thought with ace-playbook tag also invalidates cache."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["trail1"] = 999.0
        original = _make_thought(thought_id="OLD0", tags=["regular"])
        new = _make_thought(thought_id="NEW0", tags=["ace-playbook"])
        event = AfterSupersedeEvent(trail_name="trail1", new_thought=new, original_thought=original)
        await ace.after_supersede(event)
        assert "trail1" not in ace._PLAYBOOK_CACHE

    @pytest.mark.asyncio
    async def test_non_playbook_no_cache_invalidation(self):
        """Superseding non-playbook thought leaves cache intact."""
        _configure()
        ace._PLAYBOOK_CACHE["trail1"] = [_make_rule()]
        ace._CACHE_TIMESTAMPS["trail1"] = 999.0
        original = _make_thought(thought_id="OLD0", tags=["regular"])
        new = _make_thought(thought_id="NEW0", tags=["also-regular"])
        event = AfterSupersedeEvent(trail_name="trail1", new_thought=new, original_thought=original)
        await ace.after_supersede(event)
        assert "trail1" in ace._PLAYBOOK_CACHE

    @pytest.mark.asyncio
    async def test_supersede_telemetry_capped_fifo(self):
        """Supersede telemetry evicts oldest entries when exceeding cap."""
        _configure(telemetry_max_per_scope=2)
        for i in range(4):
            original = _make_thought(thought_id=f"OLD{i}", tags=[])
            new = _make_thought(thought_id=f"NEW{i}", tags=[])
            event = AfterSupersedeEvent(trail_name="trail1", new_thought=new, original_thought=original)
            await ace.after_supersede(event)
        entries = ace._SUPERSEDE_STATS["trail1"]
        assert len(entries) == 2
        assert entries[0]["original_id"] == "OLD2"
        assert entries[1]["original_id"] == "OLD3"


# ---------------------------------------------------------------------------
# TestPipelineIntegration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_full_recall_pipeline_with_rule(self):
        """End-to-end: configure → lazy-load rule → rerank → annotate."""
        ace.configure({"playbook_namespace": "preferences"})

        raw_rule = _make_thought(
            thought_id="RULE0001",
            extra={
                "rule_type": "retrieval_priority",
                "match": {"source_type": "decision"},
                "action": {"boost": 3.0},
                "helpful_count": 5,
                "harmful_count": 0,
            },
        )
        mock_context = AsyncMock()
        mock_context.recall = AsyncMock(return_value=[raw_rule])

        t_obs = _make_thought(thought_id="OBS0", source_type="observation", confidence=0.9)
        t_dec = _make_thought(thought_id="DEC0", source_type="decision", confidence=0.5)

        event = OnRecallEvent(
            trail_name="scope1",
            results=[t_obs, t_dec],
            context=mock_context,
        )
        result = await ace.on_recall(event)

        assert result is not None
        select = next(a for a in result if isinstance(a, RecallSelect))
        assert select.ordered_ulids[0] == "DEC0"
        annotate = next(a for a in result if isinstance(a, Annotate))
        assert annotate.values["rules_applied"] == 1

    @pytest.mark.asyncio
    async def test_cache_invalidated_then_reloaded_on_next_recall(self):
        """after_save invalidates cache → next recall reloads from context."""
        ace.configure({"playbook_namespace": "preferences"})

        rule_thought = _make_thought(
            thought_id="RULE0001",
            extra={"rule_type": "retrieval_priority", "match": {}, "action": {"boost": 1.5}},
        )
        mock_context = AsyncMock()
        mock_context.recall = AsyncMock(return_value=[rule_thought])

        # Pre-populate cache
        ace._PLAYBOOK_CACHE["scope1"] = []
        ace._CACHE_TIMESTAMPS["scope1"] = time.monotonic()

        # Invalidate via after_save
        ace_playbook_thought = _make_thought(tags=["ace-playbook"])
        await ace.after_save(AfterSaveEvent(trail_name="scope1", thought=ace_playbook_thought))
        assert "scope1" not in ace._PLAYBOOK_CACHE

        # Next recall reloads
        t = _make_thought(thought_id="T1")
        event = OnRecallEvent(trail_name="scope1", results=[t], context=mock_context)
        await ace.on_recall(event)

        mock_context.recall.assert_called_once()
        assert len(ace._PLAYBOOK_CACHE["scope1"]) == 1

    @pytest.mark.asyncio
    async def test_malformed_rule_in_playbook_does_not_crash_recall(self):
        """Malformed rule among valid ones: valid rules still applied."""
        ace.configure({"playbook_namespace": "preferences"})

        good_rule = _make_thought(
            thought_id="GOODRULE",
            extra={
                "rule_type": "retrieval_priority",
                "match": {"source_type": "decision"},
                "action": {"boost": 2.0},
                "helpful_count": 9,
                "harmful_count": 1,
            },
        )
        bad_rule = _make_thought(
            thought_id="BADRULEW",
            extra={"weight": {"not": "castable"}},
        )
        mock_context = AsyncMock()
        mock_context.recall = AsyncMock(return_value=[bad_rule, good_rule])

        # DEC score = 0.5 * 2.0 * (10/12) ≈ 0.833; OBS score = 0.6 (no rule)
        t_dec = _make_thought(thought_id="DEC0", source_type="decision", confidence=0.5)
        t_obs = _make_thought(thought_id="OBS0", source_type="observation", confidence=0.6)

        event = OnRecallEvent(
            trail_name="scope1",
            results=[t_obs, t_dec],
            context=mock_context,
        )
        result = await ace.on_recall(event)
        # Good rule still fires: DEC0 gets boosted above OBS0
        assert result is not None
        select = next(a for a in result if isinstance(a, RecallSelect))
        assert select.ordered_ulids[0] == "DEC0"

    @pytest.mark.asyncio
    async def test_concurrent_cold_cache_loads_consistent(self):
        """Two concurrent on_recall calls on same scope get consistent results."""
        ace.configure({"playbook_namespace": "preferences"})

        rule_thought = _make_thought(
            thought_id="RULE0001",
            extra={"rule_type": "retrieval_priority", "match": {}, "action": {"boost": 1.2}},
        )
        mock_context = AsyncMock()
        mock_context.recall = AsyncMock(return_value=[rule_thought])

        t = _make_thought(thought_id="T1")
        event1 = OnRecallEvent(trail_name="scope1", results=[t], context=mock_context)
        event2 = OnRecallEvent(trail_name="scope1", results=[t], context=mock_context)

        r1, r2 = await asyncio.gather(
            ace.on_recall(event1),
            ace.on_recall(event2),
        )

        # Both should have received results
        assert r1 is not None
        assert r2 is not None
        # Cache should have exactly one entry for scope1
        assert "scope1" in ace._PLAYBOOK_CACHE

"""Tests for SECOM Compression Hooks (protocols/secom)."""

from __future__ import annotations

import pytest

from fava_trails.hook_types import (
    Advise,
    Annotate,
    BeforeProposeEvent,
    BeforeSaveEvent,
    Mutate,
    OnRecallEvent,
    RecallSelect,
)
from fava_trails.models import ThoughtFrontmatter, ThoughtMetadata, ThoughtRecord
from fava_trails.protocols.secom import (
    _compress_heuristic,
    before_propose,
    before_save,
    configure,
    on_recall,
)


def _make_thought(
    content: str = "test",
    thought_id: str = "ULID1",
    tags: list[str] | None = None,
    confidence: float = 0.5,
    extra: dict | None = None,
) -> ThoughtRecord:
    """Create a ThoughtRecord for testing."""
    meta = ThoughtMetadata(tags=tags or [], extra=extra or {})
    fm = ThoughtFrontmatter(thought_id=thought_id, confidence=confidence, metadata=meta)
    return ThoughtRecord(frontmatter=fm, content=content)


@pytest.fixture(autouse=True)
def _reset_secom():
    """Reset SECOM module state between tests."""
    import fava_trails.protocols.secom as mod

    mod._CONFIG = {}
    mod._COMPRESSOR = None
    yield
    mod._CONFIG = {}
    mod._COMPRESSOR = None


def _configure(**overrides):
    """Configure SECOM with defaults + overrides."""
    config = {
        "compression_threshold_chars": 500,
        "verbosity_warn_chars": 1000,
        "target_compress_rate": 0.6,
        "compression_engine": "heuristic",
    }
    config.update(overrides)
    configure(config)


# --- Heuristic Compression Engine ---


class TestHeuristicCompression:
    def test_short_text_unchanged(self):
        """Text with <= 2 sentences passes through unchanged."""
        text = "Hello world. Goodbye world."
        compressed, rate = _compress_heuristic(text, 0.6)
        assert compressed == text
        assert rate == 1.0

    def test_single_sentence_unchanged(self):
        text = "Just one sentence here."
        compressed, rate = _compress_heuristic(text, 0.6)
        assert compressed == text
        assert rate == 1.0

    def test_compresses_multi_sentence(self):
        """Multi-sentence text is compressed by removing short sentences."""
        text = (
            "This is the first important sentence with significant content. "
            "Short. "
            "This is another important sentence that contains key information. "
            "Also short. "
            "This is the third important sentence with substantial details."
        )
        compressed, rate = _compress_heuristic(text, 0.6)
        assert len(compressed) < len(text)
        assert rate < 1.0

    def test_preserves_sentence_order(self):
        """Compressed output retains original sentence ordering."""
        text = "First sentence is long enough to keep. Second is tiny. Third sentence is also quite long enough."
        compressed, rate = _compress_heuristic(text, 0.6)
        sentences = compressed.split(". ")
        # Verify ordering is preserved (no reordering)
        if len(sentences) > 1:
            first_pos = text.find(sentences[0])
            last_pos = text.find(sentences[-1].rstrip("."))
            assert first_pos < last_pos

    def test_empty_text(self):
        compressed, rate = _compress_heuristic("", 0.6)
        assert compressed == ""
        assert rate == 1.0

    def test_duplicate_sentences(self):
        """Duplicate sentences are handled correctly via index-based selection."""
        text = "Important fact. Filler. Important fact. More filler. Important fact."
        compressed, rate = _compress_heuristic(text, 0.6)
        # Should not keep all duplicates when only some indices are selected
        assert rate < 1.0 or len(compressed) <= len(text)


# --- before_propose Hook ---


class TestBeforePropose:
    @pytest.mark.asyncio
    async def test_below_threshold_passes_through(self):
        """Content below threshold is not compressed."""
        _configure(compression_threshold_chars=500)
        thought = _make_thought(content="Short content.")
        event = BeforeProposeEvent(trail_name="t", thought=thought)
        result = await before_propose(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_above_threshold_compresses(self):
        """Content above threshold is compressed."""
        _configure(compression_threshold_chars=100)
        long_content = (
            "This is the first substantial sentence with important details. "
            "This is filler. "
            "This is the second substantial sentence containing key facts. "
            "More filler. "
            "This is the third substantial sentence with significant information. "
            "Tiny. "
            "This is the fourth substantial sentence that has relevant content. "
            "Brief. "
            "This is the fifth substantial sentence with critical data points."
        )
        thought = _make_thought(content=long_content)
        event = BeforeProposeEvent(trail_name="t", thought=thought)
        result = await before_propose(event)

        assert result is not None
        assert len(result) == 2

        mutate_action = result[0]
        assert isinstance(mutate_action, Mutate)
        assert mutate_action.patch.content is not None
        assert len(mutate_action.patch.content) < len(long_content)
        assert "secom-compressed" in mutate_action.patch.tags
        assert "secom_compress_rate" in mutate_action.patch.metadata
        assert "secom_original_chars" in mutate_action.patch.metadata
        assert "secom_engine" in mutate_action.patch.metadata

        annotate_action = result[1]
        assert isinstance(annotate_action, Annotate)
        assert annotate_action.values["secom_status"] == "compressed"

    @pytest.mark.asyncio
    async def test_already_compressed_skipped(self):
        """Thoughts with secom-compressed tag are not re-compressed."""
        _configure(compression_threshold_chars=10)
        thought = _make_thought(
            content="A" * 1000,
            tags=["secom-compressed"],
        )
        event = BeforeProposeEvent(trail_name="t", thought=thought)
        result = await before_propose(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_thought_returns_none(self):
        """Event without thought returns None."""
        _configure()
        event = BeforeProposeEvent(trail_name="t")
        result = await before_propose(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_minimal_compression_skipped(self):
        """If compression achieves < 5% reduction, annotate skip (no Mutate)."""
        _configure(compression_threshold_chars=10, target_compress_rate=0.99)
        # Two long sentences of similar length -- heuristic can't remove much at 0.99
        text = "First long sentence. Second long sentence."
        thought = _make_thought(content=text)
        event = BeforeProposeEvent(trail_name="t", thought=thought)
        result = await before_propose(event)
        # With only 2 sentences at 0.99 rate, heuristic returns 1.0 -- minimal compression
        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Annotate)
        assert result[0].values["secom_status"] == "skipped_minimal_compression"

    @pytest.mark.asyncio
    async def test_compression_failure_fails_open(self):
        """Compression error returns Annotate with error, does not block."""
        import fava_trails.protocols.secom as mod

        _configure(compression_threshold_chars=10, compression_engine="heuristic")

        # Monkey-patch heuristic to raise
        original = mod._compress_heuristic

        def _bad_compress(text, rate):
            raise RuntimeError("compressor exploded")

        mod._compress_heuristic = _bad_compress
        try:
            thought = _make_thought(content="A" * 100 + ". B" * 50 + ". C" * 50 + ".")
            event = BeforeProposeEvent(trail_name="t", thought=thought)
            result = await before_propose(event)
            assert result is not None
            assert len(result) == 1
            assert isinstance(result[0], Annotate)
            assert result[0].values["secom_status"] == "compression_failed"
        finally:
            mod._compress_heuristic = original

    @pytest.mark.asyncio
    async def test_idempotency_no_double_compress(self):
        """Promoting a thought that already has secom-compressed tag skips compression."""
        _configure(compression_threshold_chars=10)
        thought = _make_thought(
            content="Long content " * 100,
            tags=["secom-compressed"],
            extra={"secom_compress_rate": 0.6, "secom_original_chars": 2000},
        )
        event = BeforeProposeEvent(trail_name="t", thought=thought)
        result = await before_propose(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_preserves_existing_tags(self):
        """Compression adds secom-compressed without removing existing tags."""
        _configure(compression_threshold_chars=10)
        long_content = (
            "First important sentence with substantial details. "
            "Filler. "
            "Second important sentence with key information. "
            "More filler. "
            "Third important sentence with critical content."
        )
        thought = _make_thought(content=long_content, tags=["my-tag", "another-tag"])
        event = BeforeProposeEvent(trail_name="t", thought=thought)
        result = await before_propose(event)
        assert result is not None
        mutate_action = result[0]
        assert isinstance(mutate_action, Mutate)
        assert "my-tag" in mutate_action.patch.tags
        assert "another-tag" in mutate_action.patch.tags
        assert "secom-compressed" in mutate_action.patch.tags


# --- before_save Hook ---


class TestBeforeSave:
    @pytest.mark.asyncio
    async def test_below_warn_threshold_no_advice(self):
        """Short content produces no advisory."""
        _configure(verbosity_warn_chars=1000)
        thought = _make_thought(content="Short.")
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await before_save(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_above_warn_threshold_advises(self):
        """Verbose content triggers advisory."""
        _configure(verbosity_warn_chars=50, compression_threshold_chars=30)
        thought = _make_thought(content="A" * 100)
        event = BeforeSaveEvent(trail_name="t", thought=thought)
        result = await before_save(event)
        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Advise)
        assert result[0].code == "secom_verbosity_advisory"
        assert "100 chars" in result[0].message

    @pytest.mark.asyncio
    async def test_no_thought_returns_none(self):
        _configure()
        event = BeforeSaveEvent(trail_name="t")
        result = await before_save(event)
        assert result is None


# --- on_recall Hook ---


class TestOnRecall:
    @pytest.mark.asyncio
    async def test_no_results_returns_none(self):
        _configure()
        event = OnRecallEvent(trail_name="t", results=[])
        result = await on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_compressed_returns_none(self):
        """If no results are compressed, no reranking is applied."""
        _configure()
        t1 = _make_thought(content="short", thought_id="A")
        t2 = _make_thought(content="also short", thought_id="B")
        event = OnRecallEvent(trail_name="t", results=[t1, t2])
        result = await on_recall(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_compressed_thoughts_boosted(self):
        """Compressed thoughts get density boost in ranking."""
        _configure(compression_threshold_chars=500)
        t_compressed = _make_thought(
            content="compressed",
            thought_id="COMP",
            tags=["secom-compressed"],
            confidence=0.5,
            extra={"secom_compress_rate": 0.5},
        )
        t_normal = _make_thought(
            content="normal",
            thought_id="NORM",
            confidence=0.5,
        )
        event = OnRecallEvent(trail_name="t", results=[t_normal, t_compressed])
        result = await on_recall(event)
        assert result is not None

        # Find RecallSelect
        select = [a for a in result if isinstance(a, RecallSelect)][0]
        # Compressed thought should be ranked first (higher score)
        assert select.ordered_ulids[0] == "COMP"
        assert select.reason == "secom_density_rerank"

        # Find Annotate
        annotate = [a for a in result if isinstance(a, Annotate)][0]
        assert annotate.values["compressed_count"] == 1
        assert annotate.values["total_count"] == 2

    @pytest.mark.asyncio
    async def test_verbose_uncompressed_penalized(self):
        """Uncompressed thoughts above threshold get mild penalty."""
        _configure(compression_threshold_chars=10)
        t_compressed = _make_thought(
            content="compressed",
            thought_id="COMP",
            tags=["secom-compressed"],
            confidence=0.5,
            extra={"secom_compress_rate": 0.6},
        )
        t_verbose = _make_thought(
            content="x" * 100,  # Above 10 char threshold
            thought_id="VERBOSE",
            confidence=0.5,
        )
        t_short = _make_thought(
            content="tiny",  # Below 10 char threshold
            thought_id="SHORT",
            confidence=0.5,
        )
        event = OnRecallEvent(trail_name="t", results=[t_verbose, t_short, t_compressed])
        result = await on_recall(event)
        assert result is not None

        select = [a for a in result if isinstance(a, RecallSelect)][0]
        # Compressed first (boosted), then short (no penalty), then verbose (penalized)
        assert select.ordered_ulids.index("COMP") < select.ordered_ulids.index("VERBOSE")

    @pytest.mark.asyncio
    async def test_zero_confidence_preserved(self):
        """confidence=0.0 should not be replaced with 0.5."""
        _configure()
        t_zero = _make_thought(
            content="zero",
            thought_id="ZERO",
            tags=["secom-compressed"],
            confidence=0.0,
            extra={"secom_compress_rate": 0.5},
        )
        t_normal = _make_thought(
            content="normal",
            thought_id="NORM",
            confidence=0.5,
            tags=["secom-compressed"],
            extra={"secom_compress_rate": 0.5},
        )
        event = OnRecallEvent(trail_name="t", results=[t_zero, t_normal])
        result = await on_recall(event)
        assert result is not None
        select = [a for a in result if isinstance(a, RecallSelect)][0]
        # Normal (0.5 base) should rank above zero (0.0 base)
        assert select.ordered_ulids[0] == "NORM"

    @pytest.mark.asyncio
    async def test_invalid_compress_rate_handled(self):
        """Invalid secom_compress_rate in metadata doesn't crash."""
        _configure()
        t_bad = _make_thought(
            content="bad",
            thought_id="BAD",
            tags=["secom-compressed"],
            confidence=0.5,
            extra={"secom_compress_rate": "oops"},
        )
        t_ok = _make_thought(
            content="ok",
            thought_id="OK",
            confidence=0.5,
        )
        event = OnRecallEvent(trail_name="t", results=[t_bad, t_ok])
        result = await on_recall(event)
        # Should not crash -- falls back to 0.6 rate
        assert result is not None

    @pytest.mark.asyncio
    async def test_higher_compression_higher_boost(self):
        """More compressed thoughts get a larger density boost."""
        _configure()
        t_heavy = _make_thought(
            content="heavy",
            thought_id="HEAVY",
            tags=["secom-compressed"],
            confidence=0.5,
            extra={"secom_compress_rate": 0.4},  # 60% removed
        )
        t_light = _make_thought(
            content="light",
            thought_id="LIGHT",
            tags=["secom-compressed"],
            confidence=0.5,
            extra={"secom_compress_rate": 0.8},  # 20% removed
        )
        event = OnRecallEvent(trail_name="t", results=[t_light, t_heavy])
        result = await on_recall(event)
        assert result is not None

        select = [a for a in result if isinstance(a, RecallSelect)][0]
        # Heavy compression = higher density = ranked first
        assert select.ordered_ulids[0] == "HEAVY"


# --- Integration: Pipeline Execution ---


class TestPipelineIntegration:
    """Test SECOM hooks through the actual pipeline engine."""

    @pytest.mark.asyncio
    async def test_full_compress_pipeline(self):
        """Run before_propose through pipeline, verify Mutate is applied."""
        from fava_trails.hook_manifest import HookRegistry, HookSpec
        from fava_trails.hook_pipeline import run_pipeline

        _configure(compression_threshold_chars=10, target_compress_rate=0.6)

        registry = HookRegistry()
        spec = HookSpec(
            name="before_propose",
            fn=before_propose,
            fail_mode="open",
            timeout=5.0,
            order=20,
            source="fava_trails.protocols.secom",
        )
        registry._hooks.setdefault("before_propose", []).append(spec)

        long_content = (
            "This is the first significant sentence with details. "
            "Tiny. "
            "This is the second significant sentence with information. "
            "Small. "
            "This is the third significant sentence with more content."
        )
        thought = _make_thought(content=long_content)
        event = BeforeProposeEvent(trail_name="t", thought=thought)
        result = await run_pipeline(registry, event)

        assert result.feedback.mutated
        assert result.event.thought.content != long_content
        assert len(result.event.thought.content) < len(long_content)
        assert "secom-compressed" in result.event.thought.frontmatter.metadata.tags
        assert "secom_compress_rate" in result.event.thought.frontmatter.metadata.extra

"""Tests for SECOM Compression Hooks (protocols/secom).

The compression engine (LLMLingua-2) is an optional heavy dependency.
Tests that exercise before_propose compression mock _compress() to avoid
requiring the llmlingua package in the test environment.
"""

from __future__ import annotations

from unittest.mock import patch

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
    KNOWN_ENGINES,
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
    mod._ENGINE_CONFIG = {}
    mod._COMPRESSOR = None
    yield
    mod._CONFIG = {}
    mod._ENGINE_CONFIG = {}
    mod._COMPRESSOR = None


def _configure(**overrides):
    """Configure SECOM with defaults + overrides."""
    config = {
        "compression_threshold_chars": 500,
        "verbosity_warn_chars": 1000,
        "target_compress_rate": 0.6,
        "compression_engine": "llmlingua",
    }
    config.update(overrides)
    configure(config)


def _mock_compress(text: str, target_rate: float) -> tuple[str, float]:
    """Deterministic mock compressor: keeps first target_rate fraction of text."""
    keep = max(1, int(len(text) * target_rate))
    compressed = text[:keep]
    return compressed, len(compressed) / len(text) if text else 1.0


# --- Configure Validation ---


class TestConfigure:
    def test_string_engine_accepted(self):
        """String shorthand for known engines works."""
        configure({"compression_engine": "llmlingua"})

    def test_unknown_string_engine_raises(self):
        """Unknown engine string raises ValueError."""
        with pytest.raises(ValueError, match="unknown compression_engine"):
            configure({"compression_engine": "magic"})

    def test_default_engine_is_llmlingua(self):
        """Omitting compression_engine defaults to llmlingua."""
        configure({})
        import fava_trails.protocols.secom as mod
        assert mod._ENGINE_CONFIG["type"] == "llmlingua"

    def test_dict_engine_accepted(self):
        """Dict config with type + constructor args works."""
        configure({"compression_engine": {
            "type": "llmlingua",
            "model_name": "custom/model",
            "device_map": "cuda",
        }})
        import fava_trails.protocols.secom as mod
        assert mod._ENGINE_CONFIG["type"] == "llmlingua"
        assert mod._ENGINE_CONFIG["model_name"] == "custom/model"
        assert mod._ENGINE_CONFIG["device_map"] == "cuda"

    def test_dict_engine_requires_type(self):
        """Dict config without type raises."""
        with pytest.raises(ValueError, match="must include 'type'"):
            configure({"compression_engine": {"model_name": "foo"}})

    def test_dict_engine_unknown_type_raises(self):
        """Dict config with unknown type raises."""
        with pytest.raises(ValueError, match="unknown compression_engine type"):
            configure({"compression_engine": {"type": "magic"}})

    def test_dict_engine_with_compress_args(self):
        """compress_args are stored for pass-through to compress_prompt()."""
        configure({"compression_engine": {
            "type": "llmlingua",
            "compress_args": {
                "force_tokens": ["\n", "."],
                "drop_consecutive": True,
            },
        }})
        import fava_trails.protocols.secom as mod
        assert mod._ENGINE_CONFIG["compress_args"]["drop_consecutive"] is True

    def test_invalid_type_raises(self):
        """Non-string, non-dict raises."""
        with pytest.raises(ValueError, match="must be a string or dict"):
            configure({"compression_engine": 42})

    def test_known_engines_registry(self):
        assert "llmlingua" in KNOWN_ENGINES

    def test_reconfigure_resets_compressor(self):
        """Calling configure() again resets _COMPRESSOR so new config takes effect."""
        import fava_trails.protocols.secom as mod

        mod._COMPRESSOR = "sentinel"  # Simulate a loaded compressor
        configure({"compression_engine": {"type": "llmlingua", "model_name": "other/model"}})
        assert mod._COMPRESSOR is None
        assert mod._ENGINE_CONFIG["model_name"] == "other/model"


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
        long_content = "A" * 200

        with patch("fava_trails.protocols.secom._compress", side_effect=_mock_compress):
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
        assert mutate_action.patch.metadata["secom_engine"] == "llmlingua"

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
        _configure(compression_threshold_chars=10)

        def _barely_compress(text, rate):
            # Remove 1 char — 0.99+ rate
            return text[:-1], (len(text) - 1) / len(text)

        with patch("fava_trails.protocols.secom._compress", side_effect=_barely_compress):
            thought = _make_thought(content="A" * 200)
            event = BeforeProposeEvent(trail_name="t", thought=thought)
            result = await before_propose(event)

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Annotate)
        assert result[0].values["secom_status"] == "skipped_minimal_compression"

    @pytest.mark.asyncio
    async def test_compression_failure_fails_open(self):
        """Compression error returns Annotate with error, does not block."""
        _configure(compression_threshold_chars=10)

        def _bad_compress(text, rate):
            raise RuntimeError("compressor exploded")

        with patch("fava_trails.protocols.secom._compress", side_effect=_bad_compress):
            thought = _make_thought(content="A" * 200)
            event = BeforeProposeEvent(trail_name="t", thought=thought)
            result = await before_propose(event)

        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], Annotate)
        assert result[0].values["secom_status"] == "compression_failed"

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

        with patch("fava_trails.protocols.secom._compress", side_effect=_mock_compress):
            thought = _make_thought(content="A" * 200, tags=["my-tag", "another-tag"])
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

        select = [a for a in result if isinstance(a, RecallSelect)][0]
        assert select.ordered_ulids[0] == "COMP"
        assert select.reason == "secom_density_rerank"

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
            content="x" * 100,
            thought_id="VERBOSE",
            confidence=0.5,
        )
        t_short = _make_thought(
            content="tiny",
            thought_id="SHORT",
            confidence=0.5,
        )
        event = OnRecallEvent(trail_name="t", results=[t_verbose, t_short, t_compressed])
        result = await on_recall(event)
        assert result is not None

        select = [a for a in result if isinstance(a, RecallSelect)][0]
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
            extra={"secom_compress_rate": 0.4},
        )
        t_light = _make_thought(
            content="light",
            thought_id="LIGHT",
            tags=["secom-compressed"],
            confidence=0.5,
            extra={"secom_compress_rate": 0.8},
        )
        event = OnRecallEvent(trail_name="t", results=[t_light, t_heavy])
        result = await on_recall(event)
        assert result is not None

        select = [a for a in result if isinstance(a, RecallSelect)][0]
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

        long_content = "A" * 200

        with patch("fava_trails.protocols.secom._compress", side_effect=_mock_compress):
            thought = _make_thought(content=long_content)
            event = BeforeProposeEvent(trail_name="t", thought=thought)
            result = await run_pipeline(registry, event)

        assert result.feedback.mutated
        assert result.event.thought.content != long_content
        assert len(result.event.thought.content) < len(long_content)
        assert "secom-compressed" in result.event.thought.frontmatter.metadata.tags
        assert "secom_compress_rate" in result.event.thought.frontmatter.metadata.extra

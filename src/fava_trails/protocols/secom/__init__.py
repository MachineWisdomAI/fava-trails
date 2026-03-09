"""SECOM Compression Hooks (WORM Pattern).

Implements the SECOM (SEgmentation + COMpression) pattern from:
  Microsoft ICLR 2025 "On Memory Construction and Retrieval for
  Personalized Conversational Agents" (arXiv:2502.05589)

Three lifecycle hooks:
  - before_propose: Inline extractive compression via Mutate(ThoughtPatch)
  - before_save: Verbosity advisory via Advise
  - on_recall: Density-aware scoring via RecallSelect

Compression engine:
  - llmlingua: Token-level extractive compression via LLMLingua-2.
    Install with: pip install fava-trails[secom]

Configure via config.yaml hooks entry or test harness::

    hooks:
      - module: fava_trails.protocols.secom
        points: [before_propose, before_save, on_recall]
        order: 20
        fail_mode: open
        config:
          compression_threshold_chars: 500
          verbosity_warn_chars: 1000
          target_compress_rate: 0.6
          compression_engine: llmlingua
"""

from __future__ import annotations

import logging
from typing import Any

from fava_trails.hook_types import (
    Advise,
    Annotate,
    BeforeProposeEvent,
    BeforeSaveEvent,
    Mutate,
    OnRecallEvent,
    RecallSelect,
    ThoughtPatch,
)

logger = logging.getLogger(__name__)

# Known compression engines.  Each must implement:
#   (text: str, target_rate: float) -> tuple[str, float]
KNOWN_ENGINES = frozenset({"llmlingua"})

_CONFIG: dict[str, Any] = {}
_COMPRESSOR: Any = None


def configure(config: dict[str, Any]) -> None:
    """Receive hook config from HookRegistry at load time."""
    global _CONFIG
    _CONFIG = config

    engine = config.get("compression_engine", "llmlingua")
    if engine not in KNOWN_ENGINES:
        raise ValueError(
            f"SECOM: unknown compression_engine {engine!r}. "
            f"Known engines: {sorted(KNOWN_ENGINES)}"
        )


# --- Compression Engine ---


def _get_compressor() -> Any:
    """Lazy-load LLMLingua-2 compressor on first use."""
    global _COMPRESSOR
    if _COMPRESSOR is not None:
        return _COMPRESSOR

    from llmlingua import PromptCompressor

    _COMPRESSOR = PromptCompressor(
        model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
        use_llmlingua2=True,
    )
    logger.info("SECOM: LLMLingua-2 compressor loaded")
    return _COMPRESSOR


def _compress(text: str, target_rate: float) -> tuple[str, float]:
    """Run extractive token-level compression via LLMLingua-2."""
    compressor = _get_compressor()
    result = compressor.compress_prompt(
        [text],
        rate=target_rate,
        force_tokens=["\n", "?", "!", ".", ",", "#", "-", "*"],
    )
    compressed = result["compressed_prompt"]
    actual_rate = len(compressed) / len(text) if text else 1.0
    return compressed, actual_rate


# --- Lifecycle Hooks ---


async def before_propose(event: BeforeProposeEvent) -> list[Any] | None:
    """Compress thought content inline before promotion.

    Returns Mutate(ThoughtPatch) to replace content with compressed version,
    plus Annotate with compression metadata.  Skips if content is below
    threshold or already compressed.  Fails open on compression errors.
    """
    if not event.thought:
        return None

    content = event.thought.content
    threshold = _CONFIG.get("compression_threshold_chars", 500)

    if len(content.strip()) < threshold:
        return None

    # Don't re-compress
    tags = event.thought.frontmatter.metadata.tags or []
    if "secom-compressed" in tags:
        return None

    target_rate = _CONFIG.get("target_compress_rate", 0.6)
    engine = _CONFIG.get("compression_engine", "llmlingua")

    try:
        compressed, actual_rate = _compress(content, target_rate)
    except Exception as e:
        # fail_mode: open -- compression failure should not block promotion
        logger.error("SECOM: compression failed, proceeding with original: %s", e)
        return [Annotate({"secom_status": "compression_failed", "error": str(e)})]

    # Only apply if we actually compressed meaningfully
    if actual_rate > 0.95:
        return [Annotate({"secom_status": "skipped_minimal_compression"})]

    new_tags = list(tags) + ["secom-compressed"]
    original_chars = len(content)

    return [
        Mutate(ThoughtPatch(
            content=compressed,
            tags=new_tags,
            metadata={
                "secom_compress_rate": round(actual_rate, 3),
                "secom_original_chars": original_chars,
                "secom_compressed_chars": len(compressed),
                "secom_engine": engine,
            },
        )),
        Annotate({
            "secom_status": "compressed",
            "compress_rate": round(actual_rate, 3),
            "original_chars": original_chars,
            "compressed_chars": len(compressed),
        }),
    ]


async def before_save(event: BeforeSaveEvent) -> list[Any] | None:
    """Advise on verbose thoughts with front-loading guidance."""
    if not event.thought:
        return None

    content = event.thought.content
    warn_chars = _CONFIG.get("verbosity_warn_chars", 1000)

    if len(content.strip()) < warn_chars:
        return None

    threshold = _CONFIG.get("compression_threshold_chars", 500)

    return [Advise(
        message=(
            f"Thought is {len(content)} chars. Content above {threshold} chars "
            f"will be compressed at promote time (SECOM \u03c4={_CONFIG.get('target_compress_rate', 0.6)}). "
            "Consider front-loading key facts and identifiers -- extractive compression "
            "preserves tokens in order, so leading content survives at higher rates."
        ),
        code="secom_verbosity_advisory",
    )]


async def on_recall(event: OnRecallEvent) -> list[Any] | None:
    """Boost compressed thoughts proportionally to compression ratio.

    Compressed thoughts are denser (denoised), so they get a density boost.
    Uncompressed thoughts above the compression threshold get a mild penalty
    (they could have been compressed but weren't).
    """
    if not event.results:
        return None

    has_compressed = False
    scored: list[tuple[Any, float]] = []

    for thought in event.results:
        tags = thought.frontmatter.metadata.tags or []
        extra = thought.frontmatter.metadata.extra or {}
        conf = thought.frontmatter.confidence
        base_score = conf if conf is not None else 0.5

        if "secom-compressed" in tags:
            has_compressed = True
            raw_rate = extra.get("secom_compress_rate", 0.6)
            try:
                compress_rate = max(0.0, min(1.0, float(raw_rate)))
            except (TypeError, ValueError):
                compress_rate = 0.6
            # More compression = more density = higher boost
            # At tau=0.5 (50% retained): boost = 1.25
            # At tau=0.7 (70% retained): boost = 1.15
            density_boost = 1 + (1 - compress_rate) * 0.5
            score = base_score * density_boost
        else:
            threshold = _CONFIG.get("compression_threshold_chars", 500)
            if len(thought.content) > threshold:
                score = base_score * 0.85
            else:
                score = base_score

        scored.append((thought, score))

    if not has_compressed:
        return None

    scored.sort(key=lambda x: x[1], reverse=True)
    ordered_ulids = [t.thought_id for t, _ in scored]

    return [
        RecallSelect(ordered_ulids=ordered_ulids, reason="secom_density_rerank"),
        Annotate({
            "recall_policy": "secom_density_v1",
            "compressed_count": sum(
                1 for t, _ in scored if "secom-compressed" in (t.frontmatter.metadata.tags or [])
            ),
            "total_count": len(scored),
        }),
    ]

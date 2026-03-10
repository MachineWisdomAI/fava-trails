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
          compression_engine:
            type: llmlingua
            model_name: microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank
            device_map: cpu
            compress_args:
              force_tokens: ["\\n", ".", "?", "!", ",", "#", "-", "*"]
              drop_consecutive: true
"""

from __future__ import annotations

import logging
import re
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

# Known compression engine types.
KNOWN_ENGINES = frozenset({"llmlingua"})

# Default compression_engine config when none is provided.
# bert-base-multilingual (178M params) is the default — 3x smaller and faster
# on CPU than xlm-roberta-large (560M).  Both are LLMLingua-2 token classifiers
# trained on MeetingBank.  Use xlm-roberta-large for higher quality if GPU is
# available.
DEFAULT_ENGINE_CONFIG: dict[str, Any] = {
    "type": "llmlingua",
    "model_name": "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
    "device_map": "cpu",
    "use_llmlingua2": True,
}

_CONFIG: dict[str, Any] = {}
_ENGINE_CONFIG: dict[str, Any] = {}
_COMPRESSOR: Any = None


def _parse_engine_config(raw: Any) -> dict[str, Any]:
    """Normalize compression_engine config to a dict.

    Accepts:
      - omitted/None  -> DEFAULT_ENGINE_CONFIG
      - str ("llmlingua") -> {"type": "llmlingua", ...defaults}
      - dict           -> merged with defaults, "type" required
    """
    if raw is None:
        return dict(DEFAULT_ENGINE_CONFIG)

    if isinstance(raw, str):
        if raw not in KNOWN_ENGINES:
            raise ValueError(
                f"SECOM: unknown compression_engine {raw!r}. "
                f"Known engines: {sorted(KNOWN_ENGINES)}"
            )
        return {**DEFAULT_ENGINE_CONFIG, "type": raw}

    if isinstance(raw, dict):
        engine_type = raw.get("type")
        if engine_type is None:
            raise ValueError(
                "SECOM: compression_engine dict must include 'type'. "
                f"Known engines: {sorted(KNOWN_ENGINES)}"
            )
        if engine_type not in KNOWN_ENGINES:
            raise ValueError(
                f"SECOM: unknown compression_engine type {engine_type!r}. "
                f"Known engines: {sorted(KNOWN_ENGINES)}"
            )
        return {**DEFAULT_ENGINE_CONFIG, **raw}

    raise ValueError(
        f"SECOM: compression_engine must be a string or dict, got {type(raw).__name__}"
    )


def configure(config: dict[str, Any]) -> None:
    """Receive hook config from HookRegistry at load time."""
    global _CONFIG, _ENGINE_CONFIG, _COMPRESSOR
    _CONFIG = config
    _ENGINE_CONFIG = _parse_engine_config(config.get("compression_engine"))
    _COMPRESSOR = None  # Reset so lazy-load picks up new engine config


# --- Compression Engine ---

# Keys from compression_engine config that are passed to PromptCompressor().
# Everything else is either our own key ("type", "compress_args") or unknown.
_CONSTRUCTOR_KEYS = frozenset({
    "model_name", "device_map", "model_config", "open_api_config",
    "use_llmlingua2", "use_slingua", "llmlingua2_config",
})


def _get_compressor() -> Any:
    """Lazy-load LLMLingua-2 compressor on first use."""
    global _COMPRESSOR
    if _COMPRESSOR is not None:
        return _COMPRESSOR

    from llmlingua import PromptCompressor

    constructor_args = {
        k: v for k, v in _ENGINE_CONFIG.items()
        if k in _CONSTRUCTOR_KEYS
    }
    _COMPRESSOR = PromptCompressor(**constructor_args)
    logger.info("SECOM: compressor loaded with %s", constructor_args)
    return _COMPRESSOR


def _compress(text: str, target_rate: float) -> tuple[str, float]:
    """Run extractive token-level compression."""
    compressor = _get_compressor()

    # Start with configured defaults, then set rate
    call_args: dict[str, Any] = dict(_ENGINE_CONFIG.get("compress_args", {}))
    call_args["rate"] = target_rate

    result = compressor.compress_prompt([text], **call_args)
    compressed = result["compressed_prompt"]
    actual_rate = len(compressed) / len(text) if text else 1.0
    return compressed, actual_rate


# --- Structured Data Detection ---


def _has_structured_data(content: str) -> bool:
    """Return True if content appears to contain structured data.

    Heuristics (any one triggers):
    - Fenced code block (``` ... ```)
    - JSON-like block: line starting with { or [
    """
    if re.search(r"^```", content, re.MULTILINE):
        return True
    if re.search(r"^\s*[{\[]", content, re.MULTILINE):
        return True
    return False


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

    # Explicit opt-out or already compressed
    tags = event.thought.frontmatter.metadata.tags or []
    if "secom-skip" in tags or "secom-compressed" in tags:
        return None

    target_rate = _CONFIG.get("target_compress_rate", 0.6)
    engine_type = _ENGINE_CONFIG.get("type", "llmlingua")

    if _has_structured_data(content):
        logger.warning(
            "SECOM: compressing content with detected structured data "
            "(JSON/YAML/code block) — syntactic validity may be lost. "
            "Add 'secom-skip' tag to preserve structure."
        )

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
                "secom_engine": engine_type,
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
    """Advise on verbose thoughts and structured content that may be harmed by compression."""
    if not event.thought:
        return None

    content = event.thought.content
    tags = event.thought.frontmatter.metadata.tags or []
    actions: list[Any] = []

    warn_chars = _CONFIG.get("verbosity_warn_chars", 1000)
    if len(content.strip()) >= warn_chars:
        threshold = _CONFIG.get("compression_threshold_chars", 500)
        actions.append(Advise(
            message=(
                f"Thought is {len(content)} chars. Content above {threshold} chars "
                f"will be compressed at promote time (SECOM \u03c4={_CONFIG.get('target_compress_rate', 0.6)}). "
                "Consider front-loading key facts and identifiers -- extractive compression "
                "preserves tokens in order, so leading content survives at higher rates."
            ),
            code="secom_verbosity_advisory",
        ))

    if "secom-skip" not in tags and _has_structured_data(content):
        actions.append(Advise(
            message=(
                "Content appears to contain structured data (JSON/YAML/code block). "
                "SECOM's extractive compression may destroy syntactic validity at promote time. "
                "Add the 'secom-skip' tag to opt out of compression for this thought."
            ),
            code="secom_structured_data_advisory",
        ))

    return actions or None


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

    scored.sort(key=lambda x: (x[1], x[0].thought_id), reverse=True)
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

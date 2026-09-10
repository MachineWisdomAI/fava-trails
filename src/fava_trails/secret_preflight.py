"""Bounded preflight for high-confidence credential patterns.

This is not DLP. It refuses a small set of well-known token shapes before
normal write and promotion paths persist or transmit candidate content,
including nested caller-controlled metadata and relationships.
The complete MCP argument object is scanned before logging or lookup.
It never echoes matched material. It does not erase already-stored records.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Pattern ids are stable operator-facing labels. Matched text is never logged.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pem_private_key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "github_pat",
        re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59})\b"),
    ),
    ("openrouter_api_key", re.compile(r"\bsk-or-v1-[A-Za-z0-9]{32,}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b")),
    ("stripe_live_key", re.compile(r"\b(?:sk|rk)_live_[0-9a-zA-Z]{24,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
)

_SAFE_LIMITS = (
    "This check is a bounded preflight for known key prefixes and PEM private-key "
    "headers, not complete DLP. It does not erase records that were already stored."
)

# Nested walk is bounded. Exceeding the limit is a finding, not a clean miss.
_MAX_WALK_DEPTH = 32
TRAVERSAL_LIMIT_PATTERN_ID = "nested_structure_too_deep"


class ObviousSecretError(ValueError):
    """Raised when a supported high-confidence credential pattern is found."""

    def __init__(self, pattern_id: str, *, persisted_already: bool = False) -> None:
        self.pattern_id = pattern_id
        self.persisted_already = persisted_already
        super().__init__(safe_message(pattern_id, persisted_already=persisted_already))


def safe_message(pattern_id: str, *, persisted_already: bool = False) -> str:
    """Return an explanation that never includes candidate secret material."""
    if pattern_id == TRAVERSAL_LIMIT_PATTERN_ID:
        lead = (
            f"Obvious credential pattern blocked ({pattern_id}) before persist or transmit. "
            f"Nested data exceeded the preflight traversal limit ({_MAX_WALK_DEPTH}); "
            "unscanned content is not treated as clean. "
            f"{_SAFE_LIMITS} Flatten the structure and retry."
        )
    else:
        lead = (
            f"Obvious credential pattern blocked ({pattern_id}) before persist or transmit. "
            f"{_SAFE_LIMITS} Remove the credential and retry."
        )
    if persisted_already:
        return (
            f"{lead} The existing draft was left unchanged; prior persistence is not erased."
        )
    return f"{lead} Existing stored records are not erased."


def find_obvious_secret(text: str | None) -> str | None:
    """Return the first matching pattern id, or None. Never returns matched text."""
    if not text:
        return None
    for pattern_id, pattern in _PATTERNS:
        if pattern.search(text):
            return pattern_id
    return None


def find_obvious_secret_in_value(value: object) -> str | None:
    """Return the first matching pattern id in nested caller-controlled data."""

    def walk(node: object, depth: int) -> str | None:
        if depth > _MAX_WALK_DEPTH:
            return TRAVERSAL_LIMIT_PATTERN_ID
        if node is None or isinstance(node, (bool, int, float)):
            return None
        if isinstance(node, str):
            return find_obvious_secret(node)
        if isinstance(node, dict):
            for key, item in node.items():
                found = walk(key, depth + 1)
                if found:
                    return found
                found = walk(item, depth + 1)
                if found:
                    return found
            return None
        if isinstance(node, (list, tuple, set)):
            for item in node:
                found = walk(item, depth + 1)
                if found:
                    return found
            return None
        dump = getattr(node, "model_dump", None)
        if callable(dump):
            return walk(dump(mode="json"), depth + 1)
        return None

    return walk(value, 0)


def refuse_obvious_secret_in_value(
    value: object,
    *,
    persisted_already: bool = False,
) -> None:
    """Raise ObviousSecretError when a supported pattern is present in nested data."""
    pattern_id = find_obvious_secret_in_value(value)
    if pattern_id is None:
        return
    logger.warning(
        "secret_preflight blocked a supported credential pattern before persist or transmit"
    )
    raise ObviousSecretError(pattern_id, persisted_already=persisted_already)


def refuse_obvious_secret(
    text: str | None,
    *,
    persisted_already: bool = False,
) -> None:
    """Raise ObviousSecretError when a supported pattern is present."""
    refuse_obvious_secret_in_value(text, persisted_already=persisted_already)


def refuse_obvious_secret_in_arguments(arguments: dict[str, object] | None) -> None:
    """Refuse supported patterns in the complete MCP argument object."""
    if not arguments:
        return
    refuse_obvious_secret_in_value(arguments)

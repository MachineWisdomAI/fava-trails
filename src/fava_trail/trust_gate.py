"""Trust Gate — review gate for propose_truth.

Intercepts thought promotion and requires either LLM-based critic review
or explicit human approval before a thought enters a permanent namespace.

Policies:
  - llm-oneshot: Send thought to OpenRouter model with startup-loaded prompt. Fail-closed.
  - human: Not yet implemented — raises NotImplementedError.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import httpx
import yaml

from .models import ThoughtRecord

logger = logging.getLogger(__name__)

TRUST_GATE_PROMPT_FILENAME = "trust-gate-prompt.md"


class TrustGateConfigError(Exception):
    """Raised when trust gate configuration is invalid or missing."""


@dataclass
class TrustResult:
    """Standardized result from any trust gate policy."""

    verdict: Literal["approve", "reject", "error"]
    reasoning: str
    reviewer: str  # "llm-oneshot:<model>" or "human:<user_id>"
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: Optional[float] = None


class TrustGatePromptCache:
    """In-memory cache of trust-gate-prompt.md files, loaded once at startup.

    Prevents adversarial agents from modifying prompt files mid-session.
    """

    def __init__(self) -> None:
        # Maps scope prefix -> prompt content
        # e.g. {"mw/eng/fava-trail": "...", "mw/eng": "...", "mw": "...", "": "..."}
        self._prompts: dict[str, str] = {}

    def load_from_trails_dir(self, trails_dir: Path) -> None:
        """Walk all trail directories, find and cache trust-gate-prompt.md files.

        The root-level prompt (trails/trust-gate-prompt.md) maps to scope prefix "".
        Nested prompts map to their relative scope path.
        """
        self._prompts.clear()

        # Check root-level prompt (trails/trust-gate-prompt.md)
        root_prompt = trails_dir / TRUST_GATE_PROMPT_FILENAME
        if root_prompt.is_file():
            self._prompts[""] = root_prompt.read_text()
            logger.info("Loaded trust-gate-prompt.md at root (trails/)")

        # Walk all subdirectories for scope-specific prompts
        for prompt_file in trails_dir.rglob(TRUST_GATE_PROMPT_FILENAME):
            if prompt_file == root_prompt:
                continue
            try:
                scope = str(prompt_file.parent.relative_to(trails_dir))
            except ValueError:
                continue
            self._prompts[scope] = prompt_file.read_text()
            logger.info(f"Loaded trust-gate-prompt.md for scope: {scope}")

        logger.info(f"Trust gate prompt cache: {len(self._prompts)} prompt(s) loaded")

    def resolve_prompt(self, scope: str) -> str:
        """Resolve the most-specific prompt for a given scope.

        Walks from most-specific to least-specific scope, returns first match.
        For scope "mw/eng/fava-trails", checks:
          1. mw/eng/fava-trails
          2. mw/eng
          3. mw
          4. "" (root trails/)

        Raises TrustGateConfigError if no prompt found at any level.
        """
        # Try exact scope match first
        parts = scope.split("/") if scope else []

        # Check from most-specific to least-specific
        for i in range(len(parts), 0, -1):
            prefix = "/".join(parts[:i])
            if prefix in self._prompts:
                return self._prompts[prefix]

        # Check root level
        if "" in self._prompts:
            return self._prompts[""]

        raise TrustGateConfigError(
            f"No trust-gate-prompt.md found in trail hierarchy for scope '{scope}'. "
            "Create one under trails/ (e.g. trails/trust-gate-prompt.md for a global default)."
        )

    @property
    def prompt_count(self) -> int:
        return len(self._prompts)


def _redact_metadata(record: ThoughtRecord) -> dict:
    """Redact sensitive fields from thought metadata before sending to OpenRouter.

    Strips: agent_id, metadata.extra, and any fields marked sensitive.
    """
    fm = record.frontmatter
    redacted = {
        "thought_id": fm.thought_id,
        "source_type": fm.source_type.value,
        "confidence": fm.confidence,
        "validation_status": fm.validation_status.value,
    }
    if fm.parent_id:
        redacted["parent_id"] = fm.parent_id
    if fm.metadata:
        meta = {}
        if fm.metadata.project:
            meta["project"] = fm.metadata.project
        if fm.metadata.branch:
            meta["branch"] = fm.metadata.branch
        if fm.metadata.tags:
            meta["tags"] = fm.metadata.tags
        # Explicitly exclude metadata.extra — may contain sensitive runtime info
        if meta:
            redacted["metadata"] = meta
    return redacted


def _build_review_payload(
    prompt: str,
    record: ThoughtRecord,
) -> tuple[str, str]:
    """Build system and user messages for the review request.

    System message: trusted prompt loaded at startup.
    User message: thought content wrapped in XML tags as untrusted input.
    """
    redacted_meta = _redact_metadata(record)
    metadata_yaml = yaml.dump(redacted_meta, default_flow_style=False, sort_keys=False)

    system_msg = prompt

    user_msg = (
        "<thought_under_review>\n"
        f"{record.content}\n"
        "</thought_under_review>\n"
        "\n"
        "<thought_metadata>\n"
        f"{metadata_yaml}"
        "</thought_metadata>"
    )

    return system_msg, user_msg


async def _call_openrouter(
    system_msg: str,
    user_msg: str,
    model: str,
    api_key: str,
    timeout: float = 30.0,
) -> dict:
    """Call OpenRouter API with structured JSON output.

    Uses temperature=0 for deterministic output and response_format for JSON.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            },
        )
        response.raise_for_status()
        return response.json()


def _parse_verdict(response_data: dict) -> tuple[str, str, float | None]:
    """Parse structured JSON verdict from OpenRouter response.

    Returns (verdict, reasoning, confidence).
    Raises ValueError if response format is invalid.
    """
    choices = response_data.get("choices", [])
    if not choices:
        raise ValueError("No choices in OpenRouter response")

    message = choices[0].get("message", {})
    content = message.get("content", "")

    verdict_data = json.loads(content)

    verdict = verdict_data.get("verdict")
    if verdict not in ("approve", "reject"):
        raise ValueError(f"Invalid verdict: {verdict!r}. Expected 'approve' or 'reject'.")

    reasoning = verdict_data.get("reasoning", "No reasoning provided")
    confidence = verdict_data.get("confidence")

    return verdict, reasoning, confidence


async def review_thought(
    record: ThoughtRecord,
    prompt: str,
    model: str,
    api_key: str,
    policy: str = "llm-oneshot",
) -> TrustResult:
    """Review a thought using the specified policy.

    Args:
        record: The thought to review.
        prompt: The trust gate prompt (loaded at startup).
        model: OpenRouter model ID for the reviewer.
        api_key: OpenRouter API key.
        policy: Review policy ("llm-oneshot" or "human").

    Returns:
        TrustResult with verdict, reasoning, and provenance.
    """
    if policy == "human":
        raise NotImplementedError(
            "trust_gate: human is not yet implemented. Use 'llm-oneshot' policy. "
            "See Spec 3 for planned approval channels (CLI, PR/GHA, MCP tools)."
        )

    if policy != "llm-oneshot":
        raise TrustGateConfigError(
            f"Unknown trust gate policy: {policy!r}. Available: 'llm-oneshot'."
        )

    system_msg, user_msg = _build_review_payload(prompt, record)
    reviewer_id = f"llm-oneshot:{model}"

    # Attempt API call with 1 retry on parse failure
    last_error = None
    for attempt in range(2):
        try:
            response_data = await _call_openrouter(system_msg, user_msg, model, api_key)
            verdict, reasoning, confidence = _parse_verdict(response_data)

            return TrustResult(
                verdict=verdict,
                reasoning=reasoning,
                reviewer=reviewer_id,
                confidence=confidence,
            )

        except httpx.HTTPStatusError as e:
            return TrustResult(
                verdict="error",
                reasoning=f"OpenRouter HTTP {e.response.status_code}: {e.response.text[:200]}",
                reviewer=reviewer_id,
            )

        except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
            return TrustResult(
                verdict="error",
                reasoning=f"OpenRouter connection error: {type(e).__name__}: {e}",
                reviewer=reviewer_id,
            )

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt == 0:
                logger.warning(f"Trust gate parse error (retrying): {e}")
                continue
            # After 1 retry, fail-closed as reject
            return TrustResult(
                verdict="reject",
                reasoning=f"Failed to parse reviewer response after retry: {e}",
                reviewer=reviewer_id,
            )

        except Exception as e:
            return TrustResult(
                verdict="error",
                reasoning=f"Unexpected error: {type(e).__name__}: {e}",
                reviewer=reviewer_id,
            )

    # Should not reach here, but fail-closed
    return TrustResult(
        verdict="error",
        reasoning=f"Review failed: {last_error}",
        reviewer=reviewer_id,
    )

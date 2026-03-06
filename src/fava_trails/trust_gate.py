"""Trust Gate — review gate for propose_truth.

Intercepts thought promotion and requires either LLM-based critic review
or explicit human approval before a thought enters a permanent namespace.

Policies:
  - llm-oneshot: Send thought to LLM model via LLMClient. Fail-closed.
  - human: Not yet implemented — raises NotImplementedError.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import openai
import yaml

from .llm import LLMClient
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
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    confidence: float | None = None


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

    # Escape untrusted content to prevent XML tag injection
    escaped_content = html.escape(record.content, quote=False)
    escaped_metadata = html.escape(metadata_yaml, quote=False)

    user_msg = (
        "<thought_under_review>\n"
        f"{escaped_content}\n"
        "</thought_under_review>\n"
        "\n"
        "<thought_metadata>\n"
        f"{escaped_metadata}"
        "</thought_metadata>"
    )

    return system_msg, user_msg


def _extract_json_from_llm_response(raw: str) -> str:
    """Extract JSON content from an LLM response, stripping markdown code fences.

    Handles common LLM output artifacts:
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Leading/trailing whitespace
    - Preamble text before the JSON object

    Returns the extracted JSON string, or the original string (as-is) if no JSON
    object is found — letting json.loads() produce a proper error for genuinely
    invalid content.
    """
    # Step 1: Strip leading/trailing whitespace
    result = raw.strip()

    # Step 2: Strip markdown code fences (```json or ```)
    if result.startswith("```"):
        first_newline = result.find("\n")
        if first_newline != -1:
            # Remove the opening fence line (e.g. ```json or ```)
            result = result[first_newline + 1:]
        # Remove the closing fence
        if result.endswith("```"):
            result = result[:-3]

    # Step 3: Strip whitespace again after fence removal
    result = result.strip()

    # Step 4: If it still doesn't start with '{', find first '{' and last '}'
    if not result.startswith("{"):
        first_brace = result.find("{")
        if first_brace != -1:
            last_brace = result.rfind("}")
            if last_brace != -1 and last_brace > first_brace:
                result = result[first_brace : last_brace + 1]

    # Step 5: Log a warning if sanitization changed anything
    if result != raw.strip():
        logger.warning(
            "Trust gate: LLM response required sanitization before JSON parsing "
            "(fence stripping or JSON extraction applied). "
            "Raw length: %d, sanitized length: %d",
            len(raw),
            len(result),
        )

    return result


def _parse_verdict(content: str) -> tuple[str, str, float | None]:
    """Parse structured JSON verdict from LLM response content.

    Returns (verdict, reasoning, confidence).
    Raises ValueError if response format is invalid.
    """
    if not content:
        raise ValueError("Empty response content from LLM")

    verdict_data = json.loads(_extract_json_from_llm_response(content))

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
    client: LLMClient,
    policy: str = "llm-oneshot",
) -> TrustResult:
    """Review a thought using the specified policy.

    Args:
        record: The thought to review.
        prompt: The trust gate prompt (loaded at startup).
        model: Model ID for the reviewer (alias or canonical name).
        client: LLMClient instance for making API calls.
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
            response = await client.chat(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
            )
            verdict, reasoning, confidence = _parse_verdict(response.content)

            return TrustResult(
                verdict=verdict,
                reasoning=reasoning,
                reviewer=reviewer_id,
                confidence=confidence,
            )

        except openai.APIStatusError as e:
            return TrustResult(
                verdict="error",
                reasoning=f"LLM API HTTP {e.status_code}: {str(e.message)[:200]}",
                reviewer=reviewer_id,
            )

        except openai.APIConnectionError as e:
            return TrustResult(
                verdict="error",
                reasoning=f"LLM connection error: {type(e).__name__}: {e}",
                reviewer=reviewer_id,
            )

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt == 0:
                logger.warning(f"Trust gate parse error (retrying): {e}")
                continue
            return TrustResult(
                verdict="error",
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

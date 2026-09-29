"""Trust Gate — review gate for propose_truth.

Intercepts thought promotion and requires either LLM-based critic review
or explicit human approval before a thought enters a permanent namespace.

Policies:
  - llm-oneshot: Send thought to LLM model via LLMClient. Fail-closed.
  - human: Not yet implemented — raises NotImplementedError.
"""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse, urlunparse

import yaml
from any_llm.exceptions import AnyLLMError, ProviderError

from .decisions import DecisionsClient, DecisionsError
from .llm import LLMClient
from .llm.sanitize import sanitize_provider_exception
from .models import ThoughtRecord

if TYPE_CHECKING:
    from .models import GlobalConfig

logger = logging.getLogger(__name__)

TRUST_GATE_PROMPT_FILENAME = "trust-gate-prompt.md"

# Process-scoped: first disclosure (MCP startup log or promotion) sets the flag.
_egress_disclosure_lock = threading.Lock()
_egress_disclosed_in_process = False


def reset_trust_gate_egress_disclosure_state() -> None:
    """Test helper: clear the process-scoped first-disclosure flag."""
    global _egress_disclosed_in_process
    with _egress_disclosure_lock:
        _egress_disclosed_in_process = False


# Paths safe to show in disclosures. Anything else may embed gateway tokens.
_DISCLOSABLE_API_BASE_PATHS = frozenset({"", "/", "/v1", "/v1/"})


def redact_trust_gate_api_base_for_disclosure(api_base: str | None) -> str | None:
    """Return a secret-free api_base suitable for logs, doctor, and tool JSON.

    Strips URL userinfo, query string, and fragment. Path is disclosed only when
    it is empty or the conventional OpenAI-compatible ``/v1`` suffix; any other
    path is replaced with ``/[redacted]`` so gateway tokens in path segments
    cannot leak. Malformed ports fail closed to a non-secret placeholder rather
    than raising. The live request may still use the full configured value.
    """
    if not api_base:
        return None
    raw = api_base.strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    hostname = parsed.hostname or ""
    if not hostname:
        return f"{parsed.scheme or 'http'}://[invalid-api-base]"
    if ":" in hostname:
        host_for_netloc = f"[{hostname}]"
    else:
        host_for_netloc = hostname
    try:
        port = parsed.port
    except ValueError:
        # Defense in depth: never crash doctor/startup logs on a bad port.
        return f"{parsed.scheme or 'http'}://[invalid-api-base]"
    if port is not None:
        netloc = f"{host_for_netloc}:{port}"
    else:
        netloc = host_for_netloc
    path = parsed.path or ""
    if path not in _DISCLOSABLE_API_BASE_PATHS:
        path = "/[redacted]"
    elif path == "/v1/":
        path = "/v1"
    elif path == "/":
        path = ""
    # Drop username/password (netloc rebuild), params, query, and fragment.
    return urlunparse((parsed.scheme, netloc, path, "", "", ""))


def _is_loopback_api_base(api_base: str | None) -> bool:
    """True only for localhost or numeric loopback IP literals (not 127.* DNS names)."""
    if not api_base:
        return False
    try:
        host = (urlparse(api_base).hostname or "").lower()
    except Exception:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def describe_trust_gate_egress(
    config: GlobalConfig,
    *,
    approval: str | None = None,
    policy: str | None = None,
    first_in_process: bool | None = None,
) -> dict[str, Any]:
    """Describe where candidate data goes during Trust Gate review.

    Never includes API keys, key file paths, or secret values — only destination
    identity, model, and a plain summary of which candidate fields are sent.

    ``policy`` names the effective review policy (trail-level override aware);
    it defaults to ``config.trust_gate`` so doctor/startup callers that only
    hold the global config still describe the configured policy accurately.
    """
    from .credentials import trust_gate_credential_description

    if approval == "human":
        notice: dict[str, Any] = {
            "policy": "operator_human",
            "provider": None,
            "model": None,
            "destination": "operator endpoint (no LLM request)",
            "destination_kind": "operator_human",
            "credential_source": None,
            "data_sent": [],
            "data_sent_summary": (
                "No candidate content is transmitted to an LLM provider. "
                "Promotion uses explicit operator approval on this process only."
            ),
            "cloud_fallback": False,
            "rejection_happens_after_transmission": False,
            "explanation": (
                "Operator review path: propose_truth(..., approval=\"human\") on an "
                "operator-controlled endpoint (FAVA_TRAILS_OPERATOR=1 with a configured "
                "FAVA_TRAILS_AGENT_ID). Candidate text is not sent to a remote or local "
                "LLM. This is separate from automatic llm-oneshot review."
            ),
        }
        if first_in_process is not None:
            notice["first_in_process"] = first_in_process
        return notice

    effective_policy = policy or config.trust_gate
    if effective_policy == "decisions":
        from .decisions import DECISIONS_API_PATH, DEFAULT_DECISIONS_API_BASE

        decisions_provider = config.trust_gate_provider
        decisions_model = config.trust_gate_model
        api_base = config.trust_gate_api_base
        if api_base:
            disclosed_base = (
                redact_trust_gate_api_base_for_disclosure(api_base) or "[invalid-api-base]"
            )
            destination = f"{disclosed_base}{DECISIONS_API_PATH}"
            destination_kind: Literal["local_endpoint", "custom_endpoint", "remote_provider"] = (
                "local_endpoint" if _is_loopback_api_base(api_base) else "custom_endpoint"
            )
        else:
            destination_kind = "remote_provider"
            destination = (
                f"{decisions_provider} Decisions API "
                f"({DEFAULT_DECISIONS_API_BASE}{DECISIONS_API_PATH})"
            )
        decisions_data_sent = [
            "full scope-resolved Trust Gate prompt (state.review_instructions)",
            "full candidate thought content (markdown body, state.thought_under_review)",
            "selected metadata fields sent: thought_id, source_type, confidence, validation_status",
            "optional selected metadata fields sent: trail_name, parent_id, project, branch, tags",
            "the configured Noul question text (state.questions.trust.instructions)",
        ]
        notice = {
            "policy": "decisions",
            "provider": decisions_provider,
            "model": decisions_model,
            "destination": destination,
            "destination_kind": destination_kind,
            "credential_source": trust_gate_credential_description(config),
            "data_sent": decisions_data_sent,
            "data_sent_summary": (
                "The full scope-resolved Trust Gate prompt, the full candidate "
                "thought content, and the complete selected metadata fields "
                "(thought_id, source_type, confidence, validation_status; "
                "optional trail_name/parent_id/project/branch/tags) are "
                "transmitted as structured Decisions state together with the "
                "configured Noul question. agent_id and metadata.extra are "
                "excluded and never sent."
            ),
            "cloud_fallback": False,
            "rejection_happens_after_transmission": True,
            "explanation": (
                "Provider selection is a data-egress choice: the candidate is "
                f"transmitted to {destination} using model {decisions_model!r} "
                "before a verdict exists. One Noul question is asked; the answer "
                "carries a calibrated probability and no reasoning. A remote reject "
                "still means the content already left this process. There is no "
                "automatic pass-through/off mode and no silent fallback to another "
                "provider if this destination is unavailable or misconfigured."
            ),
        }
        if first_in_process is not None:
            notice["first_in_process"] = first_in_process
        return notice

    provider = config.trust_gate_provider
    model = config.trust_gate_model
    api_base = config.trust_gate_api_base
    disclosed_api_base = redact_trust_gate_api_base_for_disclosure(api_base)
    if api_base and _is_loopback_api_base(api_base):
        destination_kind: Literal["local_endpoint", "custom_endpoint", "remote_provider"] = "local_endpoint"
        destination = disclosed_api_base or ""
    elif api_base:
        destination_kind = "custom_endpoint"
        destination = disclosed_api_base or ""
    elif provider == "openrouter":
        destination_kind = "remote_provider"
        destination = "OpenRouter (provider default API)"
    else:
        destination_kind = "remote_provider"
        destination = f"{provider} (provider default API)"

    data_sent = [
        "full candidate thought content (markdown body)",
        "selected metadata fields sent: thought_id, source_type, confidence, validation_status",
        "optional selected metadata fields sent: trail_name, parent_id, project, branch, tags",
    ]
    notice = {
        "policy": config.trust_gate,
        "provider": provider,
        "model": model,
        "destination": destination,
        "destination_kind": destination_kind,
        "credential_source": trust_gate_credential_description(config),
        "data_sent": data_sent,
        "data_sent_summary": (
            "Candidate thought content plus the complete selected metadata "
            "fields (thought_id, source_type, confidence, validation_status; "
            "optional trail_name/parent_id/project/branch/tags). agent_id and "
            "metadata.extra are excluded and never sent."
        ),
        "cloud_fallback": False,
        "rejection_happens_after_transmission": True,
        "explanation": (
            "Provider selection is a data-egress choice: the candidate is transmitted "
            f"to {destination} using model {model!r} before a verdict exists. "
            "A remote reject still means the content already left this process. "
            "There is no automatic pass-through/off mode and no silent fallback to "
            "another provider if this destination is unavailable or misconfigured."
        ),
    }
    if first_in_process is not None:
        notice["first_in_process"] = first_in_process
    return notice


def format_trust_gate_egress_notice(notice: dict[str, Any]) -> str:
    """Plain multi-line operator explanation (no secrets)."""
    kind = notice.get("destination_kind")
    lines = [
        "Trust Gate data egress",
        f"  policy:       {notice.get('policy')}",
    ]
    if kind == "operator_human":
        lines.extend(
            [
                "  destination:  operator endpoint (no LLM request)",
                f"  detail:       {notice.get('data_sent_summary')}",
                f"  note:         {notice.get('explanation')}",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            f"  provider:     {notice.get('provider')}",
            f"  model:        {notice.get('model')}",
            f"  destination:  {notice.get('destination')} ({kind})",
            f"  credential:   {notice.get('credential_source')} (name/source only; secret not shown)",
            f"  data sent:    {notice.get('data_sent_summary')}",
            "  timing:       rejection by a remote gate happens after transmission",
            "  fallback:     never silently fall back to a cloud provider; fail closed",
            f"  note:         {notice.get('explanation')}",
        ]
    )
    return "\n".join(lines)


def mark_trust_gate_egress_disclosed() -> bool:
    """Mark first-in-process disclosure. Returns True if this was the first call."""
    global _egress_disclosed_in_process
    with _egress_disclosure_lock:
        first = not _egress_disclosed_in_process
        _egress_disclosed_in_process = True
        return first


def log_trust_gate_egress_notice(notice: dict[str, Any]) -> None:
    """Emit a secret-free egress notice to the server log (before network I/O)."""
    logger.info("%s", format_trust_gate_egress_notice(notice))


class TrustGateConfigError(Exception):
    """Raised when trust gate configuration is invalid or missing."""


@dataclass
class TrustResult:
    """Standardized result from any trust gate policy."""

    verdict: Literal["approve", "reject", "error"]
    reasoning: str
    reviewer: str  # "llm-oneshot:<model>", "decisions:<model>", or "human:<user_id>"
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    confidence: float | None = None
    # Provider selected for the review (e.g. "openrouter", "openai"). Optional
    # for backward compatibility with callers that construct TrustResult directly.
    provider: str | None = None
    # Model identifier returned by the provider (may differ from configured id).
    model: str | None = None
    approval_kind: Literal["llm_advisory", "human"] = "llm_advisory"
    # Review policy that produced this result ("llm-oneshot", "decisions").
    policy: str | None = None
    # Decisions policy provenance: calibrated Jev Noul probability and the
    # operator-configured threshold it was compared against.
    noul_probability: float | None = None
    threshold: float | None = None


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


def _redact_metadata(record: ThoughtRecord, *, trail_name: str | None = None) -> dict:
    """Select the metadata fields transmitted for review.

    The selected fields are sent in full (their values are not redacted);
    agent_id and metadata.extra are excluded entirely.
    Includes trail_name (scope path) when provided — not sensitive, enables
    scope-based artifact type detection (e.g. /specs/, /plans/, /reviews/).
    """
    fm = record.frontmatter
    redacted = {
        "thought_id": fm.thought_id,
        "source_type": fm.source_type.value,
        "confidence": fm.confidence,
        "validation_status": fm.validation_status.value,
    }
    if trail_name:
        redacted["trail_name"] = trail_name
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
    *,
    trail_name: str | None = None,
) -> tuple[str, str]:
    """Build system and user messages for the review request.

    System message: trusted prompt loaded at startup.
    User message: thought content wrapped in XML tags as untrusted input.
    """
    redacted_meta = _redact_metadata(record, trail_name=trail_name)
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
            result = result[first_newline + 1 :]
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
    *,
    trail_name: str | None = None,
) -> TrustResult:
    """Review a thought using the specified policy.

    Args:
        record: The thought to review.
        prompt: The trust gate prompt (loaded at startup).
        model: Model ID for the reviewer (alias or canonical name).
        client: LLMClient instance for making API calls.
        policy: Review policy ("llm-oneshot" or "human").
        trail_name: Scope path (e.g. 'codev-artifacts/Org/Repo/specs/26-foo').

    Returns:
        TrustResult with verdict, reasoning, and provenance.
    """
    if policy == "human":
        raise NotImplementedError(
            "trust_gate: human is not yet implemented. Use 'llm-oneshot' policy. "
            "See Spec 3 for planned approval channels (CLI, PR/GHA, MCP tools)."
        )

    if policy == "decisions":
        raise TrustGateConfigError(
            "trust_gate: the 'decisions' policy uses review_thought_decisions(); "
            "review_thought() implements 'llm-oneshot' only."
        )

    if policy != "llm-oneshot":
        raise TrustGateConfigError(
            f"Unknown trust gate policy: {policy!r}. Available: 'llm-oneshot', 'decisions'."
        )

    system_msg, user_msg = _build_review_payload(prompt, record, trail_name=trail_name)
    # Keep reviewer shape stable for backward compatibility; provider/model are
    # recorded separately on TrustResult for unambiguous provenance.
    reviewer_id = f"llm-oneshot:{model}"
    provider = getattr(client, "provider", None)

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
            returned_model = response.model or model
            returned_provider = response.provider or provider

            return TrustResult(
                verdict=verdict,
                reasoning=reasoning,
                reviewer=reviewer_id,
                confidence=confidence,
                provider=returned_provider,
                model=returned_model,
            )

        except ProviderError as e:
            return TrustResult(
                verdict="error",
                reasoning=f"LLM API {sanitize_provider_exception(e)}",
                reviewer=reviewer_id,
                provider=provider,
                model=model,
            )

        except AnyLLMError as e:
            return TrustResult(
                verdict="error",
                reasoning=f"LLM connection error: {sanitize_provider_exception(e)}",
                reviewer=reviewer_id,
                provider=provider,
                model=model,
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
                provider=provider,
                model=model,
            )

        except Exception as e:
            return TrustResult(
                verdict="error",
                reasoning=f"Unexpected error: {sanitize_provider_exception(e)}",
                reviewer=reviewer_id,
                provider=provider,
                model=model,
            )

    # Should not reach here, but fail-closed
    return TrustResult(
        verdict="error",
        reasoning=f"Review failed: {last_error}",
        reviewer=reviewer_id,
        provider=provider,
        model=model,
    )


def _validate_decisions_review_inputs(question: str, threshold: float) -> None:
    """Validate the Noul question and threshold before any transmission.

    Raises TrustGateConfigError so misconfiguration surfaces as an operator
    error instead of a recorded review outcome.
    """
    if not isinstance(question, str) or not question.strip():
        raise TrustGateConfigError(
            "trust_gate_decisions_config.trust_gate_noul_question must be a "
            "non-empty string before a Decisions review can be transmitted"
        )
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
        or not (0.0 <= float(threshold) <= 1.0)
    ):
        raise TrustGateConfigError(
            "trust_gate_decisions_config.trust_gate_noul_threshold must be a "
            f"finite number within [0, 1]; got {threshold!r}"
        )


def _build_decisions_state(
    prompt: str,
    record: ThoughtRecord,
    *,
    trail_name: str | None = None,
) -> dict:
    """Build the Decisions ``state`` payload.

    Sends the full scope-resolved Trust Gate prompt, the full thought body, and
    the same selected metadata as ``llm-oneshot`` (agent_id and metadata.extra
    excluded). The state is structured JSON, so untrusted content is escaped
    the same way as the chat payload to keep injection surface identical.
    """
    redacted_meta = _redact_metadata(record, trail_name=trail_name)
    return {
        "review_instructions": prompt,
        "thought_under_review": html.escape(record.content, quote=False),
        "thought_metadata": html.escape(
            yaml.dump(redacted_meta, default_flow_style=False, sort_keys=False),
            quote=False,
        ),
    }


async def review_thought_decisions(
    record: ThoughtRecord,
    prompt: str,
    model: str,
    client: DecisionsClient,
    *,
    question: str,
    threshold: float,
    trail_name: str | None = None,
) -> TrustResult:
    """Review a thought through OpenRouter Decisions (Jev) with one Noul question.

    Approves when the returned Noul probability is at or above ``threshold``;
    rejects when it is below. Jev returns no reasoning, so the recorded
    reasoning is a factual statement of the probability and threshold — never
    fabricated model rationale. Every transport, contract, or range failure
    fails closed with verdict ``error`` and never contacts another reviewer.
    """
    _validate_decisions_review_inputs(question, threshold)
    threshold = float(threshold)

    reviewer_id = f"decisions:{model}"
    provider = getattr(client, "provider", None)
    state = _build_decisions_state(prompt, record, trail_name=trail_name)

    try:
        answer = await client.ask_noul(model=model, state=state, question=question)
    except DecisionsError as e:
        return TrustResult(
            verdict="error",
            reasoning=f"Decisions review failed closed: {e}",
            reviewer=reviewer_id,
            provider=provider,
            model=model,
            policy="decisions",
            threshold=threshold,
        )
    except Exception as e:
        # Sanitize through the established provider-exception boundary: raw
        # exception text can embed URLs with userinfo/query/path credentials,
        # and durable Trust Gate provenance must never repeat it (#124).
        return TrustResult(
            verdict="error",
            reasoning=f"Unexpected error: {sanitize_provider_exception(e)}",
            reviewer=reviewer_id,
            provider=provider,
            model=model,
            policy="decisions",
            threshold=threshold,
        )

    approved = answer.probability >= threshold
    if approved:
        reasoning = (
            f"Jev Noul probability {answer.probability} is at or above the "
            f"configured threshold {threshold}. The Decisions response carries "
            "no reasoning; none is fabricated."
        )
    else:
        reasoning = (
            f"Jev Noul probability {answer.probability} is below the configured "
            f"threshold {threshold}. The Decisions response carries no reasoning; "
            "none is fabricated."
        )

    return TrustResult(
        verdict="approve" if approved else "reject",
        reasoning=reasoning,
        reviewer=reviewer_id,
        # Persist the configured reviewer provider (the transmission destination,
        # e.g. "openrouter"); the served model snapshot records what answered.
        provider=provider or answer.provider,
        model=answer.model or model,
        policy="decisions",
        noul_probability=answer.probability,
        threshold=threshold,
    )

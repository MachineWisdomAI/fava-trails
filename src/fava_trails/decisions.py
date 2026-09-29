"""OpenRouter Decisions (Jev) transport for the Trust Gate ``decisions`` policy.

Speaks the Decisions API contract (POST {api_base}/alpha/decisions) with an
OpenRouter bearer credential, an exact model identifier or alias (e.g.
``typesafe/jev-1.13`` or ``~typesafe/jev-latest``), a ``state`` payload, and
one typed Noul question. The response is a typed answer — never chat-completion
output — shaped like::

    {"model": "...", "answers": {"trust": {"type": "noul", "noul": 0.93}},
     "usage": {...}, "id": "...", "provider": "..."}

All failures (HTTP status, connection, timeout, malformed body, missing or
out-of-range probability) raise ``DecisionsError`` so callers fail closed
without contacting another reviewer.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_DECISIONS_API_BASE = "https://openrouter.ai/api"
DECISIONS_API_PATH = "/alpha/decisions"
# Key of the single typed Noul question submitted per review.
DECISIONS_QUESTION_KEY = "trust"
DEFAULT_DECISIONS_MODEL = "typesafe/jev-1.13"


class DecisionsError(Exception):
    """Transport or contract failure on the Decisions endpoint (fail closed)."""


@dataclass
class NoulAnswer:
    """Validated Noul answer plus non-secret response provenance."""

    probability: float
    provider: str | None = None
    model: str | None = None
    response_id: str | None = None


def decisions_endpoint(api_base: str | None) -> str:
    """Return the Decisions API URL for a configured (or default) API base."""
    base = (api_base or DEFAULT_DECISIONS_API_BASE).rstrip("/")
    return base + DECISIONS_API_PATH


def describe_trust_gate_egress(api_base: str | None) -> str:
    """Secret-free egress disclosure for startup diagnostics.

    Identifies remote OpenRouter transmission accurately; a custom api_base is
    disclosed as the configured destination instead.
    """
    endpoint = decisions_endpoint(api_base)
    if endpoint.startswith(DEFAULT_DECISIONS_API_BASE):
        return (
            "thought content and selected metadata are transmitted to remote "
            f"OpenRouter for Decisions review ({endpoint})"
        )
    return (
        "thought content and selected metadata are transmitted to the "
        f"configured Decisions endpoint ({endpoint})"
    )


class DecisionsClient:
    """Async client for one Noul question per call against the Decisions API.

    Mirrors ``LLMClient`` credential semantics: an ``api_key_loader`` re-reads
    the configured credential per request (supporting rotation), and no secret
    ever appears in raised error messages.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_loader: Callable[[], str] | None = None,
        api_base: str | None = None,
        provider: str = "openrouter",
        timeout: float = 60.0,
    ) -> None:
        if api_key is None and api_key_loader is None:
            raise DecisionsError("Decisions API credential required but not provided")
        self._api_key = api_key
        self._api_key_loader = api_key_loader
        self._api_base = api_base
        self._provider = provider
        self._timeout = timeout

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def endpoint(self) -> str:
        return decisions_endpoint(self._api_base)

    def _load_api_key(self) -> str:
        if self._api_key_loader is None:
            key = self._api_key
        else:
            try:
                key = self._api_key_loader()
            except Exception as exc:
                raise DecisionsError("Decisions API credential unavailable") from exc
        if not key:
            raise DecisionsError("Decisions API credential unavailable")
        return key

    async def ask_noul(
        self,
        *,
        model: str,
        state: dict[str, Any] | str,
        question: str,
    ) -> NoulAnswer:
        """Submit one typed Noul question and return the validated answer.

        The model identifier is forwarded exactly as configured (pinned id or
        ``~``-alias); no registry rewriting is applied.
        """
        if not model or not model.strip():
            raise DecisionsError("Decisions model identifier must be non-empty")
        if not question or not question.strip():
            raise DecisionsError("Noul question must be non-empty before transmission")

        payload = {
            "model": model,
            "state": state,
            "questions": {
                DECISIONS_QUESTION_KEY: {"type": "noul", "instructions": question},
            },
        }
        api_key = self._load_api_key()
        # Explicit timeout phases: a scalar timeout leaves connect/pool unbounded.
        httpx_timeout = httpx.Timeout(
            connect=10.0,
            read=self._timeout,
            write=self._timeout,
            pool=10.0,
        )
        try:
            async with httpx.AsyncClient(timeout=httpx_timeout) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise DecisionsError(f"Decisions request timed out: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise DecisionsError(
                f"Decisions connection error: {type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            raise DecisionsError(f"Decisions API HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise DecisionsError("Decisions response is not valid JSON") from exc

        return _parse_noul_answer(body)


def _parse_noul_answer(body: Any) -> NoulAnswer:
    """Validate the Decisions response contract and extract the Noul answer.

    Never fabricates reasoning or substitutes defaults: any deviation from the
    contract raises ``DecisionsError`` so the review fails closed.
    """
    if not isinstance(body, dict):
        raise DecisionsError("Decisions response is not a JSON object")
    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise DecisionsError("Decisions response is missing an 'answers' object")
    answer = answers.get(DECISIONS_QUESTION_KEY)
    if not isinstance(answer, dict):
        raise DecisionsError(
            f"Decisions response is missing the '{DECISIONS_QUESTION_KEY}' answer"
        )
    if answer.get("type") != "noul":
        raise DecisionsError(
            f"Decisions answer has unexpected type {answer.get('type')!r}; expected 'noul'"
        )
    probability = answer.get("noul")
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        raise DecisionsError("Decisions answer is missing a numeric Noul probability")
    probability = float(probability)
    if not math.isfinite(probability):
        raise DecisionsError("Decisions Noul probability is not finite")
    if not (0.0 <= probability <= 1.0):
        raise DecisionsError(
            f"Decisions Noul probability {probability} is outside [0, 1]"
        )

    provider = body.get("provider")
    model = body.get("model")
    response_id = body.get("id")
    return NoulAnswer(
        probability=probability,
        provider=provider if isinstance(provider, str) else None,
        model=model if isinstance(model, str) else None,
        response_id=response_id if isinstance(response_id, str) else None,
    )

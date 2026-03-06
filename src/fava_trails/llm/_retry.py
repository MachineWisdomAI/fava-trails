"""Async retry utility for LLM API calls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import openai

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default retry config
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_DELAYS = [1.0, 3.0]

# Exception types that warrant a retry (transient errors)
RETRYABLE_EXCEPTIONS = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


async def async_retry(
    fn: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    delays: list[float] | None = None,
    **kwargs: Any,
) -> T:
    """Call an async function with retry on transient errors.

    Raises the last exception if all attempts fail.
    Non-retryable exceptions (e.g. AuthenticationError, BadRequestError) propagate immediately.
    """
    delays = delays or DEFAULT_DELAYS
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await fn(*args, **kwargs)
        except RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            if attempt < max_attempts - 1:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(
                    "LLM API call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("LLM API call failed after %d attempts: %s", max_attempts, e)

    raise last_exc  # type: ignore[misc]

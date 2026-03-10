"""Async LLM client with multi-provider support via any-llm-sdk."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import any_llm
import httpx

from ._retry import async_retry
from .registry import get_registry

# Enable unified exception hierarchy across all providers
os.environ.setdefault("ANY_LLM_UNIFIED_EXCEPTIONS", "1")

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised for unrecoverable LLM client errors."""


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict | None = None


class LLMClient:
    """Async LLM client that routes requests through OpenRouter via any-llm-sdk."""

    def __init__(
        self,
        openrouter_api_key: str | None = None,
    ) -> None:
        self._openrouter_api_key = openrouter_api_key

    async def chat(
        self,
        messages: list[dict],
        model: str,
        *,
        temperature: float | int = 0,
        response_format: dict | None = None,
        max_output_tokens: int | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        """Send a chat completion request.

        Resolves model aliases, routes to OpenRouter via any-llm-sdk, strips
        temperature for models that don't support it, and retries on
        transient errors.
        """
        if not self._openrouter_api_key:
            raise LLMError("OpenRouter API key required but not provided")

        registry = get_registry()
        info = registry.resolve(model)

        if info is not None:
            resolved_model = info.model_name
        else:
            resolved_model = model

        # Build kwargs
        kwargs: dict = {}

        # Strip temperature if model doesn't support it
        if info is None or info.supports_temperature:
            kwargs["temperature"] = temperature

        if response_format is not None:
            kwargs["response_format"] = response_format

        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens

        async def _do_call() -> LLMResponse:
            # Use explicit httpx.Timeout phases to ensure all timeout types are set.
            # A scalar timeout only sets the total/read timeout; connect and pool
            # timeouts may default to None (infinite), leaving a hang vector.
            httpx_timeout = httpx.Timeout(
                connect=10.0,
                read=timeout,
                write=timeout,
                pool=10.0,
            )
            response = await any_llm.acompletion(
                model=resolved_model,
                provider="openrouter",
                messages=messages,
                api_key=self._openrouter_api_key,
                client_args={"timeout": httpx_timeout},
                **kwargs,
            )
            choice = response.choices[0] if response.choices else None
            content = choice.message.content if choice and choice.message else ""

            usage_dict = None
            if response.usage:
                usage_dict = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            return LLMResponse(
                content=content or "",
                model=response.model or resolved_model,
                usage=usage_dict,
            )

        return await async_retry(_do_call)

"""Async LLM client with multi-provider support via any-llm-sdk."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

import any_llm
import httpx
from any_llm.exceptions import AuthenticationError

from ._retry import async_retry
from .registry import get_registry

# Enable unified exception hierarchy across all providers
os.environ.setdefault("ANY_LLM_UNIFIED_EXCEPTIONS", "1")

# Relax service_tier validation. OpenRouter may return values outside the
# OpenAI SDK Literal set, e.g. "standard", and any-llm revalidates the response
# against this model before returning it.
from any_llm.types.completion import ChatCompletion as _ChatCompletion

_service_tier = _ChatCompletion.model_fields.get("service_tier")
if _service_tier is not None:
    _service_tier.annotation = str | None
    _ChatCompletion.model_rebuild(force=True)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised for unrecoverable LLM client errors."""


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict | None = None
    provider: str | None = None


class LLMClient:
    """Async LLM client that routes requests via any-llm-sdk.

    Defaults to OpenRouter for backward compatibility. Operators can point the
    Trust Gate at any OpenAI-compatible endpoint (e.g. Unsloth Studio) by
    setting provider + api_base + api_key.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        provider: str = "openrouter",
        api_base: str | None = None,
        openrouter_api_key: str | None = None,
        api_key_loader: Callable[[], str] | None = None,
        extra_body: dict | None = None,
    ) -> None:
        # openrouter_api_key is retained as a backward-compatible alias.
        self._api_key = api_key if api_key is not None else openrouter_api_key
        self._provider = provider
        self._api_base = api_base
        self._api_key_loader = api_key_loader
        self._extra_body = dict(extra_body or {})

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def api_base(self) -> str | None:
        return self._api_base

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

        Routes via any-llm-sdk with the configured provider/api_base. OpenRouter
        (default, no custom api_base) still resolves friendly aliases through the
        bundled registry. Non-OpenRouter providers and custom api_base targets
        forward the exact configured model identifier so local servers (e.g.
        Unsloth Studio) receive the ID they actually expose.
        """
        if not self._api_key and self._api_key_loader is None:
            raise LLMError("LLM API key required but not provided")

        # OpenRouter-oriented alias registry must not rewrite local/custom IDs
        # (e.g. gpt-4.1-mini -> openai/gpt-4.1-mini breaks a Studio serve path).
        use_openrouter_aliases = self._provider == "openrouter" and self._api_base is None
        info = None
        if use_openrouter_aliases:
            info = get_registry().resolve(model)
            resolved_model = info.model_name if info is not None else model
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

        if self._api_base is not None:
            kwargs["api_base"] = self._api_base

        if self._extra_body:
            kwargs["extra_body"] = dict(self._extra_body)

        def _load_api_key() -> str | None:
            if self._api_key_loader is None:
                return self._api_key
            try:
                return self._api_key_loader()
            except Exception as exc:
                raise LLMError("LLM API credential unavailable") from exc

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
            api_key = _load_api_key()

            async def _request(key: str | None):
                return await any_llm.acompletion(
                    model=resolved_model,
                    provider=self._provider,
                    messages=messages,
                    api_key=key,
                    client_args={"timeout": httpx_timeout},
                    **kwargs,
                )

            try:
                response = await _request(api_key)
            except AuthenticationError:
                if self._api_key_loader is None:
                    raise
                rotated_key = _load_api_key()
                if rotated_key == api_key:
                    raise
                response = await _request(rotated_key)
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
                provider=self._provider,
            )

        return await async_retry(_do_call)

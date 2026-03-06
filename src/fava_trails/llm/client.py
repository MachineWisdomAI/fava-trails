"""Async LLM client with multi-provider support via the OpenAI SDK."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import openai

from ._retry import async_retry
from .registry import get_registry

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMError(Exception):
    """Raised for unrecoverable LLM client errors."""


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict | None = None


class LLMClient:
    """Async LLM client that routes requests to OpenRouter or OpenAI direct."""

    def __init__(
        self,
        openrouter_api_key: str | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        self._openrouter_api_key = openrouter_api_key
        self._openai_api_key = openai_api_key
        self._clients: dict[str, openai.AsyncOpenAI] = {}

    def _get_client(self, provider: str) -> openai.AsyncOpenAI:
        """Get or create an AsyncOpenAI client for the given provider."""
        if provider in self._clients:
            return self._clients[provider]

        if provider == "openai":
            if not self._openai_api_key:
                raise LLMError("OpenAI API key required but not provided")
            client = openai.AsyncOpenAI(api_key=self._openai_api_key)
        else:
            # Default to OpenRouter for unknown providers too
            if not self._openrouter_api_key:
                raise LLMError("OpenRouter API key required but not provided")
            client = openai.AsyncOpenAI(
                api_key=self._openrouter_api_key,
                base_url=OPENROUTER_BASE_URL,
                default_headers={
                    "HTTP-Referer": "https://github.com/MachineWisdomAI/fava-trails",
                    "X-Title": "FAVA Trails",
                },
            )

        self._clients[provider] = client
        return client

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

        Resolves model aliases, routes to the correct provider, strips
        temperature for models that don't support it, and retries on
        transient errors.
        """
        registry = get_registry()
        info = registry.resolve(model)

        if info is not None:
            resolved_model = info.model_name
            provider = info.provider
        else:
            # Unknown model — default to OpenRouter (catch-all)
            resolved_model = model
            provider = "openrouter"
            info = None

        client = self._get_client(provider)

        # Build kwargs
        kwargs: dict = {
            "model": resolved_model,
            "messages": messages,
            "timeout": timeout,
        }

        # Strip temperature if model doesn't support it
        if info is None or info.supports_temperature:
            kwargs["temperature"] = temperature

        if response_format is not None:
            kwargs["response_format"] = response_format

        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens

        async def _do_call() -> LLMResponse:
            response = await client.chat.completions.create(**kwargs)
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

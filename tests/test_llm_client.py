"""Tests for LLM client — alias resolution, retry logic, and chat interface."""

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from fava_trails.llm.client import LLMClient, LLMError, LLMResponse


@pytest.fixture
def client():
    return LLMClient(openrouter_api_key="or-key")


def _mock_completion(content: str = '{"verdict":"approve"}', model: str = "test-model"):
    """Create a mock ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 20
    usage.total_tokens = 30
    resp = MagicMock()
    resp.choices = [choice]
    resp.model = model
    resp.usage = usage
    return resp


@pytest.mark.asyncio
async def test_chat_happy_path(client):
    """chat() returns LLMResponse with correct fields."""
    mock_resp = _mock_completion("Hello!", "google/gemini-2.5-flash")

    with patch("fava_trails.llm.client.any_llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = mock_resp

        result = await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash",
        )

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello!"
    assert result.model == "google/gemini-2.5-flash"
    assert result.usage["total_tokens"] == 30


@pytest.mark.asyncio
async def test_unknown_model_uses_openrouter(client):
    """Unknown models are passed through to OpenRouter."""
    mock_resp = _mock_completion("response", "unknown/model")

    with patch("fava_trails.llm.client.any_llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = mock_resp

        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="unknown/some-new-model",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["provider"] == "openrouter"
    assert call_kwargs["model"] == "unknown/some-new-model"


@pytest.mark.asyncio
async def test_temperature_stripped_for_unsupported_model(client):
    """Temperature param is omitted for models that don't support it."""
    mock_resp = _mock_completion("ok", "openai/o3-mini")

    with patch("fava_trails.llm.client.any_llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = mock_resp

        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="openai/o3-mini",
            temperature=0.5,
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert "temperature" not in call_kwargs


@pytest.mark.asyncio
async def test_temperature_included_for_supported_model(client):
    """Temperature param is included for models that support it."""
    mock_resp = _mock_completion("ok", "google/gemini-2.5-flash")

    with patch("fava_trails.llm.client.any_llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = mock_resp

        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash",
            temperature=0,
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["temperature"] == 0


@pytest.mark.asyncio
async def test_retry_on_transient_error(client):
    """Retry logic fires on transient API errors."""
    mock_resp = _mock_completion("ok")

    with patch("fava_trails.llm.client.any_llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        # First call raises a retryable error, second succeeds
        mock_acompletion.side_effect = [
            openai.RateLimitError(
                "rate limit",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            ),
            mock_resp,
        ]

        with patch("fava_trails.llm._retry.asyncio.sleep", new_callable=AsyncMock):
            result = await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="google/gemini-2.5-flash",
            )

    assert result.content == "ok"
    assert mock_acompletion.call_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_auth_error(client):
    """Non-retryable errors propagate immediately."""
    with patch("fava_trails.llm.client.any_llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.side_effect = openai.AuthenticationError(
            "bad key",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        )

        with pytest.raises(openai.AuthenticationError):
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="google/gemini-2.5-flash",
            )

    assert mock_acompletion.call_count == 1


@pytest.mark.asyncio
async def test_missing_openrouter_key():
    """Missing OpenRouter key raises LLMError on chat()."""
    client = LLMClient(openrouter_api_key=None)
    with pytest.raises(LLMError, match="OpenRouter API key"):
        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash",
        )


@pytest.mark.asyncio
async def test_api_key_passed_to_acompletion(client):
    """The openrouter_api_key is forwarded to acompletion."""
    mock_resp = _mock_completion("ok")

    with patch("fava_trails.llm.client.any_llm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = mock_resp

        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash",
        )

    call_kwargs = mock_acompletion.call_args.kwargs
    assert call_kwargs["api_key"] == "or-key"
    assert call_kwargs["provider"] == "openrouter"

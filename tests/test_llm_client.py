"""Tests for LLM client — provider routing, retry logic, and chat interface."""

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from fava_trails.llm.client import OPENROUTER_BASE_URL, LLMClient, LLMError, LLMResponse


@pytest.fixture
def client():
    return LLMClient(openrouter_api_key="or-key", openai_api_key="oai-key")


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

    with patch.object(client, "_get_client") as mock_get:
        mock_oai = AsyncMock()
        mock_oai.chat.completions.create.return_value = mock_resp
        mock_get.return_value = mock_oai

        result = await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash",
        )

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello!"
    assert result.model == "google/gemini-2.5-flash"
    assert result.usage["total_tokens"] == 30


@pytest.mark.asyncio
async def test_openrouter_provider_routing(client):
    """OpenRouter models get routed to OpenRouter base URL."""
    oai_client = client._get_client("openrouter")
    assert oai_client.base_url == f"{OPENROUTER_BASE_URL}/"


@pytest.mark.asyncio
async def test_openai_provider_routing(client):
    """OpenAI models get routed to default OpenAI base URL."""
    oai_client = client._get_client("openai")
    # Default OpenAI base URL
    assert "openrouter" not in str(oai_client.base_url)


@pytest.mark.asyncio
async def test_unknown_model_defaults_to_openrouter(client):
    """Unknown models default to OpenRouter."""
    mock_resp = _mock_completion("response", "unknown/model")

    with patch.object(client, "_get_client") as mock_get:
        mock_oai = AsyncMock()
        mock_oai.chat.completions.create.return_value = mock_resp
        mock_get.return_value = mock_oai

        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="unknown/some-new-model",
        )

    mock_get.assert_called_with("openrouter")


@pytest.mark.asyncio
async def test_temperature_stripped_for_unsupported_model(client):
    """Temperature param is omitted for models that don't support it."""
    mock_resp = _mock_completion("ok", "openai/o3-mini")

    with patch.object(client, "_get_client") as mock_get:
        mock_oai = AsyncMock()
        mock_oai.chat.completions.create.return_value = mock_resp
        mock_get.return_value = mock_oai

        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="openai/o3-mini",
            temperature=0.5,
        )

    call_kwargs = mock_oai.chat.completions.create.call_args.kwargs
    assert "temperature" not in call_kwargs


@pytest.mark.asyncio
async def test_temperature_included_for_supported_model(client):
    """Temperature param is included for models that support it."""
    mock_resp = _mock_completion("ok", "google/gemini-2.5-flash")

    with patch.object(client, "_get_client") as mock_get:
        mock_oai = AsyncMock()
        mock_oai.chat.completions.create.return_value = mock_resp
        mock_get.return_value = mock_oai

        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="google/gemini-2.5-flash",
            temperature=0,
        )

    call_kwargs = mock_oai.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0


@pytest.mark.asyncio
async def test_retry_on_transient_error(client):
    """Retry logic fires on transient API errors."""
    mock_resp = _mock_completion("ok")

    with patch.object(client, "_get_client") as mock_get:
        mock_oai = AsyncMock()
        # First call fails, second succeeds
        mock_oai.chat.completions.create.side_effect = [
            openai.APIConnectionError(request=MagicMock()),
            mock_resp,
        ]
        mock_get.return_value = mock_oai

        with patch("fava_trails.llm._retry.asyncio.sleep", new_callable=AsyncMock):
            result = await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="google/gemini-2.5-flash",
            )

    assert result.content == "ok"
    assert mock_oai.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_no_retry_on_auth_error(client):
    """Non-retryable errors propagate immediately."""
    with patch.object(client, "_get_client") as mock_get:
        mock_oai = AsyncMock()
        mock_oai.chat.completions.create.side_effect = openai.AuthenticationError(
            "bad key",
            response=MagicMock(status_code=401, headers={}),
            body=None,
        )
        mock_get.return_value = mock_oai

        with pytest.raises(openai.AuthenticationError):
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                model="google/gemini-2.5-flash",
            )

    assert mock_oai.chat.completions.create.call_count == 1


def test_missing_openrouter_key():
    """Missing OpenRouter key raises LLMError."""
    client = LLMClient(openrouter_api_key=None, openai_api_key="oai-key")
    with pytest.raises(LLMError, match="OpenRouter API key"):
        client._get_client("openrouter")


def test_missing_openai_key():
    """Missing OpenAI key raises LLMError."""
    client = LLMClient(openrouter_api_key="or-key", openai_api_key=None)
    with pytest.raises(LLMError, match="OpenAI API key"):
        client._get_client("openai")


@pytest.mark.asyncio
async def test_client_caching(client):
    """Clients are cached — same provider returns same instance."""
    c1 = client._get_client("openrouter")
    c2 = client._get_client("openrouter")
    assert c1 is c2

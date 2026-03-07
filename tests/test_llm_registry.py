"""Tests for LLM model registry and alias resolution."""

import json
from pathlib import Path

from fava_trails.llm.registry import ModelInfo, ModelRegistry


def test_registry_loads_from_json():
    """Registry loads 7 models from the bundled JSON file (no provider field)."""
    registry = ModelRegistry.from_json()
    info = registry.resolve("google/gemini-2.5-flash")
    assert info is not None
    assert info.model_name == "google/gemini-2.5-flash"
    assert not hasattr(info, "provider")


def test_registry_has_exactly_seven_entries():
    """Registry has exactly 7 models after removing direct-OpenAI duplicates."""
    registry = ModelRegistry.from_json()
    assert len(registry._models) == 7


def test_alias_resolution_case_insensitive():
    """Alias resolution is case-insensitive."""
    registry = ModelRegistry.from_json()
    info = registry.resolve("Gemini-Flash")
    assert info is not None
    assert info.model_name == "google/gemini-2.5-flash"

    info2 = registry.resolve("GEMINI-FLASH")
    assert info2 is not None
    assert info2.model_name == "google/gemini-2.5-flash"


def test_canonical_name_resolution():
    """Canonical model names resolve correctly."""
    registry = ModelRegistry.from_json()
    info = registry.resolve("google/gemini-2.5-flash")
    assert info is not None
    assert info.model_name == "google/gemini-2.5-flash"


def test_unknown_model_returns_none():
    """Unknown model returns None."""
    registry = ModelRegistry.from_json()
    assert registry.resolve("nonexistent/model-999") is None


def test_bare_model_names_route_via_openrouter():
    """Bare model names (without openai/ prefix) resolve to OpenRouter variants via aliases."""
    registry = ModelRegistry.from_json()
    # gpt-4.1-mini alias still resolves but now points to openai/gpt-4.1-mini (OpenRouter)
    info = registry.resolve("gpt-4.1-mini")
    assert info is not None
    assert info.model_name == "openai/gpt-4.1-mini"


def test_openrouter_openai_models_present():
    """OpenAI models via OpenRouter (with prefix) are still available."""
    registry = ModelRegistry.from_json()
    assert registry.resolve("openai/gpt-4.1-mini") is not None
    assert registry.resolve("openai/gpt-4.1") is not None
    assert registry.resolve("openai/o3-mini") is not None


def test_supports_temperature_false():
    """Models with supports_temperature=false are correctly loaded."""
    registry = ModelRegistry.from_json()
    info = registry.resolve("openai/o3-mini")
    assert info is not None
    assert info.supports_temperature is False


def test_register_custom_model():
    """Custom models can be registered without provider field."""
    registry = ModelRegistry()
    registry.register(ModelInfo(
        model_name="custom/test-model",
        aliases=["test"],
    ))
    info = registry.resolve("test")
    assert info is not None
    assert info.model_name == "custom/test-model"


def test_from_json_with_custom_path(tmp_path):
    """Registry can load from a custom JSON file; provider field is ignored."""
    custom = tmp_path / "models.json"
    custom.write_text(json.dumps({
        "models": [{
            "model_name": "test/model",
            "aliases": ["tm"],
            "supports_json_mode": True,
            "supports_temperature": True,
        }]
    }))
    registry = ModelRegistry.from_json(custom)
    assert registry.resolve("tm") is not None
    assert registry.resolve("tm").model_name == "test/model"


def test_from_json_missing_file():
    """Missing JSON file produces empty registry (doesn't crash)."""
    registry = ModelRegistry.from_json(Path("/nonexistent/models.json"))
    assert registry.resolve("anything") is None

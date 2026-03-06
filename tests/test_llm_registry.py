"""Tests for LLM model registry and alias resolution."""

import json
from pathlib import Path

from fava_trails.llm.registry import ModelInfo, ModelRegistry


def test_registry_loads_from_json():
    """Registry loads models from the bundled JSON file."""
    registry = ModelRegistry.from_json()
    # Should have loaded some models
    info = registry.resolve("google/gemini-2.5-flash")
    assert info is not None
    assert info.model_name == "google/gemini-2.5-flash"
    assert info.provider == "openrouter"


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


def test_openai_provider_models():
    """OpenAI-provider models are correctly registered."""
    registry = ModelRegistry.from_json()
    info = registry.resolve("gpt-4.1-mini")
    assert info is not None
    assert info.provider == "openai"


def test_supports_temperature_false():
    """Models with supports_temperature=false are correctly loaded."""
    registry = ModelRegistry.from_json()
    info = registry.resolve("openai/o3-mini")
    assert info is not None
    assert info.supports_temperature is False


def test_register_custom_model():
    """Custom models can be registered."""
    registry = ModelRegistry()
    registry.register(ModelInfo(
        model_name="custom/test-model",
        aliases=["test"],
        provider="openrouter",
    ))
    info = registry.resolve("test")
    assert info is not None
    assert info.model_name == "custom/test-model"


def test_from_json_with_custom_path(tmp_path):
    """Registry can load from a custom JSON file."""
    custom = tmp_path / "models.json"
    custom.write_text(json.dumps({
        "models": [{
            "model_name": "test/model",
            "aliases": ["tm"],
            "provider": "openrouter",
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

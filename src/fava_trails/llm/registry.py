"""Model registry with alias resolution for LLM client."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_REGISTRY_FILE = Path(__file__).parent / "models_registry.json"


@dataclass
class ModelInfo:
    model_name: str
    aliases: list[str] = field(default_factory=list)
    supports_json_mode: bool = True
    supports_temperature: bool = True
    max_output_tokens: int | None = None


class ModelRegistry:
    """Registry of known models with alias resolution."""

    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}
        self._aliases: dict[str, str] = {}  # lowercase alias -> model_name

    def register(self, info: ModelInfo) -> None:
        self._models[info.model_name] = info
        self._aliases[info.model_name.lower()] = info.model_name
        for alias in info.aliases:
            self._aliases[alias.lower()] = info.model_name

    def resolve(self, name_or_alias: str) -> ModelInfo | None:
        """Resolve a model name or alias to ModelInfo. Case-insensitive."""
        key = name_or_alias.lower()
        model_name = self._aliases.get(key)
        if model_name:
            return self._models[model_name]
        return None

    @classmethod
    def from_json(cls, path: Path | None = None) -> ModelRegistry:
        """Load registry from the bundled JSON file."""
        path = path or _REGISTRY_FILE
        registry = cls()
        try:
            data = json.loads(path.read_text())
            for entry in data.get("models", []):
                info = ModelInfo(
                    model_name=entry["model_name"],
                    aliases=entry.get("aliases", []),
                    supports_json_mode=entry.get("supports_json_mode", True),
                    supports_temperature=entry.get("supports_temperature", True),
                    max_output_tokens=entry.get("max_output_tokens"),
                )
                registry.register(info)
            logger.debug("Loaded %d models from registry", len(registry._models))
        except Exception:
            logger.warning("Failed to load model registry from %s", path, exc_info=True)
        return registry


# Module-level singleton, loaded once on import
_default_registry: ModelRegistry | None = None


def get_registry() -> ModelRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ModelRegistry.from_json()
    return _default_registry

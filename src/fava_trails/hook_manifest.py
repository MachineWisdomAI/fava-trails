"""Manifest-based hook registration.

Hooks are declared in hooks.yaml and loaded once at startup.
Supports module: (PyPI packages) and path: (local files/dirs).
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, field_validator, model_validator

logger = logging.getLogger(__name__)

KNOWN_HOOKS = frozenset({
    "before_save",
    "after_save",
    "before_propose",
    "after_propose",
    "after_supersede",
    "on_recall",
    "on_startup",
})

DEFAULT_TIMEOUTS: dict[str, float] = {
    "on_recall": 2.0,
    "before_save": 5.0,
    "after_save": 5.0,
    "before_propose": 5.0,
    "after_propose": 5.0,
    "after_supersede": 5.0,
    "on_startup": 10.0,
}

# Regex for ${VAR_NAME} env var interpolation
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively interpolate ${VAR} in string values from os.environ."""
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var = match.group(1)
            val = os.environ.get(var)
            if val is None:
                raise ValueError(f"Environment variable ${{{var}}} is not set (required by hooks.yaml)")
            return val
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


# --- Pydantic Manifest Models ---


class HookEntry(BaseModel):
    """A single hook entry in hooks.yaml."""
    module: str | None = None
    path: str | None = None
    points: list[str]
    order: int = 50
    fail_mode: str = "open"
    config: dict[str, Any] = {}

    @model_validator(mode="after")
    def exactly_one_source(self) -> HookEntry:
        if self.module and self.path:
            raise ValueError("Hook entry must have either 'module' or 'path', not both")
        if not self.module and not self.path:
            raise ValueError("Hook entry must have either 'module' or 'path'")
        return self

    @field_validator("points")
    @classmethod
    def validate_points(cls, v: list[str]) -> list[str]:
        for p in v:
            if p not in KNOWN_HOOKS:
                raise ValueError(f"Unknown lifecycle point: {p!r}. Valid: {sorted(KNOWN_HOOKS)}")
        return v

    @field_validator("fail_mode")
    @classmethod
    def validate_fail_mode(cls, v: str) -> str:
        if v not in ("open", "closed"):
            raise ValueError(f"fail_mode must be 'open' or 'closed', got {v!r}")
        return v


class HookManifest(BaseModel):
    """Top-level hooks.yaml schema."""
    hooks: list[HookEntry] = []


# --- HookSpec (loaded hook ready for execution) ---


@dataclass
class HookSpec:
    """A loaded hook function with its configuration."""
    name: str                    # lifecycle point name
    fn: Callable[..., Any]       # the async hook function
    fail_mode: str = "open"
    timeout: float = 5.0
    order: int = 50
    config: dict[str, Any] = field(default_factory=dict)
    source: str = ""             # module path or file path for audit


# --- HookRegistry ---


class HookRegistry:
    """Registry of lifecycle hooks, loaded from hooks.yaml manifest.

    Loaded once at startup (anti-tampering pattern).
    Supports multiple hooks per lifecycle point, ordered by 'order' field.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookSpec]] = {}

    def load_from_manifest(self, manifest_path: Path) -> None:
        """Load hooks from a hooks.yaml manifest file.

        If the file doesn't exist, no hooks are loaded (zero overhead path).
        """
        self._hooks.clear()

        if not manifest_path.exists():
            logger.debug("No hooks manifest at %s — skipping", manifest_path)
            return

        try:
            raw = yaml.safe_load(manifest_path.read_text()) or {}
            manifest = HookManifest(**raw)
        except Exception:
            logger.error("Failed to parse hooks manifest %s", manifest_path, exc_info=True)
            return

        for entry in manifest.hooks:
            try:
                # Interpolate env vars in config
                config = _interpolate_env(entry.config)
            except ValueError:
                logger.error("Env var interpolation failed for hook entry", exc_info=True)
                if entry.fail_mode == "closed":
                    raise SystemExit(1)
                continue

            # Resolve module
            try:
                mod = self._resolve_module(entry, manifest_path.parent)
            except Exception:
                logger.error("Failed to load hook module", exc_info=True)
                if entry.fail_mode == "closed":
                    raise SystemExit(1)
                continue

            # Config injection
            configure_fn = getattr(mod, "configure", None)
            if configure_fn and callable(configure_fn):
                try:
                    configure_fn(config)
                except Exception:
                    logger.error("configure() failed for hook", exc_info=True)
                    if entry.fail_mode == "closed":
                        raise SystemExit(1)
                    continue

            # Register each declared lifecycle point
            source = entry.module or entry.path or "unknown"
            for point in entry.points:
                fn = getattr(mod, point, None)
                if fn is None or not callable(fn):
                    logger.warning(
                        "Hook %s declares point %r but module has no such function — skipping point",
                        source, point,
                    )
                    continue

                if not inspect.iscoroutinefunction(fn):
                    logger.warning(
                        "Hook %s: function %r is not async — skipping point",
                        source, point,
                    )
                    continue

                spec = HookSpec(
                    name=point,
                    fn=fn,
                    fail_mode=entry.fail_mode,
                    timeout=DEFAULT_TIMEOUTS.get(point, 5.0),
                    order=entry.order,
                    config=config,
                    source=source,
                )
                self._hooks.setdefault(point, []).append(spec)

        # Sort hooks per lifecycle point by order
        for point in self._hooks:
            self._hooks[point].sort(key=lambda s: s.order)

        total = sum(len(v) for v in self._hooks.values())
        logger.info("Hook registry: %d hook(s) loaded across %d lifecycle points", total, len(self._hooks))

    def _resolve_module(self, entry: HookEntry, manifest_dir: Path) -> Any:
        """Resolve a hook entry to a Python module."""
        if entry.module:
            return importlib.import_module(entry.module)

        assert entry.path is not None
        hook_path = Path(entry.path)
        if not hook_path.is_absolute():
            hook_path = manifest_dir / hook_path

        if hook_path.is_file() and hook_path.suffix == ".py":
            spec = importlib.util.spec_from_file_location(
                f"fava_hooks.{hook_path.stem}", hook_path
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create module spec for {hook_path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        if hook_path.is_dir():
            init_file = hook_path / "__init__.py"
            if not init_file.exists():
                raise ImportError(f"Directory {hook_path} has no __init__.py")
            # Add parent to sys.path so the package is importable
            parent_str = str(hook_path.parent)
            if parent_str not in sys.path:
                sys.path.insert(0, parent_str)
            spec = importlib.util.spec_from_file_location(
                hook_path.name, init_file,
                submodule_search_locations=[str(hook_path)],
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create module spec for {hook_path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        raise ImportError(f"Hook path {hook_path} is not a .py file or directory")

    def get_hooks(self, lifecycle_point: str) -> list[HookSpec]:
        """Return hooks for a lifecycle point, ordered by 'order' field."""
        return self._hooks.get(lifecycle_point, [])

    @property
    def has_hooks(self) -> bool:
        """True if any hooks are loaded."""
        return bool(self._hooks)

    @property
    def loaded_hooks(self) -> list[str]:
        """List of lifecycle points with loaded hooks."""
        return list(self._hooks.keys())

    @property
    def all_specs(self) -> list[HookSpec]:
        """All loaded HookSpecs across all lifecycle points."""
        return [s for specs in self._hooks.values() for s in specs]

"""Lifecycle Hooks — operator-defined Python hooks fired at TrailManager lifecycle points.

Hook files live in the data repo's hooks/ directory (or FAVA_TRAILS_HOOKS_DIR).
Loaded once at startup (anti-tampering, same pattern as TrustGatePromptCache).
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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


class HookExecutionError(Exception):
    """Raised when a hook with fail_mode='closed' fails."""


class HookTimeoutError(HookExecutionError):
    """Raised when a hook with fail_mode='closed' times out."""


@dataclass
class HookSpec:
    """A loaded hook: function + configuration."""

    name: str
    fn: Callable[..., Any]
    fail_mode: str = "open"  # "open" or "closed"
    timeout: float = 5.0
    source_path: Path = field(default_factory=lambda: Path("."))


class HookRegistry:
    """Registry of lifecycle hooks, loaded once at startup.

    Mirrors TrustGatePromptCache anti-tampering pattern:
    hooks are loaded from disk once and never re-read.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, HookSpec] = {}

    def load_from_dir(self, hooks_dir: Path) -> None:
        """Discover and load hook files from a directory.

        Only files named after known lifecycle points are loaded.
        common.py is added to sys.path for shared helper imports.
        """
        self._hooks.clear()

        if not hooks_dir.is_dir():
            logger.debug("No hooks directory at %s — skipping", hooks_dir)
            return

        # Add hooks dir to sys.path so common.py is importable
        hooks_dir_str = str(hooks_dir)
        if hooks_dir_str not in sys.path:
            sys.path.insert(0, hooks_dir_str)

        for py_file in sorted(hooks_dir.glob("*.py")):
            stem = py_file.stem
            if stem == "common" or stem.startswith("_"):
                continue
            if stem not in KNOWN_HOOKS:
                logger.debug("Ignoring unknown hook file: %s", py_file.name)
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"fava_hooks.{stem}", py_file
                )
                if spec is None or spec.loader is None:
                    logger.warning("Could not load hook file %s — skipping", py_file)
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception:
                logger.warning("Hook file %s has errors — skipping", py_file, exc_info=True)
                continue

            hook_fn = getattr(module, "hook", None)
            if hook_fn is None or not callable(hook_fn):
                logger.warning("Hook file %s has no callable hook() — skipping", py_file)
                continue

            if not inspect.iscoroutinefunction(hook_fn):
                logger.warning("Hook file %s: hook() is not async — skipping", py_file)
                continue

            fail_mode = getattr(module, "FAIL_MODE", "open")
            if fail_mode not in ("open", "closed"):
                logger.warning(
                    "Hook %s: invalid FAIL_MODE %r, defaulting to 'open'", stem, fail_mode
                )
                fail_mode = "open"

            timeout = getattr(module, "TIMEOUT", DEFAULT_TIMEOUTS.get(stem, 5.0))

            self._hooks[stem] = HookSpec(
                name=stem,
                fn=hook_fn,
                fail_mode=fail_mode,
                timeout=float(timeout),
                source_path=py_file,
            )
            logger.info("Loaded hook: %s (fail_mode=%s, timeout=%.1fs)", stem, fail_mode, timeout)

        logger.info("Hook registry: %d hook(s) loaded", len(self._hooks))

    def get_hook(self, name: str) -> HookSpec | None:
        return self._hooks.get(name)

    @property
    def loaded_hooks(self) -> list[str]:
        return list(self._hooks.keys())


def build_hook_ctx(
    trail: Any = None,
    config: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the ctx dict passed to every hook."""
    ctx: dict[str, Any] = {
        "hook_api_version": "1.0",
        "trail_name": trail.trail_name if trail else None,
        "config": config or {},
    }
    ctx.update(extra)
    return ctx


async def fire_hook(
    registry: HookRegistry,
    hook_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fire a lifecycle hook. Returns result dict with status."""
    hook = registry.get_hook(hook_name)
    if hook is None:
        return {"status": "no_hook"}

    start = time.monotonic()
    try:
        result = await asyncio.wait_for(hook.fn(**kwargs), timeout=hook.timeout)
        elapsed = time.monotonic() - start
        logger.debug("Hook %s completed in %.3fs", hook_name, elapsed)
        return {"status": "ok", "result": result}

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        logger.warning(
            "Hook %s timed out after %.1fs (limit=%.1fs, fail_mode=%s)",
            hook_name, elapsed, hook.timeout, hook.fail_mode,
        )
        if hook.fail_mode == "closed":
            raise HookTimeoutError(
                f"Hook '{hook_name}' timed out after {hook.timeout}s"
            )
        return {"status": "timeout"}

    except HookExecutionError:
        raise  # Don't double-wrap

    except Exception as e:
        elapsed = time.monotonic() - start
        logger.warning(
            "Hook %s failed after %.3fs: %s: %s (fail_mode=%s)",
            hook_name, elapsed, type(e).__name__, e, hook.fail_mode,
        )
        if hook.fail_mode == "closed":
            raise HookExecutionError(
                f"Hook '{hook_name}' failed: {type(e).__name__}: {e}"
            ) from e
        return {"status": "error", "exception": str(e)}


async def fire_before(registry: HookRegistry, hook_name: str, **kwargs: Any) -> bool:
    """Fire a before_* hook. Returns True to proceed, False to reject."""
    result = await fire_hook(registry, hook_name, **kwargs)
    if result["status"] == "no_hook":
        return True
    if result["status"] in ("timeout", "error"):
        return True  # fail-open already handled
    return result["result"] is not False


async def fire_after(registry: HookRegistry, hook_name: str, **kwargs: Any) -> None:
    """Fire an after_* hook. Return value ignored."""
    await fire_hook(registry, hook_name, **kwargs)


async def fire_recall(
    registry: HookRegistry, results: list[Any], **kwargs: Any
) -> list[Any]:
    """Fire on_recall hook. Returns filtered/reordered results."""
    result = await fire_hook(registry, "on_recall", results=results, **kwargs)
    if result["status"] == "no_hook":
        return results
    if result["status"] in ("timeout", "error"):
        return results
    returned = result.get("result")
    if isinstance(returned, list):
        return returned
    return results

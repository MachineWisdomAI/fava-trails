"""Tests for manifest-based hook registration."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fava_trails.hook_manifest import (
    HookRegistry,
    _interpolate_env,
)
from fava_trails.models import HookEntry


@pytest.fixture
def hook_dir(tmp_path):
    """Create a temporary directory for hook files."""
    return tmp_path


def _write_hook_file(hook_dir: Path, name: str, code: str) -> Path:
    """Write a Python hook file."""
    path = hook_dir / f"{name}.py"
    path.write_text(textwrap.dedent(code))
    return path


# ─── Entry-based Loading ───


class TestEntryLoading:
    def test_empty_entries(self, hook_dir):
        """Empty entries list → no hooks loaded."""
        registry = HookRegistry()
        registry.load_from_entries([], base_dir=hook_dir)
        assert not registry.has_hooks
        assert registry.loaded_hooks == []

    def test_valid_path_entry(self, hook_dir):
        """path: entry resolves local .py file."""
        _write_hook_file(hook_dir, "quality", """
            async def before_save(event):
                return None
        """)
        entry = HookEntry(path="./quality.py", points=["before_save"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert "before_save" in registry.loaded_hooks
        hooks = registry.get_hooks("before_save")
        assert len(hooks) == 1
        assert hooks[0].order == 50  # default

    def test_valid_directory_entry(self, hook_dir):
        """path: entry resolves directory with __init__.py."""
        pkg_dir = hook_dir / "my_hook"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text(textwrap.dedent("""
            async def before_save(event):
                return None
        """))
        entry = HookEntry(path="./my_hook/", points=["before_save"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert "before_save" in registry.loaded_hooks

    def test_multi_point_registration(self, hook_dir):
        """One entry declaring multiple points registers all of them."""
        _write_hook_file(hook_dir, "multi", """
            async def before_save(event):
                return None
            async def after_save(event):
                return None
            async def on_recall(event):
                return None
        """)
        entry = HookEntry(path="./multi.py", points=["before_save", "after_save", "on_recall"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert len(registry.loaded_hooks) == 3

    def test_order_sorting(self, hook_dir):
        """Multiple hooks for same point are sorted by order."""
        _write_hook_file(hook_dir, "hook_a", """
            async def before_save(event):
                return "a"
        """)
        _write_hook_file(hook_dir, "hook_b", """
            async def before_save(event):
                return "b"
        """)
        entries = [
            HookEntry(path="./hook_a.py", points=["before_save"], order=100),
            HookEntry(path="./hook_b.py", points=["before_save"], order=10),
        ]
        registry = HookRegistry()
        registry.load_from_entries(entries, base_dir=hook_dir)
        hooks = registry.get_hooks("before_save")
        assert len(hooks) == 2
        assert hooks[0].order == 10  # hook_b first
        assert hooks[1].order == 100  # hook_a second

    def test_fail_mode_extraction(self, hook_dir):
        """fail_mode from entry is stored on HookSpec."""
        _write_hook_file(hook_dir, "strict", """
            async def before_save(event):
                return None
        """)
        entry = HookEntry(path="./strict.py", points=["before_save"], fail_mode="closed")
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert registry.get_hooks("before_save")[0].fail_mode == "closed"

    def test_get_hooks_empty(self):
        """get_hooks returns empty list for unregistered point."""
        registry = HookRegistry()
        assert registry.get_hooks("before_save") == []

    def test_all_specs(self, hook_dir):
        """all_specs returns flat list of all HookSpecs."""
        _write_hook_file(hook_dir, "multi", """
            async def before_save(event):
                pass
            async def on_recall(event):
                pass
        """)
        entry = HookEntry(path="./multi.py", points=["before_save", "on_recall"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert len(registry.all_specs) == 2


# ─── Config Injection ───


class TestConfigInjection:
    def test_configure_called(self, hook_dir):
        """configure() is called with the config dict."""
        _write_hook_file(hook_dir, "configurable", """
            _config = {}
            def configure(config):
                _config.update(config)
            async def before_save(event):
                return None
        """)
        entry = HookEntry(
            path="./configurable.py",
            points=["before_save"],
            config={"key": "value", "num": 42},
        )
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert "before_save" in registry.loaded_hooks
        # Config is stored on the spec
        assert registry.get_hooks("before_save")[0].config == {"key": "value", "num": 42}

    def test_configure_not_required(self, hook_dir):
        """Hook without configure() still loads fine."""
        _write_hook_file(hook_dir, "simple", """
            async def before_save(event):
                return None
        """)
        entry = HookEntry(path="./simple.py", points=["before_save"], config={"ignored": True})
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert "before_save" in registry.loaded_hooks


# ─── Env Var Interpolation ───


class TestEnvVarInterpolation:
    def test_simple_interpolation(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        assert _interpolate_env("${MY_VAR}") == "hello"

    def test_nested_dict_interpolation(self, monkeypatch):
        monkeypatch.setenv("URL", "http://localhost")
        result = _interpolate_env({"gateway": "${URL}/push"})
        assert result == {"gateway": "http://localhost/push"}

    def test_list_interpolation(self, monkeypatch):
        monkeypatch.setenv("TAG", "prod")
        result = _interpolate_env(["${TAG}", "static"])
        assert result == ["prod", "static"]

    def test_missing_env_var_raises(self):
        with pytest.raises(ValueError, match="NONEXISTENT_VAR.*not set"):
            _interpolate_env("${NONEXISTENT_VAR}")

    def test_no_interpolation_needed(self):
        assert _interpolate_env("plain string") == "plain string"
        assert _interpolate_env(42) == 42

    def test_entry_with_env_vars(self, hook_dir, monkeypatch):
        """End-to-end: env vars in entry config are interpolated."""
        monkeypatch.setenv("HOOK_URL", "http://metrics")
        _write_hook_file(hook_dir, "metrics", """
            _url = None
            def configure(config):
                global _url
                _url = config["url"]
            async def after_save(event):
                pass
        """)
        entry = HookEntry(
            path="./metrics.py",
            points=["after_save"],
            config={"url": "${HOOK_URL}/push"},
        )
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert registry.get_hooks("after_save")[0].config == {"url": "http://metrics/push"}


# ─── Validation Errors ───


class TestValidation:
    def test_both_module_and_path_rejected(self):
        with pytest.raises(ValueError, match="not both"):
            HookEntry(module="foo", path="./bar.py", points=["before_save"])

    def test_neither_module_nor_path_rejected(self):
        with pytest.raises(ValueError, match="must have either"):
            HookEntry(points=["before_save"])

    def test_unknown_lifecycle_point(self):
        with pytest.raises(ValueError, match="Unknown lifecycle point"):
            HookEntry(path="./x.py", points=["not_a_hook"])

    def test_invalid_fail_mode(self):
        with pytest.raises(ValueError, match="fail_mode"):
            HookEntry(path="./x.py", points=["before_save"], fail_mode="maybe")

    def test_missing_function_skipped(self, hook_dir):
        """Module exists but doesn't export the declared function → skip that point."""
        _write_hook_file(hook_dir, "partial", """
            async def before_save(event):
                pass
            # on_recall NOT defined
        """)
        entry = HookEntry(path="./partial.py", points=["before_save", "on_recall"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert "before_save" in registry.loaded_hooks
        assert "on_recall" not in registry.loaded_hooks

    def test_sync_function_skipped(self, hook_dir):
        """Non-async function for a lifecycle point is skipped."""
        _write_hook_file(hook_dir, "sync_hook", """
            def before_save(event):
                pass
        """)
        entry = HookEntry(path="./sync_hook.py", points=["before_save"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert not registry.has_hooks

    def test_import_error_skipped_open(self, hook_dir):
        """Import error with fail_mode=open → skip, don't crash."""
        entry = HookEntry(path="./nonexistent.py", points=["before_save"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert not registry.has_hooks

    def test_import_error_exits_closed(self, hook_dir):
        """Import error with fail_mode=closed → sys.exit(1)."""
        entry = HookEntry(path="./nonexistent.py", points=["before_save"], fail_mode="closed")
        registry = HookRegistry()
        with pytest.raises(SystemExit):
            registry.load_from_entries([entry], base_dir=hook_dir)

    def test_syntax_error_skipped(self, hook_dir):
        """Syntax error in hook file → skip with fail_mode=open."""
        (hook_dir / "bad.py").write_text("def this is bad syntax")
        entry = HookEntry(path="./bad.py", points=["before_save"])
        registry = HookRegistry()
        registry.load_from_entries([entry], base_dir=hook_dir)
        assert not registry.has_hooks

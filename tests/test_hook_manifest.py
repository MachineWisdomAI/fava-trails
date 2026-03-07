"""Tests for manifest-based hook registration (Spec 17 v2 — Phase 2)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from fava_trails.hook_manifest import (
    HookEntry,
    HookManifest,
    HookRegistry,
    _interpolate_env,
)


@pytest.fixture
def manifest_dir(tmp_path):
    """Create a temporary directory for hooks manifest."""
    return tmp_path


def _write_manifest(manifest_dir: Path, hooks: list[dict]) -> Path:
    """Write a hooks.yaml manifest."""
    path = manifest_dir / "hooks.yaml"
    path.write_text(yaml.dump({"hooks": hooks}))
    return path


def _write_hook_file(manifest_dir: Path, name: str, code: str) -> Path:
    """Write a Python hook file."""
    path = manifest_dir / f"{name}.py"
    path.write_text(textwrap.dedent(code))
    return path


# ─── Manifest Parsing ───


class TestManifestParsing:
    def test_empty_manifest(self, manifest_dir):
        """Empty hooks list → no hooks loaded."""
        path = _write_manifest(manifest_dir, [])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert not registry.has_hooks
        assert registry.loaded_hooks == []

    def test_no_manifest_file(self, manifest_dir):
        """Missing manifest file → no hooks, no error."""
        registry = HookRegistry()
        registry.load_from_manifest(manifest_dir / "nonexistent.yaml")
        assert not registry.has_hooks

    def test_valid_path_entry(self, manifest_dir):
        """path: entry resolves local .py file."""
        _write_hook_file(manifest_dir, "quality", """
            async def before_save(event):
                return None
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./quality.py",
            "points": ["before_save"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert "before_save" in registry.loaded_hooks
        hooks = registry.get_hooks("before_save")
        assert len(hooks) == 1
        assert hooks[0].order == 50  # default

    def test_valid_directory_entry(self, manifest_dir):
        """path: entry resolves directory with __init__.py."""
        pkg_dir = manifest_dir / "my_hook"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text(textwrap.dedent("""
            async def before_save(event):
                return None
        """))
        path = _write_manifest(manifest_dir, [{
            "path": "./my_hook/",
            "points": ["before_save"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert "before_save" in registry.loaded_hooks

    def test_multi_point_registration(self, manifest_dir):
        """One entry declaring multiple points registers all of them."""
        _write_hook_file(manifest_dir, "multi", """
            async def before_save(event):
                return None
            async def after_save(event):
                return None
            async def on_recall(event):
                return None
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./multi.py",
            "points": ["before_save", "after_save", "on_recall"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert len(registry.loaded_hooks) == 3

    def test_order_sorting(self, manifest_dir):
        """Multiple hooks for same point are sorted by order."""
        _write_hook_file(manifest_dir, "hook_a", """
            async def before_save(event):
                return "a"
        """)
        _write_hook_file(manifest_dir, "hook_b", """
            async def before_save(event):
                return "b"
        """)
        path = _write_manifest(manifest_dir, [
            {"path": "./hook_a.py", "points": ["before_save"], "order": 100},
            {"path": "./hook_b.py", "points": ["before_save"], "order": 10},
        ])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        hooks = registry.get_hooks("before_save")
        assert len(hooks) == 2
        assert hooks[0].order == 10  # hook_b first
        assert hooks[1].order == 100  # hook_a second

    def test_fail_mode_extraction(self, manifest_dir):
        """fail_mode from manifest is stored on HookSpec."""
        _write_hook_file(manifest_dir, "strict", """
            async def before_save(event):
                return None
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./strict.py",
            "points": ["before_save"],
            "fail_mode": "closed",
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert registry.get_hooks("before_save")[0].fail_mode == "closed"

    def test_get_hooks_empty(self, manifest_dir):
        """get_hooks returns empty list for unregistered point."""
        registry = HookRegistry()
        assert registry.get_hooks("before_save") == []

    def test_all_specs(self, manifest_dir):
        """all_specs returns flat list of all HookSpecs."""
        _write_hook_file(manifest_dir, "multi", """
            async def before_save(event):
                pass
            async def on_recall(event):
                pass
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./multi.py",
            "points": ["before_save", "on_recall"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert len(registry.all_specs) == 2


# ─── Config Injection ───


class TestConfigInjection:
    def test_configure_called(self, manifest_dir):
        """configure() is called with the config dict."""
        _write_hook_file(manifest_dir, "configurable", """
            _config = {}
            def configure(config):
                _config.update(config)
            async def before_save(event):
                return None
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./configurable.py",
            "points": ["before_save"],
            "config": {"key": "value", "num": 42},
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert "before_save" in registry.loaded_hooks
        # Config is stored on the spec
        assert registry.get_hooks("before_save")[0].config == {"key": "value", "num": 42}

    def test_configure_not_required(self, manifest_dir):
        """Hook without configure() still loads fine."""
        _write_hook_file(manifest_dir, "simple", """
            async def before_save(event):
                return None
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./simple.py",
            "points": ["before_save"],
            "config": {"ignored": True},
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
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

    def test_manifest_with_env_vars(self, manifest_dir, monkeypatch):
        """End-to-end: env vars in manifest config are interpolated."""
        monkeypatch.setenv("HOOK_URL", "http://metrics")
        _write_hook_file(manifest_dir, "metrics", """
            _url = None
            def configure(config):
                global _url
                _url = config["url"]
            async def after_save(event):
                pass
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./metrics.py",
            "points": ["after_save"],
            "config": {"url": "${HOOK_URL}/push"},
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
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

    def test_missing_function_skipped(self, manifest_dir):
        """Module exists but doesn't export the declared function → skip that point."""
        _write_hook_file(manifest_dir, "partial", """
            async def before_save(event):
                pass
            # on_recall NOT defined
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./partial.py",
            "points": ["before_save", "on_recall"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert "before_save" in registry.loaded_hooks
        assert "on_recall" not in registry.loaded_hooks

    def test_sync_function_skipped(self, manifest_dir):
        """Non-async function for a lifecycle point is skipped."""
        _write_hook_file(manifest_dir, "sync_hook", """
            def before_save(event):
                pass
        """)
        path = _write_manifest(manifest_dir, [{
            "path": "./sync_hook.py",
            "points": ["before_save"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert not registry.has_hooks

    def test_import_error_skipped_open(self, manifest_dir):
        """Import error with fail_mode=open → skip, don't crash."""
        path = _write_manifest(manifest_dir, [{
            "path": "./nonexistent.py",
            "points": ["before_save"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert not registry.has_hooks

    def test_import_error_exits_closed(self, manifest_dir):
        """Import error with fail_mode=closed → sys.exit(1)."""
        path = _write_manifest(manifest_dir, [{
            "path": "./nonexistent.py",
            "points": ["before_save"],
            "fail_mode": "closed",
        }])
        registry = HookRegistry()
        with pytest.raises(SystemExit):
            registry.load_from_manifest(path)

    def test_syntax_error_skipped(self, manifest_dir):
        """Syntax error in hook file → skip with fail_mode=open."""
        (manifest_dir / "bad.py").write_text("def this is bad syntax")
        path = _write_manifest(manifest_dir, [{
            "path": "./bad.py",
            "points": ["before_save"],
        }])
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert not registry.has_hooks

    def test_malformed_yaml(self, manifest_dir):
        """Invalid YAML → no hooks loaded."""
        path = manifest_dir / "hooks.yaml"
        path.write_text("not: [valid: yaml: {{")
        registry = HookRegistry()
        registry.load_from_manifest(path)
        assert not registry.has_hooks

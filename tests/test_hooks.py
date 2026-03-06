"""Tests for lifecycle hooks (Spec 17)."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest
import pytest_asyncio

from fava_trails.hooks import (
    DEFAULT_TIMEOUTS,
    HookExecutionError,
    HookRegistry,
    HookTimeoutError,
    build_hook_ctx,
    fire_after,
    fire_before,
    fire_hook,
    fire_recall,
)


@pytest.fixture
def hooks_dir(tmp_path):
    """Create a temporary hooks directory."""
    d = tmp_path / "hooks"
    d.mkdir()
    return d


def _write_hook(hooks_dir: Path, name: str, code: str) -> Path:
    """Write a hook file to the hooks directory."""
    path = hooks_dir / f"{name}.py"
    path.write_text(textwrap.dedent(code))
    return path


# ─── Phase 1: HookRegistry + Hook Loading ───


class TestHookRegistryLoading:
    def test_no_hooks_dir(self, tmp_path):
        """No hooks directory → no hooks loaded, no error."""
        registry = HookRegistry()
        registry.load_from_dir(tmp_path / "nonexistent")
        assert registry.loaded_hooks == []

    def test_empty_hooks_dir(self, hooks_dir):
        """Empty hooks directory → no hooks loaded."""
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert registry.loaded_hooks == []

    def test_load_valid_hook(self, hooks_dir):
        """Valid async hook() is loaded."""
        _write_hook(hooks_dir, "before_save", """
            async def hook(thought, trail, **ctx):
                return True
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert "before_save" in registry.loaded_hooks
        spec = registry.get_hook("before_save")
        assert spec is not None
        assert spec.fail_mode == "open"

    def test_skip_sync_hook(self, hooks_dir):
        """Non-async hook() is skipped with warning."""
        _write_hook(hooks_dir, "before_save", """
            def hook(thought, trail, **ctx):
                return True
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert registry.loaded_hooks == []

    def test_skip_missing_hook_fn(self, hooks_dir):
        """File without hook() function is skipped."""
        _write_hook(hooks_dir, "before_save", """
            async def not_a_hook():
                pass
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert registry.loaded_hooks == []

    def test_syntax_error_hook(self, hooks_dir):
        """File with syntax error is skipped."""
        (hooks_dir / "before_save.py").write_text("def this is bad syntax")
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert registry.loaded_hooks == []

    def test_unknown_filename_ignored(self, hooks_dir):
        """Files not matching known hook names are ignored."""
        _write_hook(hooks_dir, "random_file", """
            async def hook(**ctx):
                pass
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert registry.loaded_hooks == []

    def test_fail_mode_extraction(self, hooks_dir):
        """FAIL_MODE constant is extracted from module."""
        _write_hook(hooks_dir, "before_save", """
            FAIL_MODE = "closed"
            async def hook(thought, trail, **ctx):
                return True
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        spec = registry.get_hook("before_save")
        assert spec is not None
        assert spec.fail_mode == "closed"

    def test_invalid_fail_mode_defaults_open(self, hooks_dir):
        """Invalid FAIL_MODE defaults to 'open'."""
        _write_hook(hooks_dir, "before_save", """
            FAIL_MODE = "invalid"
            async def hook(thought, trail, **ctx):
                return True
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        spec = registry.get_hook("before_save")
        assert spec is not None
        assert spec.fail_mode == "open"

    def test_timeout_extraction(self, hooks_dir):
        """TIMEOUT constant is extracted from module."""
        _write_hook(hooks_dir, "before_save", """
            TIMEOUT = 3.0
            async def hook(thought, trail, **ctx):
                return True
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        spec = registry.get_hook("before_save")
        assert spec is not None
        assert spec.timeout == 3.0

    def test_default_timeout_by_hook_type(self, hooks_dir):
        """Default timeout varies by hook type."""
        _write_hook(hooks_dir, "on_recall", """
            async def hook(results, trail, **ctx):
                return results
        """)
        _write_hook(hooks_dir, "on_startup", """
            async def hook(**ctx):
                pass
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert registry.get_hook("on_recall").timeout == DEFAULT_TIMEOUTS["on_recall"]
        assert registry.get_hook("on_startup").timeout == DEFAULT_TIMEOUTS["on_startup"]

    def test_common_importable(self, hooks_dir):
        """common.py is importable from other hooks."""
        _write_hook(hooks_dir, "common", """
            SHARED_VALUE = 42
        """)
        _write_hook(hooks_dir, "before_save", """
            import common
            async def hook(thought, trail, **ctx):
                return common.SHARED_VALUE == 42
        """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert "before_save" in registry.loaded_hooks
        # common.py itself should NOT be loaded as a hook
        assert "common" not in registry.loaded_hooks

    def test_multiple_hooks_loaded(self, hooks_dir):
        """Multiple hook files are all loaded."""
        for name in ["before_save", "after_save", "on_recall"]:
            _write_hook(hooks_dir, name, f"""
                async def hook(**kwargs):
                    pass
            """)
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert len(registry.loaded_hooks) == 3

    def test_get_hook_returns_none_for_missing(self, hooks_dir):
        """get_hook returns None for unloaded hooks."""
        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)
        assert registry.get_hook("before_save") is None


# ─── Phase 2: Hook Execution Engine ───


def _make_registry_with_hook(hooks_dir, name, code, fail_mode="open", timeout=None):
    """Helper to create a registry with a single hook."""
    full_code = ""
    if fail_mode != "open":
        full_code += f'FAIL_MODE = "{fail_mode}"\n'
    if timeout is not None:
        full_code += f"TIMEOUT = {timeout}\n"
    full_code += textwrap.dedent(code)
    (hooks_dir / f"{name}.py").write_text(full_code)
    registry = HookRegistry()
    registry.load_from_dir(hooks_dir)
    return registry


class TestFireHook:
    @pytest.mark.asyncio
    async def test_fire_no_hook(self):
        """No hook registered → no_hook status (fast path)."""
        registry = HookRegistry()
        result = await fire_hook(registry, "before_save")
        assert result["status"] == "no_hook"

    @pytest.mark.asyncio
    async def test_fire_success(self, hooks_dir):
        """Successful hook returns ok status."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            async def hook(**kwargs):
                return True
        """)
        result = await fire_hook(registry, "before_save")
        assert result["status"] == "ok"
        assert result["result"] is True

    @pytest.mark.asyncio
    async def test_fire_timeout_open(self, hooks_dir):
        """Timeout + open → returns timeout status."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            import asyncio
            async def hook(**kwargs):
                await asyncio.sleep(10)
        """, timeout=0.1)
        result = await fire_hook(registry, "before_save")
        assert result["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_fire_timeout_closed(self, hooks_dir):
        """Timeout + closed → raises HookTimeoutError."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            import asyncio
            async def hook(**kwargs):
                await asyncio.sleep(10)
        """, fail_mode="closed", timeout=0.1)
        with pytest.raises(HookTimeoutError):
            await fire_hook(registry, "before_save")

    @pytest.mark.asyncio
    async def test_fire_exception_open(self, hooks_dir):
        """Exception + open → returns error status."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            async def hook(**kwargs):
                raise RuntimeError("boom")
        """)
        result = await fire_hook(registry, "before_save")
        assert result["status"] == "error"
        assert "boom" in result["exception"]

    @pytest.mark.asyncio
    async def test_fire_exception_closed(self, hooks_dir):
        """Exception + closed → raises HookExecutionError."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            async def hook(**kwargs):
                raise RuntimeError("boom")
        """, fail_mode="closed")
        with pytest.raises(HookExecutionError, match="boom"):
            await fire_hook(registry, "before_save")


class TestFireBefore:
    @pytest.mark.asyncio
    async def test_no_hook_proceeds(self):
        """No hook → returns True (proceed)."""
        registry = HookRegistry()
        assert await fire_before(registry, "before_save") is True

    @pytest.mark.asyncio
    async def test_hook_approves(self, hooks_dir):
        """Hook returns True → proceed."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            async def hook(**kwargs):
                return True
        """)
        assert await fire_before(registry, "before_save") is True

    @pytest.mark.asyncio
    async def test_hook_rejects(self, hooks_dir):
        """Hook returns False → rejected."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            async def hook(**kwargs):
                return False
        """)
        assert await fire_before(registry, "before_save") is False

    @pytest.mark.asyncio
    async def test_hook_returns_none_proceeds(self, hooks_dir):
        """Hook returns None (implicit) → proceed (not explicitly False)."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            async def hook(**kwargs):
                pass  # returns None
        """)
        assert await fire_before(registry, "before_save") is True

    @pytest.mark.asyncio
    async def test_timeout_open_proceeds(self, hooks_dir):
        """Timeout + open → proceed."""
        registry = _make_registry_with_hook(hooks_dir, "before_save", """
            import asyncio
            async def hook(**kwargs):
                await asyncio.sleep(10)
        """, timeout=0.1)
        assert await fire_before(registry, "before_save") is True


class TestFireAfter:
    @pytest.mark.asyncio
    async def test_no_hook(self):
        """No hook → no-op."""
        registry = HookRegistry()
        await fire_after(registry, "after_save")  # should not raise

    @pytest.mark.asyncio
    async def test_return_ignored(self, hooks_dir):
        """After hook return value is ignored."""
        registry = _make_registry_with_hook(hooks_dir, "after_save", """
            async def hook(**kwargs):
                return "should be ignored"
        """)
        result = await fire_after(registry, "after_save")
        assert result is None


class TestFireRecall:
    @pytest.mark.asyncio
    async def test_no_hook_returns_original(self):
        """No hook → original results returned."""
        registry = HookRegistry()
        results = [1, 2, 3]
        assert await fire_recall(registry, results) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_filters_results(self, hooks_dir):
        """Hook filters results."""
        registry = _make_registry_with_hook(hooks_dir, "on_recall", """
            async def hook(results, **kwargs):
                return [r for r in results if r > 1]
        """)
        results = [1, 2, 3]
        assert await fire_recall(registry, results) == [2, 3]

    @pytest.mark.asyncio
    async def test_nonlist_returns_original(self, hooks_dir):
        """Hook returns non-list → original results returned (safety)."""
        registry = _make_registry_with_hook(hooks_dir, "on_recall", """
            async def hook(results, **kwargs):
                return "not a list"
        """)
        results = [1, 2, 3]
        assert await fire_recall(registry, results) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_error_returns_original(self, hooks_dir):
        """Error in hook → original results returned (fail-open)."""
        registry = _make_registry_with_hook(hooks_dir, "on_recall", """
            async def hook(results, **kwargs):
                raise RuntimeError("oops")
        """)
        results = [1, 2, 3]
        assert await fire_recall(registry, results) == [1, 2, 3]


class TestBuildHookCtx:
    def test_basic_ctx(self):
        """Context dict contains expected fields."""
        ctx = build_hook_ctx()
        assert ctx["hook_api_version"] == "1.0"
        assert ctx["trail_name"] is None
        assert ctx["config"] == {}

    def test_with_trail(self):
        """Context includes trail_name when trail is provided."""

        class FakeTrail:
            trail_name = "mw/eng/test"

        ctx = build_hook_ctx(trail=FakeTrail())
        assert ctx["trail_name"] == "mw/eng/test"

    def test_extra_kwargs(self):
        """Extra kwargs are included in context."""
        ctx = build_hook_ctx(query="test", namespace="drafts")
        assert ctx["query"] == "test"
        assert ctx["namespace"] == "drafts"


# ─── Phase 3: Integration Tests ───


class TestTrailManagerHookIntegration:
    """Integration tests for hooks wired into TrailManager."""

    @pytest_asyncio.fixture
    async def hooked_trail(self, tmp_fava_home, hooks_dir):
        """TrailManager with a HookRegistry."""
        from fava_trails.trail import TrailManager
        from fava_trails.vcs.jj_backend import JjBackend

        registry = HookRegistry()
        registry.load_from_dir(hooks_dir)

        trail_path = tmp_fava_home / "trails" / "test-hooks"
        backend = JjBackend(repo_root=tmp_fava_home, trail_path=trail_path)
        manager = TrailManager("test-hooks", vcs=backend, hooks=registry)
        await manager.init()
        return manager, registry, hooks_dir

    @pytest.mark.asyncio
    async def test_save_no_hooks(self, trail_manager):
        """save_thought works with no hooks (backward compat)."""
        record = await trail_manager.save_thought("hello", agent_id="test")
        assert record.content == "hello"

    @pytest.mark.asyncio
    async def test_save_with_before_hook_approve(self, hooked_trail):
        """before_save hook returns True → save succeeds."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook(hooks_dir, "before_save", """
            async def hook(thought, trail, **ctx):
                return True
        """)
        registry.load_from_dir(hooks_dir)

        record = await manager.save_thought("hello", agent_id="test")
        assert record.content == "hello"

    @pytest.mark.asyncio
    async def test_save_with_before_hook_reject(self, hooked_trail):
        """before_save hook returns False → save rejected."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook(hooks_dir, "before_save", """
            async def hook(thought, trail, **ctx):
                return False
        """)
        registry.load_from_dir(hooks_dir)

        with pytest.raises(ValueError, match="before_save hook rejected"):
            await manager.save_thought("rejected thought", agent_id="test")

    @pytest.mark.asyncio
    async def test_save_with_after_hook(self, hooked_trail):
        """after_save hook fires post-commit."""
        manager, registry, hooks_dir = hooked_trail
        # Use a file as a side-effect marker
        marker = hooks_dir / "after_save_fired.txt"
        _write_hook(hooks_dir, "after_save", f"""
            from pathlib import Path
            async def hook(thought, trail, **ctx):
                Path("{marker}").write_text(thought.content)
        """)
        registry.load_from_dir(hooks_dir)

        await manager.save_thought("marker content", agent_id="test")
        assert marker.exists()
        assert marker.read_text() == "marker content"

    @pytest.mark.asyncio
    async def test_propose_with_before_hook_reject(self, hooked_trail):
        """before_propose hook rejects promotion."""
        manager, registry, hooks_dir = hooked_trail

        # Save a thought first (no before_save hook)
        record = await manager.save_thought("promote me", agent_id="test")

        # Now add before_propose hook that rejects
        _write_hook(hooks_dir, "before_propose", """
            async def hook(thought, trail, **ctx):
                return False
        """)
        registry.load_from_dir(hooks_dir)

        with pytest.raises(ValueError, match="before_propose hook rejected"):
            await manager.propose_truth(record.thought_id)

    @pytest.mark.asyncio
    async def test_propose_with_after_hook(self, hooked_trail):
        """after_propose hook fires post-promotion."""
        manager, registry, hooks_dir = hooked_trail
        marker = hooks_dir / "after_propose_fired.txt"
        _write_hook(hooks_dir, "after_propose", f"""
            from pathlib import Path
            async def hook(thought, trail, **ctx):
                Path("{marker}").write_text("promoted")
        """)
        registry.load_from_dir(hooks_dir)

        from fava_trails.models import SourceType
        record = await manager.save_thought("promote me", agent_id="test", source_type=SourceType.OBSERVATION)
        await manager.propose_truth(record.thought_id)
        assert marker.exists()

    @pytest.mark.asyncio
    async def test_supersede_with_after_hook(self, hooked_trail):
        """after_supersede hook fires with original + new thought."""
        manager, registry, hooks_dir = hooked_trail
        marker = hooks_dir / "after_supersede_fired.txt"
        _write_hook(hooks_dir, "after_supersede", f"""
            from pathlib import Path
            async def hook(thought, original, trail, **ctx):
                Path("{marker}").write_text(f"{{original.thought_id[:8]}}->{{thought.thought_id[:8]}}")
        """)
        registry.load_from_dir(hooks_dir)

        original = await manager.save_thought("v1", agent_id="test")
        new = await manager.supersede(original.thought_id, "v2", reason="update", agent_id="test")
        assert marker.exists()
        assert original.thought_id[:8] in marker.read_text()
        assert new.thought_id[:8] in marker.read_text()

    @pytest.mark.asyncio
    async def test_recall_with_on_recall_hook(self, hooked_trail):
        """on_recall hook filters results."""
        manager, registry, hooks_dir = hooked_trail

        await manager.save_thought("keep this", agent_id="test", metadata={"tags": ["keep"]})
        await manager.save_thought("drop this", agent_id="test", metadata={"tags": ["drop"]})

        _write_hook(hooks_dir, "on_recall", """
            async def hook(results, trail, **ctx):
                return [r for r in results if "keep" in r.frontmatter.metadata.tags]
        """)
        registry.load_from_dir(hooks_dir)

        results = await manager.recall()
        assert len(results) == 1
        assert "keep this" in results[0].content

    @pytest.mark.asyncio
    async def test_before_save_receives_copy(self, hooked_trail):
        """before_save hook receives a copy — mutations don't affect the saved thought."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook(hooks_dir, "before_save", """
            async def hook(thought, trail, **ctx):
                thought.content = "MUTATED"
                return True
        """)
        registry.load_from_dir(hooks_dir)

        record = await manager.save_thought("original content", agent_id="test")
        assert record.content == "original content"

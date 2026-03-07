"""Tests for lifecycle hooks v2 integration (Spec 17 v2 — Phase 4).

Integration tests verifying hooks.yaml manifest → pipeline → TrailManager wiring.
Unit tests for hook types, manifest, and pipeline are in their respective test files.
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from fava_trails.hook_manifest import HookRegistry


def _write_manifest(hooks_dir: Path, hooks: list[dict]) -> Path:
    """Write a hooks.yaml manifest."""
    path = hooks_dir / "hooks.yaml"
    path.write_text(yaml.dump({"hooks": hooks}))
    return path


def _write_hook_file(hooks_dir: Path, name: str, code: str) -> Path:
    """Write a Python hook file."""
    path = hooks_dir / f"{name}.py"
    path.write_text(textwrap.dedent(code))
    return path


# ─── TrailManager Integration Tests ───


class TestTrailManagerHookIntegration:
    """Integration tests for v2 hooks wired into TrailManager."""

    @pytest_asyncio.fixture
    async def hooked_trail(self, tmp_fava_home, hooks_dir):
        """TrailManager with a manifest-based HookRegistry."""
        from fava_trails.trail import TrailManager
        from fava_trails.vcs.jj_backend import JjBackend

        registry = HookRegistry()

        trail_path = tmp_fava_home / "trails" / "test-hooks"
        backend = JjBackend(repo_root=tmp_fava_home, trail_path=trail_path)
        manager = TrailManager("test-hooks", vcs=backend, hooks=registry)
        await manager.init()
        return manager, registry, hooks_dir

    @pytest.fixture
    def hooks_dir(self, tmp_path):
        d = tmp_path / "hooks"
        d.mkdir()
        return d

    def _load_hooks(self, registry, hooks_dir, hooks_config):
        """Write manifest and hook files, then load into registry."""
        _write_manifest(hooks_dir, hooks_config)
        registry.load_from_manifest(hooks_dir / "hooks.yaml")

    @pytest.mark.asyncio
    async def test_save_no_hooks(self, trail_manager):
        """save_thought works with no hooks (backward compat)."""
        record = await trail_manager.save_thought("hello", agent_id="test")
        assert record.content == "hello"

    @pytest.mark.asyncio
    async def test_save_with_before_hook_proceed(self, hooked_trail):
        """before_save hook returning Proceed → save succeeds."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "quality", """
            from fava_trails.hook_types import Proceed
            async def before_save(event):
                return Proceed()
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./quality.py",
            "points": ["before_save"],
        }])

        record = await manager.save_thought("hello", agent_id="test")
        assert record.content == "hello"

    @pytest.mark.asyncio
    async def test_save_with_before_hook_reject(self, hooked_trail):
        """before_save hook returning Reject → save rejected."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "guard", """
            from fava_trails.hook_types import Reject
            async def before_save(event):
                return Reject(reason="forbidden", code="GUARD")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./guard.py",
            "points": ["before_save"],
        }])

        with pytest.raises(ValueError, match="before_save hook rejected"):
            await manager.save_thought("rejected thought", agent_id="test")

    @pytest.mark.asyncio
    async def test_save_with_mutate_hook(self, hooked_trail):
        """before_save hook returning Mutate → thought content is changed."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "transform", """
            from fava_trails.hook_types import Mutate, ThoughtPatch
            async def before_save(event):
                return Mutate(patch=ThoughtPatch(content=event.thought.content.upper()))
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./transform.py",
            "points": ["before_save"],
        }])

        record = await manager.save_thought("hello world", agent_id="test")
        assert record.content == "HELLO WORLD"

    @pytest.mark.asyncio
    async def test_save_with_redirect_hook(self, hooked_trail):
        """before_save hook returning Redirect → thought saved to different namespace."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "router", """
            from fava_trails.hook_types import Redirect
            async def before_save(event):
                return Redirect(namespace="observations")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./router.py",
            "points": ["before_save"],
        }])

        record = await manager.save_thought("routed thought", agent_id="test")
        # Thought should be in observations/ not drafts/
        obs_path = manager._thought_path(record.thought_id, "observations")
        assert obs_path.exists()

    @pytest.mark.asyncio
    async def test_save_with_warn_hook(self, hooked_trail):
        """before_save hook returning Warn → save succeeds, feedback has warnings."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "checker", """
            from fava_trails.hook_types import Warn
            async def before_save(event):
                return Warn(message="short content", code="SHORT")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./checker.py",
            "points": ["before_save"],
        }])

        record = await manager.save_thought("hi", agent_id="test")
        assert record.content == "hi"
        assert manager._last_feedback is not None
        assert len(manager._last_feedback.feedback.warnings) == 1

    @pytest.mark.asyncio
    async def test_save_with_after_hook(self, hooked_trail):
        """after_save hook fires post-commit."""
        manager, registry, hooks_dir = hooked_trail
        marker = hooks_dir / "after_save_fired.txt"
        _write_hook_file(hooks_dir, "notifier", f"""
            from pathlib import Path
            async def after_save(event):
                Path("{marker}").write_text(event.thought.content)
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./notifier.py",
            "points": ["after_save"],
        }])

        await manager.save_thought("marker content", agent_id="test")
        await asyncio.sleep(0.05)  # Let fire-and-forget task run
        assert marker.exists()
        assert marker.read_text() == "marker content"

    @pytest.mark.asyncio
    async def test_propose_with_before_hook_reject(self, hooked_trail):
        """before_propose hook rejects promotion."""
        manager, registry, hooks_dir = hooked_trail

        # Save a thought first (no hooks)
        record = await manager.save_thought("promote me", agent_id="test")

        # Now add before_propose hook that rejects
        _write_hook_file(hooks_dir, "propose_guard", """
            from fava_trails.hook_types import Reject
            async def before_propose(event):
                return Reject(reason="not ready")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./propose_guard.py",
            "points": ["before_propose"],
        }])

        with pytest.raises(ValueError, match="before_propose hook rejected"):
            await manager.propose_truth(record.thought_id)

    @pytest.mark.asyncio
    async def test_propose_with_after_hook(self, hooked_trail):
        """after_propose hook fires post-promotion."""
        manager, registry, hooks_dir = hooked_trail
        marker = hooks_dir / "after_propose_fired.txt"
        _write_hook_file(hooks_dir, "propose_notify", f"""
            from pathlib import Path
            async def after_propose(event):
                Path("{marker}").write_text("promoted")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./propose_notify.py",
            "points": ["after_propose"],
        }])

        from fava_trails.models import SourceType
        record = await manager.save_thought("promote me", agent_id="test", source_type=SourceType.OBSERVATION)
        await manager.propose_truth(record.thought_id)
        await asyncio.sleep(0.05)
        assert marker.exists()

    @pytest.mark.asyncio
    async def test_supersede_with_after_hook(self, hooked_trail):
        """after_supersede hook fires with original + new thought."""
        manager, registry, hooks_dir = hooked_trail
        marker = hooks_dir / "after_supersede_fired.txt"
        _write_hook_file(hooks_dir, "supersede_notify", f"""
            from pathlib import Path
            async def after_supersede(event):
                Path("{marker}").write_text(
                    f"{{event.original_thought.thought_id[:8]}}->{{event.new_thought.thought_id[:8]}}"
                )
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./supersede_notify.py",
            "points": ["after_supersede"],
        }])

        original = await manager.save_thought("v1", agent_id="test")
        new = await manager.supersede(original.thought_id, "v2", reason="update", agent_id="test")
        await asyncio.sleep(0.05)
        assert marker.exists()
        assert original.thought_id[:8] in marker.read_text()
        assert new.thought_id[:8] in marker.read_text()

    @pytest.mark.asyncio
    async def test_recall_with_on_recall_hook(self, hooked_trail):
        """on_recall hook filters results via RecallSelect."""
        manager, registry, hooks_dir = hooked_trail

        r1 = await manager.save_thought("keep this", agent_id="test", metadata={"tags": ["keep"]})
        r2 = await manager.save_thought("drop this", agent_id="test", metadata={"tags": ["drop"]})

        _write_hook_file(hooks_dir, "recall_filter", """
            from fava_trails.hook_types import RecallSelect
            async def on_recall(event):
                keep_ulids = [
                    r.thought_id for r in event.results
                    if "keep" in r.frontmatter.metadata.tags
                ]
                return RecallSelect(ordered_ulids=keep_ulids, reason="filtering")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./recall_filter.py",
            "points": ["on_recall"],
        }])

        results = await manager.recall()
        assert len(results) == 1
        assert "keep this" in results[0].content

    @pytest.mark.asyncio
    async def test_recall_internal_bypasses_hooks(self, hooked_trail):
        """_recall_internal bypasses on_recall hooks (prevents recursion)."""
        manager, registry, hooks_dir = hooked_trail

        r1 = await manager.save_thought("thought 1", agent_id="test")
        r2 = await manager.save_thought("thought 2", agent_id="test")

        # Hook that selects only the first thought
        _write_hook_file(hooks_dir, "recall_filter", f"""
            from fava_trails.hook_types import RecallSelect
            async def on_recall(event):
                return RecallSelect(ordered_ulids=["{r1.thought_id}"], reason="first only")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./recall_filter.py",
            "points": ["on_recall"],
        }])

        # Regular recall should return only 1 (hook filters)
        results = await manager.recall()
        assert len(results) == 1
        assert results[0].thought_id == r1.thought_id

        # _recall_internal should bypass hooks and return both
        internal_results = await manager._recall_internal()
        assert len(internal_results) == 2

    @pytest.mark.asyncio
    async def test_multi_action_hook(self, hooked_trail):
        """Hook returning multiple actions: Warn + Annotate."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "multi", """
            from fava_trails.hook_types import Warn, Annotate
            async def before_save(event):
                return [
                    Warn(message="low confidence", code="LOW_CONF"),
                    Annotate(values={"quality_score": 0.3}),
                ]
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./multi.py",
            "points": ["before_save"],
        }])

        record = await manager.save_thought("test", agent_id="test")
        assert record.content == "test"
        fb = manager._last_feedback.feedback
        assert len(fb.warnings) == 1
        assert fb.annotations["quality_score"] == 0.3

    @pytest.mark.asyncio
    async def test_hook_timeout_open(self, hooked_trail):
        """Hook timeout with fail_mode=open → save proceeds."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "slow", """
            import asyncio
            async def before_save(event):
                await asyncio.sleep(10)
        """)
        _write_manifest(hooks_dir, [{
            "path": "./slow.py",
            "points": ["before_save"],
            "fail_mode": "open",
        }])
        # Override timeout to something fast for testing
        registry.load_from_manifest(hooks_dir / "hooks.yaml")
        for hook in registry.get_hooks("before_save"):
            hook.timeout = 0.1

        record = await manager.save_thought("should succeed", agent_id="test")
        assert record.content == "should succeed"

    @pytest.mark.asyncio
    async def test_hook_error_open(self, hooked_trail):
        """Hook exception with fail_mode=open → save proceeds."""
        manager, registry, hooks_dir = hooked_trail
        _write_hook_file(hooks_dir, "broken", """
            async def before_save(event):
                raise RuntimeError("boom")
        """)
        self._load_hooks(registry, hooks_dir, [{
            "path": "./broken.py",
            "points": ["before_save"],
        }])

        record = await manager.save_thought("should succeed", agent_id="test")
        assert record.content == "should succeed"

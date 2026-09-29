"""Local-only repositories vs broken configured remotes for sync."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fava_trails.models import SourceType
from fava_trails.tools.navigation import handle_sync
from fava_trails.trust_gate import TrustResult
from fava_trails.tunnel_cli import GatewayConfig, _sync_data_repo_async


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _remote_names(repo: Path) -> list[str]:
    return [line.strip() for line in _git(repo, "remote").stdout.splitlines() if line.strip()]


def _remote_urls(repo: Path) -> list[str]:
    return [line.strip() for line in _git(repo, "remote", "-v").stdout.splitlines() if line.strip()]


def _assert_no_hosted_or_auto_remotes(repo: Path, allowed: set[str] | None = None) -> None:
    names = _remote_names(repo)
    if allowed is None:
        assert names == []
    else:
        assert set(names) == allowed
    joined = "\n".join(_remote_urls(repo)).lower()
    assert "github.com" not in joined
    assert "gitlab.com" not in joined


def _approval() -> TrustResult:
    return TrustResult(verdict="approve", reasoning="Synthetic local-only review", reviewer="fixture")


def _gateway_config(data_repo: Path) -> GatewayConfig:
    return GatewayConfig(
        data_repo=data_repo,
        trails_dir=data_repo / "trails",
        host="127.0.0.1",
        port=8765,
        mcp_path="/mcp/",
        profile="fava-trails",
        tunnel_client="/usr/bin/tunnel-client",
        trust_gate_credential="test",
    )


class _SyncTrail:
    def __init__(self, result):
        self._result = result

    async def sync(self):
        return self._result


@pytest.mark.asyncio
async def test_absent_remote_is_not_configured_and_does_not_change_remotes(jj_backend):
    """A local-only repo is not a broken remote; sync must not invent remotes."""
    _assert_no_hosted_or_auto_remotes(jj_backend.repo_root)

    result = await jj_backend.fetch_and_rebase()

    assert result.success is False
    assert getattr(result, "missing_remote", False) is True
    assert getattr(result, "remote_failure", None) is None
    assert "not configured" in result.summary.lower()
    assert "git remote add" in result.summary.lower() or "fava-trails clone" in result.summary.lower()
    _assert_no_hosted_or_auto_remotes(jj_backend.repo_root)


@pytest.mark.asyncio
async def test_local_save_recall_review_and_supersession_without_remote(trail_manager):
    """Local lifecycle stays usable when remote sync is not required."""
    repo = trail_manager.vcs.repo_root
    _assert_no_hosted_or_auto_remotes(repo)

    saved = await trail_manager.save_thought(
        content="Local-only observation.",
        agent_id="test-agent",
        source_type=SourceType.OBSERVATION,
    )
    fetched = await trail_manager.get_thought(saved.thought_id)
    reviewed = await trail_manager.propose_truth(saved.thought_id, _approval())
    recalled = await trail_manager.recall("Local-only observation")
    successor = await trail_manager.supersede(
        original_id=reviewed.thought_id,
        new_content="Corrected local-only observation.",
        reason="Local review found a better wording",
        agent_id="test-agent",
    )
    approved = await trail_manager.propose_truth(successor.thought_id, _approval())
    original = await trail_manager.get_thought(saved.thought_id)

    assert fetched is not None
    assert fetched.thought_id == saved.thought_id
    assert reviewed.frontmatter.validation_status.value in {"proposed", "approved"}
    assert any(item.thought_id == reviewed.thought_id for item in recalled)
    assert approved.thought_id == successor.thought_id
    assert original is not None
    assert original.frontmatter.superseded_by == successor.thought_id
    _assert_no_hosted_or_auto_remotes(repo)


@pytest.mark.asyncio
async def test_unreachable_configured_remote_is_a_broken_remote(jj_backend, tmp_path):
    """A configured remote that cannot be reached is an error, not local-only."""
    await jj_backend.add_remote("origin", "git://127.0.0.1:1/does-not-exist.git")
    remotes_before = _remote_urls(jj_backend.repo_root)

    result = await jj_backend.fetch_and_rebase()

    assert result.success is False
    assert getattr(result, "missing_remote", False) is False
    assert getattr(result, "remote_failure", None) == "unreachable"
    assert "not configured" not in result.summary.lower()
    assert "unreachable" in result.summary.lower() or "cannot reach" in result.summary.lower()
    assert _remote_urls(jj_backend.repo_root) == remotes_before
    _assert_no_hosted_or_auto_remotes(jj_backend.repo_root, allowed={"origin"})


@pytest.mark.asyncio
async def test_permission_failure_on_configured_remote(jj_backend, tmp_path):
    """A configured remote that denies access is a permission failure, not local-only."""
    denied = tmp_path / "denied.git"
    _git(tmp_path, "init", "--bare", str(denied))
    await jj_backend.add_remote("origin", str(denied))
    remotes_before = _remote_urls(jj_backend.repo_root)
    os.chmod(denied, 0)

    try:
        result = await jj_backend.fetch_and_rebase()
    finally:
        os.chmod(denied, stat.S_IRWXU)

    assert result.success is False
    assert getattr(result, "missing_remote", False) is False
    assert getattr(result, "remote_failure", None) == "permission"
    assert "not configured" not in result.summary.lower()
    assert "permission" in result.summary.lower()
    assert _remote_urls(jj_backend.repo_root) == remotes_before
    _assert_no_hosted_or_auto_remotes(jj_backend.repo_root, allowed={"origin"})


@pytest.mark.asyncio
async def test_healthy_disposable_remote_syncs(trail_manager, tmp_path):
    """A reachable local remote still syncs; tests never create a hosted repository."""
    remote = tmp_path / "disposable.git"
    _git(tmp_path, "init", "--bare", str(remote))
    await trail_manager.vcs.add_remote("origin", str(remote))
    await trail_manager.vcs._run("bookmark", "set", "main", "-r", "@-")
    # Seed the bare remote with local bookmarks. Prefer --all over --allow-new:
    # --allow-new was removed in JJ 0.42+; --all still creates new remote bookmarks
    # on both the supported floor (0.28) and current stable.
    await trail_manager.vcs._run("git", "push", "--allow-empty-description", "--all")

    result = await trail_manager.vcs.fetch_and_rebase()

    assert result.success is True
    assert getattr(result, "missing_remote", False) is False
    assert getattr(result, "remote_failure", None) is None
    assert "complete" in result.summary.lower()
    _assert_no_hosted_or_auto_remotes(trail_manager.vcs.repo_root, allowed={"origin"})
    assert str(remote) in "\n".join(_remote_urls(trail_manager.vcs.repo_root))


@pytest.mark.asyncio
async def test_handle_sync_reports_missing_remote_as_not_configured():
    result = SimpleNamespace(
        success=False,
        has_conflicts=False,
        has_dirty_working_copy=False,
        dirty_paths=[],
        has_case_collisions=False,
        case_collisions=[],
        missing_remote=True,
        remote_failure=None,
        summary=(
            "Remote sync is not configured. Add a git remote with "
            "`git remote add origin <url>` or clone a shared repository with "
            "`fava-trails clone <url> <path>`."
        ),
    )

    payload = await handle_sync(_SyncTrail(result), {})

    assert payload["status"] == "not_configured"
    assert "not configured" in payload["message"].lower()
    assert "git remote add" in payload["message"].lower() or "fava-trails clone" in payload["message"].lower()


@pytest.mark.asyncio
async def test_handle_sync_missing_remote_is_not_an_error_for_non_operators():
    result = SimpleNamespace(
        success=False,
        has_conflicts=False,
        has_dirty_working_copy=False,
        dirty_paths=[],
        has_case_collisions=False,
        case_collisions=[],
        missing_remote=True,
        remote_failure=None,
        summary="Remote sync is not configured. Add a git remote.",
    )

    payload = await handle_sync(_SyncTrail(result), {}, private_details=False)

    assert payload["status"] == "not_configured"
    assert "not configured" in payload["message"].lower()
    assert payload["message"] != result.summary


@pytest.mark.asyncio
async def test_handle_sync_reports_broken_configured_remote_as_error():
    result = SimpleNamespace(
        success=False,
        has_conflicts=False,
        has_dirty_working_copy=False,
        dirty_paths=[],
        has_case_collisions=False,
        case_collisions=[],
        missing_remote=False,
        remote_failure="unreachable",
        summary="Configured git remote is unreachable. Check network and remote URL.",
    )

    payload = await handle_sync(_SyncTrail(result), {})

    assert payload["status"] == "error"
    assert "unreachable" in payload["message"].lower()


@pytest.mark.asyncio
async def test_startup_sync_fail_closed_when_remote_missing(jj_backend):
    """Explicit startup sync must not treat a local-only repo as healthy."""
    config = _gateway_config(jj_backend.repo_root)

    payload = await _sync_data_repo_async(config)

    assert payload["status"] == "not_configured"
    assert "not configured" in payload["message"].lower()
    _assert_no_hosted_or_auto_remotes(jj_backend.repo_root)


@pytest.mark.asyncio
async def test_startup_sync_fail_closed_when_configured_remote_is_unreachable(jj_backend):
    await jj_backend.add_remote("origin", "git://127.0.0.1:1/does-not-exist.git")
    config = _gateway_config(jj_backend.repo_root)

    payload = await _sync_data_repo_async(config)

    assert payload["status"] == "error"
    assert "not configured" not in payload["message"].lower()
    _assert_no_hosted_or_auto_remotes(jj_backend.repo_root, allowed={"origin"})


def test_bootstrap_explains_local_only_next_step(tmp_path, capsys):
    from fava_trails.cli import cmd_bootstrap

    target = tmp_path / "data-repo"
    args = argparse.Namespace(path=str(target), remote=None)

    with patch("fava_trails.cli._find_jj_bin", return_value="/usr/bin/jj"):
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stderr="", stdout="")):
            rc = cmd_bootstrap(args)

    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "local-only" in out or "local only" in out
    assert "not configured" in out or "git remote add" in out
    assert "does not create hosted" in out or "does not create" in out

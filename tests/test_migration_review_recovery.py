"""Regression probes recovered from the independent migration review."""

import pytest

import fava_trails.duplicates as duplicates
from fava_trails.governance import read_snapshot
from tests.test_duplicates import seed


@pytest.mark.asyncio
async def test_initial_receipt_directory_is_durable_before_commit(jj_backend, monkeypatch):
    plan = await seed(jj_backend)
    synced = []
    real_sync = duplicates._sync_directory
    real_commit = jj_backend.commit_files
    observed = []

    def track_sync(path):
        synced.append(path)
        return real_sync(path)

    async def inspect_commit(*args, **kwargs):
        observed.append(list(synced))
        return await real_commit(*args, **kwargs)

    monkeypatch.setattr(duplicates, "_sync_directory", track_sync)
    monkeypatch.setattr(jj_backend, "commit_files", inspect_commit)
    await duplicates.apply_plan(jj_backend, plan, plan["digest"])
    assert jj_backend.repo_root / ".jj/fava-migrations" in observed[0]
    assert jj_backend.repo_root / ".jj" in observed[0]


@pytest.mark.asyncio
async def test_receipt_proof_failure_restores_old_view_and_retries(jj_backend, monkeypatch):
    plan = await seed(jj_backend)
    root = jj_backend.repo_root
    original = duplicates.capture(root)
    real_save = duplicates._save_receipt

    def fail_receipt(*args, **kwargs):
        raise OSError("Synthetic failure saving commit evidence")

    monkeypatch.setattr(duplicates, "_save_receipt", fail_receipt)
    with pytest.raises(OSError, match="Synthetic failure saving commit evidence"):
        await duplicates.apply_plan(jj_backend, plan, plan["digest"])
    snap = read_snapshot(root / "trails", strict=True)
    assert {str(p.relative_to(root)): t for p, t in snap.texts.items()} == original
    monkeypatch.setattr(duplicates, "_save_receipt", real_save)
    assert (await duplicates.apply_plan(jj_backend, plan, plan["digest"]))["status"] == "applied"
    assert (await duplicates.apply_plan(jj_backend, plan, plan["digest"], rollback=True))["status"] == "rolled_back"
    assert duplicates.capture(root) == original

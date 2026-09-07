"""Synthetic governed migrations; never touch the operator's data repository."""

import asyncio
import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fava_trails.duplicates import apply_plan, build_plan, capture, digest, report
from fava_trails.governance import Visibility, read_snapshot
from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
from fava_trails.transactions import journal_path

SCOPE = "test-jj"


def put(root, identity, *, content="Identical accepted observation.\n", status="approved", scope=SCOPE, **kwargs):
    record = ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            thought_id=identity, created_at=datetime(2026, 1, 1, tzinfo=UTC), validation_status=status, **kwargs
        ),
        content=content,
    )
    path = root / "trails" / scope / "thoughts" / "observations" / f"{identity}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.to_markdown())
    return path


def plan_for(root, **kwargs):
    info = report(root, SCOPE)
    group = info["groups"][0]
    canonical = next(m["path"] for m in group["members"] if m["frontmatter"]["thought_id"] == "A")
    return build_plan(root, SCOPE, {group["body_sha256"]: canonical}, **kwargs)


async def seed(vcs, **kwargs):
    put(vcs.repo_root, "A")
    put(vcs.repo_root, "B", **kwargs)
    paths = [str(p) for p in (vcs.repo_root / "trails").glob("**/*.md")]
    await vcs.commit_files("Synthetic migration fixture", paths)
    return plan_for(vcs.repo_root)


def all_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.asyncio
async def test_report_and_plan_make_no_repository_writes(jj_backend):
    plan = await seed(jj_backend)
    root = jj_backend.repo_root
    before = all_bytes(root)
    assert len(report(root, SCOPE)["groups"]) == 1
    assert plan_for(root) == plan
    assert all_bytes(root) == before
    assert not (root / ".jj/fava-governance.lock").exists()


@pytest.mark.asyncio
async def test_mixed_draft_preserves_approved_and_provenance(jj_backend):
    plan = await seed(jj_backend, status="draft", agent_id="synthetic-author")
    assert plan["blockers"] == []
    result = await apply_plan(jj_backend, plan, plan["digest"])
    assert result["status"] == "applied"
    snap = read_snapshot(jj_backend.repo_root / "trails", strict=True)
    assert [r.thought_id for r in snap.records.values() if Visibility().allows(r, snap.by_id)] == ["A"]
    saved = next(iter(snap.records.values()))
    assert saved.frontmatter.validation_status == "approved"
    audit = saved.frontmatter.metadata.extra["duplicate_migrations"][0]
    assert audit["removed_count"] == 1 and "removed" not in audit
    assert "synthetic-author" not in saved.model_dump_json()
    receipt = json.loads(Path(result["receipt"]).read_text())
    removed = next(o for o in receipt["plan"]["operations"] if o["after"] is None)
    assert ThoughtRecord.from_markdown(removed["before"]).frontmatter.agent_id == "synthetic-author"
    assert len(receipt["recovery_commit"]) == 40 and len(receipt["recovery_operation"]) >= 32
    assert Path(result["receipt"]).stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
async def test_safe_cross_scope_inbound_links_redirect_and_rollback_exactly(jj_backend):
    root = jj_backend.repo_root
    put(root, "A")
    put(root, "B")
    put(
        root,
        "C",
        content="Dependent observation",
        scope="other",
        parent_id="B",
        intent_ref="B",
        relationships=[{"type": "REFERENCES", "target_id": "B"}],
    )
    paths = [str(p) for p in (root / "trails").glob("**/*.md")]
    await jj_backend.commit_files("Synthetic linked fixture", paths, allowed_prefixes=["trails/"])
    before = capture(root)
    plan = plan_for(root)
    assert plan["blockers"] == []
    await apply_plan(jj_backend, plan, plan["digest"])
    saved = ThoughtRecord.from_markdown((root / "trails/other/thoughts/observations/C.md").read_text())
    assert saved.frontmatter.parent_id == saved.frontmatter.intent_ref == "A"
    assert saved.frontmatter.relationships[0].target_id == "A"
    after = all_bytes(root)
    assert (await apply_plan(jj_backend, plan, plan["digest"]))["status"] == "already_applied"
    assert all_bytes(root) == after
    assert (await apply_plan(jj_backend, plan, plan["digest"], rollback=True))["status"] == "rolled_back"
    assert capture(root) == before
    assert (await apply_plan(jj_backend, plan, plan["digest"], rollback=True))["status"] == "already_rolled_back"


@pytest.mark.asyncio
async def test_tamper_stale_and_missing_confirmation_never_write(jj_backend):
    plan = await seed(jj_backend)
    root = jj_backend.repo_root
    before = all_bytes(root)
    bad = copy.deepcopy(plan)
    bad["operations"][0]["after"] = "tampered"
    with pytest.raises(ValueError, match="digest"):
        await apply_plan(jj_backend, bad, plan["digest"])
    with pytest.raises(ValueError, match="digest"):
        await apply_plan(jj_backend, plan, "")
    assert all_bytes(root) == before
    put(root, "new", content="New inbound reference", parent_id="B")
    source_before = capture(root)
    with pytest.raises(ValueError, match="changed since review"):
        await apply_plan(jj_backend, plan, plan["digest"])
    assert capture(root) == source_before
    assert not journal_path(root).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra,expected",
    [
        ({"status": "rejected"}, "Conflicting lifecycle"),
        ({"superseded_by": "C"}, "Existing supersession"),
        ({"confidence": 0.9}, "Source/confidence conflict"),
        ({"metadata": {"extra": {"validation": {"decision": "fail"}}}}, "Validation conflict"),
        ({"parent_id": "A"}, "Outbound lineage/relationship conflict"),
    ],
)
async def test_uncertain_cases_become_blockers(jj_backend, extra, expected):
    plan = await seed(jj_backend, **extra)
    assert any(expected in b for b in plan["blockers"])
    with pytest.raises(ValueError, match="blockers"):
        await apply_plan(jj_backend, plan, plan["digest"])


@pytest.mark.asyncio
async def test_canonical_cannot_replace_approved_with_proposed(jj_backend):
    await seed(jj_backend, status="proposed")
    info = report(jj_backend.repo_root, SCOPE)
    group = info["groups"][0]
    canonical = next(m["path"] for m in group["members"] if m["frontmatter"]["thought_id"] == "B")
    plan = build_plan(jj_backend.repo_root, SCOPE, {group["body_sha256"]: canonical})
    assert any("approved current" in b for b in plan["blockers"])


@pytest.mark.asyncio
async def test_metadata_extensions_and_exact_body_survive(jj_backend):
    root = jj_backend.repo_root
    for identity in ("A", "B"):
        path = put(root, identity, content="\nBody with blank lines.  \n\n")
        path.write_text(
            path.read_text().replace(
                "schema_version: 1",
                "schema_version: 1\ncustom_validation:\n  checked: true\ncustom_provenance: imported",
            )
        )
    await jj_backend.commit_files("Synthetic extension fixture", [str(p) for p in (root / "trails").glob("**/*.md")])
    before = capture(root)
    plan = plan_for(root)
    await apply_plan(jj_backend, plan, plan["digest"])
    after = capture(root)
    original = before[next(n for n in before if n.endswith("/A.md"))]
    remaining = next(iter(after.values()))
    assert remaining.split("---", 2)[2] == original.split("---", 2)[2]
    assert "custom_provenance: imported" in remaining
    assert report(root, SCOPE)["groups"] == []


@pytest.mark.asyncio
async def test_failed_commit_restores_source_and_retry_recovers(jj_backend, monkeypatch):
    plan = await seed(jj_backend)
    before = capture(jj_backend.repo_root)
    real = jj_backend.commit_files

    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(jj_backend, "commit_files", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        await apply_plan(jj_backend, plan, plan["digest"])
    assert journal_path(jj_backend.repo_root).exists()
    monkeypatch.setattr(jj_backend, "commit_files", real)
    await apply_plan(jj_backend, plan, plan["digest"])
    assert not journal_path(jj_backend.repo_root).exists()
    await apply_plan(jj_backend, plan, plan["digest"], rollback=True)
    assert capture(jj_backend.repo_root) == before


@pytest.mark.asyncio
async def test_process_death_during_write_is_recoverable(jj_backend, tmp_path):
    plan = await seed(jj_backend)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    code = """
import asyncio,json,os,sys
from pathlib import Path
from fava_trails.duplicates import apply_plan
from fava_trails.vcs.jj_backend import JjBackend
root,planfile=sys.argv[1:]
vcs=JjBackend(Path(root),Path(root)/"trails/test-jj")
async def die(*args,**kwargs): os._exit(73)
vcs.commit_files=die
plan=json.loads(Path(planfile).read_text())
asyncio.run(apply_plan(vcs,plan,plan["digest"]))
"""
    proc = await asyncio.create_subprocess_exec(sys.executable, "-c", code, str(jj_backend.repo_root), str(plan_path))
    assert await proc.wait() == 73
    snap = read_snapshot(jj_backend.repo_root / "trails", strict=True)
    assert sorted(r.thought_id for r in snap.records.values()) == ["A", "B"]
    await apply_plan(jj_backend, plan, plan["digest"])
    assert len(capture(jj_backend.repo_root)) == 1
    await apply_plan(jj_backend, plan, plan["digest"], rollback=True)
    assert len(capture(jj_backend.repo_root)) == 2


def test_cli_default_is_read_only_and_outputs_private_artifact(tmp_path):
    from fava_trails.cli import build_parser

    root = tmp_path / "repo"
    root.mkdir()
    put(root, "A")
    put(root, "B")
    output = tmp_path / "report.json"
    args = build_parser().parse_args(["duplicates", "--repo", str(root), "--scope", SCOPE, "--out", str(output)])
    before = all_bytes(root)
    assert args.func(args) == 0
    assert output.stat().st_mode & 0o077 == 0
    assert all_bytes(root) == before


@pytest.mark.asyncio
async def test_rehashed_unsafe_plan_and_rollback_payload_are_rejected(jj_backend):
    plan = await seed(jj_backend)
    bad = copy.deepcopy(plan)
    bad["operations"][0]["after"] = "Injected different content"
    bad["digest"] = digest({k: v for k, v in bad.items() if k != "digest"})
    with pytest.raises(ValueError, match="safe migration rules"):
        await apply_plan(jj_backend, bad, bad["digest"])
    await apply_plan(jj_backend, plan, plan["digest"])
    bad = copy.deepcopy(plan)
    bad["operations"][0]["before"] += "Injected extra body"
    bad["digest"] = digest({k: v for k, v in bad.items() if k != "digest"})
    with pytest.raises(ValueError, match="safe migration rules"):
        await apply_plan(jj_backend, bad, bad["digest"], rollback=True)


@pytest.mark.asyncio
async def test_unrelated_dirty_file_blocks_apply_and_preserves_content(jj_backend):
    plan = await seed(jj_backend)
    other = jj_backend.repo_root / "unrelated.txt"
    other.write_text("Uncommitted operator work")
    before = capture(jj_backend.repo_root)
    with pytest.raises(ValueError, match="clean working change"):
        await apply_plan(jj_backend, plan, plan["digest"])
    assert capture(jj_backend.repo_root) == before
    assert other.read_text() == "Uncommitted operator work"


@pytest.mark.asyncio
async def test_empty_record_is_reported_and_blocks_unknown_inbound_context(jj_backend):
    await seed(jj_backend)
    empty = jj_backend.repo_root / "trails/other/thoughts/observations/empty.md"
    empty.parent.mkdir(parents=True)
    empty.write_text("")
    result = report(jj_backend.repo_root, SCOPE)
    assert len(result["groups"]) == 1
    assert "trails/other/thoughts/observations/empty.md" in result["invalid_records"]
    assert any("Unparseable" in b for b in plan_for(jj_backend.repo_root)["blockers"])


@pytest.mark.asyncio
async def test_exact_body_whitespace_is_not_normalized(jj_backend):
    put(jj_backend.repo_root, "A", content="Body\n")
    put(jj_backend.repo_root, "B", content="Body \n")
    assert report(jj_backend.repo_root, SCOPE)["groups"] == []


@pytest.mark.asyncio
async def test_ambiguous_global_identity_is_a_blocker(jj_backend):
    await seed(jj_backend)
    put(jj_backend.repo_root, "B", scope="other")
    assert any("Ambiguous thought identity" in b for b in plan_for(jj_backend.repo_root)["blockers"])


@pytest.mark.asyncio
async def test_all_draft_group_stays_unapproved(jj_backend):
    root = jj_backend.repo_root
    put(root, "A", status="draft")
    put(root, "B", status="draft")
    await jj_backend.commit_files("Synthetic drafts", [str(p) for p in (root / "trails").glob("**/*.md")])
    plan = plan_for(root)
    assert plan["blockers"] == []
    await apply_plan(jj_backend, plan, plan["digest"])
    snap = read_snapshot(root / "trails", strict=True)
    assert len(snap.records) == 1
    assert not any(Visibility().allows(r, snap.by_id) for r in snap.records.values())


@pytest.mark.asyncio
async def test_corrupt_existing_recovery_receipt_blocks_source_mutation(jj_backend):
    plan = await seed(jj_backend)
    receipt = jj_backend.repo_root / ".jj/fava-migrations" / (plan["digest"] + ".json")
    receipt.parent.mkdir()
    receipt.write_text('{"plan": {}}')
    before = capture(jj_backend.repo_root)
    with pytest.raises(ValueError, match="Recovery receipt is invalid"):
        await apply_plan(jj_backend, plan, plan["digest"])
    assert capture(jj_backend.repo_root) == before
    assert not journal_path(jj_backend.repo_root).exists()


@pytest.mark.asyncio
async def test_crlf_failure_retry_apply_and_rollback_preserve_exact_bytes(jj_backend, monkeypatch):
    root = jj_backend.repo_root
    paths = [put(root, identity) for identity in ("A", "B")]
    for path in paths:
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    await jj_backend.commit_files("Synthetic CRLF sources", [str(path) for path in paths])
    original = {path: path.read_bytes() for path in paths}
    plan = plan_for(root)
    commit = jj_backend.commit_files

    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic CRLF persistence failure")

    monkeypatch.setattr(jj_backend, "commit_files", fail)
    with pytest.raises(RuntimeError, match="CRLF persistence failure"):
        await apply_plan(jj_backend, plan, plan["digest"])
    assert {path: path.read_bytes() for path in paths} == original
    before = json.loads(journal_path(root).read_bytes())["before"]
    assert all(before[str(path.relative_to(root))].encode() == original[path] for path in paths)
    snapshot = read_snapshot(root / "trails", strict=True)
    assert {path: text.encode() for path, text in snapshot.texts.items()} == original
    monkeypatch.setattr(jj_backend, "commit_files", commit)
    assert (await apply_plan(jj_backend, plan, plan["digest"]))["status"] == "applied"
    for operation in plan["operations"]:
        path = root / operation["path"]
        if operation["after"] is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == operation["after"].encode()
    assert (await apply_plan(jj_backend, plan, plan["digest"], rollback=True))["status"] == "rolled_back"
    assert {path: path.read_bytes() for path in paths} == original


@pytest.mark.asyncio
async def test_post_commit_crash_receipt_is_finalized_by_verified_retry(jj_backend, monkeypatch):
    import fava_trails.duplicates as maintenance

    plan = await seed(jj_backend)
    persist = maintenance.persist_governance

    async def crash_after_publication(*args, **kwargs):
        await persist(*args, **kwargs)
        raise SystemExit("Synthetic interruption after publication")

    monkeypatch.setattr(maintenance, "persist_governance", crash_after_publication)
    with pytest.raises(SystemExit):
        await apply_plan(jj_backend, plan, plan["digest"])
    receipt = jj_backend.repo_root / ".jj/fava-migrations" / (plan["digest"] + ".json")
    prepared = json.loads(receipt.read_text())
    assert prepared["status"] == "prepared" and len(prepared["committed_commit"]) == 40
    monkeypatch.setattr(maintenance, "persist_governance", persist)
    assert (await apply_plan(jj_backend, plan, plan["digest"]))["status"] == "already_applied"
    assert json.loads(receipt.read_text())["status"] == "applied"
    receipt.write_text('{"status":"applied","plan":{}}')
    with pytest.raises(ValueError, match="Recovery receipt"):
        await apply_plan(jj_backend, plan, plan["digest"])


@pytest.mark.asyncio
async def test_matching_after_images_without_receipt_are_not_success(jj_backend):
    plan = await seed(jj_backend)
    for operation in plan["operations"]:
        path = jj_backend.repo_root / operation["path"]
        if operation["after"] is None:
            path.unlink()
        else:
            path.write_bytes(operation["after"].encode())
    with pytest.raises(ValueError, match="Recovery receipt"):
        await apply_plan(jj_backend, plan, plan["digest"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "proposed"])
async def test_private_provenance_remains_operator_only_after_migration(jj_backend, monkeypatch, status):
    from fava_trails.tools.recall import handle_recall
    from fava_trails.trail import TrailManager

    marker = "SYNTHETIC_PRIVATE_AUTHOR_CONTEXT"
    plan = await seed(jj_backend, status=status, agent_id="private-author", metadata={"extra": {"work_note": marker}})
    trail = TrailManager(SCOPE, vcs=jj_backend)
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "different-author")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    assert marker not in json.dumps(await handle_recall(trail, {}))
    assert marker not in json.dumps(await handle_recall(trail, {"mode": "authoring"}))
    with pytest.raises(PermissionError):
        await handle_recall(trail, {"mode": "history"})
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "private-author")
    assert marker in json.dumps(await handle_recall(trail, {"mode": "authoring"}))
    result = await apply_plan(jj_backend, plan, plan["digest"])
    assert marker in Path(result["receipt"]).read_text()
    for identity in ("private-author", "different-author"):
        monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", identity)
        assert marker not in json.dumps(await handle_recall(trail, {}))
        assert (await handle_recall(trail, {"mode": "authoring"}))["thoughts"] == []
    monkeypatch.setenv("FAVA_TRAILS_OPERATOR", "1")
    history = await handle_recall(trail, {"mode": "history"})
    assert [t["thought_id"] for t in history["thoughts"]] == ["A"]
    assert marker not in json.dumps(history)

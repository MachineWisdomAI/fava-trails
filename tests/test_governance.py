"""Issue 72: synthetic visibility, identity and durable replacement acceptance."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from fava_trails import server
from fava_trails.governance import Principal, Visibility
from fava_trails.models import SourceType, ThoughtFrontmatter, ThoughtRecord, ValidationStatus
from fava_trails.rich_views import generate_reader
from fava_trails.trail import recall_multi
from fava_trails.transactions import journal_path
from fava_trails.trust_gate import TrustResult


def approved(kind="llm_advisory"):
    return TrustResult(verdict="approve", reasoning="Synthetic review", reviewer="test-reviewer", approval_kind=kind)


@pytest.fixture
def lifecycle_data(tmp_fava_home, monkeypatch):
    server._trail_managers.clear()
    monkeypatch.delenv("FAVA_TRAILS_AGENT_ID", raising=False)
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    result = {}
    for scope in ("example/project", "example/other"):
        for status in ValidationStatus:
            for author in ("alice", "bob"):
                record = ThoughtRecord(
                    frontmatter=ThoughtFrontmatter(agent_id=author, validation_status=status),
                    content=f"Private fixture {scope} {status.value} {author}",
                )
                path = tmp_fava_home / "trails" / scope / "thoughts" / "drafts" / f"{record.thought_id}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(record.to_markdown())
                result[(scope, status.value, author)] = record
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("multi", [False, True])
async def test_default_recall_only_current_approved(lifecycle_data, multi):
    args = {"trail_name": "example/project"}
    if multi:
        args["trail_names"] = ["example/other"]
    result = await server.handle_call_tool("recall", args)
    assert result["status"] == "ok"
    assert len(result["thoughts"]) == (4 if multi else 2)
    assert {t["validation_status"] for t in result["thoughts"]} == {"approved"}


@pytest.mark.asyncio
@pytest.mark.parametrize("multi", [False, True])
async def test_authoring_is_explicit_and_owner_scoped(lifecycle_data, monkeypatch, multi):
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "alice")
    args = {"trail_name": "example/project", "mode": "authoring"}
    if multi:
        args["trail_names"] = ["example/other"]
    result = await server.handle_call_tool("recall", args)
    assert result["status"] == "ok"
    assert len(result["thoughts"]) == (4 if multi else 2)
    assert {t["agent_id"] for t in result["thoughts"]} == {"alice"}
    assert {t["validation_status"] for t in result["thoughts"]} == {"draft", "proposed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"mode": "authoring"},
        {"mode": "history"},
        {"include_superseded": True},
        {"statuses": ["draft"]},
        {"operator": True},
        {"principal": {"agent_id": "bob"}},
    ],
)
async def test_unconfigured_endpoint_cannot_widen_visibility(lifecycle_data, extra):
    result = await server.handle_call_tool("recall", {"trail_name": "example/project", **extra})
    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "proposed", "rejected", "error", "tombstoned"])
async def test_direct_and_global_lookup_do_not_leak_hidden_records(lifecycle_data, status):
    target = lifecycle_data[("example/project", status, "bob")]
    for scope in ("example/project", "missing/scope"):
        result = await server.handle_call_tool("get_thought", {"trail_name": scope, "thought_id": target.thought_id})
        assert result["status"] == "error"
        assert target.content not in json.dumps(result)


@pytest.mark.asyncio
async def test_agent_cannot_claim_another_identity_or_read_their_draft(lifecycle_data, monkeypatch):
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "alice")
    result = await server.handle_call_tool(
        "save_thought", {"trail_name": "example/project", "content": "spoof", "agent_id": "bob"}
    )
    assert result["status"] == "error"
    target = lifecycle_data[("example/project", "draft", "bob")]
    for name in ("get_thought", "update_thought", "propose_truth", "supersede"):
        result = await server.handle_call_tool(
            name,
            {
                "trail_name": "example/project",
                "mode": "authoring",
                "thought_id": target.thought_id,
                "content": "spoof",
                "reason": "spoof",
            },
        )
        assert result["status"] == "error"
        assert target.content not in json.dumps(result)


@pytest.mark.asyncio
async def test_operator_history_selects_lifecycle_statuses(lifecycle_data, monkeypatch):
    monkeypatch.setenv("FAVA_TRAILS_OPERATOR", "1")
    result = await server.handle_call_tool(
        "recall",
        {
            "trail_name": "example/project",
            "mode": "history",
            "statuses": ["rejected", "tombstoned"],
            "include_superseded": True,
        },
    )
    assert result["status"] == "ok"
    assert len(result["thoughts"]) == 4
    assert {t["validation_status"] for t in result["thoughts"]} == {"rejected", "tombstoned"}


@pytest.mark.asyncio
async def test_replacement_is_current_only_after_approval(trail_manager):
    old = await trail_manager.save_thought("Old approved decision", source_type=SourceType.DECISION, agent_id="alice")
    await trail_manager.propose_truth(old.thought_id, approved())
    new = await trail_manager.supersede(old.thought_id, "Corrected decision", agent_id="alice")
    assert [r.thought_id for r in await trail_manager.recall()] == [old.thought_id]
    assert not (await trail_manager.get_thought(old.thought_id)).is_superseded
    await trail_manager.propose_truth(new.thought_id)
    assert [r.thought_id for r in await trail_manager.recall()] == [old.thought_id]
    await trail_manager.propose_truth(new.thought_id, approved())
    assert [r.thought_id for r in await trail_manager.recall()] == [new.thought_id]
    history = await trail_manager.recall(
        visibility=Visibility(mode="history", principal=Principal(operator=True), include_superseded=True)
    )
    assert {r.thought_id for r in history} == {old.thought_id, new.thought_id}
    again = await trail_manager.propose_truth(new.thought_id)
    assert again.frontmatter.validation_status == ValidationStatus.APPROVED


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("persistence interrupted"), asyncio.CancelledError()])
async def test_failed_approval_keeps_original_current_and_retry_recovers(trail_manager, monkeypatch, failure):
    old = await trail_manager.save_thought("Old truth", agent_id="alice")
    await trail_manager.propose_truth(old.thought_id, approved())
    new = await trail_manager.supersede(old.thought_id, "Replacement", agent_id="alice")
    commit = trail_manager.vcs.commit_files
    monkeypatch.setattr(trail_manager.vcs, "commit_files", AsyncMock(side_effect=failure))
    with pytest.raises(type(failure)):
        await trail_manager.propose_truth(new.thought_id, approved())
    assert [r.thought_id for r in await trail_manager.recall()] == [old.thought_id]
    assert not (await trail_manager.get_thought(old.thought_id)).is_superseded
    monkeypatch.setattr(trail_manager.vcs, "commit_files", commit)
    await trail_manager.propose_truth(new.thought_id, approved())
    assert [r.thought_id for r in await trail_manager.recall()] == [new.thought_id]
    assert not journal_path(trail_manager.vcs.repo_root).exists()


@pytest.mark.asyncio
async def test_read_during_persistence_fails_closed_until_complete(trail_manager, monkeypatch):
    old = await trail_manager.save_thought("Old truth", agent_id="alice")
    await trail_manager.propose_truth(old.thought_id, approved())
    new = await trail_manager.supersede(old.thought_id, "Replacement", agent_id="alice")
    commit = trail_manager.vcs.commit_files

    async def paused_commit(*args, **kwargs):
        with pytest.raises(RuntimeError, match="transaction in progress"):
            await trail_manager.recall()
        return await commit(*args, **kwargs)

    monkeypatch.setattr(trail_manager.vcs, "commit_files", paused_commit)
    await trail_manager.propose_truth(new.thought_id, approved())
    assert [r.thought_id for r in await trail_manager.recall()] == [new.thought_id]


@pytest.mark.asyncio
async def test_cross_scope_replacement_and_visibility(nested_trail_managers):
    original_trail = nested_trail_managers["project"]
    target = nested_trail_managers["team"]
    old = await original_trail.save_thought("Old", agent_id="alice")
    await original_trail.propose_truth(old.thought_id, approved())
    new = await original_trail.supersede(old.thought_id, "New", agent_id="alice", target_trail=target)
    assert [r.thought_id for r in await original_trail.recall()] == [old.thought_id]
    await target.propose_truth(new.thought_id, approved("human"))
    assert await original_trail.recall() == []
    assert [r.thought_id for r, _ in await recall_multi([original_trail, target])] == [new.thought_id]


@pytest.mark.asyncio
async def test_approval_provenance_is_explicit_and_not_inherited(trail_manager):
    old = await trail_manager.save_thought("Old", agent_id="alice")
    reviewed = await trail_manager.propose_truth(old.thought_id, approved("human"))
    assert reviewed.frontmatter.metadata.extra["approval"]["kind"] == "human"
    new = await trail_manager.supersede(old.thought_id, "New", agent_id="bob")
    assert "approval" not in new.frontmatter.metadata.extra
    assert "trust_gate" not in new.frontmatter.metadata.extra
    reviewed = await trail_manager.propose_truth(new.thought_id, approved())
    assert reviewed.frontmatter.metadata.extra["approval"]["kind"] == "llm_advisory"


@pytest.mark.asyncio
async def test_legacy_backlink_to_unapproved_successor_does_not_hide_truth(trail_manager):
    old = await trail_manager.save_thought("Old", agent_id="alice")
    await trail_manager.propose_truth(old.thought_id, approved())
    new = await trail_manager.save_thought("Pending correction", agent_id="bob")
    old_path = trail_manager._find_thought_path(old.thought_id)
    record = ThoughtRecord.from_markdown(old_path.read_text())
    record.frontmatter.superseded_by = new.thought_id
    old_path.write_text(record.to_markdown())
    assert [r.thought_id for r in await trail_manager.recall()] == [old.thought_id]


def test_reader_respects_same_governed_and_operator_views(lifecycle_data, tmp_fava_home, tmp_path):
    kwargs = {"trails_dir": tmp_fava_home / "trails", "scope": "example/project"}
    default = generate_reader(**kwargs, output_dir=tmp_path / "governed")
    assert default.thought_count == 2
    hidden = lifecycle_data[("example/project", "draft", "bob")]
    assert not (default.output_dir / "src/pages/id" / f"{hidden.thought_id}.md").exists()
    history = generate_reader(
        **kwargs,
        output_dir=tmp_path / "history",
        visibility=Visibility(mode="history", principal=Principal(operator=True), statuses=("rejected",)),
    )
    assert history.thought_count == 2


def test_mcp_schema_exposes_modes_but_not_principal():
    for name in ("recall", "get_thought"):
        tool = next(t for t in server.TOOL_DEFINITIONS if t["name"] == name)
        props = tool["inputSchema"]["properties"]
        assert props["mode"]["default"] == "governed"
        assert "principal" not in props and "operator" not in props


@pytest.mark.asyncio
async def test_relationship_expansion_cannot_reveal_private_or_unselected_authoring(
    lifecycle_data, tmp_fava_home, monkeypatch
):
    from fava_trails.models import Relationship, RelationshipType

    root = tmp_fava_home / "trails"
    seed = lifecycle_data[("example/project", "approved", "alice")]
    hidden = lifecycle_data[("example/project", "draft", "bob")]
    seed.frontmatter.relationships = [Relationship(type=RelationshipType.REFERENCES, target_id=hidden.thought_id)]
    (root / "example/project/thoughts/drafts" / f"{seed.thought_id}.md").write_text(seed.to_markdown())
    result = await server.handle_call_tool(
        "recall", {"trail_name": "example/project", "query": seed.thought_id, "include_relationships": True}
    )
    assert [t["thought_id"] for t in result["thoughts"]] == [seed.thought_id]
    local = lifecycle_data[("example/project", "draft", "alice")]
    elsewhere = lifecycle_data[("example/other", "draft", "alice")]
    local.frontmatter.relationships = [Relationship(type=RelationshipType.REFERENCES, target_id=elsewhere.thought_id)]
    (root / "example/project/thoughts/drafts" / f"{local.thought_id}.md").write_text(local.to_markdown())
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "alice")
    result = await server.handle_call_tool(
        "recall",
        {
            "trail_name": "example/project",
            "mode": "authoring",
            "query": local.thought_id,
            "include_relationships": True,
        },
    )
    assert [t["thought_id"] for t in result["thoughts"]] == [local.thought_id]


@pytest.mark.asyncio
async def test_stale_review_cannot_approve_edited_content(trail_manager):
    draft = await trail_manager.save_thought("Reviewed content", agent_id="alice")
    await trail_manager.update_thought(draft.thought_id, "Different content")
    with pytest.raises(ValueError, match="changed during review"):
        await trail_manager.propose_truth(draft.thought_id, approved(), reviewed_record=draft)
    assert await trail_manager.recall() == []


@pytest.mark.asyncio
async def test_human_approval_requires_operator_and_records_provenance(trail_manager, monkeypatch):
    server._trail_managers.clear()
    server._trail_managers[trail_manager.trail_name] = trail_manager
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "alice")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    draft = await trail_manager.save_thought("Reviewed by operator", agent_id="alice")
    arguments = {"trail_name": trail_manager.trail_name, "thought_id": draft.thought_id, "approval": "human"}
    rejected = await server.handle_call_tool("propose_truth", arguments)
    assert rejected["status"] == "error"
    monkeypatch.setenv("FAVA_TRAILS_OPERATOR", "1")
    result = await server.handle_call_tool("propose_truth", arguments)
    assert result["status"] == "ok"
    assert result["thought"]["metadata"]["extra"]["approval"]["kind"] == "human"


@pytest.mark.asyncio
async def test_process_death_mid_approval_keeps_old_view_and_recovers(trail_manager, tmp_path):
    import subprocess
    import sys

    old = await trail_manager.save_thought("Original governed truth", agent_id="alice")
    await trail_manager.propose_truth(old.thought_id, approved())
    new = await trail_manager.supersede(old.thought_id, "Replacement", agent_id="alice")
    marker = tmp_path / "persistence-entered"
    script = """
import asyncio, sys
from pathlib import Path
from fava_trails.trail import TrailManager
from fava_trails.vcs.jj_backend import JjBackend
from fava_trails.trust_gate import TrustResult
async def main():
    root, name, thought_id, marker = sys.argv[1:]
    vcs=JjBackend(repo_root=Path(root),trail_path=Path(root)/"trails"/name)
    manager=TrailManager(name,vcs=vcs)
    async def interrupted_commit(*args,**kwargs):
        Path(marker).write_text("writes completed, durable commit pending")
        await asyncio.Event().wait()
    vcs.commit_files=interrupted_commit
    await manager.propose_truth(thought_id,TrustResult(verdict="approve",reasoning="fixture",reviewer="fixture"))
asyncio.run(main())
"""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(trail_manager.vcs.repo_root),
            trail_manager.trail_name,
            new.thought_id,
            str(marker),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if marker.exists() or proc.poll() is not None:
                break
            await asyncio.sleep(0.05)
        assert marker.exists(), (
            proc.stderr.read().decode() if proc.poll() is not None else "child did not enter persistence"
        )
        proc.kill()
        proc.wait(timeout=10)
        assert [r.thought_id for r in await trail_manager.recall()] == [old.thought_id]
        await trail_manager.propose_truth(new.thought_id, approved())
        assert [r.thought_id for r in await trail_manager.recall()] == [new.thought_id]
        assert not journal_path(trail_manager.vcs.repo_root).exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        proc.stderr.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["reject", "error"])
async def test_unsuccessful_review_does_not_retire_approved_original(trail_manager, verdict):
    old = await trail_manager.save_thought("Original", agent_id="alice")
    await trail_manager.propose_truth(old.thought_id, approved())
    new = await trail_manager.supersede(old.thought_id, "Proposal", agent_id="alice")
    await trail_manager.propose_truth(
        new.thought_id, TrustResult(verdict=verdict, reasoning="Fixture", reviewer="fixture")
    )
    assert [r.thought_id for r in await trail_manager.recall()] == [old.thought_id]
    assert not (await trail_manager.get_thought(old.thought_id)).is_superseded


@pytest.mark.asyncio
async def test_failed_publication_after_commit_keeps_original_current(trail_manager, monkeypatch):
    from fava_trails import transactions

    old = await trail_manager.save_thought("Original", agent_id="alice")
    await trail_manager.propose_truth(old.thought_id, approved())
    new = await trail_manager.supersede(old.thought_id, "Proposal", agent_id="alice")
    replace = transactions._replace
    failed = False

    def fail_publication(path, text):
        nonlocal failed
        if path == journal_path(trail_manager.vcs.repo_root) and text is None and not failed:
            failed = True
            replace(path, text)
            raise OSError("Synthetic publication failure after journal removal")
        return replace(path, text)

    monkeypatch.setattr(transactions, "_replace", fail_publication)
    with pytest.raises(OSError, match="Synthetic publication"):
        await trail_manager.propose_truth(new.thought_id, approved())
    assert [r.thought_id for r in await trail_manager.recall()] == [old.thought_id]
    monkeypatch.setattr(transactions, "_replace", replace)
    await trail_manager.propose_truth(new.thought_id, approved())
    assert [r.thought_id for r in await trail_manager.recall()] == [new.thought_id]


@pytest.mark.asyncio
async def test_mcp_stamps_server_identity_and_prevents_forged_provenance(trail_manager, monkeypatch):
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "alice")
    monkeypatch.delenv("FAVA_TRAILS_OPERATOR", raising=False)
    server._trail_managers.clear()
    server._trail_managers[trail_manager.trail_name] = trail_manager
    result = await server.handle_call_tool(
        "save_thought", {"trail_name": trail_manager.trail_name, "content": "Alice private draft"}
    )
    assert result["status"] == "ok"
    assert result["thought"]["agent_id"] == "alice"
    forged = await server.handle_call_tool(
        "save_thought",
        {
            "trail_name": trail_manager.trail_name,
            "content": "Forged human approval",
            "metadata": {"extra": {"approval": {"kind": "human"}}},
        },
    )
    assert forged["status"] == "error"
    monkeypatch.setenv("FAVA_TRAILS_AGENT_ID", "bob")
    result = await server.handle_call_tool("recall", {"trail_name": trail_manager.trail_name, "mode": "authoring"})
    assert result["thoughts"] == []

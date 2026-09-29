"""Real JJ lifecycle integration on a disposable data repo.

Runs against whatever `jj` is on PATH (CI matrix covers min + current stable).
Covers init, save, promote/reject freeze, supersede, status, and sync plumbing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from fava_trails.jj_install import JJ_MIN_VERSION, Version, parse_version_from_output
from fava_trails.models import SourceType, ValidationStatus
from fava_trails.trail import TrailManager
from fava_trails.trust_gate import TrustResult
from fava_trails.vcs.jj_backend import JjBackend

jj_bin = shutil.which("jj") or str(Path.home() / ".local" / "bin" / "jj")
if not Path(jj_bin).exists():
    pytest.skip("jj binary not found", allow_module_level=True)


def _jj_version() -> Version:
    out = subprocess.run([jj_bin, "--version"], capture_output=True, text=True, check=True)
    ver = parse_version_from_output(out.stdout)
    assert ver is not None, out.stdout
    return ver


def review_approval() -> TrustResult:
    return TrustResult(verdict="approve", reasoning="compat matrix approval", reviewer="fixture")


def test_jj_version_meets_minimum():
    ver = _jj_version()
    assert ver >= Version.parse(JJ_MIN_VERSION), f"jj {ver} below minimum {JJ_MIN_VERSION}"


@pytest.mark.asyncio
async def test_lifecycle_init_save_promote_reject_supersede_status_sync(tmp_fava_home):
    """End-to-end thought lifecycle on disposable repo with live JJ."""
    trail_path = tmp_fava_home / "trails" / "mw" / "eng" / "jj-compat"
    backend = JjBackend(repo_root=tmp_fava_home, trail_path=trail_path)
    mgr = TrailManager("mw/eng/jj-compat", vcs=backend)
    await mgr.init()

    # status / current change
    current = await backend.current_change()
    assert current is not None

    # save draft
    saved = await mgr.save_thought(
        content="compat observation",
        source_type=SourceType.OBSERVATION,
        confidence=0.7,
        agent_id="test",
    )
    assert saved.thought_id
    drafts_path = trail_path / "thoughts" / "drafts" / f"{saved.thought_id}.md"
    assert drafts_path.exists()

    # promote
    promoted = await mgr.propose_truth(saved.thought_id)
    assert promoted.frontmatter.validation_status.value == "proposed"
    obs_path = trail_path / "thoughts" / "observations" / f"{saved.thought_id}.md"
    assert obs_path.exists()
    assert not drafts_path.exists()

    # approve then supersede
    approved = await mgr.propose_truth(saved.thought_id, review_approval())
    assert approved.frontmatter.validation_status == ValidationStatus.APPROVED

    successor = await mgr.supersede(
        original_id=saved.thought_id,
        new_content="corrected observation",
        reason="integration evidence",
        agent_id="test",
    )
    assert successor.thought_id != saved.thought_id
    await mgr.propose_truth(successor.thought_id, review_approval())
    refreshed = await mgr.get_thought(saved.thought_id)
    assert refreshed is not None
    assert refreshed.frontmatter.superseded_by == successor.thought_id

    # rejection freeze path
    other = await mgr.save_thought(content="to reject", agent_id="test")
    path = mgr._find_thought_path(other.thought_id)
    assert path is not None
    from fava_trails.models import ThoughtRecord

    loaded = ThoughtRecord.from_markdown(path.read_text())
    loaded.frontmatter.validation_status = ValidationStatus.REJECTED
    path.write_text(loaded.to_markdown())
    with pytest.raises(ValueError, match="frozen"):
        await mgr.update_thought(other.thought_id, "should fail")

    # status
    stdout, _ = await backend._run("status")
    assert isinstance(stdout, str)

    # sync plumbing without remote: dirty or clean result object
    result = await backend.fetch_and_rebase()
    assert result is not None
    assert hasattr(result, "success")

"""Tests for JjBackend VCS operations."""

import subprocess
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_init_trail(jj_backend):
    """.jj and .git at repo_root (monorepo), trail_path is just a directory."""
    assert (jj_backend.repo_root / ".jj").exists()
    assert (jj_backend.repo_root / ".git").exists()
    # trail_path has no .jj/.git — it's a subdirectory of the monorepo
    assert jj_backend.trail_path.exists()
    assert not (jj_backend.trail_path / ".jj").exists()
    assert not (jj_backend.trail_path / ".git").exists()


@pytest.mark.asyncio
async def test_init_trail_idempotent(jj_backend):
    """Re-initializing should not fail."""
    await jj_backend.init_trail()
    # Trail dir already exists, should report that
    assert jj_backend.trail_path.exists()


@pytest.mark.asyncio
async def test_init_monorepo_three_case_existing_git(tmp_path):
    """Case 1: .git exists, no .jj → colocate JJ on top."""
    from fava_trails.vcs.jj_backend import JjBackend

    repo = tmp_path / "repo"
    repo.mkdir()
    # Create a bare git repo first
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    assert (repo / ".git").exists()
    assert not (repo / ".jj").exists()

    trail = repo / "trails" / "test"
    trail.mkdir(parents=True)
    backend = JjBackend(repo_root=repo, trail_path=trail)
    await backend.init_monorepo()

    # Now both should exist
    assert (repo / ".jj").exists()
    assert (repo / ".git").exists()


@pytest.mark.asyncio
async def test_init_monorepo_three_case_both_exist(jj_backend):
    """Case 2: Both .jj and .git exist → skip, just configure."""
    result = await jj_backend.init_monorepo()
    assert "initialized" in result.lower()
    assert (jj_backend.repo_root / ".jj").exists()
    assert (jj_backend.repo_root / ".git").exists()


@pytest.mark.asyncio
async def test_init_monorepo_three_case_neither(tmp_path):
    """Case 3: Neither exists → fresh init."""
    from fava_trails.vcs.jj_backend import JjBackend

    repo = tmp_path / "fresh-repo"
    trail = repo / "trails" / "test"
    backend = JjBackend(repo_root=repo, trail_path=trail)
    await backend.init_monorepo()

    assert (repo / ".jj").exists()
    assert (repo / ".git").exists()


@pytest.mark.asyncio
async def test_init_monorepo_sets_snapshot_conflict_style(tmp_path):
    """init_monorepo configures snapshot-style conflict markers."""
    from fava_trails.vcs.jj_backend import JjBackend

    repo = tmp_path / "snap-repo"
    trail = repo / "trails" / "test"
    backend = JjBackend(repo_root=repo, trail_path=trail)
    await backend.init_monorepo()

    # Verify the config was set
    proc = subprocess.run(
        ["jj", "config", "get", "ui.conflict-marker-style"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert proc.stdout.strip() == "snapshot"


@pytest.mark.asyncio
async def test_current_change(jj_backend):
    """Should return the current working change."""
    change = await jj_backend.current_change()
    assert change is not None
    assert change.change_id


@pytest.mark.asyncio
async def test_new_change(jj_backend):
    """Creating a new change should return a VcsChange."""
    change = await jj_backend.new_change("test change")
    assert change is not None
    assert change.change_id


@pytest.mark.asyncio
async def test_describe(jj_backend):
    """Setting description should work."""
    result = await jj_backend.describe("test description")
    assert "test description" in result


@pytest.mark.asyncio
async def test_log_path_scoped(jj_backend):
    """Log should be scoped to trail path — only shows trail-relevant commits."""
    # Write a file in the trail
    test_file = jj_backend.trail_path / "test.md"
    test_file.write_text("# Trail file")
    await jj_backend.commit_files("add trail file", [str(test_file)])

    # Log should show the commit
    changes = await jj_backend.log()
    descriptions = [c.description for c in changes]
    assert any("add trail file" in d for d in descriptions)


@pytest.mark.asyncio
async def test_log_does_not_show_other_trails(jj_backend):
    """Log should not show commits from other trail paths."""
    # Write a file OUTSIDE the trail path but inside repo
    other_trail = jj_backend.repo_root / "trails" / "other-trail"
    other_trail.mkdir(parents=True)
    other_file = other_trail / "other.md"
    other_file.write_text("# Other trail")
    # Commit via JJ at repo root (bypassing the backend's commit_files assertion)
    subprocess.run(
        ["jj", "describe", "-m", "other trail commit"],
        cwd=str(jj_backend.repo_root), capture_output=True,
    )
    subprocess.run(
        ["jj", "new"],
        cwd=str(jj_backend.repo_root), capture_output=True,
    )

    # Log scoped to jj_backend's trail should NOT show the other trail commit
    changes = await jj_backend.log()
    descriptions = [c.description for c in changes]
    assert not any("other trail commit" in d for d in descriptions)


@pytest.mark.asyncio
async def test_diff_path_scoped(jj_backend):
    """Diff should be scoped to trail path."""
    test_file = jj_backend.trail_path / "diff-test.md"
    test_file.write_text("# Diff test")
    diff = await jj_backend.diff()
    # Should show the change in our trail
    assert diff.summary is not None


@pytest.mark.asyncio
async def test_op_log(jj_backend):
    """Op log should return at least the init operation."""
    ops = await jj_backend.op_log()
    assert len(ops) > 0
    for op in ops:
        assert op.op_id
        assert op.description


@pytest.mark.asyncio
async def test_conflicts_none(jj_backend):
    """Fresh trail should have no conflicts."""
    conflicts = await jj_backend.conflicts()
    assert conflicts == []


@pytest.mark.asyncio
async def test_commit_files_parameter_order(jj_backend):
    """commit_files takes (message, paths) — message first."""
    test_file = jj_backend.trail_path / "param-test.md"
    test_file.write_text("# Parameter order test")
    change = await jj_backend.commit_files("param order test", [str(test_file)])
    assert change.description == "param order test"

    # Verify in log
    changes = await jj_backend.log(limit=5)
    descriptions = [c.description for c in changes]
    assert any("param order test" in d for d in descriptions)


@pytest.mark.asyncio
async def test_commit_files_cross_trail_pollution_assertion(jj_backend):
    """commit_files should abort if dirty files are outside the trail prefix."""
    # Write a file outside the trail but inside the repo
    outside_file = jj_backend.repo_root / "trails" / "other-trail" / "evil.md"
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_text("# Cross-trail pollution")

    with pytest.raises(RuntimeError, match="Cross-trail pollution detected"):
        await jj_backend.commit_files("should fail", [str(outside_file)])


@pytest.mark.asyncio
async def test_gc(jj_backend):
    """GC should complete without error."""
    result = await jj_backend.gc()
    assert "completed" in result.lower()


# --- Phase 1b.4: Conflict content extraction ---


def test_parse_snapshot_conflict_single():
    """Parse a single snapshot-style conflict block."""
    from fava_trails.vcs.jj_backend import JjBackend

    text = """\
<<<<<<< Conflict 1 of 1
+++++++ Contents of side #1
Side A content line 1
Side A content line 2
------- Contents of base
Base content line 1
+++++++ Contents of side #2
Side B content line 1
>>>>>>> Conflict 1 of 1
"""
    side_a, base, side_b = JjBackend.parse_snapshot_conflict(text)
    assert side_a == "Side A content line 1\nSide A content line 2"
    assert base == "Base content line 1"
    assert side_b == "Side B content line 1"


def test_parse_snapshot_conflict_multiple():
    """Parse multiple conflict blocks in one file (e.g., frontmatter + content)."""
    from fava_trails.vcs.jj_backend import JjBackend

    text = """\
Some preamble
<<<<<<< Conflict 1 of 2
+++++++ Contents of side #1
frontmatter side A
------- Contents of base
frontmatter base
+++++++ Contents of side #2
frontmatter side B
>>>>>>> Conflict 1 of 2
middle text
<<<<<<< Conflict 2 of 2
+++++++ Contents of side #1
content side A
------- Contents of base
content base
+++++++ Contents of side #2
content side B
>>>>>>> Conflict 2 of 2
"""
    side_a, base, side_b = JjBackend.parse_snapshot_conflict(text)
    # Multiple blocks concatenated
    assert "frontmatter side A" in side_a
    assert "content side A" in side_a
    assert "frontmatter base" in base
    assert "content base" in base
    assert "frontmatter side B" in side_b
    assert "content side B" in side_b


def test_parse_snapshot_conflict_no_markers():
    """File without conflict markers returns all None."""
    from fava_trails.vcs.jj_backend import JjBackend

    text = "Normal file content\nNo conflicts here."
    side_a, base, side_b = JjBackend.parse_snapshot_conflict(text)
    assert side_a is None
    assert base is None
    assert side_b is None


def test_parse_snapshot_conflict_unparseable():
    """Malformed markers (no section headers) return all None."""
    from fava_trails.vcs.jj_backend import JjBackend

    text = """\
<<<<<<< Conflict 1 of 1
Some content without section headers
>>>>>>> Conflict 1 of 1
"""
    side_a, base, side_b = JjBackend.parse_snapshot_conflict(text)
    assert side_a is None
    assert base is None
    assert side_b is None


# --- Push bookmark advancement ---


@pytest.mark.asyncio
async def test_push_advances_bookmark_before_git_push(jj_backend):
    """push() must advance the main bookmark to @- before calling _git_push().

    This prevents the silent auto-push failure where JJ colocated mode keeps
    HEAD detached, so the main bookmark never advances past the bootstrap commit.
    """
    calls = []

    original_run = jj_backend._run

    async def tracking_run(*args, **kwargs):
        calls.append(args)
        return await original_run(*args, **kwargs)

    with patch.object(jj_backend, "_run", side_effect=tracking_run):
        # push() will fail at git push (no remote), but we only care about call order
        try:
            await jj_backend.push()
        except Exception:
            pass  # Expected: no remote configured in test

    # Find the bookmark set and git push calls
    bookmark_idx = None
    push_idx = None
    for i, c in enumerate(calls):
        if c[0] == "bookmark" and "set" in c:
            bookmark_idx = i
        if c[0] == "git" and "push" in c:
            push_idx = i

    assert bookmark_idx is not None, "push() did not call 'bookmark set'"
    assert push_idx is not None, "push() did not call 'git push'"
    assert bookmark_idx < push_idx, (
        f"bookmark set (call {bookmark_idx}) must come before git push (call {push_idx})"
    )


@pytest.mark.asyncio
async def test_push_uses_default_bookmark_constant(jj_backend):
    """push() should use DEFAULT_BOOKMARK, not a hardcoded string."""
    from fava_trails.vcs.jj_backend import JjBackend

    calls = []
    original_run = jj_backend._run

    async def tracking_run(*args, **kwargs):
        calls.append(args)
        return await original_run(*args, **kwargs)

    with patch.object(jj_backend, "_run", side_effect=tracking_run):
        try:
            await jj_backend.push()
        except Exception:
            pass

    bookmark_calls = [c for c in calls if c[0] == "bookmark" and "set" in c]
    assert len(bookmark_calls) == 1
    assert JjBackend.DEFAULT_BOOKMARK in bookmark_calls[0]


@pytest.mark.asyncio
async def test_push_uses_bookmark_flag_not_all(jj_backend):
    """push() must use -b <bookmark> instead of --all to avoid pushing stale changes."""
    from fava_trails.vcs.jj_backend import JjBackend

    calls = []
    original_run = jj_backend._run

    async def tracking_run(*args, **kwargs):
        calls.append(args)
        return await original_run(*args, **kwargs)

    with patch.object(jj_backend, "_run", side_effect=tracking_run):
        try:
            await jj_backend.push()
        except Exception:
            pass

    push_calls = [c for c in calls if c[0] == "git" and "push" in c]
    assert len(push_calls) == 1
    push_args = push_calls[0]
    assert "-b" in push_args, f"Expected -b flag in push args: {push_args}"
    assert JjBackend.DEFAULT_BOOKMARK in push_args, (
        f"Expected bookmark '{JjBackend.DEFAULT_BOOKMARK}' in push args: {push_args}"
    )
    assert "--all" not in push_args, f"--all should not be used: {push_args}"


# --- TICK 1b-002: Phantom empty commit prevention ---


@pytest.mark.asyncio
async def test_commit_files_empty_message_still_describes(jj_backend):
    """commit_files with empty message must still describe the commit (prevents push blockage)."""
    test_file = jj_backend.trail_path / "empty-msg.md"
    test_file.write_text("# Empty message test")
    change = await jj_backend.commit_files("", [str(test_file)])
    assert change.description == "(auto-commit)"

    # Verify the committed change has a description in jj log
    changes = await jj_backend.log(limit=5)
    descriptions = [c.description for c in changes]
    assert any("(auto-commit)" in d for d in descriptions)


@pytest.mark.asyncio
async def test_new_change_empty_description_still_describes(jj_backend):
    """new_change with empty description must still pass -m to jj new."""
    change = await jj_backend.new_change("")
    assert change is not None
    # The current working change should have a description
    current = await jj_backend.current_change()
    assert current is not None
    assert current.description == "(new change)"


@pytest.mark.asyncio
async def test_commit_files_always_creates_described_change(jj_backend):
    """After commit_files, the new working copy change (@) should have a description."""
    test_file = jj_backend.trail_path / "described.md"
    test_file.write_text("# Described change test")
    await jj_backend.commit_files("explicit message", [str(test_file)])

    # The new working copy (@) should have a description from jj new -m
    current = await jj_backend.current_change()
    assert current is not None
    assert current.description == "(new change)"


@pytest.mark.asyncio
async def test_whitespace_only_message_treated_as_empty(jj_backend):
    """Whitespace-only messages/descriptions are normalized to fallback strings."""
    # commit_files with whitespace-only message
    test_file = jj_backend.trail_path / "ws-test.md"
    test_file.write_text("# Whitespace test")
    change = await jj_backend.commit_files("   ", [str(test_file)])
    assert change.description == "(auto-commit)"

    # new_change with whitespace-only description
    new = await jj_backend.new_change("   ")
    current = await jj_backend.current_change()
    assert current is not None
    assert current.description == "(new change)"


# --- TICK 1b-003: Defense-in-depth against JJ push failures ---


@pytest.mark.asyncio
async def test_git_push_includes_allow_empty_description(jj_backend):
    """_git_push() must include --allow-empty-description in args."""
    calls = []
    original_run = jj_backend._run

    async def tracking_run(*args, **kwargs):
        calls.append(args)
        return await original_run(*args, **kwargs)

    with patch.object(jj_backend, "_run", side_effect=tracking_run):
        try:
            await jj_backend._git_push(bookmark="main")
        except Exception:
            pass  # Expected: no remote in test

    push_calls = [c for c in calls if c[0] == "git" and "push" in c]
    assert len(push_calls) == 1
    assert "--allow-empty-description" in push_calls[0]


@pytest.mark.asyncio
async def test_repair_undescribed_commits_finds_and_fixes(jj_backend):
    """_repair_undescribed_commits should find and describe empty-description commits."""
    # Create a commit with empty description by using raw jj commands
    subprocess.run(
        ["jj", "describe", "-m", ""],
        cwd=str(jj_backend.repo_root), capture_output=True,
    )
    subprocess.run(
        ["jj", "new", "-m", "after empty"],
        cwd=str(jj_backend.repo_root), capture_output=True,
    )
    # Set main bookmark to include the empty commit
    subprocess.run(
        ["jj", "bookmark", "set", "main", "-r", "@-"],
        cwd=str(jj_backend.repo_root), capture_output=True,
    )

    count = await jj_backend._repair_undescribed_commits()
    assert count >= 1

    # Verify the commit now has a description (exclude root which is always undescribed)
    stdout_out, _ = await jj_backend._run(
        "log", "--no-graph", "-r",
        'description(exact:"") & ancestors(main) & ~root()',
        "-T", 'change_id.short(12) ++ "\\n"',
        check=False,
    )
    remaining = [line.strip() for line in stdout_out.splitlines() if line.strip()]
    assert len(remaining) == 0, f"Expected 0 undescribed commits, found {len(remaining)}"


@pytest.mark.asyncio
async def test_repair_undescribed_commits_noop_when_clean(jj_backend):
    """_repair_undescribed_commits returns 0 on a repo with no empty-description commits."""
    # Ensure there's a described commit
    test_file = jj_backend.trail_path / "repair-noop.md"
    test_file.write_text("# Noop repair test")
    await jj_backend.commit_files("described commit", [str(test_file)])
    # Set main bookmark
    subprocess.run(
        ["jj", "bookmark", "set", "main", "-r", "@-"],
        cwd=str(jj_backend.repo_root), capture_output=True,
    )

    count = await jj_backend._repair_undescribed_commits()
    assert count == 0


@pytest.mark.asyncio
async def test_push_calls_repair_before_push(jj_backend):
    """push() must call _repair_undescribed_commits before _git_push."""
    calls = []
    original_run = jj_backend._run

    async def tracking_run(*args, **kwargs):
        calls.append(args)
        return await original_run(*args, **kwargs)

    with patch.object(jj_backend, "_run", side_effect=tracking_run):
        try:
            await jj_backend.push()
        except Exception:
            pass  # Expected: no remote in test

    # Find the repair log query and git push calls
    repair_idx = None
    push_idx = None
    for i, c in enumerate(calls):
        # The repair method uses a jj log with description(exact:"") revset
        if c[0] == "log" and any('description(exact:"")' in str(a) for a in c):
            repair_idx = i
        if c[0] == "git" and "push" in c:
            push_idx = i

    assert repair_idx is not None, "push() did not call _repair_undescribed_commits"
    assert push_idx is not None, "push() did not call _git_push"
    assert repair_idx < push_idx, (
        f"repair (call {repair_idx}) must come before git push (call {push_idx})"
    )


@pytest.mark.asyncio
async def test_init_monorepo_sets_default_description(tmp_path):
    """init_monorepo configures ui.default-description to prevent undescribed commits."""
    from fava_trails.vcs.jj_backend import JjBackend

    repo = tmp_path / "default-desc-repo"
    trail = repo / "trails" / "test"
    backend = JjBackend(repo_root=repo, trail_path=trail)
    await backend.init_monorepo()

    # Verify the config was set
    proc = subprocess.run(
        ["jj", "config", "get", "ui.default-description"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert proc.stdout.strip() == "(auto-described)"

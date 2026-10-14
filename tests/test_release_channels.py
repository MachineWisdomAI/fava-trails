"""Release-candidate channel: tag grammar, version policy, and workflow wiring."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text()


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


release_tag = _load("release_tag", "release-tag.py")


# --- tag grammar + metadata agreement --------------------------------------


@pytest.mark.parametrize(
    "tag,version,channel",
    [
        ("v0.8.4", "0.8.4", "stable"),
        ("v0.8.4rc1", "0.8.4rc1", "rc"),
        ("v1.10.0rc12", "1.10.0rc12", "rc"),
    ],
)
def test_allowed_tags(tag, version, channel):
    assert release_tag.classify(tag, version) == channel


@pytest.mark.parametrize(
    "tag",
    [
        "0.8.4",  # missing v
        "v0.8",
        "v0.8.4-rc.1",  # semver spelling is not PEP 440
        "v0.8.4rc0",
        "v0.8.4rc01",
        "v0.8.4a1",
        "v0.8.4b1",
        "v0.8.4.post1",
        "v0.8.4rc1.dev1",
        "v0.8.4+local",
        "v08.4.0",
        "v0.8.4rc",
        "v0.8.4 ",
    ],
)
def test_invalid_tags_rejected(tag):
    with pytest.raises(ValueError):
        release_tag.classify(tag, tag[1:])


@pytest.mark.parametrize(
    "tag,version",
    [
        ("v0.8.4", "0.8.4rc1"),  # stable tag must not publish RC metadata
        ("v0.8.4rc1", "0.8.4"),  # RC tag must not publish stable metadata
        ("v0.8.4rc2", "0.8.4rc1"),
        ("v0.8.5rc1", "0.8.4rc1"),
    ],
)
def test_tag_metadata_mismatch_rejected(tag, version):
    with pytest.raises(ValueError, match="does not match"):
        release_tag.classify(tag, version)


def test_cli_reports_channel(tmp_path):
    py = tmp_path / "pyproject.toml"
    py.write_text('[project]\nname = "x"\nversion = "0.8.4rc1"\n')
    script = str(ROOT / "scripts" / "release-tag.py")
    ok = subprocess.run([sys.executable, script, "v0.8.4rc1", str(py)], capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.strip() == "rc"
    bad = subprocess.run([sys.executable, script, "v0.8.4", str(py)], capture_output=True, text=True)
    assert bad.returncode == 1


def test_repo_version_agrees_with_a_valid_tag():
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert release_tag.classify(f"v{version}", version) in {"stable", "rc"}
    init = (ROOT / "src" / "fava_trails" / "__init__.py").read_text()
    assert f'"{version}"' in init


# --- workflow wiring --------------------------------------------------------


def test_workflow_accepts_rc_and_stable_grammar_only():
    m = re.search(r'\[\[ "\$TAG_INPUT" =~ (\^[^ ]+\$) \]\]', WORKFLOW)
    assert m, "tag grammar check missing"
    pattern = re.compile(m.group(1).replace("[0-9]", "[0-9]"))
    # bash ERE is compatible with these Python patterns for the constructs used.
    for good in ("v0.8.4", "v0.8.4rc1", "v10.0.0rc10"):
        assert pattern.fullmatch(good), good
    for bad in ("v0.8.4rc0", "v0.8.4-rc.1", "v0.8.4a1", "0.8.4rc1", "v0.8.4rc1x", "v00.8.4"):
        assert not pattern.fullmatch(bad), bad


def test_workflow_keeps_existing_protections():
    assert "environment: fava-release" in WORKFLOW
    assert "id-token: write" in WORKFLOW
    assert "attestations: true" in WORKFLOW
    assert "skip-existing: true" in WORKFLOW
    triggers = WORKFLOW.split("\non:\n")[1].split("\npermissions:")[0]
    assert "workflow_dispatch" in triggers and "release:" not in triggers
    assert "candidate-SHA256SUMS" in WORKFLOW
    assert "tests/test_packaged_mcp.py" in WORKFLOW
    assert "Refusing split-state republish" in WORKFLOW
    assert "Existing immutable tag" in WORKFLOW


def test_workflow_binds_channel_to_github_release_flags():
    assert "scripts/release-tag.py" in WORKFLOW
    assert 'stable) RELEASE_FLAGS="--latest"' in WORKFLOW
    assert 'rc) RELEASE_FLAGS="--prerelease --latest=false"' in WORKFLOW
    # Every create/edit of the Release carries the channel flags, including undraft.
    assert WORKFLOW.count("${RELEASE_FLAGS}") >= 3
    undraft = WORKFLOW.split("--draft=false")[1][:80]
    assert "RELEASE_FLAGS" in undraft
    assert "CANDIDATE_CHANNEL" in WORKFLOW


def test_workflow_never_bumps_or_rebuilds_versions():
    assert "mw-version" not in WORKFLOW
    assert "sed -i" not in WORKFLOW
    assert WORKFLOW.count("uv build") == 1


# --- local version policy: first RC entry -----------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _make_repo(tmp_path: Path, version: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "mw-version.py", repo / "scripts" / "mw-version.py")
    (repo / ".version-policy.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "units": [
                    {
                        "name": "repo",
                        "paths": ["**"],
                        "files": [{"path": "pyproject.toml", "kind": "toml", "format": "pep440"}],
                    }
                ],
            }
        )
    )
    (repo / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n')
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        _git(repo, "config", k, v)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "change.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "chore: change")
    return repo


def _run(repo: Path, command: str, title: str, body: str = ""):
    body_file = repo.parent / "body.txt"  # outside the repo: untracked files count as changes
    body_file.write_text(body)
    return subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "mw-version.py"),
            command,
            "--repo",
            str(repo),
            "--base",
            "refs/remotes/origin/main",
            "--title",
            title,
            "--body-file",
            str(body_file),
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "GITHUB_EVENT_PATH": ""},
    )


def _version(repo: Path) -> str:
    return re.search(r'^version = "([^"]+)"', (repo / "pyproject.toml").read_text(), re.M).group(1)


MARKER = "Enters the rc channel.\n\nRelease-Channel: rc\n"


def test_stable_baseline_without_marker_stays_stable(tmp_path):
    repo = _make_repo(tmp_path, "0.8.3")
    r = _run(repo, "update", "chore: x")
    assert r.returncode == 0, r.stderr
    assert _version(repo) == "0.8.4"


def test_marker_starts_rc_channel_with_one_largest_increment(tmp_path):
    repo = _make_repo(tmp_path, "0.8.3")
    r = _run(repo, "update", "chore(release): support rc", MARKER)
    assert r.returncode == 0, r.stderr
    assert _version(repo) == "0.8.4rc1"
    assert _run(repo, "check", "chore(release): support rc", MARKER).returncode == 0
    # Re-running does not accumulate.
    _run(repo, "update", "chore(release): support rc", MARKER)
    assert _version(repo) == "0.8.4rc1"


def test_marker_with_feature_is_minor_rc(tmp_path):
    repo = _make_repo(tmp_path, "0.8.3")
    r = _run(repo, "update", "feat: new thing", MARKER)
    assert r.returncode == 0, r.stderr
    assert _version(repo) == "0.9.0rc1"


def test_check_rejects_stable_when_marker_requires_rc(tmp_path):
    repo = _make_repo(tmp_path, "0.8.3")
    _run(repo, "update", "chore: x")  # 0.8.4
    r = _run(repo, "check", "chore: x", MARKER)
    assert r.returncode == 1 and "0.8.4rc1" in r.stderr


def test_marker_rejected_on_existing_prerelease_baseline(tmp_path):
    repo = _make_repo(tmp_path, "0.8.4rc1")
    r = _run(repo, "update", "chore: x", MARKER)
    assert r.returncode == 1 and "stable baseline" in r.stderr


def test_prerelease_channel_retained_and_counter_reset(tmp_path):
    repo = _make_repo(tmp_path, "0.8.4rc3")
    r = _run(repo, "update", "chore: x")
    assert r.returncode == 0, r.stderr
    assert _version(repo) == "0.8.5rc1"


def test_marker_must_be_exact_line(tmp_path):
    repo = _make_repo(tmp_path, "0.8.3")
    for body in ("Release-Channel: rc2\n", "release-channel: rc\n", "see Release-Channel: rc here\n"):
        _run(repo, "update", "chore: x", body)
        assert _version(repo) == "0.8.4", body
        _git(repo, "checkout", "--", "pyproject.toml")


def test_promotion_still_suffix_only(tmp_path):
    repo = _make_repo(tmp_path, "0.8.4rc2")
    # Promotion edits only configured version values, no base increment.
    (repo / "change.txt").unlink()
    _git(repo, "commit", "-qam", "chore: revert change")
    r = _run(repo, "update", "chore(release): promote version", MARKER)
    assert r.returncode == 0, r.stderr
    assert _version(repo) == "0.8.4"


def test_promotion_of_stable_baseline_rejected(tmp_path):
    repo = _make_repo(tmp_path, "0.8.4")
    (repo / "change.txt").unlink()
    _git(repo, "commit", "-qam", "chore: revert change")
    r = _run(repo, "update", "chore(release): promote version")
    assert r.returncode == 1

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


# --- local version policy: same-base release candidate (metadata only) --------

SAME_BASE = "Prepares the candidate for the existing base.\n\nRelease-Channel: rc-same-base\n"
SAME_BASE_TITLE = "chore(release): prepare same-base release candidate"


def _make_candidate_repo(tmp_path: Path, version: str = "0.9.3") -> Path:
    """A stable-baseline repo whose branch head still equals the base commit."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "tests").mkdir()
    shutil.copy(ROOT / "scripts" / "mw-version.py", repo / "scripts" / "mw-version.py")
    (repo / ".version-policy.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "units": [
                    {
                        "name": "repo",
                        "paths": ["**"],
                        "files": [
                            {"path": "pyproject.toml", "kind": "toml", "format": "pep440"},
                            {
                                "path": "uv.lock",
                                "kind": "uv-lock",
                                "format": "pep440",
                                "name": "x",
                            },
                            {
                                "path": "src/pkg/__init__.py",
                                "kind": "python",
                                "format": "pep440",
                            },
                        ],
                    }
                ],
                "release_paths": ["src/pkg/**"],
            }
        )
    )
    (repo / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n')
    (repo / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "x"\nversion = "{version}"\nsource = {{ editable = "." }}\n\n'
        '[[package]]\nname = "dep"\nversion = "1.0.0"\n'
    )
    (repo / "src" / "pkg" / "__init__.py").write_text(f'__version__ = "{version}"\nVALUE = 1\n')
    (repo / "src" / "pkg" / "core.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        _git(repo, "config", k, v)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _mirror_versions(repo: Path) -> set[str]:
    values = set()
    values.add(re.search(r'^version = "([^"]+)"', (repo / "pyproject.toml").read_text(), re.M).group(1))
    values.add(re.search(r'name = "x"\nversion = "([^"]+)"', (repo / "uv.lock").read_text()).group(1))
    values.add(re.search(r'__version__ = "([^"]+)"', (repo / "src/pkg/__init__.py").read_text()).group(1))
    return values


def test_same_base_marker_keeps_base_and_adds_rc_suffix(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    r = _run(repo, "update", SAME_BASE_TITLE, SAME_BASE)
    assert r.returncode == 0, r.stderr
    assert "0.9.3 -> 0.9.3-rc.1" in r.stdout
    # Every synchronized mirror carries the one PEP 440 value; the dependency is untouched.
    assert _mirror_versions(repo) == {"0.9.3rc1"}
    assert 'name = "dep"\nversion = "1.0.0"' in (repo / "uv.lock").read_text()
    assert _run(repo, "check", SAME_BASE_TITLE, SAME_BASE).returncode == 0
    # Re-running does not accumulate and never reaches 0.9.4.
    _run(repo, "update", SAME_BASE_TITLE, SAME_BASE)
    assert _mirror_versions(repo) == {"0.9.3rc1"}


def test_same_base_marker_changes_only_version_values(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    assert _run(repo, "update", SAME_BASE_TITLE, SAME_BASE).returncode == 0
    changed = set(_git(repo, "diff", "--name-only").splitlines())
    assert changed == {"pyproject.toml", "uv.lock", "src/pkg/__init__.py"}
    # Every non-version byte equals the base: stripping the version leaves no diff.
    diff = _git(repo, "diff", "-U0").splitlines()
    removed = [ln for ln in diff if ln.startswith("-") and not ln.startswith("---")]
    added = [ln for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    assert len(removed) == len(added) == 3
    assert all("0.9.3" in ln for ln in removed) and all("0.9.3rc1" in ln for ln in added)


@pytest.mark.parametrize(
    "path,content",
    [
        ("src/pkg/core.py", "VALUE = 2\n"),  # product source
        ("src/pkg/new.py", "VALUE = 3\n"),  # new shipped file
        ("change.txt", "x\n"),  # unlisted root file counts as product
        ("src/pkg/__init__.py", '__version__ = "0.9.3"\nVALUE = 2\n'),  # mirror edited beyond its version
    ],
)
def test_same_base_rejects_any_product_change(tmp_path, path, content):
    repo = _make_candidate_repo(tmp_path)
    (repo / path).write_text(content)
    for command in ("update", "check"):
        r = _run(repo, command, SAME_BASE_TITLE, SAME_BASE)
        assert r.returncode == 1, (command, r.stdout)
        assert "version values only" in r.stderr and path in r.stderr
    assert "rc1" not in (repo / "pyproject.toml").read_text()  # update wrote nothing


def test_same_base_rejects_product_change_committed_on_the_branch(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    (repo / "src" / "pkg" / "core.py").write_text("VALUE = 2\n")
    _git(repo, "commit", "-qam", "fix: change behavior")
    r = _run(repo, "update", SAME_BASE_TITLE, SAME_BASE)
    assert r.returncode == 1 and "version values only" in r.stderr


def test_same_base_allows_non_release_paths(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    (repo / "docs" / "note.md").write_text("candidate evidence\n")
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    pass\n")
    (repo / "scripts" / "check-something.py").write_text("print('ok')\n")
    r = _run(repo, "update", SAME_BASE_TITLE, SAME_BASE)
    assert r.returncode == 0, r.stderr
    assert _mirror_versions(repo) == {"0.9.3rc1"}
    assert _run(repo, "check", SAME_BASE_TITLE, SAME_BASE).returncode == 0


def test_same_base_check_rejects_unprepared_and_wrong_versions(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    r = _run(repo, "check", SAME_BASE_TITLE, SAME_BASE)  # still stable 0.9.3
    assert r.returncode == 1 and "expected 0.9.3rc1" in r.stderr
    for wrong in ("0.9.4rc1", "0.9.3rc2", "0.9.4"):
        _git(repo, "checkout", "--", ".")
        (repo / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{wrong}"\n')
        r = _run(repo, "check", SAME_BASE_TITLE, SAME_BASE)
        assert r.returncode == 1 and "expected 0.9.3rc1" in r.stderr, wrong


def test_version_only_rc_edit_without_marker_still_rejected(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.9.3rc1"\n')
    r = _run(repo, "check", "chore: relabel", "")
    assert r.returncode == 1 and "expected 0.9.3" in r.stderr


def test_same_base_rejected_on_prerelease_baseline(tmp_path):
    repo = _make_candidate_repo(tmp_path, "0.9.3rc1")
    r = _run(repo, "update", SAME_BASE_TITLE, SAME_BASE)
    assert r.returncode == 1 and "stable baseline" in r.stderr


def test_same_base_and_start_rc_markers_are_mutually_exclusive(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    r = _run(repo, "update", SAME_BASE_TITLE, SAME_BASE + "Release-Channel: rc\n")
    assert r.returncode == 1 and "mutually exclusive" in r.stderr


def test_same_base_marker_must_be_exact_line(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    for body in (
        "Release-Channel: rc-same-base2\n",
        "release-channel: rc-same-base\n",
        "see Release-Channel: rc-same-base here\n",
        "Release-Channel: rc-same\n",
    ):
        _run(repo, "update", "chore: x", body)
        assert _mirror_versions(repo) == {"0.9.3"}, body
        _git(repo, "checkout", "--", ".")


def test_same_base_not_honored_for_promotion_title(tmp_path):
    repo = _make_candidate_repo(tmp_path, "0.9.3rc1")
    r = _run(repo, "update", "chore(release): promote version", SAME_BASE)
    assert r.returncode == 0, r.stderr
    assert _mirror_versions(repo) == {"0.9.3"}


def test_candidate_then_promotion_and_next_change_keep_normal_semantics(tmp_path):
    repo = _make_candidate_repo(tmp_path)
    assert _run(repo, "update", SAME_BASE_TITLE, SAME_BASE).returncode == 0
    _git(repo, "commit", "-qam", SAME_BASE_TITLE)
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    # Promotion removes only the suffix: 0.9.3rc1 -> 0.9.3, no base increment.
    assert _run(repo, "update", "chore(release): promote version").returncode == 0
    assert _mirror_versions(repo) == {"0.9.3"}
    _git(repo, "checkout", "--", ".")
    # A later product change advances the prerelease base and resets the counter.
    (repo / "src" / "pkg" / "core.py").write_text("VALUE = 2\n")
    assert _run(repo, "update", "fix: later change").returncode == 0
    assert _mirror_versions(repo) == {"0.9.4rc1"}


# --- candidate wheel/sdist identity against the base ---------------------------

identity = _load("rc_identity", "check-rc-artifact-identity.py")


def _write_artifacts(
    directory: Path, version: str, *, init: str | None = None, extra: dict[str, str] | None = None,
    sdist_extra: dict[str, str] | None = None,
) -> None:
    import io
    import tarfile
    import zipfile

    directory.mkdir(parents=True, exist_ok=True)
    stem = f"fava_trails-{version}"
    init = init if init is not None else f'__version__ = "{version}"\n'
    files = {
        "fava_trails/__init__.py": init,
        "fava_trails/core.py": "VALUE = 1\n",
        f"{stem}.dist-info/METADATA": f"Metadata-Version: 2.4\nName: fava-trails\nVersion: {version}\n",
        f"{stem}.dist-info/RECORD": f"fava_trails/__init__.py,sha256={version},1\n",
        **(extra or {}),
    }
    with zipfile.ZipFile(directory / f"{stem}-py3-none-any.whl", "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    sdist_files = {
        f"{stem}/PKG-INFO": f"Metadata-Version: 2.4\nName: fava-trails\nVersion: {version}\n",
        f"{stem}/pyproject.toml": f'[project]\nname = "fava-trails"\nversion = "{version}"\n',
        f"{stem}/src/fava_trails/core.py": "VALUE = 1\n",
        **(sdist_extra or {}),
    }
    with tarfile.open(directory / f"{stem}.tar.gz", "w:gz") as tf:
        for name, content in sdist_files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_identity_accepts_a_version_only_candidate(tmp_path):
    _write_artifacts(tmp_path / "base", "0.9.3")
    _write_artifacts(tmp_path / "cand", "0.9.3rc1")
    assert identity.compare_artifacts(tmp_path / "base", tmp_path / "cand", "0.9.3", "0.9.3rc1") == []


def test_identity_rejects_a_changed_product_byte_in_the_wheel(tmp_path):
    _write_artifacts(tmp_path / "base", "0.9.3")
    _write_artifacts(tmp_path / "cand", "0.9.3rc1", extra={"fava_trails/core.py": "VALUE = 2\n"})
    problems = identity.compare_artifacts(tmp_path / "base", tmp_path / "cand", "0.9.3", "0.9.3rc1")
    assert problems == ["wheel: non-version bytes differ: fava_trails/core.py"]


def test_identity_rejects_a_changed_line_next_to_the_version(tmp_path):
    _write_artifacts(tmp_path / "base", "0.9.3")
    _write_artifacts(tmp_path / "cand", "0.9.3rc1", init='__version__ = "0.9.3rc1"\nVALUE = 2\n')
    problems = identity.compare_artifacts(tmp_path / "base", tmp_path / "cand", "0.9.3", "0.9.3rc1")
    assert problems == ["wheel: non-version bytes differ: fava_trails/__init__.py"]


def test_identity_rejects_added_or_removed_files_and_sdist_changes(tmp_path):
    _write_artifacts(tmp_path / "base", "0.9.3", sdist_extra={"fava_trails-0.9.3/CHANGELOG.md": "a\n"})
    _write_artifacts(
        tmp_path / "cand",
        "0.9.3rc1",
        extra={"fava_trails/new.py": "x = 1\n"},
        sdist_extra={"fava_trails-0.9.3rc1/CHANGELOG.md": "b\n"},
    )
    problems = identity.compare_artifacts(tmp_path / "base", tmp_path / "cand", "0.9.3", "0.9.3rc1")
    assert "wheel: unexpected in candidate: fava_trails/new.py" in problems
    assert "sdist: non-version bytes differ: fava_trails-0.9.3/CHANGELOG.md" in problems


def test_identity_rejects_a_candidate_without_version_change(tmp_path):
    _write_artifacts(tmp_path / "base", "0.9.3")
    _write_artifacts(tmp_path / "cand", "0.9.3")
    assert identity.compare_artifacts(tmp_path / "base", tmp_path / "cand", "0.9.3", "0.9.3") == [
        "candidate version equals base version 0.9.3"
    ]


def test_identity_rejects_wrong_artifact_name(tmp_path):
    _write_artifacts(tmp_path / "base", "0.9.3")
    _write_artifacts(tmp_path / "cand", "0.9.3rc2")
    problems = identity.compare_artifacts(tmp_path / "base", tmp_path / "cand", "0.9.3", "0.9.3rc1")
    assert any("does not carry version 0.9.3rc1" in p for p in problems)

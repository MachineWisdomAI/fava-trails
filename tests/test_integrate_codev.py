"""Tests for `fava-trails integrate codev` CLI command (Spec 26)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from fava_trails.cli import _compose_codev_prompt, _strip_provenance_header, cmd_integrate_codev


def _make_args(**kwargs):
    from argparse import Namespace
    defaults = {"check": False, "diff": False, "force": False}
    defaults.update(kwargs)
    return Namespace(**defaults)


@pytest.fixture
def data_repo(tmp_path):
    """Set up a minimal data repo with trails/ and generic trust-gate-prompt.md."""
    repo = tmp_path / "data-repo"
    trails = repo / "trails"
    trails.mkdir(parents=True)
    (repo / "config.yaml").write_text("trails_dir: trails\n")
    (trails / "trust-gate-prompt.md").write_text("You are a quality gate.\n")
    os.environ["FAVA_TRAILS_DATA_REPO"] = str(repo)
    yield repo
    os.environ.pop("FAVA_TRAILS_DATA_REPO", None)


# --- Deterministic composition ---


def test_compose_produces_deterministic_output():
    """Composing the same inputs always produces identical output."""
    generic = "You are a quality gate.\n"
    addendum = "## Codev Checks\nCheck specs.\n"
    result1 = _compose_codev_prompt(generic, addendum, "0.5.4")
    result2 = _compose_codev_prompt(generic, addendum, "0.5.4")
    assert result1 == result2


def test_compose_includes_provenance_header():
    """Composed output includes provenance header with hash and version."""
    generic = "Generic prompt content"
    addendum = "Addendum content"
    result = _compose_codev_prompt(generic, addendum, "1.0.0")

    assert result.startswith("<!-- Composed by: fava-trails integrate codev v1.0.0 -->")
    assert "Generic prompt hash:" in result
    assert "Addendum version: 1" in result
    assert "Generic prompt content" in result
    assert "Addendum content" in result


def test_compose_includes_both_parts():
    """Composed output contains both generic prompt and addendum."""
    generic = "GENERIC_MARKER"
    addendum = "ADDENDUM_MARKER"
    result = _compose_codev_prompt(generic, addendum, "0.1.0")
    assert "GENERIC_MARKER" in result
    assert "ADDENDUM_MARKER" in result


# --- integrate codev (default write mode) ---


def test_integrate_codev_writes_composed_file(data_repo):
    """integrate codev creates trails/codev-artifacts/trust-gate-prompt.md."""
    args = _make_args()
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(args)

    assert rc == 0
    output = data_repo / "trails" / "codev-artifacts" / "trust-gate-prompt.md"
    assert output.exists()
    content = output.read_text()
    assert "<!-- Composed by: fava-trails integrate codev" in content
    assert "quality gate" in content.lower()
    assert "Codev Artifact Validation" in content


# --- Idempotency ---


def test_integrate_codev_idempotent(data_repo):
    """Running integrate codev twice produces identical bytes."""
    args = _make_args()
    output = data_repo / "trails" / "codev-artifacts" / "trust-gate-prompt.md"

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc1 = cmd_integrate_codev(args)
            content1 = output.read_text()
            rc2 = cmd_integrate_codev(args)
            content2 = output.read_text()

    assert rc1 == 0
    assert rc2 == 0
    assert content1 == content2


# --- --check detects staleness ---


def test_check_ignores_version_in_header(data_repo):
    """--check should not false-positive when only the package version changes."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            # Write with version "0.5.3"
            cmd_integrate_codev(_make_args())

    # Now re-compose with a different version and verify --check still passes
    # (content is the same, only the header version line differs)
    output = data_repo / "trails" / "codev-artifacts" / "trust-gate-prompt.md"
    existing = output.read_text(encoding="utf-8")
    # Replace version in header to simulate a package upgrade
    patched = existing.replace(
        "<!-- Composed by: fava-trails integrate codev v",
        "<!-- Composed by: fava-trails integrate codev v999.",
        1,
    )
    output.write_text(patched, encoding="utf-8")

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args(check=True))

    assert rc == 0  # should pass — content is identical


def test_strip_provenance_header():
    """_strip_provenance_header removes header lines, keeps content."""
    composed = _compose_codev_prompt("generic", "addendum", "1.0.0")
    stripped = _strip_provenance_header(composed)
    assert "<!-- Composed by:" not in stripped
    assert "generic" in stripped
    assert "addendum" in stripped


def test_strip_provenance_header_no_header():
    """_strip_provenance_header returns text unchanged if no header present."""
    text = "No header here."
    assert _strip_provenance_header(text) == text


def test_check_passes_when_up_to_date(data_repo):
    """--check returns 0 when composed file matches current sources."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            # First write
            cmd_integrate_codev(_make_args())
            # Then check
            rc = cmd_integrate_codev(_make_args(check=True))

    assert rc == 0


def test_check_fails_when_stale(data_repo):
    """--check returns 1 when generic prompt changed since last compose."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            # First write
            cmd_integrate_codev(_make_args())
            # Modify generic prompt
            (data_repo / "trails" / "trust-gate-prompt.md").write_text("Updated generic prompt.\n")
            # Check should fail
            rc = cmd_integrate_codev(_make_args(check=True))

    assert rc == 1


def test_check_fails_when_no_composed_file(data_repo):
    """--check returns 1 when composed file doesn't exist."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args(check=True))

    assert rc == 1


# --- --diff mode ---


def test_diff_shows_changes(data_repo, capsys):
    """--diff previews changes without writing."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args(diff=True))

    assert rc == 0
    output = data_repo / "trails" / "codev-artifacts" / "trust-gate-prompt.md"
    assert not output.exists()  # diff mode should not write
    captured = capsys.readouterr()
    assert "+" in captured.out  # diff lines


# --- --force overwrites manual edits ---


def test_force_overwrites_manual_edit(data_repo):
    """--force overwrites a manually edited composed file."""
    output_dir = data_repo / "trails" / "codev-artifacts"
    output_dir.mkdir(parents=True)
    output = output_dir / "trust-gate-prompt.md"
    output.write_text("Manually written content with no provenance header.\n")

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args(force=True))

    assert rc == 0
    assert "<!-- Composed by:" in output.read_text()


def test_refuses_overwrite_without_force(data_repo):
    """Default mode refuses to overwrite a manually edited composed file."""
    output_dir = data_repo / "trails" / "codev-artifacts"
    output_dir.mkdir(parents=True)
    output = output_dir / "trust-gate-prompt.md"
    output.write_text("Manually written content.\n")

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args())

    assert rc == 1


# --- Error cases ---


def test_missing_generic_prompt(data_repo):
    """Error when generic trust-gate-prompt.md doesn't exist."""
    (data_repo / "trails" / "trust-gate-prompt.md").unlink()

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args())

    assert rc == 1


def test_missing_addendum_from_package(data_repo):
    """Error when addendum resource cannot be read from the package."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            with patch("fava_trails.cli.importlib_resources") as mock_res:
                mock_res.files.return_value.__truediv__ = lambda *a: mock_res.files.return_value
                mock_res.files.return_value.read_text.side_effect = FileNotFoundError("not found")
                rc = cmd_integrate_codev(_make_args())

    assert rc == 1


def test_force_rejected_with_check(data_repo):
    """--force --check is rejected."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args(force=True, check=True))

    assert rc == 1


def test_force_rejected_with_diff(data_repo):
    """--force --diff is rejected."""
    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("fava_trails.cli.get_trails_dir", return_value=data_repo / "trails"):
            rc = cmd_integrate_codev(_make_args(force=True, diff=True))

    assert rc == 1

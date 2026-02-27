"""Tests for the FAVA Trails CLI (fava-trails)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fava_trails.cli import (
    _is_env_gitignored,
    _read_env_value,
    _read_project_yaml_scope,
    _update_env_file,
    _write_project_yaml,
    build_parser,
    cmd_bootstrap,
    cmd_doctor,
    cmd_init,
    cmd_install_jj,
    cmd_scope,
    cmd_scope_list,
    cmd_scope_set,
)


# ─── _update_env_file ─────────────────────────────────────────────────────────


def test_update_env_file_creates_new(tmp_path):
    env = tmp_path / ".env"
    _update_env_file(env, "FAVA_TRAILS_SCOPE", "mw/eng/test")
    assert env.read_text() == "FAVA_TRAILS_SCOPE=mw/eng/test\n"


def test_update_env_file_appends_to_existing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER_VAR=foo\n")
    _update_env_file(env, "FAVA_TRAILS_SCOPE", "mw/eng/test")
    assert "OTHER_VAR=foo\n" in env.read_text()
    assert "FAVA_TRAILS_SCOPE=mw/eng/test\n" in env.read_text()


def test_update_env_file_updates_existing_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FAVA_TRAILS_SCOPE=old-scope\n")
    _update_env_file(env, "FAVA_TRAILS_SCOPE", "new-scope")
    text = env.read_text()
    assert "FAVA_TRAILS_SCOPE=new-scope\n" in text
    assert "old-scope" not in text


def test_update_env_file_deduplicates(tmp_path):
    """Duplicate keys are collapsed to a single entry."""
    env = tmp_path / ".env"
    env.write_text("FAVA_TRAILS_SCOPE=first\nFAVA_TRAILS_SCOPE=second\n")
    _update_env_file(env, "FAVA_TRAILS_SCOPE", "final")
    text = env.read_text()
    assert text.count("FAVA_TRAILS_SCOPE=") == 1
    assert "FAVA_TRAILS_SCOPE=final\n" in text


def test_update_env_file_preserves_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# This is a comment\nOTHER=bar\n")
    _update_env_file(env, "FAVA_TRAILS_SCOPE", "mw/test")
    text = env.read_text()
    assert "# This is a comment\n" in text
    assert "OTHER=bar\n" in text
    assert "FAVA_TRAILS_SCOPE=mw/test\n" in text


def test_read_env_value_present(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FAVA_TRAILS_SCOPE=mw/eng/test\n")
    assert _read_env_value(env, "FAVA_TRAILS_SCOPE") == "mw/eng/test"


def test_read_env_value_absent(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=foo\n")
    assert _read_env_value(env, "FAVA_TRAILS_SCOPE") is None


def test_read_env_value_missing_file(tmp_path):
    env = tmp_path / ".env"
    assert _read_env_value(env, "FAVA_TRAILS_SCOPE") is None


# ─── _is_env_gitignored ───────────────────────────────────────────────────────


def test_is_env_gitignored_true(tmp_path):
    (tmp_path / ".gitignore").write_text(".env\n")
    assert _is_env_gitignored(tmp_path) is True


def test_is_env_gitignored_false_no_file(tmp_path):
    assert _is_env_gitignored(tmp_path) is False


def test_is_env_gitignored_false_not_listed(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    assert _is_env_gitignored(tmp_path) is False


# ─── cmd_init ─────────────────────────────────────────────────────────────────


def _make_args(**kwargs):
    """Build a minimal argparse.Namespace for testing."""
    from argparse import Namespace
    return Namespace(**kwargs)


def test_init_with_existing_yaml_no_env(tmp_path, monkeypatch):
    """init reads scope from .fava-trails.yaml and writes .env."""
    monkeypatch.chdir(tmp_path)
    _write_project_yaml(tmp_path, "mw/eng/test")
    # Patch get_data_repo_root to avoid real filesystem dependency
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        rc = cmd_init(_make_args(scope=None))
    assert rc == 0
    assert _read_env_value(tmp_path / ".env", "FAVA_TRAILS_SCOPE") == "mw/eng/test"


def test_init_with_yaml_and_env_no_scope(tmp_path, monkeypatch):
    """init appends scope to .env when .env exists but lacks FAVA_TRAILS_SCOPE."""
    monkeypatch.chdir(tmp_path)
    _write_project_yaml(tmp_path, "mw/eng/proj")
    (tmp_path / ".env").write_text("OTHER=foo\n")
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        rc = cmd_init(_make_args(scope=None))
    assert rc == 0
    text = (tmp_path / ".env").read_text()
    assert "OTHER=foo" in text
    assert "FAVA_TRAILS_SCOPE=mw/eng/proj" in text


def test_init_env_already_has_scope(tmp_path, monkeypatch, capsys):
    """init is a no-op when .env already has FAVA_TRAILS_SCOPE."""
    monkeypatch.chdir(tmp_path)
    _write_project_yaml(tmp_path, "mw/eng/proj")
    (tmp_path / ".env").write_text("FAVA_TRAILS_SCOPE=mw/eng/proj\n")
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        rc = cmd_init(_make_args(scope=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "already set" in out


def test_init_noninteractive_scope_flag(tmp_path, monkeypatch):
    """init --scope creates both files without prompting."""
    monkeypatch.chdir(tmp_path)
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        rc = cmd_init(_make_args(scope="mw/eng/ci-test"))
    assert rc == 0
    assert _read_project_yaml_scope(tmp_path) == "mw/eng/ci-test"
    assert _read_env_value(tmp_path / ".env", "FAVA_TRAILS_SCOPE") == "mw/eng/ci-test"


def test_init_neither_file_interactive(tmp_path, monkeypatch):
    """init prompts for scope when neither .fava-trails.yaml nor .env exists."""
    monkeypatch.chdir(tmp_path)
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        with patch("builtins.input", return_value="mw/eng/interactive"):
            rc = cmd_init(_make_args(scope=None))
    assert rc == 0
    assert _read_project_yaml_scope(tmp_path) == "mw/eng/interactive"
    assert _read_env_value(tmp_path / ".env", "FAVA_TRAILS_SCOPE") == "mw/eng/interactive"


def test_init_gitignore_warning(tmp_path, monkeypatch, capsys):
    """init warns when .env is not in .gitignore."""
    monkeypatch.chdir(tmp_path)
    _write_project_yaml(tmp_path, "mw/test")
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        rc = cmd_init(_make_args(scope=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert ".gitignore" in out


def test_init_no_gitignore_warning_when_ignored(tmp_path, monkeypatch, capsys):
    """init does not warn when .env is already in .gitignore."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n")
    _write_project_yaml(tmp_path, "mw/test")
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        rc = cmd_init(_make_args(scope=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert ".gitignore" not in out


# ─── cmd_bootstrap ────────────────────────────────────────────────────────────


def _make_jj_mock(returncode=0):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = ""
    mock.stderr = ""
    return mock


def test_bootstrap_creates_structure(tmp_path):
    """bootstrap creates config.yaml, .gitignore, trails/, template files, and runs jj init."""
    target = tmp_path / "data-repo"
    args = _make_args(path=str(target), remote=None)

    with patch("shutil.which", return_value="/usr/bin/jj"):
        with patch("subprocess.run", return_value=_make_jj_mock(0)) as mock_run:
            rc = cmd_bootstrap(args)

    assert rc == 0
    assert (target / "config.yaml").exists()
    assert (target / ".gitignore").exists()
    assert (target / "trails").is_dir()

    # Template files copied
    assert (target / "README.md").exists()
    assert (target / "CLAUDE.md").exists()
    assert (target / "trails" / "trust-gate-prompt.md").exists()
    assert "FAVA Trails" in (target / "README.md").read_text()
    assert "quality gate" in (target / "trails" / "trust-gate-prompt.md").read_text().lower()

    import yaml as _yaml
    config = _yaml.safe_load((target / "config.yaml").read_text())
    assert config["trails_dir"] == "trails"
    assert config["push_strategy"] == "manual"
    assert config["remote_url"] is None


def test_bootstrap_with_remote(tmp_path):
    """bootstrap sets remote_url in config.yaml when --remote is provided."""
    target = tmp_path / "data-repo"
    args = _make_args(path=str(target), remote="https://github.com/org/repo.git")

    with patch("shutil.which", return_value="/usr/bin/jj"):
        with patch("subprocess.run", return_value=_make_jj_mock(0)):
            rc = cmd_bootstrap(args)

    assert rc == 0
    import yaml as _yaml
    config = _yaml.safe_load((target / "config.yaml").read_text())
    assert config["remote_url"] == "https://github.com/org/repo.git"


def test_bootstrap_fails_if_jj_missing(tmp_path):
    """bootstrap returns error when jj is not installed."""
    target = tmp_path / "data-repo"
    args = _make_args(path=str(target), remote=None)

    fallback = Path.home() / ".local" / "bin" / "jj"
    real_exists = Path.exists

    def exists_side_effect(self):
        if self == fallback:
            return False
        return real_exists(self)

    with patch("shutil.which", return_value=None):
        with patch.object(Path, "exists", exists_side_effect):
            rc = cmd_bootstrap(args)

    assert rc == 1


def test_bootstrap_fails_if_already_bootstrapped(tmp_path):
    """bootstrap returns error if .jj/ already exists."""
    target = tmp_path / "data-repo"
    target.mkdir()
    (target / ".jj").mkdir()
    args = _make_args(path=str(target), remote=None)

    with patch("shutil.which", return_value="/usr/bin/jj"):
        rc = cmd_bootstrap(args)

    assert rc == 1


# ─── cmd_scope ────────────────────────────────────────────────────────────────


def test_scope_shows_env_source(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FAVA_TRAILS_SCOPE=mw/eng/test\n")
    rc = cmd_scope(_make_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "mw/eng/test" in out
    assert ".env" in out


def test_scope_shows_yaml_source(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _write_project_yaml(tmp_path, "mw/eng/yaml-scope")
    rc = cmd_scope(_make_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "mw/eng/yaml-scope" in out
    assert ".fava-trails.yaml" in out


def test_scope_not_configured(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = cmd_scope(_make_args())
    assert rc == 1
    out = capsys.readouterr().out
    assert "not configured" in out


# ─── cmd_scope_set ────────────────────────────────────────────────────────────


def test_scope_set_updates_both_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cmd_scope_set(_make_args(scope_value="mw/eng/new-scope"))
    assert rc == 0
    assert _read_project_yaml_scope(tmp_path) == "mw/eng/new-scope"
    assert _read_env_value(tmp_path / ".env", "FAVA_TRAILS_SCOPE") == "mw/eng/new-scope"


def test_scope_set_prints_trust_gate_hint(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cmd_scope_set(_make_args(scope_value="mw/eng/proj"))
    out = capsys.readouterr().out
    assert "trust-gate-prompt.md" in out


def test_scope_set_invalid_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = cmd_scope_set(_make_args(scope_value="bad scope!"))
    assert rc == 1


# ─── cmd_scope_list ───────────────────────────────────────────────────────────


def test_scope_list_finds_scopes(tmp_path, capsys):
    """scope list finds scopes that have a thoughts/ directory."""
    trails_dir = tmp_path / "trails"
    (trails_dir / "mw/eng/proj" / "thoughts").mkdir(parents=True)
    (trails_dir / "mw/eng/other" / "thoughts").mkdir(parents=True)

    with patch("fava_trails.cli.get_trails_dir", return_value=trails_dir):
        rc = cmd_scope_list(_make_args())

    assert rc == 0
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert "mw/eng/other" in lines
    assert "mw/eng/proj" in lines
    assert lines == sorted(lines)  # sorted


def test_scope_list_empty(tmp_path, capsys):
    """scope list reports no scopes when trails/ is empty."""
    trails_dir = tmp_path / "trails"
    trails_dir.mkdir()

    with patch("fava_trails.cli.get_trails_dir", return_value=trails_dir):
        rc = cmd_scope_list(_make_args())

    assert rc == 0
    out = capsys.readouterr().out
    assert "No scopes" in out


# ─── .env idempotency ─────────────────────────────────────────────────────────


def test_env_write_idempotent(tmp_path, monkeypatch):
    """Running init twice produces the same .env content."""
    monkeypatch.chdir(tmp_path)
    _write_project_yaml(tmp_path, "mw/eng/idem")
    with patch("fava_trails.cli.get_data_repo_root") as mock_repo:
        mock_repo.return_value = tmp_path / "data"
        cmd_init(_make_args(scope=None))
        first_content = (tmp_path / ".env").read_text()
        cmd_init(_make_args(scope=None))
        second_content = (tmp_path / ".env").read_text()
    assert first_content == second_content


# ─── CLI entry point (smoke test) ─────────────────────────────────────────────


def test_cli_version():
    """fava-trails --version prints a version string."""
    result = subprocess.run(
        [sys.executable, "-m", "fava_trails.cli", "--version"],
        capture_output=True,
        text=True,
    )
    # --version exits with code 0 and prints to stdout
    assert result.returncode == 0
    assert "fava-trails" in result.stdout or "unknown" in result.stdout


def test_cli_help():
    """fava-trails --help exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "fava_trails.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "init" in result.stdout
    assert "bootstrap" in result.stdout
    assert "scope" in result.stdout


# ─── cmd_doctor ───────────────────────────────────────────────────────────────


def _make_valid_data_repo(tmp_path: Path) -> Path:
    """Create a minimal valid data repo structure."""
    data_repo = tmp_path / "data-repo"
    data_repo.mkdir()
    (data_repo / "config.yaml").write_text("trails_dir: trails\n")
    (data_repo / "trails").mkdir()
    return data_repo


def test_doctor_all_green(tmp_path, monkeypatch, capsys):
    """doctor exits 0 when JJ, data repo, and scope are all configured."""
    monkeypatch.chdir(tmp_path)
    data_repo = _make_valid_data_repo(tmp_path)
    (tmp_path / ".env").write_text(f"FAVA_TRAILS_SCOPE=mw/eng/test\n")

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("shutil.which", return_value="/usr/bin/jj"):
            with patch("subprocess.run", return_value=_make_jj_mock(0)) as mock_run:
                mock_run.return_value.stdout = "jj 0.25.0\n"
                rc = cmd_doctor(_make_args())

    assert rc == 0
    out = capsys.readouterr().out
    assert "JJ:" in out
    assert "Data repo:" in out
    assert "Scope:" in out


def test_doctor_missing_jj(tmp_path, monkeypatch, capsys):
    """doctor exits 1 and suggests install when JJ is missing."""
    monkeypatch.chdir(tmp_path)
    data_repo = _make_valid_data_repo(tmp_path)
    (tmp_path / ".env").write_text("FAVA_TRAILS_SCOPE=mw/eng/test\n")

    fallback = Path.home() / ".local" / "bin" / "jj"
    real_exists = Path.exists

    def exists_side_effect(self):
        if self == fallback:
            return False
        return real_exists(self)

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("shutil.which", return_value=None):
            with patch.object(Path, "exists", exists_side_effect):
                rc = cmd_doctor(_make_args())

    assert rc == 1
    out = capsys.readouterr().out
    assert "NOT FOUND" in out
    assert "install-jj" in out


def test_doctor_missing_data_repo(tmp_path, monkeypatch, capsys):
    """doctor exits 1 and suggests bootstrap when data repo is absent."""
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "nonexistent"
    (tmp_path / ".env").write_text("FAVA_TRAILS_SCOPE=mw/eng/test\n")

    with patch("fava_trails.cli.get_data_repo_root", return_value=missing):
        with patch("shutil.which", return_value="/usr/bin/jj"):
            with patch("subprocess.run", return_value=_make_jj_mock(0)) as mock_run:
                mock_run.return_value.stdout = "jj 0.25.0\n"
                rc = cmd_doctor(_make_args())

    assert rc == 1
    out = capsys.readouterr().out
    assert "NOT FOUND" in out
    assert "bootstrap" in out


def test_doctor_missing_scope(tmp_path, monkeypatch, capsys):
    """doctor exits 1 and suggests init when scope is not configured."""
    monkeypatch.chdir(tmp_path)
    data_repo = _make_valid_data_repo(tmp_path)

    with patch("fava_trails.cli.get_data_repo_root", return_value=data_repo):
        with patch("shutil.which", return_value="/usr/bin/jj"):
            with patch("subprocess.run", return_value=_make_jj_mock(0)) as mock_run:
                mock_run.return_value.stdout = "jj 0.25.0\n"
                rc = cmd_doctor(_make_args())

    assert rc == 1
    out = capsys.readouterr().out
    assert "NOT CONFIGURED" in out
    assert "fava-trails init" in out


def test_doctor_in_help(capsys):
    """doctor subcommand appears in fava-trails --help output."""
    result = subprocess.run(
        [sys.executable, "-m", "fava_trails.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert "doctor" in result.stdout


# ─── Additional bootstrap tests ───────────────────────────────────────────────


def test_bootstrap_refuses_existing_config(tmp_path):
    """bootstrap refuses to overwrite an existing config.yaml."""
    target = tmp_path / "data-repo"
    target.mkdir()
    (target / "config.yaml").write_text("trails_dir: trails\n")
    args = _make_args(path=str(target), remote=None)

    with patch("shutil.which", return_value="/usr/bin/jj"):
        rc = cmd_bootstrap(args)

    assert rc == 1

# ─── install-jj tests ─────────────────────────────────────────────────────────


def _make_install_jj_args(version=None):
    args = MagicMock()
    args.jj_version = version
    return args


def test_install_jj_skips_if_version_matches(tmp_path, capsys):
    """install-jj exits 0 without downloading when the installed version matches."""
    jj_bin = str(tmp_path / "jj")
    Path(jj_bin).touch()

    mock_result = MagicMock()
    mock_result.stdout = "jj 0.28.0\n"
    mock_result.returncode = 0

    with patch("shutil.which", return_value=jj_bin):
        with patch("subprocess.run", return_value=mock_result):
            rc = cmd_install_jj(_make_install_jj_args())

    assert rc == 0
    out = capsys.readouterr().out
    assert "already installed" in out


def test_install_jj_unsupported_platform(capsys):
    """install-jj exits 1 on Windows and prints winget instructions."""
    with patch("sys.platform", "win32"):
        with patch("shutil.which", return_value=None):
            rc = cmd_install_jj(_make_install_jj_args())

    assert rc == 1
    out = capsys.readouterr().out
    assert "winget" in out


def test_install_jj_unsupported_arch(capsys):
    """install-jj exits 1 on unsupported Linux architecture."""
    with patch("sys.platform", "linux"):
        with patch("platform.machine", return_value="mips"):
            with patch("shutil.which", return_value=None):
                with patch("subprocess.run", side_effect=OSError("no jj")):
                    rc = cmd_install_jj(_make_install_jj_args())

    assert rc == 1
    err = capsys.readouterr().err
    assert "Unsupported" in err


def _make_fake_tarball(jj_data: bytes = b"#!/bin/sh\necho jj") -> bytes:
    """Create an in-memory .tar.gz containing a 'jj' binary."""
    import io
    import tarfile as _tarfile

    buf = io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = _tarfile.TarInfo(name="jj")
        info.size = len(jj_data)
        tf.addfile(info, io.BytesIO(jj_data))
    return buf.getvalue()


def _fake_urlopen(fake_bytes: bytes):
    """Return a context-manager mock for urllib.request.urlopen."""
    import io

    class FakeResponse:
        def read(self, n=-1):
            return self._buf.read(n)

        def __enter__(self):
            self._buf = io.BytesIO(fake_bytes)
            return self

        def __exit__(self, *a):
            pass

    return FakeResponse()


def test_install_jj_downloads_and_installs(tmp_path, capsys):
    """install-jj downloads tarball, extracts binary, and verifies installation."""
    fake_bytes = _make_fake_tarball(b"#!/bin/sh\necho jj 0.28.0")
    install_dir = tmp_path / ".local" / "bin"
    install_dir.mkdir(parents=True)

    mock_run_result = MagicMock()
    mock_run_result.stdout = "jj 0.28.0\n"
    mock_run_result.returncode = 0

    with patch("shutil.which", return_value=None):
        with patch("fava_trails.cli._JJ_INSTALL_DIR", install_dir):
            with patch("urllib.request.urlopen", return_value=_fake_urlopen(fake_bytes)):
                with patch("subprocess.run", return_value=mock_run_result):
                    rc = cmd_install_jj(_make_install_jj_args())

    assert rc == 0
    assert (install_dir / "jj").exists()


def test_install_jj_custom_version(tmp_path, capsys):
    """install-jj uses --version argument in the download URL."""
    captured_urls = []
    fake_bytes = _make_fake_tarball()
    install_dir = tmp_path / ".local" / "bin"
    install_dir.mkdir(parents=True)

    def fake_urlopen(url, timeout=None):
        captured_urls.append(url)
        return _fake_urlopen(fake_bytes)

    mock_run_result = MagicMock()
    mock_run_result.stdout = "jj 0.29.0\n"

    with patch("shutil.which", return_value=None):
        with patch("fava_trails.cli._JJ_INSTALL_DIR", install_dir):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with patch("subprocess.run", return_value=mock_run_result):
                    rc = cmd_install_jj(_make_install_jj_args(version="0.29.0"))

    assert rc == 0
    assert len(captured_urls) == 1
    assert "0.29.0" in captured_urls[0]


def test_install_jj_in_help(capsys):
    """install-jj subcommand appears in fava-trails --help output."""
    result = subprocess.run(
        [sys.executable, "-m", "fava_trails.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert "install-jj" in result.stdout

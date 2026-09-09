"""Unit tests for JJ installer selection / install policy (issue #98)."""

from __future__ import annotations

import hashlib
import io
import stat
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from fava_trails.jj_install import (
    JJ_MIN_VERSION,
    Version,
    detect_platform,
    format_selection_report,
    is_compatible,
    parse_version_from_output,
    select_or_install,
)


def _make_tarball(jj_script: str) -> bytes:
    data = jj_script.encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="jj")
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fake_jj_script(version: str) -> str:
    # Portable enough for Linux CI; reports via --version
    return f"#!/bin/sh\necho 'jj {version}'\n"


def _write_executable(path: Path, version: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_fake_jj_script(version))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _release_payload(version: str, suffix: str, blob: bytes, *, with_digest: bool = True) -> dict:
    digest = f"sha256:{hashlib.sha256(blob).hexdigest()}" if with_digest else None
    name = f"jj-v{version}-{suffix}.tar.gz"
    asset = {
        "name": name,
        "browser_download_url": f"https://example.test/{name}",
    }
    if digest:
        asset["digest"] = digest
    return {"tag_name": f"v{version}", "assets": [asset]}


def test_parse_and_compare_versions():
    assert parse_version_from_output("jj 0.45.1-abcdef") == Version(0, 45, 1)
    assert is_compatible(Version.parse("0.28.0"))
    assert is_compatible(Version.parse("0.45.1"))
    assert not is_compatible(Version.parse("0.27.9"))
    assert Version.parse("0.45.1") >= Version.parse(JJ_MIN_VERSION)


def test_detect_platform_linux_and_windows():
    t = detect_platform(os_name="linux", machine="x86_64")
    assert "linux-musl" in t.suffix
    with pytest.raises(Exception, match="Windows"):
        detect_platform(os_name="win32", machine="x86_64")


def test_reuse_compatible_newer(tmp_path):
    jj = _write_executable(tmp_path / "bin" / "jj", "0.45.1")
    install_dir = tmp_path / "managed"

    def boom(*_a, **_k):
        raise AssertionError("must not hit network when reusing")

    result = select_or_install(
        install_dir=install_dir,
        which_jj=str(jj),
        fetch_json=boom,
        download=boom,
        os_name="linux",
        machine="x86_64",
    )
    assert result.exit_code == 0
    assert result.action == "reuse"
    assert result.version == "0.45.1"
    assert "compatible" in result.reason
    assert "not downgrading" in result.reason


def test_reuse_exact_min(tmp_path):
    jj = _write_executable(tmp_path / "jj", JJ_MIN_VERSION)
    result = select_or_install(
        install_dir=tmp_path / "managed",
        which_jj=str(jj),
        fetch_json=lambda *_: (_ for _ in ()).throw(RuntimeError("no")),
        os_name="linux",
        machine="x86_64",
    )
    assert result.action == "reuse"
    assert result.version == JJ_MIN_VERSION


def test_refuse_user_managed_incompatible(tmp_path):
    jj = _write_executable(tmp_path / "usr" / "bin" / "jj", "0.20.0")
    result = select_or_install(
        install_dir=tmp_path / "managed",
        which_jj=str(jj),
        fetch_json=lambda *_: {"tag_name": "v0.45.1", "assets": []},
        os_name="linux",
        machine="x86_64",
    )
    assert result.exit_code == 1
    assert result.action == "refuse"
    assert "user-managed" in result.reason
    assert "refusing to overwrite" in result.reason
    # Must not have written managed binary
    assert not (tmp_path / "managed" / "jj").exists()


def test_refuse_user_managed_when_explicit_differs(tmp_path):
    jj = _write_executable(tmp_path / "usr" / "bin" / "jj", "0.45.1")
    result = select_or_install(
        explicit_version="0.28.0",
        install_dir=tmp_path / "managed",
        which_jj=str(jj),
        os_name="linux",
        machine="x86_64",
    )
    assert result.action == "refuse"
    assert result.exit_code == 1


def test_install_when_absent(tmp_path):
    install_dir = tmp_path / "managed"
    version = "0.45.1"
    suffix = "x86_64-unknown-linux-musl"
    blob = _make_tarball(_fake_jj_script(version))
    payload = _release_payload(version, suffix, blob)

    def fetch_json(url: str):
        assert "releases/latest" in url
        return payload

    def download(url: str, dest: Path):
        dest.write_bytes(blob)

    result = select_or_install(
        install_dir=install_dir,
        which_jj=None,
        fetch_json=fetch_json,
        download=download,
        os_name="linux",
        machine="x86_64",
    )
    assert result.exit_code == 0
    assert result.action == "install"
    assert result.version == version
    assert (install_dir / "jj").exists()
    assert "sha256 verified" in result.reason


def test_explicit_override_installs_exact(tmp_path):
    install_dir = tmp_path / "managed"
    version = "0.28.0"
    suffix = "x86_64-unknown-linux-musl"
    blob = _make_tarball(_fake_jj_script(version))
    # Old tags may lack digest
    payload = _release_payload(version, suffix, blob, with_digest=False)

    def fetch_json(url: str):
        assert f"tags/v{version}" in url
        return payload

    result = select_or_install(
        explicit_version=version,
        install_dir=install_dir,
        which_jj=None,
        fetch_json=fetch_json,
        download=lambda url, dest: dest.write_bytes(blob),
        os_name="linux",
        machine="x86_64",
    )
    assert result.action == "install"
    assert result.version == version
    assert "no official digest" in result.reason


def test_network_failure_without_existing(tmp_path):
    def fetch_json(_url: str):
        from fava_trails.jj_install import JjInstallError

        raise JjInstallError("Network error resolving JJ release")

    result = select_or_install(
        install_dir=tmp_path / "managed",
        which_jj=None,
        fetch_json=fetch_json,
        os_name="linux",
        machine="x86_64",
    )
    assert result.exit_code == 1
    assert result.action == "error"
    assert "could not resolve" in result.reason


def test_failed_install_preserves_prior_managed(tmp_path):
    install_dir = tmp_path / "managed"
    prior = _write_executable(install_dir / "jj", "0.28.0")
    prior_bytes = prior.read_bytes()
    version = "0.45.1"
    suffix = "x86_64-unknown-linux-musl"
    # Tarball claims 0.45.1 but script reports wrong version → verify fails
    blob = _make_tarball(_fake_jj_script("0.0.0"))
    payload = _release_payload(version, suffix, blob, with_digest=False)

    # Force reinstall of managed (below would reuse 0.28; force_install)
    result = select_or_install(
        explicit_version=version,
        force_install=True,
        install_dir=install_dir,
        which_jj=str(prior),
        fetch_json=lambda _u: payload,
        download=lambda u, d: d.write_bytes(blob),
        os_name="linux",
        machine="x86_64",
    )
    assert result.exit_code == 1
    assert result.action == "error"
    assert "preserved" in result.reason
    # Prior binary still present and unchanged
    assert prior.exists()
    assert prior.read_bytes() == prior_bytes


def test_sha256_mismatch_aborts(tmp_path):
    install_dir = tmp_path / "managed"
    version = "0.45.1"
    suffix = "x86_64-unknown-linux-musl"
    blob = _make_tarball(_fake_jj_script(version))
    payload = _release_payload(version, suffix, blob)
    payload["assets"][0]["digest"] = "sha256:" + ("0" * 64)

    result = select_or_install(
        install_dir=install_dir,
        which_jj=None,
        fetch_json=lambda _u: payload,
        download=lambda u, d: d.write_bytes(blob),
        os_name="linux",
        machine="x86_64",
    )
    assert result.exit_code == 1
    assert "SHA-256 mismatch" in result.reason
    assert not (install_dir / "jj").exists()


def test_upgrade_managed_incompatible(tmp_path):
    install_dir = tmp_path / "managed"
    old = _write_executable(install_dir / "jj", "0.20.0")
    version = "0.45.1"
    suffix = "x86_64-unknown-linux-musl"
    blob = _make_tarball(_fake_jj_script(version))
    payload = _release_payload(version, suffix, blob)

    result = select_or_install(
        install_dir=install_dir,
        which_jj=str(old),
        fetch_json=lambda _u: payload,
        download=lambda u, d: d.write_bytes(blob),
        os_name="linux",
        machine="x86_64",
    )
    assert result.action == "install"
    assert result.version == version


def test_format_selection_report_includes_fields():
    from fava_trails.jj_install import SelectionResult

    text = format_selection_report(
        SelectionResult(action="reuse", path="/x/jj", version="0.45.1", reason="ok")
    )
    assert "action:  reuse" in text
    assert "0.45.1" in text


def test_cli_install_jj_reuses(tmp_path, capsys, monkeypatch):
    from fava_trails.cli import cmd_install_jj

    jj = _write_executable(tmp_path / "jj", "0.45.1")
    install_dir = tmp_path / "managed"
    monkeypatch.setattr("fava_trails.cli._JJ_INSTALL_DIR", install_dir)

    with patch("fava_trails.jj_install.shutil.which", return_value=str(jj)):
        with patch("fava_trails.jj_install.find_jj_candidates", return_value=[jj]):
            rc = cmd_install_jj(type("A", (), {"jj_version": None, "force": False})())

    assert rc == 0
    out = capsys.readouterr().out
    assert "reuse" in out
    assert "0.45.1" in out


def test_cli_install_jj_unsupported_windows(capsys):
    from fava_trails.cli import cmd_install_jj

    with patch("fava_trails.jj_install.sys.platform", "win32"):
        with patch("fava_trails.jj_install.platform.machine", return_value="AMD64"):
            with patch("fava_trails.jj_install.discover_existing", return_value=None):
                rc = cmd_install_jj(type("A", (), {"jj_version": None, "force": False})())

    assert rc == 1
    err = capsys.readouterr().err
    assert "winget" in err


def test_cli_install_jj_help_mentions_latest():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "fava_trails.cli", "install-jj", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "stable" in result.stdout.lower() or "version" in result.stdout.lower()

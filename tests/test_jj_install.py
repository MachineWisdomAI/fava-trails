"""Unit tests for JJ installer selection / install policy (issue #98)."""

from __future__ import annotations

import hashlib
import io
import operator
import stat
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from fava_trails.jj_install import (
    JJ_MIN_VERSION,
    JjInstallError,
    Version,
    detect_platform,
    extract_jj_from_tarball,
    format_selection_report,
    is_compatible,
    parse_version_from_output,
    path_hint,
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


def _make_tarball_from_members(members: list[tuple[str, bytes | None, str]]) -> bytes:
    """Build a gzipped tar.

    Each member is ``(name, content_or_none, kind)`` where kind is
    ``file`` | ``symlink`` | ``dir``.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content, kind in members:
            info = tarfile.TarInfo(name=name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = content.decode() if isinstance(content, bytes) else (content or "x")
                info.mode = 0o777
                tf.addfile(info)
            else:
                data = content or b""
                info.size = len(data)
                info.mode = 0o755
                info.type = tarfile.REGTYPE
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
    assert Version.parse("0.45.1") == Version(0, 45, 1)


@pytest.mark.parametrize(
    "left, right, op, expected",
    [
        # Independent cases so each operator is exercised without chained tautologies.
        (Version(0, 28, 0), Version(0, 45, 1), operator.lt, True),
        (Version(0, 45, 1), Version(0, 28, 0), operator.gt, True),
        (Version(0, 28, 0), Version(0, 45, 1), operator.le, True),
        (Version(0, 45, 1), Version(0, 28, 0), operator.ge, True),
        (Version(0, 45, 1), Version(0, 45, 1), operator.le, True),
        (Version(0, 45, 1), Version(0, 45, 1), operator.ge, True),
        (Version(0, 45, 1), Version(0, 28, 0), operator.lt, False),
        (Version(0, 28, 0), Version(0, 45, 1), operator.gt, False),
        (Version(0, 28, 0), Version.parse(JJ_MIN_VERSION), operator.eq, True),
    ],
)
def test_version_ordering_operators(left, right, op, expected):
    assert op(left, right) is expected


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


def test_failed_post_replace_verify_restores_prior(tmp_path):
    """Regression: restore prior managed bytes even when dest already has the failed new file."""
    from fava_trails.jj_install import JjInstallError, verify_executable_version

    install_dir = tmp_path / "managed"
    prior = _write_executable(install_dir / "jj", "0.28.0")
    prior_bytes = prior.read_bytes()
    version = "0.45.1"
    suffix = "x86_64-unknown-linux-musl"
    # Staged verification succeeds; only the *second* (post-replace) verify fails.
    blob = _make_tarball(_fake_jj_script(version))
    payload = _release_payload(version, suffix, blob, with_digest=False)

    real_verify = verify_executable_version
    calls = {"n": 0}

    def flaky_verify(path, expected=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_verify(path, expected)
        raise JjInstallError("post-replace verification failed (injected)")

    with patch("fava_trails.jj_install.verify_executable_version", side_effect=flaky_verify):
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
    assert prior.exists()
    assert prior.read_bytes() == prior_bytes
    # Backup must not strand the prior binary
    assert not (install_dir / "jj.fava-prev").exists()
    assert calls["n"] >= 2


def test_failed_post_replace_verify_removes_dest_when_no_prior(tmp_path):
    """Fresh install: post-replace verify failure must not leave invalid dest bytes."""
    from fava_trails.jj_install import JjInstallError, verify_executable_version

    install_dir = tmp_path / "managed"
    dest = install_dir / "jj"
    version = "0.45.1"
    suffix = "x86_64-unknown-linux-musl"
    blob = _make_tarball(_fake_jj_script(version))
    payload = _release_payload(version, suffix, blob, with_digest=False)

    real_verify = verify_executable_version
    calls = {"n": 0}

    def flaky_verify(path, expected=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_verify(path, expected)
        raise JjInstallError("post-replace verification failed (injected)")

    assert not dest.exists()
    with patch("fava_trails.jj_install.verify_executable_version", side_effect=flaky_verify):
        result = select_or_install(
            explicit_version=version,
            force_install=True,
            install_dir=install_dir,
            which_jj=None,
            fetch_json=lambda _u: payload,
            download=lambda u, d: d.write_bytes(blob),
            os_name="linux",
            machine="x86_64",
        )

    assert result.exit_code == 1
    assert result.action == "error"
    assert not dest.exists(), "failed fresh install must not leave unverified dest"
    assert not (install_dir / "jj.fava-prev").exists()
    assert not (install_dir / "jj.fava-new").exists()
    assert calls["n"] >= 2


def test_reuse_compatible_on_unsupported_download_platform(tmp_path):
    """Reuse must not require a FAVA-downloadable platform asset."""
    jj = _write_executable(tmp_path / "bin" / "jj", "0.45.1")

    def boom(*_a, **_k):
        raise AssertionError("must not hit network when reusing")

    result = select_or_install(
        install_dir=tmp_path / "managed",
        which_jj=str(jj),
        fetch_json=boom,
        download=boom,
        os_name="linux",
        machine="mips",  # no downloadable asset for this arch
    )
    assert result.exit_code == 0
    assert result.action == "reuse"
    assert result.version == "0.45.1"
    assert "compatible" in result.reason


def test_shell_install_jj_is_thin_delegate():
    """scripts/install-jj.sh must not reimplement installer policy."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "install-jj.sh"
    text = script.read_text()
    assert "fava_trails.jj_install" in text
    assert "tar -xzf" not in text
    assert "RESOLVED_SHA256" not in text
    assert "exec" in text
    # Bash 3.2 + set -u forbids expanding empty arrays; wrapper must not do that.
    assert "ARGS=()" not in text
    assert '("${ARGS[@]}")' not in text
    assert "Bash 3.2" in text


def test_shell_install_jj_bash32_empty_argv_safe(tmp_path):
    """No-arg path must not trip set -u (macOS Bash 3.2 empty-array footgun).

    Bash 3.2 treats ``\"${empty[@]}\"`` under ``set -u`` as unbound; Bash 4.4+
    does not. CI may only have modern Bash, so we (1) forbid the historical
    pattern in the script, (2) prove the ``set --`` rebuild works with zero
    args under ``set -u``, and (3) run the live no-arg wrapper path.
    """
    import os
    import shutil
    import subprocess
    import textwrap

    bash = shutil.which("bash")
    assert bash

    # Pattern used by install-jj.sh: set -- rebuild with zero incoming args.
    safe = textwrap.dedent(
        r"""
        set -euo pipefail
        _run() {
          shift
          if [[ -n "${INSTALL_DIR:-}" ]]; then
            set -- --install-dir "${INSTALL_DIR}" "$@"
          fi
          if [[ "${FORCE:-0}" == "1" ]]; then
            set -- --force "$@"
          fi
          if [[ -n "${JJ_VERSION:-}" ]]; then
            set -- --version "${JJ_VERSION}" "$@"
          fi
          printf 'argc=%s\n' "$#"
          printf 'ok\n'
        }
        _run python3
        """
    )
    good = subprocess.run([bash, "-c", safe], capture_output=True, text=True)
    assert good.returncode == 0, good.stderr + good.stdout
    assert "argc=0" in good.stdout
    assert "ok" in good.stdout

    # On Bash < 4.4, also prove the old empty-array copy fails under set -u.
    ver = subprocess.run(
        [bash, "-c", 'printf "%s.%s\\n" "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    major_s, _, minor_s = ver.partition(".")
    try:
        major, minor = int(major_s), int(minor_s or "0")
    except ValueError:
        major, minor = 99, 0
    if (major, minor) < (4, 4):
        footgun = textwrap.dedent(
            r"""
            set -euo pipefail
            ARGS=()
            MODULE_ARGS=("${ARGS[@]}")
            printf 'should-not-reach\n'
            """
        )
        bad = subprocess.run([bash, "-c", footgun], capture_output=True, text=True)
        assert bad.returncode != 0, "empty-array expand must fail under Bash 3.2 set -u"

    # Live wrapper: documented no-argument path (reuse).
    jj = _write_executable(tmp_path / "bin" / "jj", "0.45.1")
    managed = tmp_path / "managed"
    managed.mkdir()
    script = Path(__file__).resolve().parents[1] / "scripts" / "install-jj.sh"
    py = shutil.which("python3") or shutil.which("python")
    assert py
    env = os.environ.copy()
    env["PATH"] = f"{jj.parent}:{Path(py).parent}:{Path(bash).parent}"
    env["INSTALL_DIR"] = str(managed)
    # Explicitly clear optional flag env so this is a pure no-arg invocation.
    env.pop("JJ_VERSION", None)
    env.pop("FORCE", None)
    result = subprocess.run(
        [bash, str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(script.parent.parent),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "reuse" in result.stdout

def test_shell_install_jj_reuses_via_python(tmp_path):
    """Thin shell entrypoint delegates reuse to the Python installer."""
    import os
    import shutil
    import subprocess

    jj = _write_executable(tmp_path / "bin" / "jj", "0.45.1")
    managed = tmp_path / "managed"
    managed.mkdir()
    script = Path(__file__).resolve().parents[1] / "scripts" / "install-jj.sh"
    # Keep system python/bash on PATH; put fake jj first; omit fava-trails by using a
    # minimal PATH prefix without a fava-trails shim.
    py = shutil.which("python3") or shutil.which("python")
    bash = shutil.which("bash")
    assert py and bash
    py_dir = str(Path(py).parent)
    bash_dir = str(Path(bash).parent)
    env = os.environ.copy()
    env["PATH"] = f"{jj.parent}:{py_dir}:{bash_dir}"
    env["INSTALL_DIR"] = str(managed)
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(script.parent.parent),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "reuse" in result.stdout
    assert "0.45.1" in result.stdout


def test_extract_jj_accepts_single_nested_regular_member(tmp_path):
    blob = _make_tarball_from_members(
        [("prefix/jj", b"#!/bin/sh\necho ok\n", "file")]
    )
    tar_path = tmp_path / "jj.tar.gz"
    tar_path.write_bytes(blob)
    out = extract_jj_from_tarball(tar_path, tmp_path / "out")
    assert out.name == "jj"
    assert out.read_bytes().startswith(b"#!/bin/sh")


@pytest.mark.parametrize(
    "members, match",
    [
        (
            [("jj", b"a", "file"), ("other/jj", b"b", "file")],
            "ambiguous",
        ),
        (
            [("jj", None, "symlink")],
            "not a regular file",
        ),
        (
            [("jj", None, "dir")],
            "not a regular file",
        ),
        (
            [("../jj", b"x", "file")],
            "unsafe",
        ),
        (
            [("/tmp/jj", b"x", "file")],
            "unsafe",
        ),
        (
            [("bin/not-jj", b"x", "file")],
            "not found",
        ),
    ],
)
def test_extract_jj_rejects_adversarial_members(tmp_path, members, match):
    blob = _make_tarball_from_members(members)
    tar_path = tmp_path / "jj.tar.gz"
    tar_path.write_bytes(blob)
    with pytest.raises(JjInstallError, match=match):
        extract_jj_from_tarball(tar_path, tmp_path / "out")


def test_path_hint_default_mentions_local_bin():
    text = path_hint()
    assert "~/.local/bin" in text
    assert "$HOME/.local/bin" in text


def test_path_hint_uses_custom_install_dir(tmp_path):
    custom = tmp_path / "custom" / "bin"
    custom.mkdir(parents=True)
    text = path_hint(custom)
    assert str(custom.resolve()) in text or str(custom) in text
    assert "~/.local/bin" not in text
    # Export line should reference the custom directory, not the default.
    assert ".local/bin:$PATH" not in text


def test_path_hint_quotes_shell_sensitive_custom_dir(tmp_path):
    """Apostrophes and shell metacharacters must not break suggested shell commands."""
    import os
    import shlex
    import subprocess

    # Path with apostrophe, space, dollar, backtick, and double-quote.
    custom = tmp_path / "o'brien bin" / 'x$y`z"w'
    custom.mkdir(parents=True)
    text = path_hint(custom)
    resolved = str(custom.resolve())
    assert resolved in text or "o'brien" in text
    assert "~/.local/bin" not in text

    lines = text.splitlines()
    cmd_line = next(line.strip() for line in lines if line.strip().startswith("echo "))
    echo_part = cmd_line.split(" >> ", 1)[0]
    tokens = shlex.split(echo_part)
    assert tokens[0] == "echo"
    export_stmt = tokens[1]
    assert export_stmt.startswith("export PATH=")

    # Evaluate the export in bash; the directory must be PATH's first entry literally.
    probe = subprocess.run(
        [
            "bash",
            "-c",
            export_stmt + '; python3 -c "import os; print(os.environ[\'PATH\'].split(\':\')[0])"',
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == resolved


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

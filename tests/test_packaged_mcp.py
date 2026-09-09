"""The regular CI suite must exercise the installed wheel's real MCP entrypoint."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _build_artifacts(root: Path, out_dir: Path) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    assert uv, "Run the package verification with the project's uv toolchain"
    build = subprocess.run(
        [uv, "build", "--out-dir", str(out_dir)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list(out_dir.glob("*.whl"))
    sdists = list(out_dir.glob("*.tar.gz"))
    assert len(wheels) == 1, wheels
    assert len(sdists) == 1, sdists
    return wheels[0], sdists[0]


def test_built_wheel_starts_and_serves_mcp(tmp_path):
    root = Path(__file__).resolve().parent.parent
    wheel, _sdist = _build_artifacts(root, tmp_path / "dist")
    env = {**os.environ, "FAVA_EXPECT_WHEEL": "1"}
    verified = subprocess.run(
        [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--python",
            sys.executable,
            "--with",
            str(wheel),
            "--with",
            "pytest>=9,<10",
            "--with",
            "pytest-asyncio>=1.3,<2",
            "pytest",
            str(root / "tests" / "test_mcp_protocol.py"),
            "-v",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_built_wheel_preserves_governed_recall_isolation(tmp_path):
    """Issue #99 / #72: installed artifact keeps approved-only and identity isolation."""
    root = Path(__file__).resolve().parent.parent
    wheel, _sdist = _build_artifacts(root, tmp_path / "dist")
    env = {**os.environ, "FAVA_EXPECT_WHEEL": "1"}
    # Link existing #72 coverage rather than rebuilding those cases here.
    verified = subprocess.run(
        [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--python",
            sys.executable,
            "--with",
            str(wheel),
            "--with",
            "pytest>=9,<10",
            "--with",
            "pytest-asyncio>=1.3,<2",
            "pytest",
            str(root / "tests" / "test_governance.py"),
            str(root / "tests" / "test_runtime_info.py"),
            "-v",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_candidate_artifacts_support_fresh_install_and_upgrade_from_0_6_0(tmp_path):
    """Build wheel+sdist once; verify fresh install and upgrade from published 0.6.0."""
    root = Path(__file__).resolve().parent.parent
    wheel, sdist = _build_artifacts(root, tmp_path / "dist")
    uv = shutil.which("uv")
    assert uv

    def _probe(python: Path) -> str:
        probe = (
            "import importlib.metadata as m\n"
            "from fava_trails.runtime_info import runtime_report\n"
            "r = runtime_report()\n"
            "assert r['package_version'] == r['module_version'] == m.version('fava-trails')\n"
            "print(r['package_version'], r['mcp_sdk_version'], r['source_kind'])\n"
        )
        return subprocess.check_output([str(python), "-c", probe], text=True).strip()

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    subprocess.run([uv, "venv", str(fresh / ".venv")], check=True, capture_output=True, text=True)
    fresh_py = fresh / ".venv" / "bin" / "python"
    install_fresh = subprocess.run(
        [uv, "pip", "install", "--python", str(fresh_py), str(wheel)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert install_fresh.returncode == 0, install_fresh.stdout + install_fresh.stderr
    fresh_probe = _probe(fresh_py)
    assert fresh_probe.split()[0] == "0.6.1"
    version_cmd = subprocess.run(
        [str(fresh / ".venv" / "bin" / "fava-trails"), "version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert version_cmd.returncode == 0, version_cmd.stdout + version_cmd.stderr
    assert "Package version:" in version_cmd.stdout
    assert "0.6.1" in version_cmd.stdout
    assert "MCP SDK version:" in version_cmd.stdout
    assert "Source:             installed" in version_cmd.stdout

    upgrade = tmp_path / "upgrade"
    upgrade.mkdir()
    subprocess.run([uv, "venv", str(upgrade / ".venv")], check=True, capture_output=True, text=True)
    upgrade_py = upgrade / ".venv" / "bin" / "python"
    baseline = subprocess.run(
        [uv, "pip", "install", "--python", str(upgrade_py), "fava-trails==0.6.0"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    before = subprocess.check_output(
        [str(upgrade_py), "-c", "import importlib.metadata as m; print(m.version('fava-trails'))"],
        text=True,
    ).strip()
    assert before == "0.6.0"
    upgraded = subprocess.run(
        [uv, "pip", "install", "--python", str(upgrade_py), "--upgrade", str(wheel)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    after = _probe(upgrade_py)
    assert after.split()[0] == "0.6.1"

    # sdist must also be installable in isolation (release candidate gate).
    sdist_env = tmp_path / "sdist"
    sdist_env.mkdir()
    subprocess.run([uv, "venv", str(sdist_env / ".venv")], check=True, capture_output=True, text=True)
    sdist_py = sdist_env / ".venv" / "bin" / "python"
    sdist_install = subprocess.run(
        [uv, "pip", "install", "--python", str(sdist_py), str(sdist)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert sdist_install.returncode == 0, sdist_install.stdout + sdist_install.stderr
    sdist_probe = _probe(sdist_py)
    assert sdist_probe.split()[0] == "0.6.1"

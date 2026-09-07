"""The regular CI suite must exercise the installed wheel's real MCP entrypoint."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_built_wheel_starts_and_serves_mcp(tmp_path):
    root = Path(__file__).resolve().parent.parent
    uv = shutil.which("uv")
    assert uv, "Run the package verification with the project's uv toolchain"
    build = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(tmp_path / "dist")],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list((tmp_path / "dist").glob("*.whl"))
    assert len(wheels) == 1
    env = {**os.environ, "FAVA_EXPECT_WHEEL": "1"}
    verified = subprocess.run(
        [
            uv, "run", "--isolated", "--no-project", "--python", sys.executable,
            "--with", str(wheels[0]), "--with", "pytest>=9,<10", "--with", "pytest-asyncio>=1.3,<2",
            "pytest", str(root / "tests" / "test_mcp_protocol.py"), "-v",
        ],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr

"""Regression tests for runtime dependency compatibility boundaries."""

import tomllib
from pathlib import Path


def test_mcp_dependency_excludes_incompatible_major_version():
    """FAVA's current server registration API requires MCP 1.x."""
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())

    mcp_requirement = next(
        dependency
        for dependency in pyproject["project"]["dependencies"]
        if dependency.startswith("mcp")
    )

    assert "<2.0" in mcp_requirement

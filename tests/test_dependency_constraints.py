"""Regression tests for runtime dependency compatibility boundaries."""

import tomllib
from pathlib import Path


def test_all_direct_dependencies_exclude_their_next_major_version():
    """Named dependencies must not silently cross a major compatibility boundary."""
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())

    dependencies = [*pyproject["project"]["dependencies"]]
    for group in pyproject["project"].get("optional-dependencies", {}).values():
        dependencies.extend(group)
    for group in pyproject.get("dependency-groups", {}).values():
        dependencies.extend(group)
    dependencies.extend(pyproject["build-system"]["requires"])

    unbounded = [dependency for dependency in dependencies if "<" not in dependency]

    assert not unbounded, f"missing next-major bound: {', '.join(unbounded)}"

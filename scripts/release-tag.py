#!/usr/bin/env python3
"""Validate a release tag against the package version and print its channel.

Allowed tags: ``vMAJOR.MINOR.PATCH`` (stable) and ``vMAJOR.MINOR.PATCHrcN``
(PEP 440 release candidate, N >= 1, no leading zero). The tag minus ``v`` must
equal the pyproject version exactly. Prints ``stable`` or ``rc``; exits non-zero
with an error otherwise. Standard library only.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

_NUM = r"(?:0|[1-9][0-9]*)"
STABLE = re.compile(rf"^v{_NUM}\.{_NUM}\.{_NUM}$")
RC = re.compile(rf"^v{_NUM}\.{_NUM}\.{_NUM}rc[1-9][0-9]*$")


def classify(tag: str, package_version: str) -> str:
    if STABLE.fullmatch(tag):
        channel = "stable"
    elif RC.fullmatch(tag):
        channel = "rc"
    else:
        raise ValueError(f"Tag must be vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCHrcN (got: {tag})")
    if tag[1:] != package_version:
        raise ValueError(f"Tag {tag} does not match pyproject.toml version {package_version}")
    # A stable tag can never carry rc metadata and vice versa (guaranteed by equality + grammar).
    return channel


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: release-tag.py TAG [PYPROJECT]", file=sys.stderr)
        return 2
    pyproject = Path(argv[2] if len(argv) == 3 else "pyproject.toml")
    version = tomllib.loads(pyproject.read_text())["project"]["version"]
    try:
        print(classify(argv[1], version))
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

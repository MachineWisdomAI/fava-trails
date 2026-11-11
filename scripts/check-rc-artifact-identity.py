#!/usr/bin/env python3
"""Prove a same-base release candidate differs from its base only in version metadata.

Builds the wheel and sdist of ``--base-ref`` and of ``--candidate-ref`` (default
HEAD) with ``uv build`` from clean ``git archive`` trees, then compares them. The
candidate must carry the same members as the base, with identical bytes once the
candidate version (``0.9.3rc1``) is rewritten to the base version (``0.9.3``).
Wheel ``RECORD`` is ignored because it hashes the version-bearing files. Prints a
JSON report (versions, file names, SHA-256) and exits non-zero on any difference.
It never tags, publishes, installs, or touches a network index beyond what
``uv build`` needs. Standard library plus ``uv`` and ``git``.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

IGNORED_WHEEL_MEMBERS = ("RECORD",)


def _normalise(data: bytes, candidate: str, base: str) -> bytes:
    return data.replace(candidate.encode(), base.encode())


def _wheel_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {
            n: zf.read(n)
            for n in zf.namelist()
            if not n.endswith("/") and n.rsplit("/", 1)[-1] not in IGNORED_WHEEL_MEMBERS
        }


def _sdist_members(path: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as tf:
        for member in tf.getmembers():
            if member.isfile():
                out[member.name] = tf.extractfile(member).read()  # type: ignore[union-attr]
    return out


def _compare_members(
    label: str, base: dict[str, bytes], cand: dict[str, bytes], base_version: str, cand_version: str
) -> list[str]:
    problems: list[str] = []
    cand_by_base_name = {n.replace(cand_version, base_version): n for n in cand}
    for name in sorted(set(base) - set(cand_by_base_name)):
        problems.append(f"{label}: missing from candidate: {name}")
    for name in sorted(set(cand_by_base_name) - set(base)):
        problems.append(f"{label}: unexpected in candidate: {cand_by_base_name[name]}")
    differing = 0
    for name in sorted(set(base) & set(cand_by_base_name)):
        got = _normalise(cand[cand_by_base_name[name]], cand_version, base_version)
        if got != base[name]:
            problems.append(f"{label}: non-version bytes differ: {name}")
        elif cand[cand_by_base_name[name]] != base[name]:
            differing += 1
    if not differing:
        problems.append(f"{label}: candidate carries no version change; it is not a candidate")
    return problems


def _single(directory: Path, pattern: str) -> Path:
    found = sorted(directory.glob(pattern))
    if len(found) != 1:
        raise ValueError(f"expected exactly one {pattern} in {directory}, found {len(found)}")
    return found[0]


def compare_artifacts(base_dir: Path, cand_dir: Path, base_version: str, cand_version: str) -> list[str]:
    """Return a list of problems; empty means the candidate is metadata-only."""
    problems: list[str] = []
    if base_version == cand_version:
        return [f"candidate version equals base version {base_version}"]
    try:
        base_wheel, cand_wheel = _single(base_dir, "*.whl"), _single(cand_dir, "*.whl")
        base_sdist, cand_sdist = _single(base_dir, "*.tar.gz"), _single(cand_dir, "*.tar.gz")
    except ValueError as e:
        return [str(e)]
    for base_file, cand_file in ((base_wheel, cand_wheel), (base_sdist, cand_sdist)):
        if cand_file.name != base_file.name.replace(base_version, cand_version):
            problems.append(f"artifact name {cand_file.name} does not carry version {cand_version}")
    problems += _compare_members(
        "wheel", _wheel_members(base_wheel), _wheel_members(cand_wheel), base_version, cand_version
    )
    problems += _compare_members(
        "sdist", _sdist_members(base_sdist), _sdist_members(cand_sdist), base_version, cand_version
    )
    return problems


def _git_archive(repo: Path, ref: str, dest: Path) -> None:
    data = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", ref], capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        tf.extractall(dest, filter="data")


def _build(repo: Path, ref: str, work: Path) -> tuple[Path, str]:
    tree = work / "tree"
    tree.mkdir()
    _git_archive(repo, ref, tree)
    version = tomllib.loads((tree / "pyproject.toml").read_text())["project"]["version"]
    out = work / "dist"
    subprocess.run(["uv", "build", "--out-dir", str(out)], cwd=tree, check=True, capture_output=True)
    return out, version


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hashes(directory: Path) -> dict[str, str]:
    return {p.name: _sha256(p) for p in sorted(directory.iterdir()) if p.suffix == ".whl" or p.name.endswith(".tar.gz")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="commit whose product bytes the candidate must keep")
    parser.add_argument("--candidate-ref", default="HEAD")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    with tempfile.TemporaryDirectory(prefix="rc-identity.") as tmp:
        roots = {}
        for name, ref in (("base", args.base_ref), ("candidate", args.candidate_ref)):
            work = Path(tmp) / name
            work.mkdir()
            roots[name] = _build(repo, ref, work)
        (base_dir, base_version), (cand_dir, cand_version) = roots["base"], roots["candidate"]
        problems = compare_artifacts(base_dir, cand_dir, base_version, cand_version)
        report = {
            "base_ref": args.base_ref,
            "candidate_ref": args.candidate_ref,
            "base_version": base_version,
            "candidate_version": cand_version,
            "candidate_artifacts": _hashes(cand_dir),
            "base_artifacts": _hashes(base_dir),
            "problems": problems,
        }
    print(json.dumps(report, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

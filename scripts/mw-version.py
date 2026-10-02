#!/usr/bin/env python3
"""Repository-local version updates. Python 3.11+, standard library only."""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from zoneinfo import ZoneInfo

CONFIG = ".version-policy.json"
SUBJECT = re.compile(r"^([a-z][a-z0-9-]*)(?:\([^()\r\n]+\))?(!)?: ([^\r\n]+)$")
BREAKING = re.compile(r"^BREAKING(?: CHANGE|-CHANGE):\s*\S", re.MULTILINE)
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")
WORKFLOW = '''name: Version policy
on:
  pull_request:
    types: [opened, reopened, edited, synchronize, ready_for_review]
permissions:
  contents: read
concurrency:
  group: version-policy-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  version-policy:
    name: Version policy
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: '3.11'
      - name: Check intended version against current base
        env:
          BASE_BRANCH: ${{ github.event.pull_request.base.ref }}
        run: python3 scripts/mw-version.py check --base "refs/remotes/origin/$BASE_BRANCH" --event-file "$GITHUB_EVENT_PATH"
'''
GUIDANCE = '''# Repository version policy

The updater needs Python 3.11 or newer and no third-party libraries. Select that
interpreter explicitly if the system `python3` is older (for example,
`python3.13 scripts/mw-version.py ...` on macOS).

Every change PR updates affected versions before merge. Run the repository-local
updater after your implementation and again after updating the branch from main:

```bash
git fetch origin main
python3 scripts/mw-version.py update --base origin/main --title 'chore(deps): update transitive dependency'
python3 scripts/mw-version.py check --base origin/main --title 'chore(deps): update transitive dependency'
```

Use the actual PR title. Supply `--body-file PATH` for its body, or `--event-file`
with a GitHub pull-request event containing title/body. The updater also reads
the PR branch's commits. One PR gets the largest applicable increment: features
are minor; fixes and every other change (including chores, docs, tests, CI, and
direct/transitive dependencies) are patch. `!`, `BREAKING CHANGE:`, or
`BREAKING-CHANGE:` is major from 1.0 onward and minor before 1.0. A dependency's
own major number does not establish a breaking change in this project.

`.version-policy.json` lists version units, paths, and synchronized files. Changes
outside all unit paths affect every unit, except configured `exclude_paths`.
Root units use `**`. Lockfiles retain their resolved dependencies. Updating again
uses the base version, so it does not accumulate bumps. Update your branch from
current main before merging; the required check rejects a stale base.

Prereleases advance the base and reset the counter: `0.1.0-rc.5` becomes
`0.1.1-rc.1` for a patch. Python metadata serializes the same version as
`0.1.1rc1`. Date prereleases retain that format and refresh the date; `--date`
accepts YYYY-MM-DD for reproducible runs. CI accepts a valid date between the
previous version's date and today, so an overnight review does not invalidate it.

Explicit release promotion uses the exact title `chore(release): promote version`
and changes only configured version values: `0.1.1-rc.1` becomes `0.1.1`, without
another base increment. Existing release review and publication authority still
apply. The updater never creates a tag, release, publication, or deployment.

For a new versioned component, run the toolkit bootstrap again or run
`python3 scripts/mw-version.py enroll --repo PATH --unit COMPONENT_PATH` from an
installed copy. Review the generated configuration and add any runtime/plugin
mirrors. Captured templates and vendored packages are not owned version units.
'''
POINTER = "\n## Version updates\n\nFor a versioned change PR, follow [the version policy](docs/version-policy.md) and run the repository-local updater before review and after updating the branch from main. Keep commit and PR titles in Conventional Commits format.\n"


class PolicyError(ValueError):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise PolicyError(result.stderr.strip() or "git command failed")
    return result.stdout


def safe_path(root: Path, name: str) -> Path:
    path = root / name
    if not name or Path(name).is_absolute() or ".." in Path(name).parts or not path.resolve().is_relative_to(root.resolve()):
        raise PolicyError(f"unsafe repository path: {name}")
    return path


def parse_version(value: str, fmt: str = "semver", legacy: bool = False) -> tuple:
    if fmt not in {"semver", "pep440"}:
        raise PolicyError(f"unsupported version format: {fmt}")
    if fmt == "pep440":
        value = re.sub(r"^(\d+\.\d+\.\d+)(a|b|rc)(\d+)$", lambda m: m[1] + "-" + {"a": "alpha", "b": "beta", "rc": "rc"}[m[2]] + "." + m[3], value)
    if legacy and re.fullmatch(r"\d+\.\d+\.\d+\.0", value):
        value = value.rsplit(".", 1)[0]
    match = SEMVER.fullmatch(value)
    if not match:
        raise PolicyError(f"invalid version: {value}")
    major, minor, patch, pre, build = match.groups()
    for identifiers in (pre, build):
        if identifiers is not None and any(not p for p in identifiers.split(".")):
            raise PolicyError(f"empty version identifier: {value}")
    if pre and any(p.isdigit() and len(p) > 1 and p.startswith("0") for p in pre.split(".")):
        raise PolicyError(f"leading zero in prerelease: {value}")
    return int(major), int(minor), int(patch), pre, build


def serialize(version: tuple, fmt: str = "semver") -> str:
    major, minor, patch, pre, build = version
    value = f"{major}.{minor}.{patch}"
    if fmt == "pep440":
        if pre:
            m = re.fullmatch(r"(alpha|beta|rc)\.(\d+)", pre)
            if not m:
                raise PolicyError(f"unsupported Python prerelease: {pre}")
            value += {"alpha": "a", "beta": "b", "rc": "rc"}[m[1]] + m[2]
        if build:
            raise PolicyError("build metadata is not supported in Python project versions")
    else:
        value += ("-" + pre if pre else "") + ("+" + build if build else "")
    return value


def intent(title: str, body: str, commits: list[str]) -> int:
    if not SUBJECT.fullmatch(title):
        raise PolicyError("PR title must use Conventional Commits: type(scope)!: description")
    level = 1
    for message in [title + "\n" + body, *commits]:
        subject = message.splitlines()[0] if message.splitlines() else ""
        match = SUBJECT.fullmatch(subject)
        if BREAKING.search(message) or (match and match[2]):
            level = 3
        elif match and match[1] == "feat":
            level = max(level, 2)
    return level


def date_pre(pre: str | None) -> dt.date | None:
    if pre and re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}", pre):
        try:
            return dt.date(*map(int, pre.split(".")))
        except ValueError as e:
            raise PolicyError(f"invalid prerelease date: {pre}") from e
    return None


def advance(version: tuple, level: int, date: dt.date) -> tuple:
    major, minor, patch, pre, _ = version
    if level == 3 and major == 0:
        level = 2
    if level == 3:
        major, minor, patch = major + 1, 0, 0
    elif level == 2:
        minor, patch = minor + 1, 0
    else:
        patch += 1
    if date_pre(pre):
        pre = f"{date.year}.{date.month}.{date.day}"
    elif pre:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*(?:\.\d+)?", pre):
            raise PolicyError(f"unsupported prerelease channel: {pre}")
        pre = pre.split(".")[0] + ".1"
    return major, minor, patch, pre, None


def json_target(data, key):
    parent = data
    parts = key or ["version"]
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    return parent, int(parts[-1]) if isinstance(parent, list) else parts[-1]


def read_values(text: str, spec: dict) -> list[str]:
    kind = spec["kind"]
    if kind == "json":
        parent, key = json_target(json.loads(text), spec.get("key"))
        return [parent[key]]
    if kind == "npm-lock":
        data = json.loads(text)
        values = [data["version"]]
        if "packages" in data:
            values.append(data["packages"][""]["version"])
        return values
    if kind == "toml":
        return [tomllib.loads(text)["project"]["version"]]
    if kind == "uv-lock":
        values = [p["version"] for p in tomllib.loads(text)["package"] if p["name"] == spec["name"]]
        if len(values) != 1:
            raise PolicyError("uv lock must contain exactly one owned package")
        return values
    if kind == "python":
        values = re.findall(r'^[ \t]*__version__\s*=\s*[\'"]([^\'"]+)[\'"]', text, re.MULTILINE)
        if len(values) != 1:
            raise PolicyError("expected one __version__ assignment")
        return values
    if kind == "text":
        return [text.strip()]
    raise PolicyError(f"unsupported version file kind: {kind}")


def render(text: str, spec: dict, value: str) -> str:
    kind = spec["kind"]
    if kind in ("json", "npm-lock"):
        data = json.loads(text)
        if kind == "json":
            parent, key = json_target(data, spec.get("key"))
            parent[key] = value
        else:
            data["version"] = value
            if "packages" in data:
                data["packages"][""]["version"] = value
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if kind == "text":
        return value + "\n"
    if kind == "python":
        pattern = r'^([ \t]*__version__\s*=\s*)([\'"])([^\'"]+)([\'"])'
        return re.sub(pattern, lambda m: m[1] + m[2] + value + m[4], text, count=1, flags=re.MULTILINE)
    section = "project" if kind == "toml" else "[package]"
    pattern = r"(?ms)^\[" + re.escape(section) + r"\][^\n]*\n.*?(?=^\[|\Z)"
    count = 0
    def replace(block):
        nonlocal count
        content = block[0]
        if kind == "uv-lock" and tomllib.loads(content)["package"][0]["name"] != spec["name"]:
            return content
        new, n = re.subn(r'^(version\s*=\s*)([\'"])([^\'"]+)([\'"])', lambda m: m[1] + m[2] + value + m[4], content, count=1, flags=re.MULTILINE)
        count += n
        return new
    output = re.sub(pattern, replace, text)
    if count != 1:
        raise PolicyError(f"could not update exactly one version in {spec['path']}")
    return output


def evaluate(root: Path, args) -> list[tuple[Path, str]]:
    config = json.loads(safe_path(root, args.config).read_text())
    if config.get("schema_version") != 1 or not isinstance(config.get("units"), list):
        raise PolicyError("expected schema_version 1 and units list")
    base = args.base
    if not base:
        base = git(root, "symbolic-ref", "refs/remotes/origin/HEAD").strip()
    git(root, "rev-parse", "--verify", base + "^{commit}")
    # Branch ancestry plus strict required status checks prevent concurrent stale bumps.
    try:
        git(root, "merge-base", "--is-ancestor", base, "HEAD")
    except PolicyError as e:
        raise PolicyError("branch is behind current base; update the branch and rerun the updater") from e
    existing = subprocess.run(["git", "-C", str(root), "show", f"{base}:{args.config}"], capture_output=True, text=True)
    if existing.returncode == 0:
        prior = json.loads(existing.stdout)
        head_units = {u["name"]: u for u in config["units"]}
        for unit in prior["units"]:
            candidate = head_units.get(unit["name"])
            if not candidate or not set(unit["paths"]).issubset(candidate["paths"]) or any(f not in candidate["files"] for f in unit["files"]):
                raise PolicyError("existing version units, paths, and mirrors cannot be removed from a change PR")
        if not set(config.get("exclude_paths", [])).issubset(prior.get("exclude_paths", [])):
            raise PolicyError("a change PR cannot add exclusions that bypass existing version checks")
    event = json.loads(Path(args.event_file).read_text()) if args.event_file else {}
    pr = event.get("pull_request", {})
    title = args.title if args.title is not None else pr.get("title", "")
    body = Path(args.body_file).read_text() if args.body_file else pr.get("body") or ""
    commits = git(root, "log", "--format=%B%x00", base + "..HEAD").split("\0")
    level = intent(title, body, [c.strip() for c in commits if c.strip()])
    promote = title == "chore(release): promote version"
    raw_changes = set(git(root, "diff", "--name-only", "--no-renames", base).splitlines())
    raw_changes.update(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    changes = {p for p in raw_changes if not any(fnmatch.fnmatchcase(p, pat) for pat in config.get("exclude_paths", []))}
    units = config["units"]
    names = [u["name"] for u in units]
    if len(set(names)) != len(names):
        raise PolicyError("version unit names must be unique")
    if not units:
        raise PolicyError("version policy must contain at least one owned unit")
    all_patterns = [p for u in units for p in u["paths"]]
    shared = any(not any(fnmatch.fnmatchcase(p, pat) for pat in all_patterns) for p in changes)
    today = dt.datetime.now(ZoneInfo("America/Toronto")).date()
    selected_date = dt.date.fromisoformat(args.date) if args.date else today
    if selected_date > today:
        raise PolicyError("version date cannot be in the future")
    writes = []
    errors = []
    owned_files = set()
    promoted = False
    for unit in units:
        affected = shared or any(fnmatch.fnmatchcase(p, pat) for p in changes for pat in unit["paths"])
        files = unit["files"]
        if not files:
            raise PolicyError("version unit needs an authoritative file")
        contents = []
        for spec in files:
            path = safe_path(root, spec["path"])
            if spec["path"] in owned_files:
                raise PolicyError("a version file belongs to multiple units")
            owned_files.add(spec["path"])
            contents.append((path, path.read_text(), spec))
        first = files[0]
        result = subprocess.run(["git", "-C", str(root), "show", f"{base}:{first['path']}"], capture_output=True, text=True)
        if result.returncode:
            # A newly introduced unit has no older version to increment.
            baseline = parse_version(read_values(contents[0][1], first)[0], first.get("format", "semver"))
            target = baseline
        else:
            baseline = parse_version(read_values(result.stdout, first)[0], first.get("format", "semver"), legacy=True)
            target = baseline
            if promote and not raw_changes:
                affected = bool(baseline[3])
            if affected:
                if promote:
                    if not baseline[3]:
                        raise PolicyError("promotion requires a prerelease baseline")
                    target = (*baseline[:3], None, None)
                    promoted = True
                else:
                    bump_date = selected_date
                    old_date = date_pre(baseline[3])
                    if old_date:
                        if args.command == "check" and not args.date:
                            candidate = parse_version(read_values(contents[0][1], first)[0], first.get("format", "semver"))
                            bump_date = date_pre(candidate[3])
                            if not bump_date:
                                raise PolicyError("date prerelease channel must be retained")
                        if not old_date <= bump_date <= today:
                            raise PolicyError("date prerelease must be between its previous date and today")
                    target = advance(baseline, level, bump_date)
        for path, content, spec in contents:
            expected = serialize(target, spec.get("format", "semver"))
            values = read_values(content, spec)
            if any(v != expected for v in values):
                errors.append(f"{spec['path']}: expected {expected}, found {', '.join(values)}")
            if promote and spec["path"] in changes:
                old_content = git(root, "show", f"{base}:{spec['path']}")
                if render(content, spec, expected) != render(old_content, spec, expected):
                    raise PolicyError(f"promotion changes more than the version: {spec['path']}")
            new = render(content, spec, expected)
            if content != new:
                writes.append((path, new))
        print(f"{unit['name']}: {serialize(baseline)} -> {serialize(target)}" + (" (unchanged component)" if not affected else ""))
    if promote and raw_changes - owned_files:
        raise PolicyError("release promotion may change configured version values only")
    if promote and not promoted:
        raise PolicyError("promotion requires an existing affected prerelease")
    if args.command == "check" and errors:
        raise PolicyError("\n".join(errors))
    return writes


def discover(root: Path, prefix: str) -> dict | None:
    directory = safe_path(root, prefix)
    rel = lambda p: str(p.relative_to(root))
    files = []
    if (directory / "package.json").exists() and "version" in json.loads((directory / "package.json").read_text()):
        files.append({"path": rel(directory / "package.json"), "kind": "json"})
        if (directory / "package-lock.json").exists():
            files.append({"path": rel(directory / "package-lock.json"), "kind": "npm-lock"})
    elif (directory / "pyproject.toml").exists():
        data = tomllib.loads((directory / "pyproject.toml").read_text()).get("project", {})
        if "version" in data:
            files.append({"path": rel(directory / "pyproject.toml"), "kind": "toml", "format": "pep440"})
            if (directory / "uv.lock").exists():
                files.append({"path": rel(directory / "uv.lock"), "kind": "uv-lock", "format": "pep440", "name": data["name"]})
    elif (directory / "VERSION").exists():
        files.append({"path": rel(directory / "VERSION"), "kind": "text"})
    return {"name": "repo" if prefix == "." else prefix.rstrip("/"), "paths": ["**" if prefix == "." else prefix.rstrip("/") + "/**"], "files": files} if files else None


def enroll(root: Path, args) -> None:
    root = root.resolve()
    config_path = safe_path(root, args.config)
    if config_path.exists():
        config = json.loads(config_path.read_text())
        for prefix in args.unit or []:
            unit = discover(root, prefix)
            if unit and not any(u["name"] == unit["name"] for u in config["units"]):
                config["units"].append(unit)
    else:
        units = [u for p in (args.unit or ["."]) if (u := discover(root, p))]
        if not units:
            print("No owned version found; repository remains unversioned.")
            return
        config = {"schema_version": 1, "units": units}
    branch = git(root, "branch", "--show-current").strip()
    default = subprocess.run(["git", "-C", str(root), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], capture_output=True, text=True).stdout.strip().split("/")[-1]
    if branch in {default, "main", "master"} or not branch:
        raise PolicyError("enroll from a dedicated feature branch/worktree")
    script = safe_path(root, "scripts/mw-version.py")
    workflow = safe_path(root, ".github/workflows/version-policy.yml")
    docs = safe_path(root, "docs/version-policy.md")
    for path, content in [(script, Path(__file__).read_text()), (workflow, WORKFLOW), (docs, GUIDANCE)]:
        if path.exists() and path.read_text() != content:
            raise PolicyError(f"existing {path.relative_to(root)} differs; review rather than overwrite")
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    for path, content in [(script, Path(__file__).read_text()), (workflow, WORKFLOW), (docs, GUIDANCE)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    agents = safe_path(root, "AGENTS.md")
    if agents.exists() and "docs/version-policy.md" not in agents.read_text():
        agents.write_text(agents.read_text().rstrip() + "\n" + POINTER)
    print("Installed repository-local updater, configuration, guidance, and PR check.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["update", "check", "enroll"])
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config", default=CONFIG)
    parser.add_argument("--base", help="current default-branch ref; defaults to origin/HEAD")
    parser.add_argument("--title")
    parser.add_argument("--body-file")
    parser.add_argument("--event-file", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--date", help="YYYY-MM-DD for date prereleases")
    parser.add_argument("--unit", action="append", help="owned component directory to enroll; default: root")
    args = parser.parse_args(argv)
    try:
        root = Path(args.repo).resolve()
        if args.command == "enroll":
            enroll(root, args)
        else:
            writes = evaluate(root, args)
            if args.command == "update":
                for path, content in writes:
                    path.write_text(content)
                print(f"Updated {len(writes)} version file(s).")
            else:
                print("Version policy passed.")
        return 0
    except (PolicyError, OSError, ValueError, KeyError, TypeError) as e:
        print(f"Version policy failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

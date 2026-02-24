"""FAVA Trails CLI — human-facing complement to the MCP server."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

from .config import get_data_repo_root, get_trails_dir, sanitize_scope_path


# ─── .env helpers ────────────────────────────────────────────────────────────


def _read_env_file(env_path: Path) -> list[str]:
    """Read .env file lines, returning empty list if file doesn't exist."""
    if not env_path.exists():
        return []
    return env_path.read_text().splitlines(keepends=True)


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    """Set key=value in .env file.

    Preserves all existing lines (including comments and blanks).
    If the key exists (including duplicates), replaces the last occurrence
    and removes earlier duplicates. If missing, appends.
    """
    lines = _read_env_file(env_path)
    prefix = f"{key}="
    new_line = f"{key}={value}\n"

    # Find all indices where this key appears
    key_indices = [i for i, line in enumerate(lines) if line.startswith(prefix)]

    if not key_indices:
        # Key not present — append (ensure file ends with newline first)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)
    else:
        # Replace last occurrence, remove earlier duplicates
        last_idx = key_indices[-1]
        lines[last_idx] = new_line
        for idx in reversed(key_indices[:-1]):
            lines.pop(idx)

    env_path.write_text("".join(lines))


def _read_env_value(env_path: Path, key: str) -> str | None:
    """Read a key's value from .env file. Returns None if not present."""
    prefix = f"{key}="
    for line in _read_env_file(env_path):
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return None


def _is_env_gitignored(project_dir: Path) -> bool:
    """Return True if .env is covered by .gitignore in project_dir."""
    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        return False
    for line in gitignore.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Match .env and patterns like *.env
            if stripped in (".env", "*.env", ".env*"):
                return True
    return False


# ─── Project scope helpers (.fava-trail.yaml) ────────────────────────────────


def _read_project_yaml_scope(project_dir: Path) -> str | None:
    """Read scope from .fava-trail.yaml in project_dir."""
    yaml_path = project_dir / ".fava-trail.yaml"
    if not yaml_path.exists():
        return None
    data = yaml.safe_load(yaml_path.read_text()) or {}
    return data.get("scope")


def _write_project_yaml(project_dir: Path, scope: str) -> None:
    """Write (or overwrite) .fava-trail.yaml with the given scope."""
    yaml_path = project_dir / ".fava-trail.yaml"
    existing: dict = {}
    if yaml_path.exists():
        existing = yaml.safe_load(yaml_path.read_text()) or {}
    existing["scope"] = scope
    yaml_path.write_text(yaml.dump(existing, default_flow_style=False, sort_keys=False))


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a project directory for FAVA Trails."""
    project_dir = Path.cwd()
    env_path = project_dir / ".env"

    # 1. Determine scope
    scope: str | None = getattr(args, "scope", None)
    if scope:
        # --scope flag provided: validate and use directly
        try:
            scope = sanitize_scope_path(scope)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        # Write .fava-trail.yaml if missing or scope differs
        existing_yaml_scope = _read_project_yaml_scope(project_dir)
        if existing_yaml_scope != scope:
            _write_project_yaml(project_dir, scope)
            if existing_yaml_scope is None:
                print(f"Created .fava-trail.yaml with scope: {scope}")
            else:
                print(f"Updated .fava-trail.yaml scope: {existing_yaml_scope} -> {scope}")
    else:
        # No --scope flag: check .fava-trail.yaml first
        yaml_scope = _read_project_yaml_scope(project_dir)
        if yaml_scope:
            scope = yaml_scope
        else:
            # Interactive prompt
            try:
                scope = input("Enter scope (e.g. mw/eng/my-project): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.", file=sys.stderr)
                return 1
            if not scope:
                print("Error: scope cannot be empty.", file=sys.stderr)
                return 1
            try:
                scope = sanitize_scope_path(scope)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            _write_project_yaml(project_dir, scope)
            print(f"Created .fava-trail.yaml with scope: {scope}")

    # 2. Update .env
    existing_env_scope = _read_env_value(env_path, "FAVA_TRAIL_SCOPE")
    if existing_env_scope:
        print(f"Scope already set in .env: {existing_env_scope}")
        if existing_env_scope != scope:
            print(f"  (Note: .fava-trail.yaml has scope '{scope}' — run `fava-trails scope set {scope}` to sync)")
    else:
        _update_env_file(env_path, "FAVA_TRAIL_SCOPE", scope)
        print(f"Wrote FAVA_TRAIL_SCOPE={scope} to .env")

    # 3. Warn if .env is not gitignored
    if not _is_env_gitignored(project_dir):
        print("Warning: .env is not in .gitignore — add it to avoid committing local config.")

    # 4. Validate data repo
    try:
        data_repo = get_data_repo_root()
        if not data_repo.exists() or not (data_repo / "config.yaml").exists():
            print(f"Data repo not configured or not found at {data_repo}.")
            print(f"  Run: fava-trails bootstrap <path>")
        else:
            print(f"Data repo:    {data_repo}")
    except Exception:
        print("Data repo not configured. Run: fava-trails bootstrap <path>")

    print(f"Scope:        {scope}")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Bootstrap a new FAVA Trails data repository."""
    target = Path(args.path).expanduser().resolve()

    # Validate JJ is available
    import shutil
    jj_bin = shutil.which("jj")
    if not jj_bin:
        jj_bin = str(Path.home() / ".local" / "bin" / "jj")
        if not Path(jj_bin).exists():
            print("Error: jj not found. Install with: bash scripts/install-jj.sh", file=sys.stderr)
            return 1

    # Create directory
    target.mkdir(parents=True, exist_ok=True)

    # Check if already bootstrapped
    if (target / ".jj").exists():
        print(f"Error: {target} already has a .jj/ directory. Already bootstrapped.", file=sys.stderr)
        return 1

    remote_url: str | None = getattr(args, "remote", None)

    # Create config.yaml
    config_data = {
        "trails_dir": "trails",
        "remote_url": remote_url,
        "push_strategy": "manual",
    }
    config_path = target / "config.yaml"
    config_path.write_text(yaml.dump(config_data, default_flow_style=False, sort_keys=False))
    print(f"[1/4] Created config.yaml")

    # Create .gitignore
    gitignore_content = ".jj/\n__pycache__/\n*.pyc\n.venv/\n"
    (target / ".gitignore").write_text(gitignore_content)
    print(f"[2/4] Created .gitignore")

    # Create trails/ directory
    (target / "trails").mkdir(exist_ok=True)
    print(f"[3/4] Created trails/")

    # Initialize JJ colocated repo
    result = subprocess.run(
        [jj_bin, "git", "init", "--colocate"],
        cwd=str(target),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: jj git init --colocate failed:\n{result.stderr}", file=sys.stderr)
        print(f"  Partial init may have occurred. Clean up manually: rm -rf {target}/.jj", file=sys.stderr)
        return 1
    print(f"[4/4] Initialized JJ colocated repo")

    print(f"\nData repo ready: {target}")
    print(f"\nSet this in your MCP server config:")
    print(f"  FAVA_TRAILS_DATA_REPO={target}")
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    """Show current scope and resolution source."""
    project_dir = Path.cwd()
    env_path = project_dir / ".env"

    env_scope = _read_env_value(env_path, "FAVA_TRAIL_SCOPE")
    if env_scope:
        print(f"Scope:  {env_scope}")
        print(f"Source: .env (FAVA_TRAIL_SCOPE)")
        return 0

    yaml_scope = _read_project_yaml_scope(project_dir)
    if yaml_scope:
        print(f"Scope:  {yaml_scope}")
        print(f"Source: .fava-trail.yaml")
        return 0

    print("Scope:  (not configured)")
    print("Source: none")
    print("  Run: fava-trails init")
    return 1


def cmd_scope_set(args: argparse.Namespace) -> int:
    """Set scope in both .fava-trail.yaml and .env."""
    project_dir = Path.cwd()
    env_path = project_dir / ".env"

    try:
        scope = sanitize_scope_path(args.scope_value)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    _write_project_yaml(project_dir, scope)
    print(f"Updated .fava-trail.yaml scope: {scope}")

    _update_env_file(env_path, "FAVA_TRAIL_SCOPE", scope)
    print(f"Updated .env FAVA_TRAIL_SCOPE={scope}")

    trails_dir = "trails"  # default; could read from config
    print(
        f"Note: The trail directory will be created when the first thought is saved. "
        f"Trust gate prompt is inherited from parent scope. "
        f"To customize, create `{trails_dir}/{scope}/trust-gate-prompt.md`"
    )
    return 0


def cmd_scope_list(args: argparse.Namespace) -> int:
    """List all scopes in the data repo."""
    trails_dir = get_trails_dir()

    if not trails_dir.exists():
        print(f"No trails directory found at {trails_dir}.", file=sys.stderr)
        print("  Run: fava-trails bootstrap <path>", file=sys.stderr)
        return 1

    scopes: list[str] = []
    for thoughts_dir in sorted(trails_dir.rglob("thoughts")):
        if thoughts_dir.is_dir():
            scope_dir = thoughts_dir.parent
            try:
                scope_name = str(scope_dir.relative_to(trails_dir))
                scopes.append(scope_name)
            except ValueError:
                continue

    scopes = sorted(set(scopes))
    if not scopes:
        print("No scopes found.")
        return 0

    for scope in scopes:
        print(scope)
    return 0


# ─── Argument parser ──────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    try:
        from importlib.metadata import version
        _version = version("fava-trails")
    except Exception:
        _version = "unknown"

    parser = argparse.ArgumentParser(
        prog="fava-trails",
        description="FAVA Trails — human-facing CLI for setup and scope management.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a project directory for FAVA Trails")
    p_init.add_argument(
        "--scope",
        metavar="SCOPE",
        default=None,
        help="Scope path (e.g. mw/eng/my-project). Skips interactive prompt.",
    )
    p_init.set_defaults(func=cmd_init)

    # bootstrap
    p_bootstrap = subparsers.add_parser("bootstrap", help="Bootstrap a new FAVA Trails data repository")
    p_bootstrap.add_argument("path", help="Path to create the data repository")
    p_bootstrap.add_argument("--remote", metavar="URL", default=None, help="Git remote URL (optional)")
    p_bootstrap.set_defaults(func=cmd_bootstrap)

    # scope
    p_scope = subparsers.add_parser("scope", help="Show or manage the current scope")
    scope_sub = p_scope.add_subparsers(dest="scope_command", metavar="<subcommand>")

    p_scope_set = scope_sub.add_parser("set", help="Set the current scope")
    p_scope_set.add_argument("scope_value", metavar="SCOPE", help="Scope path to set")
    p_scope_set.set_defaults(func=cmd_scope_set)

    p_scope_list = scope_sub.add_parser("list", help="List all scopes in the data repo")
    p_scope_list.set_defaults(func=cmd_scope_list)

    p_scope.set_defaults(func=cmd_scope)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # For 'scope' with a subcommand, dispatch to subcommand func
    if args.command == "scope" and getattr(args, "scope_command", None):
        func = args.func
    elif hasattr(args, "func"):
        func = args.func
    else:
        parser.print_help()
        sys.exit(0)

    sys.exit(func(args))


if __name__ == "__main__":
    main()

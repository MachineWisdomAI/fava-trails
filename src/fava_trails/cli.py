"""FAVA Trails CLI — human-facing complement to the MCP server."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from importlib import resources as importlib_resources

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

    def _line_matches_key(line: str) -> bool:
        """Match both `KEY=value` and `export KEY=value` forms."""
        s = line.strip()
        if s.startswith("export "):
            s = s[len("export "):].lstrip()
        return s.startswith(prefix)

    # Find all indices where this key appears
    key_indices = [i for i, line in enumerate(lines) if _line_matches_key(line)]

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

    # Atomic write: write to temp file then replace, preventing corruption on interruption
    # Use with_name (not with_suffix) so dotfiles like .env get .env.tmp, not just .tmp
    tmp = env_path.with_name(env_path.name + ".tmp")
    tmp.write_text("".join(lines))
    tmp.replace(env_path)


def _read_env_value(env_path: Path, key: str) -> str | None:
    """Read a key's value from .env file. Returns None if not present.

    Handles both `KEY=value` and `export KEY=value` formats.
    """
    prefix = f"{key}="
    for line in _read_env_file(env_path):
        stripped = line.strip()
        # Handle optional `export ` prefix
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
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


# ─── Project scope helpers (.fava-trails.yaml) ────────────────────────────────


def _read_project_yaml_scope(project_dir: Path) -> str | None:
    """Read scope from .fava-trails.yaml in project_dir. Returns None if missing or invalid."""
    yaml_path = project_dir / ".fava-trails.yaml"
    if not yaml_path.exists():
        return None
    try:
        data = yaml.safe_load(yaml_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return None
    return data.get("scope")


def _write_project_yaml(project_dir: Path, scope: str) -> None:
    """Write (or overwrite) .fava-trails.yaml with the given scope."""
    yaml_path = project_dir / ".fava-trails.yaml"
    existing: dict = {}
    if yaml_path.exists():
        try:
            existing = yaml.safe_load(yaml_path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            existing = {}
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
        # Write .fava-trails.yaml if missing or scope differs
        existing_yaml_scope = _read_project_yaml_scope(project_dir)
        if existing_yaml_scope != scope:
            _write_project_yaml(project_dir, scope)
            if existing_yaml_scope is None:
                print(f"Created .fava-trails.yaml with scope: {scope}")
            else:
                print(f"Updated .fava-trails.yaml scope: {existing_yaml_scope} -> {scope}")
    else:
        # No --scope flag: check .fava-trails.yaml first
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
            print(f"Created .fava-trails.yaml with scope: {scope}")

    # 2. Update .env
    existing_env_scope = _read_env_value(env_path, "FAVA_TRAILS_SCOPE")
    if existing_env_scope:
        print(f"Scope already set in .env: {existing_env_scope}")
        if existing_env_scope != scope:
            print(f"  (Note: .fava-trails.yaml has scope '{scope}' — run `fava-trails scope set {scope}` to sync)")
    else:
        _update_env_file(env_path, "FAVA_TRAILS_SCOPE", scope)
        print(f"Wrote FAVA_TRAILS_SCOPE={scope} to .env")

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
    except (OSError, ValueError) as e:
        print(f"Data repo not configured ({e}). Run: fava-trails bootstrap <path>")

    print(f"Scope:        {scope}")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Bootstrap a new FAVA Trails data repository."""
    target = Path(args.path).expanduser().resolve()

    # Validate JJ is available
    jj_bin = shutil.which("jj")
    if not jj_bin:
        jj_bin = str(Path.home() / ".local" / "bin" / "jj")
        if not Path(jj_bin).exists():
            print("Error: jj not found. Install with: fava-trails install-jj\n  Or manually: https://jj-vcs.github.io/jj/", file=sys.stderr)
            return 1

    # Create directory
    target.mkdir(parents=True, exist_ok=True)

    # Check if already bootstrapped
    if (target / ".jj").exists():
        print(f"Error: {target} already has a .jj/ directory. Already bootstrapped.", file=sys.stderr)
        return 1

    # Refuse to overwrite existing config files to prevent data loss
    if (target / "config.yaml").exists():
        print(f"Error: {target}/config.yaml already exists. Refusing to overwrite.", file=sys.stderr)
        return 1
    if (target / ".gitignore").exists():
        print(f"Error: {target}/.gitignore already exists. Refusing to overwrite.", file=sys.stderr)
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
    print("[1/6] Created config.yaml")

    # Create .gitignore
    gitignore_content = ".jj/\n__pycache__/\n*.pyc\n.venv/\n"
    (target / ".gitignore").write_text(gitignore_content)
    print("[2/6] Created .gitignore")

    # Create trails/ directory
    (target / "trails").mkdir(exist_ok=True)
    print("[3/6] Created trails/")

    # Copy template files (README.md, CLAUDE.md, trust-gate-prompt.md)
    template_pkg = importlib_resources.files("fava_trails") / "data_repo_template"
    for name, dest in [
        ("README.md", target / "README.md"),
        ("CLAUDE.md", target / "CLAUDE.md"),
        ("trust-gate-prompt.md", target / "trails" / "trust-gate-prompt.md"),
    ]:
        src = template_pkg / name
        dest.write_text(src.read_text())
    print("[4/6] Created README.md, CLAUDE.md, trails/trust-gate-prompt.md")

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
    print("[5/6] Initialized JJ colocated repo")

    # Set default description to prevent undescribed commits from external JJ usage
    result = subprocess.run(
        [jj_bin, "config", "set", "--repo", "ui.default-description", "(auto-described)"],
        cwd=str(target), check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Warning: failed to set ui.default-description: {result.stderr}", file=sys.stderr)

    # Initial commit: describe and create new change
    subprocess.run(
        [jj_bin, "describe", "-m", "Bootstrap FAVA Trails data repository"],
        cwd=str(target), check=False, capture_output=True, text=True,
    )
    subprocess.run(
        [jj_bin, "new", "-m", "(new change)"],
        cwd=str(target), check=False, capture_output=True, text=True,
    )
    subprocess.run(
        [jj_bin, "bookmark", "set", "main", "-r", "@-"],
        cwd=str(target), check=False, capture_output=True, text=True,
    )
    print("[6/6] Created initial commit")

    print(f"\nData repo ready: {target}")
    print(f"\nSet this in your MCP server config:")
    print(f"  FAVA_TRAILS_DATA_REPO={target}")
    if remote_url:
        print(f"\nPush to remote:")
        print(f"  cd {target} && jj git push -b main")
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    """Show current scope and resolution source."""
    project_dir = Path.cwd()
    env_path = project_dir / ".env"

    env_scope = _read_env_value(env_path, "FAVA_TRAILS_SCOPE")
    if env_scope:
        print(f"Scope:  {env_scope}")
        print(f"Source: .env (FAVA_TRAILS_SCOPE)")
        return 0

    yaml_scope = _read_project_yaml_scope(project_dir)
    if yaml_scope:
        print(f"Scope:  {yaml_scope}")
        print(f"Source: .fava-trails.yaml")
        return 0

    print("Scope:  (not configured)")
    print("Source: none")
    print("  Run: fava-trails init")
    return 1


def cmd_scope_set(args: argparse.Namespace) -> int:
    """Set scope in both .fava-trails.yaml and .env."""
    project_dir = Path.cwd()
    env_path = project_dir / ".env"

    try:
        scope = sanitize_scope_path(args.scope_value)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    _write_project_yaml(project_dir, scope)
    print(f"Updated .fava-trails.yaml scope: {scope}")

    _update_env_file(env_path, "FAVA_TRAILS_SCOPE", scope)
    print(f"Updated .env FAVA_TRAILS_SCOPE={scope}")

    trails_dir = "trails"  # default; could read from config
    print(
        f"Note: The trail directory will be created when the first thought is saved. "
        f"Trust gate prompt is inherited from parent scope. "
        f"To customize, create `{trails_dir}/{scope}/trust-gate-prompt.md`"
    )
    return 0


def cmd_scope_list(args: argparse.Namespace) -> int:
    """List all scopes in the data repo."""
    try:
        trails_dir = get_trails_dir()
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        print("  Run: fava-trails bootstrap <path>", file=sys.stderr)
        return 1

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


# ─── Doctor ───────────────────────────────────────────────────────────────────


def cmd_doctor(args: argparse.Namespace) -> int:
    """Health check: JJ, data repo, scope. Exits 0 if all pass, 1 if any fail."""
    any_failed = False

    # Check 1: JJ installed?
    jj_bin = shutil.which("jj")
    if not jj_bin:
        jj_bin = str(Path.home() / ".local" / "bin" / "jj")
        if not Path(jj_bin).exists():
            jj_bin = None

    if jj_bin:
        try:
            result = subprocess.run(
                [jj_bin, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"JJ:           ERROR (failed to run jj --version: {e})")
            any_failed = True
        else:
            if result.returncode == 0:
                version_str = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown version"
                print(f"JJ:           installed ({version_str})")
            else:
                print("JJ:           ERROR (jj --version failed)")
                any_failed = True
    else:
        print("JJ:           NOT FOUND")
        print("  Fix: fava-trails install-jj")
        any_failed = True

    # Check 2: Data repo valid?
    try:
        data_repo = get_data_repo_root()
        if not data_repo.exists():
            print(f"Data repo:    NOT FOUND (expected: {data_repo})")
            print(f"  Fix: fava-trails bootstrap <path>")
            any_failed = True
        elif not (data_repo / "config.yaml").exists():
            print(f"Data repo:    INVALID — missing config.yaml at {data_repo}")
            print(f"  Fix: fava-trails bootstrap <path>")
            any_failed = True
        elif not (data_repo / "trails").exists():
            print(f"Data repo:    INVALID — missing trails/ at {data_repo}")
            print(f"  Fix: mkdir {data_repo / 'trails'}")
            any_failed = True
        else:
            print(f"Data repo:    {data_repo} (valid)")
    except (OSError, ValueError) as e:
        print(f"Data repo:    ERROR ({e})")
        any_failed = True

    # Check 3: Scope configured and valid?
    project_dir = Path.cwd()
    scope_value = _read_env_value(project_dir / ".env", "FAVA_TRAILS_SCOPE")
    scope_source = ".env"
    if not scope_value:
        scope_value = _read_project_yaml_scope(project_dir)
        scope_source = ".fava-trails.yaml"

    if scope_value:
        try:
            sanitize_scope_path(scope_value)
            print(f"Scope:        {scope_value} (from {scope_source})")
        except ValueError as e:
            print(f"Scope:        INVALID ({e}) (from {scope_source})")
            print("  Fix: fava-trails scope set <valid-scope>")
            any_failed = True
    else:
        print("Scope:        NOT CONFIGURED")
        print("  Fix: fava-trails init")
        any_failed = True

    return 1 if any_failed else 0


# ─── install-jj ───────────────────────────────────────────────────────────────

JJ_DEFAULT_VERSION = "0.28.0"
_JJ_INSTALL_DIR = Path.home() / ".local" / "bin"


def cmd_install_jj(args: argparse.Namespace) -> int:
    """Download and install the Jujutsu (JJ) binary."""
    version = getattr(args, "jj_version", None) or JJ_DEFAULT_VERSION

    # Platform detection first — Windows requires a different installer
    os_name = sys.platform  # "linux", "darwin", "win32"
    machine = platform.machine().lower()

    if os_name == "win32":
        print("Windows detected. Install JJ with:")
        print("  winget install Jujutsu.Jujutsu")
        print("Or manually from: https://jj-vcs.github.io/jj/")
        return 1

    # Check if JJ is already installed at the target version
    existing = shutil.which("jj") or str(_JJ_INSTALL_DIR / "jj")
    if Path(existing).exists():
        try:
            result = subprocess.run(
                [existing, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            installed_output = result.stdout.strip()
            if re.search(rf"jj {re.escape(version)}(\s|$)", installed_output):
                print(f"JJ already installed: {installed_output}")
                return 0
        except (OSError, subprocess.TimeoutExpired):
            pass

    if os_name == "linux":
        if machine in ("x86_64", "amd64"):
            suffix = "x86_64-unknown-linux-musl"
        elif machine in ("aarch64", "arm64"):
            suffix = "aarch64-unknown-linux-musl"
        else:
            print(f"Unsupported Linux architecture: {machine}", file=sys.stderr)
            print("Install manually from: https://jj-vcs.github.io/jj/", file=sys.stderr)
            return 1
    elif os_name == "darwin":
        if machine in ("x86_64", "amd64"):
            suffix = "x86_64-apple-darwin"
        elif machine in ("arm64", "aarch64"):
            suffix = "aarch64-apple-darwin"
        else:
            print(f"Unsupported macOS architecture: {machine}", file=sys.stderr)
            print("Install manually from: https://jj-vcs.github.io/jj/", file=sys.stderr)
            return 1
    else:
        print(f"Unsupported OS: {os_name}", file=sys.stderr)
        print("Install manually from: https://jj-vcs.github.io/jj/", file=sys.stderr)
        return 1

    url = f"https://github.com/jj-vcs/jj/releases/download/v{version}/jj-v{version}-{suffix}.tar.gz"
    print(f"Downloading JJ v{version} for {suffix}...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tarball = Path(tmpdir) / "jj.tar.gz"
        try:
            with urllib.request.urlopen(url, timeout=30) as r, open(tarball, "wb") as f:
                shutil.copyfileobj(r, f)
        except (urllib.error.URLError, OSError) as e:
            print(f"Error: download failed: {e}", file=sys.stderr)
            return 1

        with tarfile.open(tarball, "r:gz") as tf:
            # Find the jj binary member
            members = [m for m in tf.getmembers() if Path(m.name).name == "jj"]
            if not members:
                print("Error: jj binary not found in tarball", file=sys.stderr)
                return 1
            member = members[0]
            if not member.isfile():
                print("Error: jj entry in tarball is not a regular file", file=sys.stderr)
                return 1
            # Safe extraction: read via extractfile(), write manually (avoids path traversal)
            src_f = tf.extractfile(member)
            if src_f is None:
                print("Error: failed to read jj from tarball", file=sys.stderr)
                return 1
            extracted = Path(tmpdir) / "jj"
            with src_f, open(extracted, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)

        try:
            _JJ_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            dest = _JJ_INSTALL_DIR / "jj"
            shutil.copy2(extracted, dest)
            dest.chmod(0o755)
        except OSError as e:
            print(f"Error: failed to install JJ to {dest}: {e}", file=sys.stderr)
            return 1

    # Verify
    try:
        result = subprocess.run([str(dest), "--version"], capture_output=True, text=True, timeout=5)
        print(f"Installed: {result.stdout.strip()}")
    except Exception as e:
        print(f"Warning: install completed but verification failed: {e}", file=sys.stderr)

    # PATH check
    if not shutil.which("jj"):
        shell_rc = ".zshrc" if "zsh" in os.environ.get("SHELL", "") or sys.platform == "darwin" else ".bashrc"
        print(f"\nWarning: {_JJ_INSTALL_DIR} is not in your PATH.")
        print("Add it with:")
        print(f'  echo \'export PATH="$HOME/.local/bin:$PATH"\' >> ~/{shell_rc} && source ~/{shell_rc}')

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

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Check JJ, data repo, and scope configuration")
    p_doctor.set_defaults(func=cmd_doctor)

    # install-jj
    p_install_jj = subparsers.add_parser("install-jj", help="Download and install the Jujutsu (JJ) binary")
    p_install_jj.add_argument(
        "--version",
        dest="jj_version",
        default=None,
        metavar="VERSION",
        help=f"JJ version to install (default: {JJ_DEFAULT_VERSION})",
    )
    p_install_jj.set_defaults(func=cmd_install_jj)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        hints = []
        if not shutil.which("jj"):
            hints.append("  1. Install JJ:         fava-trails install-jj")
        data_repo = get_data_repo_root()
        if not data_repo.exists() or not (data_repo / "config.yaml").exists():
            hints.append(f"  {'1' if not hints else '2'}. Set up data repo:   fava-trails bootstrap <path>")
        if hints:
            print("\nQuick start:")
            print("\n".join(hints))
        sys.exit(0)

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

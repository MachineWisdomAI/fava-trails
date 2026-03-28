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
from importlib import resources as importlib_resources
from pathlib import Path

import yaml

from .config import get_data_repo_root, get_trails_dir, load_global_config, sanitize_scope_path, save_global_config
from .models import HookEntry, ThoughtRecord

# ─── JJ binary helper ─────────────────────────────────────────────────────────


def _find_jj_bin() -> str | None:
    """Find jj binary: PATH first, then ~/.local/bin/jj fallback. Returns None if not found."""
    jj = shutil.which("jj")
    if jj:
        return jj
    fallback = Path.home() / ".local" / "bin" / "jj"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    return None


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
            print("  Run: fava-trails bootstrap <path>")
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
    jj_bin = _find_jj_bin()
    if not jj_bin:
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
        ("AGENTS.md", target / "AGENTS.md"),
        ("trust-gate-prompt.md", target / "trails" / "trust-gate-prompt.md"),
    ]:
        src = template_pkg / name
        dest.write_text(src.read_text())
    print("[4/6] Created README.md, CLAUDE.md, AGENTS.md, trails/trust-gate-prompt.md")

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
    print("\nSet this in your MCP server config:")
    print(f"  FAVA_TRAILS_DATA_REPO={target}")
    if remote_url:
        print("\nPush to remote:")
        print(f"  cd {target} && jj git push -b main")
    print("\nAvailable integrations:")
    print("  fava-trails integrate codev    Set up codev artifact storage with quality gate")
    return 0


def cmd_clone(args: argparse.Namespace) -> int:
    """Clone an existing FAVA Trails data repository from a remote."""
    url = args.url
    target = Path(args.path).expanduser().resolve()

    # Validate JJ is available
    jj_bin = _find_jj_bin()
    if not jj_bin:
        print("Error: jj not found. Install with: fava-trails install-jj\n  Or manually: https://jj-vcs.github.io/jj/", file=sys.stderr)
        return 1

    # Check target doesn't already exist
    if target.exists():
        if target.is_file():
            print(f"Error: {target} exists and is a file.", file=sys.stderr)
            return 1
        if any(target.iterdir()):
            print(f"Error: {target} already exists and is not empty.", file=sys.stderr)
            return 1

    # Ensure parent directories exist for nested paths
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    # Clone with --colocate
    print(f"Cloning {url} into {target}...")
    result = subprocess.run(
        [jj_bin, "git", "clone", "--colocate", url, str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: jj git clone failed:\n{result.stderr}", file=sys.stderr)
        return 1
    print("[1/2] Cloned repository (colocated mode)")

    # Track main bookmark
    result = subprocess.run(
        [jj_bin, "bookmark", "track", "main@origin"],
        cwd=str(target),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("[2/2] Tracked main bookmark")
    else:
        lowered = result.stderr.lower()
        if "already tracking" in lowered or "already tracked" in lowered:
            print("[2/2] Bookmark main already tracked")
        else:
            print(f"Warning: bookmark tracking failed: {result.stderr}", file=sys.stderr)

    # Validate it looks like a data repo
    if not (target / "config.yaml").exists():
        print(f"\nWarning: {target} has no config.yaml — this may not be a FAVA Trails data repo.")
        print("  If this is a new repo, use `fava-trails bootstrap` instead.")

    print(f"\nData repo ready: {target}")
    print("\nSet this in your MCP server config:")
    print(f"  FAVA_TRAILS_DATA_REPO={target}")
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    """Show current scope and resolution source."""
    project_dir = Path.cwd()
    env_path = project_dir / ".env"

    env_scope = _read_env_value(env_path, "FAVA_TRAILS_SCOPE")
    if env_scope:
        print(f"Scope:  {env_scope}")
        print("Source: .env (FAVA_TRAILS_SCOPE)")
        return 0

    yaml_scope = _read_project_yaml_scope(project_dir)
    if yaml_scope:
        print(f"Scope:  {yaml_scope}")
        print("Source: .fava-trails.yaml")
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
    """Health check: JJ, data repo, OpenRouter key, scope. Exits 0 if all pass, 1 if any fail."""
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
    data_repo_source = "FAVA_TRAILS_DATA_REPO" if os.environ.get("FAVA_TRAILS_DATA_REPO") else "default (~/.fava-trails)"
    try:
        data_repo = get_data_repo_root()
        if not data_repo.exists():
            print(f"Data repo:    NOT FOUND — {data_repo} (from {data_repo_source})")
            print("  Fix: fava-trails bootstrap <path>")
            if data_repo_source.startswith("default"):
                print("  Or:  export FAVA_TRAILS_DATA_REPO=/path/to/your/data-repo")
            any_failed = True
        elif not (data_repo / "config.yaml").exists():
            print(f"Data repo:    INVALID — missing config.yaml at {data_repo} (from {data_repo_source})")
            print("  Fix: fava-trails bootstrap <path>")
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

    # Check 3: OpenRouter API key?
    env_var_name = "OPENROUTER_API_KEY"  # noqa: S105 — env var name, not a secret
    try:
        global_config = load_global_config()
        env_var_name = global_config.openrouter_api_key_env
    except (OSError, ValueError):
        pass  # Use default env var name if config can't be loaded
    if os.environ.get(env_var_name):
        print(f"OpenRouter:   {env_var_name} is set")
    else:
        print(f"OpenRouter:   NOT SET ({env_var_name})")
        print(f"  Fix: export {env_var_name}=sk-or-v1-...")
        print("  Get a key: https://openrouter.ai/keys")
        any_failed = True

    # Check 4: Scope configured and valid?
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


# ─── get ───────────────────────────────────────────────────────────────────────


def cmd_get(args: argparse.Namespace) -> int:
    """Retrieve thought content from a scope path.

    Stdout hygiene: ONLY requested content goes to stdout.
    All errors/diagnostics go to stderr.
    """
    scope = args.scope
    try:
        scope = sanitize_scope_path(scope)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        trails_dir = get_trails_dir()
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    scope_dir = trails_dir / scope

    # --list mode: list child scope names
    if getattr(args, "list_children", False):
        if not scope_dir.is_dir():
            print(f"Error: scope '{scope}' not found", file=sys.stderr)
            return 1
        children = sorted(
            d.name for d in scope_dir.iterdir()
            if d.is_dir() and d.name != "thoughts"
        )
        for child in children:
            print(child)
        return 0

    # Find thoughts in this scope
    thoughts_dir = scope_dir / "thoughts"
    if not thoughts_dir.is_dir():
        if getattr(args, "exists", False):
            return 1
        print(f"Error: no thoughts in scope '{scope}'", file=sys.stderr)
        return 1

    # Collect .md files across namespaces, sort by ULID descending (latest first)
    md_files = sorted(
        (f for f in thoughts_dir.rglob("*.md") if f.name != ".gitkeep"),
        key=lambda p: p.stem,
        reverse=True,
    )

    if not md_files:
        if getattr(args, "exists", False):
            return 1
        print(f"Error: no thoughts in scope '{scope}'", file=sys.stderr)
        return 1

    # --exists mode: just check existence
    if getattr(args, "exists", False):
        # Check at least one non-superseded thought exists
        for md_file in md_files:
            try:
                record = ThoughtRecord.from_markdown(md_file.read_text())
                if not record.is_superseded:
                    return 0
            except Exception:
                continue
        return 1

    # Default mode: output latest non-superseded thought content
    for md_file in md_files:
        try:
            record = ThoughtRecord.from_markdown(md_file.read_text())
        except Exception:
            continue
        if not record.is_superseded:
            if getattr(args, "with_frontmatter", False):
                print(record.to_markdown(), end="")
            else:
                print(record.content, end="")
            return 0

    print(f"Error: all thoughts in scope '{scope}' are superseded", file=sys.stderr)
    return 1


# ─── Protocol setup commands ──────────────────────────────────────────────────


def _jj_commit_dance(jj_bin: str, data_repo: Path, message: str) -> bool:
    """Run the jj commit dance: describe → new → bookmark set main → git push.

    Returns True if all steps succeeded, False if any step failed (bails on first failure).
    """
    steps = [
        ([jj_bin, "describe", "-m", message], "describe"),
        ([jj_bin, "new", "-m", "(new change)"], "new"),
        ([jj_bin, "bookmark", "set", "main", "-r", "@-"], "bookmark set"),
        ([jj_bin, "git", "push", "-b", "main"], "git push"),
    ]
    for cmd, name in steps:
        result = subprocess.run(cmd, cwd=str(data_repo), check=False, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Warning: jj {name} failed: {result.stderr.strip()}", file=sys.stderr)
            return False
    return True


def _cmd_protocol_setup(args: argparse.Namespace, protocol_name: str, module_path: str, default_entry: dict) -> int:
    """Generic protocol setup: print YAML block or write to config.yaml with jj dance."""
    # 1. Validate data repo exists
    try:
        data_repo = get_data_repo_root()
        if not data_repo.exists() or not (data_repo / "config.yaml").exists():
            print(f"Error: data repo not found at {data_repo}. Run: fava-trails bootstrap <path>", file=sys.stderr)
            return 1
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # 2. Check idempotency (module match) — only relevant for --write
    write = getattr(args, "write", False)
    if write:
        try:
            config = load_global_config()
        except (OSError, ValueError) as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            return 1
        for hook in config.hooks:
            if hook.module == module_path:
                print(f"{protocol_name} hook already configured (module: {module_path}). No changes made.")
                return 0

    # 3. Print YAML block
    yaml_block = yaml.dump({"hooks": [default_entry]}, default_flow_style=False, sort_keys=False)
    print(f"# {protocol_name} default hook config:")
    print(yaml_block)

    if not write:
        print("Add this to your config.yaml hooks section, or run:")
        print(f"  fava-trails {protocol_name.lower()} setup --write")
        return 0

    # 4. --write mode: find jj, create HookEntry, append, save, jj dance
    jj_bin = _find_jj_bin()
    if not jj_bin:
        print("Error: jj not found. Install with: fava-trails install-jj", file=sys.stderr)
        return 1

    # Warn about comment loss before rewriting YAML
    config_path = data_repo / "config.yaml"
    try:
        config_text = config_path.read_text()
        has_comments = any(line.strip().startswith("#") for line in config_text.splitlines())
    except OSError as e:
        print(f"Error reading config.yaml: {e}", file=sys.stderr)
        return 1

    entry = HookEntry(**default_entry)
    config.hooks.append(entry)
    try:
        save_global_config(config)
    except OSError as e:
        print(f"Error writing config.yaml: {e}", file=sys.stderr)
        return 1

    jj_ok = _jj_commit_dance(jj_bin, data_repo, f"feat: add {protocol_name} hook to config.yaml")

    if has_comments:
        print("Warning: config.yaml had YAML comments — they have been lost during rewrite.")

    print(f"{protocol_name} hook added to config.yaml.")
    if not jj_ok:
        print("Warning: config.yaml was saved but jj commit/push failed — data repo may have uncommitted changes.", file=sys.stderr)
    print("Hint: restart the MCP server to activate the hook.")
    if protocol_name == "secom":
        print("Hint: run 'fava-trails secom warmup' to pre-download the LLMLingua model.")
    return 0


def cmd_secom_setup(args: argparse.Namespace) -> int:
    """Print or write SECOM hook config to config.yaml."""
    from .protocols.secom import DEFAULT_HOOK_ENTRY
    return _cmd_protocol_setup(args, "secom", "fava_trails.protocols.secom", DEFAULT_HOOK_ENTRY)


def cmd_ace_setup(args: argparse.Namespace) -> int:
    """Print or write ACE hook config to config.yaml."""
    from .protocols.ace import DEFAULT_HOOK_ENTRY
    return _cmd_protocol_setup(args, "ace", "fava_trails.protocols.ace", DEFAULT_HOOK_ENTRY)


def cmd_rlm_setup(args: argparse.Namespace) -> int:
    """Print or write RLM hook config to config.yaml."""
    from .protocols.rlm import DEFAULT_HOOK_ENTRY
    return _cmd_protocol_setup(args, "rlm", "fava_trails.protocols.rlm", DEFAULT_HOOK_ENTRY)


def cmd_secom_warmup(args: argparse.Namespace) -> int:
    """Pre-download the SECOM LLMLingua model and verify compression works."""
    import importlib.util

    from .protocols.secom import DEFAULT_HOOK_ENTRY, configure

    # Configure SECOM with defaults so _get_compressor() uses them
    configure(DEFAULT_HOOK_ENTRY["config"])

    # Check llmlingua is importable
    if importlib.util.find_spec("llmlingua") is None:
        print("Error: llmlingua not installed. Install with: pip install fava-trails[secom]", file=sys.stderr)
        return 1

    print("Loading LLMLingua model (may download on first run)...")
    try:
        from .protocols.secom import _get_compressor
        _get_compressor()
    except Exception as e:
        print(f"Error: failed to load compressor: {e}", file=sys.stderr)
        return 1

    # Test compression with a short sample
    print("Testing compression...")
    try:
        from .protocols.secom import _compress
        sample = "The quick brown fox jumps over the lazy dog. " * 20
        compressed, rate = _compress(sample, 0.6)
        print(f"Compression test: {len(sample)} chars → {len(compressed)} chars (rate={rate:.2f})")
    except Exception as e:
        print(f"Error: compression test failed: {e}", file=sys.stderr)
        return 1

    # Report HuggingFace cache path
    hf_cache = os.environ.get("HF_HOME") or os.environ.get("TRANSFORMERS_CACHE") or str(Path.home() / ".cache" / "huggingface")
    print(f"HuggingFace cache: {hf_cache}")

    print("SECOM warmup complete.")
    return 0


# ─── integrate codev ──────────────────────────────────────────────────────────

CODEV_ADDENDUM_VERSION = 1
_PROVENANCE_RE = re.compile(r"^<!-- Generic prompt hash: ([a-f0-9]+)")


def _compose_codev_prompt(generic_prompt: str, addendum: str, pkg_version: str) -> str:
    """Compose the codev trust gate prompt from generic prompt + addendum."""
    import hashlib

    generic_hash = hashlib.sha256(generic_prompt.encode()).hexdigest()[:12]
    header = (
        f"<!-- Composed by: fava-trails integrate codev v{pkg_version} -->\n"
        f"<!-- Generic prompt hash: {generic_hash} | Addendum version: {CODEV_ADDENDUM_VERSION} -->\n"
        f"<!-- To update: fava-trails integrate codev --upgrade -->\n"
    )
    return header + "\n" + generic_prompt + "\n\n" + addendum


def cmd_integrate_codev(args: argparse.Namespace) -> int:
    """Compose the codev trust gate prompt (generic + addendum) into the data repo."""
    check = getattr(args, "check", False)
    diff = getattr(args, "diff", False)
    force = getattr(args, "force", False)

    # 1. Validate data repo exists
    try:
        get_data_repo_root()  # validates data repo exists
        trails_dir = get_trails_dir()
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not trails_dir.exists():
        print(f"Error: trails directory not found at {trails_dir}", file=sys.stderr)
        return 1

    # 2. Read generic trust gate prompt
    generic_path = trails_dir / "trust-gate-prompt.md"
    if not generic_path.exists():
        print(f"Error: generic trust gate prompt not found at {generic_path}", file=sys.stderr)
        print("  Run: fava-trails bootstrap <path>", file=sys.stderr)
        return 1
    generic_prompt = generic_path.read_text()

    # 3. Read addendum from package
    addendum_pkg = importlib_resources.files("fava_trails") / "integrations" / "codev" / "trust-gate-addendum.md"
    addendum = addendum_pkg.read_text()

    # 4. Get package version
    try:
        from importlib.metadata import version
        pkg_version = version("fava-trails")
    except Exception:
        pkg_version = "unknown"

    # 5. Compose
    composed = _compose_codev_prompt(generic_prompt, addendum, pkg_version)

    # 6. Determine output path
    output_dir = trails_dir / "codev-artifacts"
    output_path = output_dir / "trust-gate-prompt.md"

    # 7. Handle modes
    if check:
        if not output_path.exists():
            print("STALE: composed prompt does not exist yet.", file=sys.stderr)
            return 1
        existing = output_path.read_text()
        if existing == composed:
            print("OK: composed prompt is up to date.")
            return 0
        else:
            print("STALE: composed prompt does not match current sources.", file=sys.stderr)
            return 1

    if diff:
        if not output_path.exists():
            print(f"--- (new file)\n+++ {output_path}")
            for line in composed.splitlines():
                print(f"+{line}")
            return 0
        existing = output_path.read_text()
        if existing == composed:
            print("No changes.")
            return 0
        import difflib

        diff_lines = difflib.unified_diff(
            existing.splitlines(keepends=True),
            composed.splitlines(keepends=True),
            fromfile=str(output_path),
            tofile=str(output_path) + " (new)",
        )
        sys.stdout.writelines(diff_lines)
        return 0

    # Default write mode
    if output_path.exists() and not force:
        existing = output_path.read_text()
        # Check if existing file was manually edited (no provenance header)
        if not existing.startswith("<!-- Composed by: fava-trails integrate codev"):
            print(
                f"Error: {output_path} exists but was not generated by this tool.",
                file=sys.stderr,
            )
            print("  Use --force to overwrite, or --diff to preview changes.", file=sys.stderr)
            return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(composed)
    print(f"Wrote composed trust gate prompt to {output_path}")
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
    p_bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Create a new data repository from scratch (use 'clone' for existing remotes)",
    )
    p_bootstrap.add_argument("path", help="Path to create the data repository")
    p_bootstrap.add_argument("--remote", metavar="URL", default=None, help="Git remote URL (optional)")
    p_bootstrap.set_defaults(func=cmd_bootstrap)

    # clone
    p_clone = subparsers.add_parser("clone", help="Clone an existing data repository from a remote")
    p_clone.add_argument("url", help="Git remote URL to clone from")
    p_clone.add_argument("path", help="Local path to clone into")
    p_clone.set_defaults(func=cmd_clone)

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
    p_doctor = subparsers.add_parser("doctor", help="Check JJ, data repo, OpenRouter key, and scope configuration")
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

    # get
    p_get = subparsers.add_parser(
        "get",
        help="Retrieve thought content from a scope (stdout only, no logging)",
    )
    p_get.add_argument("scope", help="Scope path (e.g. mwai/eng/project/codev-assets/specs/17-feature)")
    get_mode = p_get.add_mutually_exclusive_group()
    get_mode.add_argument(
        "--list", dest="list_children", action="store_true",
        help="List child scope names instead of thought content",
    )
    get_mode.add_argument(
        "--exists", action="store_true",
        help="Exit 0 if non-superseded thoughts exist, 1 if not (no output)",
    )
    p_get.add_argument(
        "--with-frontmatter", action="store_true",
        help="Include YAML frontmatter in output",
    )
    p_get.set_defaults(func=cmd_get)

    # integrate
    p_integrate = subparsers.add_parser("integrate", help="Set up integrations with external tools")
    integrate_sub = p_integrate.add_subparsers(dest="integrate_command", metavar="<integration>")

    p_integrate_codev = integrate_sub.add_parser(
        "codev", help="Compose codev trust gate prompt (generic + addendum)"
    )
    p_integrate_codev.add_argument("--check", action="store_true", help="Verify composed file is up to date (CI-friendly)")
    p_integrate_codev.add_argument("--diff", action="store_true", help="Preview changes without writing")
    p_integrate_codev.add_argument("--force", action="store_true", help="Overwrite even if manually edited")
    p_integrate_codev.set_defaults(func=cmd_integrate_codev)

    p_integrate.set_defaults(func=lambda args: (p_integrate.print_help(), 0)[1])

    # secom
    p_secom = subparsers.add_parser("secom", help="SECOM compression protocol commands")
    secom_sub = p_secom.add_subparsers(dest="secom_command", metavar="<subcommand>")

    p_secom_setup = secom_sub.add_parser("setup", help="Print or write SECOM hook config to config.yaml")
    p_secom_setup.add_argument("--write", action="store_true", help="Write config to config.yaml and commit with jj")
    p_secom_setup.set_defaults(func=cmd_secom_setup)

    p_secom_warmup = secom_sub.add_parser("warmup", help="Pre-download the SECOM model and verify compression")
    p_secom_warmup.set_defaults(func=cmd_secom_warmup)

    p_secom.set_defaults(func=lambda args: (p_secom.print_help(), 0)[1])

    # ace
    p_ace = subparsers.add_parser("ace", help="ACE playbook protocol commands")
    ace_sub = p_ace.add_subparsers(dest="ace_command", metavar="<subcommand>")

    p_ace_setup = ace_sub.add_parser("setup", help="Print or write ACE hook config to config.yaml")
    p_ace_setup.add_argument("--write", action="store_true", help="Write config to config.yaml and commit with jj")
    p_ace_setup.set_defaults(func=cmd_ace_setup)

    p_ace.set_defaults(func=lambda args: (p_ace.print_help(), 0)[1])

    # rlm
    p_rlm = subparsers.add_parser("rlm", help="RLM MapReduce protocol commands")
    rlm_sub = p_rlm.add_subparsers(dest="rlm_command", metavar="<subcommand>")

    p_rlm_setup = rlm_sub.add_parser("setup", help="Print or write RLM hook config to config.yaml")
    p_rlm_setup.add_argument("--write", action="store_true", help="Write config to config.yaml and commit with jj")
    p_rlm_setup.set_defaults(func=cmd_rlm_setup)

    p_rlm.set_defaults(func=lambda args: (p_rlm.print_help(), 0)[1])

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        hints = []
        if not shutil.which("jj"):
            hints.append("  1. Install JJ:         fava-trails install-jj")
        try:
            data_repo = get_data_repo_root()
            data_repo_ok = data_repo.exists() and (data_repo / "config.yaml").exists()
        except (OSError, ValueError):
            data_repo_ok = False
        if not data_repo_ok:
            n = len(hints) + 1
            hints.append(f"  {n}. Set up data repo:   fava-trails bootstrap <path>")
        env_var_name = "OPENROUTER_API_KEY"  # noqa: S105 — env var name, not a secret
        try:
            env_var_name = load_global_config().openrouter_api_key_env
        except (OSError, ValueError):
            pass
        if not os.environ.get(env_var_name):
            n = len(hints) + 1
            hints.append(f"  {n}. Set OpenRouter key:  export {env_var_name}=sk-or-v1-...")
        if hints:
            print("\nQuick start:")
            print("\n".join(hints))
        sys.exit(0)

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

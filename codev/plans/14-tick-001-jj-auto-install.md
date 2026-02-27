# Plan: TICK 14-001 — JJ Auto-Install CLI Command

## Phase 1: `install-jj` subcommand

### Files to create/modify

**`src/fava_trails/cli.py`** — Add `cmd_install_jj` function and wire up subparser:

```python
def cmd_install_jj(args: argparse.Namespace) -> int:
    """Download and install the JJ binary."""
```

Logic:
1. Check if JJ already installed:
   - Parse installed version from `jj version` output
   - If installed version == target version → print version, exit 0
   - If versions differ → proceed with install (upgrade/downgrade)
2. Detect platform: `sys.platform` + `platform.machine()`
3. Map to release artifact name:
   - `linux` + `x86_64` → `x86_64-unknown-linux-musl`
   - `linux` + `aarch64` → `aarch64-unknown-linux-musl`
   - `darwin` + `x86_64` → `x86_64-apple-darwin`
   - `darwin` + `arm64` → `aarch64-apple-darwin`
   - `win32` → print `winget install Jujutsu.Jujutsu` and exit 1
   - else → error with manual install URL
4. Download tarball from `https://github.com/jj-vcs/jj/releases/download/v{VERSION}/jj-v{VERSION}-{suffix}.tar.gz`
5. Extract to tempdir, copy `jj` binary to `~/.local/bin/jj`
6. `chmod +x`
7. Verify: run `jj version`, print output
8. Post-install PATH check: run `shutil.which("jj")` — if None, print clear warning with instructions to add `~/.local/bin` to PATH

Constants: `JJ_VERSION = "0.28.0"` (match `scripts/install-jj.sh`), `INSTALL_DIR = ~/.local/bin`

Dependencies: `urllib.request`, `tarfile`, `tempfile`, `shutil`, `platform` — all stdlib.

### Subparser registration

```python
p_install_jj = subparsers.add_parser("install-jj", help="Download and install the Jujutsu (JJ) binary")
p_install_jj.add_argument("--version", default=None, help="JJ version to install (default: 0.28.0)")
p_install_jj.set_defaults(func=cmd_install_jj)
```

### Done criteria
- `fava-trails install-jj` downloads and installs JJ on Linux x86_64
- Skips if already installed
- `--version` flag allows pinning

## Phase 2: Error message cleanup

### Files to modify

1. **`src/fava_trails/cli.py:212`** (`cmd_bootstrap`):
   ```
   - "Error: jj not found. Install with: bash scripts/install-jj.sh"
   + "Error: jj not found. Install with: fava-trails install-jj\n  Or manually: https://jj-vcs.github.io/jj/"
   ```

2. **`src/fava_trails/cli.py:427`** (`cmd_doctor`):
   ```
   - "  Fix: bash scripts/install-jj.sh"
   + "  Fix: fava-trails install-jj"
   ```

3. **`src/fava_trails/vcs/jj_backend.py:64-65`** (`_find_jj`):
   ```
   - "jj binary not found. Install from https://jj-vcs.github.io/jj/ or run scripts/install-jj.sh (from source repo)"
   + "jj binary not found. Install with: fava-trails install-jj (or manually from https://jj-vcs.github.io/jj/)"
   ```

4. **`tests/conftest.py:14`**:
   ```
   - "jj binary not found — install via scripts/install-jj.sh"
   + "jj binary not found — install via: fava-trails install-jj"
   ```

### Done criteria
- Zero references to `scripts/install-jj.sh` in Python source files
- All JJ-missing errors point to `fava-trails install-jj`

## Phase 3: Tests

### New tests in `tests/test_cli.py`

1. `test_install_jj_skips_if_present` — mock `shutil.which` returning jj → exit 0, prints version
2. `test_install_jj_unsupported_platform` — mock `sys.platform` to `"win32"` → exit 1, prints manual URL
3. `test_install_jj_downloads_and_installs` — mock `urllib.request.urlopen`, verify binary placed in expected path
4. `test_install_jj_custom_version` — verify `--version 0.29.0` changes download URL

### Existing test updates

- `test_bootstrap_fails_if_jj_missing` — assert new error message text
- `test_cli.py:477` — assert `install-jj` in output (not `install-jj.sh`)
- `test_doctor_jj_missing` — assert new fix message

### Done criteria
- All new tests pass
- All existing tests pass (181 total)

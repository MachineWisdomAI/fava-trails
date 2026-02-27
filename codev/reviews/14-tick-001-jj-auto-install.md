# Review: TICK 14-001 — JJ Auto-Install CLI Command

**Date**: 2026-02-27
**Protocol**: TICK
**Spec**: `codev/specs/14-tick-001-jj-auto-install.md`

## What Was Amended

Added `fava-trails install-jj` subcommand to eliminate the adoption cliff between `pip install fava-trails` and a working system. Updated all "jj not found" error messages to reference `fava-trails install-jj` instead of the non-existent (in PyPI packages) `scripts/install-jj.sh`.

## Changes Made

### Spec Changes
- Standalone TICK spec at `codev/specs/14-tick-001-jj-auto-install.md` (authored by architect)

### Plan Changes
- Standalone TICK plan at `codev/plans/14-tick-001-jj-auto-install.md` (authored by architect)

### Implementation

**`src/fava_trails/cli.py`**:
- Added imports: `platform`, `tarfile`, `tempfile`, `urllib.error`, `urllib.request`
- Added `JJ_DEFAULT_VERSION = "0.28.0"` and `_JJ_INSTALL_DIR` constant
- Added `cmd_install_jj()` function (~110 LOC):
  - Platform check first (Windows → winget instructions, return 1)
  - Version-aware skip: checks installed JJ version, exits 0 if matches
  - Platform/arch detection for Linux x86_64/aarch64, macOS x86_64/arm64
  - Downloads via `urlopen(timeout=30)` (no new dependencies)
  - Safe tarball extraction via `extractfile()` + manual write (avoids path traversal)
  - Filesystem error handling with actionable messages
  - Post-install PATH check with shell snippet
- Registered `install-jj` subparser with `--version` flag
- Updated `cmd_bootstrap` error message (line ~212)
- Updated `cmd_doctor` fix suggestion (line ~427)

**`src/fava_trails/vcs/jj_backend.py`**:
- Updated `_find_jj()` error message to reference `fava-trails install-jj`

**`tests/conftest.py`**:
- Updated skip message to reference `fava-trails install-jj`

**`tests/test_cli.py`**:
- Added `cmd_install_jj` to imports
- Updated `test_doctor_missing_jj` assertion (`install-jj` not `install-jj.sh`)
- Added 6 new tests: skip-if-version-matches, Windows/winget, unsupported arch, download+install, custom version URL, appears-in-help

## Implementation Challenges

**tarfile extraction**: Initial implementation used `tf.extract()` which triggers a Python 3.12+ DeprecationWarning and is a potential path traversal vector. Replaced with `extractfile()` + manual `shutil.copyfileobj()` write — eliminates the entire traversal class of bugs.

**Test isolation for platform mocking**: Tests patching `sys.platform = "win32"` caused `shutil.which()` to internally call `_winapi.NeedCurrentDirectoryForExePath` which doesn't exist on Linux. Fixed by also patching `shutil.which`.

**Test isolation for already-installed check**: Tests for unsupported platform/arch were short-circuiting via the "already installed" check (real JJ is installed on CI). Fixed by reordering: platform check now happens *before* the version check, since Windows users shouldn't run the Linux installer path at all.

**urlopen context manager**: The `urlopen` mock needed a proper context manager interface (`__enter__`/`__exit__`) since the implementation uses it as `with urllib.request.urlopen(...) as r`.

## Multi-Agent Consultation

Ran `mcp__pal__codereview` with GPT-5.1 expert analysis. Key findings actioned:

| Issue | Severity | Action |
|-------|----------|--------|
| `tf.extract()` path traversal / Python 3.12+ deprecation | Critical | Fixed: use `extractfile()` + manual write |
| `jj version` vs `jj --version` inconsistency | High | Fixed: use `--version` everywhere |
| `urlretrieve` has no timeout | High | Fixed: use `urlopen(timeout=30)` |
| Filesystem ops not wrapped in try/except | Medium | Fixed: added `OSError` handler |
| `./jj` member name path handling | Low | Fixed: use `Path(m.name).name` |

## Lessons Learned

1. **Test platform mocking carefully**: Patching `sys.platform` without also patching stdlib functions that branch on it (like `shutil.which`) causes internal errors on non-Windows platforms.
2. **Safe tarball extraction pattern**: Always use `extractfile()` + manual write for network-downloaded tarballs. Never use `tf.extract()` without `filter='data'`.
3. **urlopen needs context manager mock**: When mocking `urlopen`, provide a proper `__enter__`/`__exit__` mock since `with urlopen(...) as r` is the canonical pattern.
4. **Order platform check before version check**: For commands with platform-specific behavior, check unsupported platforms first to fail fast with actionable messages.

## Success Criteria Verification

- [x] `fava-trails install-jj` subcommand exists and is registered
- [x] Linux x86_64, Linux aarch64, macOS x86_64, macOS arm64 supported
- [x] Windows detection prints winget instructions
- [x] Version-aware skip: exits 0 if installed version matches
- [x] `--version` flag allows pinning a different JJ version
- [x] Zero references to `scripts/install-jj.sh` in Python source/tests
- [x] All error messages point to `fava-trails install-jj`
- [x] 6 new tests added; all 187 tests pass
- [x] No new PyPI dependencies (stdlib only)

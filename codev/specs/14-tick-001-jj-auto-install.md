# TICK 14-001: JJ Auto-Install CLI Command

## Status
- **Protocol**: TICK
- **Amends**: Spec 14 (CLI)
- **Phase**: Specify

## Problem

`pip install fava-trails` does not provide JJ. Users hit an adoption cliff:

1. `fava-trails bootstrap <path>` → "Error: jj not found. Install with: bash scripts/install-jj.sh"
2. `scripts/install-jj.sh` does not exist in the PyPI package
3. User must find JJ's website, figure out which binary to download, install manually
4. Error messages in `jj_backend.py` and `cli.py` still reference `scripts/install-jj.sh`

This is three steps and a dead-end error between `pip install` and a working system. Gemini's assessment: "Complexity here kills adoption."

## Amendment

Add a `fava-trails install-jj` subcommand that downloads and installs the JJ binary. Update all error messages to reference it.

### New: `fava-trails install-jj`

Python reimplementation of `scripts/install-jj.sh`, cross-platform:

- Detect OS + arch (Linux x86_64/aarch64, macOS x86_64/arm64)
- Download pre-built binary from `github.com/jj-vcs/jj/releases`
- Install to `~/.local/bin/jj`
- Verify binary runs (`jj version`)
- Version-aware skip: if installed version matches target, exit 0. If versions differ, proceed with install (enables upgrades via `--version`)
- Windows detection: print actionable `winget install Jujutsu.Jujutsu` command instead of generic error
- Post-install PATH check: verify `~/.local/bin` is in PATH, warn clearly if not
- Use `urllib` only — no new dependencies

### Changed: Error messages

All "jj not found" error messages updated to:

```
jj binary not found. Install with: fava-trails install-jj
  Or manually from: https://jj-vcs.github.io/jj/
```

Affected locations:
- `src/fava_trails/cli.py:212` — `cmd_bootstrap`
- `src/fava_trails/cli.py:427` — `cmd_doctor`
- `src/fava_trails/vcs/jj_backend.py:64` — `_find_jj`

### Changed: `fava-trails bootstrap`

When JJ is missing, instead of failing immediately, print:

```
JJ not found. Run 'fava-trails install-jj' first, or install manually from https://jj-vcs.github.io/jj/
```

### Unchanged

- `scripts/install-jj.sh` stays (for source-repo developers, CI)
- No new PyPI dependencies
- No bundled binaries

## Success Criteria

- `pip install fava-trails && fava-trails install-jj && fava-trails bootstrap ./data` works end-to-end
- Linux x86_64, Linux aarch64, macOS x86_64, macOS arm64 supported
- Existing tests pass; new tests cover `install-jj` subcommand
- Error messages no longer reference `scripts/install-jj.sh`

## Scope

< 200 LOC new code. No architecture changes.

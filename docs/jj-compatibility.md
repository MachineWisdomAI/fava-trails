# JJ (Jujutsu) compatibility

FAVA Trails uses [Jujutsu](https://jj-vcs.github.io/jj/) in Git-colocate mode as
its storage engine. This document records the supported floor, install policy,
and versions exercised by automated tests.

## Supported minimum

| Component | Policy |
|-----------|--------|
| **Minimum supported JJ** | **0.28.0** |
| **Install default** | Current official GitHub stable (`jj-vcs/jj` latest release), not a frozen patch |
| **Override** | `fava-trails install-jj --version X.Y.Z` or `JJ_VERSION=X.Y.Z` |

The minimum is the oldest release against which FAVA Trails runs its real JJ
integration suite on disposable repositories (init, save, promote/reject freeze,
supersede, status, sync dirty-path). Newer releases that preserve the command
surface FAVA uses are accepted without forcing an upgrade.

Evidence (local + CI matrix, 2026-09-09):

| JJ version | `tests/test_jj_backend.py` | `tests/test_jj_compat_matrix.py` | `tests/test_tools.py` (subset) |
|------------|----------------------------|----------------------------------|--------------------------------|
| 0.28.0 | pass | pass | pass |
| 0.45.1 (then-current stable) | pass | pass | pass |

## Installer policy

Canonical implementation: `src/fava_trails/jj_install.py`, exposed as
`fava-trails install-jj` and as `python -m fava_trails.jj_install`.
`scripts/install-jj.sh` is a **thin entrypoint** that delegates to that module
(or the packaged CLI) so digest checks, archive validation, and restore policy
cannot drift across two implementations.

Shared behavior:

1. **Reuse first** — any installed `jj` with version `>= 0.28.0` (including newer
   than the last CI pin) is selected **before** platform/download checks, so a
   compatible binary is kept even on hosts without a FAVA-downloadable asset.
   Report `action` / `path` / `version` / `reason`.
2. **Never silently downgrade** or overwrite a **user-managed** executable
   (anything other than the managed `~/.local/bin/jj` path).
3. When install is needed, **resolve GitHub latest stable** with bounded
   network timeouts, unless an explicit version override is set.
4. **Integrity**: use GitHub release asset `digest` (`sha256:…`) when the API
   publishes it; a published digest is never silently discarded. Older tags
   without digests still verify `--version` after extract.
5. **Safe archive handling**: exactly one regular `jj` member is written;
   path traversal, absolute paths, non-regular entries (symlinks/dirs), and
   ambiguous archives with multiple `jj` candidates are rejected.
6. **Atomic install** to the managed install dir (default `~/.local/bin/jj`;
   override with `--install-dir` / `INSTALL_DIR`). If verification fails **at any
   point after replacement begins** (including post-replace `--version` when the
   new file is already at the destination): restore the prior managed binary when
   one existed; otherwise remove the failed destination so a fresh install does
   not leave an invalid unverified executable. PATH guidance after install refers
   to the selected install directory (shell-quoted), not always `~/.local/bin`.
7. Offline / API failure: if a compatible JJ is already present, keep it and
   report the resolution error in the reason; otherwise exit non-zero without
   changing disk state.
8. `scripts/install-jj.sh` builds forwarded argv with `set --` only so the
   documented no-argument path works under macOS Bash 3.2 + `set -u` (empty
   array expansion is not used).

## Command surface FAVA relies on

These JJ invocations are used by `JjBackend` and must remain available on
supported versions:

- `jj git init --colocate`
- `jj config set --repo …` (including `ui.conflict-marker-style=snapshot`)
- `jj new -m`, `jj describe -m`, `jj status`
- `jj diff --name-only`, `jj diff --stat`, `jj diff --git`
- `jj log` with templates / revsets (`conflicts()`, `description(exact:"")`, `@`, `@-`)
- `jj bookmark set`, `jj git fetch --all-remotes`, `jj rebase -d …`
- `jj git push --allow-empty-description` / `-b` (tracked bookmarks)
- `jj git push --all` when seeding a remote that does not yet have the bookmark
- `jj abandon`, `jj op log`, `jj op restore`, `jj util gc`

### Incompatible command changes observed

| Change | Impact on FAVA |
|--------|----------------|
| `jj git push --allow-new` removed (JJ **0.42+**) | Not used by `JjBackend._git_push` (tracked `-b` / `--all` only). Tests that seed a brand-new remote bookmark must use `--all` (or track + push), not `--allow-new`. |

FAVA does not use other removed legacy names (`jj untrack`, `branches()` revset,
etc.). If a future JJ release breaks a listed invocation, raise the documented
minimum and note the incompatibility here.

## CI

`.github/workflows/test.yml` installs an explicit matrix of JJ versions via
`fava-trails install-jj --version <pin> --force` so the suite runs on both the
supported minimum and a current stable pin. Production installs without
`--version` follow GitHub latest.

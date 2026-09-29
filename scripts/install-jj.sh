#!/usr/bin/env bash
# Thin entrypoint for JJ install/selection (issue #98).
#
# Canonical policy lives in src/fava_trails/jj_install.py (digest verification,
# safe archive extraction, atomic install with restore-on-failure, reuse rules).
# This script only locates a Python interpreter and delegates — avoiding a second
# policy implementation that can drift (e.g. silent digest loss without Python/jq).
#
# Usage:
#   scripts/install-jj.sh
#   JJ_VERSION=0.28.0 scripts/install-jj.sh
#   FORCE=1 scripts/install-jj.sh
#   INSTALL_DIR=~/.local/bin scripts/install-jj.sh
# Extra args are forwarded to the Python installer (--version, --force, --install-dir).
#
# Bash 3.2 note (macOS /bin/bash): under `set -u`, expanding an empty array via
# "${arr[@]}" is an unbound-variable error. Build forwarded argv with `set --`
# only — never copy or expand an empty array.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_PATH="${ROOT}/src/fava_trails/jj_install.py"

err() { printf '%s\n' "$*" >&2; }

# $@ starts as the original script arguments (may be empty). Prepend env-derived
# flags via `set --` so zero-arg invocation stays valid under Bash 3.2 + set -u.
_run_module() {
  local py="$1"
  shift
  if [[ -n "${INSTALL_DIR:-}" ]]; then
    set -- --install-dir "${INSTALL_DIR}" "$@"
  fi
  if [[ "${FORCE:-0}" == "1" ]]; then
    set -- --force "$@"
  fi
  if [[ -n "${JJ_VERSION:-}" ]]; then
    set -- --version "${JJ_VERSION}" "$@"
  fi
  export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
  exec "${py}" -m fava_trails.jj_install "$@"
}

_run_cli() {
  # INSTALL_DIR is honored by the packaged CLI via env; only forward flag-like env.
  if [[ "${FORCE:-0}" == "1" ]]; then
    set -- --force "$@"
  fi
  if [[ -n "${JJ_VERSION:-}" ]]; then
    set -- --version "${JJ_VERSION}" "$@"
  fi
  exec fava-trails install-jj "$@"
}

# Prefer the in-tree canonical module when this script lives in a source checkout.
# That keeps INSTALL_DIR / policy aligned with this revision (not a stale packaged CLI).
if [[ -f "${MODULE_PATH}" ]]; then
  if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    err "Python 3 is required to install JJ via scripts/install-jj.sh."
    err "The canonical installer is src/fava_trails/jj_install.py (also: fava-trails install-jj)."
    err "Install Python 3, or install JJ manually from: https://jj-vcs.github.io/jj/"
    exit 1
  fi
  if command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
  else
    PY="$(command -v python)"
  fi
  _run_module "${PY}" "$@"
fi

# Packaged install: delegate to the CLI (INSTALL_DIR env is honored by the installer).
if command -v fava-trails >/dev/null 2>&1; then
  _run_cli "$@"
fi

err "Could not find src/fava_trails/jj_install.py or the fava-trails CLI."
err "Install the package (pip/uv) or run from a FAVA Trails source checkout."
err "Or install JJ manually from: https://jj-vcs.github.io/jj/"
exit 1

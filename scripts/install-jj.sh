#!/usr/bin/env bash
# Install or select Jujutsu (JJ) for FAVA Trails.
# Policy mirrors src/fava_trails/jj_install.py (issue #98):
#   - Reuse any installed JJ >= JJ_MIN_VERSION (never silently downgrade).
#   - Never overwrite a user-managed executable outside ~/.local/bin/jj.
#   - When install is needed, resolve GitHub latest stable unless JJ_VERSION is set.
#   - Verify SHA-256 when GitHub publishes asset digests; atomic install; restore on failure.
set -euo pipefail

JJ_MIN_VERSION="${JJ_MIN_VERSION:-0.28.0}"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/.local/bin}"
MANAGED_BINARY="${INSTALL_DIR}/jj"
GITHUB_API_LATEST="https://api.github.com/repos/jj-vcs/jj/releases/latest"
NETWORK_TIMEOUT="${NETWORK_TIMEOUT:-30}"

log() { printf '%s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }

report() {
  local action="$1" path="${2:-}" version="${3:-}" reason="$4"
  log "action:  ${action}"
  log "path:    ${path:-'(none)'}"
  log "version: ${version:-'(none)'}"
  log "reason:  ${reason}"
}

version_ge() {
  # Return 0 if $1 >= $2 (semver X.Y.Z)
  local a b
  IFS=. read -r a1 a2 a3 <<<"${1}"
  IFS=. read -r b1 b2 b3 <<<"${2}"
  a1=${a1:-0}; a2=${a2:-0}; a3=${a3:-0}
  b1=${b1:-0}; b2=${b2:-0}; b3=${b3:-0}
  if (( a1 != b1 )); then (( a1 > b1 )); return; fi
  if (( a2 != b2 )); then (( a2 > b2 )); return; fi
  (( a3 >= b3 ))
}

parse_jj_version() {
  # stdin or $1 → prints X.Y.Z or empty
  local text="${1:-}"
  if [[ -z "${text}" ]]; then
    text="$(cat || true)"
  fi
  if [[ "${text}" =~ [Jj][Jj][[:space:]]+([0-9]+\.[0-9]+\.[0-9]+) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
}

probe_jj() {
  local bin="$1"
  if [[ ! -x "${bin}" ]]; then
    return 1
  fi
  local out
  out="$("${bin}" --version 2>/dev/null || true)"
  parse_jj_version "${out}"
}

is_managed() {
  local bin="$1"
  local managed resolved
  managed="$(cd "$(dirname "${MANAGED_BINARY}")" 2>/dev/null && pwd)/$(basename "${MANAGED_BINARY}")" || true
  resolved="$(cd "$(dirname "${bin}")" 2>/dev/null && pwd)/$(basename "${bin}")" || true
  [[ -n "${managed}" && "${resolved}" == "${managed}" ]]
}

detect_suffix() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "${os}" in
    Linux)
      case "${arch}" in
        x86_64) printf '%s\n' "x86_64-unknown-linux-musl" ;;
        aarch64|arm64) printf '%s\n' "aarch64-unknown-linux-musl" ;;
        *) err "Unsupported Linux architecture: ${arch}"; err "Install manually from: https://jj-vcs.github.io/jj/"; return 1 ;;
      esac
      ;;
    Darwin)
      case "${arch}" in
        x86_64) printf '%s\n' "x86_64-apple-darwin" ;;
        arm64|aarch64) printf '%s\n' "aarch64-apple-darwin" ;;
        *) err "Unsupported macOS architecture: ${arch}"; err "Install manually from: https://jj-vcs.github.io/jj/"; return 1 ;;
      esac
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      err "Windows detected. Install JJ with:"
      err "  winget install Jujutsu.Jujutsu"
      err "Or manually from: https://jj-vcs.github.io/jj/"
      return 1
      ;;
    *)
      err "Unsupported OS: ${os}"
      err "Install manually from: https://jj-vcs.github.io/jj/"
      return 1
      ;;
  esac
}

api_get() {
  local url="$1"
  curl -fsSL --max-time "${NETWORK_TIMEOUT}" \
    -H "Accept: application/vnd.github+json" \
    -H "User-Agent: fava-trails-install-jj.sh" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "${url}"
}

resolve_release() {
  # Sets: RESOLVED_VERSION RESOLVED_URL RESOLVED_SHA256 RESOLVED_SOURCE
  local suffix="$1"
  local explicit="${JJ_VERSION:-}"
  local json tag asset_name digest url api

  if [[ -n "${explicit}" ]]; then
    explicit="${explicit#v}"
    api="https://api.github.com/repos/jj-vcs/jj/releases/tags/v${explicit}"
    if ! json="$(api_get "${api}")"; then
      err "Network error resolving JJ v${explicit}"
      return 1
    fi
    RESOLVED_VERSION="${explicit}"
    RESOLVED_SOURCE="explicit"
  else
    if ! json="$(api_get "${GITHUB_API_LATEST}")"; then
      err "Network error resolving latest JJ release"
      return 1
    fi
    tag="$(printf '%s' "${json}" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    tag="${tag#v}"
    if [[ -z "${tag}" ]]; then
      err "GitHub latest release response missing tag_name"
      return 1
    fi
    RESOLVED_VERSION="${tag}"
    RESOLVED_SOURCE="latest"
  fi

  asset_name="jj-v${RESOLVED_VERSION}-${suffix}.tar.gz"
  RESOLVED_URL="https://github.com/jj-vcs/jj/releases/download/v${RESOLVED_VERSION}/${asset_name}"
  RESOLVED_SHA256=""

  # Prefer browser_download_url + digest from assets when present (requires python or jq).
  if command -v python3 >/dev/null 2>&1; then
    local parsed
    parsed="$(JJ_JSON="${json}" JJ_ASSET="${asset_name}" python3 - <<'PY'
import json, os
data = json.loads(os.environ["JJ_JSON"])
name = os.environ["JJ_ASSET"]
url = ""
sha = ""
for a in data.get("assets") or []:
    if a.get("name") == name:
        url = a.get("browser_download_url") or ""
        d = a.get("digest") or ""
        if isinstance(d, str) and d.startswith("sha256:"):
            sha = d.split(":", 1)[1].strip().lower()
        break
print(url)
print(sha)
PY
)"
    local p_url p_sha
    p_url="$(printf '%s\n' "${parsed}" | sed -n '1p')"
    p_sha="$(printf '%s\n' "${parsed}" | sed -n '2p')"
    [[ -n "${p_url}" ]] && RESOLVED_URL="${p_url}"
    [[ -n "${p_sha}" ]] && RESOLVED_SHA256="${p_sha}"
  fi
}

sha256_file() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${f}" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${f}" | awk '{print $1}'
  else
    err "No sha256sum/shasum available to verify download"
    return 1
  fi
}

atomic_install() {
  local extracted="$1"
  local dest="$2"
  local expected="$3"
  local staged backup got
  mkdir -p "$(dirname "${dest}")"
  staged="${dest}.fava-new"
  backup="${dest}.fava-prev"
  rm -f "${staged}"
  cp "${extracted}" "${staged}"
  chmod +x "${staged}"
  got="$(probe_jj "${staged}" || true)"
  if [[ "${got}" != "${expected}" ]]; then
    rm -f "${staged}"
    err "version mismatch after extract: expected ${expected}, got ${got:-unknown}"
    return 1
  fi
  if [[ -e "${dest}" || -L "${dest}" ]]; then
    rm -f "${backup}"
    mv "${dest}" "${backup}"
  fi
  if ! mv "${staged}" "${dest}"; then
    if [[ -e "${backup}" ]]; then
      mv "${backup}" "${dest}" || true
    fi
    err "failed to move staged binary into place"
    return 1
  fi
  got="$(probe_jj "${dest}" || true)"
  if [[ "${got}" != "${expected}" ]]; then
    if [[ -e "${backup}" ]]; then
      mv "${backup}" "${dest}" || true
    fi
    err "post-install version verification failed"
    return 1
  fi
  rm -f "${backup}"
}

# ── main ─────────────────────────────────────────────────────────────────────

SUFFIX="$(detect_suffix)" || exit 1

EXISTING_BIN=""
EXISTING_VER=""
if command -v jj >/dev/null 2>&1; then
  EXISTING_BIN="$(command -v jj)"
elif [[ -x "${MANAGED_BINARY}" ]]; then
  EXISTING_BIN="${MANAGED_BINARY}"
fi
if [[ -n "${EXISTING_BIN}" ]]; then
  EXISTING_VER="$(probe_jj "${EXISTING_BIN}" || true)"
fi

FORCE="${FORCE:-0}"
EXPLICIT="${JJ_VERSION:-}"

if [[ -n "${EXISTING_BIN}" && -n "${EXISTING_VER}" && "${FORCE}" != "1" ]]; then
  if [[ -n "${EXPLICIT}" ]]; then
    want="${EXPLICIT#v}"
    if [[ "${EXISTING_VER}" == "${want}" ]]; then
      report "reuse" "${EXISTING_BIN}" "${EXISTING_VER}" \
        "exact match for requested ${want} at ${EXISTING_BIN}"
      exit 0
    fi
    if ! is_managed "${EXISTING_BIN}"; then
      report "refuse" "${EXISTING_BIN}" "${EXISTING_VER}" \
        "user-managed JJ ${EXISTING_VER} at ${EXISTING_BIN} differs from requested ${want}; refusing to overwrite"
      exit 1
    fi
  elif version_ge "${EXISTING_VER}" "${JJ_MIN_VERSION}"; then
    report "reuse" "${EXISTING_BIN}" "${EXISTING_VER}" \
      "compatible installed JJ ${EXISTING_VER} (>= ${JJ_MIN_VERSION}) at ${EXISTING_BIN}; not downgrading or replacing"
    exit 0
  else
    if ! is_managed "${EXISTING_BIN}"; then
      report "refuse" "${EXISTING_BIN}" "${EXISTING_VER}" \
        "user-managed JJ ${EXISTING_VER} at ${EXISTING_BIN} is below minimum ${JJ_MIN_VERSION}; refusing to overwrite"
      exit 1
    fi
  fi
fi

if ! resolve_release "${SUFFIX}"; then
  if [[ -n "${EXISTING_BIN}" && -n "${EXISTING_VER}" ]] && version_ge "${EXISTING_VER}" "${JJ_MIN_VERSION}" && [[ -z "${EXPLICIT}" ]]; then
    report "reuse" "${EXISTING_BIN}" "${EXISTING_VER}" \
      "release resolution failed; reusing compatible installed JJ ${EXISTING_VER}"
    exit 0
  fi
  report "error" "${EXISTING_BIN}" "${EXISTING_VER}" \
    "could not resolve JJ release and no compatible install available"
  exit 1
fi

if [[ -n "${EXISTING_BIN}" && -n "${EXISTING_VER}" ]] && is_managed "${EXISTING_BIN}" && [[ "${EXISTING_VER}" == "${RESOLVED_VERSION}" ]]; then
  report "reuse" "${EXISTING_BIN}" "${EXISTING_VER}" "managed JJ already at target ${RESOLVED_VERSION}"
  exit 0
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT
TARBALL="${TMPDIR}/jj.tar.gz"
log "Downloading JJ v${RESOLVED_VERSION} (${RESOLVED_SOURCE}) for ${SUFFIX}..."
if ! curl -fsSL --max-time "${NETWORK_TIMEOUT}" -o "${TARBALL}" "${RESOLVED_URL}"; then
  report "error" "${EXISTING_BIN}" "${EXISTING_VER}" "download failed; prior executable preserved if present"
  exit 1
fi

if [[ -n "${RESOLVED_SHA256}" ]]; then
  actual="$(sha256_file "${TARBALL}")"
  if [[ "${actual}" != "${RESOLVED_SHA256}" ]]; then
    report "error" "${EXISTING_BIN}" "${EXISTING_VER}" "SHA-256 mismatch; prior executable preserved if present"
    exit 1
  fi
fi

tar -xzf "${TARBALL}" -C "${TMPDIR}"
if [[ ! -f "${TMPDIR}/jj" ]]; then
  # Some archives nest the binary; find leaf named jj
  found="$(find "${TMPDIR}" -type f -name jj | head -1 || true)"
  if [[ -z "${found}" ]]; then
    report "error" "${EXISTING_BIN}" "${EXISTING_VER}" "jj binary not found in tarball"
    exit 1
  fi
  cp "${found}" "${TMPDIR}/jj"
fi
chmod +x "${TMPDIR}/jj"

if ! atomic_install "${TMPDIR}/jj" "${MANAGED_BINARY}" "${RESOLVED_VERSION}"; then
  report "error" "${EXISTING_BIN}" "${EXISTING_VER}" "install failed; prior executable preserved if present"
  exit 1
fi

integrity_note="no official digest for this tag"
[[ -n "${RESOLVED_SHA256}" ]] && integrity_note="sha256 verified"
report "install" "${MANAGED_BINARY}" "${RESOLVED_VERSION}" \
  "installed JJ ${RESOLVED_VERSION} to ${MANAGED_BINARY} (resolved via ${RESOLVED_SOURCE}, ${integrity_note})"

if ! command -v jj >/dev/null 2>&1; then
  log ""
  log "Warning: ${INSTALL_DIR} is not in your PATH."
  log "Add it with:"
  log "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
fi

exit 0

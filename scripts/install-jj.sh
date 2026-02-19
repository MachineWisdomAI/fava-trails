#!/usr/bin/env bash
# Install Jujutsu (JJ) pre-built binary for linux-x86_64
# Downloads to ~/.local/bin/jj
set -euo pipefail

JJ_VERSION="${JJ_VERSION:-0.28.0}"
INSTALL_DIR="${HOME}/.local/bin"
BINARY="${INSTALL_DIR}/jj"

if command -v jj &>/dev/null; then
    echo "JJ already installed: $(jj version)"
    exit 0
fi

mkdir -p "${INSTALL_DIR}"

ARCH=$(uname -m)
case "${ARCH}" in
    x86_64) ARCH_SUFFIX="x86_64-unknown-linux-musl" ;;
    aarch64) ARCH_SUFFIX="aarch64-unknown-linux-musl" ;;
    *) echo "Unsupported architecture: ${ARCH}" >&2; exit 1 ;;
esac

URL="https://github.com/jj-vcs/jj/releases/download/v${JJ_VERSION}/jj-v${JJ_VERSION}-${ARCH_SUFFIX}.tar.gz"

echo "Downloading JJ v${JJ_VERSION} for ${ARCH}..."
TMPDIR=$(mktemp -d)
trap 'rm -rf "${TMPDIR}"' EXIT

curl -fsSL "${URL}" -o "${TMPDIR}/jj.tar.gz"
tar -xzf "${TMPDIR}/jj.tar.gz" -C "${TMPDIR}"

# The binary is at the root of the tarball
cp "${TMPDIR}/jj" "${BINARY}"
chmod +x "${BINARY}"

echo "Installed: $(${BINARY} version)"
echo "Make sure ${INSTALL_DIR} is in your PATH"

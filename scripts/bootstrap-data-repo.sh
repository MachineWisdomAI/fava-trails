#!/usr/bin/env bash
# Bootstrap a FAVA Trail data repo from an empty git clone.
#
# Usage:
#   bash scripts/bootstrap-data-repo.sh /path/to/fava-trail-data
#
# Prerequisites:
#   - JJ installed (run scripts/install-jj.sh first)
#   - The target directory is a fresh git clone with a remote (empty repo on GitHub, etc.)
#
# What this script does:
#   1. Validates the directory is an empty git repo with an origin remote
#   2. Creates config.yaml and .gitignore (the only two files needed)
#   3. Commits and pushes via git (bootstrap only — before JJ takes over)
#   4. Initializes JJ colocated mode and tracks the remote main bookmark
#   5. Prints the FAVA_TRAIL_DATA_REPO value for MCP configuration
#
# After this, use MCP tools (save_thought, recall, etc.) for all trail operations.
# NEVER use 'git push origin main' again — JJ manages all commits from this point.

set -euo pipefail

# ─── Argument parsing ───

DATA_REPO="${1:-}"
if [[ -z "${DATA_REPO}" ]]; then
    echo "Usage: $(basename "$0") /path/to/fava-trail-data" >&2
    echo "" >&2
    echo "The path must point to a freshly cloned empty git repo." >&2
    echo "Example:" >&2
    echo "  git clone https://github.com/YOUR-ORG/fava-trail-data.git" >&2
    echo "  $(basename "$0") fava-trail-data" >&2
    exit 1
fi

# Resolve to absolute path
DATA_REPO="$(cd "${DATA_REPO}" 2>/dev/null && pwd)" || {
    echo "Error: directory '${1}' does not exist." >&2
    exit 1
}

# ─── Validate prerequisites ───

# JJ must be installed
if ! command -v jj &>/dev/null; then
    echo "Error: jj not found. Run scripts/install-jj.sh first." >&2
    exit 1
fi

# Must be a git repo
if [[ ! -d "${DATA_REPO}/.git" ]]; then
    echo "Error: '${DATA_REPO}' is not a git repo (no .git/ directory)." >&2
    echo "Clone an empty repo first: git clone https://github.com/YOUR-ORG/fava-trail-data.git" >&2
    exit 1
fi

# Must have an origin remote
REMOTE_URL=$(git -C "${DATA_REPO}" remote get-url origin 2>/dev/null) || {
    echo "Error: no 'origin' remote configured in '${DATA_REPO}'." >&2
    echo "The data repo must be cloned from a remote (GitHub, etc.) for sync to work." >&2
    exit 1
}

# Must be empty (no tracked files)
FILE_COUNT=$(git -C "${DATA_REPO}" ls-files | wc -l)
if [[ "${FILE_COUNT}" -gt 0 ]]; then
    echo "Error: '${DATA_REPO}' is not empty (${FILE_COUNT} tracked files found)." >&2
    echo "This script expects a freshly cloned empty repo." >&2
    echo "If you want to start over, delete and re-clone the repo." >&2
    exit 1
fi

# Must not already have JJ
if [[ -d "${DATA_REPO}/.jj" ]]; then
    echo "Error: '${DATA_REPO}' already has a .jj/ directory." >&2
    echo "JJ is already initialized. Delete .jj/ to re-bootstrap, or use the repo as-is." >&2
    exit 1
fi

echo "Bootstrapping FAVA Trail data repo at: ${DATA_REPO}"
echo "Remote: ${REMOTE_URL}"
echo ""

# ─── Step 1: Create config.yaml ───

cat > "${DATA_REPO}/config.yaml" <<EOF
trails_dir: trails
remote_url: "${REMOTE_URL}"
push_strategy: immediate
EOF

echo "[1/5] Created config.yaml (push_strategy: immediate)"

# ─── Step 2: Create .gitignore ───
# CRITICAL: Do NOT add trails/ here. Trails are subdirectories of the monorepo,
# not nested repos. Their thought files must be tracked by git.

cat > "${DATA_REPO}/.gitignore" <<'EOF'
.jj/
__pycache__/
*.pyc
.venv/
EOF

echo "[2/5] Created .gitignore (trails/ is NOT excluded — monorepo design)"

# ─── Step 3: Git commit + push (bootstrap only) ───

git -C "${DATA_REPO}" add config.yaml .gitignore
git -C "${DATA_REPO}" commit -q -m "Bootstrap fava-trail-data"
git -C "${DATA_REPO}" push -q origin HEAD:main 2>/dev/null || \
    git -C "${DATA_REPO}" push -q origin HEAD:main --set-upstream 2>/dev/null || {
        echo "Warning: git push failed. You may need to push manually." >&2
    }

echo "[3/5] Committed and pushed bootstrap via git (last time git push is used)"

# ─── Step 4: Initialize JJ colocated mode ───
# jj git init doesn't support -R, must run from inside the directory
# Capture output first, then filter — grep -v exits 1 when all lines are filtered,
# which triggers pipefail and causes a false "failed" report.

INIT_OUT=$(cd "${DATA_REPO}" && jj git init --colocate 2>&1) || {
    echo "Error: jj git init --colocate failed." >&2
    echo "${INIT_OUT}" >&2
    exit 1
}
echo "${INIT_OUT}" | grep -v "^Hint:" || true

echo "[4/5] Initialized JJ colocated mode (.jj/ created)"

# ─── Step 5: Track remote main bookmark ───

if ! (cd "${DATA_REPO}" && jj bookmark track main@origin 2>/dev/null); then
    # main@origin doesn't exist yet (first push) — create bookmark and retry tracking
    (cd "${DATA_REPO}" && jj bookmark create main -r @- 2>/dev/null) || true
    (cd "${DATA_REPO}" && jj bookmark track main@origin 2>/dev/null) || {
        echo "Warning: could not track main@origin; auto-push may not work until you run: jj bookmark track main@origin" >&2
    }
fi

echo "[5/5] JJ bookmark 'main' tracking origin"

# ─── Done ───

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Data repo ready: ${DATA_REPO}"
echo ""
echo "Set this environment variable in your MCP config:"
echo ""
echo "  FAVA_TRAIL_DATA_REPO=${DATA_REPO}"
echo ""
echo "Example MCP registration (~/.claude.json or claude_desktop_config.json):"
echo ""
echo '  "fava-trail": {'
echo '    "type": "stdio",'
echo '    "command": "uv",'
echo '    "args": ["run", "--directory", "/path/to/fava-trail", "fava-trail-server"],'
echo "    \"env\": { \"FAVA_TRAIL_DATA_REPO\": \"${DATA_REPO}\" }"
echo '  }'
echo ""
echo "From here, use MCP tools for all trail operations."
echo "NEVER use 'git push origin main' — JJ manages commits now."
echo "If you need to push manually: jj bookmark set main -r @- && jj git push --bookmark main"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

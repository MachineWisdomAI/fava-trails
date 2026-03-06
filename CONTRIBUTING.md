# Contributing to FAVA Trails

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Prerequisites

- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
- **JJ (Jujutsu)** — required for running tests (FAVA Trails uses JJ as its VCS engine)
- **uv** — Python package manager ([docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/))

### Install JJ

```bash
fava-trails install-jj
```

This downloads a pre-built binary for your platform to `~/.local/bin/jj`. Supports Linux (x86_64, aarch64) and macOS (x86_64, arm64). Make sure `~/.local/bin` is in your `PATH`. Alternatively, install manually from [jj-vcs.github.io/jj](https://jj-vcs.github.io/jj/).

## Setup

```bash
# Clone the repo
git clone https://github.com/MachineWisdomAI/fava-trails.git
cd fava-trails

# Install dependencies (including dev tools)
uv sync
```

## Running Tests

```bash
uv run pytest -v
```

Tests create temporary JJ repositories in isolated directories — no external data repo required.

## Linting

```bash
uv run ruff check src/ tests/
```

All PRs must pass ruff with zero errors.

## Making Changes

1. Fork the repo and create a branch: `git checkout -b fix/my-fix`
2. Make your changes
3. Run tests and linting to verify everything passes
4. Push your branch and open a pull request

## PR Expectations

- Tests pass (`uv run pytest -v` exits 0)
- Lint passes (`uv run ruff check src/ tests/` exits 0)
- **PR title follows [Conventional Commits](https://www.conventionalcommits.org/)** (e.g., `feat: add X`, `fix: resolve Y`, `chore: update Z`) — enforced by CI
- One logical change per PR — keep PRs focused

## Testing and Release Process

FAVA Trails is used as a live MCP server, so changes need validation beyond unit tests.

### 1. Automated checks (CI)

Every PR runs:
- **test** — `uv run pytest -v`
- **Semantic PR** — validates PR title follows Conventional Commits

Both must pass before merge.

### 2. Dog-food locally (post-merge, pre-release)

After merging to `main`, point your MCP server at the dev copy to test with real usage:

```jsonc
// In ~/.claude.json, change the fava-trails server entry:
"args": [
  "run", "--directory",
  "/home/younes/git/MachineWisdomAI/fava-trails",  // dev copy
  "fava-trails-server"
]
```

Restart your MCP client (e.g., Claude Code) and use it for real work. Test the specific changes you made — save thoughts, recall, sync, etc. Use it for at least a working session before releasing.

### 3. Release to PyPI

Once dog-fooding confirms the changes work:

1. Bump version in `pyproject.toml`
2. Push the version bump via PR, merge to `main`
3. Create a GitHub Release: `gh release create vX.Y.Z --generate-notes`
4. CI builds, verifies the tag matches `pyproject.toml`, and publishes to PyPI
5. Update the vendor copy:
   ```bash
   cd ~/git/vendor/fava-trails
   git fetch && git checkout vX.Y.Z
   ```
6. Revert `~/.claude.json` back to the vendor path
7. Restart your MCP client

## Reporting Issues

Use the [bug report template](https://github.com/MachineWisdomAI/fava-trails/issues/new?template=bug_report.yml). Include your JJ version (`jj --version`), OS, Python version, and steps to reproduce.

For security vulnerabilities, please use [GitHub Security Advisories](https://github.com/MachineWisdomAI/fava-trails/security/advisories/new) — do not file public issues for security bugs.

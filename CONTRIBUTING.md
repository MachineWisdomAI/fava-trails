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

This **reuses** any already-installed JJ at or above the supported minimum (**0.28.0**), including newer versions. It never silently downgrades or overwrites a user-managed `jj`. When installation is needed, it resolves the current official GitHub stable release into the managed path `~/.local/bin/jj` (override with `--version` / `JJ_VERSION` for reproducible environments). Supports Linux (x86_64, aarch64) and macOS (x86_64, arm64). Make sure `~/.local/bin` is in your `PATH` if you rely on the managed binary. From a source checkout you can also run `scripts/install-jj.sh` (thin wrapper around the same Python installer). Alternatively, install manually from [jj-vcs.github.io/jj](https://jj-vcs.github.io/jj/). See [docs/jj-compatibility.md](docs/jj-compatibility.md).

## Working in this repository

Read this section before you change source, whether you are a person or an agent.

1. **Preflight.** From your checkout, run:
   ```bash
   git worktree list && git branch -r
   ```
   Done when you know every active worktree and remote branch. If another agent or branch is already working in this repository, coordinate with it or use a separate worktree.
2. **Work on a feature branch in your own worktree,** for example `git worktree add ../fava-trails-<slug> -b <type>/<slug>`. Never commit directly to `main`; land changes through a pull request.
3. **Leave installed runtimes alone.** Treat any installed or vendored FAVA Trails checkout that a running MCP client launches as read-only. Do not edit it, and do not touch live FAVA Trails instances you did not create. Develop in your own checkout and point a test client at it only as described under "Dog-food locally" below.
4. **Version bump.** Follow [docs/version-policy.md](docs/version-policy.md): bump affected product versions in the original change PR and run the repository-local updater before review. Documentation, tests, CI and development checks alone need no bump. Editing `AGENTS_USAGE_INSTRUCTIONS.md` does need one: it is shipped in the package.
5. **Open the pull request** with a Conventional Commits title, as described under "PR Expectations".

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

1. Run the preflight in [Working in this repository](#working-in-this-repository), then fork the repo (or use a worktree) and create a branch: `git checkout -b fix/my-fix`
2. Make your changes
3. Run tests and linting to verify everything passes
4. Push your branch and open a pull request

## PR Expectations

- Tests pass (`uv run pytest -v` exits 0)
- Lint passes (`uv run ruff check src/ tests/` exits 0)
- **PR title follows [Conventional Commits](https://www.conventionalcommits.org/)** (e.g., `feat: add X`, `fix: resolve Y`, `chore: update Z`) — enforced by CI
- One logical change per PR — keep PRs focused
- A behavior change updates its owning document and the summaries that repeat it in the same delivery scope; see [documentation ownership](docs/documentation-ownership.md) and the design records in [blueprints/](blueprints/README.md). See [Maintaining Blueprints](docs/blueprint-maintenance.md) for how to choose and update design records.

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
  "<path-to-your-fava-trails-checkout>",  // dev copy
  "fava-trails-server"
]
```

Restart your MCP client (e.g., Claude Code) and use it for real work. Test the specific changes you made — save thoughts, recall, sync, etc. Use it for at least a working session before releasing.

**Important:** a client config that uses `uv run --directory <checkout>` or a
vendor path keeps that tree active even after `pip install -U fava-trails`.
Run `fava-trails version` (or `fava-trails doctor`) in the same environment the
client launches to see package/module version, module path, and MCP SDK version
without printing credentials. See
[docs/runtime-and-upgrade.md](docs/runtime-and-upgrade.md).

Before tagging, build candidate artifacts from the immutable reviewed commit and
run the packaging gates against **those exact files**:

```bash
uv build
export FAVA_CANDIDATE_WHEEL=$(ls dist/*.whl)
export FAVA_CANDIDATE_SDIST=$(ls dist/*.tar.gz)
sha256sum dist/*.whl dist/*.tar.gz | tee candidate-SHA256SUMS
uv run pytest tests/test_packaged_mcp.py tests/test_governance.py tests/test_mcp_protocol.py tests/test_runtime_info.py -v
sha256sum -c candidate-SHA256SUMS
```

Until PyPI/GitHub release metadata match that candidate, label the work **merged
but unreleased**.

### 3. Release to PyPI

Once dog-fooding confirms the changes work:

Release candidates use the same flow with a PEP 440 tag `vX.Y.ZrcN` that equals
the `pyproject.toml` version (for example `v0.8.4rc1`). The Release workflow
publishes it as a GitHub prerelease (never `latest`); installers get it only with
`pip install --pre` or an exact pin. The version is set in the source PR by
`scripts/mw-version.py` (see `docs/version-policy.md`), never at tag time.
Promotion to stable uses the `chore(release): promote version` PR.

1. Bump version in `pyproject.toml`
2. Push the version bump via PR, merge to `main`
3. Create and push an immutable tag on the reviewed commit:
   `git tag vX.Y.Z <sha> && git push origin vX.Y.Z`
   Do **not** create the GitHub Release yet — validation must run first.
4. Owner runs the **Release** workflow (`workflow_dispatch`, GitHub Environment
   `fava-release`) with input `tag=vX.Y.Z`. CI resolves draft-resume state first,
   then proves `refs/tags/vX.Y.Z` peels to checked-out `HEAD` and either equals
   current protected `origin/main` (first publish) or is an ancestor of it
   (draft resume after main may have advanced), builds once, runs packaged gates
   on the exact wheel+sdist (including sdist install and 0.6.0 upgrade), stages
   or normalizes a **draft** GitHub Release (with `candidate-SHA256SUMS` and
   verified title/notes/target), publishes those same artifacts to PyPI,
   verifies published PyPI SHA-256 against `candidate-SHA256SUMS` (fail closed),
   then undrafts the Release only after that proof (reruns may resume a matching
   draft after metadata normalize; provenance env is `$GITHUB_ENV`-inherited, not
   expression-remapped).
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

# Plan 13: OSS Readiness for Early Adopters

**Status:** complete
**Spec:** `codev/specs/13-oss-readiness.md`
**Epic:** 0005a-adoption
**Prerequisites:** Spec 12 (rebrand) must be integrated first

---

## Phases (Machine Readable)

<!-- REQUIRED: porch uses this JSON to track phase progress. -->

```json
{
  "phases": [
    {"id": "phase_1", "title": "Documentation, Metadata & Scaffolding"},
    {"id": "phase_2", "title": "Security Audit, PyPI Publishing & Release Prep"}
  ]
}
```

---

## Phase 1: Documentation, Metadata & Scaffolding

Create all OSS scaffolding files and update metadata. Mechanical changes with no functional code modifications.

### 1a: pyproject.toml Metadata

- Set `version = "0.4.0"` (first post-rebrand public version)
- Add `license = {text = "Apache-2.0"}`
- Add `authors = [{name = "Machine Wisdom Solutions Inc."}]`
- Add `readme = "README.md"` (required for PyPI description rendering)
- Add `requires-python = ">=3.11"` (minimum supported version)
- Add trove classifiers:
  - `License :: OSI Approved :: Apache Software License`
  - `Programming Language :: Python :: 3`
  - `Programming Language :: Python :: 3.11`
  - `Topic :: Software Development :: Libraries`
  - `Intended Audience :: Developers`
  - `Development Status :: 4 - Beta`
- Add `[project.urls]`:
  - `Homepage = "https://github.com/MachineWisdomAI/fava-trails"`
  - `Repository = "https://github.com/MachineWisdomAI/fava-trails"`
  - `Issues = "https://github.com/MachineWisdomAI/fava-trails/issues"`
- Verify `src/fava_trails/__init__.py` has `__version__ = "0.4.0"` matching pyproject.toml

### 1b: README Example Fixes

Add `trail_name` parameter to all "Use it" tool call examples in README.md. Currently examples omit this required parameter — guaranteed "broken on arrival" for new users.

### 1c: GitHub Actions CI

Create `.github/workflows/test.yml`:

```yaml
name: Tests
on:
  push:
  pull_request:
  workflow_dispatch:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install JJ
        run: |
          bash scripts/install-jj.sh
          echo "$HOME/.local/bin" >> $GITHUB_PATH
      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: uv sync --frozen
      - name: Lint
        run: uv run ruff check src/ tests/
      - name: Run tests
        run: uv run pytest -v
        env:
          JJ_CONFIG: /dev/null
```

Notes:
- `workflow_dispatch:` allows manual test runs without pushing commits — useful for CI debugging
- `JJ_CONFIG: /dev/null` ensures tests are hermetic (JJ ignores any developer-local user config in CI)
- `python-version: "3.11"` pins to minimum supported version
- `scripts/install-jj.sh` downloads a pre-built musl binary with `JJ_VERSION=0.28.0` pinned — fast CI
- The `$GITHUB_PATH` append makes `jj` available in subsequent steps

### 1d: Issue Templates

Create `.github/ISSUE_TEMPLATE/bug_report.yml` with fields:
- Description
- Steps to reproduce
- Expected vs actual behavior
- JJ version (`jj --version`)
- OS and Python version
- FAVA Trails version (`pip show fava-trails`)

### 1e: CONTRIBUTING.md

Create `CONTRIBUTING.md` covering:
- Prerequisites (Python >= 3.11, JJ, uv)
- Install: `uv sync`
- Run tests: `uv run pytest -v`
- Lint: `uv run ruff check src/ tests/`
- PR expectations (tests pass, ruff clean, descriptive commit messages)
- Note: `codev/` directory is internal development methodology — external contributors are not expected to use SPIR

### 1f: CHANGELOG.md

Create `CHANGELOG.md` with entries from v0.1.0 through v0.4.0:
- v0.1.0 — Initial release (foundation, 15 MCP tools)
- v0.2.0 — Trust Gate, hierarchical scoping
- v0.3.0 — Storage substrate amendments (monorepo, conflict interception)
- v0.3.1 — Recall enhancements (multi-scope search, preferences auto-surface)
- v0.3.2 — MCP server instructions field, get_usage_guide tool
- v0.3.3 — Scope discovery reliability fix, CLI spec
- v0.4.0 — Rebrand to FAVA Trails, OSS readiness, CLI

Include an "Upgrading from fava-trails to fava-trails" section under v0.4.0:
- Package renamed: `fava-trails` → `fava-trails`
- Import renamed: `fava_trails` → `fava_trails`
- Entry point renamed: `fava-trails-server` → `fava-trails-server`
- Update MCP config `command` field accordingly

### 1g: SECURITY.md

Create `SECURITY.md` (minimal file, per consultation consensus):
- Supported versions table (Python ≥3.11, JJ ≥0.28.0)
- Vulnerability disclosure: use GitHub Security Advisories (private channel), not public issues
- Contact: link to `https://github.com/MachineWisdomAI/fava-trails/security/advisories/new`
- Note that vulnerability discussion should not happen in public issues

---

## Phase 2: Security Audit, PyPI Publishing & Release Prep

Validate security posture and publish the package. These steps run after all Phase 1 files are committed.

### 2a: Security Audit

Before going public (per consultation consensus — gitleaks covers git history, not just working tree):

1. Install gitleaks: download binary from GitHub releases (`gitleaks/gitleaks`)
2. Scan full git history: `gitleaks detect --source . --redact`
3. Verify `.env` is in `.gitignore` (check `.gitignore` content)
4. Verify no credentials in test fixtures: `grep -r "sk-\|password\|secret\|token" tests/ src/` (targeted grep for obvious patterns)
5. Scrub internal-only references from public-facing docs:
   - README.md: remove Agent Farm / Pal MCP references that would confuse external users
   - CONTRIBUTING.md: confirm `codev/` is explained as internal methodology
6. Document audit results in PR description

### 2b: PyPI First Publish (Upgraded from Deferred)

Per consultation consensus (all 3 models) and Desktop cross-agent review: PyPI publishing is the difference between evaluation and abandonment. Included in this pass.

1. Build the package: `uv build`
2. Verify wheel content: `python -m zipfile -l dist/fava_trails-0.4.0-py3-none-any.whl`
3. First manual publish: `uv publish` (requires `UV_PUBLISH_TOKEN` env var with PyPI API token)
4. Add `.github/workflows/release.yml` for future automated releases using Trusted Publishing (OIDC → PyPI):

```yaml
name: Release
on:
  push:
    tags: ["v*"]

permissions:
  contents: read
  id-token: write  # REQUIRED for OIDC Trusted Publishing

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: "3.11"
      - run: uv build
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          attestations: true
```

Note: `id-token: write` is mandatory for OIDC Trusted Publishing — without it GitHub will not issue the OIDC token and the publish step will fail with a permissions error.

### 2c: GitHub Topics + Release (Post-Merge)

Create version-scoped release notes first, then create the release:
```bash
# Extract only the v0.4.0 section from CHANGELOG.md
sed -n '/^## \[0.4.0\]/,/^## \[/p' CHANGELOG.md | head -n -1 > /tmp/release-notes-v0.4.0.md

gh repo edit --add-topic mcp,ai-agents,memory,jujutsu,python,mcp-server
gh release create v0.4.0 --title "v0.4.0 — FAVA Trails" --notes-file /tmp/release-notes-v0.4.0.md
```

Note: Use version-scoped notes (not entire CHANGELOG.md) — GitHub renders the full file as release notes otherwise, which is noisy.

---

## Done Criteria

- `pip show fava-trails` displays correct license (`Apache-2.0`), version (`0.4.0`), and URLs
- README "Use it" examples execute without errors when copy-pasted
- GitHub Actions CI passes on a fresh PR
- Issue templates render correctly on GitHub
- CONTRIBUTING.md and CHANGELOG.md exist and are linked from README
- SECURITY.md exists with vulnerability disclosure instructions
- gitleaks scan clean (no secrets in working tree or git history)
- Package published to PyPI (`pip install fava-trails` works)
- All 127+ tests pass

## Human Merge Checklist

- [ ] GitHub Actions workflow correct (JJ install works on Ubuntu, `JJ_CONFIG: /dev/null` is present)
- [ ] License metadata matches LICENSE file (Apache-2.0 in pyproject.toml + LICENSE)
- [ ] gitleaks scan clean (no API keys, internal paths, hostnames in history)
- [ ] README golden-path examples work when copy-pasted
- [ ] `pip install fava-trails` works after PyPI publish

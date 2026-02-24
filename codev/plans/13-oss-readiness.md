# Plan 13: OSS Readiness for Early Adopters

**Status:** not started
**Spec:** `codev/specs/13-oss-readiness.md`
**Epic:** 0005a-adoption
**Prerequisites:** Spec 12 (rebrand) must be integrated first

---

## Phase 1: Single-Pass OSS Polish

All items are mechanical scaffolding with no functional code changes. One phase, one builder.

### 1a: pyproject.toml Metadata

- Set `version = "0.4.0"` (first post-rebrand public version)
- Add `license = {text = "Apache-2.0"}`
- Add `authors = [{name = "Machine Wisdom Solutions Inc."}]`
- Add `[project.urls]`:
  - `Homepage = "https://github.com/MachineWisdomAI/fava-trails"`
  - `Repository = "https://github.com/MachineWisdomAI/fava-trails"`
  - `Issues = "https://github.com/MachineWisdomAI/fava-trails/issues"`

### 1b: README Example Fixes

Add `trail_name` parameter to all "Use it" tool call examples in README.md. Currently examples omit this required parameter — guaranteed "broken on arrival" for new users.

### 1c: GitHub Actions CI

Create `.github/workflows/test.yml`:

```yaml
name: Tests
on: [push, pull_request]
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
      - name: Install dependencies
        run: uv sync
      - name: Run tests
        run: uv run pytest -v
      - name: Lint
        run: uv run ruff check src/ tests/
```

`scripts/install-jj.sh` already downloads a pre-built musl binary (not cargo compile) with version pinned via `JJ_VERSION=0.28.0` env var — CI will be fast. The `$GITHUB_PATH` append makes `jj` available in subsequent steps. Ensure tests are hermetic (no developer-local jj config dependencies).

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

### 1g: Security Audit

Before going public:
- `grep -r` for API keys, internal hostnames, hardcoded paths
- Verify `.env` is in `.gitignore`
- Verify no credentials in test fixtures
- Scrub internal-only references from public-facing docs (Agent Farm, Pal MCP, internal project names)

### 1h: Upgrade Notes

Add "Upgrade from fava-trail to fava-trails" section in CHANGELOG or README:
- Package renamed: `fava-trail` → `fava-trails`
- Import renamed: `fava_trail` → `fava_trails`
- Entry point renamed: `fava-trail-server` → `fava-trails-server`
- Update MCP config accordingly

### 1i: PyPI Publishing (Deferred — Fast Follow)

Per the Desktop cross-agent review (thought `01KJ83Z750Y7TED496WNC5DW73`): PyPI publishing is near-term critical — trial friction is the difference between evaluation and abandonment. Not blocking v0.4.0 launch, but treat as a fast-follow task:
- Add `release.yml` GitHub Actions workflow using Trusted Publishing (OIDC → PyPI, no stored secrets)
- Add PyPI trove classifiers to pyproject.toml
- First manual `uv publish` or `twine upload` for v0.4.0, then automate

### 1j: GitHub Topics + Release (Post-Merge)

Document `gh` commands to run after merge + repo rename (Wave 3):
```bash
gh repo edit --add-topic mcp,ai-agents,memory,jujutsu,python,mcp-server
gh release create v0.4.0 --title "v0.4.0 — FAVA Trails" --notes-file CHANGELOG.md
```

---

## Done Criteria

- `pip show fava-trails` displays correct license (`Apache-2.0`), version (`0.4.0`), and URLs
- README "Use it" examples execute without errors when copy-pasted
- GitHub Actions CI passes on a fresh PR
- Issue templates render correctly on GitHub
- CONTRIBUTING.md and CHANGELOG.md exist and are linked from README
- No secrets, internal paths, or sensitive data exposed (grep audit clean)
- All 127+ tests pass

## Human Merge Checklist

- [ ] GitHub Actions workflow correct (JJ install works on Ubuntu, tests hermetic)
- [ ] License metadata matches LICENSE file (Apache-2.0 in pyproject.toml + LICENSE)
- [ ] Secrets scan clean (no API keys, internal paths, hostnames)
- [ ] README golden-path examples work when copy-pasted

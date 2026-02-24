# Review: Spec 13 — OSS Readiness for Early Adopters

**Date**: 2026-02-24
**Protocol**: ASPIR
**Epic**: 0005a-adoption
**Status**: Complete

---

## Spec vs. Implementation

| Spec Item | Status | Notes |
|-----------|--------|-------|
| Repo public at `MachineWisdomAI/fava-trails` | Deferred (human action) | Requires repo visibility flip — cannot be automated |
| `pip show fava-trails` shows Apache-2.0, 0.4.0, URLs | ✓ Complete | pyproject.toml fully updated |
| README examples execute without errors | ✓ Complete | trail_name added to all 3 examples |
| GitHub Actions CI on every PR | ✓ Complete | test.yml with workflow_dispatch |
| Issue templates render correctly | ✓ Complete | bug_report.yml with required fields |
| CONTRIBUTING.md exists and linked from README | ✓ Complete | |
| CHANGELOG.md exists and linked from README | ✓ Complete | |
| SECURITY.md exists | ✓ Complete | GitHub Security Advisories disclosure |
| GitHub topics set | Deferred (human action) | Post-merge `gh repo edit` command documented |
| GitHub Release created | Deferred (human action) | Post-merge `gh release create` command documented |
| All 128+ tests pass | ✓ Complete | 128 tests pass |
| No secrets/sensitive data exposed | ✓ Complete | gitleaks scan clean |

---

## Issues Encountered Across Phases

### Pre-existing ruff lint failures

**Phase 1** discovered 65 ruff lint errors in the existing codebase that would have caused CI to fail immediately after launch. The errors were not introduced by this spec — they were pre-existing. 59 were auto-fixed by `ruff --fix`, 6 required manual intervention:

- UP042: `str, Enum` → `StrEnum` (models.py)
- B904: `raise ... from err` (server.py)
- F841: unused variables in tests

These were fixed as part of Phase 1. All 128 tests continue to pass after the fixes.

**Lesson**: Before introducing CI that runs ruff, run ruff locally first to verify the baseline is clean.

### sdist incomplete

**Phase 1 code review** identified that the sdist include list omitted `README.md` and `LICENSE`. Since `readme = "README.md"` is referenced in pyproject.toml, PyPI would fail to render the package description without it. Fixed immediately.

**Lesson**: Always verify sdist contents with `uv build` + `python -m tarfile -l` before declaring packaging complete.

### release.yml missing attestations:write

**Phase 2 code review** identified that `attestations: true` in pypa/gh-action-pypi-publish requires both `id-token: write` (OIDC) and `attestations: write` (SLSA provenance). Without it, the release job would silently fail at the attestation upload step.

**Lesson**: When using GitHub Actions attestations features, check both the `id-token: write` and `attestations: write` permissions.

### CHANGELOG premature PyPI claim

The initial CHANGELOG draft claimed "Package now available via pip install fava-trails" before the package was actually published. Corrected to describe the workflow addition.

**Lesson**: CHANGELOG entries should describe what was done, not the future result. Don't write "now available" until the thing is actually available.

---

## Architecture Updates

*See `codev/resources/architectural-choices.md` for the full architecture doc.*

### CI/CD Architecture Added (new)

FAVA Trails now has a GitHub Actions CI/CD setup:

- **test.yml**: Runs on push, pull_request, and workflow_dispatch. Linux-only (JJ musl binary). Installs JJ via `scripts/install-jj.sh` (pre-built binary, ~5s). `JJ_CONFIG: /dev/null` for test hermeticity. Lint-first, then tests.

- **release.yml**: Tag-based Trusted Publishing to PyPI. OIDC authentication (`id-token: write`). SLSA provenance attestations (`attestations: write`). No stored API keys.

### Package Publishing Architecture (new)

Package is now fully described in pyproject.toml for PyPI distribution:
- Version: 0.4.0 (semantic versioning, post-rebrand)
- License: Apache-2.0 (explicit `{text = "Apache-2.0"}` field)
- Authors: Machine Wisdom Solutions Inc.
- URLs: Homepage, Repository, Issues
- Classifiers: Beta, Apache-2.0, Python 3, Developers, Libraries

First publish is manual (`uv publish`). Subsequent releases automated via release.yml on `v*` tag push.

---

## Lessons Learned Updates

*See `codev/resources/lessons-learned.md` for the accumulated lessons doc.*

### New Lessons

1. **Run lint locally before introducing CI**: If CI is a new addition to a project, run the linter on the existing codebase first. Pre-existing violations will cause the first CI run to fail, creating a poor first impression for external contributors.

2. **Verify sdist contents with `uv build` + file inspection**: Packaging `readme = "README.md"` in pyproject.toml is not enough — the sdist include list must explicitly include the file or PyPI will render a blank description. Always inspect with `python -m tarfile -l dist/*.tar.gz`.

3. **GitHub Actions attestations require two permissions**: `pypa/gh-action-pypi-publish` with `attestations: true` needs both `id-token: write` (OIDC for Trusted Publishing) and `attestations: write` (SLSA provenance). Missing either causes a silent release failure.

4. **CHANGELOG should describe actuals, not futures**: Write "Added release workflow for tag-based PyPI publishing" not "Package now available via pip install" until the publish actually happens. Premature availability claims confuse users and damage trust.

5. **JJ hermeticity in CI via `JJ_CONFIG: /dev/null`**: JJ reads user config from `~/.config/jj/config.toml` by default. In CI, if a developer's local config is somehow present (e.g., Docker with mounted home), tests can behave differently. `JJ_CONFIG: /dev/null` forces JJ to use defaults-only, making tests hermetic.

---

## Post-Merge Checklist (Human Actions)

The following items require human action after the PR is merged and the repo is made public:

```bash
# 1. First PyPI publish (requires PyPI account + token)
UV_PUBLISH_TOKEN=<your-token> uv publish

# 2. Set up Trusted Publishing on PyPI for future releases
# Go to: https://pypi.org/manage/account/publishing/
# Configure: owner=MachineWisdomAI, repo=fava-trails, workflow=release.yml

# 3. Set GitHub topics
gh repo edit --add-topic mcp,ai-agents,memory,jujutsu,python,mcp-server

# 4. Create GitHub release with version-scoped notes
sed -n '/^## \[0\.4\.0\]/,/^## \[/p' CHANGELOG.md | sed '$d' > /tmp/release-notes.md
gh release create v0.4.0 --title "v0.4.0 — FAVA Trails" --notes-file /tmp/release-notes.md

# 5. Flip repo visibility to public
gh repo edit --visibility public
```

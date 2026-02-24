# Spec 13 — Rebuttal for Iteration 1 Consultation Feedback

**Date**: 2026-02-24
**Models**: GPT-5.1-Codex (for), Gemini 3 Pro (against), O3-Pro (neutral)

## Summary of Feedback Themes

All three models rated the spec highly (7/10, 9/10, 8/10) and agreed it is technically feasible as a single-pass polish. The key concerns were:

1. Security audit methodology (manual grep vs. tooled scan)
2. JJ CI hermeticity (local config bleed risk)
3. PyPI name squatting risk
4. Missing `workflow_dispatch` in CI
5. Incomplete pyproject.toml metadata (classifiers, readme, requires-python)
6. SECURITY.md and CODE_OF_CONDUCT.md omission
7. Python version matrix in CI
8. Multi-platform CI (macOS/Windows)

---

## Accepted Changes (Will Incorporate in Plan)

### 1. Security Audit: Upgrade to gitleaks

**Feedback**: All three models flagged that manual `grep` cannot scan git history. Gemini 3 Pro specifically recommended gitleaks/trufflehog.

**Decision**: ACCEPTED. Plan 1g will be updated to include:
- Run `gitleaks detect --source . --redact` before public visibility flip
- Scan covers both working tree and git history
- This is the industry standard for pre-public repos

### 2. workflow_dispatch in CI

**Feedback**: Gemini 3 Pro flagged this as a useful CI enhancement — allows manual test runs without pushing commits.

**Decision**: ACCEPTED. The `.github/workflows/test.yml` will include `workflow_dispatch:` trigger alongside `push` and `pull_request`.

### 3. Full pyproject.toml Metadata

**Feedback**: O3-Pro flagged missing `readme`, `classifiers`, `requires-python >=3.11` and potential empty wheel risk.

**Decision**: ACCEPTED. Plan 1a will be expanded to include:
- `readme = "README.md"` in `[project]`
- `requires-python = ">=3.11"`
- Trove classifiers: `License :: OSI Approved :: Apache Software License`, `Programming Language :: Python :: 3`, `Topic :: Software Development :: Libraries`, `Intended Audience :: Developers`
- Verify `__version__` matches pyproject.toml

### 4. PyPI Name Reservation

**Feedback**: Gemini 3 Pro raised the name squatting risk — the name `fava-trails` should be reserved on PyPI even if full publish is deferred.

**Decision**: ACCEPTED as a first manual publish. Per the Desktop cross-agent review (thought `01KJ83Z750Y7TED496WNC5DW73`), PyPI is near-term critical. We'll do the first `uv publish` as part of this pass (1i is upgraded from "deferred fast-follow" to "included"). This also resolves the name squatting risk.

### 5. SECURITY.md (Minimal File)

**Feedback**: Both GPT-5.1-Codex and O3-Pro recommended a minimal SECURITY.md pointing to a security contact.

**Decision**: ACCEPTED. A minimal SECURITY.md will be added with:
- Supported Python and JJ version window
- Private disclosure contact (GitHub Security Advisories)
- Note that vulnerability discussion should not happen in public issues

---

## Partially Accepted

### 6. CODE_OF_CONDUCT.md

**Feedback**: O3-Pro and GPT-5.1-Codex suggested Contributor Covenant v2.1.

**Decision**: DEFERRED to fast-follow. The current community is 0 external contributors. Adding a CoC before there is community behavior to govern is premature ceremony. It will be added when the first external contributor engages (likely TICK amendment). No change to spec.

---

## Rejected / Deferred

### 7. Multi-Platform CI (macOS/Windows)

**Feedback**: O3-Pro recommended expanding CI to macOS and Windows.

**Decision**: DEFERRED. JJ on Windows requires a different install path (ZIP vs. musl binary). Adding Windows CI would require conditional install logic, significantly expanding the CI workflow scope. This is appropriate for a follow-up TICK when JJ upstream provides better cross-platform packaging. Linux-only CI is correct for v0.4.0.

### 8. Python Version Matrix (3.11 + 3.13)

**Feedback**: Gemini 3 Pro recommended testing minimum (3.11) and latest (3.13).

**Decision**: DEFERRED. Single-version CI on `python-version: "3.11"` (minimum supported) is sufficient for the OSS launch. A Python matrix adds CI minutes without changing adoption behavior for early adopters. This can be added as part of a maintenance pass.

---

## Net Impact on Spec/Plan

The accepted changes are minor mechanical additions that do not change the scope or structure of the plan. Changes needed:
- Plan 1a: Add `readme`, `classifiers`, `requires-python` to pyproject.toml changes
- Plan 1c: Add `workflow_dispatch` to test.yml; note JJ env hermeticity
- Plan 1g: Upgrade security audit to use gitleaks
- Plan 1i: Upgrade PyPI from "deferred" to "included in this pass" (first manual publish)
- Plan 1k (new): Add SECURITY.md

These changes will be applied during the Plan phase or as inline clarifications. No spec amendments required — the spec's scope statement ("all missing OSS scaffolding") already encompasses these items.

# Phase 1 — Rebuttal for Iteration 1 Consultation Feedback

**Date**: 2026-02-24

## Summary

All reviewers APPROVED Phase 1 with one critical fix needed (sdist packaging).

---

## Accepted Changes (Applied)

### 1. sdist include list — CRITICAL

**Feedback**: `[tool.hatch.build.targets.sdist]` include list omits `README.md` and `LICENSE`. Since `readme = "README.md"` is referenced in pyproject.toml, hatchling would fail when building a source distribution from sdist if README.md is not included.

**Decision**: ACCEPTED. Fixed pyproject.toml sdist include to add `README.md`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.

### 2. CHANGELOG PyPI availability claim — MEDIUM

**Feedback**: CHANGELOG v0.4.0 entry claims "Package now available via pip install fava-trails" but the package hasn't been published to PyPI yet (that's Phase 2).

**Decision**: ACCEPTED. Rewording to "PyPI publishing workflow: Added Trusted Publishing GitHub Actions workflow for tag-based releases (pip install available after first publish)".

---

## Rejected

### 3. Emojis in description (LOW)

**Feedback**: Emojis in `description` field may render oddly.

**Decision**: REJECTED. The emoji is part of the brand identity and renders correctly on PyPI and GitHub. Not blocking.

### 4. CONTRIBUTING Linux-specific (LOW)

**Feedback**: JJ install instructions are Linux-specific.

**Decision**: ACKNOWLEDGED. install-jj.sh only supports Linux (x86_64 and aarch64). This is already the case and is documented. External users on macOS can use `brew install jj` — this can be added in a follow-up TICK.

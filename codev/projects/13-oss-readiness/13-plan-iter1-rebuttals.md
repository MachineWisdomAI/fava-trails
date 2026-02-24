# Plan 13 — Rebuttal for Iteration 1 Consultation Feedback

**Date**: 2026-02-24
**Models**: GPT-5.1-Codex, Gemini/GPT-5.1 via codereview, O3-Pro via codereview

## Summary

All reviewers confirmed the plan is actionable and well-ordered. Two high-priority issues were identified and accepted.

---

## Accepted Changes (Applied to Plan)

### 1. OIDC Trusted Publishing permissions (HIGH)

**Feedback**: All reviewers flagged that `release.yml` needs `permissions: id-token: write` for OIDC Trusted Publishing. Without it, GitHub will not issue the OIDC token and the PyPI publish step fails with a permissions error.

**Decision**: ACCEPTED. Added complete release.yml skeleton with required permissions to plan 2b.

### 2. Version-scoped GitHub release notes (HIGH)

**Feedback**: `gh release create --notes-file CHANGELOG.md` publishes the entire changelog (all versions) as the GitHub release body — noisy and unhelpful.

**Decision**: ACCEPTED. Updated plan 2c to extract only the v0.4.0 section using sed and pass it as `--notes-file`.

### 3. `uv sync --frozen` for deterministic CI (MEDIUM)

**Feedback**: `uv sync` without `--frozen` allows dep drift if the lock is not pinned to the runner. uv.lock is committed to the repo.

**Decision**: ACCEPTED. Updated CI spec to `uv sync --frozen`. Also reordered lint before tests for faster CI feedback (fail fast on style errors).

---

## Partially Accepted

### 4. Issue template YAML metadata

**Feedback**: Template needs `name`, `description`, `labels: [bug]`, and required field markings.

**Decision**: The plan already says "Create bug_report.yml with fields." The YAML metadata (`name`, `description`, `labels`, required) are standard and expected. Will be included in implementation. No plan update needed — this is an implementation detail.

---

## Rejected / Deferred

### 5. gitleaks shallow clone note

**Feedback**: Run from non-shallow clone (`git fetch --unshallow`).

**Decision**: DEFERRED. The security audit runs locally from the developer's full-history clone, not in CI. The `git fetch --unshallow` step only applies if running in a shallow CI checkout, which is not the intended audit environment. Implementation note is sufficient.

### 6. Lint/test order swap

**Decision**: ACCEPTED inline (lint before tests in CI). Already applied in plan update 3.

---

## Net Impact on Plan

- Plan 2b: Added complete `release.yml` skeleton with OIDC permissions
- Plan 2c: Version-scoped release notes extraction
- Plan 1c: `uv sync --frozen`, lint before tests
- No structural or scope changes

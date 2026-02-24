# Spec 12 Review Rebuttals — Specify Iteration 1

## Addressing Gemini Feedback

### 1. Env Var Naming Inconsistency
**Feedback:** `FAVA_TRAILS_DATA_REPO` and `FAVA_TRAILS_SCOPE` remain singular while the package becomes plural, creating mixed configuration interface.

**Response:** This is intentional and explicitly acknowledged in the spec. The spec lists these env vars unchanged in the configuration table — they are kept singular to avoid breaking changes for existing users. The `FAVA_TRAILS_DIR` variable already uses plural because it was added more recently. Renaming `FAVA_TRAILS_DATA_REPO` and `FAVA_TRAILS_SCOPE` would require server-side code changes which violate the "no functional changes" non-goal. This is appropriate for a pre-v1 project. **No change needed.**

### 2. Default Data Directory (`~/.fava-trails`)
**Feedback:** The default data directory should arguably move to `~/.fava-trails`.

**Response:** The spec explicitly states the default is `~/.fava-trails` (in the configuration table). Changing the default would be a behavioral change for existing users. This is intentionally out of scope. **No change needed.**

### 3. Repo Rename Note
**Feedback:** "Rename repo" is an admin action, not a code change.

**Response:** The spec acknowledges this under "Update `wise-fava-trails` data repo references if needed" and Phase 3 of the plan covers external reference updates. The GitHub repo rename is noted as coordinate-with-org. **Acknowledged, no spec change needed.**

---

## Addressing Codex Feedback

### 1. Missing Backwards-Compatibility Plan
**Feedback:** The package rename is a breaking API change, not cosmetic. Spec should include shims, dual entry points, deprecation period.

**Response:** This is a pre-v1 project (v0.3.3) with no published PyPI package. The "engine" (`fava-trails`) is open source but not yet widely distributed. A backwards-compat shim would add complexity without benefit at this stage. The architect has explicitly scoped this as a clean rename. **No change needed.**

### 2. Concrete Artifact Checklist
**Feedback:** Lacking inventory of files to rename.

**Response:** The plan's 3 phases provide the concrete checklist:
- Phase 1: Documentation split (README.md, AGENTS.md, CLAUDE.md stub)
- Phase 2: `src/fava_trails/` → `src/fava_trails/`, all imports, pyproject.toml, tests
- Phase 3: External references in docs, MCP configs, data repo refs

This is sufficient detail for the builder to execute. **No change needed.**

### 3. Version Bump and Changelog
**Feedback:** Rebranding should pair with semantic version bump and release notes.

**Response:** Valid observation for future consideration. Version bump and changelog are outside the spec scope but can be added as a follow-on task. The architect will decide versioning strategy. **Noted for architect follow-up, no spec change.**

---

## Summary

No spec changes required. All feedback points are either intentional non-goals or covered by the existing plan. Proceeding to implementation.

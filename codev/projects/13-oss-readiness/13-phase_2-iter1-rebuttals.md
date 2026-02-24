# Phase 2 — Rebuttal for Iteration 1 Consultation Feedback

**Date**: 2026-02-24

## Accepted Changes

### 1. attestations:write permission (HIGH) — ACCEPTED

`attestations: true` in `pypa/gh-action-pypi-publish@release/v1` generates SLSA provenance attestations, which requires `attestations: write` in addition to `id-token: write`. Without it, the release job would fail on the attestation upload step.

Fixed: added `attestations: write` to release.yml permissions.

### 2. Plan status (MEDIUM) — ACCEPTED

Updated `codev/plans/13-oss-readiness.md` status from "not started" to "complete".

## Rejected

### 3. Emojis in description (LOW) — REJECTED

Brand decision. FAVA Trails uses 🫛👣 as part of its identity. Renders correctly on PyPI and GitHub.

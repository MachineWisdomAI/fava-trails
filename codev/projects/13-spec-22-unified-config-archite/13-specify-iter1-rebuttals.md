# Rebuttal — Iteration 1 Review Feedback
# Project: 13 — Spec 22: Unified Config Architecture
# Date: 2026-03-09

## Summary

All three reviewers (Gemini 3.1, GPT-5.1-Codex, Gemini 2.5 Pro) approved the implementation.
One in-scope bug was identified unanimously and has been fixed. All other findings were
pre-existing issues unrelated to this PR's changes and have been deferred.

---

## Issue: server.py — GlobalConfig.__dict__ → model_dump(mode="json")

**Status: FIXED** (commit d5ecab3)

All three reviewers flagged that `store.global_config.__dict__` does not recursively
serialize nested Pydantic V2 models. With `hooks: list[HookEntry]` now present in
`GlobalConfig`, hook plugins receiving the startup event config would get raw `HookEntry`
instances instead of plain dicts.

Fix applied:
```python
# Before
startup_event = OnStartupEvent(trails_dir=trails_dir, config=store.global_config.__dict__)

# After
startup_event = OnStartupEvent(trails_dir=trails_dir, config=store.global_config.model_dump(mode="json"))
```

This was a pre-existing pattern (the original code also used `.__dict__`) but became
materially impactful once `GlobalConfig` gained a nested `list[HookEntry]` field.
353 tests pass after the fix.

---

## Pre-existing issues raised (deferred, out of scope for Spec 22)

The following issues were raised but are pre-existing and outside the scope of this PR:

### get_trust_gate_policy condition (Gemini 3.1)
The `trail_config.trust_gate_policy != "llm-oneshot"` condition predates this PR.
Spec 22 does not touch `get_trust_gate_policy`. Deferred.

### Root-level warning path handling (Gemini 3.1)
Pre-existing server.py logic. Out of scope. Deferred.

### FAVA_TRAILS_DATA_REPO tilde expansion (GPT-5.1-Codex)
The original `get_data_repo_root()` also did not expand tilde — `return Path(data_repo)`.
This PR preserves that existing behavior. Not a regression. Deferred.

### Threading lock for ConfigStore (GPT-5.1-Codex)
The MCP server is a single-process asyncio application with no threading. A threading
lock would add complexity without benefit. Not applicable.

### sys.path mutation in hook_manifest.py (Gemini 2.5 Pro)
Pre-existing since Spec 17. Out of scope for Spec 22. Deferred.

### _trail_managers unbounded cache (Gemini 2.5 Pro)
Pre-existing server design. Out of scope. Deferred.

### ThoughtRecord.to_markdown redundant conversions (Gemini 2.5 Pro)
Pre-existing. Out of scope. Deferred.

---

## Final State

- All Spec 22 success criteria met
- One consultation-identified bug fixed (model_dump)
- 353 tests pass, ruff clean
- PR pushed to origin, ready for merge

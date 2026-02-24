# Plan 14 — Plan Phase Rebuttal (Iteration 1)

## Summary

All three models returned LGTM with implementation-level notes (no structural changes required). The plan is approved. Changes incorporated below are minor additions from spec consultation feedback that strengthen the implementation detail.

---

## Changes Made to Plan

### 1. `--version` flag in step 1a (ACCEPTED — Codex + GPT-5.1)
Added to step 1a: `parser.add_argument('--version', action='version', version=f'%(prog)s {version}')` using `importlib.metadata.version('fava-trails')`. Trivial argparse addition.

### 2. `--scope` flag in step 1b (ACCEPTED — Codex + GPT-5.1)
Added to step 1b: `init` accepts optional `--scope` argument. If provided, skips `input()` prompt. If absent and `.fava-trail.yaml` missing, falls back to interactive prompt.

### 3. `.env` write helper extraction (ACCEPTED — GPT-5.1)
Made explicit in plan: `_update_env_file(path, key, value)` internal helper function, called by both `init` (1b) and `scope set` (1e). Avoids code duplication.

### 4. `doctor` exit codes and `--check-remote` (ACCEPTED — Codex + GPT-5.1)
Added to step 2a: exit 0 on all-pass, exit 1 on any failure. `--check-remote` flag gates network check.

### 5. Test for duplicate key scenario (ACCEPTED — Gemini + GPT-5.1)
Added to step 1g: `test_init_env_duplicate_key` — verifies that running `init` when `.env` already has duplicate `FAVA_TRAIL_SCOPE` entries results in a single entry (deduplication).

---

## No Structural Changes

Phase ordering and sequencing are confirmed correct by all three models. No phases added, removed, or reordered.

# Spec 14 — Specify Phase Rebuttal (Iteration 1)

## Summary

All three models confirmed the spec is technically sound and feasible (7–9/10 confidence). No blocking concerns were raised. The feedback is a set of UX and robustness refinements that I will incorporate into the spec's implementation notes.

---

## Changes Made to Spec

### 1. `--version` flag (ACCEPTED — all 3 models)
Added to spec. `fava-trails --version` will be trivially implemented via `argparse`'s `version` action pulling from package metadata.

### 2. `--scope` flag for `init` (ACCEPTED — GPT-5.1)
Added to spec. `fava-trails init --scope mw/eng/foo` skips interactive prompt. If `--scope` is not provided and `.fava-trail.yaml` is absent, falls back to `input()`.

### 3. Robust `.env` parser (ACCEPTED — all 3 models)
Acknowledged as the highest-risk implementation area. Implementation notes strengthened: parse line-by-line into memory model, preserve comments/blanks/trailing whitespace, handle duplicate `FAVA_TRAIL_SCOPE` entries by updating in-place. Test added for "duplicate key in existing file" scenario.

### 4. `init` warns if `.env` not in `.gitignore` (ACCEPTED — Gemini + GPT-5.1-Codex)
Added to spec: `init` checks if `.env` appears in `.gitignore`. If not, prints: "Warning: .env is not in .gitignore — add it to avoid committing local config."

### 5. `init` guidance when no data repo found (ACCEPTED — all 3 models)
Open question resolved: `init` does NOT automatically run `init-data`. When `get_data_repo_root()` fails, prints: "Data repo not configured. Run: fava-trails init-data <path>"

### 6. `doctor --check-remote` flag (ACCEPTED — all 3 models)
`doctor` shows configured remote URL from config.yaml without a network call by default. Remote reachability check only runs with `--check-remote` flag.

### 7. `scope list` sorted unique (ACCEPTED — GPT-5.1)
Implementation note: sorted alphabetically, deduplicated. Trivial to implement.

### 8. `doctor` exits non-zero on failure (ACCEPTED — GPT-5.1)
`doctor` will exit 0 only if all checks pass, 1 if any check fails. This is standard for health-check commands.

---

## Deferred (Not in This Spec)

### `scope unset` command (DEFERRED — Gemini)
This is a reasonable future addition. Deferred to a TICK amendment if needed. Current scope (no pun intended) is sufficient for the immediate use cases.

### `init-data` rollback on failure (DEFERRED — GPT-5.1-Codex)
Full rollback is complex (removing partially-created directories, JJ state). Will implement: clear error message + "Partial init may have occurred. Clean up manually: rm -rf <path>" warning. Full rollback deferred.

### `scope list` caching (DEFERRED — GPT-5.1-Codex)
Data repos are not expected to be large in v1. Caching is premature optimization. Deferred.

---

## No Changes Required

### Argparse vs Click (all 3 models agreed: argparse is correct)
No change. All models explicitly endorsed argparse given the constraint set.

### Shared helpers (all 3 models)
The plan already specifies reuse of `config.py:get_data_repo_root()` and `config.py:sanitize_scope_path()`. No duplication of scope resolution logic is planned.

---

## Updated Open Questions (Resolved)

- "Should `init` also run `init-data` if no data repo is configured?" → **No** — keep commands separate, print guidance.
- "Should `doctor` check network connectivity to the git remote?" → **Optional** — behind `--check-remote` flag.

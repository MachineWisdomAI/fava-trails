# Review 0: Repository Separation — Engine vs. Data

**Status:** completed
**Spec:** `codev/specs/0-repo-separation.md`
**Plan:** `codev/plans/0-repo-separation.md`
**Reviewer:** GPT-5.1 Codex via `mcp__pal__codereview`
**Continuation ID:** `1382f4d3-d89f-4283-a3f6-760425909213`

---

## Summary

Phase 0 successfully separated the FAVA Trail codebase into two repos following the Engine vs. Fuel pattern. The GPT-5.1 Codex code review found 3 issues (1 HIGH, 2 MEDIUM), all resolved.

## What Was Done

1. **Created `fava-trails/` OSS repo** — Moved all Python source, tests, SPIR docs, scripts. Added Apache-2.0 LICENSE, `.gitignore`, comprehensive `CLAUDE.md`. Git initialized.
2. **Enhanced `config.py`** — Added 3-level priority for trails directory: `FAVA_TRAILS_DIR` env > absolute config > relative config. Added 6 tests.
3. **Created `fava-trails-data/` internal repo** — Created `config.yaml`, `Makefile`, `CLAUDE.md`, `.gitignore`, `trails/`. Git initialized.
4. **Wired together** — Verified all 36 tests pass with `FAVA_TRAILS_DATA_REPO` pointing to `fava-trails-data/`.

## Spec Compliance

| Criterion | Status |
|-----------|--------|
| `fava-trails` has all Python source, tests pass | Pass |
| `fava-trails-data` has config/data files only | Pass |
| `FAVA_TRAILS_DATA_REPO` correctly points server to data repo | Pass |
| No company-specific data in OSS repo | Pass |
| `make setup` bootstraps working environment | Pass (prints instructions) |
| All 30+ tests pass against restructured code | Pass (36/36) |

## Code Review Findings (GPT-5.1 Codex)

### HIGH: Path traversal in `trail_name` (config.py:61-79)

`trail_name` is concatenated directly into filesystem paths via `get_trails_dir() / trail_name`. A malicious MCP client could supply `"../../.ssh"` to read/write outside the trails root.

**Fix applied:** Added `_sanitize_trail_name()` validation in `config.py` — rejects names containing `..`, `/`, `\`, or any non-slug characters.

### MEDIUM: `ensure_fava_home` ignores custom trails directory (config.py:82-87)

When `FAVA_TRAILS_DIR` points outside `$FAVA_TRAILS_DATA_REPO`, the function still creates `$FAVA_TRAILS_DATA_REPO/trails` but not the actual configured trails directory.

**Fix applied:** `ensure_fava_home()` now calls `get_trails_dir()` and creates that directory.

### MEDIUM: Tilde expansion missing for `FAVA_TRAILS_DIR` (config.py:31-34)

`FAVA_TRAILS_DIR=~/trails` would be interpreted as a relative path since `Path('~/trails')` doesn't expand tildes.

**Fix applied:** Added `os.path.expanduser()` before `Path()` construction for the env var.

## Positive Aspects (per reviewer)

- Clean separation between OSS engine and internal data repo
- Comprehensive documentation in both `CLAUDE.md` files
- Thorough tests covering the 3-level precedence rules
- `.gitignore` precisely scopes what belongs to outer vs inner repos

## Lessons Learned

1. **Always validate user-supplied path components** — trail names come from MCP clients (untrusted input)
2. **Test with custom paths** — `ensure_fava_home()` was only tested with default paths, missing the `FAVA_TRAILS_DIR` override case
3. **Expand tildes in env vars** — `Path()` doesn't expand `~`, but users commonly use it

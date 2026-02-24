# Plan 14: FAVA Trails CLI

**Status:** not started
**Spec:** `codev/specs/14-cli.md`
**Epic:** 0005a-adoption
**Prerequisites:** Spec 12 (rebrand) must be integrated first

---

## Phase 1: Core Commands

Create `src/fava_trails/cli.py` with argparse subcommands and register as a console_script.

### 1a: CLI Entry Point

Add to `pyproject.toml`:
```toml
[project.scripts]
fava-trails-server = "fava_trails.server:run"
fava-trails = "fava_trails.cli:main"
```

Create `src/fava_trails/cli.py` with argparse and subcommand dispatch.

Also add `--version` to the top-level parser:
```python
from importlib.metadata import version
parser.add_argument('--version', action='version', version=f'%(prog)s {version("fava-trails")}')
```

### 1b: `fava-trails init`

Initialize a project directory for FAVA Trails. Assumes data repo and MCP server are already set up. Accepts optional `--scope <value>` flag for non-interactive/CI use.

1. If `--scope` provided, use it directly. Otherwise check for `.fava-trails.yaml`:
   - If exists: read `scope` field
   - If missing: prompt user for scope via `input()`, create `.fava-trails.yaml` with `scope: <value>`
2. Check `.env` for `FAVA_TRAILS_SCOPE`:
   - If already set: print current scope, no-op
   - If missing: append `FAVA_TRAILS_SCOPE=<scope>` to `.env` (create if needed)
3. Check if `.env` is in `.gitignore` — if not, print: "Warning: .env is not in .gitignore — add it to avoid committing local config."
4. Validate data repo is accessible (call `get_data_repo_root()` from `config.py`). If not found, print: "Data repo not configured. Run: fava-trails bootstrap <path>"
5. Print summary: "Scope: mw/eng/my-project, Data repo: /path/to/data"

**Reuse:** `config.py:get_data_repo_root()` for data repo validation.

**`.env` write safety:** Extract as `_update_env_file(path, key, value)` internal helper (also used by `scope set`). Parse existing `.env` line by line. Only append/update the `FAVA_TRAILS_SCOPE` line. Handle comments, blanks, and duplicate keys (deduplicate — keep last). Never clobber other variables.

### 1c: `fava-trails bootstrap <path>`

Bootstrap a new data repository (replaces `scripts/bootstrap-data-repo.sh`):

1. Create directory at `<path>` if it doesn't exist
2. Create `config.yaml` with defaults:
   ```yaml
   trails_dir: trails
   remote_url: null
   push_strategy: manual
   ```
3. Create `.gitignore` (ignore `.jj/` internal files if needed)
4. Create `trails/` directory
5. Run `jj git init --colocate` in the directory
6. Optionally set remote URL if provided via `--remote` flag
7. Print summary

**Reuse:** Port logic from `scripts/bootstrap-data-repo.sh` to Python. Validate JJ is installed before proceeding.

### 1d: `fava-trails scope`

Show current scope and resolution source:

```
Scope: mw/eng/fava-trails
Source: .env (FAVA_TRAILS_SCOPE)
```

Resolution order (same as server):
1. `.env` → `FAVA_TRAILS_SCOPE`
2. `.fava-trails.yaml` → `scope`
3. Not configured

### 1e: `fava-trails scope set <scope>`

Update scope in both config files:

1. Validate scope path (reuse `config.py:sanitize_scope_path()`)
2. Update `.fava-trails.yaml` `scope` field (create if missing)
3. Update `.env` `FAVA_TRAILS_SCOPE` (create/append if missing)
4. Print hint: "Note: The trail directory will be created when the first thought is saved. Trust gate prompt is inherited from parent scope. To customize, create `<trails_dir>/<scope>/trust-gate-prompt.md`"

### 1f: `fava-trails scope list`

List all scopes in the data repo:

1. Get data repo root via `get_data_repo_root()`
2. Walk `trails/` directory for any path containing `thoughts/`
3. Print as slash-separated scope paths

**Reuse:** Same logic as `list_scopes` MCP tool in `tools/navigation.py`.

### 1g: Tests

Create `tests/test_cli.py`:
- `init` in directory with `.fava-trails.yaml` but no `.env` — creates `.env` with correct scope
- `init` in directory with both files (no scope in .env) — appends scope
- `init` in directory with `.env` already containing `FAVA_TRAILS_SCOPE` — no-op, prints current
- `init` in directory with neither file — prompts for scope, creates both
- `init --scope mw/eng/foo` — non-interactive, skips prompt
- `init` with `.env` containing duplicate `FAVA_TRAILS_SCOPE` entries — deduplicates to single entry
- `bootstrap` creates valid data repo structure (config.yaml, .gitignore, trails/, JJ init)
- `scope` shows correct resolution source
- `scope set` updates both files
- `scope list` finds scopes in data repo
- `.env` writes preserve existing content (idempotency)

Mock filesystem via `tmp_path` fixture. Mock JJ calls via `subprocess` patching.

---

## Phase 2: Doctor + Polish

### 2a: `fava-trails doctor`

Health check command that validates the full setup. Exits 0 if all checks pass, 1 if any check fails.

```
fava-trails doctor

JJ:           installed (v0.25.0)
Data repo:    /home/user/.fava-trails (valid)
Scope:        mw/eng/fava-trails (from .env)
```

Checks:
1. JJ installed? What version? (`jj --version`)
2. Data repo valid? Path exists? Has `config.yaml`? Has `trails/`?
3. Scope configured? From `.env`, `.fava-trails.yaml`, or not set?

Each check prints pass/fail with actionable fix suggestion:
- "JJ not found. Install with: bash scripts/install-jj.sh"
- "Data repo not found. Run: fava-trails bootstrap <path>"
- "Scope not configured. Run: fava-trails init"

### 2b: Deprecation Notice

Update `scripts/bootstrap-data-repo.sh` to print deprecation warning at the top:
```bash
echo "DEPRECATED: Use 'fava-trails bootstrap <path>' instead."
```

### 2c: Integration Tests

Add integration tests for `doctor`:
- Doctor with everything configured — all green
- Doctor with missing JJ — reports error with install suggestion
- Doctor with missing data repo — reports error with bootstrap suggestion
- Doctor with missing scope — reports error with init suggestion

### 2d: README/Docs Update

Add CLI usage section to README.md or link to `fava-trails --help` output.

---

## Phases (Machine Readable)

<!-- REQUIRED: porch uses this JSON to track phase progress. -->

```json
{
  "phases": [
    {"id": "phase_1", "title": "Core Commands"},
    {"id": "phase_2", "title": "Doctor + Polish"}
  ]
}
```

---

## Done Criteria

- `fava-trails init` creates `.fava-trails.yaml` and populates `.env` with `FAVA_TRAILS_SCOPE`
- `fava-trails init` works in a project that already has `.fava-trails.yaml` (reads scope, writes `.env`)
- `fava-trails bootstrap <path>` replaces `bootstrap-data-repo.sh` functionality
- `fava-trails doctor` validates JJ, data repo, and scope configuration
- `fava-trails scope` shows current scope and resolution source
- CLI is installed as a console_script alongside `fava-trails-server`
- Existing `bootstrap-data-repo.sh` is deprecated in favor of `fava-trails bootstrap`
- All new commands have tests
- All existing tests still pass

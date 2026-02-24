# Review: FAVA Trails CLI (Spec 14)

**Status:** Complete
**Protocol:** SPIR
**Epic:** 0005a-adoption

---

## Spec vs Implementation Comparison

| Success Criterion | Status |
|---|---|
| `fava-trails init` creates `.fava-trail.yaml` and populates `.env` | DONE |
| `fava-trails init` works with existing `.fava-trail.yaml` | DONE |
| `fava-trails init --scope` for non-interactive use | DONE (added during consultation) |
| `fava-trails init` warns if `.env` not in `.gitignore` | DONE (added during consultation) |
| `fava-trails init` guides to `bootstrap` when no data repo | DONE |
| `fava-trails bootstrap <path>` replaces bootstrap-data-repo.sh | DONE |
| `fava-trails doctor` validates JJ, data repo, scope | DONE |
| `fava-trails doctor` exits non-zero on failure | DONE |
| `fava-trails scope` shows current scope and resolution source | DONE |
| `fava-trails --version` prints version | DONE (added during consultation) |
| CLI installed as console_script alongside fava-trails-server | DONE |
| bootstrap-data-repo.sh deprecated | DONE |
| All new commands have tests | DONE (39 tests) |

All spec success criteria met. One command was renamed during architect review:
- `init-data` → `bootstrap` (matches developer expectation of `git init`, `npm init` etc.)

---

## Issues Found Across Phases

### Phase 1 (Core Commands)
| Issue | Severity | Resolution |
|---|---|---|
| `.env` write not atomic | HIGH | Atomic write via tmp + replace() |
| `bootstrap` would overwrite existing files | HIGH | Added config.yaml/.gitignore existence checks |
| Broad `except Exception` in init | MEDIUM | Narrowed to `(OSError, ValueError)` |
| `_read_env_value` didn't handle `export KEY=value` | MEDIUM | Added export prefix stripping |
| `with_suffix` on dotfiles | MEDIUM | Fixed to use `with_name` |
| Redundant dispatch in `main()` | LOW | Simplified to single `hasattr` check |

### Phase 2 (Doctor + Polish)
| Issue | Severity | Resolution |
|---|---|---|
| `jj --version` could hang (no timeout) | HIGH | Added `timeout=2` + `OSError/TimeoutExpired` handling |
| `_read_project_yaml_scope` could crash on invalid YAML | HIGH | Added `yaml.YAMLError` catch |
| `doctor` scope check didn't validate scope format | MEDIUM | Added `sanitize_scope_path` validation |
| `import shutil` inside function | LOW | Moved to module-level |

---

## Architecture Updates

The CLI adds a **human-facing layer** to FAVA Trails alongside the existing MCP server (agent-facing). Key architectural decisions confirmed:

1. **Shared package, separate entry points** — `fava-trails` (CLI) and `fava-trails-server` (MCP) coexist in the same `fava_trails` package. CLI reuses `config.py` helpers.

2. **Two-file scope configuration** — `.fava-trail.yaml` (committed, project-level default) + `.env` (local, gitignored, agent-loadable). The `init` command bridges these two files reliably.

3. **Argparse over click** — Confirmed correct. Zero new dependencies, adequate for 5 commands.

4. **Atomic .env writes** — `_update_env_file` uses `with_name(name + ".tmp")` + `Path.replace()` for safe atomic updates.

---

## Lessons Learned

1. **Consult first, then resolve open questions** — Both open questions in the spec (init/init-data separation, doctor remote check) were cleanly resolved during consultation without bikeshedding in the implementation.

2. **Dotfile edge cases in stdlib** — `Path.with_suffix()` on a dotfile like `.env` (which has no extension from Python's perspective) appends to the empty suffix, giving `.tmp` not `.env.tmp`. Use `with_name(name + ".tmp")` for reliable dotfile temp paths.

3. **`subprocess.run` needs timeout in health checks** — Any CLI `doctor` command that calls external binaries must have a timeout. Health checks that can hang are worse than health checks that fail fast.

4. **Code review catches YAML safety gaps** — `yaml.safe_load` on a user-editable config file (`_read_project_yaml_scope`) needs a `yaml.YAMLError` catch. The spec mentioned `.env` write safety but not YAML safety — code review surfaced it.

5. **Architect feedback mid-stream** — `init-data` → `bootstrap` rename was applied correctly after explicit architect instruction. Builder correctly stopped and applied corrections rather than inferring intent.

---

## PR

See pull request for full diff.

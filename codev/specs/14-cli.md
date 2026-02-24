# Specification: FAVA Trails CLI

## Metadata
- **ID**: spec-2026-02-24-cli
- **Status**: draft
- **Created**: 2026-02-24
- **Protocol**: SPIR
- **Epic**: 0005a-adoption
- **Prerequisites**: Spec 12 (rebrand)

## Clarifying Questions Asked

1. **What's the immediate problem?** — Agents fail to discover project scope because `.fava-trail.yaml` requires proactive file reads that agents skip in practice. The `.env` approach is more reliable (auto-loaded by agent runtimes) but `.env` is gitignored and not auto-populated from `.fava-trail.yaml`. A CLI `init` command bridges this gap.
2. **What else would the CLI do?** — Beyond init, a CLI is the natural home for data repo bootstrapping, health checks, scope management, and any future operations that don't belong in the MCP server (which is agent-facing, not human-facing).

## Problem Statement

FAVA Trails has two human-facing setup scripts (`install-jj.sh`, `bootstrap-data-repo.sh`) and a scope discovery protocol that requires agents to read `.fava-trail.yaml` and populate `.env` — which they frequently fail to do. There is no unified CLI for humans to:

1. **Initialize a project directory** for FAVA Trails (create `.fava-trail.yaml`, populate `.env`)
2. **Bootstrap a data repo** (currently a bash script)
3. **Verify setup** (is JJ installed? is the data repo valid? is scope configured?)
4. **Manage scopes** (list, switch, create sub-scopes)

The `bootstrap-data-repo.sh` script works but is not discoverable — users must know it exists. A `fava-trails init` command is the expected entry point.

## Current State

- **Scope setup**: Manual — user creates `.fava-trail.yaml` by hand, or copies from docs
- **Data repo setup**: `bash scripts/bootstrap-data-repo.sh <path>` — works but undiscoverable
- **JJ installation**: `bash scripts/install-jj.sh` — separate script
- **Health check**: None — no way to verify everything is wired correctly
- **Scope management**: Manual file editing

The scope discovery gap is the acute trigger: agents are told to check `.fava-trail.yaml` but don't, leading to wrong-scope operations (observed in practice during this session).

## Desired State

A `fava-trails` CLI (installed alongside the MCP server via the same package) that provides:

```bash
# Initialize a project directory for FAVA Trails
fava-trails init
# → Checks for .fava-trail.yaml: if missing, asks for scope and creates it
# → Writes FAVA_TRAIL_SCOPE=<scope> to .env (creates if needed, appends if exists)
# → Validates the data repo is accessible
# → Prints summary: "Scope: mwai/eng/my-project, Data repo: /path/to/data"

# Bootstrap a new data repo (replaces bootstrap-data-repo.sh)
fava-trails init-data <path>
# → Creates directory, config.yaml, .gitignore
# → Initializes JJ colocated repo
# → Optionally sets remote URL

# Check health of the current setup
fava-trails doctor
# → JJ installed? Version?
# → Data repo valid? Path?
# → Scope configured? From .env or .fava-trail.yaml?
# → Remote configured? Reachable?

# Scope management
fava-trails scope
# → Shows current scope and source (.env, .fava-trail.yaml, or hint)

fava-trails scope set <scope>
# → Updates .fava-trail.yaml and .env

fava-trails scope list
# → Lists all scopes in the data repo (delegates to list_scopes)
```

## Stakeholders
- **Primary Users**: Developers setting up FAVA Trails in their projects
- **Secondary Users**: Agents (indirectly — `init` populates `.env` which agents read reliably)
- **Technical Team**: Machine Wisdom
- **Business Owner**: Younes (Machine Wisdom Solutions Inc.)

## Success Criteria
- [ ] `fava-trails init` creates `.fava-trail.yaml` and populates `.env` with `FAVA_TRAIL_SCOPE`
- [ ] `fava-trails init` works in a project that already has `.fava-trail.yaml` (reads scope, writes `.env`)
- [ ] `fava-trails init` accepts `--scope <value>` for non-interactive/CI use
- [ ] `fava-trails init` warns if `.env` is not in `.gitignore`
- [ ] `fava-trails init` prints clear guidance when no data repo is configured
- [ ] `fava-trails init-data <path>` replaces `bootstrap-data-repo.sh` functionality
- [ ] `fava-trails doctor` validates JJ, data repo, and scope configuration
- [ ] `fava-trails doctor` exits non-zero if any check fails
- [ ] `fava-trails doctor --check-remote` optionally checks remote reachability
- [ ] `fava-trails scope` shows current scope and resolution source
- [ ] `fava-trails --version` prints the package version
- [ ] CLI is installed as a console_script alongside `fava-trails-server`
- [ ] Existing `bootstrap-data-repo.sh` is deprecated in favor of `fava-trails init-data`
- [ ] All new commands have tests

## Constraints

### Technical Constraints
- Must be pure Python (no additional binary dependencies beyond JJ)
- CLI and MCP server share the same package — no separate install
- `.env` writes must be append-safe (don't clobber existing variables)
- Must work on Linux, macOS, and WSL

### Business Constraints
- CLI should feel familiar to developers who've used `git init`, `npm init`, `uv init`
- Minimal dependencies — prefer stdlib (`argparse`) or lightweight (`click` if already transitively available)

## Assumptions
- Spec 12 (rebrand) is integrated: package name is `fava-trails`, entry point is `fava-trails`
- The CLI shares the `fava_trails` Python package (no separate repo)
- JJ is a prerequisite — the CLI checks for it but doesn't install it (points to docs/script)

## Solution Approaches

### Approach 1: argparse-based CLI (Recommended)

**Description**: Add a `cli.py` module to `fava_trails` with `argparse` subcommands. Register as a `console_scripts` entry point alongside the server.

**Pros**:
- Zero new dependencies (argparse is stdlib)
- Simple, predictable
- Easy to test (call functions directly, mock filesystem)

**Cons**:
- argparse is verbose for complex CLIs
- No auto-completion out of the box

**Estimated Complexity**: Low-Medium
**Risk Level**: Low

### Approach 2: click-based CLI

**Description**: Use `click` for the CLI framework.

**Pros**:
- Cleaner API, auto-generated help
- Better UX for interactive prompts (`click.prompt`)

**Cons**:
- New dependency (click is not currently in the dependency tree)
- Heavier than needed for ~5 commands

**Estimated Complexity**: Low-Medium
**Risk Level**: Low

**Recommendation**: Approach 1 (argparse). The CLI is small enough that argparse is adequate, and avoiding a new dependency keeps the package lean. If interactive prompts are needed, `input()` is sufficient.

## Open Questions

### Critical (Blocks Progress)
- [x] Should `init` also run `init-data` if no data repo is configured? **Resolved: No — keep separate. `init` prints guidance: "Run: fava-trails init-data <path>"**

### Important (Affects Design)
- [x] Should `doctor` check network connectivity to the git remote? **Resolved: Optional — `--check-remote` flag only**
- [ ] Should `scope set` also update the data repo (create the trail directory)?

### Nice-to-Know (Optimization)
- [ ] Should we add shell completion generation (`fava-trails --completion`)?
- [x] Should `init` offer to add `.env` to `.gitignore` if not already ignored? **Resolved: Yes — `init` warns if `.env` is not in `.gitignore`**

## Performance Requirements
N/A — CLI commands are interactive, human-speed.

## Security Considerations
- `init` writes to `.env` — must not overwrite existing variables, only append/update `FAVA_TRAIL_SCOPE`
- `init-data` creates directories and runs JJ — standard filesystem permissions apply
- No network access except `doctor` checking remote reachability (optional)

## Test Scenarios

### Functional Tests
1. `init` in a directory with `.fava-trail.yaml` but no `.env` — creates `.env` with correct scope
2. `init` in a directory with both `.fava-trail.yaml` and `.env` (no scope) — appends scope to `.env`
3. `init` in a directory with `.env` already containing `FAVA_TRAIL_SCOPE` — no-op, prints current scope
4. `init` in a directory with neither file — prompts for scope, creates both files
5. `init-data` creates valid data repo structure (config.yaml, .gitignore, JJ init)
6. `doctor` reports missing JJ, missing data repo, missing scope
7. `scope` shows correct resolution source

### Non-Functional Tests
1. `init` is idempotent — running twice produces same result
2. `.env` writes preserve existing content

## Dependencies
- **Spec 12 (rebrand)**: Package name and entry points use post-rebrand naming
- **JJ binary**: Required by `init-data` and `doctor`
- **Existing `config.py`**: Reuse `get_data_repo_root()`, `sanitize_scope_path()`, etc.

## References
- Scope discovery gap observed in practice (this session — agent used server hint instead of `.fava-trail.yaml`)
- Existing scripts: `scripts/bootstrap-data-repo.sh`, `scripts/install-jj.sh`
- Epic 0005a: `codev/epics/0005a-adoption.md`

## Risks and Mitigation
| Risk | Probability | Impact | Mitigation Strategy |
|------|------------|--------|-------------------|
| `.env` write corrupts existing content | Low | High | Parse existing `.env`, only update/append `FAVA_TRAIL_SCOPE` line |
| Users expect `init` to also bootstrap data repo | Medium | Low | Clear messaging: "Data repo not found. Run `fava-trails init-data <path>` to create one." |
| CLI adds maintenance burden | Low | Low | Small surface area (~5 commands), shares code with server |

## Expert Consultation
Deferred — scope is straightforward. Consult at plan phase if the command surface grows.

## Approval
- [ ] Technical Lead Review
- [ ] Product Owner Review
- [ ] Stakeholder Sign-off
- [ ] Expert AI Consultation Complete

## Notes
- The CLI is the human-facing complement to the MCP server (agent-facing). Together they cover both audiences.
- `init` is the immediate fix for the scope discovery reliability gap. The other commands (`init-data`, `doctor`, `scope`) are natural extensions that consolidate existing scripts.
- Post-rebrand, the entry point is `fava-trails` (not `fava-trails-cli` or similar). The server remains `fava-trails-server`.

---

## Amendments

<!-- When adding a TICK amendment, add a new entry below this line in chronological order -->

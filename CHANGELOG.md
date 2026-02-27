# Changelog

All notable changes to FAVA Trails are documented here.

## [0.4.9] — 2026-02-27

### Fixed
- **CI lint passing**: Added `ruff` to dev dependencies (was configured but not installed in CI). Fixed all lint warnings (import ordering, unused f-strings, unused variables).

---

## [0.4.8] — 2026-02-27

### Fixed
- **Quick-start guidance**: CLI help now shows numbered setup steps for all missing prerequisites (JJ binary + data repo), silent when fully configured

---

## [0.4.7] — 2026-02-27

### Fixed
- **Install-jj discoverability**: CLI help now shows "Quick start: run 'fava-trails install-jj'" when JJ is not installed

---

## [0.4.6] — 2026-02-27

### Added
- **`fava-trails install-jj` subcommand** (TICK 14-001): Downloads JJ binary from GitHub releases — eliminates the adoption cliff between `pip install fava-trails` and a working system. Supports Linux (x86_64, aarch64), macOS (x86_64, arm64), Windows (winget guidance). Version-aware skip, regex version match, zsh-aware PATH hint.
- All "jj not found" error messages now reference `fava-trails install-jj` instead of `scripts/install-jj.sh`
- CI dogfoods the `install-jj` CLI command

---

## [0.4.5] — 2026-02-27

### Changed
- **README refresh for public launch**: PyPI badges, dual install paths (PyPI primary), `fava-trails bootstrap` CLI, updated MCP configs, refreshed architecture diagram
- **Docs cleanup**: Removed stale internal references from AGENTS.md, AGENTS_USAGE_INSTRUCTIONS.md, CONTRIBUTING.md, FAQ, and onepager; updated all bootstrap instructions to CLI command
- **Removed orphaned `.architect-role.md`**

---

## [0.4.4] — 2026-02-27

### Fixed
- **JJ push defense-in-depth** (TICK 1b-003): Repair skips immutable commits via `mutable()` revset; per-commit error isolation prevents one failure from blocking the entire push

---

## [0.4.3] — 2026-02-27

### Added
- **Defense-in-depth against JJ push failures** (TICK 1b-003): Three-layer defense — prevention (`ui.default-description` config), repair (`_repair_undescribed_commits()` before every push), fallback (`--allow-empty-description` flag)

---

## [0.4.2] — 2026-02-26

### Fixed
- **Trust Gate JSON parsing** (TICK 3-001): LLM responses wrapped in markdown code fences are now correctly parsed
- **Data repo bootstrap**: Template files (`.gitignore`, config) included in `fava-trails bootstrap`

---

## [0.4.1] — 2026-02-25

### Fixed
- **Phantom empty JJ commits** (TICK 1b-002): `commit_files()` and `new_change()` always pass `-m` to prevent undescribed commits that block `jj git push`
- Docs filenames updated to plural FAVA Trails
- Removed stale compat shims and upgrade guide

---

## [0.4.0] — 2026-02-24

### Added
- **Rebrand**: Project renamed from `fava-trail` to `fava-trails` (package, module, entry point)
- **OSS readiness**: Apache 2.0 license declared in pyproject.toml, CONTRIBUTING.md, CHANGELOG.md, SECURITY.md
- **GitHub Actions CI**: Automated test + lint on every push and pull request
- **Issue templates**: Bug report template with JJ/OS/Python version fields
- **PyPI publishing workflow**: Added Trusted Publishing GitHub Actions workflow for tag-based releases (`pip install fava-trails` available after first publish)
- **Full pyproject.toml metadata**: license, authors, readme, classifiers, project URLs

### Changed
- Version bumped to 0.4.0 (first public release post-rebrand)

---

## [0.3.3] — 2026-02-10

### Fixed
- Scope discovery reliability: `.fava-trails.yaml` now correctly propagates scope to `.env` for all agents in a project
- CLI spec improvements for `fava-trails-server` startup behavior

---

## [0.3.2] — 2026-01-28

### Added
- `get_usage_guide` MCP tool: returns full protocol reference on-demand
- MCP server `instructions` field: auto-injects core usage guidance at session start for all MCP clients that support it

---

## [0.3.1] — 2026-01-15

### Added
- Multi-scope search in `recall`: `trail_names` parameter accepts glob patterns (e.g., `mw/eng/*`)
- Preferences auto-surface: user preference thoughts automatically included in relevant recall results

---

## [0.3.0] — 2025-12-20

### Added
- Storage substrate amendments: monorepo support for shared FAVA Trails data repos
- Conflict interception: JJ conflicts in data repos are detected and surfaced to agents before they cause silent data loss

---

## [0.2.0] — 2025-11-10

### Added
- Trust Gate: recalled thoughts pass through a configurable trust review before being returned to agents
- Hierarchical scoping: trail names use slash-separated paths (e.g., `org/project/epic`) with inheritance

---

## [0.1.0] — 2025-10-01

### Added
- Initial release: 15 MCP tools for agent memory management
- VCS-backed storage using Jujutsu (JJ) colocated git repos
- Draft/promoted thought lifecycle (`save_thought` → `propose_truth`)
- Full thought lineage tracking (who wrote it, when, why it changed)
- Engine/Fuel split architecture: stateless MCP server + separate user-controlled data repo

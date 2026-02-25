# Spec 15: Data Repo Management CLI

## Status
- **Protocol**: SPIR
- **Epic**: 0005a-adoption
- **Phase**: Specify
- **Status**: draft

## Problem Statement

Humans who operate FAVA Trails data repositories need to perform two categories of maintenance that currently require direct JJ commands:

1. **Trust gate prompt management** — Editing `trails/trust-gate-prompt.md` and per-scope `trails/<scope>/trust-gate-prompt.md` files
2. **Configuration management** — Editing `config.yaml` (global) and per-trail `.fava-trails.yaml` files

Both operations require a precise 4-step JJ commit sequence (`describe → new -m → bookmark set → push`) that is extremely error-prone for humans unfamiliar with JJ's working-copy model. Getting it wrong creates phantom empty commits that permanently block push operations (see TICK 1b-002).

The `fava-trail-data` repository's README.md and CLAUDE.md are now 80% devoted to warning users about this footgun and providing exact step-by-step instructions. This is a UX failure — the CLI should make the safe path the easy path.

### Concrete Failure Modes

1. **Phantom empty commits**: User runs `jj new` without `jj describe` first. The undescribed working copy freezes as a permanent commit. All subsequent pushes fail silently via `try_push()`.
2. **Forgotten bookmark advance**: User runs `jj describe` + `jj new` but forgets `jj bookmark set main -r @-`. Remote never advances.
3. **Forgotten push**: User completes the commit sequence but forgets `jj git push -b main`. Remote falls behind.
4. **Direct git commands**: User runs `git commit` or `git add` in a JJ-colocated repo, corrupting JJ's working-copy tracking.

All of these are eliminated by routing data repo writes through the CLI.

## Proposed Solution

Add a `fava-trails data` command group to the existing CLI with subcommands for trust gate prompt and config management. Each subcommand handles the full JJ commit sequence internally, matching what the MCP server does.

### Command: `fava-trails data prompt show`

Display the current trust gate prompt for a given scope.

```bash
# Show root-level prompt
fava-trails data prompt show

# Show scope-specific prompt (with fallback to root)
fava-trails data prompt show --scope mw/eng/fava-trails
```

**Behavior:**
- Reads `$FAVA_TRAILS_DATA_REPO/trails/trust-gate-prompt.md` (root) or `trails/<scope>/trust-gate-prompt.md` (scoped)
- For scoped queries, walks up the scope hierarchy (matching `TrustGatePromptCache.resolve_prompt()` logic) and shows which file matched
- Outputs to stdout for piping

### Command: `fava-trails data prompt edit`

Open the trust gate prompt in `$EDITOR` and commit the change via JJ.

```bash
# Edit root-level prompt
fava-trails data prompt edit

# Edit scope-specific prompt (creates file if it doesn't exist)
fava-trails data prompt edit --scope mw/eng/fava-trails

# Non-interactive: replace from stdin or file
fava-trails data prompt set --scope mw/eng/fava-trails < prompt.md
fava-trails data prompt set --scope mw/eng/fava-trails --file prompt.md
```

**Behavior:**
1. Resolve the data repo root (`get_data_repo_root()`)
2. Determine the prompt file path (root or scoped)
3. Open in `$EDITOR` (or `$VISUAL`, falling back to `vi`)
4. If file changed: run the JJ commit sequence:
   - `jj describe -m "Update trust gate prompt: <scope or root>"`
   - `jj new -m "(new change)"`
   - `jj bookmark set main -r @-`
   - `jj git push -b main` (if `push_strategy == "immediate"`)
5. If file unchanged: print "No changes" and exit

**`fava-trails data prompt set`** is the non-interactive variant — reads new prompt content from `--file` or stdin, writes it, and commits. Useful for automation and CI.

### Command: `fava-trails data config show`

Display the current global or trail-level configuration.

```bash
# Show global config
fava-trails data config show

# Show trail-level config
fava-trails data config show --trail mw/eng/fava-trails
```

### Command: `fava-trails data config set`

Set individual configuration values and commit via JJ.

```bash
# Global config
fava-trails data config set trust_gate llm-oneshot
fava-trails data config set push_strategy immediate
fava-trails data config set trust_gate_model google/gemini-2.5-flash

# Trail-level config
fava-trails data config set --trail mw/eng/fava-trails trust_gate_policy human
fava-trails data config set --trail mw/eng/fava-trails gc_interval_snapshots 1000
```

**Behavior:**
1. Load existing config (global `config.yaml` or trail `.fava-trails.yaml`)
2. Validate the key exists in the respective Pydantic model (`GlobalConfig` or `TrailConfig`)
3. Validate the value type matches the model field
4. Write updated config
5. JJ commit sequence (same as prompt edit)

### Command: `fava-trails data status`

Show the state of the data repo: local vs remote sync status, pending changes, any phantom empty commits.

```bash
fava-trails data status
```

**Output example:**
```
Data repo:  /home/user/.fava-trails
Remote:     https://github.com/org/fava-trails-data.git
Sync:       3 commits ahead of origin/main
Pending:    No uncommitted changes
Health:     OK (no empty-description commits detected)
```

**Health check:** Scan recent `jj log` for commits with "(no description)" — if found, warn and suggest `fava-trails data repair`.

### Command: `fava-trails data repair`

Auto-fix common data repo problems.

```bash
fava-trails data repair
```

**Fixes:**
1. **Phantom empty commits**: Find undescribed commits in the `main..@` range, describe them with `"(auto-repaired empty commit)"`, advance bookmark, push
2. **Stale bookmark**: If `main` is behind `@-`, advance it
3. **Remote behind**: If local is ahead of remote, push

Each fix is reported to the user before execution. Destructive operations (like `jj abandon`) require `--force`.

## Design Decisions

### Why `fava-trails data` not `fava-trails config`?

The data repo is a separate entity from the engine. `fava-trails data` scopes all commands to the data repo, making it clear these operate on `$FAVA_TRAILS_DATA_REPO`, not on the engine's pyproject.toml or the project's `.fava-trails.yaml`.

### Why not MCP tools?

Trust gate prompt editing is a human-operator activity, not an agent activity. The MCP server is agent-facing. The CLI is human-facing. Agents should NOT be able to modify the trust gate prompt — that would let agents weaken their own review criteria.

### JJ commit helper

All write subcommands share a common helper:

```python
async def _jj_commit_and_push(repo_root: Path, message: str) -> None:
    """Commit current working copy changes and push to remote.

    Mirrors the MCP server's commit sequence exactly:
    describe → new -m → bookmark set → push
    """
    jj = JjBackend._find_jj()
    subprocess.run([jj, "describe", "-m", message], cwd=repo_root, check=True)
    subprocess.run([jj, "new", "-m", "(new change)"], cwd=repo_root, check=True)
    subprocess.run([jj, "bookmark", "set", "main", "-r", "@-"], cwd=repo_root, check=True)
    # Push if immediate strategy
    config = load_global_config()
    if config.push_strategy == "immediate":
        subprocess.run([jj, "git", "push", "-b", "main"], cwd=repo_root, check=True)
```

## Files Affected

| File | Change |
|------|--------|
| `src/fava_trails/cli.py` | Add `data` command group with `prompt`, `config`, `status`, `repair` subcommands |
| `tests/test_cli.py` | Tests for all new subcommands (mocked JJ, real file ops) |

## Success Criteria

1. `fava-trails data prompt show` displays the correct prompt (root and scoped)
2. `fava-trails data prompt edit` opens `$EDITOR`, commits changes via JJ, pushes
3. `fava-trails data prompt set` accepts stdin/file input non-interactively
4. `fava-trails data config show` displays global and trail configs
5. `fava-trails data config set` validates keys/values against Pydantic models
6. `fava-trails data status` shows sync state and health
7. `fava-trails data repair` fixes phantom empty commits
8. All write commands use the same JJ commit helper (no duplicate sequences)
9. No write command leaves the repo in a broken state (atomic or rollback)
10. Humans never need to run direct JJ write commands in the data repo again

## Out of Scope

- MCP tool equivalents (agents don't manage trust gate prompts)
- Per-scope config inheritance UI (display only — inheritance logic already exists in `config.py`)
- Interactive prompt editor with syntax highlighting
- Data repo migration from per-trail repos (historical — already done)
- Trust gate prompt versioning/rollback (JJ history provides this)

# FAVA Trails Data Repository

Shared data repository for [FAVA Trails](https://github.com/MachineWisdomAI/fava-trails) — versioned, auditable memory for AI agents via MCP.

## Repository layout

```
config.yaml                  # Global config (remote URL, trust gate, push strategy)
trails/
  trust-gate-prompt.md       # Prompt used by the LLM trust gate to review thoughts
  <org>/<team>/<project>/
    .fava-trails.yaml        # Per-trail config
    thoughts/
      drafts/                # Unpromoted work-in-progress thoughts
      observations/          # Promoted observations (evidence-backed findings)
      decisions/             # Promoted decisions (choices with rationale)
      intents/               # Promoted intents
      preferences/
        firm/                # Firm preferences (org-level)
        client/              # Client preferences (user-level)
```

Thoughts are Markdown files with YAML frontmatter, named by ULID (e.g., `01KJ8HB6...md`).

## Version control: JJ + Git (colocated)

This repo uses **Jujutsu (JJ)** in colocated mode with Git. JJ manages the working copy and commit graph; Git handles the remote. The FAVA Trails MCP server commits thoughts automatically via JJ.

### Key commands

```bash
# Check repo state
jj log
jj status

# Sync from remote (other agents/machines)
jj git fetch
jj rebase -d main@origin

# Push local commits to GitHub
jj git push -b main
```

## Direct commands policy

**The FAVA Trails MCP server owns this repo's commit graph. Do not run write commands directly.**

The MCP server follows a strict sequence: `describe → new → bookmark set → push`. Any `jj new` or `jj commit` run outside this sequence creates phantom empty commits that block future pushes.

### Forbidden (never run these)

```bash
jj new          # Creates empty commits that block pushes
jj commit       # Disrupts the MCP server's commit sequence
git commit      # Never — JJ is the only interface
git add         # Never — JJ manages the working copy
```

### Allowed (safe operations)

```bash
jj git push -b main                          # Push local commits to remote
jj git push --allow-empty-description -b main  # If blocked by empty-description commit
jj git fetch && jj rebase -d main@origin     # Pull remote changes
jj log / jj status / jj diff                 # Read-only inspection
```

### Exception: updating the trust gate prompt

The only file a human operator may edit directly is `trails/trust-gate-prompt.md`. After editing:

```bash
jj describe -m "Update trust gate prompt: <reason>"
jj new -m "(new change)"
jj bookmark set main -r @-
jj git push -b main
```

> **Do not skip or reorder steps.** Skipping `jj describe` before `jj new` creates phantom empty commits. Always pass `-m` to `jj new`.

## How agents interact with this repo

Agents never touch this repo directly. They use the FAVA Trails MCP tools (`save_thought`, `propose_truth`, `recall`, `sync`, etc.), which handle JJ operations internally.

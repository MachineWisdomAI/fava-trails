# CLAUDE.md — FAVA Trails Data Repository

> This file contains instructions specific to Claude Code. For other AI coding tools (Codex, Crush, etc.), see AGENTS.md.

## What this repo is

This is the shared data store for FAVA Trails. It contains agent thoughts (observations, decisions, preferences) organized by scope (`trails/<org>/<team>/<project>/`). **The FAVA Trails MCP server owns this repo's commit graph.** Do not modify it directly unless following the specific procedures below.

## Direct commands policy

**Do NOT run any of these in this repo:**

```
jj new          # Creates empty commits that block pushes
jj commit       # Disrupts the MCP server's commit sequence
jj describe     # Only the MCP server should describe commits
                # (exception: trust gate procedure below — follow it exactly)
git commit      # Never — JJ is the only interface
git add         # Never — JJ manages the working copy
git reset       # Never — destroys the commit graph
```

**Why**: The MCP server follows a strict sequence — `describe → new → bookmark set → push`. Any bare `jj new` run outside this sequence freezes an empty or mis-described commit as `@-`. The push hook then sets `main` to that phantom commit, and JJ refuses to push the whole chain.

## Allowed operations

### Push local commits to remote

```bash
jj git push -b main
```

If blocked by a no-description commit:

```bash
jj git push --allow-empty-description -b main
```

### Pull remote changes

```bash
jj git fetch
jj rebase -d main@origin
```

### Inspect (always safe)

```bash
jj log
jj status
jj diff
jj op log --limit 20
```

## Updating the trust gate prompt

The trust gate LLM prompt lives at `trails/trust-gate-prompt.md`. This is the **only file** you may edit directly. Follow this exact sequence:

```bash
# 1. Edit the file
$EDITOR trails/trust-gate-prompt.md

# 2. Verify the change
jj diff

# 3. Describe the current working copy
jj describe -m "Update trust gate prompt: <reason>"

# 4. Freeze the commit and create new working copy
jj new -m "(new change)"

# 5. Advance main to the described commit
jj bookmark set main -r @-

# 6. Push to remote
jj git push -b main
```

> **Do not skip or reorder any step.** Steps 3–6 mirror what the MCP server does. Skipping `jj describe` before `jj new` creates phantom empty commits.

## If something goes wrong

```bash
# Inspect the commit graph
jj log

# Is origin behind?
jj log -r "main@origin..main" --no-graph

# Push
jj git push -b main

# Is local behind?
jj git fetch && jj rebase -d main@origin
```

### If you accidentally ran `jj new` without describing first

**Stop. Do not run further write commands.** Share the output of `jj log --limit 10` and `jj op log --limit 10` with the maintainer for recovery.

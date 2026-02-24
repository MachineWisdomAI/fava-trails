# FAVA Trail

**Federated Agents Versioned Audit Trail** — VCS-backed memory for AI agents via MCP.

Every thought, decision, and observation is stored as a markdown file with YAML frontmatter, tracked in a [Jujutsu (JJ)](https://jj-vcs.github.io/jj/) colocated git monorepo. Agents interact through [MCP](https://modelcontextprotocol.io/) tools — they never see VCS commands.

## Why

- **Supersession tracking** — when an agent corrects a belief, the old version is hidden from default recall. No contradictory memories.
- **Draft isolation** — working thoughts stay in `drafts/`. Other agents only see promoted thoughts.
- **Full lineage** — every thought carries who wrote it, when, and why it changed.
- **Crash-proof** — JJ auto-snapshots. No unsaved work.
- **Engine/Fuel split** — this repo is the engine (stateless MCP server). Your data lives in a separate repo you control.

## Install

```bash
# 1. Install JJ (required, one-time)
bash scripts/install-jj.sh

# 2. Install dependencies
uv sync
```

## Quick Start

### Set up your data repo

```bash
# Create an empty repo on GitHub (or any git remote), then clone it
git clone https://github.com/YOUR-ORG/fava-trail-data.git

# Bootstrap it (creates config, .gitignore, initializes JJ)
bash scripts/bootstrap-data-repo.sh fava-trail-data
```

### Register the MCP server

Add to `~/.claude.json` (Claude Code) or `claude_desktop_config.json` (Claude Desktop):

```json
{
  "mcpServers": {
    "fava-trail": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fava-trail", "fava-trail-server"],
      "env": {
        "FAVA_TRAIL_DATA_REPO": "/path/to/fava-trail-data"
      }
    }
  }
}
```

For Claude Desktop on Windows (accessing WSL):

```json
{
  "mcpServers": {
    "fava-trail": {
      "command": "wsl.exe",
      "args": [
        "-e", "bash", "-lc",
        "FAVA_TRAIL_DATA_REPO=/path/to/fava-trail-data uv run --directory /path/to/fava-trail fava-trail-server"
      ]
    }
  }
}
```

### Use it

Agents call MCP tools. Core workflow:

```
save_thought("My finding about X", source_type="observation")
  → creates a draft in drafts/

propose_truth(thought_id)
  → promotes to observations/ (visible to all agents)

recall(query="X")
  → finds the promoted thought
```

## Cross-Machine Sync

FAVA Trail uses git remotes for cross-machine sync. The bootstrap script sets `push_strategy: immediate` which auto-pushes after every write.

### Setting up a second machine

On the second machine:

```bash
# 1. Install JJ
bash scripts/install-jj.sh

# 2. Clone the SAME data repo
git clone https://github.com/YOUR-ORG/fava-trail-data.git

# 3. Initialize JJ colocated mode + track remote
cd fava-trail-data
jj git init --colocate
jj bookmark track main@origin

# 4. Clone the engine
git clone https://github.com/YOUR-ORG/fava-trail.git

# 5. Install engine dependencies
cd fava-trail && uv sync

# 6. Register MCP (same config as above, with local paths)
```

That's it. Both machines push/pull through the same git remote. Use the `sync` MCP tool to pull latest thoughts from other machines.

### Manual push (if auto-push is off)

```bash
cd /path/to/fava-trail-data
jj bookmark set main -r @-
jj git push --bookmark main
```

**NEVER use `git push origin main`** after JJ colocates — it misses thought commits. See CLAUDE.md "Pushing to Remote" for why.

## Architecture

```
fava-trail (this repo)         fava-trail-data (your repo)
├── src/fava_trail/            ├── config.yaml
│   ├── server.py  ←── MCP ──→├── .gitignore
│   ├── trail.py               └── trails/
│   ├── config.py                  └── default/
│   └── vcs/                           └── thoughts/
│       └── jj_backend.py                 ├── drafts/
└── scripts/                              ├── decisions/
    ├── install-jj.sh                     ├── observations/
    └── bootstrap-data-repo.sh            └── preferences/
```

- **Engine** (`fava-trail`) — stateless MCP server, Apache-2.0
- **Fuel** (`fava-trail-data`) — your organization's trail data, private

## Development

```bash
uv run pytest -v          # run tests
uv run pytest --cov       # with coverage
```

## Docs

- [CLAUDE.md](CLAUDE.md) — Agent-facing: MCP tools reference, data repo setup, push semantics
- [CLAUDE_USAGE_INSTRUCTIONS.md](CLAUDE_USAGE_INSTRUCTIONS.md) — Canonical usage: scope discovery, session protocol, agent identity
- [AGENTS.md](AGENTS.md) — Agent onboarding cheat sheet: session start/end protocol
- [docs/fava_trail_faq.md](docs/fava_trail_faq.md) — Detailed FAQ for framework authors and ML engineers

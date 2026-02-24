# FAVA Trails

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
    "fava-trails": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fava-trails", "fava-trails-server"],
      "env": {
        "FAVA_TRAILS_DATA_REPO": "/path/to/fava-trail-data"
      }
    }
  }
}
```

For Claude Desktop on Windows (accessing WSL):

```json
{
  "mcpServers": {
    "fava-trails": {
      "command": "wsl.exe",
      "args": [
        "-e", "bash", "-lc",
        "FAVA_TRAILS_DATA_REPO=/path/to/fava-trail-data uv run --directory /path/to/fava-trails fava-trails-server"
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
git clone https://github.com/YOUR-ORG/fava-trails.git

# 5. Install engine dependencies
cd fava-trails && uv sync

# 6. Register MCP (same config as above, with local paths)
```

That's it. Both machines push/pull through the same git remote. Use the `sync` MCP tool to pull latest thoughts from other machines.

### Manual push (if auto-push is off)

```bash
cd /path/to/fava-trail-data
jj bookmark set main -r @-
jj git push --bookmark main
```

**NEVER use `git push origin main`** after JJ colocates — it misses thought commits. See [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md#pushing-to-remote) for the correct protocol.

## Architecture

```
fava-trails (this repo)        fava-trail-data (your repo)
├── src/fava_trails/           ├── config.yaml
│   ├── server.py  ←── MCP ──→├── .gitignore
│   ├── trail.py               └── trails/
│   ├── config.py                  └── default/
│   └── vcs/                           └── thoughts/
│       └── jj_backend.py                 ├── drafts/
└── scripts/                              ├── decisions/
    ├── install-jj.sh                     ├── observations/
    └── bootstrap-data-repo.sh            └── preferences/
```

- **Engine** (`fava-trails`) — stateless MCP server, Apache-2.0
- **Fuel** (`fava-trail-data`) — your organization's trail data, private

## Configuration

Environment variables:

| Variable | Read by | Purpose | Default |
|----------|---------|---------|---------|
| `FAVA_TRAILS_DATA_REPO` | Server | Root directory for trail data (monorepo root) | `~/.fava-trail` |
| `FAVA_TRAILS_DIR` | Server | Override trails directory location (absolute path) | `$FAVA_TRAILS_DATA_REPO/trails` |
| `FAVA_TRAIL_SCOPE_HINT` | Server | Broad scope hint baked into tool descriptions | *(none)* |
| `FAVA_TRAIL_SCOPE` | Agent | Project-specific scope from `.env` file | *(none)* |

The server reads `$FAVA_TRAILS_DATA_REPO/config.yaml` for global settings. Minimal `config.yaml`:

```yaml
trails_dir: trails          # relative to FAVA_TRAILS_DATA_REPO
remote_url: null            # git remote URL (optional)
push_strategy: manual       # manual | immediate
```

When `push_strategy: immediate`, the server auto-pushes after every successful write. Push failures are non-fatal.

See [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md) for full config reference including trust gate and per-trail overrides.

## Development

```bash
uv run pytest -v          # run tests
uv run pytest --cov       # with coverage
```

## Docs

- [AGENTS.md](AGENTS.md) — Agent-facing: MCP tools reference, scope discovery, thought lifecycle, agent conventions
- [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md) — Canonical usage: scope discovery, session protocol, agent identity
- [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md) — Data repo setup, config reference, trust gate prompts
- [docs/fava_trail_faq.md](docs/fava_trail_faq.md) — Detailed FAQ for framework authors and ML engineers

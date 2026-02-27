[![PyPI](https://img.shields.io/pypi/v/fava-trails)](https://pypi.org/project/fava-trails/)
[![License](https://img.shields.io/github/license/MachineWisdomAI/fava-trails)](LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/MachineWisdomAI/fava-trails/test.yml?label=tests)](https://github.com/MachineWisdomAI/fava-trails/actions)
[![Python](https://img.shields.io/pypi/pyversions/fava-trails)](https://pypi.org/project/fava-trails/)

# FAVA Trails

**Federated Agents Versioned Audit Trail** — VCS-backed memory for AI agents via MCP.

Every thought, decision, and observation is stored as a markdown file with YAML frontmatter, tracked in a [Jujutsu (JJ)](https://jj-vcs.github.io/jj/) colocated git monorepo. Agents interact through [MCP](https://modelcontextprotocol.io/) tools — they never see VCS commands.

## Why

- **Supersession tracking** — when an agent corrects a belief, the old version is hidden from default recall. No contradictory memories.
- **Draft isolation** — working thoughts stay in `drafts/`. Other agents only see promoted thoughts.
- **Trust Gate** — an LLM-based reviewer validates thoughts before they enter shared truth. Hallucinations stay contained in draft.
- **Full lineage** — every thought carries who wrote it, when, and why it changed.
- **Crash-proof** — JJ auto-snapshots. No unsaved work.
- **Engine/Fuel split** — this repo is the engine (stateless MCP server). Your data lives in a separate repo you control.

## Install

### Prerequisites

Install [Jujutsu (JJ)](https://jj-vcs.github.io/jj/) — FAVA Trails uses JJ as its VCS engine:

```bash
bash scripts/install-jj.sh
```

### From PyPI (recommended)

```bash
pip install fava-trails
```

### From source (for development)

```bash
git clone https://github.com/MachineWisdomAI/fava-trails.git
cd fava-trails
uv sync
```

## Quick Start

### Set up your data repo

```bash
# Create an empty repo on GitHub (or any git remote), then clone it
git clone https://github.com/YOUR-ORG/fava-trails-data.git

# Bootstrap it (creates config, .gitignore, initializes JJ)
fava-trails bootstrap fava-trails-data
```

### Register the MCP server

Add to `~/.claude.json` (Claude Code) or `claude_desktop_config.json` (Claude Desktop):

**If installed from PyPI:**

```json
{
  "mcpServers": {
    "fava-trails": {
      "command": "fava-trails-server",
      "env": {
        "FAVA_TRAILS_DATA_REPO": "/path/to/fava-trails-data"
      }
    }
  }
}
```

**If installed from source:**

```json
{
  "mcpServers": {
    "fava-trails": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/fava-trails", "fava-trails-server"],
      "env": {
        "FAVA_TRAILS_DATA_REPO": "/path/to/fava-trails-data"
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
        "FAVA_TRAILS_DATA_REPO=/path/to/fava-trails-data fava-trails-server"
      ]
    }
  }
}
```

### Use it

Agents call MCP tools. Core workflow:

```
save_thought(trail_name="myorg/eng/my-project", content="My finding about X", source_type="observation")
  → creates a draft in drafts/

propose_truth(trail_name="myorg/eng/my-project", thought_id=thought_id)
  → promotes to observations/ (visible to all agents)

recall(trail_name="myorg/eng/my-project", query="X")
  → finds the promoted thought
```

Agents interact through MCP tools — they never see VCS commands. JJ expertise is not required.

## Cross-Machine Sync

FAVA Trails uses git remotes for cross-machine sync. The `fava-trails bootstrap` command sets `push_strategy: immediate` which auto-pushes after every write.

### Setting up a second machine

```bash
# 1. Install JJ
bash scripts/install-jj.sh

# 2. Install FAVA Trails
pip install fava-trails

# 3. Clone the SAME data repo
git clone https://github.com/YOUR-ORG/fava-trails-data.git

# 4. Initialize JJ colocated mode + track remote
cd fava-trails-data
jj git init --colocate
jj bookmark track main@origin

# 5. Register MCP (same config as above, with local paths)
```

Both machines push/pull through the same git remote. Use the `sync` MCP tool to pull latest thoughts from other machines.

### Manual push (if auto-push is off)

```bash
cd /path/to/fava-trails-data
jj bookmark set main -r @-
jj git push --bookmark main
```

**NEVER use `git push origin main`** after JJ colocates — it misses thought commits. See [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md#pushing-to-remote) for the correct protocol.

## Architecture

```
fava-trails (this repo)        fava-trails-data (your repo)
├── src/fava_trails/           ├── config.yaml
│   ├── server.py  ←── MCP ──→├── .gitignore
│   ├── cli.py                 └── trails/
│   ├── trail.py                   └── myorg/eng/project/
│   ├── config.py                      └── thoughts/
│   ├── trust_gate.py                      ├── drafts/
│   └── vcs/                               ├── decisions/
│       └── jj_backend.py                  ├── observations/
└── scripts/                               └── preferences/
    └── install-jj.sh
```

- **Engine** (`fava-trails`) — stateless MCP server, Apache-2.0. Install via `pip install fava-trails`.
- **Fuel** (`fava-trails-data`) — your organization's trail data, private.

## Configuration

Environment variables:

| Variable | Read by | Purpose | Default |
|----------|---------|---------|---------|
| `FAVA_TRAILS_DATA_REPO` | Server | Root directory for trail data (monorepo root) | `~/.fava-trails` |
| `FAVA_TRAILS_DIR` | Server | Override trails directory location (absolute path) | `$FAVA_TRAILS_DATA_REPO/trails` |
| `FAVA_TRAILS_SCOPE_HINT` | Server | Broad scope hint baked into tool descriptions | *(none)* |
| `FAVA_TRAILS_SCOPE` | Agent | Project-specific scope from `.env` file | *(none)* |

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
- [docs/fava_trails_faq.md](docs/fava_trails_faq.md) — Detailed FAQ for framework authors and ML engineers

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, how to run tests, and PR expectations.

See [CHANGELOG.md](CHANGELOG.md) for release history.

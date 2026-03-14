[![PyPI](https://img.shields.io/pypi/v/fava-trails)](https://pypi.org/project/fava-trails/)
[![License](https://img.shields.io/github/license/MachineWisdomAI/fava-trails)](LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/MachineWisdomAI/fava-trails/test.yml?label=tests)](https://github.com/MachineWisdomAI/fava-trails/actions)
[![Python](https://img.shields.io/pypi/pyversions/fava-trails)](https://pypi.org/project/fava-trails/)
[![Views](https://raw.githubusercontent.com/MachineWisdomAI/fava-trails/traffic/traffic-fava-trails/views.svg)](https://github.com/MachineWisdomAI/fava-trails)

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
fava-trails install-jj
```

Or install manually from [jj-vcs.github.io/jj](https://jj-vcs.github.io/jj/).

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

**New data repo (from scratch):**

```bash
# Create an empty repo on GitHub (or any git remote), then clone it
git clone https://github.com/YOUR-ORG/fava-trails-data.git

# Bootstrap it (creates config, .gitignore, initializes JJ)
fava-trails bootstrap fava-trails-data
```

**Existing data repo (clone from remote):**

```bash
fava-trails clone https://github.com/YOUR-ORG/fava-trails-data.git fava-trails-data
```

### Register the MCP server

Add to your MCP client config:
- **Claude Code CLI**: `~/.claude.json` (top-level `mcpServers` key)
- **Claude Desktop**: `claude_desktop_config.json`

**If installed from PyPI:**

```json
{
  "mcpServers": {
    "fava-trails": {
      "command": "fava-trails-server",
      "env": {
        "FAVA_TRAILS_DATA_REPO": "/path/to/fava-trails-data",
        "OPENROUTER_API_KEY": "sk-or-v1-..."
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
        "FAVA_TRAILS_DATA_REPO": "/path/to/fava-trails-data",
        "OPENROUTER_API_KEY": "sk-or-v1-..."
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
        "FAVA_TRAILS_DATA_REPO=/path/to/fava-trails-data OPENROUTER_API_KEY=sk-or-v1-... fava-trails-server"
      ]
    }
  }
}
```

> **The Trust Gate uses LLM verification:** Thoughts are reviewed before promotion to ensure they're coherent and safe. By default, FAVA Trails uses [OpenRouter](https://openrouter.ai/) to access 300–500+ models from 60+ providers including Anthropic, OpenAI, Google, Qwen, and others. Get a free API key at [openrouter.ai/keys](https://openrouter.ai/keys). The default model (`google/gemini-2.5-flash`) costs ~$0.001 per review. Multi-provider support via [any-llm-sdk](https://github.com/mozilla-ai/any-llm) enables switching to other providers by modifying `config.yaml`.

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
# 1. Install FAVA Trails
pip install fava-trails

# 2. Install JJ
fava-trails install-jj

# 3. Clone the SAME data repo (handles colocated mode + bookmark tracking)
fava-trails clone https://github.com/YOUR-ORG/fava-trails-data.git fava-trails-data

# 4. Register MCP (same config as above, with local paths)
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
│   ├── hook_manifest.py                   ├── decisions/
│   ├── protocols/                         ├── observations/
│   │   └── secom/                         └── preferences/
│   └── vcs/
│       └── jj_backend.py
└── tests/
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
| `OPENROUTER_API_KEY` | Server | API key for Trust Gate LLM reviews via [OpenRouter](https://openrouter.ai/keys) | *(none — required for `propose_truth`)* |

**LLM Provider:** FAVA Trails uses [any-llm-sdk](https://github.com/mozilla-ai/any-llm) for unified LLM access. OpenRouter is the default provider (recommended for simplicity — single API key, 300–500+ models from 60+ providers). Additional providers (Anthropic, OpenAI, Bedrock, etc.) can be configured in `config.yaml` for future versions.

The server reads `$FAVA_TRAILS_DATA_REPO/config.yaml` for global settings. Minimal `config.yaml`:

```yaml
trails_dir: trails          # relative to FAVA_TRAILS_DATA_REPO
remote_url: null            # git remote URL (optional)
push_strategy: manual       # manual | immediate
```

When `push_strategy: immediate`, the server auto-pushes after every successful write. Push failures are non-fatal.

See [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md) for full config reference including trust gate and per-trail overrides.

## Protocols

FAVA Trails supports optional **lifecycle protocols** — hook modules that run custom logic at key points in the thought lifecycle (save, promote, recall). Protocols are registered in your data repo's `config.yaml` and loaded at server startup.

### SECOM — Compression at Promote Time

Extractive token-level compression via [LLMLingua-2](https://github.com/microsoft/LLMLingua), based on the [SECOM paper](https://arxiv.org/abs/2502.05589) (Tsinghua University and Microsoft, ICLR 2025). Thoughts are compressed once at promote time (WORM pattern), reducing storage and boosting recall density. Purely extractive — only original tokens survive, no paraphrasing or rewriting.

```bash
pip install fava-trails[secom]
```

Add to your data repo's `config.yaml`:

```yaml
hooks:
  - module: fava_trails.protocols.secom
    points: [before_propose, before_save, on_recall]
    order: 20
    fail_mode: open
    config:
      compression_threshold_chars: 500
      target_compress_rate: 0.6
      compression_engine:
        type: llmlingua
```

**Structured data**: SECOM's token-level compression has no notion of syntactic validity — JSON objects, YAML blocks, and fenced code blocks may be silently destroyed at promote time. Tag thoughts with `secom-skip` to opt out:

```python
save_thought(trail_name="my/scope", content='{"phases": [...]}', metadata={"tags": ["secom-skip"]})
```

The `before_save` hook warns when structured content is detected without `secom-skip`.

See [protocols/secom/README.md](src/fava_trails/protocols/secom/README.md) for full config reference, model options, and the `secom-skip` opt-out. See [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md#lifecycle-hooks) for the general hooks system.

**Quick setup via CLI:**

```bash
# Print default config (copy-paste into config.yaml)
fava-trails secom setup

# Write config directly + commit with jj
fava-trails secom setup --write

# Pre-download model to avoid first-use delay
fava-trails secom warmup
```

### ACE — Agentic Context Engineering

Playbook-driven reranking and anti-pattern detection, based on [ACE (arXiv:2510.04618)](https://arxiv.org/abs/2510.04618) (Stanford, UC Berkeley, and SambaNova, ICLR 2026). Applies multiplicative scoring using rules stored in the `preferences/` namespace.

```bash
pip install fava-trails  # included in base install
```

Add to your data repo's `config.yaml`:

```yaml
hooks:
  - module: fava_trails.protocols.ace
    points: [on_startup, on_recall, before_save, after_save, after_propose, after_supersede]
    order: 10
    fail_mode: open
    config:
      playbook_namespace: preferences
      telemetry_max_per_scope: 10000
```

**Quick setup via CLI:**

```bash
fava-trails ace setup           # print default config
fava-trails ace setup --write   # write + jj commit
```

### RLM — MapReduce Orchestration

Lifecycle hooks for [MIT RLM (arXiv:2512.24601)](https://arxiv.org/abs/2512.24601) MapReduce workflows. Validates mapper outputs, tracks batch progress, and sorts results deterministically for reducer consumption.

```bash
pip install fava-trails  # included in base install
```

Add to your data repo's `config.yaml`:

```yaml
hooks:
  - module: fava_trails.protocols.rlm
    points: [before_save, after_save, on_recall]
    order: 15
    fail_mode: closed
    config:
      expected_mappers: 5
      min_mapper_output_chars: 20
```

**Quick setup via CLI:**

```bash
fava-trails rlm setup           # print default config
fava-trails rlm setup --write   # write + jj commit
```

## Development

```bash
uv run pytest -v          # run tests
uv run pytest --cov       # with coverage
```

## Docs

- [AGENTS.md](AGENTS.md) — Agent-facing: MCP tools reference, scope discovery, thought lifecycle, agent conventions
- [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md) — Canonical usage: scope discovery, session protocol, agent identity
- [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md) — Data repo setup, config reference, trust gate prompts, lifecycle hooks
- [protocols/secom/README.md](src/fava_trails/protocols/secom/README.md) — SECOM compression protocol: config, models, WORM architecture
- [docs/fava_trails_faq.md](docs/fava_trails_faq.md) — Detailed FAQ for framework authors and ML engineers

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, how to run tests, and PR expectations.

See [CHANGELOG.md](CHANGELOG.md) for release history.

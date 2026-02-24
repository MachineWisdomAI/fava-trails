# Setting Up FAVA Trail

Instructions for creating and configuring a FAVA Trail data repo. For day-to-day usage (scope discovery, session protocol), see [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md).

## Prerequisites

Install [Jujutsu (JJ)](https://jj-vcs.github.io/jj/):

```bash
bash scripts/install-jj.sh
```

Install engine dependencies:

```bash
uv sync
```

## Creating the Data Repo

The data repo is a plain git repository that the MCP server JJ-colocates on first use. It holds your organization's trail data — separate from the engine.

### Automated (recommended)

```bash
# 1. Create an empty repo on GitHub, then clone it
git clone https://github.com/YOUR-ORG/fava-trail-data.git

# 2. Run the bootstrap script
bash scripts/bootstrap-data-repo.sh fava-trail-data
```

The script validates the repo is empty, creates `config.yaml` + `.gitignore`, commits via git (once), initializes JJ colocated mode, and tracks the remote bookmark.

### Manual

```bash
git clone https://github.com/YOUR-ORG/fava-trail-data.git
cd fava-trail-data
```

Create exactly **two files** — nothing else:

**`config.yaml`:**
```yaml
default_trail: default
trails_dir: trails
remote_url: "https://github.com/YOUR-ORG/fava-trail-data.git"
push_strategy: immediate
```

**`.gitignore`:**
```
.jj/
__pycache__/
*.pyc
.venv/
```

> **CRITICAL — do NOT add `trails/` to `.gitignore`.** Trails are plain subdirectories of the monorepo tracked by the same git/JJ repo. Gitignoring `trails/` means thought files are never committed and never pushed to remote.

Do not add a README, CLAUDE.md, Makefile, or any other files. The MCP server creates `trails/` on first use.

```bash
# Commit and push (git — bootstrap only, LAST time you use git push)
git add config.yaml .gitignore
git commit -m "Bootstrap fava-trail-data"
git push origin main

# Initialize JJ colocated mode
jj git init --colocate
jj bookmark track main@origin
```

`jj bookmark track main@origin` is **required once** for auto-push to work. The MCP server calls `jj git init --colocate` automatically if `.jj/` is missing, but it does not set up bookmark tracking.

### After setup

Register the MCP server (see [CLAUDE.md](CLAUDE.md#mcp-registration)), then use MCP tools (`save_thought`, `recall`, etc.) for all trail operations. Do not use `git` commands to manage thought files.

## Setting Up a Second Machine

```bash
# 1. Clone the SAME data repo
git clone https://github.com/YOUR-ORG/fava-trail-data.git

# 2. Initialize JJ colocated mode + track remote
cd fava-trail-data
jj git init --colocate
jj bookmark track main@origin

# 3. Register the MCP server (same config, with local paths)
```

Both machines push/pull through the same git remote. Use the `sync` MCP tool to pull latest thoughts.

## Global Config Reference (`config.yaml`)

```yaml
# Required
trails_dir: trails                        # relative to FAVA_TRAIL_DATA_REPO
remote_url: "https://github.com/..."      # git remote URL (null if local-only)
push_strategy: immediate                  # manual | immediate

# Trust Gate
trust_gate: llm-oneshot                   # llm-oneshot | human (future)
trust_gate_model: google/gemini-2.5-flash # model for LLM-based review
openrouter_api_key_env: OPENROUTER_API_KEY # env var name for API key

# Per-trail overrides (optional)
trails:
  mw/eng/sensitive-project:
    trust_gate_policy: human              # override for this trail
    stale_draft_days: 30                  # tombstone drafts older than 30 days
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trails_dir` | string | `trails` | Directory for trail data (relative to repo root) |
| `remote_url` | string | `null` | Git remote URL for sync |
| `push_strategy` | string | `manual` | `immediate` auto-pushes after writes; `manual` requires explicit sync |
| `trust_gate` | string | `llm-oneshot` | Global trust gate policy |
| `trust_gate_model` | string | `google/gemini-2.5-flash` | Model for LLM-based trust review |
| `openrouter_api_key_env` | string | `OPENROUTER_API_KEY` | Env var name holding the API key |

### Per-Trail Config

Override global settings for specific trails via the `trails` map:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trust_gate_policy` | string | *(inherits global)* | Override trust gate for this trail |
| `gc_interval_snapshots` | int | `500` | Snapshots between GC runs |
| `gc_interval_seconds` | int | `3600` | Seconds between GC runs |
| `stale_draft_days` | int | `0` | Tombstone drafts older than N days (0 = disabled) |

## Trust Gate Prompts

The Trust Gate uses a `trust-gate-prompt.md` file to instruct the reviewing LLM on what to approve or reject. These files live **inside the data repo**, alongside the trails they govern.

### Placement

```
FAVA_TRAIL_DATA_REPO/
├── config.yaml
└── trails/
    ├── trust-gate-prompt.md              # Root prompt — applies to all trails
    └── mw/
        ├── trust-gate-prompt.md          # Company-level override
        └── eng/
            └── fava-trails/
                └── trust-gate-prompt.md  # Project-level override
```

### Resolution Order

When reviewing a thought at scope `mw/eng/fava-trails`, the server checks:

1. `trails/mw/eng/fava-trails/trust-gate-prompt.md` (most specific)
2. `trails/mw/eng/trust-gate-prompt.md`
3. `trails/mw/trust-gate-prompt.md`
4. `trails/trust-gate-prompt.md` (root fallback)

The **most specific** match wins. If no prompt is found at any level, `propose_truth` returns an error — you must create at least one prompt.

### Writing a Prompt

The prompt is plain markdown. It's sent to the trust gate model along with the thought's content and metadata. See [TRUST_GATE_PROMPT_EXAMPLE.md](TRUST_GATE_PROMPT_EXAMPLE.md) for a working example.

Prompt files are cached in memory at server startup and never re-read during a session. This prevents adversarial agents from modifying prompts mid-session.

## Pushing to Remote

**NEVER use `git push origin main`** after JJ colocates. In JJ colocated mode:
- HEAD is always **detached** — JJ manages commits, not git
- Thought commits live on the detached HEAD chain, not on the `main` git branch
- `git push origin main` only pushes the git `main` bookmark — it misses all thought commits

**If `push_strategy: immediate` is set** (recommended), the server auto-pushes the main bookmark after every write. No manual action needed.

**If you need to push manually:**
```bash
# From within fava-trail-data:
jj bookmark set main -r @-     # advance main bookmark to latest committed change
jj git push --bookmark main    # push to remote
```

## Data Repo Layout

```
FAVA_TRAIL_DATA_REPO/           # Monorepo root (.jj/ + .git/)
├── config.yaml                 # Global config
├── .gitignore
└── trails/
    ├── trust-gate-prompt.md    # Root trust gate prompt
    └── mw/                     # Company scope
        ├── thoughts/
        │   ├── drafts/
        │   ├── decisions/
        │   ├── observations/
        │   ├── intents/
        │   └── preferences/
        │       ├── client/
        │       └── firm/
        └── eng/                # Team scope
            ├── thoughts/...
            └── fava-trails/    # Project scope
                ├── thoughts/...
                ├── trust-gate-prompt.md  # Project-specific prompt
                └── auth-epic/  # Task/epic scope
                    └── thoughts/...
```

Each trail is a subdirectory — NOT a separate repo. The entire monorepo shares a single JJ/git history.

# Setting Up FAVA Trails

Instructions for creating and configuring a FAVA Trails data repo. For day-to-day usage (scope discovery, session protocol), see [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md).

## Prerequisites

Install [Jujutsu (JJ)](https://jj-vcs.github.io/jj/):

```bash
fava-trails install-jj
```

Install FAVA Trails:

```bash
# From PyPI (recommended)
pip install fava-trails

# Or from source (for development)
git clone https://github.com/MachineWisdomAI/fava-trails.git && cd fava-trails && uv sync
```

### LLM Configuration (for Trust Gate)

The Trust Gate reviews thoughts before promotion using an LLM. By default, FAVA Trails uses [OpenRouter](https://openrouter.ai/) for unified access to 100+ models.

**OpenRouter (default, recommended):**

1. Create a free account at https://openrouter.ai/
2. Generate an API key at https://openrouter.ai/keys
3. Pass it to the MCP server via the `OPENROUTER_API_KEY` environment variable
   (in your MCP client config `env` block, or in your shell profile)

The default model (`google/gemini-2.5-flash`) costs ~$0.001 per review.

**Other providers:** FAVA Trails uses [any-llm-sdk](https://github.com/mozilla-ai/any-llm) for unified LLM access, enabling support for additional providers (Anthropic, OpenAI, Bedrock, etc.). Configuration for provider selection will be available in future versions via `config.yaml`.

## Creating the Data Repo

The data repo is a plain git repository that the MCP server JJ-colocates on first use. It holds your organization's trail data — separate from the engine.

### Cloning an existing data repo

If someone on your team already bootstrapped a data repo and pushed it to a remote:

```bash
fava-trails clone https://github.com/YOUR-ORG/fava-trails-data.git fava-trails-data
```

This clones in JJ colocated mode and tracks the remote bookmark automatically. Skip to [After setup](#after-setup).

### Creating a new data repo (bootstrap)

```bash
# 1. Create an empty repo on GitHub, then clone it
git clone https://github.com/YOUR-ORG/fava-trails-data.git

# 2. Bootstrap it (creates config, .gitignore, initializes JJ)
fava-trails bootstrap fava-trails-data
```

The bootstrap command creates a **new** data repo from scratch — it does not connect to existing remote data. Use `fava-trails clone` instead if the remote already has data.

### Manual

```bash
git clone https://github.com/YOUR-ORG/fava-trails-data.git
cd fava-trails-data
```

Create exactly **two files** — nothing else:

**`config.yaml`:**
```yaml
trails_dir: trails
remote_url: "https://github.com/YOUR-ORG/fava-trails-data.git"
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
git commit -m "Bootstrap fava-trails-data"
git push origin main

# Initialize JJ colocated mode
jj git init --colocate
jj bookmark track main@origin
```

`jj bookmark track main@origin` is **required once** for auto-push to work. The MCP server calls `jj git init --colocate` automatically if `.jj/` is missing, but it does not set up bookmark tracking.

### After setup

Register the MCP server (see [README.md](README.md#register-the-mcp-server)), then use MCP tools (`save_thought`, `recall`, etc.) for all trail operations. Do not use `git` commands to manage thought files.

## Setting Up a Second Machine

```bash
# 1. Clone the existing data repo
fava-trails clone https://github.com/YOUR-ORG/fava-trails-data.git fava-trails-data

# 2. Register the MCP server (same config, with local paths)
```

Both machines push/pull through the same git remote. Use the `sync` MCP tool to pull latest thoughts.

## Global Config Reference (`config.yaml`)

```yaml
# Required
trails_dir: trails                        # relative to FAVA_TRAILS_DATA_REPO
remote_url: "https://github.com/..."      # git remote URL (null if local-only)
push_strategy: immediate                  # manual | immediate

# Trust Gate
trust_gate: llm-oneshot                   # llm-oneshot | human (future)
trust_gate_model: google/gemini-2.5-flash # model for LLM-based review
openrouter_api_key_env: OPENROUTER_API_KEY # env var name for API key

# Lifecycle hooks (optional, loaded at startup)
hooks:
  - module: fava_trails.protocols.secom   # built-in or PyPI module
    points: [before_propose, before_save, on_recall]
    order: 20
    fail_mode: open
    config: { ... }                       # passed to module's configure()

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
| `openrouter_api_key_env` | string | `OPENROUTER_API_KEY` | Env var name holding the API key for OpenRouter (default provider) |
| `hooks` | list | `[]` | Lifecycle hook entries (see [Lifecycle Hooks](#lifecycle-hooks)) |

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
FAVA_TRAILS_DATA_REPO/
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

## Lifecycle Hooks

Lifecycle hooks let operators run custom Python code at key points in the thought lifecycle: before/after save, before/after promote, after supersede, on recall, on recall mix (cross-trail), and at server startup.

### Setup

Add a `hooks:` section to your data repo's `config.yaml`. Each entry declares a hook module, the lifecycle points it handles, and optional configuration:

```yaml
# config.yaml (at data repo root)
hooks:
  # Built-in protocol (installed as a PyPI extra)
  - module: fava_trails.protocols.secom
    points: [before_propose, before_save, on_recall]
    order: 20
    fail_mode: open
    config:
      compression_threshold_chars: 500
      target_compress_rate: 0.6
      compression_engine:
        type: llmlingua

  # Local hook file (path relative to data repo root)
  - path: ./hooks/quality_gate.py
    points: [before_save, before_propose]
    order: 10                     # lower = runs first (default: 50)
    fail_mode: open               # open (skip on error) | closed (halt on error)
    config:
      min_confidence: 0.3

  # PyPI package
  - module: my_published_package.hooks
    points: [before_save]
    config:
      endpoint: "${METRICS_URL}/push"   # env var interpolation
```

Hooks are loaded once at server startup and cached (anti-tampering pattern). Restart the MCP server after changing hook configuration.

### Hook Contract (v2)

Each hook is an **async function** named after its lifecycle point. It receives a typed **Event** and returns one or more **Actions**:

```python
# quality_gate.py
from fava_trails.hook_types import Reject, Warn, Proceed

async def before_save(event):
    """Reject thoughts with very low confidence."""
    if event.thought and event.thought.frontmatter.confidence < 0.1:
        return Reject(reason="Confidence too low", code="LOW_CONF")
    if event.thought and len(event.thought.content) < 20:
        return Warn(message="Very short thought", code="SHORT")
    return Proceed()
```

### Available Actions

| Action | Effect | Valid for |
|--------|--------|-----------|
| `Proceed()` | Continue pipeline | all |
| `Reject(reason, code)` | Block operation (terminal) | before_save, before_propose |
| `Mutate(patch=ThoughtPatch(...))` | Modify thought content/tags/confidence | before_save, before_propose |
| `Redirect(namespace)` | Save to different namespace (terminal) | before_save, before_propose |
| `Warn(message, code)` | Surface concern in response | all |
| `Advise(message, code, target)` | Guidance for agent | all |
| `Annotate(values={...})` | Attach metadata | all |
| `RecallSelect(ordered_ulids=[...])` | Filter/reorder recall results | on_recall, on_recall_mix |

Hooks can return a single action, `None` (treated as `Proceed`), or a list of actions.

### Config Injection

If your hook module defines a `configure(config)` function, it's called at startup with the `config` dict from `hooks.yaml` (after env var interpolation):

```python
_min_confidence = 0.3

def configure(config):
    global _min_confidence
    _min_confidence = config.get("min_confidence", 0.3)

async def before_save(event):
    if event.thought and event.thought.frontmatter.confidence < _min_confidence:
        return Reject(reason="Below minimum confidence")
```

### HookFeedback in MCP Responses

When hooks produce warnings, advice, or annotations, they appear in the MCP tool response under `hook_feedback`:

```json
{
  "status": "ok",
  "thought": { "thought_id": "..." },
  "hook_feedback": {
    "accepted": true,
    "warnings": [{"message": "Very short thought", "code": "SHORT"}],
    "annotations": {"quality_score": 0.85}
  }
}
```

### TrailContext

Hooks that need to query trail state receive a `TrailContext` via `event.context`. It provides hook-safe methods that bypass hook firing (preventing recursion):

- `await event.context.stats()` — thought count by namespace
- `await event.context.count(namespace=None)` — total or per-namespace count
- `await event.context.recall(query, namespace, limit)` — search thoughts (max 50)

### Lifecycle Points

| Point | When | Pipeline type |
|-------|------|---------------|
| `before_save` | Before thought is written to disk | Gating (can reject/mutate/redirect) |
| `after_save` | After thought is committed | Observer (fire-and-forget) |
| `before_propose` | Before promotion from drafts | Gating (can reject/mutate/redirect) |
| `after_propose` | After promotion is committed | Observer |
| `after_supersede` | After supersession is committed | Observer |
| `on_recall` | During single-trail recall search | Gating (can filter/reorder via RecallSelect) |
| `on_recall_mix` | After cross-trail `recall_multi` merge | Gating (can filter/reorder via RecallSelect) |
| `on_startup` | Server startup | Startup (separate contract) |

### Error Handling

- **`fail_mode: open`** (default): Hook errors/timeouts are logged and skipped — the operation proceeds
- **`fail_mode: closed`**: Hook errors/timeouts halt the operation with an exception
- Import errors with `fail_mode: closed` cause `sys.exit(1)` at startup

### Built-in Protocols

FAVA Trails ships with protocol hook modules that can be enabled via `module:` entries:

| Protocol | Install | Description |
|----------|---------|-------------|
| **SECOM** | `pip install fava-trails[secom]` | Extractive compression at promote time via LLMLingua-2 ([docs](../src/fava_trails/protocols/secom/README.md)) |
| **ACE** | included | Playbook-driven reranking and anti-pattern detection (Stanford/SambaNova ACE) |
| **RLM** | included | MapReduce orchestration hooks for batch workflows (MIT RLM) |

**Quickest way to add a protocol** — use the CLI setup command:

```bash
# Print default config (copy-paste into config.yaml)
fava-trails secom setup
fava-trails ace setup
fava-trails rlm setup

# Or write directly to config.yaml + jj commit in one step
fava-trails secom setup --write
fava-trails ace setup --write
fava-trails rlm setup --write
```

**SECOM** — enable extractive compression:

```yaml
# config.yaml
hooks:
  - module: fava_trails.protocols.secom
    points: [before_propose, before_save, on_recall]
    order: 20
    fail_mode: open
    config:
      compression_threshold_chars: 500
      verbosity_warn_chars: 1000
      target_compress_rate: 0.6
      compression_engine:
        type: llmlingua
```

After installing and configuring, restart the MCP server. The first `propose_truth` that triggers compression will download the LLMLingua-2 model (~700MB) from HuggingFace Hub. Pre-download with:

```bash
fava-trails secom warmup
```

**ACE** — enable playbook-driven reranking:

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

**RLM** — enable MapReduce orchestration:

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

## Pushing to Remote

**NEVER use `git push origin main`** after JJ colocates. In JJ colocated mode:
- HEAD is always **detached** — JJ manages commits, not git
- Thought commits live on the detached HEAD chain, not on the `main` git branch
- `git push origin main` only pushes the git `main` bookmark — it misses all thought commits

**If `push_strategy: immediate` is set** (recommended), the server auto-pushes the main bookmark after every write. No manual action needed.

**If you need to push manually:**
```bash
# From within fava-trails-data:
jj bookmark set main -r @-     # advance main bookmark to latest committed change
jj git push --bookmark main    # push to remote
```

## Data Repo Layout

```
FAVA_TRAILS_DATA_REPO/          # Monorepo root (.jj/ + .git/)
├── config.yaml                 # Global config (includes hooks: section)
├── .gitignore
├── hooks/                      # Local hook files (optional, for path: entries)
│   └── quality_gate.py         # Custom hook implementation
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

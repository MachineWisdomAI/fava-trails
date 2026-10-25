# Setting Up FAVA Trails

Instructions for creating and configuring a FAVA Trails data repo. For day-to-day usage (scope discovery, session protocol), see [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md).

## Prerequisites

Install FAVA Trails, confirm what loaded, then install [Jujutsu (JJ)](https://jj-vcs.github.io/jj/). `install-jj` is a `fava-trails` command, so the package comes first:

```bash
# From PyPI (recommended)
pip install --upgrade fava-trails

# Confirm the loaded runtime (package + module + MCP product version):
fava-trails version

# Install JJ (or reuse a supported one):
fava-trails install-jj
```

Compare the version that `fava-trails version` prints with the [release history](CHANGELOG.md). The printed version, not this guide, tells you which behavior you have.

To work from source (for development), clone the repository and run `uv sync`:

```bash
git clone https://github.com/MachineWisdomAI/fava-trails.git && cd fava-trails && uv sync
```

**Version boundaries.** Governed identity and `mode="authoring"` date from 0.7.0, and a release older than 0.7.0 does not match this guide's identity model. The local-reviewer bootstrap options (`--review-endpoint`, `--review-model`, `--review-key-env`) are marked "from 0.9.0" in this guide and are not in a published package until a release announces them. After any install or upgrade, run `fava-trails version` and restart the MCP client so the process loads the intended entrypoint. See [docs/runtime-and-upgrade.md](docs/runtime-and-upgrade.md).

### LLM Configuration (for Trust Gate)

The Trust Gate reviews thoughts before promotion using a local
OpenAI-compatible `llm-oneshot` reviewer that you name (new data repositories
created by `fava-trails bootstrap` from **0.9.0**), OpenRouter Decisions (Jev),
or an explicit operator approval path. Releases through 0.8.x and any existing
configuration keep their current behavior: with no Trust Gate settings, the
built-in default is still OpenRouter Decisions (Jev). Provider selection is a **data-egress choice**: under the
shipped `decisions` policy, the full scope-resolved Trust Gate prompt, the full
candidate thought content, the selected metadata fields (`agent_id` and
`metadata.extra` are excluded), and the configured Noul question are transmitted
to OpenRouter **before** a verdict exists. A remote reject still means the
content already left this process. There is no automatic pass-through/off mode
and no silent fallback to another provider. Jev returns no reasoning; do not
invent one. Timeouts, auth failures, and invalid answers fail closed.

Before the first promotion on a machine, point `doctor` at the data repository you mean to inspect, then run it. It resolves the repository from `FAVA_TRAILS_DATA_REPO` (default `~/.fava-trails`), so without an absolute path it can inspect an unrelated repository at the default location.

```bash
export FAVA_TRAILS_DATA_REPO=/absolute/path/to/fava-trails-data
fava-trails doctor
```

Per-machine overrides come from `$XDG_CONFIG_HOME/fava-trails/config.yaml`. If you isolate them with a separate `XDG_CONFIG_HOME`, export the same value before `doctor` and give the MCP client's server process the same value (see [After setup](#after-setup)). Otherwise the server reads your normal per-machine file and can send review text to a different destination than the one `doctor` reported.

Doctor prints the effective policy, provider, model, destination, and a plain
**Data egress** explanation of which candidate fields will be sent. API keys and
credential file paths are never printed. The MCP server also logs the same notice
at startup. Successful LLM or operator `propose_truth` paths (and credential /
timeout failures after disclosure begins) include a secret-free
`trust_gate_egress` object (`first_in_process: true` on the first disclosure in
that process). Early validation failures — missing `thought_id`, missing prompt
cache, thought not found, or prompt-resolution errors — return before disclosure
and omit `trust_gate_egress`.

**New installations: local review (0.9.0 and later; no hosted account needed):**

`fava-trails bootstrap` selects the `llm-oneshot` policy and asks you to name
the reviewer. You supply the endpoint and the exact model id your server
serves. FAVA does not assume hardware, download a model, probe localhost, or
read a default credential variable.

Prepare the credential source first, because `fava-trails doctor` needs it. The secret never appears in these commands, a client configuration or a repository file. Choose one route:

- **Process environment.** Populate the variable named by `--review-key-env` (here `LOCAL_REVIEW_KEY`) in the environment of every process that reviews: the shell that runs `fava-trails doctor` and the MCP server process. A desktop client does not inherit your shell, so use the client's explicit environment-forwarding mechanism (for Codex, `env_vars`, shown in the README) rather than writing the value into its configuration. Use the secret mechanism you already trust, and keep the value out of shell history. A server that ignores authentication still needs some value in the variable.
- **Owner-only key file.** Keep the key in a regular, non-symlink file that you own with mode `0600`, outside any repository, and set `trust_gate_api_key_file: <path-to-owner-only-key-file>` in the per-machine config. The file takes precedence over the variable and is reread for each promotion. Bootstrap has no key-file option, so still pass `--review-key-env`.

Then bootstrap and check:

```bash
fava-trails bootstrap fava-trails-data \
  --review-endpoint http://127.0.0.1:8080/v1 \
  --review-model <exact-model-id-your-server-serves> \
  --review-key-env LOCAL_REVIEW_KEY
export FAVA_TRAILS_DATA_REPO="$PWD/fava-trails-data"
fava-trails doctor
```

`--review-key-env` names the variable; bootstrap neither reads nor stores its value.

Done when `fava-trails doctor` prints the effective policy, provider, model and destination with no key value and no key-file path.

With all three options, bootstrap writes `trust_gate: llm-oneshot`,
`trust_gate_provider: openai`, `trust_gate_api_base`, `trust_gate_model` and
`trust_gate_api_key_env` (the variable *name*, never the value) to the data
repository's `config.yaml`, so every clone behaves the same. The endpoint must
be a bare `http(s)://host[:port][/v1]`: URLs with credentials, a query,
a fragment or other path segments are refused because the value is committed
and may be pushed. Bootstrap warns when a loopback endpoint is combined with
`--remote`, since every clone inherits it.

With any option missing, bootstrap writes only `trust_gate: llm-oneshot`, tells
you which options to supply, and finishes. Review fails closed only when the
*effective* configuration is still incomplete: until the endpoint and model are
set (in that `config.yaml` or the per-machine config below), `propose_truth` and
`fava-trails doctor` stop with guidance and nothing is transmitted. A missing
flag never disables a reviewer the machine already has through its per-machine
config, which merges key by key and overrides the repository's fields. A repository
bootstrapped this way behaves differently on a release without the new check:
0.8.x posts the Decisions model as a chat request to OpenRouter when
`OPENROUTER_API_KEY` is set, and 0.7 and earlier use hosted
`google/gemini-2.5-flash`. Upgrade, or supply all three options.

Bootstrap never writes the per-machine config, which is shared by every data
repository on the machine and overrides it key by key. After writing, bootstrap
loads the effective configuration and reports the policy, model, endpoint,
destination kind and every Trust Gate key a per-machine file overrides. It exits
non-zero when the effective destination differs from the one you requested (the
repository is still created). Whether review text stays on this machine depends on
two things: the effective destination in that report, and where the
endpoint actually routes. The report shows the configured destination only; no
override in the report does not by itself show that requests stay local. A
`local_endpoint` label means only that the address is `localhost` or a numeric
loopback address as the calling process sees it. It cannot see a tunnel or port
forward behind that address.

Failures never fall back to a hosted provider. A server that is down, returns
401, or sends a malformed reply produces a recorded `error` verdict and
promotes nothing; a missing credential, missing setting or outer timeout is a
tool error and the record is unchanged. A local reviewer's explanation is
returned to the caller in `trust_gate.reasoning`. Jev (`decisions`) returns a
probability and threshold only, and none of its reasoning is invented. A slow
local model needs a higher `trust_gate_timeout_secs`, which now applies to each
request as well as to the whole review (keep it below `tool_timeout_secs`).
Fixture tests cover protocol handling. One recorded run of an installed 0.9.0rc1
candidate against one local model (`unsloth/Qwen3.6-27B-GGUF`) showed two
rejections with reasoning, then an approval and a correction. That is a single
observation, not a benchmark, and the candidate is not a published release. Whether
a particular model gives useful rejection feedback is for you to confirm with your
own server; see the [local review walkthrough](docs/local-review-walkthrough.md).

**Existing configurations are not rewritten.** Built-in defaults and per-key
fallback are unchanged, so an existing explicit Jev (`decisions`) selection, a
local Laya Decisions configuration, or a hosted `llm-oneshot` configuration
resolves exactly as before. Two additions apply:

- `trust_gate: llm-oneshot` with FAVA's own Decisions model (`~typesafe/jev-latest`,
  the built-in default, or `typesafe/jev-1.13`) is refused before transmission
  with an error naming `trust_gate_model`. Set the chat model your server serves,
  or `trust_gate: decisions` to keep Jev. Explicit operator
  `approval="human"` needs no model and is unaffected.
- When `trust_gate` is not stated but a provider or model is, `fava-trails doctor`,
  server startup logging and a failed promotion add an informational note naming
  the policy that took effect and `trust_gate: llm-oneshot` as the fix for a chat
  model. Behavior is unchanged; the note also appears for a correct local
  Decisions configuration, and stating the policy silences it.

**OpenRouter (hosted Decisions; the built-in default when nothing is configured, remote egress):**

1. Create a free account at https://openrouter.ai/
2. Generate an API key at https://openrouter.ai/keys
3. Give the key to every process that reviews, through the named
   `OPENROUTER_API_KEY` process environment or an owner-only key file
   (`trust_gate_api_key_file` in the per-machine config, mode `0600`, outside any
   repository). A client that starts the server in its own process needs its
   explicit environment-forwarding mechanism for that variable. Never write the key value into a client
   configuration or repository file. Do this before running `fava-trails doctor`,
   which needs the same source.

The default model (`~typesafe/jev-latest`) is OpenRouter Jev via the Decisions
API. Supply an existing OpenRouter key; you do not have to write a Noul
question. Missing cloud credentials fail closed — candidates are **not**
auto-approved. The shipped question and threshold are documented in the
[ticket 03 calibration report](https://github.com/MachineWisdomAI/fava-trails/issues/126#issuecomment-5894849724);
the private corpus is available upon request.

Local Unsloth Laya is the no-per-request-cost alternative for the same
`decisions` policy: set `trust_gate_provider: openai`,
`trust_gate_model: laya-typed-decisions` (do not use the generic `laya`
alias), and `trust_gate_api_base` to your Unsloth Decision API (requests go
to `/v1/systemone`). FAVA does not probe localhost, discover Unsloth, or fall
back between providers. Select exactly one backend.

**Local OpenAI-compatible endpoint (e.g. Unsloth Studio):**

Unsloth Studio (and similar local servers) expose authenticated OpenAI-compatible
`/v1/chat/completions` endpoints. Point Trust Gate at them on one machine via
`$XDG_CONFIG_HOME/fava-trails/config.yaml` (default
`~/.config/fava-trails/config.yaml`) and select `llm-oneshot`:

```yaml
trust_gate: llm-oneshot
trust_gate_provider: openai
trust_gate_model: <exact-model-id-served-by-studio>
trust_gate_api_base: http://127.0.0.1:<studio-api-port>/v1
trust_gate_api_key_file: /path/to/owner-only/runtime/api-key
# Slow quantized local models may need more time; keep this below tool_timeout_secs.
trust_gate_timeout_secs: 240
trust_gate_extra_body:
  enable_thinking: false
```

Check with `fava-trails doctor`: the destination kind should be `local_endpoint`
and `api_base` should match your loopback URL. `doctor` reports the effective
destination and model. It does not test that the endpoint is reachable, that the
model is good, or that review text stays on this host: `local_endpoint` only
classifies `localhost` and numeric loopback addresses, and a tunnel or port
forward behind that address is invisible to it. Confirm where the address
actually routes. A non-loopback `trust_gate_api_base` is classified
`custom_endpoint`, and a hosted provider with no `trust_gate_api_base` is
`remote_provider`. If the endpoint is unavailable or misconfigured, promotion
fails closed. There is **no automatic fallback** to OpenRouter.

The key file must be a regular, non-symlink file owned by the current user with
no group or other permissions (mode `0600`). It is read for every promotion. If
the provider returns 401 and the file value changed, FAVA retries exactly once
with the new value. `trust_gate_api_key_env` remains available as a fallback when
no key file is configured (see [Unsloth API docs](https://unsloth.ai/docs/basics/api)).
Do not hardcode host, port, model, or credentials in the engine. Do not install a
model, select a paid provider, or supply credentials on behalf of an evaluator —
operators choose and provision their own review backend.

**Decisions policy (OpenRouter Jev or local Unsloth Laya):**

Set `trust_gate: decisions` to review promotions through a Decision API instead
of a chat completion. The operator selects exactly one backend. There is no
automatic fallback.

Hosted OpenRouter Jev:

```yaml
trust_gate: decisions
trust_gate_provider: openrouter
trust_gate_model: ~typesafe/jev-latest    # tracking alias; pin typesafe/jev-1.13 if desired
trust_gate_decisions_config:
  trust_gate_noul_question: "Should this candidate be promoted as durable, high-quality institutional memory under the supplied Trust Gate policy?"
  trust_gate_noul_threshold: 0.45
```

Local Unsloth Laya (same credential file / env and timeout as local `llm-oneshot`; inherits the shipped Noul question and threshold unless overridden):

```yaml
trust_gate: decisions
trust_gate_provider: openai
trust_gate_model: laya-typed-decisions    # recommended; do not use the generic laya alias
trust_gate_api_base: http://127.0.0.1:<unsloth-api-port>/v1
trust_gate_api_key_file: /path/to/owner-only/runtime/api-key
trust_gate_timeout_secs: 240
```

Local requests POST to the configured Unsloth base at `/v1/systemone`. The
configured model identifier is forwarded unchanged. Connection, authentication,
timeout, and response errors fail closed without contacting OpenRouter.

**Operator review path (no LLM transmission) — separate from automatic review:**

`trust_gate: human` is **not** implemented as a config policy (it raises). The
supported non-LLM path is per-call explicit operator approval:

1. Run a dedicated operator-controlled MCP process with `FAVA_TRAILS_OPERATOR=1`
   and a configured `FAVA_TRAILS_AGENT_ID` (never enable operator mode on a shared
   authoring endpoint).
2. Call `propose_truth(..., approval="human")` for each candidate.
3. Provenance records `metadata.extra.approval.kind="human"`. No candidate text is
   sent to a remote or local LLM.

This keeps the approval boundary: drafts stay drafts until LLM advisory approval
or explicit operator approval. There is no automatic pass-through that skips the
gate.

Per-machine config may contain only Trust Gate runtime fields. Effective
precedence is machine config, then the data repo's `config.yaml`, then defaults;
repository paths, remotes, push strategy, hooks, and trail definitions cannot be
overridden per machine.

FAVA Trails uses [any-llm-sdk](https://github.com/mozilla-ai/any-llm) for the provider seam.

## Creating the Data Repo

The data repo is a plain git repository that the MCP server JJ-colocates on first use. It holds your organization's trail data — separate from the engine.

### Cloning an existing data repo

If someone on your team already bootstrapped a data repo and pushed it to a remote:

```bash
fava-trails clone https://github.com/YOUR-ORG/fava-trails-data.git fava-trails-data
```

This clones in JJ colocated mode and tracks the remote bookmark automatically. Skip to [After setup](#after-setup).

### Local-only evaluation

A local JJ/Git data repository is valid for evaluation. Bootstrap without a
remote:

```bash
fava-trails bootstrap fava-trails-data \
  --review-endpoint http://127.0.0.1:8080/v1 \
  --review-model <exact-model-id-your-server-serves> \
  --review-key-env LOCAL_REVIEW_KEY
```

The three `--review-*` options configure the local reviewer (0.9.0 and later; see
[LLM Configuration](#llm-configuration-for-trust-gate)). Without them,
bootstrap tells you what to supply and promotion fails closed until you do.

Save, recall, review, and supersession work without a git remote. `sync`
returns `not_configured` with the next step (`git remote add origin <url>` or
`fava-trails clone`). That is not a broken remote. FAVA does not create hosted
repositories, push private content, or change remotes automatically. Do not
pass `--sync-on-start` until a reachable remote is configured; required startup
sync stays fail-closed.

### Creating a new shared data repo (bootstrap)

```bash
# 1. Create an empty repo on a git host you already operate, then clone it
git clone https://github.com/YOUR-ORG/fava-trails-data.git

# 2. Bootstrap it (creates config, .gitignore, initializes JJ)
fava-trails bootstrap fava-trails-data
```

The bootstrap command creates a **new** data repo from scratch — it does not connect to existing remote data. Use `fava-trails clone` instead if the remote already has data. Cross-machine sharing needs a reachable remote plus ongoing access, credential, and hosting maintenance before you rely on `sync`.

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
# bootstrap / CLI default is manual. Use immediate for multi-machine authoring
# so successful writes auto-publish (a successful sync counts as a write). sync itself only fetches/rebases.
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

Register the MCP server, then use MCP tools (`save_thought`, `recall`, etc.) for all trail operations. Do not use `git` commands to manage thought files. Direct stdio testing does not register the server for native sessions.

1. Export the absolute path of the data repository, as in [LLM Configuration](#llm-configuration-for-trust-gate), then print registration instructions for your client: `fava-trails register --agent-id <stable-agent-id>`. This prints only. `--write` updates a client configuration while preserving unrelated settings and keeping a backup. `--verify` runs a direct smoke test and a configuration load check.
2. For Claude Code, Claude Desktop and any client that takes the standard JSON shape, use the printed instructions or the registration shape in [README Quick start](README.md#quick-start).
3. For Windows with WSL, OpenAI Codex CLI and other MCP clients, use [README Client registration examples](README.md#client-registration-examples). For empty scaffolding scopes that a client created, use [README Remove empty scaffolding scopes](README.md#remove-empty-scaffolding-scopes). Follow those sections as written.

Whatever the client, its server process carries the same absolute `FAVA_TRAILS_DATA_REPO`, a stable `FAVA_TRAILS_AGENT_ID`, and `XDG_CONFIG_HOME` when you isolate per-machine overrides. A desktop client may not inherit your shell exports. Reviewer credentials reach the server through its environment or a `trust_gate_api_key_file`, never as literal values in the client configuration. Done when the client lists the FAVA Trails tools after a restart.

## Setting Up a Second Machine

```bash
# 1. Clone the existing data repo
fava-trails clone https://github.com/YOUR-ORG/fava-trails-data.git fava-trails-data

# 2. Register the MCP server (same config, with local paths)
```

Both machines share the same git remote. The writing side must publish before
peers can fetch: set `push_strategy: immediate`, or under `manual` (bootstrap
default) run `jj bookmark set main -r @-` then `jj git push --bookmark main`.
Use the `sync` MCP tool to **pull** (fetch/rebase) latest shared truth; it is not
a publication step. (Under `push_strategy: immediate`, the server's after-write
push also runs after a successful `sync`.) Completed writes sit at `@-`; a bare
`jj git push` without advancing `main` can miss them.

On the second machine, set `FAVA_TRAILS_AGENT_ID` deliberately on that machine's server process. It is a stable role identifier, not a host fingerprint, so a new host does not need a new value, and the value must not be derived from the hostname. Copying a client registration does not create an independent identity. Processes that share an identity share its authoring view; if they need independent authoring privacy, configure separate identities and endpoints. See [docs/governed-recall.md](docs/governed-recall.md).

## Global Config Reference (`config.yaml`)

```yaml
# Required
trails_dir: trails                        # relative to FAVA_TRAILS_DATA_REPO
remote_url: "https://github.com/..."      # git remote URL (null if local-only)
push_strategy: manual                     # bootstrap default: local commits only
# push_strategy: immediate                # recommended multi-machine: auto-push after writes
                                          # sync MCP tool fetches/rebases; immediate mode also pushes after it succeeds

# Trust Gate (built-in default when unstated: decisions / OpenRouter Jev;
# `fava-trails bootstrap` 0.9.0+ writes llm-oneshot plus the local reviewer you name)
trust_gate: decisions                     # decisions | llm-oneshot
trust_gate_provider: openrouter           # any-llm provider id (openrouter | openai | ...)
trust_gate_model: ~typesafe/jev-latest    # tracking alias; pin typesafe/jev-1.13 if desired
trust_gate_api_base: null                 # optional; set for test doubles or local endpoints
trust_gate_api_key_env: OPENROUTER_API_KEY # env var name holding the API key
# openrouter_api_key_env: OPENROUTER_API_KEY  # deprecated alias for trust_gate_api_key_env
# trust_gate_api_key_file: /path/to/key    # owner-only file; takes precedence over env
# trust_gate_extra_body: {}               # provider-specific request body (llm-oneshot)
trust_gate_timeout_secs: 120              # reviewer wait; raise for slow local models (< tool_timeout_secs)
tool_timeout_secs: 300
trust_gate_decisions_config:
  trust_gate_noul_question: "Should this candidate be promoted as durable, high-quality institutional memory under the supplied Trust Gate policy?"
  trust_gate_noul_threshold: 0.45
# trust_gate: llm-oneshot                 # chat-completions rubric; set a chat model
# trust_gate: human  # NOT IMPLEMENTED — raises NotImplementedError at runtime

# Non-LLM promotion (not a config policy): on an operator endpoint
# (FAVA_TRAILS_OPERATOR=1 + FAVA_TRAILS_AGENT_ID), call
# propose_truth(..., approval="human") per record.

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
    # trust_gate_policy inherits the global policy (default: decisions). Do NOT set
    # trust_gate_policy: human — that policy is unimplemented and raises.
    # For human-only promotion of sensitive records, use an operator
    # endpoint and propose_truth(..., approval="human") per call.
    stale_draft_days: 30                  # tombstone drafts older than 30 days
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trails_dir` | string | `trails` | Directory for trail data (relative to repo root) |
| `remote_url` | string | `null` | Git remote URL for sync |
| `push_strategy` | string | `manual` | `immediate` auto-pushes after successful writes (advances `main` to `@-` then pushes); `manual` (bootstrap default) keeps commits local until the operator runs `jj bookmark set main -r @-` then `jj git push --bookmark main`. The `sync` tool itself only fetches/rebases; under `immediate`, a successful `sync` is also followed by the after-write push. |
| `trust_gate` | string | `decisions` | Global trust gate policy. **Built-in default when unstated: `decisions`** (OpenRouter Jev); `bootstrap` from 0.9.0 writes `llm-oneshot` for new data repositories. `llm-oneshot` with a Decisions-only model (`~typesafe/jev-latest`, `typesafe/jev-1.13`) is refused before transmission. `human` is unimplemented (raises `NotImplementedError`). Non-LLM path is per-call `propose_truth(..., approval="human")` on an operator endpoint, not this config field. |
| `trust_gate_provider` | string | `openrouter` | any-llm provider id (`openrouter`, `openai`, …) |
| `trust_gate_model` | string | `~typesafe/jev-latest` | Exact model id or alias. Chat-completions models (e.g. `google/gemini-2.5-flash`) are for explicit `llm-oneshot`. |
| `trust_gate_api_base` | string | `null` | Optional API root. Decisions default is `https://openrouter.ai/api`; OpenAI-compatible local endpoints use `/v1`. |
| `trust_gate_api_key_env` | string | `OPENROUTER_API_KEY` (via alias) | Env var name holding the API key |
| `openrouter_api_key_env` | string | `OPENROUTER_API_KEY` | Deprecated alias for `trust_gate_api_key_env` |
| `trust_gate_api_key_file` | string | `null` | Owner-only credential file; takes precedence over environment variables and is reread for each promotion |
| `trust_gate_extra_body` | mapping | `{}` | Provider-specific request body passed through to chat-completions (`llm-oneshot`) |
| `trust_gate_timeout_secs` | int | `120` | Trust Gate reviewer timeout; raise for slow local models, keep below `tool_timeout_secs` |
| `trust_gate_decisions_config.trust_gate_noul_question` | string | calibrated durable-memory question | Typed Noul proposition used when `trust_gate` is `decisions`. See [issue #126 calibration report](https://github.com/MachineWisdomAI/fava-trails/issues/126#issuecomment-5894849724). Private corpus available upon request. |
| `trust_gate_decisions_config.trust_gate_noul_threshold` | float | `0.45` | Approve at or above this probability; reject below. Finite, within `[0, 1]`. |
| `tool_timeout_secs` | int | `300` | Outer MCP tool timeout |
| `hooks` | list | `[]` | Lifecycle hook entries (see [Lifecycle Hooks](#lifecycle-hooks)) |

### Per-Trail Config

Override global settings for specific trails via the `trails` map:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `trust_gate_policy` | string | *(inherits global)* | Override trust gate for this trail. Same values as global `trust_gate` (`decisions`, `llm-oneshot`). `human` is unimplemented. Use operator `propose_truth(..., approval="human")` for non-LLM promotion. |
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
    fail_mode: open               # gating hooks: open=skip, closed=halt; after_* observers always skip
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
- `await event.context.recall(query, namespace, limit)` — lexical substring-AND search over thoughts (max 50)

### Lifecycle Points

| Point | When | Pipeline type |
|-------|------|---------------|
| `before_save` | Before thought is written to disk | Gating (can reject/mutate/redirect) |
| `after_save` | After thought is committed | Observer (awaited sequentially through completion or timeout on the caller's task; adds latency before the tool returns; at-most-once, no retry) |
| `before_propose` | Before promotion from drafts | Gating (can reject/mutate/redirect) |
| `after_propose` | After promotion is committed | Observer (awaited sequentially like `after_save`) |
| `after_supersede` | After supersession is committed | Observer (awaited sequentially like `after_save`) |
| `on_recall` | During single-trail recall search | Gating (can filter/reorder via RecallSelect) |
| `on_recall_mix` | After cross-trail `recall_multi` merge | Gating (can filter/reorder via RecallSelect) |
| `on_startup` | Server startup | Startup (separate contract) |

### Error Handling

`fail_mode` is enforced on **gating** hook paths (`before_save`, `before_propose`,
`on_recall`, `on_recall_mix`) via `run_pipeline`:

- **`fail_mode: open`** (default): Gating-hook errors/timeouts are logged and skipped — the operation proceeds
- **`fail_mode: closed`**: Gating-hook errors/timeouts halt the operation with an exception
- Import errors with `fail_mode: closed` cause `sys.exit(1)` at startup

**After-hook observers** (`after_save`, `after_propose`, `after_supersede`) are
different: `dispatch_observer` always logs and skips timeouts/errors and does
**not** consult `fail_mode`. Observer failures never halt the write that already
committed; they still add sequential await latency up to each hook timeout.

### Built-in Protocols

FAVA Trails ships with protocol hook modules that can be enabled via `module:` entries:

| Protocol | Install | Description |
|----------|---------|-------------|
| **SECOM** | `pip install fava-trails[secom]` | Extractive compression at promote time via LLMLingua-2 ([docs](../src/fava_trails/protocols/secom/README.md)) |
| **ACE** | included | Playbook-driven reranking and anti-pattern detection (Stanford, UC Berkeley, and SambaNova ACE) |
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

**If `push_strategy: immediate` is set** (recommended for multi-machine), the server auto-pushes the main bookmark after every successful write. No separate push step needed; push failures surface as non-fatal warnings.

**If `push_strategy: manual` (bootstrap default) or you need to push manually:**
```bash
# From within fava-trails-data:
jj bookmark set main -r @-     # advance main bookmark to latest committed change
jj git push --bookmark main    # push to remote
```

Do **not** treat `sync` as publish: its own work is to fetch/rebase remote shared truth. Under `push_strategy: immediate` the server's after-write push can follow a successful `sync`; under `manual` nothing is pushed.

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

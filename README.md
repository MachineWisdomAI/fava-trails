[![PyPI](https://img.shields.io/pypi/v/fava-trails)](https://pypi.org/project/fava-trails/)
[![License](https://img.shields.io/github/license/MachineWisdomAI/fava-trails)](LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/MachineWisdomAI/fava-trails/test.yml?label=tests)](https://github.com/MachineWisdomAI/fava-trails/actions)
[![Python](https://img.shields.io/pypi/pyversions/fava-trails)](https://pypi.org/project/fava-trails/)
[![Views](https://raw.githubusercontent.com/MachineWisdomAI/fava-trails/traffic/traffic-fava-trails/views.svg)](https://github.com/MachineWisdomAI/fava-trails)

# FAVA Trails

**Federated Agents Versioned Audit Trail**, an open-source agent memory system by [Machine Wisdom AI](https://machine-wisdom.ai/).

FAVA Trails helps agents share reviewed decisions across sessions and environments. Agents save drafts, a configured reviewer decides which drafts become shared records, and agents recall approved records with a history of what changed. Records are Markdown files with YAML frontmatter in a Git-compatible repository you control, exposed through [MCP](https://modelcontextprotocol.io/) tools and versioned with [Jujutsu (JJ)](https://jj-vcs.github.io/jj/).

[Evaluate](#fit-and-limits) · [Install](#install) · [Operate](#operating-fava-trails) · [Contribute](#contributing) · [Release history](CHANGELOG.md) · [Product website](https://fava-trails.org/) · [Machine Wisdom AI's engineering writing](https://machine-wisdom.ai/writing/)

## Why we built FAVA Trails

An observation from one agent can become an assumption for the next. Machine Wisdom AI built FAVA Trails to give that transition an explicit review boundary: saving a thought does not make it accepted knowledge, and an approved correction preserves the record it replaces. The result is a shared history that agents can query and operators can inspect.

FAVA is the governed institutional record for decisions, observations, validation evidence and lineage. It is not an operational working-context store.

## Fit and limits

FAVA Trails is a good fit when several agents or sessions reuse each other's decisions, when work continues across sessions or machines, or when you need to trace why a remembered conclusion changed. It is also a good fit when you want to choose the reviewer, including a model served from your own infrastructure, and keep the records in a repository you can read, diff and back up.

It is a poor fit in these cases:

- **One agent, one session.** A plain notes file avoids the overhead of a review lifecycle.
- **Search by meaning.** `recall` lowercases the query, splits it on whitespace, and requires every token to appear as a substring of the record's searchable text. Paraphrases and synonyms miss. See [docs/retrieval-baseline.md](docs/retrieval-baseline.md) for the matching rules and a shareable synthetic matrix.
- **Fact checking.** The reviewer applies a rubric or a probability threshold to one candidate with limited context. It does not verify project facts, and a convincing false claim can be approved. It does not compare a candidate with existing records, so approved records can still disagree with one another.
- **Isolation between agents on one endpoint.** A shared MCP endpoint or shared data filesystem is one identity boundary, not per-caller isolation.
- **Review text that must stay inside your network, with no reviewer you can run there.** Under a remote reviewer the candidate has already been sent when a rejection returns.

Further limits to plan for:

- **Supersession records lineage.** An approved correction replaces the earlier record in default recall and links back to it. It does not prove the replacement is true.
- **Model approval is advisory.** A model verdict is recorded as `llm_advisory`, which differs from explicit operator approval (`human`) and is not human review.
- **Writes are durable, not atomic across steps.** A successful tool return means the write finished. `save_thought` and `update_thought` write the file before their commit steps, so an interruption can leave a recoverable working copy that an operator should inspect. Approval, rejection and supersession use a before-image journal. See [docs/governed-recall.md](docs/governed-recall.md).
- **Secret preflight is bounded.** A [local preflight](docs/secret-preflight.md) refuses a small set of high-confidence credential shapes before a write or promotion stores or transmits them. It is not complete data-loss prevention and does not erase records that are already stored.

## How it works

Four steps cover one record's life, and publication to other machines is a separate fifth step.

1. **Save a draft.** `save_thought` writes a draft under `drafts/`. Default `recall` and `get_thought` return approved current records only. A process reads its own drafts with explicit `mode="authoring"`.
2. **Ask for review.** `propose_truth` sends the candidate to the configured reviewer, which approves or rejects it. Approval promotes the record, for example to `observations/` or `decisions/`. A rejected draft is frozen, and the author saves a revision with `parent_id` pointing at it.
3. **Recall approved records.** Governed recall returns approved records that have no approved successor.
4. **Correct by supersession.** `supersede` creates a draft successor and leaves the original current. When the successor is approved, the original becomes historical in default recall and both records keep their links.
5. **Publish and sync.** Other machines see approved records after they are published to a shared remote and the reader calls `sync`. See [Sharing across machines](#sharing-across-machines).

Agents call MCP tools and never run version control commands. A minimal sequence looks like this:

```
save_thought(trail_name="myorg/eng/my-project", content="My finding about X", source_type="observation")
  → draft in drafts/, not visible under default governed recall

propose_truth(trail_name="myorg/eng/my-project", thought_id=thought_id)
  → reviewer decides; an approved thought moves to observations/

recall(trail_name="myorg/eng/my-project", query="X")
  → matches because the token "x" appears in the content
```

Three visibility modes apply to `recall` and `get_thought`:

| Mode | Records | Authority |
| --- | --- | --- |
| `governed` (default) | Approved records without an approved successor | Shared readers |
| `authoring` | The process's own draft and proposed records in the scopes you select | Server-configured agent identity |
| `history` | Selected lifecycle statuses, optionally superseded records | Operator-controlled endpoint |

Neither a namespace nor a supplied `agent_id` grants access. [docs/governed-recall.md](docs/governed-recall.md) owns identity setup, approval provenance, replacement rules and interrupted-write recovery.

For a complete lifecycle against a local reviewer, with two rejections, a revision, an approval and a correction, follow the [local review walkthrough](docs/local-review-walkthrough.md). It records one run on 24 October 2026 with one model and is not a benchmark.

## Install

FAVA Trails needs [Jujutsu (JJ)](https://jj-vcs.github.io/jj/) 0.28.0 or later, which runs in colocate mode alongside Git so your data repository remains a standard Git repository.

```bash
pip install --upgrade fava-trails
fava-trails version
fava-trails install-jj
```

`fava-trails install-jj` reuses any JJ at or above the supported minimum, newer versions included, and never silently downgrades or overwrites a user-managed `jj`. When it needs to install JJ it resolves the current official GitHub stable release, and `--version` or `JJ_VERSION` pins one for reproducible environments. See [docs/jj-compatibility.md](docs/jj-compatibility.md).

`fava-trails version` prints the product version, the MCP SDK version and the loaded module path. Run it after every upgrade, because a local `uv run --directory` or vendor selector can keep an older checkout active. Restart the MCP client registration after you change the install. [docs/runtime-and-upgrade.md](docs/runtime-and-upgrade.md) explains how to check which install your client launches.

> **Release boundary.** This README describes the source on the main branch. Source features marked "from 0.9.0", including the local-reviewer bootstrap options and the recorded walkthrough, are not in a published package until a release announces them. The walkthrough was recorded on an installed 0.9.0rc1 candidate. Compare the output of `fava-trails version` with the [release history](CHANGELOG.md) before relying on a described behavior.

To work from source, see [Contributing](#contributing).

## Quick start

Create a local data repository. A local JJ and Git repository with no remote is a valid evaluation setup. Save, recall, review and supersession work without one, and FAVA never creates a hosted repository, pushes private content or changes remotes automatically.

```bash
fava-trails bootstrap "$PWD/fava-trails-data"
export FAVA_TRAILS_DATA_REPO="$PWD/fava-trails-data"
fava-trails doctor
```

`fava-trails doctor` and `fava-trails register` resolve the data repository from `FAVA_TRAILS_DATA_REPO`, which defaults to `~/.fava-trails`. Export the absolute path of the repository you just created before you run either command. Otherwise they can inspect, or print registration for, an unrelated repository that already exists at the default location. `doctor` reports the effective reviewer destination and model for that repository, merged with any per-machine overrides.

To use an existing shared repository, clone it instead with `fava-trails clone https://github.com/YOUR-ORG/fava-trails-data.git "$PWD/fava-trails-data"`, then export the same absolute path.

Print registration instructions for your MCP client with an ordinary server-configured identity:

```bash
fava-trails register --agent-id claude-code
```

This prints only. `--write` updates a client configuration while preserving unrelated settings and keeping a backup, and `--verify` runs a direct smoke test and a configuration load check. A desktop client starts the server in its own process and may not inherit your shell exports. Its registration therefore carries the same absolute `FAVA_TRAILS_DATA_REPO` and, when you deliberately isolate per-machine overrides, the intended `XDG_CONFIG_HOME`. The printed instructions and the registration shape below serve Claude Code, Claude Desktop and clients that take the standard JSON shape. [Client registration examples](#client-registration-examples) covers Windows with WSL, OpenAI Codex CLI and other MCP clients.

A registration has this shape, with the `command` field and paths adapted to your install:

```json
{
  "mcpServers": {
    "fava-trails": {
      "command": "fava-trails-server",
      "env": {
        "FAVA_TRAILS_DATA_REPO": "/path/to/fava-trails-data",
        "FAVA_TRAILS_AGENT_ID": "claude-code"
      }
    }
  }
}
```

Authoring endpoints must set a stable `FAVA_TRAILS_AGENT_ID`, and the server rejects writes without one. Omit it only for deliberate governed-read-only setups. Supply reviewer credentials through the environment of the process that runs the server or through a `trust_gate_api_key_file`, as described in [Choose a reviewer](#choose-a-reviewer), and never as literal values in a client configuration or a repository.

FAVA uses MCP SDK 2.2 or later within the 2.x series. `initialize` advertises FAVA's product version in `serverInfo.version`, which is not the SDK distribution version. Restart a configured server after updating its package, because installing alone does not update a running process.

## Client registration examples

These examples show the registration shape for clients whose setup differs from the standard JSON shown under [Quick start](#quick-start). Each sets an absolute `FAVA_TRAILS_DATA_REPO` and a stable `FAVA_TRAILS_AGENT_ID` for that authoring process, and none holds a credential. A reviewer credential comes from the server process's own environment or from a credential file named in the Trust Gate configuration. Add `XDG_CONFIG_HOME` to the `env` block only when you deliberately isolate per-machine overrides.

**Claude Desktop on Windows, with FAVA Trails installed in WSL (authoring).** The client launches `wsl.exe`, which starts the server in a WSL login shell. Because `bash -lc` loads your WSL login environment, a reviewer credential exported there reaches the server without appearing in this configuration.

```json
{
  "mcpServers": {
    "fava-trails": {
      "command": "wsl.exe",
      "args": [
        "-e", "bash", "-lc",
        "FAVA_TRAILS_DATA_REPO=/path/to/fava-trails-data FAVA_TRAILS_AGENT_ID=claude-code fava-trails-server"
      ]
    }
  }
}
```

**OpenAI Codex CLI (authoring).** Add this to `~/.codex/config.toml`, and restart Codex after editing it.

```toml
[mcp_servers.fava-trails]
command = "fava-trails-server"
# Only if the reviewer credential comes from an environment variable:
env_vars = ["LOCAL_REVIEW_KEY"]

[mcp_servers.fava-trails.env]
FAVA_TRAILS_DATA_REPO = "/path/to/fava-trails-data"
FAVA_TRAILS_AGENT_ID = "codex-cli"
```

For a reviewer that needs a credential, exporting it in the shell that starts Codex is not enough on its own, because Codex gives the server only the variables it is configured to pass. If you use an environment credential, name the variable in `env_vars` as shown, so that Codex forwards it from its parent environment (the Codex [MCP documentation](https://developers.openai.com/codex/mcp) describes `env_vars`), and set `trust_gate_api_key_env` in the FAVA Trails Trust Gate configuration to the same name. Otherwise, point `trust_gate_api_key_file` at an owner-only credential file. Never put a credential value in the TOML or on a command line. Codex's `tool_timeout_sec` is a separate client setting from FAVA Trails' server and review timers, so a slow local reviewer may need a client budget that is compatible with `trust_gate_timeout_secs`.

**Other MCP clients** such as Crush and OpenCode accept the JSON shape shown under [Quick start](#quick-start). Check your client's MCP configuration documentation for where it goes.

## Choose a reviewer

The Trust Gate decides whether a proposed thought becomes an approved record. It is process control with limited context, not independent verification. Choosing a reviewer is a data-egress decision, because the candidate is sent to the configured destination before a verdict exists.

- **`llm-oneshot`** applies a rubric through a chat model. From 0.9.0 source, `fava-trails bootstrap` can write it for a local OpenAI-compatible server you name, using `--review-endpoint`, `--review-model` and `--review-key-env` together. With no review options, or with only some of them, bootstrap writes only the policy. On a fresh configuration that is incomplete, review fails closed until you finish it. Existing per-machine Trust Gate fields can complete or override the policy key by key, and a missing flag does not disable a reviewer that machine already has. When the effective destination differs from what the flags asked for, bootstrap reports it and can exit nonzero after it has created the data repository, so run `fava-trails doctor` and read the destination before the first promotion. The walkthrough records this route with Unsloth serving `unsloth/Qwen3.6-27B-GGUF`.
- **`decisions`** sends one typed question to OpenRouter's Decisions API with TypeSafe's [Jev](https://openrouter.ai/blog/insights/what-is-jev/). A probability at or above `trust_gate_noul_threshold` approves. Jev returns a probability and no rejection rationale, so the record shows the probability and threshold and never an invented explanation. A repository or process with no Trust Gate settings keeps this behavior as the compatibility default, and a hosted Jev review needs an OpenRouter credential.
- **Operator approval** through `propose_truth(..., approval="human")` on a separate operator-controlled endpoint records an explicit operator action and transmits nothing to a reviewer.

There is no pass-through mode and no silent fallback between reviewers. An unreachable endpoint, a missing credential, a timeout or an invalid response fails closed without approving anything. If a reviewer completes with an error verdict, FAVA stores `validation_status: error` and returns `status: error`.

The effective destination comes from the merged configuration, where the per-machine file at `$XDG_CONFIG_HOME/fava-trails/config.yaml` overrides the data repository's Trust Gate fields. `fava-trails doctor` prints the effective destination, model and the candidate fields that are sent, without secrets. Successful review paths return a `trust_gate_egress` description of the same facts. A destination is reported as `local_endpoint` only when its address is `localhost` or a numeric loopback IP as seen from the calling process. That classification cannot see through a tunnel or port forward, so a loopback address can still forward text to another machine, and calling an endpoint local does not prove that the model runs on the same host. An explicit custom `api_base` that is not loopback is reported as `custom_endpoint`. A hosted provider used without an `api_base` is reported as `remote_provider`. Selecting a provider by name does not by itself keep text on your machine, and no provider label is a privacy guarantee. Configuration merges key by key, so one key set in the per-machine file can override the repository's value while the other keys keep coming from the repository.

[AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md) owns the configuration reference, provider settings and credentials, and the [Review gate Blueprint](blueprints/modules/review_gate.blueprint.md) records the contract and its reasons.

## Sharing across machines

Cross-machine sharing is optional. It requires a configured, reachable Git remote that every machine can fetch and, when pushing, write to. Plan for that remote as an operational dependency: who can read private thoughts, how credentials rotate, how you revoke a machine, and how you recover from permission or connectivity failures. A missing remote makes `sync` report `not_configured`, which means local-only. A configured remote that is unreachable or denies permission is an error.

Publishing and syncing are separate steps.

| Setting or tool | Behavior |
| --- | --- |
| `push_strategy: manual` (the `bootstrap` default) | Nothing is pushed automatically. The operator runs `jj bookmark set main -r @-` and then `jj git push --bookmark main` in the data repository. |
| `push_strategy: immediate` | After a successful write operation the server advances `main` and runs `jj git push`. Push failures are non-fatal warnings. |
| `sync` tool | Fetches and rebases from the remote. It does not commit dirty local files and is not a deliberate publication step. Under `immediate`, a successful `sync` counts as a write operation, so the after-write push can run once it finishes. |

For multi-machine authoring, set `push_strategy: immediate` or publish manually after writes, and have peers call `sync` to pull. Do not use `git push origin main` after JJ colocates, because it misses thought commits. The push procedure is in [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md#pushing-to-remote).

To set up a second machine, install FAVA Trails and JJ as above, clone the same data repository with `fava-trails clone`, and register the MCP server with local paths and that machine's own `FAVA_TRAILS_AGENT_ID`.

## Operating FAVA Trails

- **Setup, providers, credentials, hooks and per-trail overrides:** [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md)
- **Visibility modes, agent identity, replacement approval and interrupted-write recovery:** [docs/governed-recall.md](docs/governed-recall.md)
- **Runtime identity and upgrades:** [docs/runtime-and-upgrade.md](docs/runtime-and-upgrade.md)
- **A recorded run against a local reviewer:** [docs/local-review-walkthrough.md](docs/local-review-walkthrough.md)
- **A private ChatGPT connection, readiness checks and `--sync-on-start` (required startup sync stays fail-closed, and a local-only repository should not enable it):** [docs/secure-mcp-tunnel.md](docs/secure-mcp-tunnel.md)
- **Credential preflight, with its data flow, detection limits and false positives:** [docs/secret-preflight.md](docs/secret-preflight.md)
- **Retrieval matching rules:** [docs/retrieval-baseline.md](docs/retrieval-baseline.md)
- **JJ version support:** [docs/jj-compatibility.md](docs/jj-compatibility.md)
- **Reduced context overhead for MCP sessions, including the compact surface:** [docs/mcp-context-overhead.md](docs/mcp-context-overhead.md)
- **Client registration for Windows with WSL and OpenAI Codex CLI:** [Client registration examples](#client-registration-examples)
- **Empty scaffolding scopes created by a client:** [Remove empty scaffolding scopes](#remove-empty-scaffolding-scopes)
- **Duplicate maintenance.** `fava-trails duplicates` produces a read-only exact-body report and a digest-bound, reviewed migration plan. Applying or rolling back needs an explicit operator command and keeps a JJ recovery point and before images: [docs/duplicate-migration.md](docs/duplicate-migration.md)
- **Local scope reader.** Generate a private, read-only dashboard from a scope and its descendants and follow provenance, lineage and typed relationships. Source Markdown remains canonical: [docs/rich-views.md](docs/rich-views.md)

### Remove empty scaffolding scopes

If a client such as ChatGPT guessed scopes before the read-only guard was installed, `fava-trails cleanup-empty-scopes` removes only scopes it verifies hold scaffolding and no records. Run the dry run first, read what it reports, and add `--apply` only for scopes you accept. Run both with `FAVA_TRAILS_DATA_REPO` set to the absolute path of the data repository you mean to change.

```bash
fava-trails cleanup-empty-scopes --scope mw/headspace --scope mw
fava-trails cleanup-empty-scopes --scope mw/headspace --scope mw --apply
```

The scope names are examples. Substitute the scopes you found.

## Architecture

FAVA Trails separates an engine from the data it serves.

```
fava-trails (this repo)        fava-trails-data (your repo)
├── src/fava_trails/           ├── config.yaml
│   ├── server.py  ←── MCP ──→ ├── .gitignore
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

- **Engine** (`fava-trails`) is the MCP server process, licensed Apache-2.0. It retains managers, backend handles, locks and loaded hooks between calls, and it does not store the durable corpus in the package.
- **Fuel** (`fava-trails-data`) is your organization's private trail data, the durable memory graph, in a repository you control.

Each saved thought is committed to a local Jujutsu repository, and every thought carries who wrote it, when, and why it changed. The design documents are the [Blueprints](blueprints/README.md), including the [review-and-recall lifecycle](blueprints/features/review_and_recall_lifecycle.blueprint.md).

## Configuration

Environment variables:

| Variable | Read by | Purpose | Default |
| --- | --- | --- | --- |
| `FAVA_TRAILS_DATA_REPO` | Server | Root directory for trail data | `~/.fava-trails` |
| `FAVA_TRAILS_DIR` | Server | Override the trails directory (absolute path) | `$FAVA_TRAILS_DATA_REPO/trails` |
| `FAVA_TRAILS_AGENT_ID` | Server | Stable identity of an authoring process. Writes are rejected without it. | none |
| `FAVA_TRAILS_OPERATOR` | Server | Set to `1` only on a separate operator-controlled endpoint | none |
| `FAVA_TRAILS_SCOPE_HINT` | Server | Broad scope hint baked into tool descriptions | none |
| `FAVA_TRAILS_MCP_SURFACE` | Server | `full` or `compact` advertised instructions and tool text | `full` |
| `FAVA_TRAILS_SCOPE` | Agent | Optional process override for project scope. `fava-trails init` writes application `.env` files only with `--write-env`. | none |
| `OPENROUTER_API_KEY` | Server | Default credential variable for hosted Decisions review (override the variable name with `trust_gate_api_key_env`) | none |

The server reads `$FAVA_TRAILS_DATA_REPO/config.yaml` for global settings. A minimal file:

```yaml
trails_dir: trails          # relative to FAVA_TRAILS_DATA_REPO
remote_url: null            # git remote URL (optional)
push_strategy: manual       # manual | immediate
```

The per-machine file `$XDG_CONFIG_HOME/fava-trails/config.yaml` (normally `~/.config/fava-trails/config.yaml`) overrides only Trust Gate runtime fields. Repository settings such as `trails_dir`, `remote_url`, `push_strategy`, hooks and trail definitions stay with the data repository. Effective precedence is machine config, then data-repo config, then defaults. A credential file set with `trust_gate_api_key_file` takes precedence over the environment and must be a regular, non-symlink, owner-only file. A slow local model may need a higher `trust_gate_timeout_secs`, kept below `tool_timeout_secs`.

FAVA Trails reaches models through [any-llm-sdk](https://github.com/mozilla-ai/any-llm). Provider fields, the Decisions question and threshold, and per-trail overrides are documented in [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md). The built-in default values are defined in `src/fava_trails/models.py`.

## Protocols

FAVA Trails supports optional lifecycle protocols: hook modules that run custom logic when a thought is saved, promoted or recalled. You register them in the data repository's `config.yaml`, and the server loads them at startup. [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md#lifecycle-hooks) describes the hook system.

- **SECOM** compresses a thought once at promote time with extractive token-level compression from [LLMLingua-2](https://github.com/microsoft/LLMLingua), based on the [SECOM paper](https://arxiv.org/abs/2502.05589) (Tsinghua University and Microsoft, ICLR 2025). Only original tokens survive. Token-level compression can destroy JSON, YAML and fenced code, so tag such thoughts `secom-skip`. Install with `pip install fava-trails[secom]`, then `fava-trails secom setup --write`. Configuration and model options are in [the SECOM README](src/fava_trails/protocols/secom/README.md).
- **ACE** (Agentic Context Engineering) reranks recalled thoughts and detects anti-patterns using playbook rules stored in the `preferences/` namespace, based on [arXiv:2510.04618](https://arxiv.org/abs/2510.04618) (Stanford, UC Berkeley and SambaNova, ICLR 2026). It is included in the base install. Set it up with `fava-trails ace setup --write`.
- **RLM** supports [MapReduce workflows](https://arxiv.org/abs/2512.24601) from MIT by validating mapper outputs, tracking batch progress and sorting results deterministically for reducer consumption. It is included in the base install. Set it up with `fava-trails rlm setup --write`.

Running a setup command without `--write` prints the default configuration so you can review it first.

## Documentation

- [AGENTS.md](AGENTS.md): MCP tool reference, scope discovery, thought lifecycle and agent conventions
- [AGENTS_USAGE_INSTRUCTIONS.md](AGENTS_USAGE_INSTRUCTIONS.md): session protocol, scope discovery and agent identity
- [AGENTS_SETUP_INSTRUCTIONS.md](AGENTS_SETUP_INSTRUCTIONS.md): data repository setup, configuration reference and lifecycle hooks
- [docs/governed-recall.md](docs/governed-recall.md), [docs/local-review-walkthrough.md](docs/local-review-walkthrough.md), [docs/runtime-and-upgrade.md](docs/runtime-and-upgrade.md): operating guides
- [docs/documentation-ownership.md](docs/documentation-ownership.md): which document owns each fact, and the approved wording for claims
- [blueprints/README.md](blueprints/README.md) and [docs/blueprint-maintenance.md](docs/blueprint-maintenance.md): design documents and how to maintain them
- [docs/attribution.md](docs/attribution.md): project authorship, engineering articles and attribution guidance
- Background reading: the [February 2026 two-agent case study](https://fava-trails.org/case-study/) and the [July 2026 local trust gate experiment](https://fava-trails.org/local-trust-gate/), both dated accounts written for earlier versions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, how to run tests and what a pull request needs. To work from source:

```bash
git clone https://github.com/MachineWisdomAI/fava-trails.git
cd fava-trails
uv sync
uv run pytest -v
```

When behavior changes, update the owning document and its listed summaries in the same change, following [docs/documentation-ownership.md](docs/documentation-ownership.md).

## Release history

Release notes are in [CHANGELOG.md](CHANGELOG.md) and [docs/releases/](docs/releases/).

## Built by Machine Wisdom AI

FAVA Trails is part of [Machine Wisdom AI's open-source work on production agent systems](https://machine-wisdom.ai/). The [agent memory architecture analysis](https://machine-wisdom.ai/writing/agent-memory-landscape/) and the [context engineering protocol guide](https://machine-wisdom.ai/writing/agent-memory-protocols/) explain the reasoning behind the implementation. For hands-on help applying these ideas to a production system, see [Machine Wisdom AI's engagement options](https://machine-wisdom.ai/engage/).

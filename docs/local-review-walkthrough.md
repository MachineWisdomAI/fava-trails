# Local review walkthrough: from a weak draft to a governed correction

This guide takes you through one complete FAVA Trails lifecycle against a reviewer model you run yourself. You choose a local OpenAI-compatible endpoint, set up a throwaway data repository, start a process with its own agent identity, and then watch a thought move through draft, rejection, revision, approval, recall and correction.

It is built from one recorded run, and that run is not a promise. The reviewer rejected two drafts before it approved a third. Read the rejections as the useful part: they show what the feedback looks like and how it changed the next draft.

**Candidate-evidence note.** The run used an installed candidate build, version 0.9.0rc1, built from source commit `effba472d342f74be9439f72329f96797a4acfec`. That candidate is not a published release, and nothing here claims a public package, tag or website deployment. The run used a disposable data repository and a disposable configuration. It did not touch any existing client configuration, stored record, identity or credential. Install the FAVA Trails build you intend to use, then confirm what actually loaded with `fava-trails version`; see [runtime-and-upgrade.md](runtime-and-upgrade.md) for checking which install your client launches.

## What you need

- A FAVA Trails build that includes the `llm-oneshot` reviewer option, installed in an environment you control.
- An OpenAI-compatible chat endpoint you operate. The recorded run used a model served from the same machine as the FAVA Trails process, at a loopback address.
- The API key for that endpoint, held in an environment variable. You give FAVA Trails the variable's name, never the key itself. Do not paste a key into a command line, a committed file or a chat.
- An MCP client that can start a stdio server with environment variables. The recorded run used a plain stdio MCP client.

## 1. Decide where review content goes

Review is a data-egress decision. Before a verdict exists, FAVA Trails sends the candidate thought to the configured reviewer. According to the egress report that `propose_truth` returns, that is the full thought body plus `thought_id`, `source_type`, `confidence` and `validation_status`, and optionally `trail_name`, `parent_id`, `project`, `branch` and `tags`. It does not send `agent_id` or `metadata.extra`. A rejection does not recall the text; it has already been sent.

Choose three things on purpose:

1. **Endpoint.** The recorded run reported `destination_kind: local_endpoint` for `http://127.0.0.1:8888/v1`. That address is what the run observed, not a recommended value. A provider name alone does not tell you where text goes. The label `local_endpoint` means only that the effective address is `localhost` or a numeric loopback IP, as seen from the process that makes the call; a hostname, another machine, or a tunnel or port forward on a loopback port is not something FAVA Trails can see through, and any address that is not loopback is reported as `custom_endpoint`. Read the destination in the egress report, or run `fava-trails doctor`, which shows the effective destination and model without printing secrets.
2. **Model.** The run used `unsloth/Qwen3.6-27B-GGUF` through provider `openai`. Any model you pick is your own experiment; see "What this run does and does not show".
3. **Credential source.** Name the environment variable that holds the key. The run also used a key-file reference, shown in section 2.

There is no pass-through or "off" mode and no silent fallback to another provider. A new bootstrap that does not name a reviewer writes only `trust_gate: llm-oneshot` and fails closed: review is refused until you finish the reviewer configuration. It does not choose a hosted reviewer for you.

The hosted Decisions reviewer, Jev, is a separate choice that you configure explicitly (settings below). It sends thought content to a hosted endpoint, so it is not a local fallback for a broken local setup. It also returns a calibrated approval probability and no rejection rationale, so a Jev rejection tells you nothing about what to fix. The feedback loop in this guide needs a reviewer that returns reasoning. Older configurations that leave the Trust Gate unstated keep a legacy compatibility default of Jev; that is not what a new bootstrap produces.

## 2. Bootstrap a disposable repository

Use a directory you can throw away. No git remote is needed. Isolate your configuration first so the run does not inherit a hosted setup you already have.

FAVA Trails reads a per-machine configuration file at `$XDG_CONFIG_HOME/fava-trails/config.yaml` (normally `~/.config/fava-trails/config.yaml`). Supported Trust Gate keys in that file override the same keys in the data repository's `config.yaml`. The recorded run pointed `XDG_CONFIG_HOME` at a separate empty directory, so the only reviewer settings in effect were the disposable repository's. Do the same, and check the effective destination with `fava-trails doctor` before you rely on any review.

```bash
export XDG_CONFIG_HOME="$(mktemp -d)"
# Populate LOCAL_REVIEW_KEY securely, using the secret mechanism you already
# use, before you run review. Do not type the key into this shell history.

fava-trails bootstrap local-review-data \
  --review-endpoint http://127.0.0.1:8888/v1 \
  --review-model '<your-chat-model-id>' \
  --review-key-env LOCAL_REVIEW_KEY

# Use the absolute path of the directory bootstrap just created.
export FAVA_TRAILS_DATA_REPO="$(pwd)/local-review-data"
fava-trails doctor
```

Bootstrap names the variable, not its value, so it does not need the key. `fava-trails doctor` and every later review do need `LOCAL_REVIEW_KEY` to be set in the environment of the process that runs them. If you keep the key in an existing owner-only key file instead, use the `trust_gate_api_key_file` setting described below.

The three `--review-*` options together select `llm-oneshot` with provider `openai`. Bootstrap does not accept `--reviewer`, `--endpoint`, `--model` or `--api-key-env`. Bootstrap does not edit any application `.env` file or live client setting, and you should not either for this exercise.

The generated `config.yaml` in the data repository holds these settings. Add the timeout and `push_strategy` lines if bootstrap did not write them for you:

```yaml
trust_gate: llm-oneshot
trust_gate_provider: openai
trust_gate_api_base: http://127.0.0.1:8888/v1
trust_gate_model: <your-chat-model-id>
trust_gate_api_key_env: LOCAL_REVIEW_KEY
trust_gate_timeout_secs: 180
push_strategy: manual
```

The timeout is a single timer around the whole review call, retries included, and the same value is passed to each request. At 180 seconds, a slow reviewer that retries still ends the call at 180 seconds in total, not per attempt. Keep it below `tool_timeout_secs`, the outer limit on any one tool call. The recorded run also set `trust_gate_api_key_file` to an existing owner-only key file instead of relying on the environment variable. Use `trust_gate_api_key_file: <path-to-owner-only-key-file>` if you prefer a file; keep it outside the repository and never commit the key.

For comparison, an explicit Jev configuration looks like this. Choose it only if you accept hosted transmission:

```yaml
trust_gate: decisions
trust_gate_provider: openrouter
trust_gate_model: ~typesafe/jev-latest
trust_gate_api_key_env: OPENROUTER_API_KEY
```

See [AGENTS_SETUP_INSTRUCTIONS.md](../AGENTS_SETUP_INSTRUCTIONS.md) for the full reviewer configuration reference.

**Commit the repository configuration before writing any thought.** Writes for a trail may touch only that trail's paths, and a modified `config.yaml` sits outside them. The recorded run's first `save_thought` failed for exactly this reason:

```text
Cross-trail pollution detected: 'config.yaml' is outside allowed prefixes ['trails/example/local-review']. Aborting commit to prevent data corruption.
```

The run committed the edited configuration and the next save succeeded. In the disposable repository that was:

```bash
cd local-review-data
jj describe -m "Configure disposable local review"
jj new
```

Leave the shipped default rubric alone for a first run, so the feedback below reflects the default.

## 3. Start a process with its own identity

An authoring process needs a stable agent identity, set by the operator at launch. The agent may omit `agent_id`; if it sends one, it must match. Passing a different `agent_id`, or a namespace, never lets one process act as another author. Without an identity, the server refuses writes.

```bash
FAVA_TRAILS_DATA_REPO="$FAVA_TRAILS_DATA_REPO" \
XDG_CONFIG_HOME="$XDG_CONFIG_HOME" \
FAVA_TRAILS_AGENT_ID=walkthrough-author \
LOCAL_REVIEW_KEY="$LOCAL_REVIEW_KEY" \
fava-trails-server
```

The run used `walkthrough-author`. `fava-trails register --agent-id walkthrough-author` prints the registration instructions for your install; it only prints unless you add `--write`. Run it in the same shell, after the exports above.

A desktop MCP client may not inherit your shell's exports. In the client's server registration, pass both the same absolute data repository path (`FAVA_TRAILS_DATA_REPO`) and the same isolated configuration directory (`XDG_CONFIG_HOME`), plus `FAVA_TRAILS_AGENT_ID`. Without the configuration directory, the client's server reads your normal per-machine configuration and may send review content somewhere other than the endpoint you checked. Give the server the review key through the client's own secret handling, as you would for any other credential. Do not set `FAVA_TRAILS_OPERATOR=1` here; the whole journey needs no operator privilege.

Do not share this authoring endpoint between independent agents. One endpoint is one identity boundary. For a second agent, start a second process with a second identity.

## 4. Save a weak draft and see who can read it

Save something deliberately poor:

```python
save_thought(
    trail_name="example/local-review",
    content="This approach is bad. Always avoid it.",
    source_type="observation",
    confidence=0.99,
)
```

The result is a `draft` with your agent's identity. Now check two views. Governed recall is the default:

```python
recall(trail_name="example/local-review")
```

In the run it returned `count: 0`: a draft is not shared truth. To read your own draft, ask for the authoring view. The run did this by looking the draft up directly:

```python
get_thought(trail_name="example/local-review", thought_id="<id from save>", mode="authoring")
```

That returned the draft. `recall` accepts the same visibility selection, so authoring recall is a supported alternative, though the run did not use it:

```python
recall(trail_name="example/local-review", mode="authoring", statuses=["draft", "proposed"])
```

Authoring mode is for the process's own configured identity only; it never shows another agent's drafts.

Recall matches words, not meaning: every whitespace-separated token of `query` must appear as a substring of the record's text. A paraphrase misses.

## 5. Ask for review and read the rejection

```python
propose_truth(trail_name="example/local-review", thought_id="<id from save>")
```

The reviewer rejected it. This is the response, trimmed:

```json
{
  "status": "rejected",
  "trust_gate": {
    "verdict": "reject",
    "reasoning": "The thought is a vague assertion without grounding, lacking any evidence, methodology, or specifics about what 'this approach' refers to or why it is bad. It also contains imperative language ('Always avoid it') disguised as an observation.",
    "reviewer": "llm-oneshot:unsloth/Qwen3.6-27B-GGUF"
  },
  "trust_gate_egress": {
    "destination": "http://127.0.0.1:8888/v1",
    "destination_kind": "local_endpoint",
    "cloud_fallback": false,
    "rejection_happens_after_transmission": true
  }
}
```

The reviewer's own words tell you what to change: say what "this approach" is, ground the claim, and stop giving orders inside an observation. The stored verdict is marked `kind: llm_advisory`. That means a model gave an opinion about whether the text is a useful, well-formed record. Nobody checked the claim, and it is not a human approval.

## 6. A rejected draft is frozen: revise with `parent_id`

Trying to edit the rejected record fails:

```text
Tool 'update_thought' failed: Target thought is unavailable to this caller
```

Do not look for a way around it. Save a new draft and point it at the rejected one with `parent_id`:

```python
save_thought(
    trail_name="example/local-review",
    content="<a more specific, grounded version>",
    source_type="decision",
    confidence=0.9,
    parent_id="<id of the rejected draft>",
)
```

`parent_id` records that this draft replaces a rejected attempt. It is different from `supersede`, which you use later to replace an approved conclusion.

## 7. The first revision was rejected too

The first revision turned the record into a decision about using a temporary local repository to validate promotion. The reviewer rejected it again:

```text
The thought describes a transient, disposable workflow ('Disposable walkthrough') that explicitly lacks collaboration or remote publication evidence. This context-specific setup is not useful for future agents who will likely need persistent, collaborative solutions.
```

The first rejection said "be specific". This one said something different: specific is not enough if the record only narrates a throwaway setup. A future reader needs a decision they can act on. Nothing in the run shows that a second try is generally enough; here it took a second revision, and a different reviewer or rubric could need more or fewer.

## 8. The revision that was approved

The second revision stated a decision, the reason and the cost. Its `parent_id` pointed at the first rejected revision:

```python
save_thought(
    trail_name="example/local-review",
    source_type="decision",
    confidence=0.9,
    parent_id="<id of the first rejected revision>",
    content=(
        "Decision for the FAVA Trails documentation: use manual push in lifecycle "
        "examples because records remain local until an explicit publication step. "
        "This reduces accidental disclosure of example records, accepting that "
        "collaborators do not receive new records automatically. A local-only "
        "repository also has no configured remote; the example teaches local "
        "promotion rather than remote collaboration."
    ),
)
propose_truth(trail_name="example/local-review", thought_id="<new id>")
```

The reviewer approved, with this reasoning:

```text
This is a concrete decision with clear rationale and tradeoffs (manual push to prevent accidental disclosure vs. lack of automatic collaboration). It provides actionable guidance for future agents working on FAVA Trails documentation, specifically regarding lifecycle examples.
```

Across the three drafts the reviewer first asked for grounding, then for lasting value, and approved once the record held a decision, a reason and a stated tradeoff. That is one observation from one model, not a rule about what any reviewer will accept.

Governed recall now returns the approved record, with `metadata.extra.approval.kind` set to `llm_advisory`.

## 9. Correct an approved decision with `supersede`

Later you decide the approved decision needs correction. Do not edit it. Use `supersede`, which creates a new draft and leaves the old record current:

```python
supersede(
    trail_name="example/local-review",
    thought_id="<id of the approved record>",
    content=(
        "Correction to the documentation decision: use manual push for the "
        "introductory lifecycle example, but distinguish policy from topology. "
        "Manual push allows explicit remote publication when a reachable remote "
        "exists; the absence of a remote makes the repository local-only. A "
        "separate collaboration example can use immediate push, which publishes "
        "after successful writes. This separation reduces accidental disclosure "
        "while teaching both supported workflows; the tradeoff is a second "
        "example for remote collaboration."
    ),
    reason="Distinguish manual push policy from absence of a remote",
    confidence=0.95,
)
```

Before the successor is approved, governed recall still returns the old record. A proposal never retires approved truth. Call `propose_truth` on the new draft; the reviewer approved it in the run. Afterwards:

- governed recall returns only the successor;
- `get_thought` on the old record in the default view reports that the thought was not found in the selected visibility mode;
- `get_thought` on the successor shows the lineage back to the old record.

Approval installs the old record's backlink at the same moment it approves the successor. A successor does not inherit its predecessor's approval; it carries its own `llm_advisory` evidence.

## 10. What gets published, and what does not

Review and publication are separate. `sync` fetches and rebases. That is its core behavior, and it is not how you deliberately publish a record.

There is one side effect to know about. The server can run a push after a successful write operation, and `sync` counts as one. With `push_strategy: immediate`, a reachable remote and an available backend, a successful `sync` or a successful write can therefore attempt a push. With `push_strategy: manual`, as in this guide, nothing is pushed until you push. To publish a manual-mode repository, run in the data repository:

```bash
jj bookmark set main -r @-
jj git push --bookmark main
```

The disposable repository in the run had no remote and used manual push, so **remote publication was not exercised**. `sync` reports `not_configured` until you add a reachable remote. That is not an error.

## When something goes wrong

**The reviewer is down, unreachable or misconfigured.** Review fails closed and nothing is approved. Run `fava-trails doctor` to see the effective destination, model and fields sent, then fix the endpoint, model name, key variable or the per-machine configuration that overrides it. If the failure happened before promotion, such as a configuration error or a timeout, the draft is unchanged and you can propose it again.

**The reviewer answered with an error verdict.** Fail-closed does not mean every failure leaves a draft. If the reviewer completes with an error verdict, FAVA Trails stores `validation_status: error` on the record and returns `status: error`. Normal authoring shows only your own draft and proposed records, so an errored record may be hidden from your usual view, and an operator may need to inspect it through separate history tools. Do not plan to retry the same record. Fix the reviewer, then save a fresh draft with `parent_id` pointing at the errored record and propose that. This changes no identity or permission.

**Review times out.** `trust_gate_timeout_secs` is the total time for the whole review call, retries included, and it is also applied to each request. A slow reviewer that retries therefore never runs past that single limit. Raise it only if your model is simply slow, keep it below `tool_timeout_secs`, and check the model server first.

**A rejection comes with no explanation.** The configured reviewer may not return reasoning; Jev does not. Either switch to a reviewer that does, or improve the draft against the rubric yourself. Do not read an unexplained rejection as a quality score. Not every local chat model gives useful feedback either; a reviewer that returns vague or contradictory reasoning teaches you little.

**A rejected draft cannot be edited.** This is intended. Save a new draft with `parent_id`.

**A successor approval was interrupted.** Approval and `supersede` run under a governance transaction. If a process dies midway, reads keep showing the old complete state, and the next governance writer performs recovery. Do not delete the pending journal in `.jj/fava-governance-transaction.json`, copy the repository mid-transaction, or reset the repository. If recovery reports unrelated dirty files, preserve them and resolve that file specifically, then call `propose_truth` on the successor again.

**A plain save is interrupted.** `save_thought` and `update_thought` do not use that journal. An interruption can leave an uncommitted file, and later writes can refuse with an unexpected-dirty-path error. An operator should inspect that file; do not reset.

## What this run does and does not show

It shows one real end-to-end journey with one model, `unsloth/Qwen3.6-27B-GGUF`, through one local OpenAI-compatible service, on 24 October 2026. The reviewer's verdicts are advisory model output. They are not human approval and not verification of any fact in the text.

It does not show that every local chat model gives useful feedback, that a revised draft will be approved, or how often. It is not a benchmark. The candidate's separate automated tests check deterministic behavior; they did not produce any of the model judgments shown here.

For the full visibility and approval rules, continue with [governed recall and replacement approval](governed-recall.md).

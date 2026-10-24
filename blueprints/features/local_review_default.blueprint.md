---
feature_name: local_review_default
status: draft
module_blueprints: [review_gate]
dependencies: [review_and_recall_lifecycle]
date_added: 2026-10-24
---

# Local review default

## Status

- Design: draft.
- Implementation: Not started. Current behavior below was observed at `fava-trails@0f7c01f`.
- Evidence: the configuration results come from loading `GlobalConfig` at that revision. No test exists for the proposed behavior.
- Release: nothing published. Public documentation must not say new installations select a local reviewer until a release containing this change exists.

## Problem and current behavior

Built-in defaults are policy `decisions`, provider `openrouter`, model `~typesafe/jev-latest`. `fava-trails bootstrap` writes only `trails_dir`, `remote_url` and `push_strategy`, so a fresh installation reviews through hosted OpenRouter and sends every candidate off the machine. Jev returns a probability and no reasoning, so a rejected agent cannot see why.

Each Trust Gate key falls back to its default independently. Observed results (policy / provider / model):

| Stated in config | Effective | Assessment |
| --- | --- | --- |
| nothing | `decisions` / `openrouter` / `~typesafe/jev-latest` | Intended hosted default. |
| all three | as stated | Correct. |
| `trust_gate: decisions`, `trust_gate_model: typesafe/jev-1.13` | `decisions` / `openrouter` / the pin | Documented Jev pin; correct. |
| `trust_gate: llm-oneshot`, a hosted chat model | `llm-oneshot` / `openrouter` / that model | Documented hosted rubric form; correct. |
| provider `openai`, `laya-typed-decisions`, `api_base`; no policy | `decisions` / `openai` / that model | Local Decisions form as the setup guide's prose and the missing-credential hint describe it (the README's YAML also states the policy); correct. |
| provider `openai`, a local chat model, `api_base`; no policy | `decisions` / `openai` / that model | A pre-0.8 style config now posts a chat model to `/v1/systemone`. |
| a hosted chat model; no policy | `decisions` / `openrouter` / that model | Same pre-0.8 mismatch; the candidate goes to OpenRouter's Decisions endpoint. |
| `trust_gate: llm-oneshot`; no model | `llm-oneshot` / `openrouter` / `~typesafe/jev-latest` | A Decisions-only model id used for chat completion. |

Runtime validation accepts every row. The last three are the defects.

## Proposed behavior

Before: a new installation reviews through hosted Jev. After: it reviews through a local OpenAI-compatible server the operator names, and no existing configuration changes meaning.

**New installation.** `fava-trails bootstrap` accepts `--review-endpoint`, `--review-model` and `--review-key-env NAME` (the name of the environment variable holding the credential; a server that ignores authentication still needs a placeholder value). The endpoint must be a bare `http(s)://host[:port][/v1]`; userinfo, query, fragment and other path segments are refused, because the value is committed and may be pushed. Bootstrap warns when a loopback endpoint is combined with `--remote`, since every clone inherits it.

When all three are given, bootstrap writes to the data repository's `config.yaml`: `trust_gate: llm-oneshot`, `trust_gate_provider: openai`, `trust_gate_api_base`, `trust_gate_model` and `trust_gate_api_key_env`. A complete selection behaves the same on every clone and release. When any is missing, bootstrap writes only `trust_gate: llm-oneshot`, finishes, and prints what to supply; with no per-machine override, promotion then fails closed with the same guidance. It never probes the endpoint, assumes hardware, downloads a model or reads a default credential variable.

Bootstrap never writes the per-machine config. That file is shared by every data repository on the machine and overrides key by key, so writing it would change those repositories' reviewers. After writing, bootstrap loads the effective configuration and reports the selection, the destination kind (local, custom or remote) and each Trust Gate key a per-machine file overrides. It exits non-zero when the effective destination differs from the one requested; the repository is still created. A machine file can supply the missing model, redirect the base URL, switch the policy to `decisions` or add a key file that takes precedence over the named variable, so "no request leaves the machine" holds only when the report shows no such override.

**Existing configurations.** Default constants and per-key fallback stay as they are, so every row above that is marked correct keeps resolving exactly as it does now, as does any other combination that names a coherent backend. Two additions:

1. *Fail closed on a Decisions-only model.* With effective policy `llm-oneshot` and an effective model equal to one of FAVA's own Decisions constants (`~typesafe/jev-latest`, the built-in default, or `typesafe/jev-1.13`), promotion errors before transmission and names `trust_gate_model`. The comparison is against FAVA's constants, not a vendor naming pattern, so it survives a config rewrite that makes defaults explicit. It runs in `handle_propose_truth` after the explicit-human-approval branch (which needs no model), and in doctor and tunnel preflight. It is not part of `GlobalConfig` load. Three existing fixtures use `llm-oneshot` with the default model and a mocked reviewer (`test_gateway_workflow.py`, `test_mcp_context.py`, `test_trust_gate_decisions.py`) and need updating.
2. *Diagnose, don't reinterpret.* When the policy is not stated but a provider or model is, doctor, startup logging and a failed promotion add an informational line: which policy took effect, and `trust_gate: llm-oneshot` as the fix if the model is a chat model. Behavior is unchanged because the configuration alone cannot reliably distinguish a pre-0.8 chat configuration from the local Decisions form, so the line also appears for a correct Decisions configuration. `GlobalConfig.model_fields_set` supplies "stated". A command that rewrites `config.yaml` with all defaults makes the policy stated and silences the line.

Both apply to the effective policy of the trail being promoted. A trail that pins a different policy than the global one is an explicit operator choice and is not second-guessed.

## Responsibilities and interfaces

- `models.py`/`config.py`: the model check and the "stated" diagnostic.
- `trust_gate.py`/`tools/navigation.py`: apply the check before any network call; chat requests pass `trust_gate_timeout_secs`. At the inspected revision `llm-oneshot` leaves each HTTP request at the client's 60 s default, makes up to three attempts, and the HTTP client may repeat each (up to nine requests were observed against a slow fixture), so raising the setting does not help a slow local model.
- `cli.py`: bootstrap options, the effective-configuration report and doctor output.
- The review gate's fail-closed behavior is unchanged ([Review gate](../modules/review_gate.blueprint.md)).

## Failure and recovery

Two kinds of failure already occur, and neither falls back to a hosted provider:

- *Tool error, record unchanged.* Missing setup, a missing credential, a configuration error, or the outer timeout firing first. The same agent can retry after the operator fixes configuration.
- *Recorded `error` verdict.* A server that is down, a 401, or a malformed reply (and a slow reviewer whose retries run out before the outer timeout, or with the outer timeout set to 0). The record becomes `error` and nothing is promoted. The authoring agent can no longer see it; an operator re-proposes it, or the agent saves a new draft ([Rejection and revision](review_and_recall_lifecycle.blueprint.md#rejection-and-revision)). A stopped local server is the most likely cause.

Nothing rewrites an existing configuration or stored record. Rollback is a revert of the change; no explicit configuration changed.

## Verification outcomes (planned)

| Condition | Expected result |
| --- | --- |
| Bootstrap with all three options | Data repo states the complete selection; machine config untouched; no network call |
| Bootstrap with an endpoint containing userinfo, a query or a token path | Refused |
| Bootstrap with the model but no endpoint, no machine override | Only `trust_gate: llm-oneshot` written; promotion errors; no request leaves the machine |
| Same, with a machine file that supplies a hosted model, redirects the base URL, selects `decisions` or names a key file | Report names the override and destination kind; non-zero exit when the destination differs |
| Each "correct" row in the table above | Resolves exactly as at `0f7c01f` |
| `llm-oneshot` with either Decisions constant as the model | Error naming `trust_gate_model`; reviewer not called; `approval="human"` unaffected |
| Policy unstated with a chat model | Resolution unchanged; informational line names the effective policy and the fix |
| Explicit Jev below threshold | Reject; reasoning is probability and threshold only |
| Local reviewer rejects with an explanation | Explanation reaches the caller in `trust_gate.reasoning` |
| Local server down, 401, malformed body | Recorded `error`; no promotion; hosted provider not contacted |
| Reviewer slower than 60 s with `trust_gate_timeout_secs` raised | The configured timeout applies to the whole call |

These are fixture checks. A separate run against a real local reviewer is required before documentation claims useful rejection feedback.

## Limits kept

A keyless local server still needs a placeholder credential. A trail cannot pin `llm-oneshot` while the global policy is `decisions`, because the per-trail value `llm-oneshot` means "inherit". A repository bootstrapped without all options behaves differently on a release lacking the new check: on 0.8.x it posts the Decisions model as a chat request to OpenRouter when `OPENROUTER_API_KEY` is set, and on 0.7 and earlier it is reviewed by hosted `google/gemini-2.5-flash`. Bootstrap prints that warning when it writes the policy alone.

## References

[Tracking issue](https://github.com/MachineWisdomAI/fava-trails.org/issues/33) · [Review gate](../modules/review_gate.blueprint.md) · [Review-and-recall lifecycle](review_and_recall_lifecycle.blueprint.md)

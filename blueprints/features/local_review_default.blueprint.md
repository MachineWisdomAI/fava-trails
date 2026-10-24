---
feature_name: local_review_default
status: draft
module_blueprints: [review_gate]
dependencies: [review_and_recall_lifecycle]
date_added: 2026-10-24
---

# Local review default

## Status

- Design: draft; an independent source review found blocking errors in the first revision, and this revision resolves them.
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
| provider `openai`, `laya-typed-decisions`, `api_base`; no policy | `decisions` / `openai` / that model | Documented local Decisions form (setup guide, README, runtime hint); correct. |
| provider `openai`, a local chat model, `api_base`; no policy | `decisions` / `openai` / that model | A pre-0.8 style config now posts a chat model to `/v1/systemone`. |
| a hosted chat model; no policy | `decisions` / `openrouter` / that model | Same pre-0.8 mismatch; the candidate goes to OpenRouter's Decisions endpoint. |
| `trust_gate: llm-oneshot`; no model | `llm-oneshot` / `openrouter` / `~typesafe/jev-latest` | A Decisions-only model id used for chat completion. |

Runtime validation accepts every row. The last three are the defects.

## Proposed behavior

Before: a new installation reviews through hosted Jev. After: it reviews through a local OpenAI-compatible server the operator names, and no existing configuration changes meaning.

**New installation.** `fava-trails bootstrap` accepts `--review-endpoint`, `--review-model` and `--review-key-env NAME` (the name of the environment variable holding the credential; a server that ignores authentication still needs a placeholder value). When all three are given, it writes to the data repository's `config.yaml`: `trust_gate: llm-oneshot`, `trust_gate_provider: openai`, `trust_gate_api_base`, `trust_gate_model` and `trust_gate_api_key_env`. A complete selection in the data repository behaves the same on every clone and release. When any is missing, bootstrap writes only `trust_gate: llm-oneshot`, finishes, and prints what to supply. Promotion then fails closed with the same guidance. Bootstrap never probes the endpoint, assumes hardware, downloads a model or reads a default credential variable.

Bootstrap does not write the per-machine config. That file is shared by every data repository on the machine and overrides key by key, so writing it would change those repositories' reviewers. Doctor shows the effective selection and any machine override.

**Existing configurations.** Default constants and per-key fallback stay as they are, so every row above that is marked correct keeps resolving exactly as it does now, as does any other combination that names a coherent backend. Two additions:

1. *Fail closed on the Decisions-only model.* With effective policy `llm-oneshot` and effective model `~typesafe/jev-latest` (the built-in Decisions default), promotion errors before transmission and names `trust_gate_model`. The check compares against FAVA's own constant, not a vendor naming pattern, so it survives a config rewrite that makes defaults explicit.
2. *Diagnose, don't reinterpret.* When the policy is not stated but a provider or model is, doctor, startup logging and a failed promotion say which policy took effect and the one-line fix (`trust_gate: llm-oneshot` for a chat model). Behavior is unchanged because the configuration alone cannot reliably distinguish a pre-0.8 chat configuration from the documented local Decisions form. `GlobalConfig.model_fields_set` supplies "stated" for the diagnostic only. A command that rewrites `config.yaml` with all defaults makes the policy stated and silences it.

The check applies to the effective policy of the trail being promoted. A trail that pins a different policy than the global one is an explicit operator choice and is not second-guessed.

## Responsibilities and interfaces

- `models.py`/`config.py`: the model check and the "stated" diagnostic.
- `trust_gate.py`/`tools/navigation.py`: apply the check before any network call; chat requests pass `trust_gate_timeout_secs`. Today `llm-oneshot` leaves each attempt at the client's 60 s default and retries transport failures up to three times, so raising the setting does not help a slow local model.
- `cli.py`: bootstrap options and doctor output.
- The review gate's fail-closed behavior is unchanged ([Review gate](../modules/review_gate.blueprint.md)).

## Failure and recovery

Unreachable, unauthorized, timed-out, malformed or invalid reviewer responses already produce `error` with no promotion and no hosted fallback. Missing setup produces the guidance above. Recovery is editing configuration and proposing again. Nothing rewrites an existing configuration or stored record. Rollback is a revert of the change; no explicit configuration changed.

## Verification outcomes (planned)

| Condition | Expected result |
| --- | --- |
| Bootstrap with all three options | Data repo states the complete selection; machine config untouched; no network call |
| Bootstrap with the model but no endpoint | Only `trust_gate: llm-oneshot` written; promotion errors; no request leaves the machine |
| Each "correct" row in the table above | Resolves exactly as at `0f7c01f` |
| `llm-oneshot` with the Decisions default model | Error naming `trust_gate_model`; reviewer not called |
| Policy unstated with a chat model | Resolution unchanged; doctor names the effective policy and the fix |
| Explicit Jev below threshold | Reject; reasoning is probability and threshold only |
| Local reviewer rejects with an explanation | Explanation reaches the caller in `trust_gate.reasoning` |
| Local server down, 401, malformed body; reviewer slower than 60 s | `error`; draft unchanged; hosted provider not contacted; the configured timeout applies |

These are fixture checks. A separate run against a real local reviewer is required before documentation claims useful rejection feedback.

## Limits kept

A keyless local server still needs a placeholder credential. A trail cannot pin `llm-oneshot` while the global policy is `decisions`, because the per-trail value `llm-oneshot` means "inherit". A repository bootstrapped without all options and cloned onto an older release resolves to OpenRouter with the Decisions model as a chat model.

## References

[Tracking issue](https://github.com/MachineWisdomAI/fava-trails.org/issues/33) · [Review gate](../modules/review_gate.blueprint.md) · [Review-and-recall lifecycle](review_and_recall_lifecycle.blueprint.md)

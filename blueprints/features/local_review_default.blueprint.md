---
feature_name: local_review_default
status: draft
module_blueprints: [review_gate]
dependencies: [review_and_recall_lifecycle]
date_added: 2026-10-24
---

# Local review default

## Status

- Design: draft. Describes a change that does not exist yet. Independent source review and coordinator approval are recorded here when they happen.
- Implementation: Not started. Current behavior below was observed at `fava-trails@0f7c01f`.
- Evidence: the configuration results below come from running `GlobalConfig` on that revision. No fixture or real-model test exists for the proposed behavior.
- Release: nothing published. Public documentation must say that new installations select a local reviewer only after a release containing this change is published.

## Problem and current behavior

The built-in defaults are policy `decisions`, provider `openrouter`, model `~typesafe/jev-latest`. `fava-trails bootstrap` writes only `trails_dir`, `remote_url` and `push_strategy`, so a fresh installation reviews through hosted OpenRouter and sends every candidate off the machine. Jev returns a probability and no reasoning, so a rejected agent cannot see why.

Each Trust Gate key falls back to its default independently. A configuration that states some keys therefore picks up constants meant for a different backend:

| Stated in config | Effective policy / provider / model at `0f7c01f` | Problem |
| --- | --- | --- |
| nothing | `decisions` / `openrouter` / `~typesafe/jev-latest` | Intended hosted default. |
| all three, hosted or local | exactly as stated | None. |
| provider `openai`, a local chat model and `api_base`; no policy | `decisions` / `openai` / that model | Local chat model sent to a Decisions endpoint. The setup guide only documents configurations that state the policy. |
| a hosted chat model; no policy | `decisions` / `openrouter` / that model | Chat model sent to OpenRouter Decisions. |
| policy `llm-oneshot`; no provider or model | `llm-oneshot` / `openrouter` / `~typesafe/jev-latest` | A Decisions model used for chat completion. |

Runtime validation accepts all five.

## Proposed behavior

Before: a new installation reviews through hosted Jev. After: a new installation reviews through a local OpenAI-compatible server the operator names, and an existing explicit choice behaves exactly as before.

**New installation.** `fava-trails bootstrap` accepts the reviewer endpoint and served model identifier, plus a credential source (see Interfaces). It writes `trust_gate: llm-oneshot` to the data repository, and the machine-specific provider (`openai`), endpoint, model and credential source to the per-machine config. It does not probe the endpoint, assume hardware or download a model. If the endpoint or model is omitted, bootstrap still completes and prints exactly what to supply; promotion then fails closed with the same guidance.

**Existing configuration.** Selection depends on which of three keys the merged config states: `trust_gate`, `trust_gate_provider`, `trust_gate_model`. Base URL, credential, timeout and extra body are modifiers and do not count.

| Stated keys | Result |
| --- | --- |
| All three | Used exactly. Explicit Jev, hosted `llm-oneshot` and local selections never change. |
| None | Unchanged: built-in Jev default. Doctor and server startup add a one-line notice that no reviewer was chosen explicitly. |
| Policy omitted, model is a `typesafe/` or `~typesafe/` id, or a Decisions block is present | `decisions`, as today. |
| Policy omitted, any other model | Fail closed before transmission: name the missing `trust_gate` key and the two valid values. |
| Policy stated, provider or model missing | Fail closed and name the missing keys. The Jev defaults complete a `decisions` selection only when the stated keys are consistent with them (provider `openrouter` or absent, no other model). |

The last rows are the only intended behavior change for existing configurations. They replace a request to the wrong endpoint with an error that costs no egress. A config that selects the local Decisions model (`laya-typed-decisions`) without stating `trust_gate: decisions` now needs that one line, because the runtime does not recognize model names it does not own.

## Responsibilities and interfaces

- `models.py`/`config.py` track which selection keys were stated and compute the table above. This is the only new logic.
- `cli.py` bootstrap and `doctor` gain the setup options and the notice. Proposed flags: `--review-endpoint`, `--review-model`, `--review-key-file` or `--review-key-env`.
- The review gate and its fail-closed behavior are unchanged ([Review gate](../modules/review_gate.blueprint.md)).
- Machine config holds the endpoint and model because they describe one machine's server. The data repository holds only the policy, so a second clone with no local reviewer fails closed with guidance instead of inheriting someone else's endpoint.

## Failure and recovery

Unreachable, unauthorized, timed-out, malformed or invalid reviewer responses already return `error` without promotion and without any hosted fallback. Missing setup returns the guidance above. Both are recovered by editing configuration and re-proposing. Nothing rewrites an existing configuration or stored record. Rollback is a revert of the change; clones keep working because explicit configurations never changed.

## Verification outcomes (planned)

| Condition | Expected result |
| --- | --- |
| Bootstrap with endpoint and model | Data repo states the policy; machine config states provider, endpoint, model; no network call |
| Bootstrap without them | Success with instructions; `propose_truth` errors naming the missing settings; no request leaves the machine |
| Each row of the existing-configuration table, including machine over data-repo precedence | The stated result, with no value borrowed from a different backend |
| Explicit Jev, probability below threshold | Reject; reasoning states probability and threshold and contains no model rationale |
| Local reviewer rejects with an explanation | The explanation reaches the caller in `trust_gate.reasoning` |
| Local server down, 401, timeout, malformed body | `error`; draft unchanged; hosted provider not contacted |

These are fixture checks. A separate run against a real local reviewer, with disposable data, is required before documentation claims useful rejection feedback.

## Implementation sequence

1. Selection tracking and fail-closed guidance, with the configuration tests.
2. Bootstrap options, doctor notice and local-reviewer tests.
3. Reconcile README, setup guide and website summaries to the shipped behavior.

## Open decisions

None blocking. Recorded limits: a keyless local server still needs a placeholder credential, and a trail cannot pin `llm-oneshot` while the global policy is `decisions` (the per-trail value `llm-oneshot` means "inherit"). Both are existing behavior and stay out of scope.

## References

- Tracking: [fava-trails.org#33](https://github.com/MachineWisdomAI/fava-trails.org/issues/33)
- [Review gate](../modules/review_gate.blueprint.md) · [Review-and-recall lifecycle](review_and_recall_lifecycle.blueprint.md)

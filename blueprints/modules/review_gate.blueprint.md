---
name: review_gate
type: module
description: Decides whether a draft thought may become approved shared memory, and records who or what decided.
status: draft
---

# Review gate

## Status

- Design: draft. Describes existing behavior; the proposed new-install default is in [Local review default](../features/local_review_default.blueprint.md).
- Implementation: Implemented, inspected at `fava-trails@0f7c01f` in `src/fava_trails/trust_gate.py`, `decisions.py`, `credentials.py`, `models.py` and `config.py`.
- Evidence: fixture tests in `tests/test_trust_gate*.py`, `test_machine_trust_gate_config.py` and `test_config.py` (236 passed together with the lifecycle tests). Fixture servers prove protocol handling and fail-closed behavior. They do not show that any real model reviews well.
- Release: not applicable.

## Purpose and boundaries

`propose_truth` asks the gate for one verdict on one candidate. The gate owns reviewer selection, what is sent, how the answer is parsed and what provenance is recorded. It does not own visibility, identity or persistence: the lifecycle applies the verdict, and the gate never writes a record.

A verdict is process control with limited context. The reviewer sees one candidate, the scope's prompt and a few metadata fields. It does not check the candidate against existing records or against reality, and a convincing false claim can be approved.

## Interfaces and behavior

**Input.** The scope-resolved `trust-gate-prompt.md` (the nearest file up the scope path, cached at startup so a running agent cannot change it), the candidate body, and `thought_id`, `source_type`, `confidence`, `validation_status` plus optional `trail_name`, `parent_id`, `project`, `branch`, `tags`. `agent_id` and `metadata.extra` are never sent.

**Output.** `TrustResult`: `verdict` (`approve`, `reject`, `error`), `reasoning`, reviewer id, provider, model, `approval_kind`, and for Decisions the probability and threshold.

| Policy | How it decides | What the caller learns on rejection |
| --- | --- | --- |
| `llm-oneshot` | One chat-completion request (temperature 0 where the model supports it), JSON `{verdict, reasoning, confidence}`; one retry if the reply does not parse. | The reviewer's own explanation. Quality depends on the model. |
| `decisions` | One typed question; approve when the returned probability is at or above `trust_gate_noul_threshold`. | A sentence stating the probability and threshold. The response carries no reasoning, and none is invented. |
| operator `approval="human"` | No model call. Allowed only on an operator endpoint. | Not applicable. Recorded as `kind: human`. |

The policy value `human` in configuration is not implemented and raises.

**Selection.** Policy, provider, model, base URL, credential source, timeout, extra request body and the Decisions block resolve in this order: per-machine `config.yaml` (Trust Gate keys only), then the data repository's `config.yaml`, then built-in defaults. A trail can override the policy; the value `llm-oneshot` means "inherit". At the inspected revision the built-in defaults, defined in `models.py`, are `decisions`, `openrouter`, `~typesafe/jev-latest` and threshold 0.45. Bootstrap writes none of them, so a configuration that omits a key receives the default for that key independently of the others. The legacy `openrouter_api_key_env` setting is read from the data repository only; the per-machine file accepts `trust_gate_api_key_env` and `trust_gate_api_key_file`.

**Credentials.** Every automatic policy needs a non-empty credential from an owner-only key file or an environment variable, including for a local server. A local server that ignores authentication still needs a placeholder value.

**Disclosure.** Before any network call the gate logs, and returns as `trust_gate_egress`, the destination, model, credential source name and the candidate fields sent. `fava-trails doctor` prints the same notice. A base URL is disclosed without userinfo or query; any path other than empty or `/v1` is replaced with `/[redacted]`.

## Failure and recovery

Every failure below produces `error` or a tool error. None promotes, and none contacts another reviewer.

| Trigger | Visible result |
| --- | --- |
| Missing credential, key file unreadable, symlinked or not owner-only | Error naming the source, not the secret. |
| HTTP error, connection failure, authentication failure | Error with a sanitized description; URL userinfo and query strings never reach stored provenance. |
| Reply not valid JSON, unknown verdict (`llm-oneshot`); missing, non-numeric or out-of-range probability (`decisions`) | Error after the single parse retry (`llm-oneshot`). |
| Threshold outside [0, 1] | Refused at configuration load. |
| Empty Noul question | Refused at load when the global policy is `decisions`; otherwise a configuration error before transmission. |
| Reviewer slower than `trust_gate_timeout_secs` (default 120, below the 300 s tool timeout) | Tool error suggesting retry; no verdict recorded. For `llm-oneshot` each HTTP attempt is also capped at 60 s by the client default and transport failures are retried up to three times, so raising the setting alone does not extend a slow reviewer past 60 s per attempt. The Decisions client honors the setting. |

Recovery is operator action: fix configuration or availability, then call `propose_truth` again. For a recorded `error` verdict the authoring agent cannot re-propose the record (see the lifecycle).

## Verification outcomes

| Condition | Expected result | Evidence |
| --- | --- | --- |
| Probability exactly at the threshold | Approve | `test_decisions_approve_at_threshold_boundary` (fixture) |
| Probability below threshold | Reject; reasoning states probability and threshold | `test_decisions_reject_below_threshold` (fixture) |
| Local server returns malformed JSON, 401 or an unreachable address | Error; no promotion | `test_local_client_*_fail_closed` (fixture) |
| Credential missing | Error naming the variable; draft stays a draft; reviewer not called | `test_missing_cloud_credentials_fail_closed_no_auto_approve` (fixture) |
| Local base URL configured | Only that host is contacted | `test_local_only_intercepts_outbound_and_never_hits_cloud` (fixture) |
| Local reviewer errors and is retried | Retries stay on the configured host | `test_local_retry_error_path_stays_on_configured_endpoint` (fixture) |
| Machine config sets a non-Trust-Gate key | Rejected | `test_machine_config_rejects_non_runtime_keys` (fixture) |

Not yet evidenced: a rejection explanation from a real local model that is useful to a revising agent.

## Limits kept

A keyless local server still needs a placeholder credential. A trail cannot pin `llm-oneshot` while the global policy is `decisions`, because the per-trail value `llm-oneshot` means "inherit". Both are recorded in [Local review default](../features/local_review_default.blueprint.md).

## Related contracts and implementations

[Review-and-recall lifecycle](../features/review_and_recall_lifecycle.blueprint.md) · [Local review default](../features/local_review_default.blueprint.md) · [`src/fava_trails` codebase map](../codebases/src/fava_trails/codebase.blueprint.md)

---
codebase_path: src/fava_trails
associated_module: review_gate
implemented_features: [review_and_recall_lifecycle]
---

# `src/fava_trails` codebase map

## Status

- This document records inspected implementation; it grants no design approval, so it carries no design status.
- Inspected at `fava-trails@0f7c01f`, version 0.8.5rc1; updated for PRREF (version 0.9.0-rc.1), which adds the local-review default.
- Covers the review-and-recall lifecycle and the review gate. Rich views, the secure-tunnel gateway, duplicate maintenance and the ACE/RLM/SECOM protocol hooks are present in the tree but not described here.
- [Local review default](../../../features/local_review_default.blueprint.md) is implemented in PRREF and unpublished.

## Where behavior lives

| Source | Owns | Does not own |
| --- | --- | --- |
| `server.py` | MCP tool definitions, per-call authorization (`_authorize_tool`), the outer tool timeout, the post-write push hook, and the sync summary for non-operators. | Review decisions, record storage. |
| `governance.py` | `Principal` (agent id and operator flag, read from the process environment), the three visibility modes, and the rule that only an approved successor retires a record. | Writing records. |
| `trail.py` | `TrailManager`: save, update, supersede, `propose_truth` (applies a verdict), lexical `recall`, `sync`. | Choosing a reviewer. |
| `transactions.py` | The before-image journal, process lock and recovery used by every multi-file governance write. | What the files mean. |
| `tools/navigation.py` | `handle_propose_truth` (resolves policy, builds the client, applies the timeout, shapes the caller's response) and `handle_sync`. | Verdict parsing. |
| `tools/thought.py`, `tools/recall.py` | Thin handlers for save/update/get/supersede and recall. | Visibility rules (delegated to `governance.py`). |
| `trust_gate.py` | Prompt cache, payload construction, `llm-oneshot` and `decisions` review, `TrustResult`, egress disclosure. | Provider transport. |
| `llm/` | Chat-completion client over `any-llm-sdk`. Forwards the configured model id unchanged for non-default providers or custom base URLs. | Policy. |
| `decisions.py` | Decisions HTTP client and response validation. | Threshold comparison (in `trust_gate.py`). |
| `credentials.py` | Key lookup from an owner-only file or environment variable. | Where the key is stored. |
| `models.py`, `config.py` | Record schema, `GlobalConfig` defaults and validators, the Decisions-only model check and the unstated-policy note, machine-over-data-repo config merge, scope and namespace validation. | — |
| `secret_preflight.py` | Refuses a bounded set of obvious credential shapes before persist or transmit. | Complete leak prevention. |
| `vcs/jj_backend.py` | Every Jujutsu command; `commit_files` asserts that only the expected paths are dirty. | — |
| `cli.py` | `bootstrap` (including `--review-endpoint`, `--review-model`, `--review-key-env`, endpoint validation and the effective-configuration report), `doctor` and operator commands. | Server behavior. |

## Contract mapping

- Lifecycle: `trail.py::propose_truth` applies `approve → approved`, `reject → rejected`, `error → error`; a record moves to its permanent namespace on approval, or on an unreviewed proposal (no verdict supplied). Every `propose_truth` outcome and `supersede` go through `persist_governance`, including the original's `superseded_by` link on approval.
- Review gate: `handle_propose_truth` selects `review_thought` or `review_thought_decisions` from the effective policy; neither writes a record.
- Identity: `_authorize_tool` overwrites `agent_id` with the process identity for write tools and rejects caller-supplied principal or approval provenance.

## Known gaps and limits

- Defaults are applied per key, so partial configurations can still pair constants from different backends. The one pairing that is always wrong, `llm-oneshot` with a Decisions-only model, is refused at promotion, doctor and tunnel preflight; the others are diagnosed with an informational note and left unchanged (see [Local review default](../../../features/local_review_default.blueprint.md)).
- `save_thought`, `update_thought` and `learn_preference` write the file before the Jujutsu steps and do not use the governance journal. An interrupted write can leave a dirty working copy.
- `llm-oneshot` retries transport failures up to three times; `trust_gate_timeout_secs` is now passed to each attempt and also bounds the whole call, so one slow reviewer can still use up to three times the setting before the outer bound applies.
- `save_global_config` persists every field, defaults included, so a command that rewrites `config.yaml` turns unstated Trust Gate keys into stated ones.
- Recall is lexical. There is no semantic search.
- `trust_gate: human` is accepted by the schema and raises when used.
- A shared MCP endpoint is one identity; there is no per-caller isolation inside it.

## Verification

Run on `fava-trails@0f7c01f` with `python -m pytest` over `tests/test_config.py`, `test_machine_trust_gate_config.py`, `test_trust_gate.py`, `test_trust_gate_local_provider.py`, `test_trust_gate_decisions.py`, `test_trust_gate_egress.py`, `test_governance.py`, `test_local_only_sync.py` and `test_navigation_tools.py`: 236 passed. These use fixture servers and a local Jujutsu 0.45.1. They are not evidence of review quality from a real model, and they are a subset of the full suite. PRREF adds `tests/test_local_review_default.py`, and the full suite passed on its head.

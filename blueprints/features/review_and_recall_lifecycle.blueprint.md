---
feature_name: review_and_recall_lifecycle
status: draft
module_blueprints: [review_gate]
dependencies: []
date_added: 2026-10-24
---

# Review-and-recall lifecycle

## Status

- Design: draft. This document describes existing behavior and proposes no change to it.
- Implementation: Implemented. Claims were compared with source at `fava-trails@0f7c01f` (version 0.8.5rc1); behaviors without a dedicated test say so.
- Evidence: 236 fixture-based tests across configuration, the review gate, governed visibility, local-only sync and navigation passed on that revision. The reviewer in those tests is a fixture HTTP server; no real model was run.
- Release: not applicable; no behavior changes here.

## What the lifecycle does

An agent saves a draft that other agents cannot see. A reviewer approves or rejects it when the agent proposes it. Approved records appear in default recall. A correction replaces an approved record only after the correction is itself approved.

```text
save_thought ─▶ drafts/ (draft) ──propose_truth──▶ review gate
                                                    ├─ approve ─▶ decisions/ observations/ preferences/ (approved)
                                                    ├─ reject  ─▶ stays in drafts/ (rejected, content frozen)
                                                    └─ error   ─▶ stays in drafts/ (error)
recall / get_thought (default) ─▶ approved records with no approved successor
supersede ─▶ new draft ──propose_truth──▶ approve ─▶ original becomes historical
```

## Responsibilities and interfaces

| Concern | Owner | Behavior |
| --- | --- | --- |
| Identity | Operator's process environment | `FAVA_TRAILS_AGENT_ID` names the one agent for a process; a caller-supplied `agent_id` must match it. `FAVA_TRAILS_OPERATOR=1` adds history, rollback and explicit human approval, and belongs only on a separate operator endpoint. Tool arguments cannot grant either. |
| Visibility | `governance.py` | `governed` (default): approved records without an approved successor. `authoring`: the configured agent's own draft and proposed records. `history`: operator-only, any lifecycle status. Namespace and tag filters narrow a view; they never widen it. |
| Review | [Review gate](../modules/review_gate.blueprint.md) | Returns `approve`, `reject` or `error` with reasoning and provenance. |
| Persistence | `trail.py`, `transactions.py` | Each lifecycle step is a local Jujutsu commit. |
| Recall | `TrailManager.recall` | Lexical: lowercase the query, split on whitespace, require every token to be a substring of the record's content, id, source type, agent, project, branch or tags. |

Approval provenance is server-owned. A model verdict is recorded as `kind: llm_advisory`, which is neither human approval nor verification that the record is true. A caller-supplied `metadata.extra.approval` is refused.

## Rejection and revision

A rejected draft stays in `drafts/` with its verdict recorded, and `update_thought` refuses to edit it. The caller receives the reviewer's reasoning in that response. Authoring mode lists only draft and proposed records, so after a recorded reject or error the agent can no longer read, edit, re-propose or supersede that record. To revise, it saves a new draft (optionally with `parent_id` pointing at the rejected record) and proposes that. An operator, who can see every status, can re-propose the record unchanged.

Under a rubric reviewer the reasoning is an explanation. Under Decisions it states a probability and a threshold with no rationale, so the agent has only the threshold gap to revise against. A remote reviewer has already received the text when it returns a reject.

## Correction

`supersede` writes a draft successor linked to the original. The original stays current while the successor is a draft, proposed, rejected or errored. When the successor is approved, one governance transaction writes the successor and the original's `superseded_by` link together. Approval is refused if the original already has an approved replacement (checked in `propose_truth`; no dedicated test). Supersession records lineage; it does not show the replacement is true, and it does not remove contradictions elsewhere in a trail. The review gate sees one candidate at a time and does not compare it with existing records.

## Publication and sync

Every step commits locally. Publishing is separate:

- `push_strategy: manual` (the bootstrap default): the operator runs `jj bookmark set main -r @-` then `jj git push --bookmark main`.
- `push_strategy: immediate`: the server pushes after each successful write operation, including a successful `sync`. A failed push is a warning and does not undo the write.
- The sync operation itself fetches and rebases. It reports `not_configured` when no remote exists, blocks on a dirty working copy, and restores the prior state on conflict. For non-operators it returns a fixed summary without paths or raw diagnostics.

A peer sees a record only after the writer has published it and the peer has synced.

## Failure and interruption

| Trigger | Outcome |
| --- | --- |
| Missing credential, configuration error, or the outer review timeout (`trust_gate_timeout_secs`) firing first | A tool error. No verdict is recorded and the record stays a draft, so the same caller can retry once the cause is fixed. |
| Reviewer reachable but failing (HTTP or authentication error, a provider-level timeout or connection error returned as a reviewer result, unparsable reply) | Verdict `error` is recorded; nothing is promoted; no other provider is tried. The authoring agent cannot re-propose the record. See Rejection and revision for what the agent can do next. |
| Draft edited while under review | Approval is refused ("re-review"). |
| Process killed during `save_thought` or `update_thought` | The file write precedes the Jujutsu commit steps and these writes do not use the governance journal. An interruption can leave an uncommitted file, and later writes to that repository can then refuse with an unexpected-dirty-path error until an operator resolves it. A successful tool return is the durability signal; an in-flight write is not guaranteed to survive. |
| Process killed after a `propose_truth` or `supersede` write began but before its commit finished | A before-image journal in `.jj/` keeps readers on the old complete state. A read during a live transaction gets a retryable busy error. The next governance writer restores the before-images and commits a recovery change. The approval is rolled back, not completed; propose it again. |
| Push fails after a committed approval | The approval stands in the local repository, and peers keep seeing the previous state until a push succeeds. |

Do not describe this system as crash-proof or as preventing contradictory memories.

## Verification outcomes

| Condition | Expected result | Evidence (fixture) |
| --- | --- | --- |
| Default recall with draft, proposed, rejected and error records present | Only approved records | `test_governance.py::test_default_recall_only_current_approved` |
| An approved record with an approved successor | Only the successor | `test_replacement_is_current_only_after_approval` |
| Agent supplies another `agent_id` | Permission error | `test_agent_cannot_claim_another_identity_or_read_their_draft` |
| Successor proposed, rejected or errored | Original stays current | `test_unsuccessful_review_does_not_retire_approved_original` |
| Process death after the writes, before the commit completes | Old view readable; next writer recovers | `test_process_death_mid_approval_keeps_old_view_and_recovers` |
| Rejected record edited | Refused, content frozen | `test_tools.py::test_update_thought_content_freeze_rejected` (outside the 236-test set) |
| Remote missing | `sync` reports `not_configured`; local save, review and supersession still work | `test_local_only_sync.py` |

Evidence gap: no recorded run of the full cycle against a real local reviewer.

## Limits kept

Per-trail `trust_gate_policy` treats the value `llm-oneshot` as "inherit global", so a trail cannot pin `llm-oneshot` when the global policy is `decisions`.

## References

[`docs/governed-recall.md`](../../docs/governed-recall.md) states the operator-facing visibility, identity and replacement rules. [Documentation ownership](../../docs/documentation-ownership.md) maps each topic to its owner.

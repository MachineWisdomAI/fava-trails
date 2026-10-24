---
feature_name: review_and_recall_lifecycle
status: draft
module_blueprints: [review_gate]
dependencies: []
date_added: 2026-10-24
---

# Review-and-recall lifecycle

## Status

- Design: draft. This document describes existing behavior; it proposes no change to it.
- Implementation: Implemented. Every claim below was checked against source at `fava-trails@0f7c01f` (version 0.8.5rc1).
- Evidence: 236 existing fixture-based tests covering configuration, the review gate, governed visibility, local-only sync and navigation tools passed on that revision. No real-model review was run for this document; the reviewer in those tests is a fixture HTTP server.
- Release: not applicable; no behavior changes here.

## What the lifecycle does

An agent saves a draft. Other agents cannot see it. A reviewer approves or rejects it when the agent proposes it. Approved records appear in default recall. A later correction replaces an approved record only after the correction itself is approved.

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
| Visibility | `governance.py` | `governed` (default): approved records without an approved successor. `authoring`: the configured agent's own draft/proposed records. `history`: operator-only, any lifecycle status. Namespace and tag filters narrow a view; they never widen it. |
| Review | [Review gate](../modules/review_gate.blueprint.md) | Returns `approve`, `reject` or `error` with reasoning and provenance. |
| Persistence | `trail.py`, `transactions.py` | Each lifecycle step is a local Jujutsu commit. |
| Recall | `TrailManager.recall` | Lexical, not semantic: lowercase the query, split on whitespace, require every token to be a substring of the record's content, id, source type, agent, project, branch or tags. |

Approval provenance is server-owned. A model verdict is recorded as `kind: llm_advisory`, which is neither human approval nor verification that the record is true. A supplied `metadata.extra.approval` is refused.

## Rejection and revision

A rejected draft keeps its place in `drafts/` with its verdict recorded, and `update_thought` refuses to edit it. To revise, the agent saves a new draft (setting `parent_id` to the rejected record) and proposes that. The caller receives the reviewer's reasoning. Under a rubric reviewer this is an explanation; under Decisions it is a statement of probability and threshold with no rationale, so the agent has nothing to revise against except the threshold gap. A rejection does not mean the text stayed local: a remote reviewer has already received it.

## Correction

`supersede` writes a draft successor that links to the original. The original stays current while the successor is a draft, proposed, rejected or errored. When the successor is approved, one governance transaction writes the successor and the original's `superseded_by` link together. A concurrent attempt to replace an already-replaced record is refused. Supersession records lineage; it does not show the replacement is true, and it does not remove contradictions elsewhere in a trail. The review gate sees one candidate at a time and does not compare it against existing records.

## Publication and sync

Every step commits locally. Publishing is separate:

- `push_strategy: manual` (the bootstrap default): the operator runs `jj bookmark set main -r @-` then `jj git push --bookmark main`.
- `push_strategy: immediate`: the server pushes after each successful write. A failed push is reported as a warning and does not undo the write.
- `sync` fetches and rebases only. It never publishes. It reports `not_configured` when no remote exists, blocks on a dirty working copy, and restores the prior state on conflict. For non-operators it returns a fixed summary without paths or raw diagnostics.

A peer sees a record only after the writer has published it and the peer has synced.

## Failure and interruption

| Trigger | Outcome |
| --- | --- |
| Reviewer unreachable, unauthorized, malformed, or missing credentials | Verdict `error`; nothing is promoted; the caller is told to retry. No other provider is tried. A reviewer timeout returns an error without recording a verdict. |
| Draft edited while under review | Approval is refused ("re-review"). |
| Process killed during `save_thought` or `update_thought` | The file write precedes the Jujutsu commit steps. An interruption can leave an uncommitted file, and later writes to that repository can then refuse with an unexpected-dirty-path error until an operator resolves it. A successful tool return is the durability signal; an in-flight write is not guaranteed to survive. |
| Process killed during approval or supersession | A before-image journal in `.jj/` keeps readers on the old complete state. A read during a live transaction gets a retryable busy error. The next governance writer restores the before-images and commits a recovery change. The approval is rolled back, not completed; re-propose it. |
| Push fails after a committed approval | The approval stands in the local repository, so peers keep seeing the previous state until a push succeeds; the failure surfaces as a warning (`push_strategy: immediate`) or does not arise (`manual`). |

Do not describe this system as crash-proof or as preventing contradictory memories.

## Verification outcomes

| Condition | Expected result | Evidence |
| --- | --- | --- |
| Default recall with drafts, rejected and superseded records present | Only current approved records | `test_governance.py::test_default_recall_only_current_approved` (fixture) |
| Agent supplies another `agent_id` | Permission error | `test_agent_cannot_claim_another_identity_or_read_their_draft` (fixture) |
| Successor proposed, rejected or errored | Original stays current | `test_unsuccessful_review_does_not_retire_approved_original` (fixture) |
| Process death mid-approval | Old view readable; next writer recovers | `test_process_death_mid_approval_keeps_old_view_and_recovers` (fixture) |
| Rejected record edited | Refused, content frozen | `test_update_thought_content_freeze_rejected` (fixture) |
| Remote missing | `sync` reports `not_configured`; local save, review and supersession still work | `test_local_only_sync.py` (fixture) |

Open evidence gap: no recorded run of the full cycle against a real local reviewer. The operator walkthrough in the documentation release owns that run.

## Open decisions

None. One recorded limit: per-trail `trust_gate_policy` treats the value `llm-oneshot` as "inherit global", so a trail cannot pin `llm-oneshot` when the global policy is `decisions` ([Local review default](local_review_default.blueprint.md)).

## References

- [`docs/governed-recall.md`](../../docs/governed-recall.md), the operator-facing statement of the visibility, identity and replacement rules.
- [Documentation ownership](../../docs/documentation-ownership.md)

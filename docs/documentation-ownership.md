# Documentation ownership

Each fact has one authoritative source. Other documents summarize it and link to it. When behavior changes, the change updates the owner and every summary in the same delivery scope.

## Who owns what

| Fact | Owner | Summaries that must agree |
| --- | --- | --- |
| What FAVA is for, and the claims made about it | [README](../README.md) opening sections and the wording table below | Website pages, package description, an agent index (`llms.txt`) when published |
| The values of built-in defaults | `src/fava_trails/models.py` | Every document that quotes a default. Blueprints quote values only with the inspected revision. |
| How to install and configure: per-machine setup, providers, credentials | [AGENTS_SETUP_INSTRUCTIONS.md](../AGENTS_SETUP_INSTRUCTIONS.md) | README quick start, website Quick Start |
| Tool parameters and results | [AGENTS.md](../AGENTS.md) | Tool descriptions in `server.py` |
| Session protocol for agents | [AGENTS_USAGE_INSTRUCTIONS.md](../AGENTS_USAGE_INSTRUCTIONS.md) | Website agent guidance |
| Operator rules: visibility modes, identity setup, replacement and recovery procedures | [governed-recall.md](governed-recall.md) | README feature list |
| Why the lifecycle works as it does: flow, publication, failure behavior | [Review-and-recall lifecycle](../blueprints/features/review_and_recall_lifecycle.blueprint.md) | Website lifecycle pages, case study |
| The review gate's contract and the reasons behind it | [Review gate](../blueprints/modules/review_gate.blueprint.md) | Setup guide, README Trust Gate paragraph |
| The planned change to new-install review | [Local review default](../blueprints/features/local_review_default.blueprint.md) | Nothing, until a release contains the change |
| Interrupted-write guarantees (the short statement) | [README](../README.md) durable-writes bullet | Website, `AGENTS.md` summaries |
| Runtime identity and upgrades | [runtime-and-upgrade.md](runtime-and-upgrade.md) | README upgrade notes |
| Release history | [CHANGELOG.md](../CHANGELOG.md), [releases/](releases/) | None. History is never edited to match later behavior. |
| Website page layout and authoring rules | `AGENTS.md` in the [fava-trails.org](https://github.com/MachineWisdomAI/fava-trails.org) repository | Site contributors and agents |

The website repository owns presentation only. A page may shorten an explanation but must not introduce a claim, default or guarantee that the owning document does not make.

## Approved and avoided wording

| Say | Do not say | Why |
| --- | --- | --- |
| A successful tool return means the write finished. An interrupted write can leave a recoverable working copy. | "Crash-proof", "no unsaved work", "every write is atomic" | `save_thought` and `update_thought` write a file before their commit steps and can leave it uncommitted. Approval, rejection and supersession use a before-image journal. |
| A correction replaces a record only after it is approved, and lineage is preserved. | "No contradictory memories" | The review gate sees one candidate at a time and does not compare it with existing records. |
| The reviewer applies a rubric or a probability threshold with limited context. | "Validates", "verifies" or "ensures accuracy" | A convincing false claim can be approved. |
| With a remote reviewer, the text has already been sent when a reject is returned. | "Rejected content never leaves your machine" | Transmission precedes the verdict. A local reviewer keeps it on the configured host. |
| Jev returns a probability and no explanation. | "Jev explains its rejections" | The response carries no reasoning. |
| Approved by model review (`llm_advisory`) or by explicit operator action (`human`). | "Human-reviewed" for a model verdict | The two are recorded differently. |

## Keep three kinds of evidence apart

- **Approved design.** A Blueprint's design status and the revision that was reviewed.
- **Implementation.** What a source revision does, with the tests and runs that show it. Fixture tests and runs against a real reviewer are separate claims.
- **Release.** A published package and a deployed site. A merged pull request is neither.

Product prose states the first two as current facts and the third only once it is true. Delivery chronology, worker instructions and review history stay in the tracker.

## Changing behavior

1. Find the fact above and read its owner.
2. Change the owner and update the affected Blueprint's Status section.
3. Update each listed summary in the same delivery scope. When a summary lives in the other repository, open a linked change there.
4. Leave release notes for earlier versions as written.

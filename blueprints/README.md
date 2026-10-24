# Blueprints

Blueprints explain how FAVA Trails behaves and why, in enough detail for an engineer to judge a change before reading the code. They adapt the feature / module / codebase split of the [A2UI Blueprint model](https://github.com/a2ui-project/a2ui/tree/1657e70119eaa3b76c2a106ac60c7c4dcfe206e0/blueprints) and leave its tooling behind.

| Type | Location | Describes | Front matter |
| --- | --- | --- | --- |
| Feature | [`features/`](features/) | A capability or change that crosses modules: flow, failure behavior, verification outcomes. | `feature_name`, `status`, `module_blueprints`, `dependencies`, `date_added` |
| Module | [`modules/`](modules/) | One responsibility: what it owns, what callers can rely on, where its authority ends. | `name`, `type: module`, `description`, `status` |
| Codebase | [`codebases/`](codebases/) | How a source tree realizes a module contract, with known gaps. The path mirrors the repository path. | `codebase_path`, `associated_module`, `implemented_features` |

Filenames are stable `snake_case` capability names with no dates. Feature and module `status` is the design decision: `draft`, `approved`, `rejected` or `superseded`. A codebase document describes inspected code and carries no design status.

## Find a design

| If you are working on… | Start here |
| --- | --- |
| Save, review, recall and correct a record end to end | [Review-and-recall lifecycle](features/review_and_recall_lifecycle.blueprint.md) |
| The review gate's contract, provider selection and failure behavior | [Review gate](modules/review_gate.blueprint.md) |
| Which reviewer new installations use, and how existing configuration is preserved | [Local review default](features/local_review_default.blueprint.md) |
| Which source file owns what | [`src/fava_trails` codebase map](codebases/src/fava_trails/codebase.blueprint.md) |
| Which document is authoritative for a behavior | [Documentation ownership](../docs/documentation-ownership.md) |

## Status section

Every feature and module has a short **Status** section with four separate lines, so a reader can tell what to rely on:

- **Design** — the decision above, and the reviewed revision once approved.
- **Implementation** — `Not started`, `Partial`, `Implemented` or `Unverified`, with the source revision inspected or the change that landed it, and any scope still missing.
- **Evidence** — fixture tests, observed runs against a real reviewer, and release publication are different claims. Say which one a sentence relies on.
- **Release** — a source merge is not a published package or a deployed site.

A merged document does not approve or implement anything by itself.

## Authoring

Write for a reader deciding whether the design makes sense. Lead with a before/after example, then responsibilities, interfaces, tradeoffs, failure behavior and verification outcomes. Aim for 500–1,000 words per feature; go longer only when the contract needs it. Keep worker instructions, review chronology and ticket history in the tracker. To change a Blueprint alongside code, tests and documentation, see [Maintaining Blueprints](../docs/blueprint-maintenance.md).

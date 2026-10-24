# Blueprints

Blueprints explain how FAVA Trails behaves and why, in enough detail for an engineer to judge a change before reading the code. They adapt the feature / module / codebase split used by the A2UI and SAGA projects, and leave the rest of that tooling behind.

| Type | Location | Describes |
| --- | --- | --- |
| Feature | [`features/`](features/) | A capability or change that crosses modules: the user-visible flow, failure behavior and verification outcomes. |
| Module | [`modules/`](modules/) | One responsibility: what it owns, what callers can rely on, where its authority ends. |
| Codebase | [`codebases/`](codebases/) | How the source tree realizes the module contracts, including known gaps. Paths mirror the repository path. |

Filenames are stable `snake_case` capability names with no dates. A document's front matter `status` records the design decision: `draft`, `approved`, `rejected` or `superseded`. Its **Status** section records, separately, what is implemented and what evidence exists. A merged document does not approve or implement anything by itself.

## Find a design

| If you are working on… | Start here |
| --- | --- |
| Save, review, recall and correct a record end to end | [Review-and-recall lifecycle](features/review_and_recall_lifecycle.blueprint.md) |
| The review gate's contract, provider selection and failure behavior | [Review gate](modules/review_gate.blueprint.md) |
| Which reviewer new installations use, and how existing configuration is preserved | [Local review default](features/local_review_default.blueprint.md) |
| Which source file owns what | [`src/fava_trails` codebase map](codebases/src/fava_trails/codebase.blueprint.md) |
| Which document is authoritative for a behavior | [Documentation ownership](../docs/documentation-ownership.md) |

## Status vocabulary

- **Design** — `draft`, `approved`, `rejected` or `superseded`, plus the reviewed revision once approved.
- **Implementation** — `Not started`, `Partial`, `Implemented` or `Unverified`. State the source revision inspected or the change that landed it, and name any scope still missing.
- **Evidence** — fixture tests, observed runs against a real reviewer, and release publication are different claims. Record each separately and say which one a sentence relies on.
- **Release** — a source merge is not a published package or a deployed site.

## Authoring

Write for a reader deciding whether the design makes sense. Lead with a before/after example, then responsibilities, interfaces, tradeoffs, failure behavior and verification outcomes. Keep a feature to roughly 500–1,000 words. Worker instructions, review chronology and ticket history belong in the tracker, not here. Use `mw-writing-tech-specs`, then `mw-writing-for-human-readers`.

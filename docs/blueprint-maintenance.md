# Maintaining Blueprints

This guide is for engineers who change FAVA Trails behavior and need to keep its design records, code, tests, documentation and website summaries in agreement. It assumes you have read the [Blueprints README](../blueprints/README.md) and can find the owner of a fact in [documentation ownership](documentation-ownership.md). It does not repeat either. It shows how to use them together on one change.

## Choose the record

A Blueprint lets a reviewer judge a change before reading the code. Pick the record by the question the change raises.

A **feature** Blueprint describes behavior that crosses modules: a flow, its failure behavior and the outcomes that verify it. Choose it when the change alters what an operator or agent experiences end to end, for example which reviewer a new installation uses. A **module** Blueprint describes one responsibility, what callers can rely on and where its authority ends. Choose it when the change alters something other code depends on, such as how the review gate selects a reviewer, which failures it reports or how long it waits. A **codebase** Blueprint describes how a source tree realizes a module contract and lists known gaps. Choose it when files move, ownership between files changes, or inspected behavior no longer matches the map or its gaps.

Most changes touch more than one. A feature names the modules it relies on in `module_blueprints`, but naming a module is not the same as having checked it. Read the module record and compare its specific statements with the new behavior, not only its headline principle. A module can keep the same principle and still need edits to the details beneath it, such as limits, selection rules, failure rows and verification outcomes. When you leave a record alone, say so in the pull request and give the reason, so a reviewer knows it was considered. Do not create a new record for a variation of an existing capability; extend the existing one. Filenames are stable `snake_case` capability names with no dates.

## Status fields and approval provenance

Feature and module front matter carries a design `status` of `draft`, `approved`, `rejected` or `superseded`. A codebase record describes inspected code and carries no design status. Each feature and module also has a Status section with four separate lines, and each line makes a different claim:

- **Design** is the decision, plus the reviewed revision once approved.
- **Implementation** is `Not started`, `Partial`, `Implemented` or `Unverified`, with the source revision inspected or the change that landed it, and any scope still missing.
- **Evidence** says whether a sentence relies on fixture tests, on observed runs against a real reviewer, or on a published release. These are three claims.
- **Release** records whether a package or site containing the change has been published. A source merge is neither.

A merged Blueprint does not approve or implement anything by itself. Approval is recorded where the project's reviewers record design decisions, and the Blueprint then cites the reviewed revision, which is the commit the reviewers read. When you record an approval, change the front matter `status` and the Design line together, in one change, and cite that revision in the Design line with a link to the recorded decision under References.

When you land an implementation, update the Implementation line afterward, from the code you inspected: name the revision or merged change, and name any scope still missing. Add to the Evidence line only what has been run, naming the tests or runs. Leave Release alone until a package or site is published. A design is not implemented because it is approved, and it is not released because it is implemented. Conversely, code that is present and passes the required source checks is `Implemented` and merged but unreleased; it does not need publication or a live run first. Those two later steps are recorded on the Release and Evidence lines and gate only the claims that depend on them.

Keep ticket chronology, review history and worker instructions out of the Blueprint. A link to the tracking issue under References is enough.

## What each record must say

Write for a reader deciding whether the design makes sense. Lead with a before and after example, then give responsibilities, interfaces, tradeoffs, failure behavior and verification outcomes. Aim for 500 to 1,000 words per feature and go longer only when the contract needs it.

Responsibilities name the component that does each job, so a contributor can find the file. Interfaces name what crosses a boundary: command options, configuration keys, tool results. Failure behavior says what happens, whether the stored record changes, and who can retry. Evidence is a list of verification outcomes, each a condition and an observable result. A planned outcome stays labelled planned until a test or run exists. Quote a built-in default only together with the inspected revision, because `src/fava_trails/models.py` owns the value.

## Worked example: a local review default

This example illustrates the workflow. It is built on the design in [Local review default](../blueprints/features/local_review_default.blueprint.md) and shows how a contributor would take such a design from an approved record to a source change, a release and a live check. The steps describe the workflow; they do not assert that any installation selects a local reviewer. Read the feature Blueprint for the full contract. The summary here is enough to follow the steps.

### 1. State the contract before and after

Write the contract first, in a few sentences, because every later claim is checked against it.

Before: at the revision the Blueprint inspected (`fava-trails@0f7c01f`), a fresh installation reviews candidates through hosted OpenRouter with the Jev model. Bootstrap writes only `trails_dir`, `remote_url` and `push_strategy`, and the built-in defaults are policy `decisions`, provider `openrouter`, model `~typesafe/jev-latest`.

After: `fava-trails bootstrap` accepts `--review-endpoint`, `--review-model` and `--review-key-env`. With all three it writes a complete local selection to the data repository's `config.yaml`. With fewer it writes only `trust_gate: llm-oneshot`; absent a per-machine override that supplies the rest, promotion then fails closed with guidance. Existing coherent configurations resolve exactly as before. Bootstrap never writes the per-machine config. After writing, it loads the effective configuration and reports the selection, the destination kind and each Trust Gate key that a per-machine file overrides, so the report diagnoses machine overrides and destination differences. It exits non-zero when the effective destination differs from the requested one.

The contract has three invariants that every owner below must preserve:

1. An explicit, coherent legacy configuration keeps its meaning.
2. A missing or unavailable reviewer fails closed and never falls back to a hosted provider.
3. Shared data-repository configuration is kept apart from per-machine settings, which override it key by key.

### 2. Find the owners and change each in the same delivery scope

Start from the ownership table. For this change the owners and their consequences are as follows.

**Design.** The feature Blueprint owns the flow and failure behavior. When reviewers approve it, update `status` and the Design line together. Then read the [Review gate](../blueprints/modules/review_gate.blueprint.md) module record against the new contract. Its general principle, that every failure yields an error or a tool error, promotes nothing and contacts no other reviewer, stays as written. Several details beneath it are affected and need inspection and, where they no longer match, edits:

- The failure table's row for a slow reviewer states that, for `llm-oneshot`, each HTTP attempt is capped at 60 seconds by the client default, that transport failures are retried up to three times, and that raising `trust_gate_timeout_secs` therefore does not help. The change passes the configured timeout through to chat requests, so this statement and the sentence saying only the Decisions client honors the setting must be rewritten to the new behavior.
- The change adds a check that refuses an `llm-oneshot` policy whose effective model is one of FAVA's own Decisions model constants, before anything is transmitted. The failure table needs a row for this trigger, and the verification outcomes need matching rows.
- The Selection paragraph says bootstrap writes none of the selection keys. Compare it with the new bootstrap behavior and revise what it says about what bootstrap writes.
- The Status section points to the feature for the proposed default; update that pointer to match the feature's recorded status.
- The Limits section records the placeholder-credential and per-trail `inherit` limits. Confirm these still hold and leave them alone if they do.

Do not rewrite the module's responsibilities or its input, output and credential sections without a reason found in the contract. Revise only the statements the change makes untrue or incomplete. Then read the [`src/fava_trails` codebase map](../blueprints/codebases/src/fava_trails/codebase.blueprint.md) and its known gaps. Remove or reword any gap the change closes, such as the timeout limitation, and add any new gap the change leaves behind.

**Implementation.** The feature Blueprint's Responsibilities section maps the work to files: `models.py` and `config.py` for the Decisions-model check and the "stated" diagnostic, `trust_gate.py` and `tools/navigation.py` for applying the check before any network call and for passing `trust_gate_timeout_secs`, and `cli.py` for the bootstrap options, the effective-configuration report and doctor output. Defaults in `models.py` do not change. If your change moves responsibility between files, update the codebase map too. Set the Implementation line only after you have inspected the landed code: `Partial` while any part of the contract is missing, `Implemented` when the whole contract is present, with the revision and any missing scope.

**Tests.** The feature's verification table is the checklist. A required code or fixture row is satisfied only by a test that exists and passes. Listing such a row under known gaps records unfinished work; it does not satisfy the row, and the Implementation line stays `Partial` until the row passes. A row may sit in the gaps only while the change is explicitly labelled partial. The Blueprint also names three existing fixtures that use `llm-oneshot` with the default model and a mocked reviewer, `test_gateway_workflow.py`, `test_mcp_context.py` and `test_trust_gate_decisions.py`, which the new fail-closed check requires you to update. The configurations the Blueprint marks "correct" are the regression set for invariant 1. Run the project's checks as [CONTRIBUTING.md](../CONTRIBUTING.md) specifies: `uv run pytest -v` and `uv run ruff check src/ tests/`.

**Operating documents.** [AGENTS_SETUP_INSTRUCTIONS.md](../AGENTS_SETUP_INSTRUCTIONS.md) owns how to install and configure, so it gains the bootstrap options and the per-machine override report. The README quick start and Trust Gate paragraph summarize it and must agree. The ownership table's summary column for this feature says "Nothing, until a release contains the change"; revisit that row when the release exists.

The approved wording table still applies. With a hosted reviewer, the text has already been sent when a reject is returned; a local reviewer keeps it on the configured host. The absence of a machine override does not by itself show that review stays local, because the explicit endpoint may also be remote. Review goes only to the effective destination the bootstrap report shows. Say "No request leaves the machine" only when that destination is a loopback or on-machine address and the report shows no override that redirects it.

**Site summary.** Website pages in the [fava-trails.org](https://github.com/MachineWisdomAI/fava-trails.org) repository own presentation only. A page that mentions installation or review may shorten the setup guide's explanation but must not claim the new default. Open a linked change in that repository, and hold any statement that new installations use a local reviewer until a release containing the change is published.

### 3. Know what proves each claim

| Claim | What proves it | What it does not prove |
| --- | --- | --- |
| The design is approved | The recorded decision and the reviewed revision cited in the Design line | That any code exists |
| Bootstrap writes the complete selection and leaves the machine config alone | A fixture test for the matching row of the verification table | Behavior against a real local reviewer |
| Incomplete bootstrap input fails closed | Tests showing a tool error or recorded `error` verdict, no promotion and no contact with a hosted provider, with no machine override present | Behavior when a machine file supplies the missing keys; the report covers that case |
| Machine overrides and destination differences are diagnosed | Tests where a machine file supplies a hosted model, redirects the base URL, selects `decisions` or names a key file; the report names the override and destination kind and the exit is non-zero when the destination differs | That an operator reads the report |
| Existing coherent configurations are unchanged | Tests that load each "correct" configuration and compare the effective result with the values the Blueprint recorded at `0f7c01f` | Configurations the Blueprint does not list |
| A Decisions-only model with `llm-oneshot` is refused before transmission | A test showing an error naming `trust_gate_model`, the reviewer not called, and `approval="human"` unaffected | Anything about other policies |
| The configured timeout applies to the whole call | A test with a reviewer slower than 60 seconds and `trust_gate_timeout_secs` raised | Behavior of a real model under load |
| A local reviewer's rejection reason is useful to the caller | A separate run against a real local reviewer, recorded as observed evidence | Anything about other reviewers |
| New installations select a local reviewer for users | A published release containing the change, checked live | A merged pull request |

The rows from bootstrap writing the selection through the raised timeout concern code and fixtures, and passing tests are what let the Implementation line say `Implemented`. The design row depends on a recorded decision. The last two rows are different. They depend on a run against a real reviewer and on a published release, and until those exist the Evidence and Release lines say so. Their absence blocks those two claims, not the description of the merged code. The Blueprint says useful rejection feedback may not be documented until the real-reviewer run exists.

### 4. Separate the source change, the release and live acceptance

A pull request that changes code, tests, Blueprints and operating documents is a source change. Its description says which Status lines it moves and which it leaves. When it merges, label it merged but unreleased, as CONTRIBUTING.md directs, and leave the Release line at nothing published. Publication follows the release process in CONTRIBUTING.md: a version set in a source pull request through `scripts/mw-version.py` and `docs/version-policy.md`, packaging gates on the exact candidate artifacts, and the Release workflow. After the package is published, update the Release line, the ownership table row and the website summaries in their own changes. Release notes for earlier versions stay as written.

Live acceptance is a separate observation. Install the published package in the environment the client launches, check what ran with `fava-trails version` or `fava-trails doctor` as [runtime and upgrade](runtime-and-upgrade.md) describes, and run the scenario against a real local reviewer. Record the result in the Evidence line, naming the scenario, the reviewer and the package version. Until that record exists, documentation makes no claim about live behavior.

## Review checklist for a Blueprint change

- Does each record chosen match the question the change raises, and has each record left alone been checked in detail and said to be so?
- Does each Status line make only the claim its evidence supports?
- Is every required code or fixture row backed by a passing test, rather than listed as a gap? If one is missing, is the change labelled `Partial`?
- Are claims that need a real-reviewer run or a published release held back, and the Evidence and Release lines left accordingly?
- Is every default quoted with an inspected revision?
- Does every summary listed for the changed fact agree with its owner, including any claim about where review requests go?
- Is the source change distinct from release and live acceptance in the wording of the pull request?

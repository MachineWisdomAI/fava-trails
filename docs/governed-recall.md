# Governed recall and replacement approval

FAVA stores governed decisions, observations, validation evidence, and lineage.
Operational working context belongs in the caller's working-context system.

## Views

`recall` and `get_thought` use the same visibility rules, including multi-scope
queries, exact-ID fallback, and relationship expansion:

| Mode | Records | Authority |
| --- | --- | --- |
| `governed` (default) | Approved records without an approved successor | Shared readers |
| `authoring` | Own draft/proposed records in explicitly selected scopes | Server-configured agent identity |
| `history` | Selected lifecycle statuses, optionally superseded records | Operator-controlled endpoint |

`namespace` and metadata `scope` narrow a view; neither bypasses lifecycle or
identity checks. `statuses` selects lifecycle states in authoring/history mode.
`include_superseded=true` requires history mode. Direct lookup does not expose
private records or private ambiguity candidates. Authoring lookup never expands
an incorrect scope into a global private-record search.

```python
recall(trail_name="example/engineering", query="decisions")
recall(trail_name="example/engineering", mode="authoring", statuses=["draft", "proposed"])
# Only on an operator-controlled endpoint:
recall(trail_name="example/engineering", mode="history", statuses=["rejected"], include_superseded=True)
```

## Identity boundary

The operator sets `FAVA_TRAILS_AGENT_ID` when starting a dedicated MCP process.
An agent may omit `agent_id`; if it sends one, it must match that configured
identity. Tool arguments cannot establish a principal or grant operator powers.
An unconfigured process offers governed reads and scope discovery; writes and
private authoring require configuration.

Keep each private authoring endpoint within one authenticated identity boundary.
The existing HTTP gateway's shared credential represents one shared identity;
do not expose one configured authoring process to independent agents and describe
it as identity isolation. Use separate authenticated processes/endpoints or keep
the shared endpoint in governed-read-only mode. Agent processes must not be able
to alter operator-owned launch configuration or access the data repository directly.
The local Python API and filesystem remain trusted operator interfaces.

`FAVA_TRAILS_OPERATOR=1` enables history, repository-history tools, and explicit
human approval on a separate operator-controlled process. Never enable it on an
ordinary agent endpoint. Existing installations must configure identities before
turning on authoring; this change does not migrate files or assume old `agent_id`
claims were authenticated. Existing draft ownership needs operator review before
reusing an old identity for private authoring.

After package upgrades, confirm the process your MCP client launches is the
intended install with `fava-trails version` (module path and product vs MCP SDK
versions). Local `uv run --directory` / vendor selectors can keep an older
checkout active; see [runtime-and-upgrade.md](runtime-and-upgrade.md).

## Replacement lifecycle

`supersede` and `change_scope` create a draft successor with `supersedes_id` and
`supersedes_scope`. They leave the original unchanged and current. A proposal,
rejected verdict, or failed review never retires approved truth.

After successful review, promotion persists the approved successor and the
original's `superseded_by`/`superseded_scope` together. Concurrent replacements
cannot silently overwrite an already approved successor. Repeating promotion of
an approved record does not downgrade it. Legacy eager backlinks to unapproved
successors do not hide originals; no destructive data migration is performed.

The before-image journal in `.jj/fava-governance-transaction.json` keeps reads on
the old complete state until VCS persistence succeeds. Process locks serialize
governance publication across local runtimes. A read during a live transaction
returns a retryable busy error rather than observing partial files. Failure or cancellation restores
the touched files; a process interruption retains the old read view. The next
governance writer records recovery before retrying. Do not delete a pending
journal by hand or copy a data repository mid-transaction. If recovery reports
unrelated dirty files, preserve those files and resolve that specific conflict
before retrying; never reset the repository wholesale.

## Approval evidence

The configured Trust Gate can approve under its existing policy. New provenance
records `metadata.extra.approval.kind="llm_advisory"`; that is not explicit human
approval. On an operator endpoint, `propose_truth(..., approval="human")` records
an explicit operator action with `kind="human"` and the configured actor.
Do not infer human approval from `source_type="user_input"`, the preferences
namespace, a reviewer-shaped string, or legacy metadata. A successor never
inherits its predecessor's approval evidence.

## Rich Views

Generated readers default to the same governed view. Local operators can choose
archaeology explicitly:

```sh
fava-trails rich-view generate --scope example/engineering --out /tmp/fava-reader \
  --mode history --status rejected --include-superseded
```

The generated artifact contains the selected records. Keep authoring/history
artifacts private, and regenerate an existing artifact when changing modes.
`serve --no-generate` serves the existing snapshot, not a newly filtered view.

Each recall response and reader generation captures one repository view before
processing scopes. Per-scope recall hooks and their nested recall queries use
that same view. An approval committed during processing becomes visible on the
next request; one response cannot combine an old current record with its newly
approved replacement.

Configured agents can call `sync` without operator privileges. Their responses
contain a fixed success, blocked, conflict or error summary; private repository
paths, conflict descriptions and raw fetch/push diagnostics remain available only
to operators. Existing conflicts require operator repair. Sync access does not
grant `diff`, `conflicts`, `rollback`, `forget`, history or human approval access.

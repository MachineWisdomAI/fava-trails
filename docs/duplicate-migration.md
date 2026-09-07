# Reviewed duplicate maintenance

`fava-trails duplicates` is a local operator command for an existing JJ data
repository with its conventional `trails/` layout. It is not an MCP mutation.
Markdown remains canonical. Reports and plans contain private provenance and
record bodies: keep them outside source control and do not publish them.

Start with a read-only report:

```sh
fava-trails duplicates --repo /private/data --scope example/operations \
  --out /private/review/duplicates.json
```

The command creates only the requested new artifact, with owner-only permissions.
It does not invoke JJ, create a governance lock, or change the data repository.
Two identical scans are required; an active transaction or changing source causes
an error. The report hashes exact UTF-8 bytes after the closing frontmatter
separator, including whitespace. It is not fuzzy matching or a search service.
All scopes are read to find inbound references, but only the exact selected scope
is grouped. Invalid records are reported and prevent apply until reviewed and
repaired; they are never silently dropped.

For each group you intend to migrate, put its `body_sha256` and the deliberate
canonical `members[].path` in a JSON map, then generate the exact plan:

```json
{
  "<body SHA256 from report>": "trails/example/operations/thoughts/observations/A.md"
}
```

```sh
fava-trails duplicates --repo /private/data --scope example/operations \
  --canonical /private/review/canonical.json --out /private/review/plan.json
```

The plan includes exact before/after text for every rewrite/deletion, hashes for
the complete source snapshot, before/after counts, identity redirects, unresolved
references, approved current counts, blockers, and its SHA256 digest. Unselected
groups stay untouched. Canonical selection must retain approved current truth
when a group contains approved records. Groups with only one unapproved lifecycle
retain that lifecycle; consolidation never approves them. Removed frontmatter,
review provenance, and source hashes remain in the operator-only receipt before
images. The canonical record's `metadata.extra.duplicate_migrations` contains only
a count and opaque audit reference; hidden author context never enters governed
recall through copied metadata. Original body bytes and extension fields
survive rewrites.

The tool redirects unambiguous inbound relationships, parentage, intent and
supersession links across scopes. It refuses conflicting validation/source
assertions, existing supersession on group members, ambiguous IDs, differing
outbound relationships, newly unresolved references, self links, and parent or
supersession cycles. A relationship between duplicate members may therefore need
a separate explicit lineage decision. A blocked plan is an inspectable proposal,
not an executable migration; editing its blocker list does not bypass validation.

Review the complete exact delete/rewrite set and canonical choices, resolve every
blocker, and obtain the operator's explicit approval for this destructive apply.
A digest identifies reviewed bytes; generating it is not approval. Any source
change, including a new inbound record in another scope, requires a fresh plan
and review. The following command is only for that approved plan:

```sh
fava-trails duplicates --repo /private/data --apply \
  --plan /private/review/plan.json --confirm-plan <reviewed-plan-digest>
```

Apply regenerates the safe plan under the shared governance lock, checks the exact
source snapshot and a clean, conflict-free working change, then records the JJ
commit and operation recovery point plus full before images in an owner-only
`.jj/fava-migrations/<digest>.json` receipt. The existing governance journal keeps
readers on one consistent view until all files are durably committed. No push is
performed. Before publication, the tool checks the complete resulting snapshot and saves
durable commit evidence in the receipt. Repeating a completed apply validates the
receipt and committed history without writes or new VCS operations. A crash after
publication leaves a prepared receipt with commit evidence; retry verifies it and
finishes the receipt instead of inferring success from matching files alone.

If the process fails or dies after writes begin, readers retain the before-image
view. Repeating the explicitly approved command recovers the journal through JJ,
then revalidates and applies the same plan. If recovery fails, stop and inspect the
receipt and journal; do not delete them to force progress. Receipts and journals
are local metadata, so keep the private plan with the repository's backups.

To undo a completed migration, review and approve rollback, then use:

```sh
fava-trails duplicates --repo /private/data --rollback \
  --plan /private/review/plan.json --confirm-plan <reviewed-plan-digest>
```

Rollback requires the complete post-migration snapshot to still match. It commits
the exact original Markdown bytes using the same journal and saves a separate
recovery receipt. It never overwrites subsequent edits. If the repository changed,
prepare a separately reviewed recovery from the recorded before images or JJ
recovery point. Do not blindly restore a repository-wide JJ operation over later
work. Repeated successful rollback is a no-op.

For WisdomLoop issue #74, real migration and malformed-record repair remain
explicit reviewed-apply decisions. Synthetic acceptance tests demonstrate tooling
behavior; they do not establish that a real-data migration or operator approval
has occurred.

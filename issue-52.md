title:	Generate a minimal FAVA reader from source records
state:	OPEN
author:	timeleft--
labels:	ready-for-agent
comments:	0
assignees:	
projects:	
milestone:	
issue-type:	
parent:	
sub-issues:	
sub-issues-completed:	
blocked-by:	
blocking:	
number:	52
--
## Parent

Parent PRD: #51

## What to build

Build the first end-to-end tracer bullet for FAVA Rich Views: a plain Astro-based reader that can generate a minimal local render from FAVA source thought records.

The slice should prove the core contract: existing FAVA Markdown records are read as the source of truth, ULIDs remain durable identity and route keys, human-readable titles are display metadata derived from the record, and the generated output carries enough freshness metadata for a reader to know when and from which scope it was generated.

This issue does not need a full dashboard, search, graph, or polished UI. It should produce a small but real generated reader that future slices can extend.

## Acceptance criteria

- [ ] A manual generation command or documented command sequence builds a minimal FAVA reader from fixture FAVA source records.
- [ ] The generated reader uses plain Astro and does not start from Starlight or Quartz.
- [ ] The generated reader preserves ULID-backed thought identity and route uniqueness.
- [ ] The generated reader displays a human-readable title derived from an explicit title if available, otherwise the first heading or a body-derived fallback.
- [ ] The generated output includes generation metadata, at minimum the input scope and generation time.
- [ ] The generated output does not imply that the static view is live.
- [ ] Tests or build checks verify generation from fixture FAVA records and preservation of ULID-backed routes.

## Blocked by

None - can start immediately.


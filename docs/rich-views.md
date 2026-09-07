# Read a FAVA scope locally

Rich Views generates a read-only Astro snapshot from the existing Markdown thought records. The source trail remains canonical. The generated reader contains the included private data, so keep its output directory private and serve it on loopback.

```bash
# Generate a known scope and every descendant scope.
fava-trails rich-view generate \
  --trails-dir /path/to/data-repo/trails \
  --scope example/operations \
  --out /path/to/private-reader

# Build the static snapshot, then use the supported local server.
npm install --prefix /path/to/private-reader
npm run build --prefix /path/to/private-reader
fava-trails rich-view serve --out /path/to/private-reader --no-generate --no-install
```

The local server binds to `127.0.0.1:4321` by default. Supply `--port` to choose another local port. To generate and serve in one step, use `rich-view serve` with `--trails-dir` and optional repeated `--scope` arguments. Omitting scope includes all discovered scopes. Manual regeneration replaces generated pages, including obsolete routes. The footer records the input scope and generation time; it never implies that the snapshot is live. A future file watcher or JJ change trigger can invoke the same generator, but automatic regeneration is not included.

## Read the dashboard

The index and `/scopes/<full-scope>/` dashboards include descendant records. Summary counts describe the included records: total thoughts, descendant scopes, active decisions, draft/proposed records, and superseded records. An active decision is an approved decision without a supersession target.

Use namespace, source type, validation, tag, contributor, and scope filters together. Quick views show active decisions, unfinished records, or superseded records. Reset clears every filter. Recent activity is ordered by source creation time; contributors and scope links summarize the included records. Excerpts stay compact; source provenance is available on each row.

## Follow a record

Human routes include the full scope and a title-derived slug. If titles collide within a scope, only the colliding routes receive a short ID suffix. The canonical and fallback routes are recorded in `src/data/generated.json` under `thoughtRoutes`. `/id/<thought-id>/` remains the durable lookup when a title changes. Source filenames and frontmatter are never renamed to match human routes.

Thought pages show validation, source type, confidence, contributor, tags, creation time, namespace, source path, and durable ID before the full Markdown body. Parentage and supersession form explicit lineage links. The same title never merges two identities. Cyclic source links remain finite to traverse and keep their explicit edge labels.

Typed relationship sections preserve the stored FAVA types and show inbound links from included records. Targets absent from the selected view remain visible as **Unresolved / outside this view**, without guessing a title or exposing a hidden record. This can mean a missing source record, another scope, or an excluded record; the UI does not invent which explanation applies.

## Markdown boundary

Astro's supported Unified processor handles Markdown. `rehype-sanitize` removes executable HTML, event attributes, and unsafe URL protocols from the rendered body. The original Markdown remains unchanged and available in the source repository. This reader does not treat agent-authored HTML as executable UI code. No search index, thought write controls, public hosting, or alternate lifecycle is introduced.

## Acceptance still requiring an operator

Implementation and fixture/browser verification are separate from the five real context re-entry or review sessions in issue #54. The operator still needs to record whether the dashboard reduces raw-file opening or manual reconstruction, what remains hard to inspect, and a continue, revise, or stop decision. Synthetic QA sessions do not count toward that acceptance. The September 7 continuation authorizes implementation of the remaining reader surfaces; it supplies no completed operator sessions or product-outcome decision.

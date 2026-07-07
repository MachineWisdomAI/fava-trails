title:	PRD: FAVA Rich Views semantic renderer
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
number:	51
--
## Problem Statement

FAVA Trails already stores valuable institutional memory as Markdown thought records with YAML frontmatter, but the human re-entry path is still mostly agent-mediated. When an operator wants to regain context on a scope, they have to ask an agent to summarize raw trails or read individual Markdown files directly.

That loses the structure FAVA already has: scopes, namespaces, source types, validation status, supersession, parentage, relationships, confidence, agent provenance, tags, and Trust Gate state. Generic Markdown-to-HTML tooling can make the prose nicer, but it cannot answer FAVA-specific questions like what is current, what was superseded, what depends on what, which drafts need attention, or which decisions are active.

The project boundary is therefore: not a Markdown theme, a FAVA semantic renderer.

## Solution

Build a FAVA Rich Views renderer that reads existing FAVA Markdown thought records and renders FAVA semantics as glanceable operator views.

The first milestone should use plain Astro as the static renderer. Astro should parse Markdown, while FAVA-aware view-model and UI code interprets FAVA-specific fields. The original Markdown remains the source of truth. The renderer should not duplicate the thought lifecycle, replace MCP recall, or invent semantics that are not present in FAVA data.

Starlight, Quartz, and Pagefind remain relevant to later search, retrieval, and shareable projection work. They should not set the first renderer's information architecture. This milestone should first prove that FAVA-specific readability works before adding search over the rendered human artifacts or source Markdown.

The first useful product shape is:

- A scope dashboard for a FAVA scope and its descendant scopes.
- Thought detail pages that expose FAVA metadata before the Markdown body.
- Lineage views from parentage and supersession fields.
- Local relationship views from typed FAVA relationships.
- Dense, operational navigation for current decisions, recent observations, drafts, superseded records, tags, contributors, and relationship clusters.

## User Stories

1. As a team operator, I want to open a FAVA scope dashboard, so that I can regain context without asking an agent to summarize raw trails.
2. As a team operator, I want the dashboard to include descendant scopes, so that nested project work is not hidden.
3. As a team operator, I want a first-viewport count summary, so that I can understand the shape of a scope quickly.
4. As a team operator, I want to see total thoughts, child scopes, active decisions, drafts, and supersessions, so that I can decide where to spend attention.
5. As a team operator, I want recent thoughts surfaced separately, so that I can see what changed since my last visit.
6. As a team operator, I want decisions separated from observations and drafts, so that durable commitments are easy to find.
7. As a team operator, I want drafts and proposed records called out, so that unfinished institutional memory is not accidentally treated as settled.
8. As a team operator, I want rejected and tombstoned records represented explicitly, so that the view does not silently erase important lifecycle state.
9. As a team operator, I want superseded thoughts marked clearly, so that I can avoid relying on stale conclusions.
10. As a team operator, I want supersession lineage rendered as a timeline or chain, so that I can see how a conclusion changed.
11. As a team operator, I want thought cards or rows to show source type, validation status, agent, confidence, tags, age, and scope, so that I can scan without reading every body.
12. As a team operator, I want body excerpts instead of full Markdown bodies on dashboards, so that the dashboard stays glanceable.
13. As a team operator, I want full Markdown bodies preserved on thought detail pages, so that evidence and prose remain auditable.
14. As a team operator, I want exact source provenance on every rendered item, so that I can trace a rendered view back to the source record.
15. As a team operator, I want confidence displayed consistently, so that lower-confidence records are visually distinct from strong decisions.
16. As a team operator, I want tags visible and filterable, so that I can pattern-match across related work.
17. As a team operator, I want contributor or agent summaries, so that I can see who produced the trail content.
18. As a team operator, I want relationship counts on thought summaries, so that connected records stand out.
19. As a team operator, I want outbound relationships listed on thought pages, so that I can see what a thought references or depends on.
20. As a team operator, I want inbound relationships listed on thought pages, so that I can see what depends on or references a thought.
21. As a team operator, I want relationship views to use FAVA relationship types, so that the graph is semantic rather than decorative.
22. As a team operator, I want a local relationship graph or relationship page for a scope, so that I can inspect nearby typed connections without a global galaxy graph.
23. As a team operator, I want the dashboard to answer one operational question in under five seconds, so that re-entry is faster than asking for a summary.
24. As a team operator, I want dense rows and compact panels, so that large scopes remain usable.
25. As a team operator, I want visual status cues to carry lifecycle meaning, so that styling is functional rather than decorative.
26. As a team operator, I want the first viewport to avoid prose walls, so that the page is scannable before it is readable.
27. As a team operator, I want child-scope grouping, so that scope hierarchy is visible.
28. As a team operator, I want active decisions surfaced before stale or superseded records, so that current commitments are obvious.
29. As a team operator, I want broken or unresolved relationships called out, so that I can spot trail hygiene problems.
30. As a FAVA maintainer, I want the renderer to read existing FAVA Markdown directly, so that it does not create a second source of truth.
31. As a FAVA maintainer, I want the renderer to preserve the engine/fuel split, so that the package remains the stateless engine and user trail data remains external.
32. As a FAVA maintainer, I want Astro to handle generic Markdown rendering, so that FAVA code does not implement a Markdown parser.
33. As a FAVA maintainer, I want FAVA-specific code to focus on semantic interpretation, so that the module stays narrow and testable.
34. As a FAVA maintainer, I want unsupported edge types deferred, so that the renderer does not invent meaning absent from source records.
35. As a FAVA maintainer, I want duplicate thought IDs or malformed frontmatter to fail visibly, so that rich views do not silently lie.
36. As a FAVA maintainer, I want fixture-based tests over realistic thought records, so that the renderer contract is verified against FAVA data shape.
37. As an agent, I want rendered pages to expose machine-readable metadata later, so that I can consume structure without reparsing prose.
38. As an agent, I want stable thought identifiers in rendered output, so that I can detect drift and avoid stale references.
39. As a future renderer author, I want FAVA semantics kept separate from Astro presentation, so that other outputs can reuse the same interpretation.
40. As a future renderer author, I want scope, thought, lineage, and relationship surfaces modeled distinctly, so that different FAVA objects do not all collapse into one document view.
41. As a team operator, I want human-readable thought titles in rendered views, so that I can scan records without treating ULIDs as prose.
42. As a team operator, I want records with the same or similar titles to remain distinct, so that superseded and current versions do not collapse into one page.
43. As a FAVA maintainer, I want ULIDs to remain the durable route and identity key, so that title changes do not break lineage or relationships.
44. As a team operator, I want a manual way to regenerate the rendered views, so that I can refresh the reader when I know the trail changed.
45. As a team operator, I want rendered pages to show when they were generated, so that I can tell whether a view may be stale.
46. As a FAVA maintainer, I want a clear future trigger path for automatic regeneration, so that a watcher or JJ-backed change trigger can be added without changing the renderer contract.

## Implementation Decisions

- Build a FAVA semantic renderer, not a generic Markdown theme.
- The first renderer should use plain Astro for static page generation and Markdown rendering.
- Do not start the first milestone from Astro Starlight or Quartz.
- Starlight is useful because it brings documentation structure and Pagefind search defaults, but the first milestone needs custom FAVA-semantic surfaces rather than a documentation shell.
- Quartz is useful because it brings graph, backlinks, and garden-style affordances, but the first milestone should not inherit Obsidian-shaped identity or a generic knowledge-garden information architecture.
- Re-evaluate Starlight, Quartz, Pagefind, or a dedicated search index in the follow-up search and retrieval PRD, after the readability surfaces exist.
- Astro parses Markdown; FAVA-aware modules interpret FAVA fields and paths.
- The original FAVA Markdown remains the source of truth.
- The renderer should read existing FAVA thought records directly in the first milestone.
- Do not make a separate Python export-view compiler the first abstraction for this milestone.
- Do not introduce a stored duplicate representation of thoughts.
- Interpret the existing FAVA semantic fields: thought ID, parent ID, supersession target, agent ID, confidence, source type, validation status, intent reference, relationships, metadata, tags, namespace, and scope path.
- ULID remains the durable identity and route key for a thought.
- Do not elevate a ULID into the human title.
- Human-readable titles should be display metadata derived by the renderer from the existing record, such as an explicit title if one exists later, otherwise the first heading or a body-derived fallback.
- Human-readable slugs may be generated for display or convenience, but they must not become the canonical identity for links, lineage, supersession, or route uniqueness.
- Multiple thoughts may legitimately have the same or similar human title, especially across superseded and current versions; the renderer must preserve identity through ULID-backed records.
- Adding canonical `title` or `aliases` frontmatter is not part of this readability milestone. That belongs in the follow-up search and retrieval PRD if search proves it needs canonical human aliases.
- Derive scope and namespace from source location rather than requiring duplicated frontmatter.
- Model the renderer around first-class semantic surfaces: scope dashboard, thought card or row, thought detail page, lineage view, and relationship view.
- The scope dashboard should include descendant scopes from day one.
- Dashboards should render summaries, counts, filters, and compact previews instead of rendering every Markdown body.
- Thought detail pages should expose lifecycle, provenance, relationships, and lineage before the Markdown body.
- Lineage should use parentage and supersession fields.
- Relationship views should use explicit FAVA relationship types and should stay local to a thought or scope.
- A global decorative graph is not part of the first milestone.
- Edge normalization should only use signals FAVA currently stores or can derive deterministically.
- Unsupported semantic edges such as support, contradiction, blockers, and concept mentions are deferred until FAVA stores them explicitly or a deterministic extractor exists with provenance.
- Use existing libraries for generic rendering concerns such as Markdown parsing, typography, routing, and static build output.
- Add search only after the first HTML views exist and the core semantic surfaces are proven.
- Keep the first milestone focused on operator re-entry rather than publishing workflows or synthesized narrative.
- The initial routes should cover scope dashboards, thought detail pages, lineage pages, and local relationship pages.
- The first milestone must include a documented manual generation path for rebuilding the rendered views from the current FAVA source records.
- Rendered output should include generation metadata, at minimum the generation time and the input scope, so users can judge freshness.
- If a source revision, JJ operation marker, Git commit, or content hash is cheaply available, include it in the generated metadata; do not block the first milestone on perfect revision tracking.
- Automatic regeneration should have a named path, such as a file watcher or JJ-backed change trigger, but it may be delivered as a separate follow-up issue if manual generation and freshness metadata are present first.
- The renderer must not imply that a static view is live; stale views should be detectable by generation metadata.
- The renderer should be dense and operational in visual posture, matching a repeated-use knowledge tool rather than a marketing page.
- Styling should communicate lifecycle state, provenance, relationship density, and attention needs.
- The system should preserve a path for later machine-readable metadata such as JSON-LD, but the first milestone should not block on a full metadata publishing strategy.

## Testing Decisions

- The highest-value test seam is the renderer boundary: FAVA Markdown thought records in a fixture trail become rendered scope, thought, lineage, and relationship pages.
- Tests should verify external behavior of the renderer and view model, not internal component structure.
- Fixture data should include multiple scopes, descendant scopes, decisions, observations, drafts, proposed records, superseded records, parentage, explicit relationships, tags, multiple agents, and confidence variation.
- Tests should assert that scope dashboards include descendant-scope records when requested by the milestone.
- Tests should assert counts by namespace, source type, validation status, supersession state, tags, and agents.
- Tests should assert that dashboard summaries do not render full Markdown bodies.
- Tests should assert that thought detail pages preserve the full Markdown body and expose frontmatter-derived metadata.
- Tests should assert that supersession banners appear for superseded thoughts.
- Tests should assert that lineage pages connect parentage and supersession chains correctly.
- Tests should assert that relationship pages expose typed outbound and inbound relationships.
- Tests should assert that unsupported relationship types are not invented.
- Tests should assert that broken internal relationship targets are visible as unresolved or fail according to the chosen renderer contract.
- Tests should assert that duplicate thought IDs are detected rather than silently collapsed.
- Tests should assert that malformed frontmatter fails clearly.
- Tests should include two records with the same or similar display title and different ULIDs, including a supersession case, and assert that the rendered routes and lineage stay distinct.
- Tests should assert that thought summaries show human-readable titles while preserving ULID-backed links and source provenance.
- Tests should verify the manual generation path rebuilds the renderer output from fixture FAVA source records.
- Tests should assert that rendered output includes generation metadata for freshness inspection.
- Existing test prior art includes fixture-based temporary FAVA data repos, nested trail managers, model parsing tests for thought records, recursive scope discovery tests, and lifecycle tests for promotion, supersession, validation status, and recall.
- The Astro build should be part of the verification path once the renderer package exists.
- Browser QA should verify desktop and mobile layouts, no text overlap, no prose wall in the first viewport, usable relationship links, and preserved drill-in access to source bodies.

## Out of Scope

- A generic Markdown theme.
- A replacement for MkDocs, markdown-styles, or project documentation sites.
- A new Markdown parser.
- A stored copy of FAVA thoughts.
- A Python export-view compiler as the first milestone.
- Changes to the core thought lifecycle.
- Changes to Trust Gate behavior.
- Replacing MCP recall.
- Public publishing workflow.
- Search as a milestone blocker. Search and retrieval should be specified in a separate fast-follow PRD after the readability surfaces are defined.
- Canonical `title` or `aliases` migrations for FAVA thought records.
- Choosing Starlight, Quartz, Pagefind, SQLite FTS5, or another search/projection stack for the follow-up search layer.
- Podcast, WhatsApp, email, printable report, or digest generation.
- AI-generated synthesis that invents semantics absent from FAVA frontmatter.
- Global decorative graph visualization.
- Unsupported relationship types that FAVA does not currently store.

## Further Notes

The authoritative FAVA decision for this work is the promoted rich-views thought `01KWEQ7DR51N5N6QE6XVCR1BST`. It supersedes the older PRD seed `01KWDKPYDGJW22JYWC7YJH5ZSX`.

The key boundary to preserve throughout implementation is:

Not a Markdown theme. A FAVA semantic renderer.

The first implementation should prove that FAVA-specific semantics can make existing trails glanceable before expanding into broader publishing, synthesis, or graph products.


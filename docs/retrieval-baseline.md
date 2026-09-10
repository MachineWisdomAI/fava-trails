# Retrieval baseline (lexical recall)

Shareable synthetic benchmark for the **implemented** `TrailManager.recall`
matcher. This is not a product claim about future search work (see
[issue #59](https://github.com/MachineWisdomAI/fava-trails/issues/59)).

## Matcher under test

Source of truth: `src/fava_trails/trail.py` (`TrailManager.recall`).

1. Lowercase the query string.
2. Split on whitespace into tokens (`str.split()`).
3. Build a searchable string from content + thought_id + source_type + agent_id
   + metadata project/branch/tags (all lowercased). **`metadata.extra` is not
   searched.**
4. Keep a record only when **every** query token is a **substring** of that
   searchable string (`all(word in searchable for word in query_words)`).
5. Empty query matches all visibility-allowed records (subject to `limit`).

This is **lexical substring AND**, not ranking, stemming, phrase search, or
semantic similarity. Punctuation attached to a query token is part of the token.
A shared filesystem / shared MCP endpoint is **one** identity and data boundary;
it does not cryptographically isolate concurrent callers.

## Visibility under test

| Mode | What appears |
| --- | --- |
| `governed` (default) | Approved records without an approved successor |
| `authoring` | Only the configured author's own draft/proposed records in selected scopes |
| `history` | Operator-selected lifecycle statuses; may include superseded |

Default `recall` does **not** surface another agent's unapproved drafts. Supplying
`agent_id` or a `drafts/` namespace does not bypass lifecycle or identity checks.
See [governed-recall.md](governed-recall.md).

## Trust Gate and supersession (limits)

- Trust Gate review is rubric-based LLM (or explicit human) **advisory process
  control**. It is not independent verification of project facts, safety policy,
  or the caller's system prompt.
- Supersession records lineage and hides predecessors from default governed
  recall after durable successor approval. It does **not** establish that the
  replacement is true.

## Tested version

| Field | Value |
| --- | --- |
| Product version | `0.6.1` (`pyproject.toml`) — **unreleased** release candidate on this tree / `main`; PyPI and GitHub Releases latest remain **0.6.0** |
| Git baseline (matrix authoring) | `54692dbaae7ca4fdcc80a4a8e26018411541207f` (PR #110 repair for review `5161963110` on `automation/fava-trails-100`). Prior SHA rows (`36d6bbb`, `10b937d`, `32b5b82`, `187f523`) are historical only. |
| Runner | `uv run pytest tests/test_retrieval_baseline.py -v` |
| Issue | [#100](https://github.com/MachineWisdomAI/fava-trails/issues/100) |

**How tests relate to this file:** `tests/test_retrieval_baseline.py` encodes the
same Expected/Actual sets **independently**. It does **not** parse this Markdown,
does **not** rewrite the table, and does **not** stamp a Git SHA. Documentation
drift is possible if only one side is updated — change the matrix and the tests
together. Fixture identifiers used in Expected/Actual columns live in
`metadata.extra.fixture` and are **outside** the lexical searchable string.

## Synthetic corpus

Stable fixture ids (matrix labels) are stored only in `metadata.extra.fixture`.
They are **not** written into searchable `tags`, `branch`, or body text.

| Fixture id | Content (abbreviated) | Searchable tags | Notes |
| --- | --- | --- | --- |
| `exact-jj` | `JJ colocated mode keeps a standard Git remote.` | (none) | Approved observation |
| `punct-api` | `Use the /v1/chat/completions endpoint for local models.` | (none) | Slash and dots in body |
| `short-ulid-tag` | `Short token probe.` | `ab`, `tok_x7k2m` | Short-token + unique-tag probes |
| `synonym-deploy` | `Production rollout uses blue-green deploys.` | (none) | "rollout" present; "release" absent |
| `paraphrase-model` | `ViT-Large outperforms ResNet-50 by 3% on this dataset.` | (none) | No phrase "model architecture decisions" |
| `noise-budget` | `Quarterly budget planning is deferred.` | (none) | Irrelevant distractor |
| `draft-private` | `Unapproved draft concerning secret migration plan.` | (none) | Draft; body avoids accidental `ab` via "about" |
| `superseded-old` | `ResNet-50 is optimal for this dataset.` | (none) | Approved, then superseded |
| *(successor)* | `ViT-Large is the current model choice for this dataset.` | (none) | Test dict key `superseder-new` is **not** a fixture id; `supersede` inherits predecessor `extra.fixture=superseded-old` |

## Results matrix

Legend: **hit** = listed fixture ids present; **miss** = empty fixture-id set;
**complete actual** = full fixture-id set returned (not a subset check).
"Expected" is the behavior of the current matcher, not a wishlist. Cells list
**complete** fixture-id sets under the stated mode.

| Case | Query | Mode / filters | Expected (complete fixture ids) | Actual (0.6.1 matcher) | Notes |
| --- | --- | --- | --- | --- | --- |
| Exact token | `colocated` | governed | `{exact-jj}` | `{exact-jj}` | Baseline true positive |
| Multi-token AND | `JJ Git` | governed | `{exact-jj}` | `{exact-jj}` | Non-contiguous tokens OK |
| Irrelevant | `budget` | governed | `{noise-budget}` | `{noise-budget}` | Body hit only; fixture id not searchable |
| Short token | `ab` | governed | `{short-ulid-tag}` | `{short-ulid-tag}` | Real length-2 tag probe; complete set recorded |
| Unique tag token | `tok_x7k2m` | governed | `{short-ulid-tag}` | `{short-ulid-tag}` | Longer unique tag; precision case |
| Punctuation in body | `/v1/chat/completions` | governed | `{punct-api}` | `{punct-api}` | Whole token must appear including `/` |
| Punctuation variant | `v1 chat completions` | governed | `{punct-api}` | `{punct-api}` | Whitespace-split tokens still substrings of body |
| Synonym miss | `release` | governed | `∅` | `∅` | No synonym expansion |
| Paraphrase miss | `model architecture decisions` | governed | `∅` | `∅` | Reported user-shaped failure mode |
| Partial synonym | `deploy` | governed | `{synonym-deploy}` | `{synonym-deploy}` | Shared stem/substring in body only |
| Draft hidden (governed) | `secret migration` | governed | `∅` | `∅` | Complete empty set; unapproved drafts not in default view |
| Own draft (authoring) | `secret migration` | authoring, matching agent | `{draft-private}` | `{draft-private}` | Explicit authoring only |
| Other draft blocked | `secret migration` | authoring, other agent | `∅` | `∅` | Complete empty set; no cross-agent draft read |
| Superseded hidden | `ResNet-50 is optimal` | governed | `∅` | `∅` | Complete empty set; default hides predecessor |
| Superseded visible | `ResNet-50 is optimal` | history + include_superseded | `{superseded-old}` | `{superseded-old}` | Complete set only; operator archaeology |

## Measured misses to feed discovery (#59)

These are **real caller needs** the lexical matcher does not satisfy. They are
inputs to Lima Discovery on #59 — **not** a selection of embeddings, a vector
database, or a retrieval architecture:

1. **Paraphrase recall** — operators remember the topic ("model architecture
   decisions") rather than tokens stored in the body.
2. **Synonym / vocabulary drift** — "release" vs "rollout" / "deploy".
3. **Short-token breadth** — length-2 substrings such as `ab` are easy to over-match
   when identifiers or common words land in searchable fields. This baseline keeps
   fixture ids out of searchable fields and records the intentional `{short-ulid-tag}`
   hit for tag `ab`; treat other short-token collisions as a discovery input, not a
   precision guarantee.
4. **Punctuation-sensitive tokens** — callers may omit path slashes or dots and
   still expect a hit (sometimes works when pieces remain substrings; not a
   contract).
5. **Visibility education** — callers expect drafts or foreign authoring records
   to appear under default `recall`; governed mode correctly refuses.

## Non-goals of this baseline

- Choosing Pagefind, SQLite FTS5, embeddings, or any index product.
- Changing matcher behavior in the same change set as documentation correction.
- Claiming hallucination prevention or factual correctness from Trust Gate.

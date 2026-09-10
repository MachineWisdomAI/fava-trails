# Retrieval baseline (lexical recall)

Shareable synthetic benchmark for the **implemented** `TrailManager.recall`
matcher. This is not a product claim about future search work (see
[issue #59](https://github.com/MachineWisdomAI/fava-trails/issues/59)).

## Matcher under test

Source of truth: `src/fava_trails/trail.py` (`TrailManager.recall`).

1. Lowercase the query string.
2. Split on whitespace into tokens (`str.split()`).
3. Build a searchable string from content + thought_id + source_type + agent_id
   + metadata project/branch/tags (all lowercased).
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
| Git baseline (matrix authoring) | `36d6bbbee669891e4b6f5310a0eb991fe043e3df` (PR #110 / issue #100 branch head when the Expected/Actual columns were written) |
| Runner | `uv run pytest tests/test_retrieval_baseline.py -v` |
| Issue | [#100](https://github.com/MachineWisdomAI/fava-trails/issues/100) |

`tests/test_retrieval_baseline.py` **validates** the static Expected/Actual matrix against the live matcher; it does **not** rewrite this Markdown file, does **not** stamp a Git SHA into the doc, and does **not** refresh the Actual column at run time. If matcher behavior changes, update both the table and the tests in the same change.

## Synthetic corpus

Stable fixture labels (not ULIDs) used in expected/actual columns:

| Label | Content (abbreviated) | Notes |
| --- | --- | --- |
| `exact-jj` | `JJ colocated mode keeps a standard Git remote.` | Approved observation |
| `punct-api` | `Use the /v1/chat/completions endpoint for local models.` | Slash and dots in body |
| `short-ulid-tag` | `Short token probe.` tags=`["tok_x7k2m"]` | Unique short tag (not a substring of other fixtures' `label:` tags) |
| `synonym-deploy` | `Production rollout uses blue-green deploys.` | "rollout" present; "release" absent |
| `paraphrase-model` | `ViT-Large outperforms ResNet-50 by 3% on this dataset.` | No phrase "model architecture decisions" |
| `noise-budget` | `Quarterly budget planning is deferred.` | Irrelevant distractor |
| `draft-private` | `Unapproved draft about secret migration plan.` | Draft; same author vs other author cases |
| `superseded-old` | `ResNet-50 is optimal for this dataset.` | Approved, then superseded |
| *(successor)* | `ViT-Large is the current model choice for this dataset.` | Fixture dict key `superseder-new` is **not** a persisted `label:` tag; `supersede` inherits predecessor tags, so the successor still carries `label:superseded-old` |

## Results matrix

Legend: **hit** = labeled record present in results; **miss** = absent;
**empty** = zero results. "Expected" is the behavior of the current matcher, not
a wishlist.

| Case | Query | Mode / filters | Expected | Actual (0.6.1 matcher) | Notes |
| --- | --- | --- | --- | --- | --- |
| Exact token | `colocated` | governed | hit `exact-jj` | hit `exact-jj` | Baseline true positive |
| Multi-token AND | `JJ Git` | governed | hit `exact-jj` | hit `exact-jj` | Non-contiguous tokens OK |
| Irrelevant | `budget` | governed | hit only `noise-budget` | hit only `noise-budget` | No false friends from other rows |
| Short unique tag token | `tok_x7k2m` | governed | hit only `short-ulid-tag` | hit only `short-ulid-tag` | Tag is unique to that fixture; full actual label set is `{short-ulid-tag}` (not a subset check). Length-2 tokens like `ab` would match every `label:` string and are a measured miss mode |
| Punctuation in body | `/v1/chat/completions` | governed | hit `punct-api` | hit `punct-api` | Whole token must appear including `/` |
| Punctuation variant | `v1 chat completions` | governed | hit `punct-api` | hit `punct-api` | Whitespace-split tokens still substrings of body |
| Synonym miss | `release` | governed | miss `synonym-deploy` | miss `synonym-deploy` | No synonym expansion |
| Paraphrase miss | `model architecture decisions` | governed | miss `paraphrase-model` | miss `paraphrase-model` | Reported user-shaped failure mode |
| Partial synonym | `deploy` | governed | hit `synonym-deploy` | hit `synonym-deploy` | Shared stem/substring only |
| Draft hidden (governed) | `secret migration` | governed | miss `draft-private` | miss `draft-private` | Unapproved drafts not in default view |
| Own draft (authoring) | `secret migration` | authoring, matching agent | hit `draft-private` | hit `draft-private` | Explicit authoring only |
| Other draft blocked | `secret migration` | authoring, other agent | miss `draft-private` | miss `draft-private` | No cross-agent draft read |
| Superseded hidden | `ResNet-50 is optimal` | governed | miss old / may hit new if tokens remain | miss `superseded-old` | Default hides predecessor |
| Superseded visible | `ResNet-50 is optimal` | history + include_superseded | hit `superseded-old` | hit `superseded-old` | Operator archaeology |

## Measured misses to feed discovery (#59)

These are **real caller needs** the lexical matcher does not satisfy. They are
inputs to Lima Discovery on #59 — **not** a selection of embeddings, a vector
database, or a retrieval architecture:

1. **Paraphrase recall** — operators remember the topic ("model architecture
   decisions") rather than tokens stored in the body.
2. **Synonym / vocabulary drift** — "release" vs "rollout" / "deploy".
3. **Short-token ambiguity** — length-2 substrings such as `ab` match every fixture that carries a `label:` tag (because `ab` is a substring of `label:`), so they cannot isolate one metadata field. Prefer longer unique tokens; treat broad short-token hits as a discovery input, not a precision guarantee.
4. **Punctuation-sensitive tokens** — callers may omit path slashes or dots and
   still expect a hit (sometimes works when pieces remain substrings; not a
   contract).
5. **Visibility education** — callers expect drafts or foreign authoring records
   to appear under default `recall`; governed mode correctly refuses.

## Non-goals of this baseline

- Choosing Pagefind, SQLite FTS5, embeddings, or any index product.
- Changing matcher behavior in the same change set as documentation correction.
- Claiming hallucination prevention or factual correctness from Trust Gate.

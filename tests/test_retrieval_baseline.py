"""Synthetic lexical-recall baseline for docs/retrieval-baseline.md (issue #100).

Holds independent Expected/Actual expectations that must stay aligned with the
static matrix in the Markdown doc. Does not parse or rewrite that doc, does not
stamp a Git SHA, and does not select a future retrieval architecture (see #59).
"""

from __future__ import annotations

import itertools
from importlib.metadata import PackageNotFoundError, version

import pytest

from fava_trails.governance import Principal, Visibility
from fava_trails.models import SourceType
from fava_trails.trust_gate import TrustResult

PRODUCT_VERSION = "0.6.1"

# Stable fixture ids for matrix rows. Stored only in metadata.extra (not searchable).
FIXTURE_EXACT = "exact-jj"
FIXTURE_PUNCT = "punct-api"
FIXTURE_SHORT = "short-ulid-tag"
FIXTURE_SYNONYM = "synonym-deploy"
FIXTURE_PARAPHRASE = "paraphrase-model"
FIXTURE_NOISE = "noise-budget"
FIXTURE_DRAFT = "draft-private"
FIXTURE_SUPERSEDED = "superseded-old"
# Dict-only key for the successor thought_id; not a persisted fixture id.
KEY_SUCCESSOR = "superseder-new"


def _approval() -> TrustResult:
    return TrustResult(verdict="approve", reasoning="baseline fixture", reviewer="fixture")


def _fixture_labels(results) -> set[str]:
    """Return fixture ids from metadata.extra only (never from searchable tags)."""
    out: set[str] = set()
    for record in results:
        extra = record.frontmatter.metadata.extra or {}
        fid = extra.get("fixture")
        if isinstance(fid, str) and fid:
            out.add(fid)
    return out


async def _promote(manager, record):
    return await manager.propose_truth(record.thought_id, _approval())


@pytest.fixture
async def baseline_corpus(tmp_fava_home, monkeypatch):
    """Build the shareable synthetic corpus described in docs/retrieval-baseline.md."""
    # Pin thought_ids so short-token queries cannot flaky-match random ULID substrings.
    seq = itertools.count(1)

    class _StableULID:
        def __str__(self) -> str:
            # Crockford-ish digits only; deliberately avoids the substring "ab".
            return f"01FIX{next(seq):022d}"

    monkeypatch.setattr("fava_trails.models.ULID", _StableULID)

    from fava_trails.trail import TrailManager
    from fava_trails.vcs.jj_backend import JjBackend

    path = tmp_fava_home / "trails" / "baseline" / "retrieval"
    backend = JjBackend(repo_root=tmp_fava_home, trail_path=path)
    manager = TrailManager("baseline/retrieval", vcs=backend)
    await manager.init()

    async def save(
        content: str,
        fixture: str,
        *,
        agent_id: str = "agent-a",
        tags=None,
        source_type=SourceType.OBSERVATION,
    ):
        # Fixture ids live only in metadata.extra (excluded from lexical searchable text).
        # Searchable tags are intentional probe tokens only — never "label:<fixture>".
        return await manager.save_thought(
            content=content,
            agent_id=agent_id,
            source_type=source_type,
            metadata={
                "project": "retrieval-baseline",
                "tags": list(tags or []),
                "extra": {"fixture": fixture},
            },
        )

    exact = await save("JJ colocated mode keeps a standard Git remote.", FIXTURE_EXACT)
    punct = await save("Use the /v1/chat/completions endpoint for local models.", FIXTURE_PUNCT)
    # Real short-token probe: tag "ab" is searchable; fixture id is not.
    short = await save("Short token probe.", FIXTURE_SHORT, tags=["ab", "tok_x7k2m"])
    synonym = await save("Production rollout uses blue-green deploys.", FIXTURE_SYNONYM)
    paraphrase = await save(
        "ViT-Large outperforms ResNet-50 by 3% on this dataset.",
        FIXTURE_PARAPHRASE,
    )
    noise = await save("Quarterly budget planning is deferred.", FIXTURE_NOISE)
    # Avoid the substring "ab" in draft body ("about") so short-token results stay intentional.
    draft = await save(
        "Unapproved draft concerning secret migration plan.",
        FIXTURE_DRAFT,
        agent_id="agent-a",
    )

    for record in (exact, punct, short, synonym, paraphrase, noise):
        await _promote(manager, record)

    old = await save("ResNet-50 is optimal for this dataset.", FIXTURE_SUPERSEDED)
    await _promote(manager, old)
    # supersede copies predecessor metadata (including extra.fixture=superseded-old).
    # KEY_SUCCESSOR is only the fixture dict key for the successor thought_id.
    new = await manager.supersede(
        old.thought_id,
        "ViT-Large is the current model choice for this dataset.",
        reason="benchmark corrected the earlier claim",
        agent_id="agent-a",
        confidence=0.9,
    )
    await _promote(manager, new)

    return {
        "manager": manager,
        "draft_id": draft.thought_id,
        "old_id": old.thought_id,
        "new_id": new.thought_id,
        "ids": {
            FIXTURE_EXACT: exact.thought_id,
            FIXTURE_PUNCT: punct.thought_id,
            FIXTURE_SHORT: short.thought_id,
            FIXTURE_SYNONYM: synonym.thought_id,
            FIXTURE_PARAPHRASE: paraphrase.thought_id,
            FIXTURE_NOISE: noise.thought_id,
            FIXTURE_DRAFT: draft.thought_id,
            FIXTURE_SUPERSEDED: old.thought_id,
            KEY_SUCCESSOR: new.thought_id,  # dict key only; not a fixture id
        },
    }


def test_documented_product_version_matches_package():
    """Baseline doc pins 0.6.1; fail if package metadata drifts without doc update."""
    try:
        installed = version("fava-trails")
    except PackageNotFoundError:
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        installed = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert installed == PRODUCT_VERSION


@pytest.mark.asyncio
async def test_baseline_exact_and_multi_token(baseline_corpus):
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")

    exact = await manager.recall(query="colocated", visibility=governed)
    assert _fixture_labels(exact) == {FIXTURE_EXACT}

    multi = await manager.recall(query="JJ Git", visibility=governed)
    assert _fixture_labels(multi) == {FIXTURE_EXACT}


@pytest.mark.asyncio
async def test_baseline_irrelevant_budget(baseline_corpus):
    """Query 'budget' must hit body text only — fixture ids are not searchable."""
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")

    budget = await manager.recall(query="budget", visibility=governed)
    assert _fixture_labels(budget) == {FIXTURE_NOISE}
    assert {r.thought_id for r in budget} == {baseline_corpus["ids"][FIXTURE_NOISE]}


@pytest.mark.asyncio
async def test_baseline_short_token_ab_and_unique_tag(baseline_corpus):
    """Short token 'ab' is a real substring probe; unique tag remains a precision case."""
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")

    short = await manager.recall(query="ab", visibility=governed)
    # Under governed visibility the only intentional hit is the fixture tagged "ab".
    # Complete actual set (fixture ids): {short-ulid-tag}
    assert _fixture_labels(short) == {FIXTURE_SHORT}
    assert {r.thought_id for r in short} == {baseline_corpus["ids"][FIXTURE_SHORT]}

    unique = await manager.recall(query="tok_x7k2m", visibility=governed)
    assert _fixture_labels(unique) == {FIXTURE_SHORT}
    assert {r.thought_id for r in unique} == {baseline_corpus["ids"][FIXTURE_SHORT]}


@pytest.mark.asyncio
async def test_baseline_punctuation_variants(baseline_corpus):
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")

    with_slash = await manager.recall(query="/v1/chat/completions", visibility=governed)
    assert _fixture_labels(with_slash) == {FIXTURE_PUNCT}

    split = await manager.recall(query="v1 chat completions", visibility=governed)
    assert _fixture_labels(split) == {FIXTURE_PUNCT}


@pytest.mark.asyncio
async def test_baseline_synonym_and_paraphrase_misses(baseline_corpus):
    """Documented misses: no synonym expansion; paraphrases without shared tokens fail."""
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")

    synonym = await manager.recall(query="release", visibility=governed)
    assert _fixture_labels(synonym) == set()

    paraphrase = await manager.recall(query="model architecture decisions", visibility=governed)
    assert _fixture_labels(paraphrase) == set()

    partial = await manager.recall(query="deploy", visibility=governed)
    # Body substring in "deploys" only — not via a searchable fixture label.
    assert _fixture_labels(partial) == {FIXTURE_SYNONYM}
    assert {r.thought_id for r in partial} == {baseline_corpus["ids"][FIXTURE_SYNONYM]}


@pytest.mark.asyncio
async def test_baseline_visibility_boundaries(baseline_corpus):
    manager = baseline_corpus["manager"]
    draft_id = baseline_corpus["draft_id"]
    old_id = baseline_corpus["old_id"]

    governed = Visibility(mode="governed")
    # Complete actual sets (not mere non-membership): both hidden queries return ∅.
    hidden = await manager.recall(query="secret migration", visibility=governed)
    assert _fixture_labels(hidden) == set()
    assert {r.thought_id for r in hidden} == set()

    own = Visibility(mode="authoring", principal=Principal(agent_id="agent-a"))
    own_hits = await manager.recall(query="secret migration", visibility=own)
    assert _fixture_labels(own_hits) == {FIXTURE_DRAFT}
    assert {r.thought_id for r in own_hits} == {draft_id}

    other = Visibility(mode="authoring", principal=Principal(agent_id="agent-b"))
    other_hits = await manager.recall(query="secret migration", visibility=other)
    assert _fixture_labels(other_hits) == set()
    assert {r.thought_id for r in other_hits} == set()

    governed_old = await manager.recall(query="ResNet-50 is optimal", visibility=governed)
    assert _fixture_labels(governed_old) == set()
    assert {r.thought_id for r in governed_old} == set()

    history = Visibility(
        mode="history",
        principal=Principal(operator=True),
        include_superseded=True,
    )
    hist = await manager.recall(query="ResNet-50 is optimal", visibility=history)
    # Complete actual set under history + include_superseded: exactly the predecessor.
    assert _fixture_labels(hist) == {FIXTURE_SUPERSEDED}
    assert {r.thought_id for r in hist} == {old_id}


@pytest.mark.asyncio
async def test_baseline_fixture_ids_cover_shareable_matrix(baseline_corpus):
    """Sanity: every matrix fixture id is present on corpus records via extra only."""
    manager = baseline_corpus["manager"]
    history = Visibility(
        mode="history",
        principal=Principal(operator=True),
        include_superseded=True,
    )
    results = await manager.recall(query="", visibility=history, limit=50)
    labels = _fixture_labels(results)
    for required in {
        FIXTURE_EXACT,
        FIXTURE_PUNCT,
        FIXTURE_SHORT,
        FIXTURE_SYNONYM,
        FIXTURE_PARAPHRASE,
        FIXTURE_NOISE,
        FIXTURE_DRAFT,
        FIXTURE_SUPERSEDED,
    }:
        assert required in labels, f"missing corpus fixture id {required}"
    assert baseline_corpus["ids"][KEY_SUCCESSOR] in {r.thought_id for r in results}
    # Successor inherits predecessor extra.fixture; no distinct superseder-new fixture id.
    successor = next(r for r in results if r.thought_id == baseline_corpus["ids"][KEY_SUCCESSOR])
    assert (successor.frontmatter.metadata.extra or {}).get("fixture") == FIXTURE_SUPERSEDED

"""Synthetic lexical-recall baseline for docs/retrieval-baseline.md (issue #100).

Validates the static Expected/Actual matrix in the Markdown doc against the
shipped substring-AND matcher. Does not rewrite the doc, stamp a Git SHA, or
select a future retrieval architecture (see issue #59).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import pytest

from fava_trails.governance import Principal, Visibility
from fava_trails.models import SourceType
from fava_trails.trust_gate import TrustResult

PRODUCT_VERSION = "0.6.1"


def _approval() -> TrustResult:
    return TrustResult(verdict="approve", reasoning="baseline fixture", reviewer="fixture")


def _labels(results) -> set[str]:
    out: set[str] = set()
    for record in results:
        tags = record.frontmatter.metadata.tags or []
        for tag in tags:
            if tag.startswith("label:"):
                out.add(tag.removeprefix("label:"))
    return out


async def _promote(manager, record):
    return await manager.propose_truth(record.thought_id, _approval())


@pytest.fixture
async def baseline_corpus(tmp_fava_home):
    """Build the shareable synthetic corpus described in docs/retrieval-baseline.md."""
    from fava_trails.trail import TrailManager
    from fava_trails.vcs.jj_backend import JjBackend

    path = tmp_fava_home / "trails" / "baseline" / "retrieval"
    backend = JjBackend(repo_root=tmp_fava_home, trail_path=path)
    manager = TrailManager("baseline/retrieval", vcs=backend)
    await manager.init()

    async def save(
        content: str,
        label: str,
        *,
        agent_id: str = "agent-a",
        tags=None,
        source_type=SourceType.OBSERVATION,
    ):
        meta_tags = [f"label:{label}", *(tags or [])]
        return await manager.save_thought(
            content=content,
            agent_id=agent_id,
            source_type=source_type,
            metadata={"project": "retrieval-baseline", "tags": meta_tags},
        )

    exact = await save("JJ colocated mode keeps a standard Git remote.", "exact-jj")
    punct = await save("Use the /v1/chat/completions endpoint for local models.", "punct-api")
    short = await save(
        "Short token probe.",
        "short-ulid-tag",
        tags=["tok_x7k2m"],
    )
    synonym = await save("Production rollout uses blue-green deploys.", "synonym-deploy")
    paraphrase = await save(
        "ViT-Large outperforms ResNet-50 by 3% on this dataset.",
        "paraphrase-model",
    )
    noise = await save("Quarterly budget planning is deferred.", "noise-budget")
    draft = await save(
        "Unapproved draft about secret migration plan.",
        "draft-private",
        agent_id="agent-a",
    )

    for record in (exact, punct, short, synonym, paraphrase, noise):
        await _promote(manager, record)

    old = await save("ResNet-50 is optimal for this dataset.", "superseded-old")
    await _promote(manager, old)
    # supersede keeps predecessor metadata tags; successor still has label:superseded-old.
    # "superseder-new" is only the fixture dict key for the successor thought_id.
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
            "exact-jj": exact.thought_id,
            "punct-api": punct.thought_id,
            "short-ulid-tag": short.thought_id,
            "synonym-deploy": synonym.thought_id,
            "paraphrase-model": paraphrase.thought_id,
            "noise-budget": noise.thought_id,
            "draft-private": draft.thought_id,
            "superseded-old": old.thought_id,
            "superseder-new": new.thought_id,  # dict key only; not a label: tag
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
    assert baseline_corpus["ids"]["exact-jj"] in {r.thought_id for r in exact}

    multi = await manager.recall(query="JJ Git", visibility=governed)
    assert baseline_corpus["ids"]["exact-jj"] in {r.thought_id for r in multi}


@pytest.mark.asyncio
async def test_baseline_irrelevant_and_short_tag(baseline_corpus):
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")

    budget = await manager.recall(query="budget", visibility=governed)
    ids = {r.thought_id for r in budget}
    assert ids == {baseline_corpus["ids"]["noise-budget"]}

    short = await manager.recall(query="tok_x7k2m", visibility=governed)
    assert _labels(short) == {"short-ulid-tag"}
    assert {r.thought_id for r in short} == {baseline_corpus["ids"]["short-ulid-tag"]}


@pytest.mark.asyncio
async def test_baseline_punctuation_variants(baseline_corpus):
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")
    target = baseline_corpus["ids"]["punct-api"]

    with_slash = await manager.recall(query="/v1/chat/completions", visibility=governed)
    assert target in {r.thought_id for r in with_slash}

    split = await manager.recall(query="v1 chat completions", visibility=governed)
    assert target in {r.thought_id for r in split}


@pytest.mark.asyncio
async def test_baseline_synonym_and_paraphrase_misses(baseline_corpus):
    """Documented misses: no synonym expansion; paraphrases without shared tokens fail."""
    manager = baseline_corpus["manager"]
    governed = Visibility(mode="governed")

    synonym = await manager.recall(query="release", visibility=governed)
    assert baseline_corpus["ids"]["synonym-deploy"] not in {r.thought_id for r in synonym}

    paraphrase = await manager.recall(query="model architecture decisions", visibility=governed)
    assert baseline_corpus["ids"]["paraphrase-model"] not in {r.thought_id for r in paraphrase}

    partial = await manager.recall(query="deploy", visibility=governed)
    assert baseline_corpus["ids"]["synonym-deploy"] in {r.thought_id for r in partial}


@pytest.mark.asyncio
async def test_baseline_visibility_boundaries(baseline_corpus):
    manager = baseline_corpus["manager"]
    draft_id = baseline_corpus["draft_id"]
    old_id = baseline_corpus["old_id"]

    governed = Visibility(mode="governed")
    hidden = await manager.recall(query="secret migration", visibility=governed)
    assert draft_id not in {r.thought_id for r in hidden}

    own = Visibility(mode="authoring", principal=Principal(agent_id="agent-a"))
    own_hits = await manager.recall(query="secret migration", visibility=own)
    assert draft_id in {r.thought_id for r in own_hits}

    other = Visibility(mode="authoring", principal=Principal(agent_id="agent-b"))
    other_hits = await manager.recall(query="secret migration", visibility=other)
    assert draft_id not in {r.thought_id for r in other_hits}

    governed_old = await manager.recall(query="ResNet-50 is optimal", visibility=governed)
    assert old_id not in {r.thought_id for r in governed_old}

    history = Visibility(
        mode="history",
        principal=Principal(operator=True),
        include_superseded=True,
    )
    hist = await manager.recall(query="ResNet-50 is optimal", visibility=history)
    assert old_id in {r.thought_id for r in hist}


@pytest.mark.asyncio
async def test_baseline_labels_cover_shareable_matrix(baseline_corpus):
    """Sanity: promoted corpus labels are recoverable via tag tokens for the doc matrix."""
    manager = baseline_corpus["manager"]
    history = Visibility(
        mode="history",
        principal=Principal(operator=True),
        include_superseded=True,
    )
    results = await manager.recall(query="", visibility=history, limit=50)
    labels = _labels(results)
    for required in {
        "exact-jj",
        "punct-api",
        "short-ulid-tag",
        "synonym-deploy",
        "paraphrase-model",
        "noise-budget",
        "draft-private",
        "superseded-old",
    }:
        assert required in labels, f"missing corpus label {required}"
    assert baseline_corpus["ids"]["superseder-new"] in {r.thought_id for r in results}

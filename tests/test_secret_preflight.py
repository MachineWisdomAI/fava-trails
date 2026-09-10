"""Bounded obvious-secret preflight: block persist and transmit without echoing secrets."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fava_trails.models import (
    SourceType,
    ThoughtFrontmatter,
    ThoughtMetadata,
    ThoughtRecord,
    ValidationStatus,
)
from fava_trails.secret_preflight import (
    ObviousSecretError,
    find_obvious_secret,
    find_obvious_secret_in_value,
    refuse_obvious_secret,
)
from fava_trails.trust_gate import TrustGatePromptCache, TrustResult

# Synthetic canaries — not real credentials. Shapes match supported high-confidence patterns.
AWS_CANARY = "AKIA" + "TESTFAKE0CANARY1"
GITHUB_CANARY = "ghp_" + ("A" * 36)
OPENROUTER_CANARY = "sk-or-v1-" + ("a" * 64)
OPENAI_CANARY = "sk-" + ("b" * 48)
STRIPE_CANARY = "sk_live_" + ("c" * 24)
SLACK_CANARY = "xoxb-1234567890-" + ("d" * 24)
PEM_CANARY = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIFakeCanaryMaterial\n-----END RSA PRIVATE KEY-----"


def _assert_canary_absent(root: Path, canary: str) -> None:
    needle = canary.encode()
    hits = [str(path) for path in root.rglob("*") if path.is_file() and needle in path.read_bytes()]
    assert hits == [], f"canary leaked into {hits}"


def _assert_canary_absent_from_tree(root: Path, canary: str) -> None:
    path_hits = [str(path) for path in root.rglob("*") if canary in str(path)]
    assert path_hits == [], f"canary leaked into paths {path_hits}"
    _assert_canary_absent(root, canary)


def test_finds_supported_high_confidence_patterns():
    cases = {
        "aws_access_key_id": f"token {AWS_CANARY} here",
        "github_pat": f"auth {GITHUB_CANARY}",
        "openrouter_api_key": OPENROUTER_CANARY,
        "openai_api_key": OPENAI_CANARY,
        "stripe_live_key": STRIPE_CANARY,
        "slack_token": SLACK_CANARY,
        "pem_private_key": PEM_CANARY,
    }
    for pattern_id, text in cases.items():
        assert find_obvious_secret(text) == pattern_id


def test_finds_secret_in_nested_metadata_and_relationships():
    assert (
        find_obvious_secret_in_value(
            {"content": "benign body", "metadata": {"project": AWS_CANARY}}
        )
        == "aws_access_key_id"
    )
    assert (
        find_obvious_secret_in_value({"extra": {"runtime": {"token": GITHUB_CANARY}}})
        == "github_pat"
    )
    assert (
        find_obvious_secret_in_value(
            {"relationships": [{"type": "REFERENCES", "target_id": OPENAI_CANARY}]}
        )
        == "openai_api_key"
    )
    assert find_obvious_secret_in_value({"project": "fava-trails", "tags": ["gotcha"]}) is None


def test_benign_technical_content_is_not_a_match():
    samples = [
        "Use bcrypt for password hashing; never store plaintext passwords.",
        "Set OPENROUTER_API_KEY in the environment, not in thought bodies.",
        'Example placeholder: "sk-or-v1-..."',
        "IAM access keys use an AKIA-style prefix; rotate them in the console.",
        "JWT compact serialization has three base64url segments.",
        "trust_gate_api_key_file: /private/runtime/api-key",
        "The fake-password review was a gate verdict, not proof of non-persistence.",
    ]
    for text in samples:
        assert find_obvious_secret(text) is None


def test_refuse_does_not_echo_the_secret():
    with pytest.raises(ObviousSecretError) as exc_info:
        refuse_obvious_secret(f"leaked {GITHUB_CANARY}")
    message = str(exc_info.value)
    assert GITHUB_CANARY not in message
    assert "github_pat" in message
    assert "not complete DLP" in message
    assert "not erased" in message


def test_legacy_message_explains_existing_persistence_is_kept():
    with pytest.raises(ObviousSecretError) as exc_info:
        refuse_obvious_secret(f"legacy {AWS_CANARY}", persisted_already=True)
    message = str(exc_info.value)
    assert AWS_CANARY not in message
    assert "left unchanged" in message
    assert "not erased" in message


@pytest.mark.asyncio
async def test_save_thought_blocks_before_files_history_or_logs(trail_manager, tmp_fava_home, caplog):
    caplog.set_level("DEBUG")
    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.save_thought(content=f"draft {GITHUB_CANARY}", agent_id="test-agent")
    assert GITHUB_CANARY not in str(exc_info.value)
    _assert_canary_absent(tmp_fava_home, GITHUB_CANARY)
    assert GITHUB_CANARY not in caplog.text
    assert list((trail_manager.trail_path / "thoughts").rglob("*.md")) == []


@pytest.mark.asyncio
async def test_update_and_supersede_block_new_secret_input(trail_manager, tmp_fava_home, caplog):
    caplog.set_level("DEBUG")
    record = await trail_manager.save_thought(content="benign draft", agent_id="test-agent")
    with pytest.raises(ObviousSecretError):
        await trail_manager.update_thought(record.thought_id, f"updated {OPENAI_CANARY}")
    with pytest.raises(ObviousSecretError):
        await trail_manager.supersede(
            record.thought_id,
            f"replacement {STRIPE_CANARY}",
            reason=f"because {SLACK_CANARY}",
            agent_id="test-agent",
        )
    retrieved = await trail_manager.get_thought(record.thought_id)
    assert retrieved is not None
    assert retrieved.content == "benign draft"
    _assert_canary_absent(tmp_fava_home, OPENAI_CANARY)
    _assert_canary_absent(tmp_fava_home, STRIPE_CANARY)
    _assert_canary_absent(tmp_fava_home, SLACK_CANARY)
    assert OPENAI_CANARY not in caplog.text
    assert STRIPE_CANARY not in caplog.text
    assert SLACK_CANARY not in caplog.text


@pytest.mark.asyncio
async def test_save_thought_allows_ordinary_technical_content(trail_manager):
    record = await trail_manager.save_thought(
        content="Use bcrypt for password hashing. Configure OPENROUTER_API_KEY via env.",
        agent_id="test-agent",
    )
    retrieved = await trail_manager.get_thought(record.thought_id)
    assert retrieved is not None
    assert "bcrypt" in retrieved.content


async def _plant_legacy_draft(
    trail_manager, content: str, metadata: dict | None = None
) -> ThoughtRecord:
    record = ThoughtRecord(
        frontmatter=ThoughtFrontmatter(
            agent_id="legacy-agent",
            source_type=SourceType.OBSERVATION,
            metadata=ThoughtMetadata.model_validate(metadata or {}),
        ),
        content=content,
    )
    path = trail_manager.trail_path / "thoughts" / "drafts" / f"{record.thought_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.to_markdown())
    await trail_manager.vcs.commit_files(
        f"Plant legacy draft {record.thought_id[:8]}",
        [str(path)],
    )
    return record


@pytest.mark.asyncio
async def test_propose_truth_blocks_legacy_secret_without_copy_or_erase(trail_manager, tmp_fava_home):
    planted = await _plant_legacy_draft(trail_manager, f"already stored {PEM_CANARY}")
    drafts = trail_manager.trail_path / "thoughts" / "drafts" / f"{planted.thought_id}.md"
    before = drafts.read_text()

    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.propose_truth(planted.thought_id)
    assert planted.thought_id in str(exc_info.value) or "left unchanged" in str(exc_info.value)
    assert PEM_CANARY not in str(exc_info.value)
    assert drafts.read_text() == before
    observations = trail_manager.trail_path / "thoughts" / "observations"
    if observations.exists():
        assert list(observations.rglob("*.md")) == []
    still = await trail_manager.get_thought(planted.thought_id)
    assert still is not None
    assert PEM_CANARY in still.content


@pytest.mark.asyncio
async def test_handle_propose_truth_does_not_call_model_for_legacy_secret(
    trail_manager, tmp_fava_home, caplog
):
    from fava_trails.tools.navigation import handle_propose_truth

    caplog.set_level("DEBUG")
    planted = await _plant_legacy_draft(trail_manager, f"legacy transmit {OPENROUTER_CANARY}")
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."
    review = AsyncMock(return_value=TrustResult(verdict="reject", reasoning="secret", reviewer="llm"))

    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-test-key"}),
        patch("fava_trails.tools.navigation.review_thought", review),
    ):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": planted.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "error"
    assert OPENROUTER_CANARY not in result["message"]
    assert "not complete DLP" in result["message"]
    assert "left unchanged" in result["message"]
    review.assert_not_called()
    assert OPENROUTER_CANARY not in caplog.text
    observations = trail_manager.trail_path / "thoughts" / "observations"
    if observations.exists():
        assert list(observations.rglob("*.md")) == []


@pytest.mark.asyncio
async def test_save_thought_blocks_secret_in_metadata_project(trail_manager, tmp_fava_home, caplog):
    caplog.set_level("DEBUG")
    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.save_thought(
            content="benign draft body",
            agent_id="test-agent",
            metadata={"project": AWS_CANARY},
        )
    assert AWS_CANARY not in str(exc_info.value)
    assert "aws_access_key_id" in str(exc_info.value)
    _assert_canary_absent(tmp_fava_home, AWS_CANARY)
    assert AWS_CANARY not in caplog.text
    assert list((trail_manager.trail_path / "thoughts").rglob("*.md")) == []


@pytest.mark.asyncio
async def test_save_thought_blocks_secret_in_nested_metadata_extra(
    trail_manager, tmp_fava_home, caplog
):
    caplog.set_level("DEBUG")
    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.save_thought(
            content="benign draft body",
            agent_id="test-agent",
            metadata={"extra": {"runtime": {"token": GITHUB_CANARY}}},
        )
    assert GITHUB_CANARY not in str(exc_info.value)
    _assert_canary_absent(tmp_fava_home, GITHUB_CANARY)
    assert GITHUB_CANARY not in caplog.text
    assert list((trail_manager.trail_path / "thoughts").rglob("*.md")) == []


@pytest.mark.asyncio
async def test_propose_truth_blocks_legacy_metadata_secret_without_copy_or_erase(
    trail_manager, tmp_fava_home
):
    planted = await _plant_legacy_draft(
        trail_manager, "benign body", metadata={"project": AWS_CANARY}
    )
    drafts = trail_manager.trail_path / "thoughts" / "drafts" / f"{planted.thought_id}.md"
    before = drafts.read_text()

    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.propose_truth(planted.thought_id)
    assert "left unchanged" in str(exc_info.value)
    assert AWS_CANARY not in str(exc_info.value)
    assert drafts.read_text() == before
    observations = trail_manager.trail_path / "thoughts" / "observations"
    if observations.exists():
        assert list(observations.rglob("*.md")) == []
    still = await trail_manager.get_thought(planted.thought_id)
    assert still is not None
    assert still.content == "benign body"
    assert still.frontmatter.metadata.project == AWS_CANARY


@pytest.mark.asyncio
async def test_handle_propose_truth_does_not_call_model_for_legacy_metadata_secret(
    trail_manager, tmp_fava_home, caplog
):
    from fava_trails.tools.navigation import handle_propose_truth

    caplog.set_level("DEBUG")
    planted = await _plant_legacy_draft(
        trail_manager, "benign body", metadata={"project": OPENROUTER_CANARY}
    )
    cache = MagicMock(spec=TrustGatePromptCache)
    cache.resolve_prompt.return_value = "You are a reviewer."
    review = AsyncMock(return_value=TrustResult(verdict="reject", reasoning="secret", reviewer="llm"))

    with (
        patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-test-key"}),
        patch("fava_trails.tools.navigation.review_thought", review),
    ):
        result = await handle_propose_truth(
            trail_manager,
            {"thought_id": planted.thought_id},
            prompt_cache=cache,
        )

    assert result["status"] == "error"
    assert OPENROUTER_CANARY not in result["message"]
    assert "not complete DLP" in result["message"]
    assert "left unchanged" in result["message"]
    review.assert_not_called()
    assert OPENROUTER_CANARY not in caplog.text
    observations = trail_manager.trail_path / "thoughts" / "observations"
    if observations.exists():
        assert list(observations.rglob("*.md")) == []


@pytest.mark.asyncio
async def test_supersede_blocks_copying_secret_metadata(trail_manager, tmp_fava_home, caplog):
    caplog.set_level("DEBUG")
    planted = await _plant_legacy_draft(
        trail_manager, "benign original", metadata={"project": STRIPE_CANARY}
    )
    original_path = trail_manager.trail_path / "thoughts" / "drafts" / f"{planted.thought_id}.md"
    before = original_path.read_text()

    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.supersede(
            planted.thought_id,
            "replacement without a credential",
            reason="correct the conclusion",
            agent_id="test-agent",
        )
    assert STRIPE_CANARY not in str(exc_info.value)
    assert original_path.read_text() == before
    drafts = list((trail_manager.trail_path / "thoughts" / "drafts").rglob("*.md"))
    assert drafts == [original_path]
    assert STRIPE_CANARY not in caplog.text
    still = await trail_manager.get_thought(planted.thought_id)
    assert still is not None
    assert still.content == "benign original"
    assert still.frontmatter.metadata.project == STRIPE_CANARY


def _nested_dict(depth: int, leaf: str) -> object:
    node: object = leaf
    for _ in range(depth):
        node = {"layer": node}
    return node


def test_traversal_limit_fails_closed_instead_of_treating_unscanned_content_as_clean():
    nested = _nested_dict(40, AWS_CANARY)
    assert find_obvious_secret_in_value(nested) == "nested_structure_too_deep"
    assert find_obvious_secret_in_value(_nested_dict(1, AWS_CANARY)) == "aws_access_key_id"
    assert find_obvious_secret_in_value(_nested_dict(32, AWS_CANARY)) == "aws_access_key_id"
    assert find_obvious_secret_in_value(_nested_dict(33, AWS_CANARY)) == "nested_structure_too_deep"
    assert find_obvious_secret_in_value(_nested_dict(40, "benign")) == "nested_structure_too_deep"


@pytest.mark.asyncio
async def test_save_thought_blocks_secret_nested_beyond_traversal_limit(
    trail_manager, tmp_fava_home, caplog
):
    caplog.set_level("DEBUG")
    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.save_thought(
            content="benign draft body",
            agent_id="test-agent",
            metadata={"extra": _nested_dict(40, AWS_CANARY)},
        )
    message = str(exc_info.value)
    assert AWS_CANARY not in message
    assert "nested_structure_too_deep" in message or "traversal" in message.lower()
    _assert_canary_absent(tmp_fava_home, AWS_CANARY)
    assert AWS_CANARY not in caplog.text
    assert list((trail_manager.trail_path / "thoughts").rglob("*.md")) == []


@pytest.mark.asyncio
async def test_propose_truth_blocks_secret_in_reject_trust_result(
    trail_manager, tmp_fava_home, caplog
):
    caplog.set_level("DEBUG")
    record = await trail_manager.save_thought(content="benign draft body", agent_id="test-agent")
    draft_path = trail_manager.trail_path / "thoughts" / "drafts" / f"{record.thought_id}.md"
    before = draft_path.read_text()
    trust_result = TrustResult(
        verdict="reject",
        reasoning=f"blocked candidate {GITHUB_CANARY}",
        reviewer="llm-oneshot:test-model",
        provider="openrouter",
        model="test-model",
    )

    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.propose_truth(record.thought_id, trust_result=trust_result)

    assert GITHUB_CANARY not in str(exc_info.value)
    assert draft_path.read_text() == before
    still = await trail_manager.get_thought(record.thought_id)
    assert still is not None
    assert still.content == "benign draft body"
    assert still.frontmatter.validation_status == ValidationStatus.DRAFT
    assert "trust_gate" not in still.frontmatter.metadata.extra
    _assert_canary_absent(tmp_fava_home, GITHUB_CANARY)
    assert GITHUB_CANARY not in caplog.text


@pytest.mark.asyncio
async def test_propose_truth_blocks_secret_in_approve_trust_result(
    trail_manager, tmp_fava_home, caplog
):
    caplog.set_level("DEBUG")
    record = await trail_manager.save_thought(content="benign draft body", agent_id="test-agent")
    draft_path = trail_manager.trail_path / "thoughts" / "drafts" / f"{record.thought_id}.md"
    before = draft_path.read_text()
    trust_result = TrustResult(
        verdict="approve",
        reasoning="Looks good",
        reviewer="llm-oneshot:test-model",
        provider=f"provider-{OPENAI_CANARY}",
        model="test-model",
    )

    with pytest.raises(ObviousSecretError) as exc_info:
        await trail_manager.propose_truth(record.thought_id, trust_result=trust_result)

    assert OPENAI_CANARY not in str(exc_info.value)
    assert draft_path.read_text() == before
    observations = trail_manager.trail_path / "thoughts" / "observations"
    if observations.exists():
        assert list(observations.rglob("*.md")) == []
    still = await trail_manager.get_thought(record.thought_id)
    assert still is not None
    assert still.frontmatter.validation_status == ValidationStatus.DRAFT
    _assert_canary_absent(tmp_fava_home, OPENAI_CANARY)
    assert OPENAI_CANARY not in caplog.text


@pytest.mark.asyncio
async def test_handle_call_tool_blocks_secret_in_trail_name_before_log_or_init(
    tmp_fava_home, caplog
):
    from fava_trails import server as fava_server

    caplog.set_level("DEBUG")
    fava_server._trail_managers.clear()
    review = AsyncMock()

    with patch("fava_trails.tools.navigation.review_thought", review):
        result = await fava_server.handle_call_tool(
            "start_thought",
            {"trail_name": GITHUB_CANARY, "description": "benign start"},
        )

    assert result["status"] == "error"
    assert "github_pat" in result["message"]
    assert GITHUB_CANARY not in result["message"]
    assert GITHUB_CANARY not in caplog.text
    review.assert_not_called()
    _assert_canary_absent_from_tree(tmp_fava_home, GITHUB_CANARY)
    assert not (tmp_fava_home / "trails" / GITHUB_CANARY).exists()


@pytest.mark.asyncio
async def test_handle_call_tool_blocks_secret_in_trail_name_on_read_tool(
    tmp_fava_home, caplog
):
    from fava_trails import server as fava_server

    caplog.set_level("DEBUG")
    fava_server._trail_managers.clear()

    result = await fava_server.handle_call_tool(
        "recall",
        {"trail_name": GITHUB_CANARY, "query": "status"},
    )

    assert result["status"] == "error"
    assert "github_pat" in result["message"]
    assert GITHUB_CANARY not in result["message"]
    assert GITHUB_CANARY not in caplog.text
    _assert_canary_absent_from_tree(tmp_fava_home, GITHUB_CANARY)
    assert not (tmp_fava_home / "trails" / GITHUB_CANARY).exists()


@pytest.mark.asyncio
async def test_handle_call_tool_blocks_secret_in_trail_names(
    trail_manager, tmp_fava_home, caplog
):
    from fava_trails import server as fava_server

    caplog.set_level("DEBUG")
    fava_server._trail_managers.clear()

    result = await fava_server.handle_call_tool(
        "recall",
        {
            "trail_name": trail_manager.trail_name,
            "query": "status",
            "trail_names": [GITHUB_CANARY],
        },
    )

    assert result["status"] == "error"
    assert "github_pat" in result["message"]
    assert GITHUB_CANARY not in result["message"]
    assert GITHUB_CANARY not in caplog.text
    _assert_canary_absent_from_tree(tmp_fava_home, GITHUB_CANARY)
    assert not (tmp_fava_home / "trails" / GITHUB_CANARY).exists()


@pytest.mark.asyncio
async def test_handle_call_tool_blocks_secret_in_target_trail_name(
    trail_manager, tmp_fava_home, caplog
):
    from fava_trails import server as fava_server

    caplog.set_level("DEBUG")
    fava_server._trail_managers.clear()
    record = await trail_manager.save_thought(content="benign draft body", agent_id="test-agent")

    result = await fava_server.handle_call_tool(
        "change_scope",
        {
            "trail_name": trail_manager.trail_name,
            "thought_id": record.thought_id,
            "content": "rewritten for a broader audience",
            "target_trail_name": GITHUB_CANARY,
            "reason": "elevate without a credential",
        },
    )

    assert result["status"] == "error"
    assert "github_pat" in result["message"]
    assert GITHUB_CANARY not in result["message"]
    assert GITHUB_CANARY not in caplog.text
    _assert_canary_absent_from_tree(tmp_fava_home, GITHUB_CANARY)
    still = await trail_manager.get_thought(record.thought_id)
    assert still is not None
    assert still.content == "benign draft body"


def test_refuse_warning_log_omits_pattern_id(caplog):
    caplog.set_level("WARNING")
    with pytest.raises(ObviousSecretError):
        refuse_obvious_secret(f"leaked {GITHUB_CANARY}")
    assert GITHUB_CANARY not in caplog.text
    assert "github_pat" not in caplog.text
    assert "pattern=" not in caplog.text


@pytest.mark.asyncio
async def test_handle_call_tool_blocks_secret_in_list_scopes_prefix(tmp_fava_home, caplog):
    from fava_trails import server as fava_server

    caplog.set_level("DEBUG")
    fava_server._trail_managers.clear()
    list_scopes = AsyncMock()

    with patch("fava_trails.tools.navigation.handle_list_scopes", list_scopes):
        result = await fava_server.handle_call_tool("list_scopes", {"prefix": GITHUB_CANARY})

    assert result["status"] == "error"
    assert "github_pat" in result["message"]
    assert GITHUB_CANARY not in result["message"]
    assert GITHUB_CANARY not in caplog.text
    list_scopes.assert_not_called()
    _assert_canary_absent_from_tree(tmp_fava_home, GITHUB_CANARY)


@pytest.mark.asyncio
async def test_handle_call_tool_blocks_secret_in_thought_id_lookup(
    trail_manager, tmp_fava_home, caplog
):
    from fava_trails import server as fava_server

    caplog.set_level("DEBUG")
    fava_server._trail_managers.clear()
    get_thought = AsyncMock()

    with patch("fava_trails.tools.thought.handle_get_thought", get_thought):
        result = await fava_server.handle_call_tool(
            "get_thought",
            {"trail_name": trail_manager.trail_name, "thought_id": GITHUB_CANARY},
        )

    assert result["status"] == "error"
    assert "github_pat" in result["message"]
    assert GITHUB_CANARY not in result["message"]
    assert GITHUB_CANARY not in caplog.text
    get_thought.assert_not_called()
    _assert_canary_absent_from_tree(tmp_fava_home, GITHUB_CANARY)


@pytest.mark.asyncio
async def test_handle_call_tool_blocks_secret_in_diff_revision(
    trail_manager, tmp_fava_home, caplog
):
    from fava_trails import server as fava_server

    caplog.set_level("DEBUG")
    fava_server._trail_managers.clear()
    handle_diff = AsyncMock()

    with patch("fava_trails.tools.navigation.handle_diff", handle_diff):
        result = await fava_server.handle_call_tool(
            "diff",
            {"trail_name": trail_manager.trail_name, "revision": GITHUB_CANARY},
        )

    assert result["status"] == "error"
    assert "github_pat" in result["message"]
    assert GITHUB_CANARY not in result["message"]
    assert GITHUB_CANARY not in caplog.text
    handle_diff.assert_not_called()
    _assert_canary_absent_from_tree(tmp_fava_home, GITHUB_CANARY)

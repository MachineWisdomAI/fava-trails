"""Governed reader snapshots and lifecycle navigation use the same source truth."""
import json
from unittest.mock import patch

from fava_trails.governance import Principal, Visibility
from fava_trails.models import ThoughtRecord
from fava_trails.rich_views import generate_reader, generate_reader_for_scopes
from tests.test_rich_views_semantics import page_data, write_record

HISTORY = Visibility(mode="history", principal=Principal(operator=True), include_superseded=True)


def test_pending_replacement_remains_current_in_reader(tmp_path):
    trails, reader = tmp_path / "trails", tmp_path / "reader"
    write_record(trails, "example/team", "original", "# Current policy", source_type="decision",
                 superseded_by="proposal", superseded_scope="example/team")
    write_record(trails, "example/team", "proposal", "# Private proposal title", validation_status="proposed")
    result = generate_reader(trails_dir=trails, scope="example/team", output_dir=reader)
    assert result.thought_count == 1
    detail = page_data(reader, "original")
    assert detail["isSuperseded"] is False
    assert detail["supersededBy"]["resolved"] is False
    assert detail["supersededBy"]["route"] is None
    assert "Private proposal title" not in (reader / "src/pages/index.astro").read_text()
    assert not (reader / "src/pages/id/proposal.md").exists()
    generate_reader(trails_dir=trails, scope="example/team", output_dir=reader, visibility=HISTORY)
    detail = page_data(reader, "original")
    assert detail["isSuperseded"] is False
    assert detail["supersededBy"]["resolved"] is True
    assert {edge["type"] for edge in detail["lineage"]} == {"replacement link (not effective)"}


def test_approved_replacement_is_history_and_keeps_scope_qualified_target(tmp_path):
    trails, reader = tmp_path / "trails", tmp_path / "reader"
    write_record(trails, "example/original", "original", "# Historical policy", source_type="decision",
                 superseded_by="replacement", superseded_scope="example/actual")
    write_record(trails, "example/actual", "replacement", "# Hidden correct successor")
    write_record(trails, "example/unrelated", "replacement", "# Unrelated same identifier")
    generate_reader_for_scopes(trails_dir=trails, scopes=["example/original", "example/unrelated"],
                               output_dir=reader, visibility=HISTORY)
    detail = page_data(reader, "original")
    assert detail["isSuperseded"] is True
    assert detail["supersededBy"]["resolved"] is False
    assert detail["supersededBy"]["route"] is None
    assert "Hidden correct successor" not in (reader / "src/pages/index.astro").read_text()
    assert all(edge["target"]["route"] is None for edge in detail["lineage"])


def test_multiscope_reader_uses_one_coherent_current_snapshot(tmp_path):
    trails, reader = tmp_path / "trails", tmp_path / "reader"
    original = write_record(trails, "example/a", "original", "# Original current")
    successor = write_record(trails, "example/b", "successor", "# Proposed successor", validation_status="proposed")
    before = {original: original.read_text(), successor: successor.read_text()}
    old = ThoughtRecord.from_markdown(before[original])
    old.frontmatter.superseded_by = "successor"
    old.frontmatter.superseded_scope = "example/b"
    new = ThoughtRecord.from_markdown(before[successor])
    from fava_trails.models import ValidationStatus
    new.frontmatter.validation_status = ValidationStatus.APPROVED
    after = {original: old.to_markdown(), successor: new.to_markdown()}
    # A transaction commits after the first snapshot. A generation that re-reads
    # each scope would incorrectly contain both versions as current truth.
    with patch("fava_trails.governance.snapshot_texts", side_effect=[before, after]):
        result = generate_reader_for_scopes(trails_dir=trails, scopes=None, output_dir=reader)
    assert result.thought_count == 1
    routes = json.loads((reader / "src/data/generated.json").read_text())["thoughtRoutes"]
    assert set(routes) == {"original"}


def test_proposed_supersession_keeps_explicit_predecessor_scope(tmp_path):
    trails, reader = tmp_path / "trails", tmp_path / "reader"
    write_record(trails, "example/actual", "predecessor", "# Hidden predecessor")
    write_record(trails, "example/unrelated", "predecessor", "# Unrelated same identifier")
    write_record(trails, "example/proposal", "proposal", "# Proposed replacement", validation_status="proposed",
                 parent_id="predecessor", supersedes_id="predecessor", supersedes_scope="example/actual")
    generate_reader_for_scopes(trails_dir=trails, scopes=["example/proposal", "example/unrelated"],
                               output_dir=reader, visibility=HISTORY)
    detail = page_data(reader, "proposal")
    assert detail["isSuperseded"] is False
    assert detail["parent"]["resolved"] is False
    assert {edge["type"] for edge in detail["lineage"]} == {"parent", "replacement proposal for"}
    assert all(edge["target"]["route"] is None for edge in detail["lineage"])

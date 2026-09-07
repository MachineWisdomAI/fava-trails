"""Reader boundary tests: canonical source records become auditable local pages."""
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from fava_trails.models import ThoughtFrontmatter, ThoughtRecord
from fava_trails.rich_views import generate_reader, generate_reader_for_scopes

STAMP = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def write_record(trails: Path, scope: str, thought_id: str, body: str, **fields):
    namespace = fields.pop("namespace", "decisions")
    record = ThoughtRecord(frontmatter=ThoughtFrontmatter(
        thought_id=thought_id, validation_status=fields.pop("validation_status", "approved"),
        created_at=STAMP, **fields,
    ), content=body)
    path = trails / scope / "thoughts" / namespace / f"{thought_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.to_markdown())
    return path


def page_data(reader, thought_id):
    return yaml.safe_load((reader / "src/pages/id" / f"{thought_id}.md").read_text().split("---", 2)[1])


def test_descendant_dashboard_and_semantic_detail_preserve_source(tmp_path):
    trails, reader = tmp_path / "trails", tmp_path / "reader"
    source = write_record(trails, "example/team", "old-00000001", "# Queue policy\n\nOriginal conclusion.",
                          source_type="decision", superseded_by="new-00000002")
    write_record(trails, "example/team", "new-00000002", "# Queue policy\n\n" + "Complete evidence. " * 40,
                 source_type="decision", parent_id="old-00000001", agent_id="reviewer", confidence=.95,
                 metadata={"tags": ["queue", "operations"]}, relationships=[{"type": "DEPENDS_ON", "target_id": "child-00000003"}, {"type": "REFERENCES", "target_id": "missing-target"}])
    write_record(trails, "example/team/child", "child-00000003", "# Worker capacity\n\nTwo slots.",
                 source_type="observation", namespace="observations", agent_id="builder")
    write_record(trails, "example/other", "other-00000004", "# Outside selected scope")
    before = source.read_bytes()
    result = generate_reader(trails_dir=trails, scope="example/team", output_dir=reader, generated_at=STAMP)
    assert result.scopes == ("example/team", "example/team/child")
    assert result.thought_count == 3
    assert source.read_bytes() == before
    metadata = json.loads((reader / "src/data/generated.json").read_text())
    routes = metadata["thoughtRoutes"]
    assert routes["old-00000001"]["canonical"] == "/example/team/queue-policy-00000001/"
    assert routes["new-00000002"]["canonical"] == "/example/team/queue-policy-00000002/"
    assert routes["new-00000002"]["fallback"] == "/id/new-00000002/"
    detail = page_data(reader, "new-00000002")
    assert detail["parent"]["thoughtId"] == "old-00000001"
    assert detail["parent"]["route"] == routes["old-00000001"]["canonical"]
    assert {edge["type"] for edge in detail["outbound"]} == {"DEPENDS_ON", "REFERENCES"}
    assert detail["outbound"][1]["resolved"] is False
    assert detail["outbound"][1]["route"] is None
    child = page_data(reader, "child-00000003")
    assert child["inbound"][0]["thoughtId"] == "new-00000002"
    assert child["inbound"][0]["type"] == "DEPENDS_ON"
    assert len(detail["lineage"]) == 2
    assert detail["sourcePath"] == "example/team/thoughts/decisions/new-00000002.md"
    assert detail["createdAt"] == STAMP.isoformat()
    assert len(detail["excerpt"]) == 200
    body_path = reader / "src/pages/example/team/queue-policy-00000002.md"
    assert "Complete evidence. " * 39 in body_path.read_text()
    dashboard = (reader / "src/pages/scopes/example/team/index.astro").read_text()
    assert "Worker capacity" in dashboard
    assert "Outside selected scope" not in dashboard
    assert "Complete evidence. " * 39 not in dashboard


def test_scope_without_direct_thoughts_includes_descendants(tmp_path):
    write_record(tmp_path / "trails", "example/team/child", "one", "# Nested record")
    result = generate_reader(trails_dir=tmp_path / "trails", scope="example/team", output_dir=tmp_path / "reader")
    assert result.scope == "example/team"
    assert result.thought_count == 1
    assert (tmp_path / "reader/src/pages/scopes/example/team/index.astro").is_file()


def test_parentage_cycle_is_finite_and_preserves_explicit_edges(tmp_path):
    write_record(tmp_path / "trails", "example/team", "a", "# Same title", parent_id="b")
    write_record(tmp_path / "trails", "example/team", "b", "# Same title", parent_id="a")
    generate_reader(trails_dir=tmp_path / "trails", scope="example/team", output_dir=tmp_path / "reader")
    assert len(page_data(tmp_path / "reader", "a")["lineage"]) == 2


def test_reader_rejects_missing_identity_without_synthesizing_records(tmp_path):
    path = tmp_path / "trails/example/team/thoughts/drafts/broken.md"
    path.parent.mkdir(parents=True)
    path.write_text("No frontmatter or durable identity")
    with pytest.raises(ValueError, match="Missing thought_id"):
        generate_reader(trails_dir=tmp_path / "trails", scope="example/team", output_dir=tmp_path / "reader")


def test_same_title_in_separate_scopes_needs_no_suffix(tmp_path):
    write_record(tmp_path / "trails", "example/one", "first", "# Same title")
    write_record(tmp_path / "trails", "example/two", "second", "# Same title")
    result = generate_reader_for_scopes(trails_dir=tmp_path / "trails", scopes=None, output_dir=tmp_path / "reader")
    assert set(result.routes) == {"/example/one/same-title/", "/example/two/same-title/"}


def test_unknown_relationship_type_fails_instead_of_inventing_semantics(tmp_path):
    path = write_record(tmp_path / "trails", "example/team", "first", "# Typed edge")
    path.write_text(path.read_text().replace("relationships: []", "relationships: [{type: CONTRADICTS, target_id: missing}]"))
    with pytest.raises(ValueError, match="Input should be"):
        generate_reader(trails_dir=tmp_path / "trails", scope="example/team", output_dir=tmp_path / "reader")

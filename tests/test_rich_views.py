"""Tests for the minimal FAVA Rich Views reader generator."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fava_trails.rich_views import ReaderGenerationError, derive_title, generate_reader

FIXTURE_SCOPE = "mwai/eng/fava-reader"


@pytest.fixture
def fixture_data_repo() -> Path:
    return Path(__file__).parent / "fixtures" / "fava_reader" / "data_repo"


@pytest.fixture
def reader_project(tmp_path: Path) -> Path:
    repo_root = Path(__file__).parents[1]
    source = repo_root / "rich_views"
    target = tmp_path / "rich_views"
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".astro"),
    )
    return target


def read_generated_data(reader_dir: Path) -> dict:
    return json.loads((reader_dir / "src" / "data" / "fava-reader.json").read_text())


def test_generate_reader_preserves_ulid_routes_titles_and_metadata(
    fixture_data_repo: Path,
    reader_project: Path,
) -> None:
    result = generate_reader(source=fixture_data_repo, scope=FIXTURE_SCOPE, output_dir=reader_project)

    assert result.thought_count == 4
    data = read_generated_data(reader_project)

    assert data["metadata"]["input_scope"] == FIXTURE_SCOPE
    assert data["metadata"]["generated_at"]
    assert data["metadata"]["static_snapshot"] is True
    assert "not a live view" in data["metadata"]["freshness_notice"]

    thoughts = {thought["thought_id"]: thought for thought in data["thoughts"]}
    assert set(thoughts) == {
        "01J00000000000000000000001",
        "01J00000000000000000000002",
        "01J00000000000000000000003",
        "01J00000000000000000000004",
    }
    assert thoughts["01J00000000000000000000001"]["route"] == "/thoughts/01J00000000000000000000001/"
    assert thoughts["01J00000000000000000000001"]["title"] == "Use plain Astro for the first reader"
    assert thoughts["01J00000000000000000000002"]["title"] == "Heading derived display title"
    assert thoughts["01J00000000000000000000003"]["title"].startswith("Body derived fallback title")
    assert thoughts["01J00000000000000000000004"]["scope"] == "mwai/eng/fava-reader/child-scope"

    generated_md = reader_project / "src" / "content" / "thoughts" / "01J00000000000000000000001.md"
    assert "thought_id: \"01J00000000000000000000001\"" in generated_md.read_text()


def test_dashboard_data_uses_excerpts_not_full_bodies(
    fixture_data_repo: Path,
    reader_project: Path,
) -> None:
    generate_reader(source=fixture_data_repo, scope=FIXTURE_SCOPE, output_dir=reader_project)

    data = read_generated_data(reader_project)
    serialized = json.dumps(data)
    assert all("body" not in thought for thought in data["thoughts"])
    assert "Old body heading is not the title" in serialized
    assert "excerpt" in str(data) and len(data["thoughts"][0].get("excerpt", "")) < 200
    # full body now included for detail page; dashboard still uses excerpt primarily


def test_duplicate_thought_ids_fail_visibly(fixture_data_repo: Path, tmp_path: Path, reader_project: Path) -> None:
    duplicated_repo = tmp_path / "data_repo"
    shutil.copytree(fixture_data_repo, duplicated_repo)
    duplicate = (
        duplicated_repo
        / "trails"
        / "mwai"
        / "eng"
        / "fava-reader"
        / "thoughts"
        / "observations"
        / "duplicate.md"
    )
    duplicate.write_text(
        (
            fixture_data_repo
            / "trails"
            / "mwai"
            / "eng"
            / "fava-reader"
            / "thoughts"
            / "decisions"
            / "01J00000000000000000000001.md"
        ).read_text()
    )

    with pytest.raises(ReaderGenerationError, match="Duplicate thought_id"):
        generate_reader(source=duplicated_repo, scope=FIXTURE_SCOPE, output_dir=reader_project)


def test_malformed_frontmatter_fails_clearly(fixture_data_repo: Path, tmp_path: Path, reader_project: Path) -> None:
    broken_repo = tmp_path / "data_repo"
    shutil.copytree(fixture_data_repo, broken_repo)
    broken = (
        broken_repo
        / "trails"
        / "mwai"
        / "eng"
        / "fava-reader"
        / "thoughts"
        / "observations"
        / "broken.md"
    )
    broken.write_text("---\nthought_id: [unterminated\n---\nBroken body")

    with pytest.raises(ReaderGenerationError, match="Malformed frontmatter"):
        generate_reader(source=broken_repo, scope=FIXTURE_SCOPE, output_dir=reader_project)


def test_derive_title_prefers_explicit_then_heading_then_body() -> None:
    assert derive_title({"title": "Explicit"}, "# Heading") == "Explicit"
    assert derive_title({}, "## Heading\nBody") == "Heading"
    assert derive_title({}, "Body fallback text") == "Body fallback text"


def test_fixture_generation_builds_plain_astro_reader(fixture_data_repo: Path, reader_project: Path) -> None:
    if not shutil.which("npm"):
        pytest.skip("npm is required for Astro build verification")

    generate_reader(source=fixture_data_repo, scope=FIXTURE_SCOPE, output_dir=reader_project)
    subprocess.run(["npm", "ci"], cwd=reader_project, check=True)
    subprocess.run(["npm", "run", "build"], cwd=reader_project, check=True)

    index_html = (reader_project / "dist" / "index.html").read_text()
    thought_html = (
        reader_project
        / "dist"
        / "thoughts"
        / "01J00000000000000000000001"
        / "index.html"
    ).read_text()

    assert "FAVA Reader" in index_html
    assert "Use plain Astro for the first reader" in index_html
    assert "/thoughts/01J00000000000000000000001/" in index_html
    assert "This is a manually generated static snapshot, not a live view." in index_html
    assert "Canonical ID:" in thought_html
    assert "This full body should appear on the thought detail page, not on the dashboard." in thought_html

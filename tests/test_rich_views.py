"""Tests for generating a minimal FAVA Rich Views reader."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from fava_trails.cli import cmd_rich_view_serve
from fava_trails.rich_views import generate_reader, generate_reader_for_scopes

EXPLICIT_TITLE_ID = "01KTEST000000000000000001"
HEADING_TITLE_ID = "01KTEST000000000000000002"
FALLBACK_TITLE_ID = "01KTEST000000000000000003"


def _write_thought(
    trails_dir: Path,
    scope: str,
    namespace: str,
    thought_id: str,
    body: str,
    *,
    filename: str | None = None,
    title: str | None = None,
    source_type: str = "observation",
) -> Path:
    path = trails_dir / scope / "thoughts" / namespace / f"{filename or thought_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    title_line = f'title: "{title}"\n' if title else ""
    path.write_text(
        f"""---
schema_version: 1
thought_id: "{thought_id}"
{title_line}agent_id: test-agent
source_type: {source_type}
confidence: 0.85
validation_status: approved
created_at: "2026-07-01T09:30:00Z"
metadata:
  project: rich-views
  tags:
    - fixture
---
{body}
""",
        encoding="utf-8",
    )
    return path


def test_generate_reader_writes_plain_astro_reader_from_fixture_records(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    scope = "mw/eng/demo"
    generated_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    _write_thought(
        trails_dir,
        scope,
        "decisions",
        EXPLICIT_TITLE_ID,
        "Body with an explicit frontmatter title.",
        title="Explicit operator title",
        source_type="decision",
    )
    _write_thought(
        trails_dir,
        scope,
        "observations",
        HEADING_TITLE_ID,
        "# Heading-derived title\n\nBody content under the heading.",
    )
    _write_thought(
        trails_dir,
        scope,
        "drafts",
        FALLBACK_TITLE_ID,
        "Fallback title comes from the first words of the body when no heading exists.",
    )

    result = generate_reader(
        trails_dir=trails_dir,
        scope=scope,
        output_dir=output_dir,
        generated_at=generated_at,
    )

    assert result.thought_count == 3
    assert result.scope == scope

    package_json = (output_dir / "package.json").read_text(encoding="utf-8")
    assert '"astro"' in package_json
    assert "starlight" not in package_json.lower()
    assert "quartz" not in package_json.lower()
    assert (output_dir / "astro.config.mjs").is_file()

    metadata = (output_dir / "src/data/generated.json").read_text(encoding="utf-8")
    assert '"inputScope": "mw/eng/demo"' in metadata
    assert '"generatedAt": "2026-07-01T12:00:00+00:00"' in metadata
    assert f"/id/{EXPLICIT_TITLE_ID}/" in metadata
    assert f"/id/{HEADING_TITLE_ID}/" in metadata
    assert f"/id/{FALLBACK_TITLE_ID}/" in metadata
    assert f"/thoughts/{EXPLICIT_TITLE_ID}/" not in metadata
    assert f'"/{EXPLICIT_TITLE_ID}/"' not in metadata

    index = (output_dir / "src/pages/index.astro").read_text(encoding="utf-8")
    assert "Static snapshot" in index
    assert "not a live view" in index
    assert "Input scope: mw/eng/demo" in index
    assert "Generated at: 2026-07-01T12:00:00+00:00" in index
    assert "Explicit operator title" in index
    assert "Heading-derived title" in index
    assert "Fallback title comes from the first words" in index
    assert f"/id/{EXPLICIT_TITLE_ID}/" in index
    assert f"/id/{HEADING_TITLE_ID}/" in index
    assert f"/id/{FALLBACK_TITLE_ID}/" in index
    assert f"/thoughts/{EXPLICIT_TITLE_ID}/" not in index
    assert f'"/{EXPLICIT_TITLE_ID}/"' not in index

    assert not (output_dir / "src/pages/thoughts" / f"{EXPLICIT_TITLE_ID}.md").exists()

    detail_page = output_dir / "src/pages/id" / f"{EXPLICIT_TITLE_ID}.md"
    detail_text = detail_page.read_text(encoding="utf-8")
    assert f'thoughtId: "{EXPLICIT_TITLE_ID}"' in detail_text
    assert 'inputScope: "mw/eng/demo"' in detail_text
    assert 'generatedAt: "2026-07-01T12:00:00+00:00"' in detail_text
    assert "Body with an explicit frontmatter title." in detail_text


def test_generate_reader_for_scopes_defaults_to_all_discovered_scopes(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    generated_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    _write_thought(trails_dir, "mw/eng/alpha", "decisions", EXPLICIT_TITLE_ID, "# Alpha")
    _write_thought(trails_dir, "mw/eng/beta", "observations", HEADING_TITLE_ID, "# Beta")

    result = generate_reader_for_scopes(
        trails_dir=trails_dir,
        scopes=None,
        output_dir=output_dir,
        generated_at=generated_at,
    )

    assert result.scopes == ("mw/eng/alpha", "mw/eng/beta")
    assert result.scope == "all scopes"
    assert result.thought_count == 2

    metadata = (output_dir / "src/data/generated.json").read_text(encoding="utf-8")
    assert '"inputScope": "all scopes"' in metadata
    assert '"inputScopes": [\n    "mw/eng/alpha",\n    "mw/eng/beta"\n  ]' in metadata
    assert f"/id/{EXPLICIT_TITLE_ID}/" in metadata
    assert f"/id/{HEADING_TITLE_ID}/" in metadata
    assert f"/thoughts/{EXPLICIT_TITLE_ID}/" not in metadata
    assert f'"/{EXPLICIT_TITLE_ID}/"' not in metadata

    index = (output_dir / "src/pages/index.astro").read_text(encoding="utf-8")
    assert "Input scope: all scopes" in index
    assert "mw/eng/alpha" in index
    assert "mw/eng/beta" in index


def test_generate_reader_for_scopes_scope_filter_narrows_selected_scopes(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    generated_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    _write_thought(trails_dir, "mw/eng/alpha", "decisions", EXPLICIT_TITLE_ID, "# Alpha")
    _write_thought(trails_dir, "mw/eng/beta", "observations", HEADING_TITLE_ID, "# Beta")

    result = generate_reader_for_scopes(
        trails_dir=trails_dir,
        scopes=["mw/eng/beta"],
        output_dir=output_dir,
        generated_at=generated_at,
    )

    assert result.scopes == ("mw/eng/beta",)
    assert result.scope == "mw/eng/beta"
    assert result.thought_count == 1
    assert not (output_dir / "src/pages/id" / f"{EXPLICIT_TITLE_ID}.md").exists()
    assert (output_dir / "src/pages/id" / f"{HEADING_TITLE_ID}.md").is_file()


def test_generate_reader_for_scopes_rejects_duplicate_ids_across_scopes(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    duplicate_id = "01KTEST0000000000000000DUP"
    _write_thought(trails_dir, "mw/eng/alpha", "decisions", duplicate_id, "# Alpha copy")
    _write_thought(trails_dir, "mw/eng/beta", "observations", duplicate_id, "# Beta copy")

    with pytest.raises(ValueError, match=f"Duplicate thought_id {duplicate_id}"):
        generate_reader_for_scopes(
            trails_dir=trails_dir,
            scopes=None,
            output_dir=tmp_path / "reader",
            generated_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )


def test_generate_reader_rejects_duplicate_thought_ids(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    scope = "mw/eng/demo"
    duplicate_id = "01KTEST0000000000000000DUP"
    _write_thought(trails_dir, scope, "decisions", duplicate_id, "# First copy")
    _write_thought(trails_dir, scope, "observations", duplicate_id, "# Second copy")

    with pytest.raises(ValueError, match=f"Duplicate thought_id {duplicate_id}"):
        generate_reader(
            trails_dir=trails_dir,
            scope=scope,
            output_dir=tmp_path / "reader",
            generated_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )


def test_generate_reader_rejects_path_traversal_thought_id_without_writing_outside_output(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    outside_dir = tmp_path / "tmp"
    outside_dir.mkdir()
    outside_path = outside_dir / "pwned.md"
    scope = "mw/eng/demo"
    unsafe_id = "../../../../tmp/pwned"
    source_path = _write_thought(
        trails_dir,
        scope,
        "decisions",
        unsafe_id,
        "# Poisoned",
        filename="01KTEST000000000000000004",
    )

    with pytest.raises(ValueError) as exc:
        generate_reader(
            trails_dir=trails_dir,
            scope=scope,
            output_dir=output_dir,
            generated_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )

    message = str(exc.value)
    assert "Unsafe thought_id" in message
    assert unsafe_id in message
    assert str(source_path) in message
    assert not outside_path.exists()


def test_generate_reader_rejects_non_empty_non_reader_output_without_clobbering(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "existing-project"
    scope = "mw/eng/demo"
    source_id = "01KTEST000000000000000004"
    _write_thought(trails_dir, scope, "decisions", source_id, "# Safe source")

    existing_src = output_dir / "src"
    existing_src.mkdir(parents=True)
    existing_app = existing_src / "app.py"
    existing_app.write_text("print('keep me')\n", encoding="utf-8")
    existing_readme = output_dir / "README.md"
    existing_readme.write_text("# Existing project\n", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to overwrite non-reader output directory"):
        generate_reader(
            trails_dir=trails_dir,
            scope=scope,
            output_dir=output_dir,
            generated_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )

    assert existing_app.read_text(encoding="utf-8") == "print('keep me')\n"
    assert existing_readme.read_text(encoding="utf-8") == "# Existing project\n"
    assert not (output_dir / "src/pages/id" / f"{source_id}.md").exists()


def test_generate_reader_rerun_cleans_stale_generated_pages(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    scope = "mw/eng/demo"
    first_id = "01KTEST000000000000000004"
    stale_id = "01KTEST000000000000000005"
    generated_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    _write_thought(trails_dir, scope, "decisions", first_id, "# Current thought")
    stale_source = _write_thought(trails_dir, scope, "observations", stale_id, "# Stale thought")

    generate_reader(
        trails_dir=trails_dir,
        scope=scope,
        output_dir=output_dir,
        generated_at=generated_at,
    )
    assert (output_dir / "src/pages/id" / f"{stale_id}.md").is_file()

    stale_source.unlink()
    result = generate_reader(
        trails_dir=trails_dir,
        scope=scope,
        output_dir=output_dir,
        generated_at=generated_at,
    )

    assert result.thought_count == 1
    assert (output_dir / "src/pages/id" / f"{first_id}.md").is_file()
    assert not (output_dir / "src/pages/id" / f"{stale_id}.md").exists()


def test_cli_rich_view_generate_command_builds_reader_from_fixture_records(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    scope = "mw/eng/demo"
    _write_thought(
        trails_dir,
        scope,
        "decisions",
        EXPLICIT_TITLE_ID,
        "# CLI fixture\n\nGenerated from the CLI.",
        source_type="decision",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fava_trails.cli",
            "rich-view",
            "generate",
            "--trails-dir",
            str(trails_dir),
            "--scope",
            scope,
            "--out",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Generated FAVA reader" in result.stdout
    assert (output_dir / "src/pages/index.astro").is_file()
    assert (output_dir / "src/pages/id" / f"{EXPLICIT_TITLE_ID}.md").is_file()
    assert not (output_dir / "src/pages/thoughts" / f"{EXPLICIT_TITLE_ID}.md").exists()


def test_cli_rich_view_serve_generates_all_scopes_and_starts_loopback_server(tmp_path, capsys):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    _write_thought(trails_dir, "mw/eng/alpha", "decisions", EXPLICIT_TITLE_ID, "# Alpha")
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0

    with patch("fava_trails.cli._ensure_reader_node_modules") as ensure_node:
        with patch("fava_trails.cli._wait_for_reader_server"):
            with patch("subprocess.Popen", return_value=process) as popen:
                rc = cmd_rich_view_serve(
                    _make_serve_args(
                        trails_dir=trails_dir,
                        out=output_dir,
                        port=4322,
                        serve_duration=0,
                    )
                )

    assert rc == 0
    ensure_node.assert_called_once_with(output_dir, skip_install=False)
    popen.assert_called_once_with(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "4322", "--strictPort"],
        cwd=str(output_dir),
    )
    process.terminate.assert_called_once()
    out = capsys.readouterr().out
    assert "Serving local private FAVA data" in out
    assert "http://127.0.0.1:4322/" in out
    assert "Scopes: mw/eng/alpha" in out
    assert (output_dir / "src/pages/id" / f"{EXPLICIT_TITLE_ID}.md").is_file()


def test_cli_rich_view_serve_scope_filter_narrows_generated_reader(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    _write_thought(trails_dir, "mw/eng/alpha", "decisions", EXPLICIT_TITLE_ID, "# Alpha")
    _write_thought(trails_dir, "mw/eng/beta", "observations", HEADING_TITLE_ID, "# Beta")
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0

    with patch("fava_trails.cli._ensure_reader_node_modules"):
        with patch("fava_trails.cli._wait_for_reader_server"):
            with patch("subprocess.Popen", return_value=process):
                rc = cmd_rich_view_serve(
                    _make_serve_args(
                        trails_dir=trails_dir,
                        out=output_dir,
                        scope=["mw/eng/beta"],
                        port=4323,
                        serve_duration=0,
                    )
                )

    assert rc == 0
    assert not (output_dir / "src/pages/id" / f"{EXPLICIT_TITLE_ID}.md").exists()
    assert (output_dir / "src/pages/id" / f"{HEADING_TITLE_ID}.md").is_file()


def test_cli_rich_view_serve_rejects_non_loopback_host(tmp_path, capsys):
    rc = cmd_rich_view_serve(
        _make_serve_args(
            trails_dir=tmp_path / "trails",
            out=tmp_path / "reader",
            host="0.0.0.0",
            serve_duration=0,
        )
    )

    assert rc == 1
    assert "loopback" in capsys.readouterr().err


def test_cli_rich_view_serve_no_generate_requires_existing_reader(tmp_path, capsys):
    rc = cmd_rich_view_serve(
        _make_serve_args(
            trails_dir=tmp_path / "trails",
            out=tmp_path / "not-reader",
            no_generate=True,
            serve_duration=0,
        )
    )

    assert rc == 1
    assert "not a generated FAVA reader" in capsys.readouterr().err


def test_cli_rich_view_serve_formats_ipv6_loopback_url(tmp_path, capsys):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    _write_thought(trails_dir, "mw/eng/alpha", "decisions", EXPLICIT_TITLE_ID, "# Alpha")
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0

    with patch("fava_trails.cli._ensure_reader_node_modules"):
        with patch("fava_trails.cli._wait_for_reader_server"):
            with patch("subprocess.Popen", return_value=process):
                rc = cmd_rich_view_serve(
                    _make_serve_args(
                        trails_dir=trails_dir,
                        out=output_dir,
                        host="::1",
                        port=4324,
                        serve_duration=0,
                    )
                )

    assert rc == 0
    assert "http://[::1]:4324/" in capsys.readouterr().out


def test_cli_rich_view_serve_stops_process_when_readiness_fails(tmp_path):
    trails_dir = tmp_path / "data-repo" / "trails"
    output_dir = tmp_path / "reader"
    _write_thought(trails_dir, "mw/eng/alpha", "decisions", EXPLICIT_TITLE_ID, "# Alpha")
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0

    with patch("fava_trails.cli._ensure_reader_node_modules"):
        with patch("fava_trails.cli._wait_for_reader_server", side_effect=TimeoutError("not ready")):
            with patch("subprocess.Popen", return_value=process):
                rc = cmd_rich_view_serve(
                    _make_serve_args(
                        trails_dir=trails_dir,
                        out=output_dir,
                        port=4325,
                        serve_duration=0,
                    )
                )

    assert rc == 1
    process.terminate.assert_called_once()


def _make_serve_args(
    *,
    trails_dir: Path | None = None,
    out: Path | None = None,
    scope: list[str] | None = None,
    host: str = "127.0.0.1",
    port: int = 4321,
    no_generate: bool = False,
    no_install: bool = False,
    serve_duration: float | None = None,
):
    return type(
        "Args",
        (),
        {
            "trails_dir": str(trails_dir) if trails_dir else None,
            "out": str(out) if out else None,
            "scope": scope,
            "host": host,
            "port": port,
            "no_generate": no_generate,
            "no_install": no_install,
            "serve_duration": serve_duration,
        },
    )()

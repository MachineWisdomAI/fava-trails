"""Astro presentation assets for the generated, read-only FAVA reader."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def write_reader_ui(
    output_dir: Path, scope: str, generated_at: str,
    thoughts: list[dict[str, Any]], scopes: tuple[str, ...],
) -> None:
    """Write local pages and packaged templates; never read or mutate source data."""
    templates = Path(__file__).with_name("reader_templates")
    components = output_dir / "src/components"
    components.mkdir(parents=True, exist_ok=True)
    for path in templates.glob("*.astro"):
        target = output_dir / "src/layouts" if path.name.endswith("Layout.astro") else components
        shutil.copyfile(path, target / path.name)
    _dashboard(output_dir / "src/pages/index.astro", "../components/Dashboard.astro", scope, generated_at, thoughts, scopes)
    dashboards = sorted(set(scopes) | ({scope} if scope != "all scopes" else set()))
    for dashboard_scope in dashboards:
        path = output_dir / "src/pages/scopes" / dashboard_scope / "index.astro"
        path.parent.mkdir(parents=True, exist_ok=True)
        selected = [thought for thought in thoughts if thought["scope"] == dashboard_scope or thought["scope"].startswith(dashboard_scope + "/")]
        children = tuple(item for item in scopes if item == dashboard_scope or item.startswith(dashboard_scope + "/"))
        relative = "../" * (len(dashboard_scope.split("/")) + 2) + "components/Dashboard.astro"
        _dashboard(path, relative, dashboard_scope, generated_at, selected, children)


def _dashboard(path, component, scope, generated_at, thoughts, scopes):
    # JSON strings stay in server frontmatter; Astro escapes values in templates.
    data = {"scope": scope, "generatedAt": generated_at, "thoughts": thoughts, "scopes": scopes}
    path.write_text(
        f'---\nimport Dashboard from {json.dumps(component)};\nconst data = {json.dumps(data, indent=2)};\n---\n'
        f'<!-- Input scope: {scope}; Generated at: {generated_at}. Static snapshot; not a live view. -->\n'
        '<Dashboard {...data} />\n', encoding="utf-8",
    )

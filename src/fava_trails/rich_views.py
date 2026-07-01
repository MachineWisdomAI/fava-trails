"""Minimal FAVA Rich Views reader generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .config import sanitize_scope_path
from .models import ThoughtRecord

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_SAFE_THOUGHT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ReaderThought:
    """View model for a generated FAVA reader thought page."""

    thought_id: str
    title: str
    content: str
    namespace: str
    source_path: str
    source_type: str
    validation_status: str
    agent_id: str
    confidence: float
    tags: tuple[str, ...]
    route: str


@dataclass(frozen=True)
class GenerationResult:
    """Summary returned after reader generation."""

    scope: str
    output_dir: Path
    generated_at: datetime
    thought_count: int
    routes: tuple[str, ...]


def generate_reader(
    *,
    trails_dir: Path | str,
    scope: str,
    output_dir: Path | str,
    generated_at: datetime | None = None,
) -> GenerationResult:
    """Generate a minimal plain-Astro reader from FAVA source thought records."""

    safe_scope = sanitize_scope_path(scope)
    source_root = Path(trails_dir)
    destination = Path(output_dir)
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    thoughts = _load_reader_thoughts(source_root, safe_scope)
    _write_reader(destination, safe_scope, timestamp, thoughts)

    return GenerationResult(
        scope=safe_scope,
        output_dir=destination,
        generated_at=timestamp,
        thought_count=len(thoughts),
        routes=tuple(thought.route for thought in thoughts),
    )


def _load_reader_thoughts(trails_dir: Path, scope: str) -> list[ReaderThought]:
    thoughts_dir = trails_dir / scope / "thoughts"
    if not thoughts_dir.is_dir():
        raise ValueError(f"No FAVA thoughts found for scope {scope!r} at {thoughts_dir}")

    seen: dict[str, Path] = {}
    thoughts: list[ReaderThought] = []
    for path in sorted(p for p in thoughts_dir.rglob("*.md") if p.name != ".gitkeep"):
        raw_text = path.read_text(encoding="utf-8")
        raw_frontmatter = _read_raw_frontmatter(raw_text)
        record = ThoughtRecord.from_markdown(raw_text)
        thought_id = record.thought_id
        _validate_reader_thought_id(thought_id, path)
        if thought_id in seen:
            raise ValueError(f"Duplicate thought_id {thought_id} in {path} and {seen[thought_id]}")
        seen[thought_id] = path

        try:
            namespace = str(path.parent.relative_to(thoughts_dir))
        except ValueError:
            namespace = path.parent.name
        source_path = str(path.relative_to(trails_dir))
        fm = record.frontmatter
        thoughts.append(
            ReaderThought(
                thought_id=thought_id,
                title=_derive_title(raw_frontmatter, record.content),
                content=record.content,
                namespace=namespace,
                source_path=source_path,
                source_type=fm.source_type.value,
                validation_status=fm.validation_status.value,
                agent_id=fm.agent_id,
                confidence=fm.confidence,
                tags=tuple(fm.metadata.tags),
                route=f"/id/{thought_id}/",
            )
        )

    return sorted(thoughts, key=lambda thought: thought.thought_id)


def _validate_reader_thought_id(thought_id: str, source_path: Path) -> None:
    if not _SAFE_THOUGHT_ID_RE.fullmatch(thought_id):
        raise ValueError(f"Unsafe thought_id {thought_id!r} in {source_path}")


def _read_raw_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1]) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _derive_title(frontmatter: dict[str, Any], content: str) -> str:
    explicit_title = frontmatter.get("title")
    if isinstance(explicit_title, str) and explicit_title.strip():
        return _normalize_title(explicit_title)

    heading = _HEADING_RE.search(content)
    if heading:
        return _normalize_title(heading.group(1))

    for line in content.splitlines():
        candidate = _normalize_title(line)
        if candidate:
            return _truncate_title(candidate)

    return "Untitled thought"


def _normalize_title(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip().strip("#").strip())


def _truncate_title(value: str, max_length: int = 80) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "..."


def _write_reader(output_dir: Path, scope: str, generated_at: datetime, thoughts: list[ReaderThought]) -> None:
    generated_at_iso = generated_at.isoformat()

    (output_dir / "src/pages/id").mkdir(parents=True, exist_ok=True)
    (output_dir / "src/data").mkdir(parents=True, exist_ok=True)
    (output_dir / "src/layouts").mkdir(parents=True, exist_ok=True)

    _write_package_json(output_dir)
    _write_astro_config(output_dir)
    _write_readme(output_dir, scope, generated_at_iso)
    _write_generated_metadata(output_dir, scope, generated_at_iso, thoughts)
    _write_index(output_dir, scope, generated_at_iso, thoughts)
    _write_layout(output_dir)
    for thought in thoughts:
        _write_thought_page(output_dir, scope, generated_at_iso, thought)


def _write_package_json(output_dir: Path) -> None:
    package = {
        "name": "fava-reader",
        "private": True,
        "type": "module",
        "scripts": {
            "dev": "astro dev",
            "build": "astro build",
            "preview": "astro preview",
        },
        "devDependencies": {
            "astro": "latest",
        },
    }
    (output_dir / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")


def _write_astro_config(output_dir: Path) -> None:
    (output_dir / "astro.config.mjs").write_text(
        "import { defineConfig } from 'astro/config';\n\n"
        "export default defineConfig({\n"
        "  output: 'static',\n"
        "});\n",
        encoding="utf-8",
    )


def _write_readme(output_dir: Path, scope: str, generated_at: str) -> None:
    (output_dir / "README.md").write_text(
        f"""# FAVA Reader

This is a static snapshot generated from FAVA source records.
It is not a live view. Regenerate it when the trail changes.

- Input scope: {scope}
- Generated at: {generated_at}

## Build

```bash
npm install
npm run build
npm run preview
```
""",
        encoding="utf-8",
    )


def _write_generated_metadata(output_dir: Path, scope: str, generated_at: str, thoughts: list[ReaderThought]) -> None:
    metadata = {
        "inputScope": scope,
        "generatedAt": generated_at,
        "generator": "fava-trails rich-view generate",
        "snapshotNotice": "Static snapshot; not a live view.",
        "thoughtCount": len(thoughts),
        "routes": [thought.route for thought in thoughts],
    }
    (output_dir / "src/data/generated.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def _write_index(output_dir: Path, scope: str, generated_at: str, thoughts: list[ReaderThought]) -> None:
    thought_data = [
        {
            "thoughtId": thought.thought_id,
            "title": thought.title,
            "route": thought.route,
            "namespace": thought.namespace,
            "sourceType": thought.source_type,
            "validationStatus": thought.validation_status,
            "sourcePath": thought.source_path,
        }
        for thought in thoughts
    ]
    (output_dir / "src/pages/index.astro").write_text(
        f"""---
const thoughts = {json.dumps(thought_data, indent=2)};
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>FAVA Reader - {scope}</title>
    <style>
      :root {{
        color: #161616;
        background: #f7f7f4;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      body {{
        margin: 0;
      }}
      main {{
        max-width: 980px;
        margin: 0 auto;
        padding: 32px 20px 48px;
      }}
      header {{
        border-bottom: 1px solid #d8d8d0;
        margin-bottom: 24px;
        padding-bottom: 16px;
      }}
      h1 {{
        font-size: 1.9rem;
        margin: 0 0 12px;
      }}
      .meta {{
        color: #555;
        display: flex;
        flex-wrap: wrap;
        gap: 8px 18px;
        font-size: 0.92rem;
        margin: 0;
      }}
      .notice {{
        background: #fff8d8;
        border: 1px solid #e1ce75;
        border-radius: 6px;
        margin: 18px 0 0;
        padding: 10px 12px;
      }}
      ul {{
        list-style: none;
        margin: 0;
        padding: 0;
      }}
      li {{
        background: #fff;
        border: 1px solid #ddd;
        border-radius: 6px;
        margin-bottom: 10px;
        padding: 14px 16px;
      }}
      a {{
        color: #135d54;
        font-weight: 650;
      }}
      code {{
        font-size: 0.82rem;
      }}
      .row-meta {{
        color: #666;
        display: flex;
        flex-wrap: wrap;
        gap: 8px 14px;
        margin-top: 8px;
      }}
    </style>
  </head>
  <body>
    <main>
      <header>
        <h1>FAVA Reader</h1>
        <p class="meta">
          <span>Input scope: {scope}</span>
          <span>Generated at: {generated_at}</span>
          <span>{len(thoughts)} thoughts</span>
        </p>
        <p class="notice">Static snapshot generated from FAVA source records; this is not a live view.</p>
      </header>
      <ul>
        {{thoughts.map((thought) => (
          <li>
            <a href={{thought.route}}>{{thought.title}}</a>
            <div class="row-meta">
              <code>{{thought.thoughtId}}</code>
              <span>{{thought.namespace}}</span>
              <span>{{thought.sourceType}}</span>
              <span>{{thought.validationStatus}}</span>
              <span>{{thought.sourcePath}}</span>
            </div>
          </li>
        ))}}
      </ul>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )


def _write_layout(output_dir: Path) -> None:
    (output_dir / "src/layouts/ThoughtLayout.astro").write_text(
        """---
const { frontmatter } = Astro.props;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{frontmatter.title}</title>
    <style>
      :root {
        color: #161616;
        background: #f7f7f4;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      body {
        margin: 0;
      }
      main {
        max-width: 880px;
        margin: 0 auto;
        padding: 32px 20px 56px;
      }
      a {
        color: #135d54;
      }
      header {
        border-bottom: 1px solid #d8d8d0;
        margin-bottom: 24px;
        padding-bottom: 16px;
      }
      h1 {
        font-size: 1.8rem;
        margin: 0 0 12px;
      }
      dl {
        display: grid;
        gap: 8px 14px;
        grid-template-columns: max-content 1fr;
      }
      dt {
        color: #555;
        font-weight: 650;
      }
      dd {
        margin: 0;
      }
      code {
        font-size: 0.85rem;
      }
      .notice {
        background: #fff8d8;
        border: 1px solid #e1ce75;
        border-radius: 6px;
        margin: 16px 0 0;
        padding: 10px 12px;
      }
      article {
        background: #fff;
        border: 1px solid #ddd;
        border-radius: 6px;
        padding: 22px;
      }
    </style>
  </head>
  <body>
    <main>
      <p><a href="/">Back to reader index</a></p>
      <header>
        <h1>{frontmatter.title}</h1>
        <dl>
          <dt>Thought ID</dt>
          <dd><code>{frontmatter.thoughtId}</code></dd>
          <dt>Input scope</dt>
          <dd>{frontmatter.inputScope}</dd>
          <dt>Generated at</dt>
          <dd>{frontmatter.generatedAt}</dd>
          <dt>Namespace</dt>
          <dd>{frontmatter.namespace}</dd>
          <dt>Source type</dt>
          <dd>{frontmatter.sourceType}</dd>
          <dt>Validation</dt>
          <dd>{frontmatter.validationStatus}</dd>
          <dt>Source path</dt>
          <dd><code>{frontmatter.sourcePath}</code></dd>
        </dl>
        <p class="notice">Static snapshot generated from FAVA source records; this is not a live view.</p>
      </header>
      <article>
        <slot />
      </article>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )


def _write_thought_page(output_dir: Path, scope: str, generated_at: str, thought: ReaderThought) -> None:
    frontmatter = [
        "---",
        'layout: "../../layouts/ThoughtLayout.astro"',
        f"title: {_yaml_string(thought.title)}",
        f"thoughtId: {_yaml_string(thought.thought_id)}",
        f"inputScope: {_yaml_string(scope)}",
        f"generatedAt: {_yaml_string(generated_at)}",
        f"namespace: {_yaml_string(thought.namespace)}",
        f"sourceType: {_yaml_string(thought.source_type)}",
        f"validationStatus: {_yaml_string(thought.validation_status)}",
        f"agentId: {_yaml_string(thought.agent_id)}",
        f"confidence: {thought.confidence}",
        f"sourcePath: {_yaml_string(thought.source_path)}",
    ]
    if thought.tags:
        frontmatter.append("tags:")
        frontmatter.extend(f"  - {_yaml_string(tag)}" for tag in thought.tags)
    else:
        frontmatter.append("tags: []")
    frontmatter.append("---")
    page = "\n".join(frontmatter) + "\n" + thought.content.rstrip() + "\n"
    (output_dir / "src/pages/id" / f"{thought.thought_id}.md").write_text(page, encoding="utf-8")


def _yaml_string(value: str) -> str:
    return json.dumps(value)

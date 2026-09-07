"""Generate a local Astro reader from canonical FAVA Markdown records."""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .config import sanitize_scope_path
from .governance import RecordSnapshot, Visibility, is_effectively_superseded, read_snapshot

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_SAFE_THOUGHT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_WHITESPACE_RE = re.compile(r"\s+")
_GENERATED_READER_MARKER = "fava-trails rich-view generate"
_GENERATED_READER_ARTIFACTS = ("src", "package.json", "astro.config.mjs", "README.md")


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
    scope: str
    created_at: str = ""
    parent_id: str | None = None
    superseded_by: str | None = None
    superseded_scope: str | None = None
    supersedes_id: str | None = None
    supersedes_scope: str | None = None
    is_superseded: bool = False
    intent_ref: str | None = None
    relationships: tuple[tuple[str, str], ...] = ()
    fallback_route: str = ""


@dataclass(frozen=True)
class GenerationResult:
    """Summary returned after reader generation."""

    scope: str
    output_dir: Path
    generated_at: datetime
    thought_count: int
    routes: tuple[str, ...]
    scopes: tuple[str, ...]


def generate_reader(
    *,
    trails_dir: Path | str,
    scope: str,
    output_dir: Path | str,
    generated_at: datetime | None = None,
    visibility: Visibility | None = None,
) -> GenerationResult:
    """Generate a minimal plain-Astro reader from FAVA source thought records."""

    return generate_reader_for_scopes(
        trails_dir=trails_dir, scopes=[scope], output_dir=output_dir, generated_at=generated_at, visibility=visibility,
    )


def generate_reader_for_scopes(
    *,
    trails_dir: Path | str,
    scopes: list[str] | tuple[str, ...] | None,
    output_dir: Path | str,
    generated_at: datetime | None = None,
    visibility: Visibility | None = None,
) -> GenerationResult:
    """Generate a minimal plain-Astro reader for selected or all discovered scopes."""

    source_root = Path(trails_dir)
    destination = Path(output_dir)
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    safe_scopes = tuple(_resolve_reader_scopes(source_root, scopes))
    all_thoughts: list[ReaderThought] = []
    seen: dict[str, Path] = {}
    snapshot = read_snapshot(source_root, strict=True)
    for scope in safe_scopes:
        for thought, source_path in _load_reader_thoughts_with_sources(source_root, scope, visibility, snapshot=snapshot):
            if thought.thought_id in seen:
                raise ValueError(f"Duplicate thought_id {thought.thought_id} in {source_path} and {seen[thought.thought_id]}")
            seen[thought.thought_id] = source_path
            all_thoughts.append(thought)

    display_scope = sanitize_scope_path(scopes[0]) if scopes and len(scopes) == 1 else (safe_scopes[0] if len(safe_scopes) == 1 else "all scopes")
    all_thoughts = _assign_routes(sorted(all_thoughts, key=lambda thought: (thought.scope, thought.thought_id)))
    _write_reader(destination, display_scope, timestamp, all_thoughts, input_scopes=safe_scopes)

    return GenerationResult(
        scope=display_scope,
        output_dir=destination,
        generated_at=timestamp,
        thought_count=len(all_thoughts),
        routes=tuple(thought.route for thought in all_thoughts),
        scopes=safe_scopes,
    )


def _load_reader_thoughts(trails_dir: Path, scope: str, visibility: Visibility | None = None) -> list[ReaderThought]:
    return [thought for thought, _source_path in _load_reader_thoughts_with_sources(trails_dir, scope, visibility)]


def _load_reader_thoughts_with_sources(
    trails_dir: Path, scope: str, visibility: Visibility | None = None,
    *, snapshot: RecordSnapshot | None = None,
) -> list[tuple[ReaderThought, Path]]:
    thoughts_dir = trails_dir / scope / "thoughts"
    if not thoughts_dir.is_dir():
        raise ValueError(f"No FAVA thoughts found for scope {scope!r} at {thoughts_dir}")

    visibility = visibility or Visibility()
    snapshot = snapshot if snapshot is not None else read_snapshot(trails_dir, strict=True)
    texts, records, by_id = snapshot.texts, snapshot.records, snapshot.by_id
    seen: dict[str, Path] = {}
    thoughts: list[tuple[ReaderThought, Path]] = []
    for path in sorted(p for p in texts if p.is_relative_to(thoughts_dir)):
        raw_text = texts[path]
        raw_frontmatter = _read_raw_frontmatter(raw_text)
        if not isinstance(raw_frontmatter.get("thought_id"), str) or not raw_frontmatter["thought_id"]:
            raise ValueError(f"Missing thought_id in FAVA frontmatter: {path}")
        record = records[path]
        if not visibility.allows(record, by_id):
            continue
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
        thought = ReaderThought(
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
            scope=scope,
            created_at=fm.created_at.isoformat(),
            parent_id=fm.parent_id,
            superseded_by=fm.superseded_by,
            superseded_scope=fm.superseded_scope,
            supersedes_id=fm.supersedes_id,
            supersedes_scope=fm.supersedes_scope,
            is_superseded=is_effectively_superseded(record, by_id),
            intent_ref=fm.intent_ref,
            relationships=tuple((rel.type.value, rel.target_id) for rel in fm.relationships),
            fallback_route=f"/id/{thought_id}/",
        )
        thoughts.append((thought, path))

    return sorted(thoughts, key=lambda item: item[0].thought_id)


def _resolve_reader_scopes(trails_dir: Path, scopes: list[str] | tuple[str, ...] | None) -> list[str]:
    discovered = discover_reader_scopes(trails_dir)
    if scopes:
        selected = set()
        for raw_scope in scopes:
            requested = sanitize_scope_path(raw_scope)
            matches = [scope for scope in discovered if scope == requested or scope.startswith(requested + "/")]
            if not matches:
                raise ValueError(f"No FAVA thoughts found for scope {requested!r}")
            selected.update(matches)
        return sorted(selected)
    if not discovered:
        raise ValueError(f"No FAVA scopes found under {trails_dir}")
    return discovered


def discover_reader_scopes(trails_dir: Path | str) -> list[str]:
    """Discover scope paths with a thoughts/ directory under trails_dir."""

    root = Path(trails_dir)
    scopes: list[str] = []
    if not root.exists():
        return scopes
    for thoughts_dir in sorted(root.rglob("thoughts")):
        if not thoughts_dir.is_dir():
            continue
        try:
            scope = str(thoughts_dir.parent.relative_to(root))
        except ValueError:
            continue
        scopes.append(scope)
    return sorted(set(scopes))


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


def _write_reader(
    output_dir: Path,
    scope: str,
    generated_at: datetime,
    thoughts: list[ReaderThought],
    *,
    input_scopes: tuple[str, ...] | None = None,
) -> None:
    generated_at_iso = generated_at.isoformat()
    scopes = input_scopes or (scope,)

    _prepare_reader_output_dir(output_dir)

    (output_dir / "src/pages/id").mkdir(parents=True, exist_ok=True)
    (output_dir / "src/data").mkdir(parents=True, exist_ok=True)
    (output_dir / "src/layouts").mkdir(parents=True, exist_ok=True)

    _write_package_json(output_dir)
    _write_astro_config(output_dir)
    _write_readme(output_dir, scope, generated_at_iso, scopes)
    _write_generated_metadata(output_dir, scope, generated_at_iso, thoughts, scopes)
    from .reader_ui import write_reader_ui

    write_reader_ui(output_dir, scope, generated_at_iso, [_thought_data(thought, thoughts) for thought in thoughts], scopes)
    for thought in thoughts:
        _write_thought_page(output_dir, scope, generated_at_iso, thought, thoughts)


def _prepare_reader_output_dir(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {output_dir}")
    if not any(output_dir.iterdir()):
        return
    if not _is_generated_reader_output_dir(output_dir):
        raise ValueError(
            f"refusing to overwrite non-reader output directory {output_dir}; "
            "choose an empty directory or a previous fava-trails reader output"
        )

    # Clean prior generated artifacts so re-runs don't leave stale pages from previous generations.
    for name in _GENERATED_READER_ARTIFACTS:
        p = output_dir / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink(missing_ok=True)


def is_generated_reader_output_dir(output_dir: Path | str) -> bool:
    """Return True when output_dir is a previous FAVA reader generation."""

    return _is_generated_reader_output_dir(Path(output_dir))


def _is_generated_reader_output_dir(output_dir: Path) -> bool:
    marker_path = output_dir / "src/data/generated.json"
    if not marker_path.is_file():
        return False
    try:
        metadata = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(metadata, dict) and metadata.get("generator") == _GENERATED_READER_MARKER


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
            "astro": "^7.0.0",
            "rehype-sanitize": "^6.0.0",
            "@astrojs/markdown-remark": "^7.3.0",
        },
    }
    (output_dir / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")


def _write_astro_config(output_dir: Path) -> None:
    (output_dir / "astro.config.mjs").write_text(
        "import { defineConfig } from 'astro/config';\n"
        "import rehypeSanitize from 'rehype-sanitize';\n"
        "import { unified } from '@astrojs/markdown-remark';\n\n"
        "export default defineConfig({\n"
        "  output: 'static',\n"
        "  devToolbar: { enabled: false },\n"
        "  markdown: { processor: unified({ rehypePlugins: [rehypeSanitize] }) },\n"
        "});\n",
        encoding="utf-8",
    )


def _write_readme(output_dir: Path, scope: str, generated_at: str, scopes: tuple[str, ...]) -> None:
    scope_lines = "\n".join(f"  - {input_scope}" for input_scope in scopes)
    (output_dir / "README.md").write_text(
        f"""# FAVA Reader

This is a static snapshot generated from FAVA source records.
It is not a live view. Regenerate it when the trail changes.

- Input scope: {scope}
- Generated at: {generated_at}

## Included scopes

{scope_lines}

## Build

```bash
npm install
npm run build
npm run preview
```
""",
        encoding="utf-8",
    )


def _write_generated_metadata(
    output_dir: Path,
    scope: str,
    generated_at: str,
    thoughts: list[ReaderThought],
    scopes: tuple[str, ...],
) -> None:
    metadata = {
        "inputScope": scope,
        "inputScopes": list(scopes),
        "generatedAt": generated_at,
        "generator": "fava-trails rich-view generate",
        "snapshotNotice": "Static snapshot; not a live view.",
        "thoughtCount": len(thoughts),
        "routes": [thought.route for thought in thoughts],
        "thoughtRoutes": {thought.thought_id: {"canonical": thought.route, "fallback": thought.fallback_route} for thought in thoughts},
    }
    (output_dir / "src/data/generated.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def _assign_routes(thoughts: list[ReaderThought]) -> list[ReaderThought]:
    """Titles name human routes; the /id route always preserves record identity."""
    def slug(title: str) -> str:
        ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:80].rstrip("-") or "thought"

    stems = {thought.thought_id: f"/{thought.scope}/{slug(thought.title)}" for thought in thoughts}
    counts = Counter(stems.values())
    used = {f"/id/{thought.thought_id}/" for thought in thoughts}
    used.update(f"/scopes/{thought.scope}/" for thought in thoughts)
    routes = []
    for thought in thoughts:
        stem = stems[thought.thought_id]
        route = stem + "/"
        if counts[stem] > 1 or route in used:
            length = min(8, len(thought.thought_id))
            while True:
                route = f"{stem}-{thought.thought_id[-length:]}/"
                if route not in used:
                    break
                length += 1
                if length > len(thought.thought_id):
                    raise ValueError(f"Cannot assign unique route for {thought.thought_id}")
        used.add(route)
        routes.append(replace(thought, route=route, fallback_route=f"/id/{thought.thought_id}/"))
    return routes


def _thought_data(thought: ReaderThought, thoughts: list[ReaderThought]) -> dict[str, Any]:
    """Project only stored semantics; missing targets carry no inferred metadata."""
    by_id = {item.thought_id: item for item in thoughts}

    def target(thought_id: str, target_scope: str | None = None) -> dict[str, Any]:
        found = by_id.get(thought_id)
        if found and target_scope and found.scope != target_scope:
            found = None
        return {"thoughtId": thought_id, "title": found.title if found else thought_id,
                "route": found.route if found else None, "resolved": found is not None,
                "scope": target_scope or (found.scope if found else None)}

    def parent_scope(item: ReaderThought) -> str | None:
        return item.supersedes_scope if item.parent_id == item.supersedes_id else None

    outbound = [{"type": kind, **target(tid)} for kind, tid in thought.relationships]
    inbound = [{"type": kind, **target(other.thought_id)} for other in thoughts
               for kind, tid in other.relationships if tid == thought.thought_id]
    # Traverse only explicit parentage and supersession, preserving branch/cycle evidence.
    lineage = []
    pending = [thought.thought_id]
    visited = set()
    edges = []
    for other in thoughts:
        if other.parent_id:
            edges.append((other.thought_id, "parent", other.parent_id, parent_scope(other)))
        if other.superseded_by:
            kind = "superseded by" if other.is_superseded else "replacement link (not effective)"
            edges.append((other.thought_id, kind, other.superseded_by, other.superseded_scope))
        if other.supersedes_id:
            kind = "supersedes" if other.validation_status == "approved" else "replacement proposal for"
            edges.append((other.thought_id, kind, other.supersedes_id, other.supersedes_scope))
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for source, kind, dest, dest_scope in edges:
            destination = target(dest, dest_scope)
            if current != source and not (current == dest and destination["resolved"]):
                continue
            edge = {"source": target(source), "type": kind, "target": destination}
            if edge not in lineage:
                lineage.append(edge)
            neighbors = (source, dest) if destination["resolved"] else (source,)
            for neighbor in neighbors:
                if neighbor in by_id and neighbor not in visited:
                    pending.append(neighbor)

    return {
        "thoughtId": thought.thought_id, "title": thought.title, "route": thought.route,
        "fallbackRoute": thought.fallback_route, "slug": thought.route.rstrip("/").rsplit("/", 1)[-1],
        "namespace": thought.namespace, "sourceType": thought.source_type,
        "validationStatus": thought.validation_status, "sourcePath": thought.source_path,
        "scope": thought.scope, "agentId": thought.agent_id, "confidence": thought.confidence,
        "tags": thought.tags, "createdAt": thought.created_at,
        "excerpt": _WHITESPACE_RE.sub(" ", thought.content).strip()[:200],
        "supersededBy": target(thought.superseded_by, thought.superseded_scope) if thought.superseded_by else None,
        "isSuperseded": thought.is_superseded,
        "parent": target(thought.parent_id, parent_scope(thought)) if thought.parent_id else None,
        "intent": target(thought.intent_ref) if thought.intent_ref else None,
        "outbound": outbound, "inbound": inbound, "lineage": lineage,
        "relationshipCount": len(outbound) + len(inbound),
    }


def _write_thought_page(
    output_dir: Path, scope: str, generated_at: str, thought: ReaderThought, thoughts: list[ReaderThought],
) -> None:
    data = _thought_data(thought, thoughts)
    data.update(inputScope=scope, generatedAt=generated_at)
    # Both routes render the same source body, generated together from one record.
    for route in (thought.fallback_route, thought.route):
        parts = route.strip("/").split("/")
        page_path = output_dir / "src/pages" / Path(*parts[:-1]) / f"{parts[-1]}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        layout = "../" * len(parts) + "layouts/ThoughtLayout.astro"
        frontmatter = ["---", f"layout: {_yaml_string(layout)}"]
        frontmatter.extend(f"{key}: {json.dumps(value)}" for key, value in data.items())
        page = "\n".join(frontmatter) + "\n---\n" + thought.content.rstrip() + "\n"
        page_path.write_text(page, encoding="utf-8")


def _yaml_string(value: str) -> str:
    return json.dumps(value)

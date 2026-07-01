"""Generate a minimal Astro reader from FAVA thought records."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import ThoughtRecord


class ReaderGenerationError(ValueError):
    """Raised when source thought records cannot be rendered truthfully."""


@dataclass(frozen=True)
class ReaderGenerationResult:
    """Summary of a generated reader input set."""

    output_dir: Path
    scope: str
    generated_at: str
    thought_count: int


@dataclass(frozen=True)
class ThoughtView:
    """FAVA-aware view model for one thought record."""

    record: ThoughtRecord
    raw_frontmatter: dict[str, Any]
    source_path: Path
    scope: str
    namespace: str
    title: str

    @property
    def thought_id(self) -> str:
        return self.record.thought_id

    def to_json(self, source_root: Path) -> dict[str, Any]:
        fm = self.record.frontmatter
        metadata = fm.metadata.model_dump(mode="json")
        return {
            "thought_id": fm.thought_id,
            "title": self.title,
            "route": f"/thoughts/{fm.thought_id}/",
            "scope": self.scope,
            "namespace": self.namespace,
            "source_path": self.source_path.relative_to(source_root).as_posix(),
            "source_type": str(fm.source_type),
            "validation_status": str(fm.validation_status),
            "agent_id": fm.agent_id,
            "confidence": fm.confidence,
            "created_at": fm.created_at.isoformat(),
            "parent_id": fm.parent_id,
            "superseded_by": fm.superseded_by,
            "intent_ref": fm.intent_ref,
            "tags": metadata.get("tags", []),
            "metadata": metadata,
            "relationships": [
                {"type": str(relationship.type), "target_id": relationship.target_id}
                for relationship in fm.relationships
            ],
            "excerpt": derive_excerpt(self.record.content),
        }


def generate_reader(
    *,
    source: Path,
    scope: str,
    output_dir: Path,
    build: bool = False,
) -> ReaderGenerationResult:
    """Generate Astro inputs for a minimal FAVA reader.

    ``source`` may be a FAVA data repo root, a ``trails`` directory, or a single
    scope directory containing ``thoughts/``. The generated files are derived
    from source records and are intended only as static reader inputs.
    """

    source = source.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    generated_at = datetime.now(UTC).isoformat()

    source_root, scope_roots = resolve_scope_roots(source, scope)
    thoughts = load_thought_views(source_root, scope_roots)
    write_astro_inputs(output_dir, source_root, scope, generated_at, thoughts)

    if build:
        subprocess.run(["npm", "run", "build"], cwd=output_dir, check=True)

    return ReaderGenerationResult(
        output_dir=output_dir,
        scope=scope,
        generated_at=generated_at,
        thought_count=len(thoughts),
    )


def resolve_scope_roots(source: Path, scope: str) -> tuple[Path, list[Path]]:
    """Return ``(source_root, scope_roots)`` for the requested scope and descendants."""

    candidates: list[tuple[Path, Path]] = []
    if (source / "trails").is_dir():
        candidates.append((source / "trails", source / "trails" / scope))
    candidates.append((source, source / scope))
    if (source / "thoughts").is_dir():
        candidates.append((source.parent, source))

    for source_root, scope_root in candidates:
        if (scope_root / "thoughts").is_dir():
            roots = [scope_root]
            roots.extend(
                sorted(
                    parent.parent
                    for parent in scope_root.glob("**/thoughts")
                    if parent.parent != scope_root
                )
            )
            return source_root.resolve(), [root.resolve() for root in roots]

    raise ReaderGenerationError(
        f"Could not find thoughts for scope {scope!r} under {source}. "
        "Pass a data repo root, trails directory, or scope directory."
    )


def load_thought_views(source_root: Path, scope_roots: list[Path]) -> list[ThoughtView]:
    seen: dict[str, Path] = {}
    thoughts: list[ThoughtView] = []

    for scope_root in scope_roots:
        thoughts_dir = scope_root / "thoughts"
        for path in sorted(thoughts_dir.rglob("*.md")):
            if path.name == ".gitkeep":
                continue
            relative_to_thoughts = path.relative_to(thoughts_dir)
            namespace = relative_to_thoughts.parts[0]
            raw_text = path.read_text()
            record, raw_frontmatter = parse_source_record(raw_text, path)
            if record.thought_id in seen:
                raise ReaderGenerationError(
                    f"Duplicate thought_id {record.thought_id} in {path} and {seen[record.thought_id]}"
                )
            seen[record.thought_id] = path
            thoughts.append(
                ThoughtView(
                    record=record,
                    raw_frontmatter=raw_frontmatter,
                    source_path=path,
                    scope=scope_root.relative_to(source_root).as_posix(),
                    namespace=namespace,
                    title=derive_title(raw_frontmatter, record.content),
                )
            )

    return sorted(thoughts, key=lambda thought: thought.record.frontmatter.created_at, reverse=True)


def parse_source_record(text: str, path: Path) -> tuple[ThoughtRecord, dict[str, Any]]:
    if not text.startswith("---\n"):
        raise ReaderGenerationError(f"Malformed FAVA record {path}: missing YAML frontmatter")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ReaderGenerationError(f"Malformed FAVA record {path}: unterminated YAML frontmatter")

    try:
        raw_frontmatter = yaml.safe_load(parts[1].strip()) or {}
        record = ThoughtRecord.from_markdown(text)
    except yaml.YAMLError as exc:
        raise ReaderGenerationError(f"Malformed frontmatter in {path}: {exc}") from exc
    except ValidationError as exc:
        raise ReaderGenerationError(f"Invalid FAVA frontmatter in {path}: {exc}") from exc

    if not isinstance(raw_frontmatter, dict):
        raise ReaderGenerationError(f"Malformed frontmatter in {path}: expected a mapping")
    return record, raw_frontmatter


def derive_title(frontmatter: dict[str, Any], body: str) -> str:
    title = str(frontmatter.get("title", "")).strip()
    if title:
        return title

    for line in body.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            return clean_inline_markdown(match.group(1))

    return derive_excerpt(body, fallback="Untitled thought")


def derive_excerpt(body: str, *, fallback: str = "") -> str:
    for line in body.splitlines():
        text = clean_inline_markdown(line)
        if text:
            return text[:157].rstrip() + "..." if len(text) > 160 else text
    return fallback


def clean_inline_markdown(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_~>#-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def write_astro_inputs(
    output_dir: Path,
    source_root: Path,
    scope: str,
    generated_at: str,
    thoughts: list[ThoughtView],
) -> None:
    generated_content_dir = output_dir / "src" / "content" / "thoughts"
    generated_data_dir = output_dir / "src" / "data"
    shutil.rmtree(generated_content_dir, ignore_errors=True)
    generated_content_dir.mkdir(parents=True, exist_ok=True)
    generated_data_dir.mkdir(parents=True, exist_ok=True)

    for thought in thoughts:
        target = generated_content_dir / f"{thought.thought_id}.md"
        target.write_text(thought.source_path.read_text())

    data = {
        "metadata": {
            "input_scope": scope,
            "generated_at": generated_at,
            "source_root": source_root.as_posix(),
            "thought_count": len(thoughts),
            "static_snapshot": True,
            "freshness_notice": "This is a manually generated static snapshot, not a live view.",
        },
        "thoughts": [thought.to_json(source_root) for thought in thoughts],
    }
    (generated_data_dir / "fava-reader.json").write_text(json.dumps(data, indent=2) + "\n")

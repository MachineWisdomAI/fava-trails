"""Governed visibility and trusted, process-owned MCP identity.

Tool arguments select a view; they never establish a caller's authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .models import ThoughtRecord, ValidationStatus
from .transactions import snapshot_texts


@dataclass(frozen=True)
class Principal:
    agent_id: str | None = None
    operator: bool = False


def runtime_principal() -> Principal:
    """Configured by the operator on a dedicated process, never by a tool call."""
    return Principal(
        agent_id=os.environ.get("FAVA_TRAILS_AGENT_ID", "").strip() or None,
        operator=os.environ.get("FAVA_TRAILS_OPERATOR", "") == "1",
    )


@dataclass(frozen=True)
class Visibility:
    mode: str = "governed"
    principal: Principal = Principal()
    statuses: tuple[str, ...] = ()
    include_superseded: bool = False

    def __post_init__(self):
        if self.mode not in {"governed", "authoring", "history"}:
            raise ValueError("mode must be governed, authoring, or history")
        if self.mode == "authoring" and not self.principal.agent_id:
            raise PermissionError("authoring requires a server-configured agent identity")
        if self.mode == "history" and not self.principal.operator:
            raise PermissionError("history requires an operator-controlled endpoint")
        if self.include_superseded and self.mode != "history":
            raise ValueError("include_superseded requires explicit history mode")
        if self.statuses and self.mode == "governed":
            raise ValueError("status selection requires authoring or history mode")
        for status in self.statuses:
            ValidationStatus(status)
        if self.mode == "authoring" and set(self.statuses) - {"draft", "proposed"}:
            raise ValueError("authoring statuses are limited to draft and proposed")

    def allows(self, record: ThoughtRecord, records: dict[str, ThoughtRecord]) -> bool:
        fm = record.frontmatter
        status = fm.validation_status.value
        if self.mode == "governed" and status != "approved":
            return False
        if self.mode == "authoring":
            if status not in (self.statuses or ("draft", "proposed")):
                return False
            if fm.agent_id != self.principal.agent_id:
                return False
        if self.mode == "history" and self.statuses and status not in self.statuses:
            return False
        return self.include_superseded or not is_effectively_superseded(record, records)


def is_effectively_superseded(record: ThoughtRecord, records: dict[str, ThoughtRecord]) -> bool:
    """A legacy or current backlink retires truth only with an approved successor."""
    fm = record.frontmatter
    key = f"{fm.superseded_scope}:{fm.superseded_by}" if fm.superseded_scope else fm.superseded_by
    successor = records.get(key or "")
    return successor is not None and successor.frontmatter.validation_status == ValidationStatus.APPROVED


def read_records(trails_dir: Path) -> dict[Path, ThoughtRecord]:
    result = {}
    for path, text in snapshot_texts(trails_dir).items():
        try:
            result[path] = ThoughtRecord.from_markdown(text)
        except Exception:
            continue
    return result


def record_index(records: dict[Path, ThoughtRecord], trails_dir: Path) -> dict[str, ThoughtRecord]:
    """Qualify new lineage by scope; ambiguous legacy IDs never retire originals."""
    index = {}
    duplicates = set()
    for path, record in records.items():
        scope = str(path.relative_to(trails_dir)).split("/thoughts/", 1)[0]
        index[f"{scope}:{record.thought_id}"] = record
        if record.thought_id in index:
            duplicates.add(record.thought_id)
        index[record.thought_id] = record
    for thought_id in duplicates:
        index.pop(thought_id, None)
    return index


def visibility_from_arguments(arguments: dict, principal: Principal) -> Visibility:
    statuses = arguments.get("statuses") or ()
    if not isinstance(statuses, (tuple, list)):
        raise ValueError("statuses must be an array")
    return Visibility(
        mode=arguments.get("mode", "governed"),
        principal=principal,
        statuses=tuple(statuses),
        include_superseded=arguments.get("include_superseded", False),
    )

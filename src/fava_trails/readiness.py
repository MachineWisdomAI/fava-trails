"""Bounded, non-mutating readiness checks for a FAVA Trails data repository."""

from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import GlobalConfig, ThoughtRecord

MAX_CONFIG_BYTES = 256 * 1024
MAX_THOUGHT_BYTES = 512 * 1024
MAX_TREE_ENTRIES = 100_000
DEFAULT_READINESS_TIMEOUT_SECONDS = 2.0


class ReadinessFailure(Exception):
    """A safe, bounded readiness failure suitable for an HTTP response."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass
class _TreeProbe:
    entries: int = 0
    scopes: int = 0
    records: int = 0
    representative: Path | None = None
    representative_key: str | None = None


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ReadinessFailure("probe_timeout", "data readiness probe exceeded its time limit")


def _read_bounded(
    path: Path,
    *,
    limit: int,
    missing_reason: str,
    unreadable_reason: str,
    too_large_reason: str,
    label: str,
    deadline: float,
) -> bytes:
    _check_deadline(deadline)
    try:
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except FileNotFoundError as exc:
        raise ReadinessFailure(missing_reason, f"{label} is missing") from exc
    except OSError as exc:
        raise ReadinessFailure(unreadable_reason, f"{label} is not readable") from exc
    if len(payload) > limit:
        raise ReadinessFailure(too_large_reason, f"{label} exceeds the readiness read limit")
    _check_deadline(deadline)
    return payload


def _validate_config(data_repo: Path, deadline: float) -> GlobalConfig:
    raw = _read_bounded(
        data_repo / "config.yaml",
        limit=MAX_CONFIG_BYTES,
        missing_reason="config_missing",
        unreadable_reason="config_unreadable",
        too_large_reason="config_too_large",
        label="data repository config",
        deadline=deadline,
    )
    try:
        parsed = yaml.safe_load(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("config must be a mapping")
        config = GlobalConfig(**parsed)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError, ValidationError) as exc:
        raise ReadinessFailure("config_malformed", "data repository config is malformed") from exc
    return config


def _configured_trails_dir(data_repo: Path, config: GlobalConfig) -> Path:
    override = os.environ.get("FAVA_TRAILS_DIR")
    if override:
        return Path(os.path.expanduser(override))
    configured = Path(config.trails_dir)
    return configured if configured.is_absolute() else data_repo / configured


def _directory(
    path: Path,
    *,
    missing_reason: str,
    unreadable_reason: str,
    label: str,
    deadline: float,
) -> Path:
    _check_deadline(deadline)
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
    except FileNotFoundError as exc:
        raise ReadinessFailure(missing_reason, f"{label} is missing") from exc
    except OSError as exc:
        raise ReadinessFailure(unreadable_reason, f"{label} is not accessible") from exc
    if not stat.S_ISDIR(mode):
        raise ReadinessFailure(missing_reason, f"{label} is missing")
    _check_deadline(deadline)
    return resolved


def _entries(path: Path, probe: _TreeProbe, deadline: float) -> list[os.DirEntry[str]]:
    entries: list[os.DirEntry[str]] = []
    _check_deadline(deadline)
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                _check_deadline(deadline)
                probe.entries += 1
                if probe.entries > MAX_TREE_ENTRIES:
                    raise ReadinessFailure(
                        "scope_tree_too_large",
                        "scope tree exceeds the readiness traversal limit",
                    )
                entries.append(entry)
    except ReadinessFailure:
        raise
    except OSError as exc:
        raise ReadinessFailure(
            "scope_tree_unreadable",
            "scope tree cannot be traversed by the runtime identity",
        ) from exc
    return sorted(entries, key=lambda entry: entry.name)


def _is_dir(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError as exc:
        raise ReadinessFailure(
            "scope_tree_unreadable",
            "scope tree cannot be traversed by the runtime identity",
        ) from exc


def _is_file(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_file(follow_symlinks=False)
    except OSError as exc:
        raise ReadinessFailure(
            "scope_tree_unreadable",
            "scope tree cannot be traversed by the runtime identity",
        ) from exc


def _scan_thoughts(
    thoughts_dir: Path,
    trails_dir: Path,
    probe: _TreeProbe,
    deadline: float,
) -> None:
    stack = [thoughts_dir]
    while stack:
        current = stack.pop()
        entries = _entries(current, probe, deadline)
        for entry in reversed(entries):
            path = Path(entry.path)
            if _is_dir(entry):
                stack.append(path)
                continue
            if not _is_file(entry) or path.suffix != ".md":
                continue
            probe.records += 1
            key = path.relative_to(trails_dir).as_posix()
            if probe.representative_key is None or key < probe.representative_key:
                probe.representative = path
                probe.representative_key = key


def _scan_scope_tree(trails_dir: Path, deadline: float) -> _TreeProbe:
    probe = _TreeProbe()
    stack = [trails_dir]
    while stack:
        current = stack.pop()
        entries = _entries(current, probe, deadline)
        for entry in reversed(entries):
            if not _is_dir(entry):
                continue
            path = Path(entry.path)
            if entry.name == "thoughts":
                probe.scopes += 1
                _scan_thoughts(path, trails_dir, probe, deadline)
            else:
                stack.append(path)
    return probe


def _read_representative(path: Path, deadline: float) -> None:
    raw = _read_bounded(
        path,
        limit=MAX_THOUGHT_BYTES,
        missing_reason="thought_unreadable",
        unreadable_reason="thought_unreadable",
        too_large_reason="thought_too_large",
        label="representative thought",
        deadline=deadline,
    )
    try:
        text = raw.decode("utf-8")
        if not text.startswith("---") or len(text.split("---", 2)) < 3:
            raise ValueError("frontmatter is missing")
        record = ThoughtRecord.from_markdown(text)
        if record.thought_id != path.stem:
            raise ValueError("thought id does not match filename")
    except (UnicodeDecodeError, ValueError, yaml.YAMLError, ValidationError) as exc:
        raise ReadinessFailure("thought_malformed", "representative thought is malformed") from exc


def probe_data_repository(
    data_repo: Path,
    *,
    timeout_seconds: float = DEFAULT_READINESS_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Prove that configured trail data is traversable and representative data parses.

    The probe never creates directories, initializes repositories, syncs, or writes files.
    Returned diagnostics contain counts and stable reason codes, never filesystem paths or
    thought content.
    """
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    repo_root = _directory(
        data_repo,
        missing_reason="data_repo_missing",
        unreadable_reason="data_repo_unreadable",
        label="data repository",
        deadline=deadline,
    )
    config = _validate_config(repo_root, deadline)
    trails_dir = _configured_trails_dir(repo_root, config)
    configured_trails = _directory(
        trails_dir,
        missing_reason="trails_missing",
        unreadable_reason="trails_unreadable",
        label="trails directory",
        deadline=deadline,
    )
    try:
        configured_trails.relative_to(repo_root)
    except ValueError as exc:
        raise ReadinessFailure(
            "trails_outside_data_repo",
            "trails directory must be inside the data repository",
        ) from exc

    probe = _scan_scope_tree(configured_trails, deadline)
    if probe.representative is not None:
        _read_representative(probe.representative, deadline)

    return {
        "status": "ok",
        "scopes": probe.scopes,
        "records": probe.records,
        "empty": probe.records == 0,
        "representative_read": probe.representative is not None,
    }

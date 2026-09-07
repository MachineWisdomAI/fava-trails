"""Publish multi-file governance changes only after durable VCS persistence.

A write-ahead before-image journal lives in local JJ metadata, outside versioned
thoughts. Readers use the before images until the single journal removal publishes
the completed transaction. Failure/cancellation restores those images; a process
interruption leaves the same view available until the next writer recovers it.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path


def journal_path(repo_root: Path) -> Path:
    return repo_root / ".jj" / "fava-governance-transaction.json"


@contextmanager
def _file_lock(root: Path, *, exclusive: bool):
    """Nonblocking process lock; an occupied writer is a retryable condition."""
    path = root / ".jj" / "fava-governance.lock"
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.write(b"0")
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(stream.fileno(), operation | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _replace(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
        if path.parent.exists():
            _sync_directory(path.parent)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".governance-tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        _sync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _load_journal(root: Path) -> dict[str, str | None]:
    path = journal_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("before"), dict):
        raise RuntimeError("invalid governance transaction journal; operator recovery required")
    for name, value in data["before"].items():
        target = (root / name).resolve()
        if not target.is_relative_to(root.resolve()) or "/thoughts/" not in "/" + name:
            raise RuntimeError("unsafe governance transaction path")
        if value is not None and not isinstance(value, str):
            raise RuntimeError("invalid governance before image")
    return data["before"]


def snapshot_texts(trails_dir: Path) -> dict[Path, str]:
    root = next((p for p in trails_dir.parents if (p / ".jj").is_dir()), trails_dir.parent)
    if not (root / ".jj").is_dir():
        return _snapshot(trails_dir, root)
    try:
        with _file_lock(root, exclusive=False):
            return _snapshot(trails_dir, root)
    except BlockingIOError:
        # Do not race a live writer, including a second transaction beginning
        # while a previous before-image snapshot is being assembled.
        raise RuntimeError("Governance transaction in progress; retry the read") from None


def _snapshot(trails_dir: Path, root: Path, before=None) -> dict[Path, str]:
    if before is None:
        before = _load_journal(root)
    result = {}
    for path in trails_dir.glob("**/thoughts/**/*.md"):
        name = str(path.relative_to(root))
        try:
            text = before[name] if name in before else path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        if text is not None:
            result[path] = text
    for name, text in before.items():
        if text is not None:
            result[root / name] = text
        else:
            result.pop(root / name, None)
    return result


async def _recover(vcs) -> None:
    root = vcs.repo_root
    previous = _load_journal(root)
    if previous:
        for name, text in previous.items():
            (root / name).with_name(Path(name).name + ".governance-tmp").unlink(missing_ok=True)
            _replace(root / name, text)
        await vcs.commit_files(
            "Recover interrupted governance approval",
            [str(root / name) for name in previous],
            allowed_prefixes=[str(Path(name).parent) for name in previous],
        )
        _replace(journal_path(root), None)


async def recover_governance(vcs) -> None:
    async with vcs.repo_lock:
        with _file_lock(vcs.repo_root, exclusive=True):
            await _recover(vcs)


async def persist_governance(vcs, writes: dict[Path, str | None], message: str, *, expected=None) -> None:
    """Commit a bounded set of thought files, preserving a consistent read view."""
    root = vcs.repo_root
    async with vcs.repo_lock:
        with _file_lock(root, exclusive=True):
            await _recover(vcs)
            for path, expected_record in (expected or {}).items():
                from .models import ThoughtRecord

                if not path.exists() or ThoughtRecord.from_markdown(path.read_text()) != expected_record:
                    raise ValueError("Thought changed during approval; re-review before retrying")
            journal = journal_path(root)
            before = {str(p.relative_to(root)): p.read_text(encoding="utf-8") if p.exists() else None for p in writes}
            _replace(journal, json.dumps({"before": before}))
            try:
                for path, text in writes.items():
                    _replace(path, text)
                await vcs.commit_files(
                    message,
                    [str(path) for path in writes],
                    allowed_prefixes=[str(path.parent.relative_to(root)) for path in writes],
                )
                _replace(journal, None)
            except BaseException:
                for name, text in before.items():
                    _replace(root / name, text)
                # Include failures while publishing/removing the journal: readers
                # must retain the old view even after an uncertain durable commit.
                _replace(journal, json.dumps({"before": before}))
                raise

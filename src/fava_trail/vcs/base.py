"""Abstract base class for VCS backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VcsChange:
    """Represents a VCS change/commit."""

    change_id: str
    description: str
    author: str = ""
    timestamp: str = ""
    is_empty: bool = False


@dataclass
class VcsDiff:
    """Diff between two VCS states."""

    summary: str
    files_changed: list[str] = field(default_factory=list)


@dataclass
class VcsConflict:
    """Structured representation of a VCS conflict."""

    file_path: str
    description: str
    sides: list[str] = field(default_factory=list)


@dataclass
class VcsOpLogEntry:
    """Semantic summary of a VCS operation log entry."""

    op_id: str
    description: str
    timestamp: str = ""


@dataclass
class RebaseResult:
    """Result of a rebase/sync operation."""

    success: bool
    has_conflicts: bool = False
    pre_rebase_op_id: str = ""
    conflict_details: list[VcsConflict] = field(default_factory=list)
    summary: str = ""


class VcsBackend(ABC):
    """Abstract VCS backend. All output is semantically translated — no raw VCS stdout."""

    def __init__(self, trail_path: Path):
        self.trail_path = trail_path

    @abstractmethod
    async def init_trail(self) -> str:
        """Initialize a new trail repository. Returns semantic summary."""
        ...

    @abstractmethod
    async def new_change(self, description: str = "") -> VcsChange:
        """Begin a new change/branch from current state."""
        ...

    @abstractmethod
    async def describe(self, description: str) -> str:
        """Set description on the current change."""
        ...

    @abstractmethod
    async def commit_files(self, paths: list[str], description: str) -> VcsChange:
        """Stage and commit specific files with a description."""
        ...

    @abstractmethod
    async def log(self, revset: str = "", limit: int = 20) -> list[VcsChange]:
        """Get change log as semantic summaries."""
        ...

    @abstractmethod
    async def diff(self, revision: str = "") -> VcsDiff:
        """Get diff for a revision."""
        ...

    @abstractmethod
    async def abandon(self, revision: str = "") -> str:
        """Abandon/discard a change. Returns summary."""
        ...

    @abstractmethod
    async def op_log(self, limit: int = 10) -> list[VcsOpLogEntry]:
        """Get operation log as semantic summaries."""
        ...

    @abstractmethod
    async def op_restore(self, op_id: str) -> str:
        """Restore to a previous operation state. Returns summary."""
        ...

    @abstractmethod
    async def conflicts(self) -> list[VcsConflict]:
        """Detect and return structured conflict information."""
        ...

    @abstractmethod
    async def current_change(self) -> Optional[VcsChange]:
        """Get the current working change."""
        ...

    @abstractmethod
    async def fetch_and_rebase(self) -> RebaseResult:
        """Fetch from remote and rebase. Returns structured result."""
        ...

    @abstractmethod
    async def git_push(self, bookmark: str = "") -> str:
        """Push changes to git remote."""
        ...

    @abstractmethod
    async def gc(self) -> str:
        """Run garbage collection. Returns summary."""
        ...

    @abstractmethod
    async def snapshot_count(self) -> int:
        """Get approximate number of snapshots since last GC."""
        ...

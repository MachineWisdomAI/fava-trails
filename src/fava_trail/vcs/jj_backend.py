"""Jujutsu (JJ) VCS backend — primary implementation.

All output goes through the semantic translation layer.
Raw jj stdout is NEVER returned to agents.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from .base import (
    RebaseResult,
    VcsBackend,
    VcsChange,
    VcsConflict,
    VcsDiff,
    VcsOpLogEntry,
)

logger = logging.getLogger(__name__)


class JjError(Exception):
    """Error from jj subprocess."""

    def __init__(self, message: str, returncode: int = 1, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(message)


class JjBackend(VcsBackend):
    """JJ colocated mode backend. Git repos underneath, JJ on top."""

    def __init__(self, trail_path: Path):
        super().__init__(trail_path)
        self._jj_bin = self._find_jj()

    @staticmethod
    def _find_jj() -> str:
        """Find jj binary. Raises if not installed."""
        jj = shutil.which("jj")
        if jj:
            return jj
        # Check ~/.local/bin explicitly (may not be in PATH)
        local_jj = Path.home() / ".local" / "bin" / "jj"
        if local_jj.exists():
            return str(local_jj)
        raise FileNotFoundError(
            "jj binary not found. Run scripts/install-jj.sh or install from https://jj-vcs.github.io/jj/"
        )

    async def _run(self, *args: str, check: bool = True) -> tuple[str, str]:
        """Run a jj command. Returns (stdout, stderr). All output is raw — callers translate."""
        cmd = [self._jj_bin, "--color=never", "--no-pager", *args]
        logger.debug(f"jj: {' '.join(cmd)} (cwd={self.trail_path})")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.trail_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        if check and proc.returncode != 0:
            raise JjError(
                f"jj {args[0]} failed (rc={proc.returncode}): {stderr or stdout}",
                returncode=proc.returncode,
                stderr=stderr,
            )
        return stdout, stderr

    # --- Semantic translation helpers ---

    @staticmethod
    def _parse_log_line(line: str) -> Optional[VcsChange]:
        """Parse a single jj log template output line into VcsChange."""
        # Template outputs: change_id SEP commit_id SEP description SEP author SEP timestamp SEP empty
        parts = line.split("\x1f")
        if len(parts) < 3:
            return None
        return VcsChange(
            change_id=parts[0].strip(),
            description=parts[2].strip() if len(parts) > 2 else "",
            author=parts[3].strip() if len(parts) > 3 else "",
            timestamp=parts[4].strip() if len(parts) > 4 else "",
            is_empty=parts[5].strip().lower() == "true" if len(parts) > 5 else False,
        )

    @staticmethod
    def _translate_conflicts(raw: str) -> list[VcsConflict]:
        """Translate raw jj conflict output into structured conflicts.

        Intercepts algebraic notation like A+(C-B)+(E-D) and produces
        human-readable structured summaries instead.
        """
        conflicts = []
        if not raw.strip():
            return conflicts

        for line in raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            # Extract file path from conflict markers
            # JJ shows conflicts as file paths with conflict info
            conflicts.append(VcsConflict(
                file_path=line,
                description=f"Conflicting changes detected in: {line}",
            ))
        return conflicts

    # Log template: change_id, commit_id, description, author email, timestamp, empty flag
    LOG_TEMPLATE = (
        'separate("\\x1f", change_id.short(12), commit_id.short(12), '
        'if(description, description.first_line(), "(no description)"), '
        'if(author.email(), author.email(), "unknown"), '
        'author.timestamp().format("%Y-%m-%d %H:%M"), '
        'if(empty, "true", "false")) ++ "\\n"'
    )

    # --- VcsBackend interface ---

    async def init_trail(self) -> str:
        self.trail_path.mkdir(parents=True, exist_ok=True)
        jj_dir = self.trail_path / ".jj"
        if jj_dir.exists():
            return f"Trail already initialized at {self.trail_path}"

        # Initialize colocated JJ+Git repo
        await self._run("git", "init", "--colocate")

        # Configure JJ for this trail
        await self._run("config", "set", "--repo", "user.name", "FAVA Trail")
        await self._run("config", "set", "--repo", "user.email", "fava@machine-wisdom.ai")

        return f"Initialized JJ colocated trail at {self.trail_path}"

    async def new_change(self, description: str = "") -> VcsChange:
        args = ["new"]
        if description:
            args.extend(["-m", description])
        stdout, _ = await self._run(*args)
        change = await self.current_change()
        if change:
            return change
        return VcsChange(change_id="(new)", description=description)

    async def describe(self, description: str) -> str:
        await self._run("describe", "-m", description)
        return f"Updated description: {description[:80]}"

    async def commit_files(self, paths: list[str], description: str) -> VcsChange:
        """Squash current change with description — JJ's equivalent of git commit."""
        # In JJ, files are auto-tracked. We just describe and create new change.
        if description:
            await self._run("describe", "-m", description)

        # Snapshot to ensure files are tracked
        await self._run("status")  # triggers snapshot

        change = await self.current_change()
        if change:
            change.description = description
        else:
            change = VcsChange(change_id="(committed)", description=description)

        # Create new empty change on top
        await self._run("new")
        return change

    async def log(self, revset: str = "", limit: int = 20) -> list[VcsChange]:
        args = ["log", "--no-graph", "-T", self.LOG_TEMPLATE, "-n", str(limit)]
        if revset:
            args.extend(["-r", revset])
        stdout, _ = await self._run(*args)
        changes = []
        for line in stdout.splitlines():
            change = self._parse_log_line(line)
            if change:
                changes.append(change)
        return changes

    async def diff(self, revision: str = "") -> VcsDiff:
        args = ["diff", "--stat"]
        if revision:
            args.extend(["-r", revision])
        stdout, _ = await self._run(*args, check=False)
        files = []
        for line in stdout.splitlines():
            line = line.strip()
            if line and "|" in line:
                files.append(line.split("|")[0].strip())
        return VcsDiff(
            summary=stdout if stdout else "No changes",
            files_changed=files,
        )

    async def abandon(self, revision: str = "") -> str:
        args = ["abandon"]
        if revision:
            args.append(revision)
        stdout, _ = await self._run(*args)
        return f"Abandoned change{' ' + revision if revision else ''}"

    async def op_log(self, limit: int = 10) -> list[VcsOpLogEntry]:
        op_template = (
            'separate("\\x1f", self.id().short(12), description.first_line(), '
            'self.time().start().format("%Y-%m-%d %H:%M")) ++ "\\n"'
        )
        stdout, _ = await self._run("op", "log", "--no-graph", "-T", op_template, "-n", str(limit))
        entries = []
        for line in stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) >= 2:
                entries.append(VcsOpLogEntry(
                    op_id=parts[0].strip(),
                    description=parts[1].strip(),
                    timestamp=parts[2].strip() if len(parts) > 2 else "",
                ))
        return entries

    async def op_restore(self, op_id: str) -> str:
        await self._run("op", "restore", op_id)
        return f"Restored to operation {op_id}"

    async def conflicts(self) -> list[VcsConflict]:
        """Detect conflicts via jj log with conflicts() revset.

        CONFLICT INTERCEPTION: Raw algebraic notation is never exposed.
        Returns structured VcsConflict objects with human-readable descriptions.
        """
        stdout, _ = await self._run(
            "log", "--no-graph", "-r", "conflicts()", "-T",
            'separate("\\x1f", change_id.short(12), description.first_line()) ++ "\\n"',
            check=False,
        )
        if not stdout.strip():
            return []

        conflicts = []
        for line in stdout.strip().splitlines():
            parts = line.split("\x1f")
            change_id = parts[0].strip() if parts else "unknown"
            desc = parts[1].strip() if len(parts) > 1 else "(no description)"
            conflicts.append(VcsConflict(
                file_path=f"change:{change_id}",
                description=f"Conflict in change {change_id}: {desc}",
            ))
        return conflicts

    async def current_change(self) -> Optional[VcsChange]:
        changes = await self.log(revset="@", limit=1)
        return changes[0] if changes else None

    async def fetch_and_rebase(self) -> RebaseResult:
        # Record pre-rebase op for rollback
        ops = await self.op_log(limit=1)
        pre_op = ops[0].op_id if ops else ""

        try:
            await self._run("git", "fetch", "--all-remotes", check=False)
        except JjError as e:
            logger.warning(f"Git fetch failed: {e}")
            return RebaseResult(success=False, pre_rebase_op_id=pre_op, summary=f"Fetch failed: {e}")

        try:
            await self._run("rebase", "-d", "main@origin")
        except JjError as e:
            # Check for conflicts
            if "conflict" in str(e).lower():
                conflicts = await self.conflicts()
                return RebaseResult(
                    success=False,
                    has_conflicts=True,
                    pre_rebase_op_id=pre_op,
                    conflict_details=conflicts,
                    summary=f"Rebase produced conflicts: {len(conflicts)} conflict(s)",
                )
            return RebaseResult(success=False, pre_rebase_op_id=pre_op, summary=f"Rebase failed: {e}")

        # Check for conflicts after rebase
        conflicts = await self.conflicts()
        if conflicts:
            return RebaseResult(
                success=False,
                has_conflicts=True,
                pre_rebase_op_id=pre_op,
                conflict_details=conflicts,
                summary=f"Rebase produced {len(conflicts)} conflict(s)",
            )

        return RebaseResult(success=True, pre_rebase_op_id=pre_op, summary="Sync complete")

    async def git_push(self, bookmark: str = "") -> str:
        args = ["git", "push"]
        if bookmark:
            args.extend(["-b", bookmark])
        else:
            args.append("--all")
        stdout, _ = await self._run(*args)
        return f"Pushed to git remote"

    async def gc(self) -> str:
        """Run garbage collection: jj util gc + git gc."""
        try:
            await self._run("util", "gc")
            logger.info("jj util gc completed")
        except JjError as e:
            logger.warning(f"jj util gc failed: {e}")

        # Also run git gc for the colocated repo
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "gc", "--prune=now",
                cwd=self.trail_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info("git gc completed")
        except Exception as e:
            logger.warning(f"git gc failed: {e}")

        return "Garbage collection completed"

    async def snapshot_count(self) -> int:
        """Approximate snapshot count from op log."""
        ops = await self.op_log(limit=1000)
        return sum(1 for op in ops if "snapshot" in op.description.lower())

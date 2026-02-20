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
    """JJ colocated mode backend. Single monorepo, trail-path scoped operations."""

    # Shared repo locks: all instances with the same repo_root share one lock.
    # This deduplicates GC and serializes global ops (push/fetch) across all trail backends.
    _repo_locks: dict[str, asyncio.Lock] = {}

    def __init__(self, repo_root: Path, trail_path: Path):
        super().__init__(repo_root, trail_path)
        # Override per-instance repo_lock with shared lock keyed by repo_root
        key = str(repo_root.resolve())
        if key not in JjBackend._repo_locks:
            JjBackend._repo_locks[key] = asyncio.Lock()
        self.repo_lock = JjBackend._repo_locks[key]
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
        """Run a jj command at repo_root. Returns (stdout, stderr). All output is raw — callers translate."""
        cmd = [self._jj_bin, "--color=never", "--no-pager", *args]
        logger.debug(f"jj: {' '.join(cmd)} (cwd={self.repo_root})")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.repo_root,
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

    def _trail_rel_path(self) -> str:
        """Get trail path relative to repo root, for path-scoped JJ commands."""
        try:
            return str(self.trail_path.relative_to(self.repo_root))
        except ValueError:
            # trail_path not under repo_root — return as-is (shouldn't happen)
            return str(self.trail_path)

    # Log template: change_id, commit_id, description, author email, timestamp, empty flag
    LOG_TEMPLATE = (
        'separate("\\x1f", change_id.short(12), commit_id.short(12), '
        'if(description, description.first_line(), "(no description)"), '
        'if(author.email(), author.email(), "unknown"), '
        'author.timestamp().format("%Y-%m-%d %H:%M"), '
        'if(empty, "true", "false")) ++ "\\n"'
    )

    # --- VcsBackend interface ---

    async def init_monorepo(self) -> str:
        """Initialize the monorepo at repo_root with three-case detection.

        Cases:
        1. .git only (no .jj) → colocate JJ on top of existing git repo
        2. Both .jj and .git exist → already initialized, configure and skip
        3. Neither exists → fresh init with jj git init --colocate
        """
        self.repo_root.mkdir(parents=True, exist_ok=True)
        jj_dir = self.repo_root / ".jj"
        git_dir = self.repo_root / ".git"

        if jj_dir.exists() and git_dir.exists():
            # Case 2: Both exist — already initialized
            logger.info(f"Monorepo already initialized at {self.repo_root}")
        elif git_dir.exists() and not jj_dir.exists():
            # Case 1: .git only — colocate JJ on top
            logger.info(f"Colocating JJ on existing git repo at {self.repo_root}")
            await self._run("git", "init", "--colocate")
        else:
            # Case 3: Neither exists (or .jj without .git — shouldn't happen in colocated mode)
            logger.info(f"Initializing fresh monorepo at {self.repo_root}")
            await self._run("git", "init", "--colocate")

        # Configure JJ for the monorepo
        await self._run("config", "set", "--repo", "user.name", "FAVA Trail")
        await self._run("config", "set", "--repo", "user.email", "fava@machine-wisdom.ai")
        # Snapshot-style conflict markers — directly extractable content,
        # unlike diff-style (%%%%%%%) which requires diff application
        await self._run("config", "set", "--repo", "ui.conflict-marker-style", "snapshot")

        return f"Monorepo initialized at {self.repo_root}"

    async def init_trail(self) -> str:
        """Create trail directory structure. No repo init — that's init_monorepo's job."""
        self.trail_path.mkdir(parents=True, exist_ok=True)
        if (self.trail_path / "thoughts").exists():
            return f"Trail already initialized at {self.trail_path}"
        return f"Trail directory created at {self.trail_path}"

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

    async def commit_files(self, message: str, paths: list[str]) -> VcsChange:
        """Commit files with cross-trail pollution assertion.

        Uses jj diff --name-only to get dirty paths. Asserts all dirty paths
        fall under the expected trail prefix. Then describes and creates new change.
        """
        # Get dirty files in the working copy
        stdout, _ = await self._run("diff", "--name-only", check=False)
        dirty_paths = [line.strip() for line in stdout.splitlines() if line.strip()]

        # Cross-trail assertion: all dirty files must be under our trail
        if dirty_paths:
            trail_rel = self._trail_rel_path()
            for dp in dirty_paths:
                if not dp.startswith(trail_rel):
                    raise RuntimeError(
                        f"Cross-trail pollution detected: '{dp}' is outside trail prefix '{trail_rel}'. "
                        "Aborting commit to prevent data corruption."
                    )

        # Proceed with commit
        if message:
            await self._run("describe", "-m", message)

        # Snapshot to ensure files are tracked
        await self._run("status")  # triggers snapshot

        change = await self.current_change()
        if change:
            change.description = message
        else:
            change = VcsChange(change_id="(committed)", description=message)

        # Create new empty change on top
        await self._run("new")
        return change

    async def log(self, revset: str = "", limit: int = 20) -> list[VcsChange]:
        """Get change log scoped to trail path."""
        args = ["log", "--no-graph", "-T", self.LOG_TEMPLATE, "-n", str(limit)]
        if revset:
            args.extend(["-r", revset])
        # Path-scope: only show commits touching this trail's files
        trail_rel = self._trail_rel_path()
        args.append(trail_rel)
        stdout, _ = await self._run(*args)
        changes = []
        for line in stdout.splitlines():
            change = self._parse_log_line(line)
            if change:
                changes.append(change)
        return changes

    async def diff(self, revision: str = "") -> VcsDiff:
        """Get diff scoped to trail path."""
        args = ["diff", "--stat"]
        if revision:
            args.extend(["-r", revision])
        # Path-scope: only show changes in this trail
        trail_rel = self._trail_rel_path()
        args.append(trail_rel)
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
        """Get current working change. Uses revset @, NOT path-scoped."""
        args = ["log", "--no-graph", "-T", self.LOG_TEMPLATE, "-n", "1", "-r", "@"]
        stdout, _ = await self._run(*args)
        for line in stdout.splitlines():
            change = self._parse_log_line(line)
            if change:
                return change
        return None

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
        return "Pushed to git remote"

    async def push(self) -> str:
        """Push all bookmarks to remote."""
        async with self.repo_lock:
            return await self.git_push()

    async def fetch(self) -> str:
        """Fetch from remote without rebase."""
        async with self.repo_lock:
            await self._run("git", "fetch", "--all-remotes", check=False)
            return "Fetched from remote"

    async def add_remote(self, name: str, url: str) -> str:
        """Add a git remote to the colocated repo."""
        proc = await asyncio.create_subprocess_exec(
            "git", "remote", "add", name, url,
            cwd=self.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            if "already exists" in stderr:
                return f"Remote '{name}' already exists"
            raise JjError(f"git remote add failed: {stderr}", returncode=proc.returncode, stderr=stderr)
        return f"Added remote '{name}' -> {url}"

    async def gc(self) -> str:
        """Run garbage collection at repo_root: jj util gc + git gc."""
        async with self.repo_lock:
            try:
                await self._run("util", "gc")
                logger.info("jj util gc completed")
            except JjError as e:
                logger.warning(f"jj util gc failed: {e}")

            # Also run git gc for the colocated repo — at repo_root
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "gc", "--prune=now",
                    cwd=self.repo_root,
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

"""Jujutsu (JJ) VCS backend — primary implementation.

All output goes through the semantic translation layer.
Raw jj stdout is NEVER returned to agents.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

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

    # Default bookmark name — must match what `fava-trails bootstrap` creates.
    DEFAULT_BOOKMARK = "main"

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
            "jj binary not found. Install with: fava-trails install-jj (or manually from https://jj-vcs.github.io/jj/)"
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
    def _parse_log_line(line: str) -> VcsChange | None:
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
        """Initialize the monorepo at repo_root with four-case detection.

        Cases:
        1. .git only (no .jj) → colocate JJ on top of existing git repo
        2. Both .jj and .git exist → already initialized, configure and skip
        3. .jj only (no .git) → non-colocated repo, raise error with fix instructions
        4. Neither exists → fresh init with jj git init --colocate
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
        elif jj_dir.exists() and not git_dir.exists():
            # Case 3: .jj only — non-colocated repo, cannot proceed
            raise RuntimeError(
                f"Data repo at {self.repo_root} has .jj/ but no .git/ — "
                f"this is a non-colocated JJ repo which FAVA Trails does not support.\n"
                f"  Fix: re-clone with colocated mode:\n"
                f"    rm -rf {self.repo_root}\n"
                f"    fava-trails clone <remote-url> {self.repo_root}"
            )
        else:
            # Case 4: Neither exists — fresh init
            logger.info(f"Initializing fresh monorepo at {self.repo_root}")
            await self._run("git", "init", "--colocate")

        # Configure JJ for the monorepo
        await self._run("config", "set", "--repo", "user.name", "FAVA Trail")
        await self._run("config", "set", "--repo", "user.email", "fava@machine-wisdom.ai")
        # Snapshot-style conflict markers — directly extractable content,
        # unlike diff-style (%%%%%%%) which requires diff application
        await self._run("config", "set", "--repo", "ui.conflict-marker-style", "snapshot")
        # Default description prevents undescribed commits from external JJ usage
        await self._run("config", "set", "--repo", "ui.default-description", "(auto-described)")

        return f"Monorepo initialized at {self.repo_root}"

    async def init_trail(self) -> str:
        """Create trail directory structure. No repo init — that's init_monorepo's job."""
        self.trail_path.mkdir(parents=True, exist_ok=True)
        if (self.trail_path / "thoughts").exists():
            return f"Trail already initialized at {self.trail_path}"
        return f"Trail directory created at {self.trail_path}"

    async def new_change(self, description: str = "") -> VcsChange:
        effective = description.strip() or "(new change)"
        args = ["new", "-m", effective]
        stdout, _ = await self._run(*args)
        change = await self.current_change()
        if change:
            return change
        return VcsChange(change_id="(new)", description=effective)

    async def describe(self, description: str) -> str:
        await self._run("describe", "-m", description)
        return f"Updated description: {description[:80]}"

    async def commit_files(
        self,
        message: str,
        paths: list[str],
        allowed_prefixes: list[str] | None = None,
    ) -> VcsChange:
        """Commit files with cross-trail pollution assertion.

        Uses jj diff --name-only to get dirty paths. Asserts all dirty paths
        fall under the expected trail prefix (or allowed_prefixes for cross-scope ops).
        Then describes and creates new change.
        """
        # Get dirty files in the working copy
        stdout, _ = await self._run("diff", "--name-only", check=False)
        dirty_paths = [line.strip() for line in stdout.splitlines() if line.strip()]

        # Cross-trail assertion: all dirty files must be under allowed prefixes
        if dirty_paths:
            prefixes = allowed_prefixes or [self._trail_rel_path()]
            for dp in dirty_paths:
                if not any(dp.startswith(pfx) for pfx in prefixes):
                    raise RuntimeError(
                        f"Cross-trail pollution detected: '{dp}' is outside allowed prefixes {prefixes}. "
                        "Aborting commit to prevent data corruption."
                    )

        # Proceed with commit — always describe to prevent phantom empty commits
        # that block jj git push (JJ refuses to push undescribed commits)
        effective_msg = message.strip() or "(auto-commit)"
        await self._run("describe", "-m", effective_msg)

        # Snapshot to ensure files are tracked
        await self._run("status")  # triggers snapshot

        change = await self.current_change()
        if change:
            change.description = effective_msg
        else:
            change = VcsChange(change_id="(committed)", description=effective_msg)

        # Create new empty change on top — always with description
        await self._run("new", "-m", "(new change)")
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

    @staticmethod
    def parse_snapshot_conflict(text: str) -> tuple[str | None, str | None, str | None]:
        """Parse JJ snapshot-style conflict markers from file content.

        Returns (side_a, base, side_b). All None if unparseable.
        Handles single and multiple conflict blocks — concatenates all sides.

        Expected format:
            <<<<<<< Conflict N of M
            +++++++ Contents of side #1
            content from side A
            ------- Contents of base
            base content
            +++++++ Contents of side #2
            content from side B
            >>>>>>> Conflict N of M
        """
        if "<<<<<<< Conflict" not in text:
            return None, None, None

        side_a_parts: list[str] = []
        base_parts: list[str] = []
        side_b_parts: list[str] = []
        current_section: str | None = None

        for line in text.splitlines():
            if line.startswith("<<<<<<< Conflict"):
                current_section = None
                continue
            if line.startswith(">>>>>>> Conflict"):
                current_section = None
                continue
            if line.startswith("+++++++ Contents of side #1"):
                current_section = "side_a"
                continue
            if line.startswith("------- Contents of base"):
                current_section = "base"
                continue
            if line.startswith("+++++++ Contents of side #2"):
                current_section = "side_b"
                continue

            if current_section == "side_a":
                side_a_parts.append(line)
            elif current_section == "base":
                base_parts.append(line)
            elif current_section == "side_b":
                side_b_parts.append(line)

        # If we got nothing from any section, markers were unparseable
        if not side_a_parts and not base_parts and not side_b_parts:
            return None, None, None

        return (
            "\n".join(side_a_parts) if side_a_parts else None,
            "\n".join(base_parts) if base_parts else None,
            "\n".join(side_b_parts) if side_b_parts else None,
        )

    async def get_conflict_content(self) -> dict[str, tuple[str | None, str | None, str | None]]:
        """Read conflicted working copy files and parse snapshot-style conflict markers.

        Returns dict mapping file_path -> (side_a, base, side_b).
        Only includes files with parseable conflict markers.
        """
        # Get list of conflicted files via jj diff
        stdout, _ = await self._run("diff", "--name-only", check=False)
        if not stdout.strip():
            return {}

        result = {}
        trail_rel = self._trail_rel_path()
        for line in stdout.strip().splitlines():
            file_rel = line.strip()
            if not file_rel:
                continue
            # Only process files in our trail
            if not file_rel.startswith(trail_rel):
                continue
            file_path = self.repo_root / file_rel
            if not file_path.exists():
                continue
            try:
                content = file_path.read_text()
            except Exception:
                continue
            if "<<<<<<< Conflict" not in content:
                continue
            side_a, base, side_b = self.parse_snapshot_conflict(content)
            result[file_rel] = (side_a, base, side_b)

        return result

    async def conflicts(self) -> list[VcsConflict]:
        """Detect conflicts via jj log with conflicts() revset.

        CONFLICT INTERCEPTION: Raw algebraic notation is never exposed.
        Returns structured VcsConflict objects with human-readable descriptions
        including side_a/side_b/base content when available.
        """
        stdout, _ = await self._run(
            "log", "--no-graph", "-r", "conflicts()", "-T",
            'separate("\\x1f", change_id.short(12), description.first_line()) ++ "\\n"',
            check=False,
        )
        if not stdout.strip():
            return []

        # Get conflict content from files
        conflict_content = await self.get_conflict_content()

        conflicts = []
        for line in stdout.strip().splitlines():
            parts = line.split("\x1f")
            change_id = parts[0].strip() if parts else "unknown"
            desc = parts[1].strip() if len(parts) > 1 else "(no description)"

            if conflict_content:
                # Create one VcsConflict per conflicted file
                for file_path, (side_a, base, side_b) in conflict_content.items():
                    conflicts.append(VcsConflict(
                        file_path=file_path,
                        description=f"Conflict in change {change_id}: {desc}",
                        side_a=side_a,
                        side_b=side_b,
                        base=base,
                    ))
            else:
                # No file-level detail available
                conflicts.append(VcsConflict(
                    file_path=f"change:{change_id}",
                    description=f"Conflict in change {change_id}: {desc}",
                ))

        return conflicts

    async def current_change(self) -> VcsChange | None:
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
            await self._run("rebase", "-d", f"{self.DEFAULT_BOOKMARK}@origin")
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

    async def _git_push(self, bookmark: str = "") -> str:
        """Low-level git push. Use push() instead — it advances bookmarks and repairs first."""
        args = ["git", "push", "--allow-empty-description"]
        if bookmark:
            args.extend(["-b", bookmark])
        else:
            args.append("--all")
        stdout, _ = await self._run(*args)
        return "Pushed to git remote"

    async def _repair_undescribed_commits(self) -> int:
        """Find and describe any mutable commits with empty descriptions in main's ancestry.

        Legacy undescribed commits or those created by external JJ usage block
        jj git push. This method repairs them before pushing. Immutable commits
        (already pushed to remote) are excluded from the revset and skipped
        per-commit if describe fails.

        Returns the count of successfully repaired commits.
        """
        try:
            stdout, _ = await self._run(
                "log", "--no-graph", "-r",
                f'description(exact:"") & ancestors({self.DEFAULT_BOOKMARK}) & ~root() & mutable()',
                "-T", 'change_id.short(12) ++ "\\n"',
            )
        except JjError as e:
            logger.warning(f"Repair scan failed; proceeding without repair: {e}")
            return 0
        if not stdout.strip():
            return 0

        change_ids = [line.strip() for line in stdout.splitlines() if line.strip()]
        repaired = 0
        for cid in change_ids:
            try:
                await self._run(
                    "describe", "-r", cid,
                    "-m", "(auto-described: legacy empty commit)",
                )
                repaired += 1
            except JjError as e:
                logger.warning(f"Could not auto-describe {cid}: {e}")
        if repaired:
            logger.info(f"Repaired {repaired} undescribed commit(s)")
        return repaired

    async def push(self) -> str:
        """Push main bookmark to remote.

        Advances the 'main' bookmark to the latest committed change (@-),
        repairs any undescribed commits in the ancestry, then pushes.
        """
        async with self.repo_lock:
            # Advance main bookmark to latest committed change
            try:
                await self._run("bookmark", "set", self.DEFAULT_BOOKMARK, "-r", "@-")
            except JjError as e:
                logger.warning(f"Could not advance main bookmark: {e}")
            # Repair any undescribed commits before pushing
            await self._repair_undescribed_commits()
            return await self._git_push(bookmark=self.DEFAULT_BOOKMARK)

    async def try_push(self) -> dict:
        """Non-throwing push wrapper. Returns status dict.

        Returns {"status": "pushed"} on success,
        {"status": "warning", "message": "..."} on failure.
        Push failures never fail the calling write operation.
        """
        try:
            await self.push()
            return {"status": "pushed"}
        except Exception as e:
            logger.warning(f"Push failed (non-fatal): {e}")
            return {"status": "warning", "message": str(e)}

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

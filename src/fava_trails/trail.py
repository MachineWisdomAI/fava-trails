"""TrailManager — coordinates VCS backend, models, and per-trail mutex."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from pathlib import Path

from .config import (
    get_trails_dir,
    load_trail_config,
    sanitize_namespace,
    sanitize_scope_path,
    save_trail_config,
)
from .hook_manifest import HookRegistry
from .hook_pipeline import PipelineResult, dispatch_observer, run_pipeline
from .hook_types import (
    AfterProposeEvent,
    AfterSaveEvent,
    AfterSupersedeEvent,
    BeforeProposeEvent,
    BeforeSaveEvent,
    OnRecallEvent,
    TrailContext,
)
from .models import (
    DEFAULT_NAMESPACE,
    NAMESPACE_ROUTES,
    SourceType,
    ThoughtFrontmatter,
    ThoughtRecord,
    TrailConfig,
    ValidationStatus,
)
from .trust_gate import TrustResult
from .vcs.base import RebaseResult, VcsBackend, VcsChange, VcsConflict, VcsDiff, VcsOpLogEntry

logger = logging.getLogger(__name__)


class AmbiguousThoughtID(Exception):
    """Raised when a shortened thought ID prefix matches more than one thought file."""

    def __init__(self, prefix: str, candidates: list[dict]) -> None:
        self.prefix = prefix
        self.candidates = candidates  # list of {thought_id, namespace, source_type, created_at, content_preview}
        super().__init__(
            f"Prefix '{prefix}' is ambiguous — matches {len(candidates)} thoughts. "
            "Provide a longer prefix or the full ULID."
        )


# Namespace subdirectories created on trail init
NAMESPACE_DIRS = [
    "thoughts/decisions",
    "thoughts/observations",
    "thoughts/intents",
    "thoughts/preferences/client",
    "thoughts/preferences/firm",
    "thoughts/drafts",
]


class TrailManager:
    """Manages a single trail: VCS ops, thought CRUD, namespace routing, GC."""

    def __init__(self, trail_name: str, vcs: VcsBackend, hooks: HookRegistry | None = None):
        self.trail_name = sanitize_scope_path(trail_name)
        self.trail_path = get_trails_dir() / self.trail_name
        self.vcs = vcs
        self._hooks = hooks
        self._lock = asyncio.Lock()
        self._config: TrailConfig | None = None
        self._snapshot_count = 0
        self._last_gc_time = time.time()
        self._feedback_by_task: dict[asyncio.Task, PipelineResult | None] = {}

    def _set_feedback(self, value: PipelineResult | None) -> None:
        """Store pipeline feedback scoped to the current asyncio task."""
        task = asyncio.current_task()
        if task is not None:
            self._feedback_by_task[task] = value

    def consume_feedback(self) -> PipelineResult | None:
        """Consume and return pipeline feedback for the current asyncio task."""
        task = asyncio.current_task()
        if task is None:
            return None
        return self._feedback_by_task.pop(task, None)

    def _merge_observer_feedback(self, observer_result: PipelineResult | None) -> None:
        """Merge observer hook feedback into existing pipeline feedback."""
        if observer_result is None:
            return
        existing = self.consume_feedback()
        if existing is not None:
            existing.feedback.merge_from(observer_result.feedback)
            self._set_feedback(existing)
        else:
            self._set_feedback(observer_result)

    @property
    def config(self) -> TrailConfig:
        if self._config is None:
            self._config = load_trail_config(self.trail_name)
        return self._config

    def _thoughts_dir(self, namespace: str = DEFAULT_NAMESPACE) -> Path:
        return self.trail_path / "thoughts" / namespace

    def _thought_path(self, thought_id: str, namespace: str = DEFAULT_NAMESPACE) -> Path:
        return self._thoughts_dir(namespace) / f"{thought_id}.md"

    def _find_thought_path(self, thought_id: str) -> Path | None:
        """Find a thought file by ULID across all namespaces.

        Supports prefix matching: if thought_id is shorter than a full ULID (26 chars),
        all thought files whose stem starts with the prefix are collected.
        - Exact match (full ULID): returns immediately.
        - Unique prefix match: returns the single matching path.
        - Ambiguous prefix match: raises AmbiguousThoughtID with candidate info.
        - No match: returns None.
        """
        # Fast path: exact match
        for p in self.trail_path.glob("thoughts/**/*.md"):
            if p.stem == thought_id:
                return p

        # Prefix match (only attempted when no exact match found)
        if len(thought_id) < 26:  # ULIDs are 26 chars
            matches = [
                p for p in self.trail_path.glob("thoughts/**/*.md")
                if p.stem.startswith(thought_id)
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                candidates = []
                for p in matches:
                    try:
                        record = ThoughtRecord.from_markdown(p.read_text())
                        fm = record.frontmatter
                        candidates.append({
                            "thought_id": fm.thought_id,
                            "namespace": self._get_namespace_from_path(p),
                            "source_type": fm.source_type.value,
                            "created_at": fm.created_at.isoformat() if fm.created_at else None,
                            "content_preview": record.content[:100] + ("..." if len(record.content) > 100 else ""),
                        })
                    except Exception:
                        candidates.append({"thought_id": p.stem, "namespace": self._get_namespace_from_path(p)})
                raise AmbiguousThoughtID(thought_id, candidates)

        return None

    def _get_namespace_from_path(self, path: Path) -> str:
        """Extract namespace from a thought file path. Handles nested dirs (e.g., preferences/firm)."""
        # path is like: .../trails/test/thoughts/preferences/firm/ULID.md
        # We want: preferences/firm
        thoughts_dir = self.trail_path / "thoughts"
        try:
            rel = path.parent.relative_to(thoughts_dir)
            return str(rel)
        except ValueError:
            return DEFAULT_NAMESPACE

    async def init(self) -> str:
        """Initialize the trail repo and namespace directories."""
        async with self._lock:
            result = await self.vcs.init_trail()

            # Create namespace subdirectories
            for ns_dir in NAMESPACE_DIRS:
                (self.trail_path / ns_dir).mkdir(parents=True, exist_ok=True)
                # Add .gitkeep to track empty dirs
                gitkeep = self.trail_path / ns_dir / ".gitkeep"
                if not gitkeep.exists():
                    gitkeep.touch()

            # Save trail config
            save_trail_config(self.trail_name, self.config)

            # Initial commit with directory structure
            await self.vcs.commit_files(
                "Initialize trail with namespace directories",
                [str(p) for p in self.trail_path.rglob(".gitkeep")],
            )

            return result

    async def save_thought(
        self,
        content: str,
        agent_id: str = "unknown",
        source_type: SourceType = SourceType.OBSERVATION,
        confidence: float = 0.5,
        namespace: str | None = None,
        parent_id: str | None = None,
        intent_ref: str | None = None,
        relationships: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> ThoughtRecord:
        """Save a new thought. Defaults to drafts/ namespace."""
        ns = namespace or DEFAULT_NAMESPACE
        sanitize_namespace(ns)  # Validate namespace — prevents path traversal

        frontmatter = ThoughtFrontmatter(
            agent_id=agent_id,
            source_type=source_type,
            confidence=confidence,
            parent_id=parent_id,
            intent_ref=intent_ref,
            metadata=metadata or {},
        )

        if relationships:
            from .models import Relationship, RelationshipType
            frontmatter.relationships = [
                Relationship(type=RelationshipType(r["type"]), target_id=r["target_id"])
                for r in relationships
            ]

        # Warn if decision without intent_ref
        if source_type == SourceType.DECISION and not intent_ref:
            logger.warning(
                f"Decision thought {frontmatter.thought_id} saved without intent_ref. "
                "Consider linking to an intent document."
            )

        record = ThoughtRecord(frontmatter=frontmatter, content=content)

        # before_save hook — can reject, mutate, or redirect
        self._set_feedback(None)
        if self._hooks and self._hooks.has_hooks:
            event = BeforeSaveEvent(
                trail_name=self.trail_name,
                thought=copy.deepcopy(record),
                namespace=ns,
                context=TrailContext(self),
            )
            pipeline_result = await run_pipeline(self._hooks, event)
            self._set_feedback(pipeline_result)
            if pipeline_result.rejected:
                raise ValueError("before_save hook rejected this thought")
            if pipeline_result.redirect_namespace:
                sanitize_namespace(pipeline_result.redirect_namespace)
                ns = pipeline_result.redirect_namespace
            if pipeline_result.event and pipeline_result.event.thought:
                record = pipeline_result.event.thought

        async with self._lock:
            thought_dir = self._thoughts_dir(ns)
            thought_dir.mkdir(parents=True, exist_ok=True)
            path = self._thought_path(record.thought_id, ns)
            path.write_text(record.to_markdown())

            await self.vcs.commit_files(
                f"Save thought {record.thought_id[:8]} [{source_type.value}] in {ns}/",
                [str(path)],
            )

            await self._maybe_gc()

        # after_save hook — runs inline so feedback reaches the caller
        if self._hooks and self._hooks.has_hooks:
            after_event = AfterSaveEvent(
                trail_name=self.trail_name,
                thought=record,
                namespace=ns,
            )
            self._merge_observer_feedback(
                await dispatch_observer(self._hooks, after_event)
            )

        return record

    async def get_thought(self, thought_id: str) -> ThoughtRecord | None:
        """Retrieve a thought by ULID. Searches all namespaces."""
        path = self._find_thought_path(thought_id)
        if path:
            return ThoughtRecord.from_markdown(path.read_text())
        return None

    # Content-freeze statuses: thoughts in these states cannot be updated via update_thought
    FROZEN_STATUSES = {
        ValidationStatus.APPROVED,
        ValidationStatus.REJECTED,
        ValidationStatus.TOMBSTONED,
    }

    async def update_thought(self, thought_id: str, new_content: str) -> ThoughtRecord:
        """Update thought content in-place. Frontmatter is preserved (tamper-proof).

        Content-freeze guard: rejects updates when:
        - validation_status is APPROVED, REJECTED, or TOMBSTONED
        - superseded_by is set (thought has been replaced)
        """
        async with self._lock:
            path = self._find_thought_path(thought_id)
            if path is None:
                raise ValueError(f"Thought {thought_id} not found")

            record = ThoughtRecord.from_markdown(path.read_text())

            # Content-freeze guards
            if record.frontmatter.validation_status in self.FROZEN_STATUSES:
                raise ValueError(
                    f"Cannot update thought {thought_id[:8]}: "
                    f"content is frozen (status={record.frontmatter.validation_status.value})"
                )
            if record.is_superseded:
                raise ValueError(
                    f"Cannot update thought {thought_id[:8]}: "
                    f"content is frozen (superseded by {record.frontmatter.superseded_by})"
                )

            # Replace content only — frontmatter loaded from disk and re-serialized verbatim
            record.content = new_content
            path.write_text(record.to_markdown())

            namespace = self._get_namespace_from_path(path)
            await self.vcs.commit_files(
                f"Update thought {thought_id[:8]} in {namespace}/",
                [str(path)],
            )

            await self._maybe_gc()

        return record

    async def supersede(
        self,
        original_id: str,
        new_content: str,
        reason: str = "",
        agent_id: str = "unknown",
        target_trail: TrailManager | None = None,
        **kwargs,
    ) -> ThoughtRecord:
        """Atomically supersede a thought: create new + backlink original in single JJ change.

        This is the SINGLE PERMITTED EXCEPTION to the immutability rule.
        Both the new thought creation AND the original's superseded_by backlink
        occur in a single JJ change. If process crashes mid-operation,
        either both writes exist or neither does.

        When target_trail is provided, the new thought is created in the target trail
        instead of the source trail (cross-scope supersession / scope elevation).
        """
        async with self._lock:
            # Find original in this trail
            original_path = self._find_thought_path(original_id)
            if original_path is None:
                raise ValueError(f"Thought {original_id} not found")

            original = ThoughtRecord.from_markdown(original_path.read_text())
            namespace = self._get_namespace_from_path(original_path)

            # Determine where the new thought lands
            dest = target_trail or self
            new_thoughts_dir = dest.trail_path / "thoughts" / namespace

            # Create new thought
            new_fm = ThoughtFrontmatter(
                agent_id=agent_id,
                source_type=original.frontmatter.source_type,
                confidence=kwargs.get("confidence", original.frontmatter.confidence),
                parent_id=original_id,
                intent_ref=original.frontmatter.intent_ref,
                metadata=original.frontmatter.metadata,
                relationships=original.frontmatter.relationships,
            )

            new_record = ThoughtRecord(frontmatter=new_fm, content=new_content)
            new_path = new_thoughts_dir / f"{new_record.thought_id}.md"

            # ATOMIC: Write both files before committing
            # 1. Write new thought (may be in a different trail)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(new_record.to_markdown())

            # 2. Backlink original (the ONLY permitted mutation)
            original.frontmatter.superseded_by = new_record.thought_id
            original_path.write_text(original.to_markdown())

            # 3. Single JJ change for both writes
            desc = f"Supersede {original_id[:8]} with {new_record.thought_id[:8]}"
            if target_trail:
                desc += f" (scope: {self.trail_name} → {target_trail.trail_name})"
            if reason:
                desc += f": {reason}"

            # For cross-scope supersede, allow both trail prefixes
            allowed_prefixes = None
            if target_trail and target_trail.trail_name != self.trail_name:
                trails_dir = get_trails_dir()
                repo_root = trails_dir.parent
                source_rel = str(self.trail_path.relative_to(repo_root))
                target_rel = str(dest.trail_path.relative_to(repo_root))
                allowed_prefixes = [source_rel, target_rel]

            await self.vcs.commit_files(
                desc,
                [str(new_path), str(original_path)],
                allowed_prefixes=allowed_prefixes,
            )

            await self._maybe_gc()

        # after_supersede hook — runs inline so feedback reaches the caller
        if self._hooks and self._hooks.has_hooks:
            after_event = AfterSupersedeEvent(
                trail_name=self.trail_name,
                new_thought=new_record,
                original_thought=original,
            )
            self._merge_observer_feedback(
                await dispatch_observer(self._hooks, after_event)
            )

        return new_record

    async def _recall_internal(
        self,
        query: str = "",
        namespace: str | None = None,
        limit: int = 20,
    ) -> list[ThoughtRecord]:
        """Internal recall that bypasses hooks. Used by TrailContext to prevent recursion."""
        return await self.recall(
            query=query,
            namespace=namespace,
            limit=limit,
            _skip_hooks=True,
        )

    async def recall(
        self,
        query: str = "",
        namespace: str | None = None,
        scope: dict | None = None,
        include_superseded: bool = False,
        include_relationships: bool = False,
        limit: int = 20,
        _skip_hooks: bool = False,
    ) -> list[ThoughtRecord]:
        """Search thoughts by query, namespace, and scope. Hides superseded by default."""
        self._set_feedback(None)
        results = []
        search_dirs = []

        if namespace:
            sanitize_namespace(namespace)  # Validate — prevents path traversal
            search_dirs.append(self._thoughts_dir(namespace))
        else:
            search_dirs.append(self.trail_path / "thoughts")

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for path in search_dir.rglob("*.md"):
                if path.name == ".gitkeep":
                    continue
                try:
                    record = ThoughtRecord.from_markdown(path.read_text())
                except Exception as e:
                    logger.debug("Failed to parse thought file %s: %s", path, e)
                    continue

                # Filter superseded
                if not include_superseded and record.is_superseded:
                    continue

                meta = record.frontmatter.metadata

                # Filter by scope
                if scope:
                    if "project" in scope and meta.project != scope["project"]:
                        continue
                    if "branch" in scope and meta.branch != scope["branch"]:
                        continue
                    if "tags" in scope:
                        required_tags = set(scope["tags"])
                        if not required_tags.issubset(set(meta.tags)):
                            continue

                # Filter by query (simple text match across all fields)
                if query:
                    query_lower = query.lower()
                    searchable = " ".join([
                        record.content.lower(),
                        record.frontmatter.thought_id.lower(),
                        (record.frontmatter.source_type.value if record.frontmatter.source_type else ""),
                        (record.frontmatter.agent_id or "").lower(),
                        (meta.project or "").lower(),
                        (meta.branch or "").lower(),
                        " ".join(t.lower() for t in meta.tags),
                    ])
                    query_words = query_lower.split()
                    if not all(word in searchable for word in query_words):
                        continue

                results.append(record)

                if len(results) >= limit:
                    break

        # 1-hop relationship traversal
        if include_relationships and results:
            related_ids = set()
            for r in results:
                for rel in r.frontmatter.relationships:
                    related_ids.add(rel.target_id)

            for rid in related_ids:
                if any(r.thought_id == rid for r in results):
                    continue
                related = await self.get_thought(rid)
                if related and (include_superseded or not related.is_superseded):
                    results.append(related)

        # on_recall hook — filter/reorder results
        if self._hooks and self._hooks.has_hooks and not _skip_hooks:
            recall_event = OnRecallEvent(
                trail_name=self.trail_name,
                results=results,
                query=query,
                namespace=namespace,
                scope=scope,
                context=TrailContext(self),
            )
            pipeline_result = await run_pipeline(self._hooks, recall_event)
            self._set_feedback(pipeline_result)
            if pipeline_result.recall_selection is not None:
                # Reorder/filter results by hook-specified ULID order
                ulid_order = {uid: i for i, uid in enumerate(pipeline_result.recall_selection)}
                results = sorted(
                    [r for r in results if r.thought_id in ulid_order],
                    key=lambda r: ulid_order[r.thought_id],
                )

        return results[:limit]

    async def propose_truth(
        self,
        thought_id: str,
        trust_result: TrustResult | None = None,
    ) -> ThoughtRecord:
        """Promote a thought from drafts/ to its permanent namespace based on source_type.

        When trust_result is provided, applies the review verdict:
          - approve: move to permanent namespace, set validation_status = "approved"
          - reject: keep in drafts, set validation_status = "rejected", attach reasoning
          - error: keep in drafts, set validation_status = "error", attach error reason
        When trust_result is None (backward compat): promotes without review.
        """
        async with self._lock:
            # Find the thought in drafts
            drafts_path = self._thought_path(thought_id, "drafts")
            if not drafts_path.exists():
                # Check other namespaces — persist the status update to disk
                existing_path = self._find_thought_path(thought_id)
                if existing_path:
                    record = ThoughtRecord.from_markdown(existing_path.read_text())
                    record.frontmatter.validation_status = ValidationStatus.PROPOSED
                    existing_path.write_text(record.to_markdown())
                    await self.vcs.commit_files(
                        f"Propose {thought_id[:8]} (already in {self._get_namespace_from_path(existing_path)}/)",
                        [str(existing_path)],
                    )
                    return record
                raise ValueError(f"Thought {thought_id} not found")

            record = ThoughtRecord.from_markdown(drafts_path.read_text())

            # Determine target namespace from source_type
            target_ns = NAMESPACE_ROUTES.get(record.frontmatter.source_type, "observations")

            # before_propose hook — can reject, mutate, or redirect promotion
            if self._hooks and self._hooks.has_hooks:
                propose_event = BeforeProposeEvent(
                    trail_name=self.trail_name,
                    thought=record,
                    target_namespace=target_ns,
                    context=TrailContext(self),
                )
                pipeline_result = await run_pipeline(self._hooks, propose_event)
                self._set_feedback(pipeline_result)
                if pipeline_result.rejected:
                    raise ValueError("before_propose hook rejected this promotion")
                if pipeline_result.redirect_namespace:
                    sanitize_namespace(pipeline_result.redirect_namespace)
                    target_ns = pipeline_result.redirect_namespace
                if pipeline_result.event and pipeline_result.event.thought:
                    record = pipeline_result.event.thought

            # Apply trust gate result if provided
            if trust_result is not None:
                # Attach provenance to thought metadata
                record.frontmatter.metadata.extra["trust_gate"] = {
                    "reviewer": trust_result.reviewer,
                    "reviewed_at": trust_result.reviewed_at.isoformat(),
                    "verdict": trust_result.verdict,
                    "reasoning": trust_result.reasoning,
                }
                if trust_result.confidence is not None:
                    record.frontmatter.metadata.extra["trust_gate"]["confidence"] = trust_result.confidence

                if trust_result.verdict == "reject":
                    record.frontmatter.validation_status = ValidationStatus.REJECTED
                    drafts_path.write_text(record.to_markdown())
                    await self.vcs.commit_files(
                        f"Reject {thought_id[:8]} (trust gate: {trust_result.reasoning[:50]})",
                        [str(drafts_path)],
                    )
                    return record

                if trust_result.verdict == "error":
                    record.frontmatter.validation_status = ValidationStatus.ERROR
                    drafts_path.write_text(record.to_markdown())
                    await self.vcs.commit_files(
                        f"Error reviewing {thought_id[:8]} (trust gate: {trust_result.reasoning[:50]})",
                        [str(drafts_path)],
                    )
                    return record

                # verdict == "approve" — proceed with promotion
                record.frontmatter.validation_status = ValidationStatus.APPROVED
            else:
                record.frontmatter.validation_status = ValidationStatus.PROPOSED

            target_path = self._thought_path(thought_id, target_ns)
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to new location and remove from drafts
            target_path.write_text(record.to_markdown())
            drafts_path.unlink()

            await self.vcs.commit_files(
                f"Promote {thought_id[:8]} from drafts/ to {target_ns}/ [{record.frontmatter.source_type.value}]",
                [str(target_path)],
            )

        # after_propose hook — runs inline so feedback reaches the caller
        if self._hooks and self._hooks.has_hooks:
            after_event = AfterProposeEvent(
                trail_name=self.trail_name,
                thought=record,
                trust_result=trust_result,
            )
            self._merge_observer_feedback(
                await dispatch_observer(self._hooks, after_event)
            )

        return record

    async def forget(self, revision: str = "") -> str:
        """Abandon a reasoning line."""
        async with self._lock:
            return await self.vcs.abandon(revision)

    async def sync(self) -> RebaseResult:
        """Sync with shared truth."""
        async with self._lock:
            result = await self.vcs.fetch_and_rebase()
            if result.has_conflicts:
                # Pull Daemon safety: abort on conflict
                logger.warning("Conflict after sync, restoring pre-sync state")
                await self.vcs.op_restore(result.pre_rebase_op_id)
            return result

    async def get_conflicts(self) -> list[VcsConflict]:
        """Surface cognitive dissonance — structured, never raw algebraic notation."""
        return await self.vcs.conflicts()

    async def rollback(self, op_id: str) -> str:
        """Restore trail to historical state."""
        async with self._lock:
            return await self.vcs.op_restore(op_id)

    async def get_diff(self, revision: str = "") -> VcsDiff:
        """Compare thought states."""
        return await self.vcs.diff(revision)

    async def get_op_log(self, limit: int = 10) -> list[VcsOpLogEntry]:
        """Get operation history as semantic summaries."""
        return await self.vcs.op_log(limit)

    async def start_thought(self, description: str = "") -> VcsChange:
        """Begin new reasoning branch from current truth."""
        async with self._lock:
            return await self.vcs.new_change(description)

    async def learn_preference(
        self,
        content: str,
        preference_type: str = "firm",
        agent_id: str = "unknown",
        metadata: dict | None = None,
    ) -> ThoughtRecord:
        """Capture user correction. Bypasses Trust Gate (user input is auto-approved)."""
        ns = f"preferences/{preference_type}"
        return await self.save_thought(
            content=content,
            agent_id=agent_id,
            source_type=SourceType.USER_INPUT,
            confidence=1.0,
            namespace=ns,
            metadata=metadata,
        )

    async def _maybe_gc(self) -> None:
        """Run GC if thresholds exceeded. Non-blocking — failures don't halt operations."""
        self._snapshot_count += 1
        elapsed = time.time() - self._last_gc_time

        should_gc = (
            self._snapshot_count >= self.config.gc_interval_snapshots
            or elapsed >= self.config.gc_interval_seconds
        )

        if should_gc:
            try:
                await self.vcs.gc()
                self._snapshot_count = 0
                self._last_gc_time = time.time()
                logger.info(f"GC completed for trail {self.trail_name}")
            except Exception as e:
                logger.warning(f"GC failed for trail {self.trail_name}: {e}")


async def recall_multi(
    trail_managers: list[TrailManager],
    query: str = "",
    namespace: str | None = None,
    scope: dict | None = None,
    include_superseded: bool = False,
    include_relationships: bool = False,
    limit: int = 20,
) -> list[tuple[ThoughtRecord, str]]:
    """Search across multiple scopes. Returns (thought, source_trail_name) tuples.

    Results deduplicated by thought_id. Each result tagged with its source trail name.
    After merging, fires on_recall_mix hook on the primary trail (trail_managers[0])
    so ACE and other reranking hooks can act on the full cross-trail result set.
    """
    seen_ids: set[str] = set()
    results: list[tuple[ThoughtRecord, str]] = []
    for tm in trail_managers:
        for r in await tm.recall(
            query=query,
            namespace=namespace,
            scope=scope,
            include_superseded=include_superseded,
            include_relationships=include_relationships,
            limit=limit,
        ):
            if r.thought_id not in seen_ids:
                seen_ids.add(r.thought_id)
                results.append((r, tm.trail_name))

    # on_recall_mix: fire AFTER merging, only when multiple distinct trails were searched.
    # Single-trail recalls are already handled by on_recall inside tm.recall().
    primary = trail_managers[0] if trail_managers else None
    distinct_trails = {tm.trail_name for tm in trail_managers} if trail_managers else set()
    if primary and len(distinct_trails) > 1 and primary._hooks and primary._hooks.has_hooks:
        mix_event = OnRecallEvent(
            lifecycle_point="on_recall_mix",
            trail_name=primary.trail_name,
            results=[r for r, _ in results],
            query=query,
            namespace=namespace,
            scope=scope,
            context=TrailContext(primary),
        )
        pipeline_result = await run_pipeline(primary._hooks, mix_event)
        # Merge with existing on_recall feedback from primary trail so
        # warnings/annotations from per-trail hooks are not lost.
        existing = primary.consume_feedback()
        if existing is not None:
            pipeline_result.feedback.merge_from(existing.feedback)
        primary._set_feedback(pipeline_result)
        if pipeline_result.recall_selection is not None:
            # Reorder/filter the (ThoughtRecord, trail_name) tuples by hook-specified ULID order
            ulid_order = {uid: i for i, uid in enumerate(pipeline_result.recall_selection)}
            results = sorted(
                [pair for pair in results if pair[0].thought_id in ulid_order],
                key=lambda pair: ulid_order[pair[0].thought_id],
            )

    return results[:limit]

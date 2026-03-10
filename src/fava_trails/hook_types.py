"""Hook type system for the Event-Action Pipeline.

Defines typed Events, Actions, HookFeedback, ThoughtPatch, TrailContext,
and startup return types. All events and actions are frozen dataclasses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ulid import ULID

if TYPE_CHECKING:
    from .models import ThoughtRecord
    from .trust_gate import TrustResult

logger = logging.getLogger(__name__)

HOOK_API_VERSION = "2.0"

# --- Actions (what a hook WANTS TO DO) ---


@dataclass(frozen=True)
class Proceed:
    """No-op — continue pipeline."""


@dataclass(frozen=True)
class Reject:
    """Halt pipeline, block the operation."""
    reason: str
    code: str = ""


@dataclass(frozen=True)
class Warn:
    """Accept but surface a concern to the agent."""
    message: str
    code: str = ""


@dataclass(frozen=True)
class Advise:
    """Guidance for the agent, surfaced in MCP response."""
    message: str
    code: str = ""
    suggested_patch: dict[str, Any] | None = None
    target: str = "agent"


@dataclass(frozen=True)
class Mutate:
    """Change thought content/metadata/tags/confidence via a patch."""
    patch: ThoughtPatch


@dataclass(frozen=True)
class Redirect:
    """Save/promote to a different namespace. Terminal — depth=1, no re-entry."""
    namespace: str


@dataclass(frozen=True)
class Annotate:
    """Attach metadata without modifying thought core."""
    values: dict[str, Any]


@dataclass(frozen=True)
class RecallSelect:
    """Provenance-safe reorder/filter of recall results. on_recall only."""
    ordered_ulids: list[str]
    reason: str = ""


# Union of all action types for type hints
Action = Proceed | Reject | Warn | Advise | Mutate | Redirect | Annotate | RecallSelect


# --- ThoughtPatch (for Mutate action) ---


@dataclass
class ThoughtPatch:
    """Partial update to a thought. All fields optional — only set fields are applied."""
    content: str | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    confidence: float | None = None

    def apply(self, thought: ThoughtRecord) -> ThoughtRecord:
        """Apply this patch to a ThoughtRecord, returning a modified copy."""
        import copy
        patched = copy.deepcopy(thought)
        if self.content is not None:
            patched.content = self.content
        if self.metadata is not None:
            patched.frontmatter.metadata.extra.update(self.metadata)
        if self.tags is not None:
            patched.frontmatter.metadata.tags = list(self.tags)
        if self.confidence is not None:
            patched.frontmatter.confidence = self.confidence
        return patched


# --- Startup Returns (separate contract, NOT Actions) ---


@dataclass(frozen=True)
class StartupOk:
    """Startup hook succeeded."""
    message: str = ""


@dataclass(frozen=True)
class StartupWarn:
    """Startup hook succeeded with warnings."""
    message: str = ""


@dataclass(frozen=True)
class StartupFail:
    """Startup hook failed — server should exit."""
    message: str = ""


StartupResult = StartupOk | StartupWarn | StartupFail


# --- Events (typed per lifecycle point) ---


@dataclass(frozen=True)
class HookEvent:
    """Base event passed to lifecycle hooks."""
    trail_name: str
    lifecycle_point: str = ""
    event_id: str = field(default_factory=lambda: str(ULID()))
    request_id: str = ""
    actor: str = ""
    hook_api_version: str = HOOK_API_VERSION


def _make_event(cls: type, lifecycle_point: str, **kwargs: Any) -> Any:
    """Factory to create frozen event subclasses with lifecycle_point set."""
    return cls(lifecycle_point=lifecycle_point, **kwargs)


@dataclass(frozen=True)
class BeforeSaveEvent(HookEvent):
    """Fired before a thought is saved. Hook can reject, mutate, or redirect."""
    thought: ThoughtRecord | None = None
    namespace: str = ""
    context: TrailContext | None = None

    def __post_init__(self) -> None:
        if not self.lifecycle_point:
            object.__setattr__(self, "lifecycle_point", "before_save")


@dataclass(frozen=True)
class AfterSaveEvent(HookEvent):
    """Fired after a thought is committed. Observer-only."""
    thought: ThoughtRecord | None = None
    namespace: str = ""

    def __post_init__(self) -> None:
        if not self.lifecycle_point:
            object.__setattr__(self, "lifecycle_point", "after_save")


@dataclass(frozen=True)
class BeforeProposeEvent(HookEvent):
    """Fired before a thought is promoted. Hook can reject, mutate, or redirect."""
    thought: ThoughtRecord | None = None
    target_namespace: str = ""
    context: TrailContext | None = None

    def __post_init__(self) -> None:
        if not self.lifecycle_point:
            object.__setattr__(self, "lifecycle_point", "before_propose")


@dataclass(frozen=True)
class AfterProposeEvent(HookEvent):
    """Fired after a thought is promoted. Observer-only."""
    thought: ThoughtRecord | None = None
    trust_result: TrustResult | None = None

    def __post_init__(self) -> None:
        if not self.lifecycle_point:
            object.__setattr__(self, "lifecycle_point", "after_propose")


@dataclass(frozen=True)
class AfterSupersedeEvent(HookEvent):
    """Fired after a thought is superseded. Observer-only."""
    new_thought: ThoughtRecord | None = None
    original_thought: ThoughtRecord | None = None

    def __post_init__(self) -> None:
        if not self.lifecycle_point:
            object.__setattr__(self, "lifecycle_point", "after_supersede")


@dataclass(frozen=True)
class OnRecallEvent(HookEvent):
    """Fired during recall. Hook can filter/reorder via RecallSelect."""
    results: list[Any] = field(default_factory=list)
    query: str = ""
    namespace: str | None = None
    scope: dict[str, Any] | None = None
    context: TrailContext | None = None

    def __post_init__(self) -> None:
        if not self.lifecycle_point:
            object.__setattr__(self, "lifecycle_point", "on_recall")


@dataclass
class OnStartupEvent:
    """Fired at server startup. Separate contract — NOT a HookEvent subclass."""
    trails_dir: Path | None = None
    config: dict[str, Any] = field(default_factory=dict)


# --- Action Validity Matrix ---

ACTION_VALIDITY: dict[str, set[type]] = {
    "before_save": {Proceed, Reject, Mutate, Redirect, Warn, Advise, Annotate},
    "after_save": {Warn, Advise, Annotate},
    "before_propose": {Proceed, Reject, Mutate, Redirect, Warn, Advise, Annotate},
    "after_propose": {Warn, Advise, Annotate},
    "after_supersede": {Warn, Advise, Annotate},
    "on_recall": {Proceed, Warn, Advise, Annotate, RecallSelect},
}


def validate_action(lifecycle_point: str, action: Action) -> bool:
    """Check if an action type is valid for a given lifecycle point."""
    valid = ACTION_VALIDITY.get(lifecycle_point)
    if valid is None:
        return False
    return type(action) in valid


# --- HookFeedback (accumulated per request) ---

MAX_WARNINGS = 20
MAX_ADVICE = 20
MAX_MESSAGE_BYTES = 4096


def _truncate_message(msg: str) -> str:
    """Truncate a message to MAX_MESSAGE_BYTES."""
    encoded = msg.encode("utf-8")
    if len(encoded) <= MAX_MESSAGE_BYTES:
        return msg
    return encoded[:MAX_MESSAGE_BYTES].decode("utf-8", errors="ignore")


@dataclass
class HookFeedback:
    """Accumulated feedback from hook pipeline, attached to MCP responses."""
    accepted: bool = True
    mutated: bool = False
    redirected_to: str | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)
    advice: list[dict[str, Any]] = field(default_factory=list)

    def merge(self, action: Action) -> None:
        """Merge an action's effects into this feedback."""
        if isinstance(action, Reject):
            self.accepted = False
        elif isinstance(action, Warn):
            if len(self.warnings) < MAX_WARNINGS:
                self.warnings.append({
                    "message": _truncate_message(action.message),
                    "code": action.code,
                })
        elif isinstance(action, Advise):
            if len(self.advice) < MAX_ADVICE:
                entry: dict[str, Any] = {
                    "message": _truncate_message(action.message),
                    "code": action.code,
                    "target": action.target,
                }
                if action.suggested_patch is not None:
                    entry["suggested_patch"] = action.suggested_patch
                self.advice.append(entry)
        elif isinstance(action, Annotate):
            self.annotations.update(action.values)
        elif isinstance(action, Mutate):
            self.mutated = True
        elif isinstance(action, Redirect):
            self.redirected_to = action.namespace

    def merge_from(self, other: HookFeedback) -> None:
        """Merge another HookFeedback into this one."""
        if not other.accepted:
            self.accepted = False
        if other.mutated:
            self.mutated = True
        if other.redirected_to is not None:
            self.redirected_to = other.redirected_to
        self.annotations.update(other.annotations)
        for w in other.warnings:
            if len(self.warnings) < MAX_WARNINGS:
                self.warnings.append(w)
        for a in other.advice:
            if len(self.advice) < MAX_ADVICE:
                self.advice.append(a)

    def is_empty(self) -> bool:
        """True if no feedback was generated (skip in MCP response)."""
        return (
            self.accepted
            and not self.mutated
            and self.redirected_to is None
            and not self.annotations
            and not self.warnings
            and not self.advice
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for MCP response. Omits empty fields."""
        d: dict[str, Any] = {"accepted": self.accepted}
        if self.mutated:
            d["mutated"] = True
        if self.redirected_to is not None:
            d["redirected_to"] = self.redirected_to
        if self.annotations:
            d["annotations"] = self.annotations
        if self.warnings:
            d["warnings"] = self.warnings
        if self.advice:
            d["advice"] = self.advice
        return d


# --- TrailContext (lazy, hook-safe) ---

TRAIL_CONTEXT_RECALL_LIMIT = 50


class TrailContext:
    """Read-only context for hooks to query trail state.

    Uses _recall_internal to prevent recursive hook firing.
    All methods are async to match TrailManager's interface.
    """

    def __init__(self, trail_manager: Any) -> None:
        self._trail = trail_manager

    async def stats(self) -> dict[str, int]:
        """Thought count by namespace."""
        counts: dict[str, int] = {}
        thoughts_dir = self._trail.trail_path / "thoughts"
        if not thoughts_dir.exists():
            return counts
        for ns_dir in thoughts_dir.iterdir():
            if ns_dir.is_dir():
                count = sum(1 for f in ns_dir.rglob("*.md") if f.name != ".gitkeep")
                if count > 0:
                    counts[ns_dir.name] = count
        return counts

    async def count(self, namespace: str | None = None) -> int:
        """Count thoughts, optionally filtered by namespace."""
        if namespace:
            ns_dir = self._trail.trail_path / "thoughts" / namespace
            if not ns_dir.exists():
                return 0
            return sum(1 for f in ns_dir.rglob("*.md") if f.name != ".gitkeep")
        stats = await self.stats()
        return sum(stats.values())

    async def recall(
        self,
        query: str = "",
        namespace: str | None = None,
        limit: int = TRAIL_CONTEXT_RECALL_LIMIT,
    ) -> list[ThoughtRecord]:
        """Search thoughts using _recall_internal (bypasses hooks)."""
        capped_limit = min(limit, TRAIL_CONTEXT_RECALL_LIMIT)
        return await self._trail._recall_internal(
            query=query,
            namespace=namespace,
            limit=capped_limit,
        )

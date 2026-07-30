"""Pydantic models for FAVA Trail thought records and configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, NonNegativeInt, field_validator, model_validator
from ulid import ULID


class SourceType(StrEnum):
    OBSERVATION = "observation"
    INFERENCE = "inference"
    USER_INPUT = "user_input"
    TOOL_OUTPUT = "tool_output"
    DECISION = "decision"


class ValidationStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"
    TOMBSTONED = "tombstoned"


class RelationshipType(StrEnum):
    DEPENDS_ON = "DEPENDS_ON"
    REVISED_BY = "REVISED_BY"
    AUTHORED_BY = "AUTHORED_BY"
    REFERENCES = "REFERENCES"
    SUPERSEDES = "SUPERSEDES"


class Relationship(BaseModel):
    type: RelationshipType
    target_id: str


class ThoughtMetadata(BaseModel):
    project: str | None = None
    branch: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ThoughtFrontmatter(BaseModel):
    """YAML frontmatter for a thought file."""

    schema_version: int = 1
    thought_id: str = Field(default_factory=lambda: str(ULID()))
    parent_id: str | None = None
    superseded_by: str | None = None
    agent_id: str = "unknown"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_type: SourceType = SourceType.OBSERVATION
    validation_status: ValidationStatus = ValidationStatus.DRAFT
    intent_ref: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    relationships: list[Relationship] = Field(default_factory=list)
    metadata: ThoughtMetadata = Field(default_factory=ThoughtMetadata)

    @field_validator("thought_id", "parent_id", "superseded_by", "intent_ref", mode="before")
    @classmethod
    def validate_ulid_format(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            # Accept any non-empty string — ULIDs are 26 chars but we don't enforce strictly
            # to allow flexibility during testing
            pass
        return v


class ThoughtRecord(BaseModel):
    """Complete thought record: frontmatter + body content."""

    frontmatter: ThoughtFrontmatter
    content: str = ""

    @property
    def thought_id(self) -> str:
        return self.frontmatter.thought_id

    @property
    def is_superseded(self) -> bool:
        return self.frontmatter.superseded_by is not None

    def to_markdown(self) -> str:
        """Serialize to markdown with YAML frontmatter."""
        import yaml

        fm = self.frontmatter.model_dump(mode="json", exclude_none=True)
        # Convert datetime to ISO string
        if "created_at" in fm and isinstance(fm["created_at"], str):
            pass  # already string from mode="json"
        # Convert enums
        if "source_type" in fm:
            fm["source_type"] = str(fm["source_type"])
        if "validation_status" in fm:
            fm["validation_status"] = str(fm["validation_status"])
        # Convert relationships
        if "relationships" in fm:
            fm["relationships"] = [
                {"type": str(r["type"]), "target_id": r["target_id"]} for r in fm["relationships"]
            ]

        yaml_str = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return f"---\n{yaml_str}---\n{self.content}"

    @classmethod
    def from_markdown(cls, text: str) -> ThoughtRecord:
        """Parse a markdown file with YAML frontmatter."""
        import yaml

        if not text.startswith("---"):
            return cls(frontmatter=ThoughtFrontmatter(), content=text)

        parts = text.split("---", 2)
        if len(parts) < 3:
            return cls(frontmatter=ThoughtFrontmatter(), content=text)

        yaml_str = parts[1].strip()
        content = parts[2].strip()

        fm_dict = yaml.safe_load(yaml_str) or {}
        frontmatter = ThoughtFrontmatter(**fm_dict)
        return cls(frontmatter=frontmatter, content=content)


KNOWN_HOOKS = frozenset({
    "before_save",
    "after_save",
    "before_propose",
    "after_propose",
    "after_supersede",
    "on_recall",
    "on_recall_mix",
    "on_startup",
})


class HookEntry(BaseModel):
    """A single hook entry in global or trail config."""

    module: str | None = None
    path: str | None = None
    points: list[str]
    order: int = 50
    fail_mode: str = "open"
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exactly_one_source(self) -> HookEntry:
        if self.module and self.path:
            raise ValueError("Hook entry must have either 'module' or 'path', not both")
        if not self.module and not self.path:
            raise ValueError("Hook entry must have either 'module' or 'path'")
        return self

    @field_validator("points")
    @classmethod
    def validate_points(cls, v: list[str]) -> list[str]:
        for p in v:
            if p not in KNOWN_HOOKS:
                raise ValueError(f"Unknown lifecycle point: {p!r}. Valid: {sorted(KNOWN_HOOKS)}")
        return v

    @field_validator("fail_mode")
    @classmethod
    def validate_fail_mode(cls, v: str) -> str:
        if v not in ("open", "closed"):
            raise ValueError(f"fail_mode must be 'open' or 'closed', got {v!r}")
        return v


# Namespace routing: source_type -> permanent namespace
NAMESPACE_ROUTES: dict[SourceType, str] = {
    SourceType.DECISION: "decisions",
    SourceType.OBSERVATION: "observations",
    SourceType.INFERENCE: "observations",
    SourceType.TOOL_OUTPUT: "observations",
    SourceType.USER_INPUT: "preferences",
}

# Default namespace for save_thought
DEFAULT_NAMESPACE = "drafts"


class TrailConfig(BaseModel):
    """Configuration for a single trail."""

    name: str
    default_namespace: str = DEFAULT_NAMESPACE
    trust_gate_policy: str = "llm-oneshot"  # llm-oneshot | human (future)
    gc_interval_snapshots: int = 500
    gc_interval_seconds: int = 3600
    stale_draft_days: int = 0  # 0 = disabled; >0 = tombstone drafts older than N days
    hooks: list[HookEntry] = Field(default_factory=list)

    @field_validator("hooks")
    @classmethod
    def hooks_not_yet_supported(cls, v: list[HookEntry]) -> list[HookEntry]:
        if v:
            raise ValueError(
                "Per-trail hook overrides not yet supported — "
                "define hooks in global config.yaml"
            )
        return v


class GlobalConfig(BaseModel):
    """Global FAVA Trail configuration."""

    trails_dir: str = "trails"
    remote_url: str | None = None
    push_strategy: str = "manual"  # manual | immediate
    trust_gate: str = "llm-oneshot"  # llm-oneshot | human (future)
    # Provider-neutral Trust Gate LLM settings (default: OpenRouter).
    trust_gate_provider: str = "openrouter"
    trust_gate_model: str = "google/gemini-2.5-flash"
    trust_gate_api_base: str | None = None
    # Preferred env-var name for the Trust Gate API key. When unset, falls back
    # to openrouter_api_key_env for backward compatibility with existing configs.
    trust_gate_api_key_env: str | None = None
    # Deprecated alias for trust_gate_api_key_env (OpenRouter default).
    openrouter_api_key_env: str = "OPENROUTER_API_KEY"
    # Timeout for the Trust Gate LLM call (asyncio.wait_for guard).
    # Should be well above a normal slow response (e.g. 60-90s) but short enough
    # to recover from a hung provider before the session times out. 0 = disabled.
    # Slow local quantized models may need a higher value; keep it below tool_timeout_secs.
    trust_gate_timeout_secs: NonNegativeInt = 120
    # Timeout for an entire MCP tool call (outermost guard covering all tools).
    # Catches jj hangs, slow syncs, and any other unanticipated blocking.
    # Should be generous — set 0 to disable.
    tool_timeout_secs: NonNegativeInt = 300
    trails: dict[str, TrailConfig] = Field(default_factory=dict)
    hooks: list[HookEntry] = Field(default_factory=list)

    def resolve_trust_gate_api_key_env(self) -> str:
        """Return the env var name that holds the Trust Gate API key.

        Prefers ``trust_gate_api_key_env`` when set; otherwise the legacy
        ``openrouter_api_key_env`` alias (default ``OPENROUTER_API_KEY``).
        """
        if self.trust_gate_api_key_env:
            return self.trust_gate_api_key_env
        return self.openrouter_api_key_env

    @field_validator("trust_gate_provider", "trust_gate_model", "openrouter_api_key_env")
    @classmethod
    def non_empty_trust_gate_str(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip()

    @field_validator("trust_gate_api_key_env")
    @classmethod
    def normalize_trust_gate_api_key_env(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            raise ValueError("trust_gate_api_key_env must be a non-empty string when set")
        return v.strip()

    @field_validator("trust_gate_api_base")
    @classmethod
    def normalize_trust_gate_api_base(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip():
            raise ValueError("trust_gate_api_base must be a non-empty URL when set")
        base = v.strip()
        if not (base.startswith("http://") or base.startswith("https://")):
            raise ValueError("trust_gate_api_base must start with http:// or https://")
        return base

    @model_validator(mode="after")
    def trust_gate_timeout_within_tool_timeout(self) -> GlobalConfig:
        """Ensure Trust Gate timeout fires before the outer tool timeout.

        If both are enabled and trust_gate_timeout_secs >= tool_timeout_secs,
        the outer guard fires first with a generic error, hiding the specific
        Trust Gate message. Fail early so misconfiguration is obvious.
        """
        tg = self.trust_gate_timeout_secs
        tool = self.tool_timeout_secs
        if tg > 0 and tool > 0 and tg >= tool:
            raise ValueError(
                f"trust_gate_timeout_secs ({tg}) must be less than "
                f"tool_timeout_secs ({tool}) so the Trust Gate timeout fires "
                "before the outer tool timeout. Set either to 0 to disable it."
            )
        return self

    def validate_trust_gate_runtime(self) -> str:
        """Validate Trust Gate provider configuration for startup/preflight.

        Returns the resolved API-key environment variable name. Raises
        ``ValueError`` when the typed provider/model/base/key-env contract is
        incomplete for ``llm-oneshot``.
        """
        if self.trust_gate != "llm-oneshot":
            return self.resolve_trust_gate_api_key_env()

        provider = self.trust_gate_provider
        model = self.trust_gate_model
        if not provider:
            raise ValueError("trust_gate_provider must be a non-empty string")
        if not model:
            raise ValueError("trust_gate_model must be a non-empty string")

        # Local / custom OpenAI-compatible endpoints need an explicit API base.
        # Hosted OpenRouter keeps the historical default (no api_base).
        if provider != "openrouter" and not self.trust_gate_api_base:
            raise ValueError(
                f"trust_gate_api_base is required when trust_gate_provider is {provider!r} "
                "(set the OpenAI-compatible base URL, e.g. http://127.0.0.1:<port>/v1)"
            )

        key_env = self.resolve_trust_gate_api_key_env()
        if not key_env:
            raise ValueError("Trust Gate API key environment variable name is empty")
        return key_env

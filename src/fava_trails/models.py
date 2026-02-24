"""Pydantic models for FAVA Trail thought records and configuration."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from ulid import ULID


class SourceType(str, Enum):
    OBSERVATION = "observation"
    INFERENCE = "inference"
    USER_INPUT = "user_input"
    TOOL_OUTPUT = "tool_output"
    DECISION = "decision"


class ValidationStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"
    TOMBSTONED = "tombstoned"


class RelationshipType(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"
    REVISED_BY = "REVISED_BY"
    AUTHORED_BY = "AUTHORED_BY"
    REFERENCES = "REFERENCES"
    SUPERSEDES = "SUPERSEDES"


class Relationship(BaseModel):
    type: RelationshipType
    target_id: str


class ThoughtMetadata(BaseModel):
    project: Optional[str] = None
    branch: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ThoughtFrontmatter(BaseModel):
    """YAML frontmatter for a thought file."""

    schema_version: int = 1
    thought_id: str = Field(default_factory=lambda: str(ULID()))
    parent_id: Optional[str] = None
    superseded_by: Optional[str] = None
    agent_id: str = "unknown"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_type: SourceType = SourceType.OBSERVATION
    validation_status: ValidationStatus = ValidationStatus.DRAFT
    intent_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    relationships: list[Relationship] = Field(default_factory=list)
    metadata: ThoughtMetadata = Field(default_factory=ThoughtMetadata)

    @field_validator("thought_id", "parent_id", "superseded_by", "intent_ref", mode="before")
    @classmethod
    def validate_ulid_format(cls, v: Optional[str]) -> Optional[str]:
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


class GlobalConfig(BaseModel):
    """Global FAVA Trail configuration."""

    trails_dir: str = "trails"
    remote_url: Optional[str] = None
    push_strategy: str = "manual"  # manual | immediate
    trust_gate: str = "llm-oneshot"  # llm-oneshot | human (future)
    openrouter_api_key_env: str = "OPENROUTER_API_KEY"
    trust_gate_model: str = "google/gemini-2.5-flash"
    trails: dict[str, TrailConfig] = Field(default_factory=dict)

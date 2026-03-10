"""ACE Playbook Rule engine.

PlaybookRule models a single rule stored in the preferences/ namespace with
the ``ace-playbook`` tag. Rules are parsed from ThoughtRecord objects via
_parse_rules() and applied multiplicatively during on_recall scoring.

Rule types:
- retrieval_priority: boosts or deprioritizes matching thoughts (default)
- confidence_floor: deprioritizes low-confidence thoughts
- staleness: deprioritizes old thoughts
- anti_pattern: detected in before_save; does NOT contribute a score multiplier
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fava_trails.models import ThoughtRecord

logger = logging.getLogger(__name__)

# Score multiplier clamping bounds (plan consensus addition)
SCORE_CLAMP_MIN = 0.5
SCORE_CLAMP_MAX = 2.0


@dataclass
class PlaybookRule:
    """A single ACE playbook rule parsed from a FAVA Trails thought.

    Attributes:
        name:             Short identifier (first 8 chars of thought_id).
        rule_type:        One of retrieval_priority | confidence_floor |
                          staleness | anti_pattern.
        match:            Dict of match criteria (AND logic).
        action:           Dict describing score adjustment: {"boost": N} or
                          {"deprioritize": N}.
        weight:           Conflict-resolution priority (higher wins).
        helpful_count:    ACE-style feedback counter.
        harmful_count:    ACE-style feedback counter.
        section:          Playbook section label.
        description:      Human-readable description of the rule.
        source_thought_id: ULID of the originating thought.
    """

    name: str
    rule_type: str
    match: dict[str, Any]
    action: dict[str, Any]
    weight: int = 0
    helpful_count: int = 0
    harmful_count: int = 0
    section: str = ""
    description: str = ""
    source_thought_id: str = ""

    # Match criteria keys understood by matches()
    _MATCH_KEYS: frozenset[str] = field(
        default=frozenset({
            "source_type", "confidence_lt", "tags_include", "tags_exclude", "age_lt_days"
        }),
        init=False,
        repr=False,
        compare=False,
    )

    def matches(self, thought: ThoughtRecord) -> bool:
        """Return True if ALL match criteria are satisfied (AND logic).

        Supported criteria:
          source_type:    str  — frontmatter.source_type must equal this value
          confidence_lt:  float — frontmatter.confidence must be < this value
          tags_include:   list[str] — thought must have ALL these tags
          tags_exclude:   list[str] — thought must have NONE of these tags
          age_lt_days:    float — thought must have been created within N days
        """
        fm = thought.frontmatter
        m = self.match

        if "source_type" in m:
            if fm.source_type.value != m["source_type"]:
                return False

        if "confidence_lt" in m:
            confidence = 0.0 if fm.confidence is None else fm.confidence
            if confidence >= m["confidence_lt"]:
                return False

        thought_tags = set(fm.metadata.tags or [])

        if "tags_include" in m:
            if not set(m["tags_include"]).issubset(thought_tags):
                return False

        if "tags_exclude" in m:
            if set(m["tags_exclude"]).intersection(thought_tags):
                return False

        if "age_lt_days" in m:
            try:
                created = fm.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                age_days = (datetime.now(UTC) - created).total_seconds() / 86400
                if age_days >= m["age_lt_days"]:
                    return False
            except Exception:
                # Defensive: if age check fails, default to matching (non-blocking)
                pass

        unknown = m.keys() - self._MATCH_KEYS
        if unknown:
            logger.warning(
                "ACE rule %s: unknown match key(s) %s — "
                "valid keys are %s (did you mean 'tags_include' or 'tags_exclude'?)",
                self.name,
                sorted(unknown),
                sorted(self._MATCH_KEYS),
            )

        return True

    def evaluate(self, thought: ThoughtRecord) -> float:
        """Return a multiplicative score factor for this rule.

        anti_pattern rules contribute 1.0 (neutral) — they signal in before_save,
        not during scoring. All other rules apply only when matches() is True.

        Uses Laplace-smoothed helpful/harmful ratio:
          ratio = (helpful_count + 1) / (helpful_count + harmful_count + 2)

        The base score is derived from action["boost"] or action["deprioritize"].
        Final result is clamped to [SCORE_CLAMP_MIN, SCORE_CLAMP_MAX].
        """
        if self.rule_type == "anti_pattern":
            return 1.0

        if not self.matches(thought):
            return 1.0

        helpful = max(0, self.helpful_count)
        harmful = max(0, self.harmful_count)
        ratio = (helpful + 1) / (helpful + harmful + 2)
        base_score = self.action.get("boost", self.action.get("deprioritize", 1.0))

        result = base_score * ratio
        return max(SCORE_CLAMP_MIN, min(SCORE_CLAMP_MAX, result))


def _parse_rules(raw_thoughts: list[ThoughtRecord]) -> list[PlaybookRule]:
    """Parse ThoughtRecord objects into PlaybookRule instances.

    Reads rule fields from metadata.extra. Malformed entries are skipped with
    a warning — never crash recall.
    """
    rules: list[PlaybookRule] = []
    for thought in raw_thoughts:
        try:
            extra = thought.frontmatter.metadata.extra or {}
            match = extra.get("match", {})
            action = extra.get("action", {})
            if not isinstance(match, dict) or not isinstance(action, dict):
                logger.warning(
                    "ACE: skipping rule %s: match/action must be dicts",
                    thought.thought_id[:8],
                )
                continue
            rule = PlaybookRule(
                name=thought.thought_id[:8],
                rule_type=extra.get("rule_type", "retrieval_priority"),
                match=match,
                action=action,
                weight=int(extra.get("weight", 0)),
                helpful_count=int(extra.get("helpful_count", 0)),
                harmful_count=int(extra.get("harmful_count", 0)),
                section=str(extra.get("section", "")),
                description=str(extra.get("description", "")),
                source_thought_id=thought.thought_id,
            )
            rules.append(rule)
        except Exception as e:
            logger.warning(
                "ACE: skipping malformed rule %s: %s",
                getattr(thought, "thought_id", "?")[:8],
                e,
            )
    return rules

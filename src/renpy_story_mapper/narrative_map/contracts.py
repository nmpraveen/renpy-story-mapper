"""Versioned, deterministic contracts shared by all M15 tracks.

These records keep AI boundary decisions and optional prose subordinate to exact M10/M11
authority.  Identity-bearing records exclude mutable presentation prose from their stable IDs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from renpy_story_mapper.storage import canonical_json

M15_CORRIDOR_SCHEMA = "m15-narrative-corridor-v1"
M15_BOUNDARY_SCHEMA = "m15-boundary-decision-v1"
M15_EVENT_SCHEMA = "m15-narrative-event-v1"
M15_MAP_SCHEMA = "m15-narrative-map-v1"
M15_CORRIDOR_RULE_VERSION = "m15-corridor-rules-v1"
M15_TECHNICAL_CORRECTION_SCHEMA = "m15-leading-technical-coverage-correction-v1"
M15_TECHNICAL_CORRECTION_RULE_VERSION = "m15-leading-technical-coverage-rule-v1"

MAX_REASON_LENGTH = 500
MAX_TITLE_LENGTH = 80
MAX_SUMMARY_LENGTH = 600
MAX_REFERENCES = 100_000

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class BoundarySignal(StrEnum):
    LOCATION = "location"
    CAST = "cast"
    NARRATIVE_OBJECTIVE = "narrative_objective"
    RESOLVED_TRANSFER = "resolved_transfer"
    VISUAL_FAMILY = "visual_family"


class BoundaryDecisionKind(StrEnum):
    MERGE = "merge"
    SPLIT = "split"
    UNCERTAIN = "uncertain"


class CoverageState(StrEnum):
    COMPLETE = "complete"
    TECHNICAL = "technical"
    UNRESOLVED = "unresolved"
    PARTIAL_ENRICHMENT = "partial_enrichment"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class NarrativeNodeKind(StrEnum):
    EVENT_CLUSTER = "event_cluster"
    SUB_EVENT = "sub_event"
    CHOICE = "choice"
    CHOICE_ARM = "choice_arm"
    REJOIN = "rejoin"
    CONTINUATION = "continuation"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"
    TECHNICAL_COVERAGE = "technical_coverage"


class NarrativeEdgeKind(StrEnum):
    CONTINUATION = "continuation"
    CHOICE_ARM = "choice_arm"
    REJOIN = "rejoin"
    PERSISTENT_SPLIT = "persistent_split"
    PERSISTENT_MERGE = "persistent_merge"
    CALL = "call"
    RETURN = "return"
    LOOP = "loop"
    TERMINAL = "terminal"
    UNRESOLVED = "unresolved"


def _require_text(value: str, label: str, *, maximum: int | None = None) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")


def _require_optional_text(value: str | None, label: str) -> None:
    if value is not None:
        _require_text(value, label)


def _require_unique(values: tuple[str, ...], label: str, *, allow_empty: bool = True) -> None:
    if not allow_empty and not values:
        raise ValueError(f"{label} requires at least one value")
    if len(values) > MAX_REFERENCES:
        raise ValueError(f"{label} exceeds the bounded reference limit")
    for value in values:
        _require_text(value, label)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stable_m15_id(prefix: str, value: object) -> str:
    _require_text(prefix, "identity prefix")
    return f"{prefix}_{canonical_hash(value)[:24]}"


@dataclass(frozen=True)
class AuthorityBinding:
    source_generation: str
    canonical_schema: str
    canonical_hash: str
    atom_schema: str
    atom_hash: str

    def __post_init__(self) -> None:
        for name in (
            "source_generation",
            "canonical_schema",
            "canonical_hash",
            "atom_schema",
            "atom_hash",
        ):
            _require_text(str(getattr(self, name)), name)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source_generation": self.source_generation,
            "canonical_schema": self.canonical_schema,
            "canonical_hash": self.canonical_hash,
            "atom_schema": self.atom_schema,
            "atom_hash": self.atom_hash,
        }

    @property
    def identity(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, order=True)
class SourceLocator:
    relative_path: str
    start_line: int
    end_line: int
    line_basis: str

    def __post_init__(self) -> None:
        _require_text(self.relative_path, "relative source path")
        path = PurePosixPath(self.relative_path.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
            raise ValueError("source locators require a safe relative path")
        object.__setattr__(self, "relative_path", path.as_posix())
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("source locators require a valid inclusive line range")
        _require_text(self.line_basis, "line basis")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "relative_path": self.relative_path.replace("\\", "/"),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line_basis": self.line_basis,
        }


@dataclass(frozen=True)
class QualifiedSourceLocator:
    """One source range qualified by exact M11/M10 occurrence identity."""

    atom_id: str
    primary_node_id: str
    evidence_ids: tuple[str, ...]
    source: SourceLocator

    def __post_init__(self) -> None:
        _require_text(self.atom_id, "qualified locator atom ID")
        _require_text(self.primary_node_id, "qualified locator primary node ID")
        _require_unique(self.evidence_ids, "qualified locator evidence ID")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "atom_id": self.atom_id,
            "primary_node_id": self.primary_node_id,
            "evidence_ids": list(self.evidence_ids),
            "source": self.source.to_dict(),
        }


@dataclass(frozen=True)
class LeadingTechnicalCoverageCorrection:
    """Explicit authority for one exact, leading technical-coverage prefix."""

    authority: AuthorityBinding
    reason: str
    qualified_locators: tuple[QualifiedSourceLocator, ...]
    ordered_atom_ids: tuple[str, ...]
    rule_version: str = M15_TECHNICAL_CORRECTION_RULE_VERSION

    def __post_init__(self) -> None:
        _require_text(self.reason, "technical correction reason", maximum=MAX_REASON_LENGTH)
        _require_unique(
            self.ordered_atom_ids,
            "technical correction atom ID",
            allow_empty=False,
        )
        if not self.qualified_locators:
            raise ValueError("technical correction qualified locators require at least one value")
        if len(self.qualified_locators) > MAX_REFERENCES:
            raise ValueError("technical correction qualified locators exceed the bounded limit")
        if len(self.qualified_locators) != len(set(self.qualified_locators)):
            raise ValueError("technical correction qualified locators must be unique")
        if any(not isinstance(item, QualifiedSourceLocator) for item in self.qualified_locators):
            raise ValueError("technical correction locators must be occurrence-qualified")
        _require_text(self.rule_version, "technical correction rule version")
        if self.rule_version != M15_TECHNICAL_CORRECTION_RULE_VERSION:
            raise ValueError("technical correction rule version is unsupported")
        if tuple(item.atom_id for item in self.qualified_locators) != self.ordered_atom_ids:
            raise ValueError("qualified locator order must equal the correction atom tuple")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_TECHNICAL_CORRECTION_SCHEMA,
            "rule_version": self.rule_version,
            "authority": self.authority.to_dict(),
            "reason": self.reason,
            "qualified_locators": [item.to_dict() for item in self.qualified_locators],
            "ordered_atom_ids": list(self.ordered_atom_ids),
        }

    @property
    def normalized_hash(self) -> str:
        return canonical_hash(self.identity_dict())

    @property
    def correction_id(self) -> str:
        return stable_m15_id("technical_correction", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "correction_id": self.correction_id,
            "normalized_hash": self.normalized_hash,
            **self.identity_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> LeadingTechnicalCoverageCorrection:
        if not isinstance(value, dict):
            raise ValueError("technical correction must be an object")
        required = {
            "correction_id",
            "normalized_hash",
            "schema",
            "rule_version",
            "authority",
            "reason",
            "qualified_locators",
            "ordered_atom_ids",
        }
        if set(value) != required:
            raise ValueError("technical correction has unknown or missing fields")
        if value["schema"] != M15_TECHNICAL_CORRECTION_SCHEMA:
            raise ValueError("technical correction schema is unsupported")
        authority_value = value["authority"]
        if not isinstance(authority_value, dict) or set(authority_value) != {
            "source_generation",
            "canonical_schema",
            "canonical_hash",
            "atom_schema",
            "atom_hash",
        }:
            raise ValueError("technical correction authority is malformed")
        if not all(isinstance(authority_value[item], str) for item in authority_value):
            raise ValueError("technical correction authority is malformed")
        if not isinstance(value["reason"], str) or not isinstance(value["rule_version"], str):
            raise ValueError("technical correction text fields are malformed")
        if not isinstance(value["correction_id"], str) or not isinstance(
            value["normalized_hash"], str
        ):
            raise ValueError("technical correction identity is malformed")
        locator_values = value["qualified_locators"]
        atom_values = value["ordered_atom_ids"]
        if not isinstance(locator_values, list) or not isinstance(atom_values, list):
            raise ValueError("technical correction references must be arrays")
        locators: list[QualifiedSourceLocator] = []
        for item in locator_values:
            if not isinstance(item, dict) or set(item) != {
                "atom_id",
                "primary_node_id",
                "evidence_ids",
                "source",
            }:
                raise ValueError("technical correction locator is malformed")
            source = item["source"]
            evidence_ids = item["evidence_ids"]
            if (
                not isinstance(item["atom_id"], str)
                or not isinstance(item["primary_node_id"], str)
                or not isinstance(evidence_ids, list)
                or not all(isinstance(value, str) for value in evidence_ids)
                or not isinstance(source, dict)
                or set(source) != {"relative_path", "start_line", "end_line", "line_basis"}
                or not isinstance(source["relative_path"], str)
                or not isinstance(source["line_basis"], str)
                or isinstance(source["start_line"], bool)
                or not isinstance(source["start_line"], int)
                or isinstance(source["end_line"], bool)
                or not isinstance(source["end_line"], int)
            ):
                raise ValueError("technical correction locator is malformed")
            try:
                locators.append(
                    QualifiedSourceLocator(
                        atom_id=item["atom_id"],
                        primary_node_id=item["primary_node_id"],
                        evidence_ids=tuple(evidence_ids),
                        source=SourceLocator(
                            relative_path=source["relative_path"],
                            start_line=source["start_line"],
                            end_line=source["end_line"],
                            line_basis=source["line_basis"],
                        ),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("technical correction locator is malformed") from exc
        if not all(isinstance(item, str) for item in atom_values):
            raise ValueError("technical correction atom IDs must be strings")
        correction = cls(
            authority=AuthorityBinding(
                source_generation=authority_value["source_generation"],
                canonical_schema=authority_value["canonical_schema"],
                canonical_hash=authority_value["canonical_hash"],
                atom_schema=authority_value["atom_schema"],
                atom_hash=authority_value["atom_hash"],
            ),
            reason=value["reason"],
            qualified_locators=tuple(locators),
            ordered_atom_ids=tuple(atom_values),
            rule_version=value["rule_version"],
        )
        if value["normalized_hash"] != correction.normalized_hash:
            raise ValueError("technical correction normalized hash does not match")
        if value["correction_id"] != correction.correction_id:
            raise ValueError("technical correction ID does not match")
        return correction


@dataclass(frozen=True)
class Provenance:
    atom_ids: tuple[str, ...] = ()
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    locators: tuple[SourceLocator, ...] = ()

    def __post_init__(self) -> None:
        for values, label in (
            (self.atom_ids, "atom ID"),
            (self.node_ids, "node ID"),
            (self.edge_ids, "edge ID"),
            (self.fact_ids, "fact ID"),
            (self.evidence_ids, "evidence ID"),
        ):
            _require_unique(values, label)
        if len(self.locators) > MAX_REFERENCES or len(self.locators) != len(set(self.locators)):
            raise ValueError("source locators must be unique and bounded")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "atom_ids": list(self.atom_ids),
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "fact_ids": list(self.fact_ids),
            "evidence_ids": list(self.evidence_ids),
            "locators": [item.to_dict() for item in self.locators],
        }


@dataclass(frozen=True)
class NarrativeCorridor:
    authority: AuthorityBinding
    lane_id: str
    chapter_id: str | None
    call_occurrence_id: str | None
    loop_id: str | None
    temporary_container_id: str | None
    temporary_arm_id: str | None
    ordered_atom_ids: tuple[str, ...]
    entry_node_id: str
    exit_node_id: str
    incident_edge_ids: tuple[str, ...]
    choice_ids: tuple[str, ...] = ()
    rejoin_node_ids: tuple[str, ...] = ()
    hard_boundary_before: bool = False
    hard_boundary_after: bool = False
    soft_boundary_signals: tuple[BoundarySignal, ...] = ()
    technical_atom_ids: tuple[str, ...] = ()
    technical_correction_id: str | None = None
    provenance: Provenance = Provenance()
    rule_version: str = M15_CORRIDOR_RULE_VERSION

    def __post_init__(self) -> None:
        _require_text(self.lane_id, "corridor lane ID")
        for value, label in (
            (self.chapter_id, "corridor chapter ID"),
            (self.call_occurrence_id, "corridor call occurrence ID"),
            (self.loop_id, "corridor loop ID"),
            (self.temporary_container_id, "temporary container ID"),
            (self.temporary_arm_id, "temporary arm ID"),
        ):
            _require_optional_text(value, label)
        _require_unique(self.ordered_atom_ids, "corridor atom ID", allow_empty=False)
        _require_text(self.entry_node_id, "corridor entry node ID")
        _require_text(self.exit_node_id, "corridor exit node ID")
        _require_unique(self.incident_edge_ids, "corridor incident edge ID")
        _require_unique(self.choice_ids, "corridor choice ID")
        _require_unique(self.rejoin_node_ids, "corridor rejoin node ID")
        _require_unique(self.technical_atom_ids, "technical atom ID")
        _require_optional_text(self.technical_correction_id, "technical correction ID")
        if not set(self.technical_atom_ids).issubset(self.ordered_atom_ids):
            raise ValueError("technical coverage must belong to the corridor's ordered atoms")
        if len(self.soft_boundary_signals) != len(set(self.soft_boundary_signals)):
            raise ValueError("soft boundary signals must be unique")
        _require_text(self.rule_version, "corridor rule version")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_CORRIDOR_SCHEMA,
            "rule_version": self.rule_version,
            "authority": self.authority.to_dict(),
            "lane_id": self.lane_id,
            "chapter_id": self.chapter_id,
            "call_occurrence_id": self.call_occurrence_id,
            "loop_id": self.loop_id,
            "temporary_container_id": self.temporary_container_id,
            "temporary_arm_id": self.temporary_arm_id,
            "ordered_atom_ids": list(self.ordered_atom_ids),
            "entry_node_id": self.entry_node_id,
            "exit_node_id": self.exit_node_id,
            "incident_edge_ids": list(self.incident_edge_ids),
            "choice_ids": list(self.choice_ids),
            "rejoin_node_ids": list(self.rejoin_node_ids),
            "hard_boundary_before": self.hard_boundary_before,
            "hard_boundary_after": self.hard_boundary_after,
            "soft_boundary_signals": [item.value for item in self.soft_boundary_signals],
            "technical_atom_ids": list(self.technical_atom_ids),
            "technical_correction_id": self.technical_correction_id,
            "provenance": self.provenance.to_dict(),
        }

    @property
    def corridor_id(self) -> str:
        return stable_m15_id("corridor", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {"corridor_id": self.corridor_id, **self.identity_dict()}


@dataclass(frozen=True)
class BoundaryCandidate:
    authority: AuthorityBinding
    left_corridor_id: str
    right_corridor_id: str
    signals: tuple[BoundarySignal, ...]
    evidence_ids: tuple[str, ...] = ()
    technical_correction_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.left_corridor_id, "left corridor ID")
        _require_text(self.right_corridor_id, "right corridor ID")
        if self.left_corridor_id == self.right_corridor_id:
            raise ValueError("a boundary candidate requires two different adjacent corridors")
        if not self.signals or len(self.signals) != len(set(self.signals)):
            raise ValueError("soft boundary candidates require unique signals")
        _require_unique(self.evidence_ids, "boundary evidence ID")
        _require_optional_text(self.technical_correction_id, "technical correction ID")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_BOUNDARY_SCHEMA,
            "authority": self.authority.to_dict(),
            "left_corridor_id": self.left_corridor_id,
            "right_corridor_id": self.right_corridor_id,
            "signals": [item.value for item in self.signals],
            "evidence_ids": list(self.evidence_ids),
            "technical_correction_id": self.technical_correction_id,
        }

    @property
    def candidate_id(self) -> str:
        return stable_m15_id("boundary", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {"candidate_id": self.candidate_id, **self.identity_dict()}


@dataclass(frozen=True)
class BoundaryProviderIdentity:
    provider: str
    adapter_version: str
    requested_model: str
    resolved_model: str
    settings_hash: str
    prompt_version: str
    response_schema: str
    input_hash: str

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "adapter_version",
            "requested_model",
            "resolved_model",
            "settings_hash",
            "prompt_version",
            "response_schema",
            "input_hash",
        ):
            _require_text(str(getattr(self, name)), name)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "provider": self.provider,
            "adapter_version": self.adapter_version,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "settings_hash": self.settings_hash,
            "prompt_version": self.prompt_version,
            "response_schema": self.response_schema,
            "input_hash": self.input_hash,
        }


@dataclass(frozen=True)
class BoundaryDecision:
    candidate: BoundaryCandidate
    decision: BoundaryDecisionKind
    reason: str
    confidence: float
    provider_identity: BoundaryProviderIdentity | None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.reason, "boundary decision reason", maximum=MAX_REASON_LENGTH)
        if isinstance(self.confidence, bool) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("boundary decision confidence must be between zero and one")
        for warning in self.warnings:
            _require_text(warning, "boundary warning", maximum=MAX_REASON_LENGTH)
        if len(self.warnings) != len(set(self.warnings)):
            raise ValueError("boundary warnings must be unique")
        if self.provider_identity is None and self.decision is not BoundaryDecisionKind.UNCERTAIN:
            raise ValueError("provider-free fallback decisions must remain uncertain")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_BOUNDARY_SCHEMA,
            "candidate_id": self.candidate.candidate_id,
            "left_corridor_id": self.candidate.left_corridor_id,
            "right_corridor_id": self.candidate.right_corridor_id,
            "decision": self.decision.value,
            "reason": self.reason,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "provider_identity": (
                self.provider_identity.to_dict() if self.provider_identity is not None else None
            ),
        }


@dataclass(frozen=True)
class NarrativeEvent:
    authority: AuthorityBinding
    ordered_corridor_ids: tuple[str, ...]
    ordered_atom_ids: tuple[str, ...]
    chapter_id: str | None
    lane_id: str
    call_occurrence_id: str | None
    temporary_container_id: str | None
    temporary_arm_id: str | None
    loop_id: str | None
    entry_node_id: str
    exit_node_id: str
    nested_choice_ids: tuple[str, ...]
    rejoin_node_ids: tuple[str, ...]
    deterministic_title: str
    coverage_state: CoverageState
    provenance: Provenance
    technical_correction_id: str | None = None
    ai_title: str | None = None
    ai_summary: str | None = None
    ai_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_unique(self.ordered_corridor_ids, "event corridor ID", allow_empty=False)
        _require_unique(self.ordered_atom_ids, "event atom ID", allow_empty=False)
        _require_text(self.lane_id, "event lane ID")
        for value, label in (
            (self.chapter_id, "event chapter ID"),
            (self.call_occurrence_id, "event call occurrence ID"),
            (self.temporary_container_id, "event temporary container ID"),
            (self.temporary_arm_id, "event temporary arm ID"),
            (self.loop_id, "event loop ID"),
        ):
            _require_optional_text(value, label)
        _require_text(self.entry_node_id, "event entry node ID")
        _require_text(self.exit_node_id, "event exit node ID")
        _require_unique(self.nested_choice_ids, "event choice ID")
        _require_unique(self.rejoin_node_ids, "event rejoin node ID")
        _require_text(
            self.deterministic_title,
            "deterministic event title",
            maximum=MAX_TITLE_LENGTH,
        )
        if self.ai_title is not None:
            _require_text(self.ai_title, "AI event title", maximum=MAX_TITLE_LENGTH)
        if self.ai_summary is not None:
            _require_text(self.ai_summary, "AI event summary", maximum=MAX_SUMMARY_LENGTH)
        _require_unique(self.ai_claim_ids, "AI claim ID")
        _require_optional_text(self.technical_correction_id, "technical correction ID")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_EVENT_SCHEMA,
            "authority": self.authority.to_dict(),
            "ordered_corridor_ids": list(self.ordered_corridor_ids),
            "ordered_atom_ids": list(self.ordered_atom_ids),
            "chapter_id": self.chapter_id,
            "lane_id": self.lane_id,
            "call_occurrence_id": self.call_occurrence_id,
            "temporary_container_id": self.temporary_container_id,
            "temporary_arm_id": self.temporary_arm_id,
            "loop_id": self.loop_id,
            "entry_node_id": self.entry_node_id,
            "exit_node_id": self.exit_node_id,
            "nested_choice_ids": list(self.nested_choice_ids),
            "rejoin_node_ids": list(self.rejoin_node_ids),
            "coverage_state": self.coverage_state.value,
            "provenance": self.provenance.to_dict(),
            "technical_correction_id": self.technical_correction_id,
        }

    @property
    def event_id(self) -> str:
        return stable_m15_id("event", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "event_id": self.event_id,
            **self.identity_dict(),
            "deterministic_title": self.deterministic_title,
            "ai_title": self.ai_title,
            "ai_summary": self.ai_summary,
            "ai_claim_ids": list(self.ai_claim_ids),
        }


@dataclass(frozen=True)
class EvidenceNavigation:
    target_kind: str
    target_id: str
    mode: str = "detail_evidence"

    def __post_init__(self) -> None:
        _require_text(self.target_kind, "evidence target kind")
        _require_text(self.target_id, "evidence target ID")
        if self.mode != "detail_evidence":
            raise ValueError("Narrative Map navigation must use Detail/Evidence")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"mode": self.mode, "target_kind": self.target_kind, "target_id": self.target_id}


@dataclass(frozen=True)
class NarrativeMapNode:
    node_id: str
    kind: NarrativeNodeKind
    title: str
    ordinal: int
    navigation: EvidenceNavigation
    event_id: str | None = None
    parent_node_id: str | None = None
    choice_id: str | None = None
    arm_id: str | None = None
    rejoin_node_id: str | None = None
    technical_count: int = 0

    def __post_init__(self) -> None:
        _require_text(self.node_id, "Narrative Map node ID")
        _require_text(self.title, "Narrative Map node title", maximum=MAX_TITLE_LENGTH)
        if self.ordinal < 0 or self.technical_count < 0:
            raise ValueError("Narrative Map ordinals and coverage counts cannot be negative")
        for value, label in (
            (self.event_id, "event ID"),
            (self.parent_node_id, "parent node ID"),
            (self.choice_id, "choice ID"),
            (self.arm_id, "arm ID"),
            (self.rejoin_node_id, "rejoin node ID"),
        ):
            _require_optional_text(value, label)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "title": self.title,
            "ordinal": self.ordinal,
            "navigation": self.navigation.to_dict(),
            "event_id": self.event_id,
            "parent_node_id": self.parent_node_id,
            "choice_id": self.choice_id,
            "arm_id": self.arm_id,
            "rejoin_node_id": self.rejoin_node_id,
            "technical_count": self.technical_count,
        }


@dataclass(frozen=True)
class NarrativeMapEdge:
    source_node_id: str
    target_node_id: str
    kind: NarrativeEdgeKind
    authority_edge_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...] = ()
    effect_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.source_node_id, "map edge source node ID")
        _require_text(self.target_node_id, "map edge target node ID")
        if self.source_node_id == self.target_node_id and self.kind is not NarrativeEdgeKind.LOOP:
            raise ValueError("only loop edges may connect a Narrative Map node to itself")
        _require_unique(self.authority_edge_ids, "authoritative edge ID", allow_empty=False)
        _require_unique(self.requirement_ids, "requirement ID")
        _require_unique(self.effect_ids, "effect ID")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "kind": self.kind.value,
            "authority_edge_ids": list(self.authority_edge_ids),
            "requirement_ids": list(self.requirement_ids),
            "effect_ids": list(self.effect_ids),
        }

    @property
    def edge_id(self) -> str:
        return stable_m15_id("map_edge", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {"edge_id": self.edge_id, **self.identity_dict()}


@dataclass(frozen=True)
class NarrativeMap:
    authority: AuthorityBinding
    event_ids: tuple[str, ...]
    nodes: tuple[NarrativeMapNode, ...]
    edges: tuple[NarrativeMapEdge, ...]
    initial_node_ids: tuple[str, ...]
    hidden_technical_atom_ids: tuple[str, ...] = ()
    technical_correction_id: str | None = None

    def __post_init__(self) -> None:
        _require_unique(self.event_ids, "Narrative Map event ID", allow_empty=False)
        _require_unique(self.initial_node_ids, "initial Narrative Map node ID", allow_empty=False)
        _require_unique(self.hidden_technical_atom_ids, "hidden technical atom ID")
        _require_optional_text(self.technical_correction_id, "technical correction ID")
        node_ids = tuple(item.node_id for item in self.nodes)
        edge_ids = tuple(item.edge_id for item in self.edges)
        _require_unique(node_ids, "Narrative Map node ID", allow_empty=False)
        _require_unique(edge_ids, "Narrative Map edge ID")
        node_set = set(node_ids)
        if not set(self.initial_node_ids).issubset(node_set):
            raise ValueError("initial Narrative Map nodes must exist in the map")
        if any(
            edge.source_node_id not in node_set or edge.target_node_id not in node_set
            for edge in self.edges
        ):
            raise ValueError("Narrative Map edges must connect known map nodes")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_MAP_SCHEMA,
            "authority": self.authority.to_dict(),
            "event_ids": list(self.event_ids),
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "initial_node_ids": list(self.initial_node_ids),
            "hidden_technical_atom_ids": list(self.hidden_technical_atom_ids),
            "technical_correction_id": self.technical_correction_id,
        }

    @property
    def normalized_hash(self) -> str:
        return canonical_hash(self.to_dict())

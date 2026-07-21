"""Frozen M15.1 contracts shared by deterministic, workflow, and browser tracks.

These records describe semantic inputs and outputs. They intentionally contain no provider,
persistence, assembly, or presentation implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.narrative_map.contracts import (
    MAX_REASON_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
    AuthorityBinding,
    EvidenceNavigation,
    JsonValue,
    Provenance,
    SourceLocator,
    _require_optional_text,
    _require_text,
    _require_unique,
    stable_m15_id,
)

M15_FINE_UNIT_SCHEMA = "m15-fine-narrative-unit-v2"
M15_GAP_CANDIDATE_SCHEMA = "m15-narrative-gap-candidate-v2"
M15_BOUNDARY_WINDOW_SCHEMA = "m15-boundary-window-v2"
M15_SEMANTIC_DECISION_SCHEMA = "m15-semantic-boundary-decision-v2"
M15_CHOICE_COMPOSITION_SCHEMA = "m15-choice-composition-v2"
M15_SEMANTIC_OUTLINE_SCHEMA = "m15-semantic-outline-v2"
M15_SEMANTIC_SUMMARY_SCHEMA = "m15-semantic-summary-v2"
M15_SEMANTIC_BUILD_SCHEMA = "m15-semantic-build-v2"


class SemanticBoundaryKind(StrEnum):
    SAME_BEAT = "same_beat"
    NEW_BEAT_SAME_CLUSTER = "new_beat_same_cluster"
    NEW_MAJOR_CLUSTER = "new_major_cluster"
    UNCERTAIN = "uncertain"


class SemanticClaimClass(StrEnum):
    FACTUAL = "factual"
    INTERPRETIVE = "interpretive"


class SemanticBuildState(StrEnum):
    NOT_STARTED = "not_started"
    BOUNDARIES_PREPARED = "boundaries_prepared"
    AWAITING_BOUNDARY_CONSENT = "awaiting_boundary_consent"
    BOUNDARIES_RUNNING = "boundaries_running"
    MEMBERSHIP_FROZEN = "membership_frozen"
    SUMMARIES_PREPARED = "summaries_prepared"
    AWAITING_SUMMARY_CONSENT = "awaiting_summary_consent"
    SUMMARIES_RUNNING = "summaries_running"
    VALIDATING = "validating"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


@dataclass(frozen=True)
class FineNarrativeUnit:
    authority: AuthorityBinding
    sequence_id: str
    ordinal: int
    story_atom_id: str
    story_locator: SourceLocator
    technical_context_atom_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    speaker_ids: tuple[str, ...]
    context_ids: tuple[str, ...]
    lane_id: str
    call_occurrence_id: str | None
    loop_id: str | None
    parent_choice_id: str | None
    parent_arm_id: str | None
    entry_node_id: str
    exit_node_id: str
    incident_edge_ids: tuple[str, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        _require_text(self.sequence_id, "fine-unit sequence ID")
        if self.ordinal < 0:
            raise ValueError("fine-unit ordinal cannot be negative")
        _require_text(self.story_atom_id, "fine-unit story atom ID")
        _require_unique(self.technical_context_atom_ids, "technical context atom ID")
        if self.story_atom_id in self.technical_context_atom_ids:
            raise ValueError("the one story-facing atom cannot be technical context")
        for values, label in (
            (self.node_ids, "fine-unit node ID"),
            (self.evidence_ids, "fine-unit evidence ID"),
            (self.speaker_ids, "fine-unit speaker ID"),
            (self.context_ids, "fine-unit context ID"),
            (self.incident_edge_ids, "fine-unit incident edge ID"),
        ):
            _require_unique(values, label)
        _require_text(self.lane_id, "fine-unit lane ID")
        for value, label in (
            (self.call_occurrence_id, "fine-unit call occurrence ID"),
            (self.loop_id, "fine-unit loop ID"),
            (self.parent_choice_id, "fine-unit parent choice ID"),
            (self.parent_arm_id, "fine-unit parent arm ID"),
        ):
            _require_optional_text(value, label)
        if self.parent_arm_id is not None and self.parent_choice_id is None:
            raise ValueError("an arm-owned fine unit requires its parent choice")
        _require_text(self.entry_node_id, "fine-unit entry node ID")
        _require_text(self.exit_node_id, "fine-unit exit node ID")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_FINE_UNIT_SCHEMA,
            "authority": self.authority.to_dict(),
            "sequence_id": self.sequence_id,
            "ordinal": self.ordinal,
            "story_atom_id": self.story_atom_id,
            "story_locator": self.story_locator.to_dict(),
            "technical_context_atom_ids": list(self.technical_context_atom_ids),
            "node_ids": list(self.node_ids),
            "evidence_ids": list(self.evidence_ids),
            "speaker_ids": list(self.speaker_ids),
            "context_ids": list(self.context_ids),
            "lane_id": self.lane_id,
            "call_occurrence_id": self.call_occurrence_id,
            "loop_id": self.loop_id,
            "parent_choice_id": self.parent_choice_id,
            "parent_arm_id": self.parent_arm_id,
            "entry_node_id": self.entry_node_id,
            "exit_node_id": self.exit_node_id,
            "incident_edge_ids": list(self.incident_edge_ids),
            "provenance": self.provenance.to_dict(),
        }

    @property
    def unit_id(self) -> str:
        return stable_m15_id("fine_unit", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {"unit_id": self.unit_id, **self.identity_dict()}


@dataclass(frozen=True)
class NarrativeGapCandidate:
    authority: AuthorityBinding
    sequence_id: str
    ordinal: int
    left_unit_id: str
    right_unit_id: str
    lane_id: str
    call_occurrence_id: str | None
    loop_id: str | None
    parent_choice_id: str | None
    parent_arm_id: str | None
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.sequence_id, "gap sequence ID")
        if self.ordinal < 0:
            raise ValueError("gap ordinal cannot be negative")
        _require_text(self.left_unit_id, "left fine-unit ID")
        _require_text(self.right_unit_id, "right fine-unit ID")
        if self.left_unit_id == self.right_unit_id:
            raise ValueError("a gap requires two distinct adjacent units")
        _require_text(self.lane_id, "gap lane ID")
        for value, label in (
            (self.call_occurrence_id, "gap call occurrence ID"),
            (self.loop_id, "gap loop ID"),
            (self.parent_choice_id, "gap parent choice ID"),
            (self.parent_arm_id, "gap parent arm ID"),
        ):
            _require_optional_text(value, label)
        if self.parent_arm_id is not None and self.parent_choice_id is None:
            raise ValueError("an arm-owned gap requires its parent choice")
        _require_unique(self.evidence_ids, "gap evidence ID")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_GAP_CANDIDATE_SCHEMA,
            "authority": self.authority.to_dict(),
            "sequence_id": self.sequence_id,
            "ordinal": self.ordinal,
            "left_unit_id": self.left_unit_id,
            "right_unit_id": self.right_unit_id,
            "lane_id": self.lane_id,
            "call_occurrence_id": self.call_occurrence_id,
            "loop_id": self.loop_id,
            "parent_choice_id": self.parent_choice_id,
            "parent_arm_id": self.parent_arm_id,
            "evidence_ids": list(self.evidence_ids),
        }

    @property
    def candidate_id(self) -> str:
        return stable_m15_id("semantic_gap", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {"candidate_id": self.candidate_id, **self.identity_dict()}


@dataclass(frozen=True)
class BoundaryWindow:
    authority: AuthorityBinding
    ordinal: int
    owned_candidate_ids: tuple[str, ...]
    context_unit_ids: tuple[str, ...]
    maximum_context_units: int

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("boundary-window ordinal cannot be negative")
        _require_unique(self.owned_candidate_ids, "owned gap ID", allow_empty=False)
        _require_unique(self.context_unit_ids, "boundary context unit ID")
        if (
            self.maximum_context_units < 0
            or len(self.context_unit_ids) > self.maximum_context_units
        ):
            raise ValueError("boundary context exceeds its frozen bound")

    def identity_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_BOUNDARY_WINDOW_SCHEMA,
            "authority": self.authority.to_dict(),
            "ordinal": self.ordinal,
            "owned_candidate_ids": list(self.owned_candidate_ids),
            "context_unit_ids": list(self.context_unit_ids),
            "maximum_context_units": self.maximum_context_units,
        }

    @property
    def window_id(self) -> str:
        return stable_m15_id("boundary_window", self.identity_dict())

    def to_dict(self) -> dict[str, JsonValue]:
        return {"window_id": self.window_id, **self.identity_dict()}


@dataclass(frozen=True)
class SemanticBoundaryDecision:
    candidate_id: str
    decision: SemanticBoundaryKind
    reason: str
    confidence: float
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.candidate_id, "semantic boundary candidate ID")
        _require_text(self.reason, "semantic boundary reason", maximum=MAX_REASON_LENGTH)
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("semantic boundary confidence must be between zero and one")
        _require_unique(self.warnings, "semantic boundary warning")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_SEMANTIC_DECISION_SCHEMA,
            "candidate_id": self.candidate_id,
            "decision": self.decision.value,
            "reason": self.reason,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ChoiceComposition:
    choice_id: str
    parent_cluster_id: str
    parent_choice_id: str | None
    parent_arm_id: str | None
    ordered_arm_ids: tuple[str, ...]
    ordered_arm_captions: tuple[str, ...]
    child_choice_ids: tuple[str, ...]
    rejoin_relationship_ids: tuple[str, ...]
    shared_target_id: str | None
    post_rejoin_continuation_id: str | None

    def __post_init__(self) -> None:
        _require_text(self.choice_id, "choice-composition ID")
        _require_text(self.parent_cluster_id, "choice parent cluster ID")
        _require_optional_text(self.parent_choice_id, "choice parent choice ID")
        _require_optional_text(self.parent_arm_id, "choice parent arm ID")
        if (self.parent_choice_id is None) != (self.parent_arm_id is None):
            raise ValueError("nested choice ownership requires both parent choice and arm")
        _require_unique(self.ordered_arm_ids, "choice arm ID", allow_empty=False)
        if len(self.ordered_arm_ids) != len(self.ordered_arm_captions):
            raise ValueError("choice arm IDs and captions must have equal length")
        for caption in self.ordered_arm_captions:
            _require_text(caption, "choice arm caption", maximum=MAX_SUMMARY_LENGTH)
        _require_unique(self.child_choice_ids, "child choice ID")
        _require_unique(self.rejoin_relationship_ids, "rejoin relationship ID", allow_empty=False)
        _require_optional_text(self.shared_target_id, "shared rejoin target ID")
        _require_optional_text(self.post_rejoin_continuation_id, "post-rejoin continuation ID")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": M15_CHOICE_COMPOSITION_SCHEMA,
            "choice_id": self.choice_id,
            "parent_cluster_id": self.parent_cluster_id,
            "parent_choice_id": self.parent_choice_id,
            "parent_arm_id": self.parent_arm_id,
            "ordered_arm_ids": list(self.ordered_arm_ids),
            "ordered_arm_captions": list(self.ordered_arm_captions),
            "child_choice_ids": list(self.child_choice_ids),
            "rejoin_relationship_ids": list(self.rejoin_relationship_ids),
            "shared_target_id": self.shared_target_id,
            "post_rejoin_continuation_id": self.post_rejoin_continuation_id,
        }


@dataclass(frozen=True)
class SemanticBeat:
    beat_id: str
    parent_cluster_id: str
    ordered_unit_ids: tuple[str, ...]
    parent_choice_id: str | None
    parent_arm_id: str | None
    navigation: EvidenceNavigation

    def __post_init__(self) -> None:
        _require_text(self.beat_id, "semantic beat ID")
        _require_text(self.parent_cluster_id, "semantic beat parent cluster ID")
        _require_unique(self.ordered_unit_ids, "semantic beat unit ID", allow_empty=False)
        _require_optional_text(self.parent_choice_id, "semantic beat parent choice ID")
        _require_optional_text(self.parent_arm_id, "semantic beat parent arm ID")
        if (self.parent_choice_id is None) != (self.parent_arm_id is None):
            raise ValueError("arm-local beat ownership requires both choice and arm")


@dataclass(frozen=True)
class MajorCluster:
    cluster_id: str
    ordinal: int
    ordered_beat_ids: tuple[str, ...]
    ordered_choice_ids: tuple[str, ...]
    navigation: EvidenceNavigation

    def __post_init__(self) -> None:
        _require_text(self.cluster_id, "major cluster ID")
        if self.ordinal < 0:
            raise ValueError("major-cluster ordinal cannot be negative")
        _require_unique(self.ordered_beat_ids, "major-cluster beat ID", allow_empty=False)
        _require_unique(self.ordered_choice_ids, "major-cluster choice ID")


@dataclass(frozen=True)
class SemanticSummaryClaim:
    claim_class: SemanticClaimClass
    text: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.text, "semantic claim", maximum=MAX_SUMMARY_LENGTH)
        _require_unique(self.evidence_ids, "semantic claim evidence ID", allow_empty=False)


@dataclass(frozen=True)
class SemanticSummary:
    subject_kind: str
    subject_id: str
    membership_hash: str
    title: str
    summary: str
    characters: tuple[str, ...]
    claims: tuple[SemanticSummaryClaim, ...]
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.subject_kind not in {"beat", "major_cluster", "choice"}:
            raise ValueError("summary subject kind is unsupported")
        _require_text(self.subject_id, "summary subject ID")
        _require_text(self.membership_hash, "summary membership hash")
        _require_text(self.title, "semantic title", maximum=MAX_TITLE_LENGTH)
        _require_text(self.summary, "semantic summary", maximum=MAX_SUMMARY_LENGTH)
        _require_unique(self.characters, "semantic summary character")
        if not self.claims:
            raise ValueError("a semantic summary requires evidence-linked claims")
        _require_unique(self.warnings, "semantic summary warning")


@dataclass(frozen=True)
class LiveSemanticProvenance:
    stage: str
    job_id: str
    input_hash: str
    manifest_id: str
    provider_identity_hash: str
    cache_identity: str

    def __post_init__(self) -> None:
        if self.stage not in {"boundaries", "summaries"}:
            raise ValueError("semantic provenance stage is unsupported")
        for value, label in (
            (self.job_id, "semantic job ID"),
            (self.input_hash, "semantic input hash"),
            (self.manifest_id, "semantic manifest ID"),
            (self.provider_identity_hash, "semantic provider identity hash"),
            (self.cache_identity, "semantic cache identity"),
        ):
            _require_text(value, label)


@dataclass(frozen=True)
class SemanticOutline:
    authority: AuthorityBinding
    ordered_unit_ids: tuple[str, ...]
    ordered_candidate_ids: tuple[str, ...]
    beats: tuple[SemanticBeat, ...]
    clusters: tuple[MajorCluster, ...]
    choices: tuple[ChoiceComposition, ...]
    boundary_provenance: tuple[LiveSemanticProvenance, ...]

    def __post_init__(self) -> None:
        _require_unique(self.ordered_unit_ids, "outline unit ID", allow_empty=False)
        _require_unique(self.ordered_candidate_ids, "outline candidate ID")
        _require_unique(
            tuple(item.beat_id for item in self.beats),
            "outline beat ID",
            allow_empty=False,
        )
        _require_unique(
            tuple(item.cluster_id for item in self.clusters),
            "outline cluster ID",
            allow_empty=False,
        )
        _require_unique(tuple(item.choice_id for item in self.choices), "outline choice ID")


@dataclass(frozen=True)
class SemanticBuildRecord:
    authority: AuthorityBinding
    state: SemanticBuildState
    boundary_manifest_id: str | None
    membership_hash: str | None
    summary_manifest_id: str | None
    published_map_hash: str | None
    completed_boundary_job_ids: tuple[str, ...]
    completed_summary_job_ids: tuple[str, ...]
    failure_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.boundary_manifest_id, "boundary manifest ID"),
            (self.membership_hash, "membership hash"),
            (self.summary_manifest_id, "summary manifest ID"),
            (self.published_map_hash, "published map hash"),
        ):
            _require_optional_text(value, label)
        _require_unique(self.completed_boundary_job_ids, "completed boundary job ID")
        _require_unique(self.completed_summary_job_ids, "completed summary job ID")
        _require_unique(self.failure_codes, "semantic failure code")
        if self.state is SemanticBuildState.COMPLETE and (
            self.membership_hash is None or self.published_map_hash is None
        ):
            raise ValueError("a complete semantic build requires frozen membership and a map hash")

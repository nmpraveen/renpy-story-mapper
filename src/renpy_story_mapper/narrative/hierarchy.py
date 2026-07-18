"""Provider-free planning contracts for the bounded M13 narrative hierarchy.

The planner is deliberately staged: it plans a higher job only from accepted child
artifacts.  This keeps logical identities bound to real artifact IDs and lets every
ancestor expose only immediate child-claim IDs.  No transitive M10 evidence is copied
into these descriptors.

Scene artifacts must first pass through :mod:`renpy_story_mapper.narrative.segments`.
Chapter jobs therefore consume summary-segment artifacts, shared-story and persistent
route jobs consume chapter artifacts, ending jobs consume a route plus bounded ending
artifacts, and the plot consumes only bounded chapter/route/ending/segment artifacts.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.m12_model import RouteBadge, TechnicalStatus
from renpy_story_mapper.narrative.contracts import (
    AuthorityReference,
    AuthoritySystem,
    ClaimClass,
    ClaimPolarity,
    ClaimSemantics,
    ClaimSupport,
    LogicalJobKind,
    LogicalJobSpec,
    NarrativeClaim,
    StructuralContext,
    SupportKind,
    canonical_hash,
)

DEFAULT_HIERARCHY_PARTITION_VERSION = "m13-hierarchy-partition-v1"
HIERARCHY_REDUCTION_TARGET_CHILDREN = 24
MAX_MANDATORY_CLAIMS_PER_HIERARCHY_JOB = 256


def _require_identifier(value: str, *, name: str, maximum: int = 500) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty, trimmed string.")
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters.")


def _require_optional_identifier(value: str | None, *, name: str) -> None:
    if value is not None:
        _require_identifier(value, name=name)


def _require_unique(values: tuple[str, ...], *, name: str) -> None:
    for value in values:
        _require_identifier(value, name=name)
    if len(values) != len(set(values)):
        raise ValueError(f"{name} values must be unique.")


class StorySection(StrEnum):
    """Route-aware presentation section; never M11 membership."""

    COMMON = "common_shared_story"
    TEMPORARY_BRANCH = "temporary_branch"
    PERSISTENT_ROUTE = "persistent_route"
    ENDING = "ending"
    UNRESOLVED = "unresolved_or_missing_coverage"


class ChronologyPolicy(StrEnum):
    """How a provider and renderer must interpret ordered direct children."""

    LINEAR = "one_owned_chronology"
    STRUCTURED_ALTERNATIVES = "structured_alternatives_with_rejoins"
    ROUTE_AWARE = "shared_then_separate_routes_and_endings"


@dataclass(frozen=True)
class HierarchyPathContext:
    """Exact route/temporary/ending ownership of one artifact or planned job."""

    section: StorySection
    persistent_lane_id: str | None = None
    route_id: str | None = None
    temporary_container_id: str | None = None
    temporary_arm_id: str | None = None
    rejoin_anchor_id: str | None = None
    ending_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("persistent_lane_id", self.persistent_lane_id),
            ("route_id", self.route_id),
            ("temporary_container_id", self.temporary_container_id),
            ("temporary_arm_id", self.temporary_arm_id),
            ("rejoin_anchor_id", self.rejoin_anchor_id),
            ("ending_id", self.ending_id),
        ):
            _require_optional_identifier(value, name=name)

        temporary_values = (
            self.temporary_container_id,
            self.temporary_arm_id,
            self.rejoin_anchor_id,
        )
        if self.section is StorySection.TEMPORARY_BRANCH:
            if any(value is None for value in temporary_values):
                raise ValueError(
                    "Temporary branch context requires container, arm, and rejoin IDs."
                )
            if self.ending_id is not None:
                raise ValueError("Temporary branch context cannot also be an ending.")
        elif any(value is not None for value in temporary_values):
            raise ValueError("Only temporary branch context can carry temporary ownership.")

        if self.section is StorySection.PERSISTENT_ROUTE:
            if self.route_id is None or self.persistent_lane_id is None:
                raise ValueError("Persistent route context requires route and lane IDs.")
            if self.ending_id is not None:
                raise ValueError("Persistent route context cannot also be an ending.")
        elif self.section is StorySection.ENDING:
            if self.ending_id is None:
                raise ValueError("Ending context requires an ending ID.")
            if (self.route_id is None) != (self.persistent_lane_id is None):
                raise ValueError("Route-owned endings require both route and lane IDs.")
        elif self.ending_id is not None:
            raise ValueError("Only ending context can carry an ending ID.")

        if self.route_id is not None and self.persistent_lane_id is None:
            raise ValueError("A route context requires its persistent lane ID.")
        if self.section is StorySection.COMMON and self.route_id is not None:
            raise ValueError("Common story context cannot belong to a persistent route.")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "section": self.section.value,
            "persistent_lane_id": self.persistent_lane_id,
            "route_id": self.route_id,
            "temporary_container_id": self.temporary_container_id,
            "temporary_arm_id": self.temporary_arm_id,
            "rejoin_anchor_id": self.rejoin_anchor_id,
            "ending_id": self.ending_id,
        }

    @property
    def identity(self) -> str:
        return canonical_hash(self.to_dict())


_SECTION_ORDER = {
    StorySection.COMMON: 0,
    StorySection.TEMPORARY_BRANCH: 1,
    StorySection.PERSISTENT_ROUTE: 2,
    StorySection.ENDING: 3,
    StorySection.UNRESOLVED: 4,
}


@dataclass(frozen=True)
class HierarchyArtifactInput:
    """One expected child artifact with bounded input and immediate claim support."""

    artifact_id: str
    job_kind: LogicalJobKind
    claim_ids: tuple[str, ...]
    estimated_tokens: int
    path: HierarchyPathContext
    chronology_index: int
    temporal_anchor: str
    mandatory_claim_ids: tuple[str, ...] = ()
    chapter_id: str | None = None
    chapter_ordinal: int | None = None
    occurrence_id: str | None = None
    call_site_id: str | None = None
    loop_id: str | None = None
    available: bool = True
    expected_leaf_count: int = 1
    covered_leaf_count: int | None = None
    contains_structured_alternatives: bool = False
    structure_manifest_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.artifact_id, name="artifact_id")
        _require_unique(self.claim_ids, name="claim_id")
        _require_unique(self.mandatory_claim_ids, name="mandatory claim_id")
        if not set(self.mandatory_claim_ids) <= set(self.claim_ids):
            raise ValueError("Mandatory claims must be exposed immediate child claims.")
        _require_identifier(self.temporal_anchor, name="temporal_anchor")
        for name, value in (
            ("chapter_id", self.chapter_id),
            ("occurrence_id", self.occurrence_id),
            ("call_site_id", self.call_site_id),
            ("loop_id", self.loop_id),
            ("structure_manifest_id", self.structure_manifest_id),
        ):
            _require_optional_identifier(value, name=name)
        if self.estimated_tokens < 0:
            raise ValueError("estimated_tokens must be non-negative.")
        if self.chronology_index < 0:
            raise ValueError("chronology_index must be non-negative.")
        if (self.chapter_id is None) != (self.chapter_ordinal is None):
            raise ValueError("chapter_id and chapter_ordinal must be present together.")
        if self.chapter_ordinal is not None and self.chapter_ordinal < 0:
            raise ValueError("chapter_ordinal must be non-negative.")
        if self.call_site_id is not None and self.occurrence_id is None:
            raise ValueError("call_site_id requires occurrence_id.")
        if self.expected_leaf_count <= 0:
            raise ValueError("expected_leaf_count must be positive.")
        covered = self.covered_leaf_count
        if covered is None:
            covered = self.expected_leaf_count if self.available else 0
            object.__setattr__(self, "covered_leaf_count", covered)
        if not 0 <= covered <= self.expected_leaf_count:
            raise ValueError("covered_leaf_count must be within expected leaf coverage.")
        if not self.available and (self.claim_ids or covered != 0):
            raise ValueError("Unavailable children cannot expose claims or covered leaves.")

    def context_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "job_kind": self.job_kind.value,
            "path": self.path.to_dict(),
            "chapter_id": self.chapter_id,
            "chapter_ordinal": self.chapter_ordinal,
            "chronology_index": self.chronology_index,
            "temporal_anchor": self.temporal_anchor,
            "mandatory_claim_ids": list(self.mandatory_claim_ids),
            "occurrence_id": self.occurrence_id,
            "call_site_id": self.call_site_id,
            "loop_id": self.loop_id,
            "available": self.available,
            "contains_structured_alternatives": self.contains_structured_alternatives,
            "structure_manifest_id": self.structure_manifest_id,
        }

    @property
    def ordering_key(self) -> tuple[int, int, int, str, str, str, str, str, str]:
        chapter = self.chapter_ordinal if self.chapter_ordinal is not None else 1_000_000_000
        return (
            chapter,
            self.chronology_index,
            _SECTION_ORDER[self.path.section],
            self.path.route_id or "",
            self.path.persistent_lane_id or "",
            self.path.temporary_container_id or "",
            self.path.temporary_arm_id or "",
            self.path.ending_id or "",
            self.artifact_id,
        )


@dataclass(frozen=True)
class HierarchySectionEntry:
    """Direct child presentation metadata; transitive structure remains lazy."""

    artifact_id: str
    job_kind: LogicalJobKind
    path: HierarchyPathContext
    chapter_id: str | None
    chapter_ordinal: int | None
    chronology_index: int
    temporal_anchor: str
    available: bool
    contains_structured_alternatives: bool
    structure_manifest_id: str | None

    @classmethod
    def from_child(cls, child: HierarchyArtifactInput) -> HierarchySectionEntry:
        return cls(
            artifact_id=child.artifact_id,
            job_kind=child.job_kind,
            path=child.path,
            chapter_id=child.chapter_id,
            chapter_ordinal=child.chapter_ordinal,
            chronology_index=child.chronology_index,
            temporal_anchor=child.temporal_anchor,
            available=child.available,
            contains_structured_alternatives=child.contains_structured_alternatives,
            structure_manifest_id=child.structure_manifest_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "job_kind": self.job_kind.value,
            "path": self.path.to_dict(),
            "chapter_id": self.chapter_id,
            "chapter_ordinal": self.chapter_ordinal,
            "chronology_index": self.chronology_index,
            "temporal_anchor": self.temporal_anchor,
            "available": self.available,
            "contains_structured_alternatives": self.contains_structured_alternatives,
            "structure_manifest_id": self.structure_manifest_id,
        }


@dataclass(frozen=True)
class M12RouteAuthority:
    """Exact M12 language included in an authority leaf without reinterpretation."""

    result_identity: str
    route_id: str | None
    persistent_lane_id: str | None
    status: TechnicalStatus | None
    badge: RouteBadge | None
    prerequisite_texts: tuple[str, ...] = ()
    conclusion_texts: tuple[str, ...] = ()
    authority_kind: str = "result"
    completion: bool | None = None
    path_role: str | None = None
    path_ordinal: int | None = None
    persistent_lane_ids: tuple[str, ...] = ()
    persistent_commitment_texts: tuple[str, ...] = ()
    warning_texts: tuple[str, ...] = ()
    path_provenance: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.result_identity, name="M12 result identity")
        if (self.route_id is None) != (self.persistent_lane_id is None):
            raise ValueError(
                "M12 route and lane context must either both be present or both absent."
            )
        if self.route_id is not None:
            _require_identifier(self.route_id, name="route_id")
            assert self.persistent_lane_id is not None
            _require_identifier(self.persistent_lane_id, name="persistent_lane_id")
        if self.authority_kind not in {"result", "path"}:
            raise ValueError("M12 authority kind must be result or path.")
        if self.authority_kind == "result":
            if self.status is None or self.badge is None:
                raise ValueError("M12 result authority requires exact status and badge.")
            if self.path_role is not None or self.path_ordinal is not None:
                raise ValueError("M12 result authority cannot claim path role or ordinal.")
        else:
            if self.status is not None or self.badge is not None:
                raise ValueError("M12 path authority cannot inherit result status or badge.")
            if self.path_role not in {"recommended", "alternative"}:
                raise ValueError("M12 path authority requires an exact path role.")
            if self.path_ordinal is None or self.path_ordinal < 0:
                raise ValueError("M12 path authority requires a stable non-negative ordinal.")
            if self.route_id is None or self.persistent_lane_id is None:
                raise ValueError("M12 path authority requires exact route and lane ownership.")
            if self.persistent_lane_id not in self.persistent_lane_ids:
                raise ValueError("M12 path authority must retain its owning persistent lane.")
        _require_unique(self.prerequisite_texts, name="M12 prerequisite text")
        _require_unique(self.conclusion_texts, name="M12 conclusion text")
        _require_unique(self.persistent_lane_ids, name="M12 persistent lane ID")
        _require_unique(
            self.persistent_commitment_texts,
            name="M12 persistent commitment text",
        )
        _require_unique(self.warning_texts, name="M12 uncertainty warning")

    @property
    def authority_identity(self) -> str:
        return f"m12-authority-{canonical_hash(self.to_dict())}"

    def to_dict(self) -> dict[str, object]:
        return {
            "result_identity": self.result_identity,
            "route_id": self.route_id,
            "persistent_lane_id": self.persistent_lane_id,
            "authority_kind": self.authority_kind,
            "status": None if self.status is None else self.status.value,
            "badge": None if self.badge is None else self.badge.value,
            "completion": self.completion,
            "path_role": self.path_role,
            "path_ordinal": self.path_ordinal,
            "persistent_lane_ids": list(self.persistent_lane_ids),
            "prerequisite_texts": list(self.prerequisite_texts),
            "persistent_commitment_texts": list(self.persistent_commitment_texts),
            "warning_texts": list(self.warning_texts),
            "path_provenance": (
                None if self.path_provenance is None else dict(self.path_provenance)
            ),
            "conclusion_texts": list(self.conclusion_texts),
        }


@dataclass(frozen=True)
class M12AuthorityLeaf:
    """Deterministic leaf claims that bind exact M12 text to one route result."""

    authority: M12RouteAuthority
    job: LogicalJobSpec
    claims: tuple[NarrativeClaim, ...]

    def __post_init__(self) -> None:
        if self.job.kind is not LogicalJobKind.AUTHORITY_FACT:
            raise ValueError("M12 authority leaves require an authority-fact logical job.")
        if (
            self.job.context.route_id != self.authority.route_id
            or self.job.context.lane_id != self.authority.persistent_lane_id
        ):
            raise ValueError("M12 authority leaf route binding is inconsistent.")
        if any(
            claim.logical_job_id != self.job.job_id
            or claim.job_kind is not LogicalJobKind.AUTHORITY_FACT
            for claim in self.claims
        ):
            raise ValueError("M12 authority claims must be owned by the leaf job.")
        if any(
            reference.owner_id != self.job.owner_id
            for claim in self.claims
            for reference in claim.support.direct_evidence
        ):
            raise ValueError("M12 authority evidence must be owned by the leaf job.")

    @property
    def claim_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.claims)


def make_m12_authority_leaf(
    authority: M12RouteAuthority,
    *,
    locale: str,
    perspective: str,
) -> M12AuthorityLeaf:
    """Create exact status/badge/prerequisite/conclusion claims from M12 authority."""

    fingerprint = canonical_hash({"m12_route_authority": authority.to_dict()})
    job = LogicalJobSpec(
        kind=LogicalJobKind.AUTHORITY_FACT,
        owner_id=authority.authority_identity,
        context=StructuralContext(
            lane_id=authority.persistent_lane_id,
            route_id=authority.route_id,
            temporal_anchor=f"m12-route-result:{authority.result_identity}",
            structural_fingerprint=fingerprint,
        ),
        locale=locale,
        perspective=perspective,
        partition_version=DEFAULT_HIERARCHY_PARTITION_VERSION,
    )
    reference = AuthorityReference(
        authority=AuthoritySystem.M12,
        record_kind="route_result",
        record_id=authority.result_identity,
        owner_id=job.owner_id,
    )
    exact_record_values: list[tuple[str, str]] = []
    if authority.status is not None:
        exact_record_values.append(("status", authority.status.value))
    if authority.badge is not None:
        exact_record_values.append(("badge", authority.badge.value))
    if authority.completion is not None:
        exact_record_values.append(("completion", str(authority.completion).lower()))
    if authority.path_role is not None:
        exact_record_values.append(("path_role", authority.path_role))
    if authority.path_ordinal is not None:
        exact_record_values.append(("path_ordinal", str(authority.path_ordinal)))
    exact_record_values.extend(
        (f"persistent_lane:{ordinal}", text)
        for ordinal, text in enumerate(authority.persistent_lane_ids)
    )
    exact_record_values.extend(
        (f"prerequisite:{ordinal}", text)
        for ordinal, text in enumerate(authority.prerequisite_texts)
    )
    exact_record_values.extend(
        (f"persistent_commitment:{ordinal}", text)
        for ordinal, text in enumerate(authority.persistent_commitment_texts)
    )
    exact_record_values.extend(
        (f"uncertainty_warning:{ordinal}", text)
        for ordinal, text in enumerate(authority.warning_texts)
    )
    if authority.path_provenance is not None:
        exact_record_values.append(
            ("path_provenance", canonical_hash(dict(authority.path_provenance)))
        )
    exact_record_values.extend(
        (f"conclusion:{ordinal}", text)
        for ordinal, text in enumerate(authority.conclusion_texts)
    )
    exact_records = tuple(exact_record_values)
    route_scope = authority.route_id or "unassigned"
    subject = f"{authority.authority_identity}:route:{route_scope}"
    claims = tuple(
        NarrativeClaim(
            logical_job_id=job.job_id,
            job_kind=LogicalJobKind.AUTHORITY_FACT,
            ordinal=ordinal,
            claim_class=ClaimClass.FACTUAL,
            text=text,
            support=ClaimSupport(
                kind=SupportKind.DIRECT_EVIDENCE,
                direct_evidence=(reference,),
            ),
            semantics=ClaimSemantics(
                subject=subject,
                predicate=predicate,
                polarity=ClaimPolarity.NEUTRAL,
                normalized_value=text,
            ),
        )
        for ordinal, (predicate, text) in enumerate(exact_records)
    )
    return M12AuthorityLeaf(authority=authority, job=job, claims=claims)


@dataclass(frozen=True)
class HierarchyPartitionConfig:
    """Hard preflight bounds for every user-facing hierarchy job."""

    locale: str
    perspective: str
    partition_version: str = DEFAULT_HIERARCHY_PARTITION_VERSION
    maximum_children: int = 32
    maximum_input_tokens: int = 24_000
    prompt_overhead_tokens: int = 256

    def __post_init__(self) -> None:
        _require_identifier(self.locale, name="locale")
        _require_identifier(self.perspective, name="perspective")
        _require_identifier(self.partition_version, name="partition_version")
        if not 1 <= self.maximum_children <= 32:
            raise ValueError("maximum_children must be between 1 and 32.")
        if self.maximum_input_tokens <= 0:
            raise ValueError("maximum_input_tokens must be positive.")
        if not 0 <= self.prompt_overhead_tokens < self.maximum_input_tokens:
            raise ValueError("prompt_overhead_tokens must leave provider input capacity.")


@dataclass(frozen=True)
class HierarchyJobDescriptor:
    """A bounded logical job and its immediate claim-DAG support allowlist."""

    spec: LogicalJobSpec
    path: HierarchyPathContext
    chronology_policy: ChronologyPolicy
    section_entries: tuple[HierarchySectionEntry, ...]
    child_claim_ids: tuple[str, ...]
    mandatory_child_claim_ids: tuple[str, ...]
    authority_leaf_claim_ids: tuple[str, ...]
    m12_authority: tuple[M12RouteAuthority, ...]
    estimated_input_tokens: int
    expected_leaf_count: int
    covered_leaf_count: int
    chapter_ordinal: int | None = None
    chronology_index: int = 0

    def __post_init__(self) -> None:
        entry_ids = tuple(entry.artifact_id for entry in self.section_entries)
        if entry_ids != self.spec.ordered_child_artifact_ids:
            raise ValueError("Section entries must exactly match ordered child artifacts.")
        _require_unique(self.child_claim_ids, name="child claim ID")
        _require_unique(self.mandatory_child_claim_ids, name="mandatory child claim ID")
        if not set(self.mandatory_child_claim_ids) <= set(self.child_claim_ids):
            raise ValueError("Mandatory child claims must belong to immediate artifacts.")
        _require_unique(self.authority_leaf_claim_ids, name="authority leaf claim ID")
        if (
            len(self.mandatory_child_claim_ids) + len(self.authority_leaf_claim_ids)
            > MAX_MANDATORY_CLAIMS_PER_HIERARCHY_JOB
        ):
            raise ValueError(
                "One hierarchy job cannot propagate more than 256 exact M12 authority claims."
            )
        if set(self.child_claim_ids) & set(self.authority_leaf_claim_ids):
            raise ValueError("Artifact and authority claim allowlists cannot overlap.")
        if self.estimated_input_tokens <= 0:
            raise ValueError("estimated_input_tokens must be positive.")
        if self.expected_leaf_count <= 0:
            raise ValueError("expected_leaf_count must be positive.")
        if not 0 <= self.covered_leaf_count <= self.expected_leaf_count:
            raise ValueError("covered_leaf_count must be within expected leaf coverage.")
        if self.chapter_ordinal is not None and self.chapter_ordinal < 0:
            raise ValueError("chapter_ordinal must be non-negative.")
        if self.chronology_index < 0:
            raise ValueError("chronology_index must be non-negative.")
        identities = tuple(item.authority_identity for item in self.m12_authority)
        if len(identities) != len(set(identities)):
            raise ValueError("M12 authority records must be unique.")

    @property
    def job_id(self) -> str:
        return self.spec.job_id

    @property
    def child_artifact_ids(self) -> tuple[str, ...]:
        return self.spec.ordered_child_artifact_ids

    @property
    def available_child_artifact_ids(self) -> tuple[str, ...]:
        return tuple(entry.artifact_id for entry in self.section_entries if entry.available)

    @property
    def missing_child_artifact_ids(self) -> tuple[str, ...]:
        return tuple(entry.artifact_id for entry in self.section_entries if not entry.available)

    @property
    def allowed_support_claim_ids(self) -> tuple[str, ...]:
        return self.child_claim_ids + self.authority_leaf_claim_ids

    @property
    def provenance_edge_count(self) -> int:
        """Only direct claim-DAG edges, never flattened transitive evidence."""

        return len(self.allowed_support_claim_ids)

    @property
    def structure_manifest_id(self) -> str:
        """Opaque pointer to direct route/branch structure, not copied transitive detail."""

        material = {
            "job_id": self.job_id,
            "chronology_policy": self.chronology_policy.value,
            "section_entries": [entry.to_dict() for entry in self.section_entries],
        }
        return f"m13_structure_{canonical_hash(material)}"

    @property
    def coverage_percentage(self) -> float:
        return round(self.covered_leaf_count * 100 / self.expected_leaf_count, 6)

    @property
    def route_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    entry.path.route_id
                    for entry in self.section_entries
                    if entry.path.route_id is not None
                }
            )
        )

    @property
    def ending_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    entry.path.ending_id
                    for entry in self.section_entries
                    if entry.path.ending_id is not None
                }
            )
        )


@dataclass(frozen=True)
class HierarchyReductionRequirement:
    """Deterministic refusal to create an unsafe, unbounded hierarchy job."""

    intended_kind: LogicalJobKind
    owner_id: str
    path: HierarchyPathContext
    chronology_policy: ChronologyPolicy
    section_entries: tuple[HierarchySectionEntry, ...]
    reason_codes: tuple[str, ...]
    partition_version: str
    locale: str
    perspective: str
    maximum_children: int
    maximum_input_tokens: int

    def __post_init__(self) -> None:
        _require_identifier(self.owner_id, name="reduction owner_id")
        _require_unique(self.reason_codes, name="reduction reason")
        _require_identifier(self.partition_version, name="reduction partition_version")
        _require_identifier(self.locale, name="reduction locale")
        _require_identifier(self.perspective, name="reduction perspective")
        if not self.section_entries:
            raise ValueError("Reduction requirements need expected child artifacts.")

    @property
    def request_id(self) -> str:
        material = {
            "partition_version": self.partition_version,
            "locale": self.locale,
            "perspective": self.perspective,
            "intended_kind": self.intended_kind.value,
            "owner_id": self.owner_id,
            "path": self.path.to_dict(),
            "chronology_policy": self.chronology_policy.value,
            "child_artifact_ids": [entry.artifact_id for entry in self.section_entries],
            "reason_codes": list(self.reason_codes),
            "maximum_children": self.maximum_children,
            "maximum_input_tokens": self.maximum_input_tokens,
        }
        return f"m13_hierarchy_reduce_{canonical_hash(material)[:24]}"


@dataclass(frozen=True)
class HierarchyLevelPlan:
    jobs: tuple[HierarchyJobDescriptor, ...] = ()
    reductions: tuple[HierarchyReductionRequirement, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.reductions


@dataclass(frozen=True)
class PersistentRouteSpec:
    route_id: str
    persistent_lane_id: str
    ordinal: int
    title: str

    def __post_init__(self) -> None:
        _require_identifier(self.route_id, name="route_id")
        _require_identifier(self.persistent_lane_id, name="persistent_lane_id")
        _require_identifier(self.title, name="route title", maximum=200)
        if self.ordinal < 0:
            raise ValueError("route ordinal must be non-negative.")


@dataclass(frozen=True)
class EndingSpec:
    ending_id: str
    ordinal: int
    title: str
    route_id: str | None = None
    persistent_lane_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.ending_id, name="ending_id")
        _require_identifier(self.title, name="ending title", maximum=200)
        _require_optional_identifier(self.route_id, name="route_id")
        _require_optional_identifier(self.persistent_lane_id, name="persistent_lane_id")
        if (self.route_id is None) != (self.persistent_lane_id is None):
            raise ValueError("Route-owned endings require both route and lane IDs.")
        if self.ordinal < 0:
            raise ValueError("ending ordinal must be non-negative.")


def plan_chapter_jobs(
    segment_artifacts: tuple[HierarchyArtifactInput, ...],
    config: HierarchyPartitionConfig,
) -> HierarchyLevelPlan:
    """Plan one bounded chapter-section job per exact route/branch context."""

    _require_globally_unique_artifacts(segment_artifacts)
    groups: dict[tuple[int, str, str, str], list[HierarchyArtifactInput]] = defaultdict(list)
    for child in segment_artifacts:
        if child.job_kind is not LogicalJobKind.SUMMARY_SEGMENT:
            raise ValueError("Chapter jobs consume summary segments, never raw scene artifacts.")
        if child.chapter_id is None or child.chapter_ordinal is None:
            raise ValueError("Chapter segment inputs require exact chapter ownership.")
        # A path may leave for a temporary arm and later reappear after its rejoin.  The
        # deterministic temporal anchor is therefore part of chapter-section ownership: folding
        # both runs together would erase the branch position even though M11 membership remains
        # unchanged.
        groups[
            (
                child.chapter_ordinal,
                child.chapter_id,
                child.path.identity,
                child.temporal_anchor,
            )
        ].append(child)

    jobs: list[HierarchyJobDescriptor] = []
    reductions: list[HierarchyReductionRequirement] = []
    for (
        chapter_ordinal,
        chapter_id,
        _path_identity,
        temporal_anchor,
    ), pending in sorted(groups.items()):
        children = tuple(sorted(pending, key=lambda child: child.ordering_key))
        path = children[0].path
        anchor_fingerprint = canonical_hash({"temporal_anchor": temporal_anchor})[:12]
        owner_id = f"chapter:{chapter_id}:{path.identity[:16]}:{anchor_fingerprint}"
        job, reduction = _plan_one_job(
            kind=LogicalJobKind.CHAPTER,
            owner_id=owner_id,
            path=path,
            chronology_policy=ChronologyPolicy.LINEAR,
            children=children,
            authority_leaves=(),
            config=config,
            chapter_id=chapter_id,
            chapter_ordinal=chapter_ordinal,
            chronology_index=min(child.chronology_index for child in children),
            temporal_anchor=(f"chapter:{chapter_id}:{path.identity[:16]}:{anchor_fingerprint}"),
        )
        if job is not None:
            jobs.append(job)
        if reduction is not None:
            reductions.append(reduction)
    return HierarchyLevelPlan(tuple(jobs), tuple(reductions))


def plan_common_story_job(
    chapter_artifacts: tuple[HierarchyArtifactInput, ...],
    config: HierarchyPartitionConfig,
    *,
    owner_id: str = "common-story",
) -> HierarchyLevelPlan:
    """Plan the shared story once, retaining temporary arms as alternatives."""

    _require_globally_unique_artifacts(chapter_artifacts)
    if not chapter_artifacts:
        raise ValueError("Common story planning requires chapter artifacts.")
    for child in chapter_artifacts:
        if child.job_kind not in {
            LogicalJobKind.CHAPTER,
            LogicalJobKind.SUMMARY_SEGMENT,
        }:
            raise ValueError("The common story consumes only chapter or reduction artifacts.")
        if child.path.route_id is not None or child.path.section not in {
            StorySection.COMMON,
            StorySection.TEMPORARY_BRANCH,
            StorySection.UNRESOLVED,
        }:
            raise ValueError("Persistent route chapters cannot enter the shared story job.")
    children = tuple(sorted(chapter_artifacts, key=lambda child: child.ordering_key))
    common_lanes = {
        child.path.persistent_lane_id
        for child in children
        if child.path.persistent_lane_id is not None
    }
    if len(common_lanes) > 1:
        raise ValueError("Shared story chapters must belong to one common M11 lane.")
    path = HierarchyPathContext(
        section=StorySection.COMMON,
        persistent_lane_id=next(iter(common_lanes), None),
    )
    has_alternatives = any(
        child.path.section is StorySection.TEMPORARY_BRANCH for child in children
    )
    policy = (
        ChronologyPolicy.STRUCTURED_ALTERNATIVES if has_alternatives else ChronologyPolicy.LINEAR
    )
    return _single_level_plan(
        _plan_one_job(
            kind=LogicalJobKind.ROUTE,
            owner_id=owner_id,
            path=path,
            chronology_policy=policy,
            children=children,
            authority_leaves=(),
            config=config,
            chapter_id=None,
            chapter_ordinal=None,
            chronology_index=0,
            temporal_anchor="common-story",
        )
    )


def _normalize_m12_authority_leaves(
    single: M12AuthorityLeaf | None,
    multiple: tuple[M12AuthorityLeaf, ...],
) -> tuple[M12AuthorityLeaf, ...]:
    if single is not None and multiple:
        raise ValueError("Supply either one M12 authority leaf or the plural bounded set.")
    leaves = (single,) if single is not None else multiple
    if len(leaves) > 32:
        raise ValueError("A hierarchy job cannot consume more than 32 M12 authority leaves.")
    identities = tuple(item.authority.authority_identity for item in leaves)
    if len(identities) != len(set(identities)):
        raise ValueError("M12 authority leaves must have unique authority identities.")
    return leaves


def plan_persistent_route_job(
    route: PersistentRouteSpec,
    shared_story_artifact: HierarchyArtifactInput,
    route_chapter_artifacts: tuple[HierarchyArtifactInput, ...],
    config: HierarchyPartitionConfig,
    *,
    m12_authority_leaf: M12AuthorityLeaf | None = None,
    m12_authority_leaves: tuple[M12AuthorityLeaf, ...] = (),
) -> HierarchyLevelPlan:
    """Plan one route without importing chapters from mutually exclusive routes."""

    _require_globally_unique_artifacts((shared_story_artifact, *route_chapter_artifacts))
    if (
        shared_story_artifact.job_kind is not LogicalJobKind.ROUTE
        or shared_story_artifact.path.section is not StorySection.COMMON
        or shared_story_artifact.path.route_id is not None
    ):
        raise ValueError("Persistent routes require one accepted shared-story route artifact.")
    for child in route_chapter_artifacts:
        if child.job_kind not in {
            LogicalJobKind.CHAPTER,
            LogicalJobKind.SUMMARY_SEGMENT,
        }:
            raise ValueError(
                "Persistent route jobs consume shared-story, chapter, or reduction artifacts."
            )
        if child.path.route_id != route.route_id:
            raise ValueError("A persistent route cannot consume another route's chapter.")
        if child.path.persistent_lane_id != route.persistent_lane_id:
            raise ValueError("Route chapter lane ownership is inconsistent.")
        if child.path.section not in {
            StorySection.PERSISTENT_ROUTE,
            StorySection.TEMPORARY_BRANCH,
            StorySection.UNRESOLVED,
        }:
            raise ValueError("Route chapters require route-owned narrative sections.")
    leaves = _normalize_m12_authority_leaves(m12_authority_leaf, m12_authority_leaves)
    if any(
        not _m12_leaf_applies_to_route(
            leaf,
            route.route_id,
            route.persistent_lane_id,
        )
        for leaf in leaves
    ):
        raise ValueError("M12 authority leaf belongs to another route.")

    children = (
        shared_story_artifact,
        *tuple(sorted(route_chapter_artifacts, key=lambda child: child.ordering_key)),
    )
    path = HierarchyPathContext(
        StorySection.PERSISTENT_ROUTE,
        persistent_lane_id=route.persistent_lane_id,
        route_id=route.route_id,
    )
    return _single_level_plan(
        _plan_one_job(
            kind=LogicalJobKind.ROUTE,
            owner_id=f"persistent-route:{route.route_id}",
            path=path,
            chronology_policy=ChronologyPolicy.ROUTE_AWARE,
            children=children,
            authority_leaves=leaves,
            config=config,
            chapter_id=None,
            chapter_ordinal=None,
            chronology_index=route.ordinal,
            temporal_anchor=f"persistent-route:{route.route_id}",
        )
    )


def plan_ending_job(
    ending: EndingSpec,
    ending_artifacts: tuple[HierarchyArtifactInput, ...],
    config: HierarchyPartitionConfig,
    *,
    route_artifact: HierarchyArtifactInput | None = None,
    m12_authority_leaf: M12AuthorityLeaf | None = None,
    m12_authority_leaves: tuple[M12AuthorityLeaf, ...] = (),
) -> HierarchyLevelPlan:
    """Plan one route-owned or common ending with exact prerequisite authority."""

    expected = ending_artifacts if route_artifact is None else (route_artifact, *ending_artifacts)
    _require_globally_unique_artifacts(expected)
    if ending.route_id is not None:
        if route_artifact is None:
            raise ValueError("Route-owned endings require their accepted route artifact.")
        if (
            route_artifact.job_kind is not LogicalJobKind.ROUTE
            or route_artifact.path.route_id != ending.route_id
            or route_artifact.path.persistent_lane_id != ending.persistent_lane_id
        ):
            raise ValueError("Ending route artifact has incompatible route ownership.")
    elif route_artifact is not None:
        raise ValueError("A common ending cannot consume a persistent route artifact.")

    for child in ending_artifacts:
        if child.job_kind not in {
            LogicalJobKind.CHAPTER,
            LogicalJobKind.SUMMARY_SEGMENT,
        }:
            raise ValueError("Ending jobs consume route, chapter, or summary-segment artifacts.")
        if child.path.section is not StorySection.ENDING:
            raise ValueError("Ending child artifacts require explicit ending context.")
        if child.path.ending_id != ending.ending_id:
            raise ValueError("An ending cannot consume another ending's artifact.")
        if (
            child.path.route_id != ending.route_id
            or child.path.persistent_lane_id != ending.persistent_lane_id
        ):
            raise ValueError("Ending child route ownership is inconsistent.")
    leaves = _normalize_m12_authority_leaves(m12_authority_leaf, m12_authority_leaves)
    if any(
        ending.route_id is None
        or ending.persistent_lane_id is None
        or not _m12_leaf_applies_to_route(
            leaf,
            ending.route_id,
            ending.persistent_lane_id,
        )
        for leaf in leaves
    ):
        raise ValueError("M12 authority leaf does not belong to the ending route.")
    if not expected:
        raise ValueError("Ending planning requires at least one bounded child artifact.")

    ordered_endings = tuple(sorted(ending_artifacts, key=lambda child: child.ordering_key))
    children = ordered_endings if route_artifact is None else (route_artifact, *ordered_endings)
    path = HierarchyPathContext(
        StorySection.ENDING,
        persistent_lane_id=ending.persistent_lane_id,
        route_id=ending.route_id,
        ending_id=ending.ending_id,
    )
    return _single_level_plan(
        _plan_one_job(
            kind=LogicalJobKind.ENDING,
            owner_id=f"ending:{ending.ending_id}:{ending.route_id or 'common'}",
            path=path,
            chronology_policy=(
                ChronologyPolicy.ROUTE_AWARE
                if ending.route_id is not None
                else ChronologyPolicy.LINEAR
            ),
            children=children,
            authority_leaves=leaves,
            config=config,
            chapter_id=None,
            chapter_ordinal=None,
            chronology_index=ending.ordinal,
            temporal_anchor=f"ending:{ending.ending_id}",
        )
    )


def _m12_leaf_applies_to_route(
    leaf: M12AuthorityLeaf,
    route_id: str,
    persistent_lane_id: str,
) -> bool:
    authority = leaf.authority
    if authority.authority_kind == "result":
        return (
            authority.route_id is None
            and authority.persistent_lane_id is None
        ) or (
            authority.route_id == route_id
            and authority.persistent_lane_id == persistent_lane_id
        )
    return (
        authority.route_id == route_id
        and authority.persistent_lane_id == persistent_lane_id
    )


def plan_plot_job(
    common_story_artifact: HierarchyArtifactInput,
    route_artifacts: tuple[HierarchyArtifactInput, ...],
    ending_artifacts: tuple[HierarchyArtifactInput, ...],
    unresolved_artifacts: tuple[HierarchyArtifactInput, ...],
    config: HierarchyPartitionConfig,
    *,
    owner_id: str = "whole-plot",
    reduction_artifacts: tuple[HierarchyArtifactInput, ...] = (),
    m12_authority_leaves: tuple[M12AuthorityLeaf, ...] = (),
) -> HierarchyLevelPlan:
    """Plan a bounded route-aware plot; raw scenes and full-project text are impossible."""

    all_children = (
        common_story_artifact,
        *route_artifacts,
        *ending_artifacts,
        *unresolved_artifacts,
        *reduction_artifacts,
    )
    _require_globally_unique_artifacts(all_children)
    if (
        common_story_artifact.job_kind is not LogicalJobKind.ROUTE
        or common_story_artifact.path.section is not StorySection.COMMON
        or common_story_artifact.path.route_id is not None
    ):
        raise ValueError("Plot planning requires the accepted common-story artifact first.")
    route_ids: set[str] = set()
    for child in route_artifacts:
        if (
            child.job_kind is not LogicalJobKind.ROUTE
            or child.path.section is not StorySection.PERSISTENT_ROUTE
            or child.path.route_id is None
        ):
            raise ValueError("Plot route children require explicit persistent-route context.")
        if child.path.route_id in route_ids:
            raise ValueError("Plot planning cannot repeat a persistent route artifact.")
        route_ids.add(child.path.route_id)
    ending_keys: set[tuple[str | None, str]] = set()
    for child in ending_artifacts:
        if (
            child.job_kind is not LogicalJobKind.ENDING
            or child.path.section is not StorySection.ENDING
            or child.path.ending_id is None
        ):
            raise ValueError("Plot ending children require explicit ending context.")
        key = (child.path.route_id, child.path.ending_id)
        if key in ending_keys:
            raise ValueError("Plot planning cannot repeat an ending artifact.")
        ending_keys.add(key)
    for child in unresolved_artifacts:
        if (
            child.job_kind
            not in {
                LogicalJobKind.CHAPTER,
                LogicalJobKind.SUMMARY_SEGMENT,
            }
            or child.path.section is not StorySection.UNRESOLVED
        ):
            raise ValueError("Plot unresolved inputs require bounded chapter or segment artifacts.")
    for child in reduction_artifacts:
        if (
            child.job_kind is not LogicalJobKind.SUMMARY_SEGMENT
            or child.path.section is not StorySection.COMMON
            or child.path.route_id is not None
            or not child.contains_structured_alternatives
            or child.structure_manifest_id is None
        ):
            raise ValueError(
                "Plot reduction inputs must preserve route-aware alternatives in bounded segments."
            )
    if any(child.job_kind is LogicalJobKind.SCENE for child in all_children):
        raise ValueError("Plot jobs never consume raw scene artifacts.")
    leaves = _normalize_m12_authority_leaves(None, m12_authority_leaves)
    if any(
        leaf.authority.route_id is not None
        or leaf.authority.persistent_lane_id is not None
        for leaf in leaves
    ):
        raise ValueError("Plot-level M12 authority must be unassigned to a persistent route.")

    children = (
        common_story_artifact,
        *tuple(sorted(route_artifacts, key=lambda child: child.ordering_key)),
        *tuple(sorted(ending_artifacts, key=lambda child: child.ordering_key)),
        *tuple(sorted(unresolved_artifacts, key=lambda child: child.ordering_key)),
        *tuple(sorted(reduction_artifacts, key=lambda child: child.ordering_key)),
    )
    path = HierarchyPathContext(
        StorySection.COMMON,
        persistent_lane_id=common_story_artifact.path.persistent_lane_id,
    )
    return _single_level_plan(
        _plan_one_job(
            kind=LogicalJobKind.PLOT,
            owner_id=owner_id,
            path=path,
            chronology_policy=ChronologyPolicy.ROUTE_AWARE,
            children=children,
            authority_leaves=leaves,
            config=config,
            chapter_id=None,
            chapter_ordinal=None,
            chronology_index=0,
            temporal_anchor="whole-plot-route-aware",
        )
    )


def plan_character_role_job(
    character_id: str,
    artifacts: tuple[HierarchyArtifactInput, ...],
    config: HierarchyPartitionConfig,
    *,
    m12_authority_leaves: tuple[M12AuthorityLeaf, ...] = (),
) -> HierarchyLevelPlan:
    """Plan bounded participation/role interpretation without inferring an advanced arc."""

    _require_identifier(character_id, name="character_id")
    _require_globally_unique_artifacts(artifacts)
    if not artifacts:
        raise ValueError("Character role planning requires bounded narrative artifacts.")
    allowed = {
        LogicalJobKind.SUMMARY_SEGMENT,
        LogicalJobKind.CHAPTER,
        LogicalJobKind.ROUTE,
        LogicalJobKind.ENDING,
    }
    if any(child.job_kind not in allowed for child in artifacts):
        raise ValueError("Character role jobs cannot consume raw scenes or plot-wide text.")
    children = tuple(sorted(artifacts, key=lambda child: child.ordering_key))
    leaves = _normalize_m12_authority_leaves(None, m12_authority_leaves)
    route_aware = len({child.path.route_id for child in children}) > 1 or any(
        child.path.section in {StorySection.TEMPORARY_BRANCH, StorySection.ENDING}
        or child.contains_structured_alternatives
        for child in children
    )
    path = HierarchyPathContext(StorySection.COMMON)
    return _single_level_plan(
        _plan_one_job(
            kind=LogicalJobKind.CHARACTER,
            owner_id=f"character-role:{character_id}",
            path=path,
            chronology_policy=(
                ChronologyPolicy.ROUTE_AWARE if route_aware else ChronologyPolicy.LINEAR
            ),
            children=children,
            authority_leaves=leaves,
            config=config,
            chapter_id=None,
            chapter_ordinal=None,
            chronology_index=0,
            temporal_anchor=f"character-role:{character_id}",
        )
    )


def accepted_hierarchy_output(
    descriptor: HierarchyJobDescriptor,
    *,
    artifact_id: str,
    claim_ids: tuple[str, ...],
    estimated_tokens: int,
    available: bool = True,
) -> HierarchyArtifactInput:
    """Project a validated hierarchy artifact into the next staged planning level."""

    context = descriptor.spec.context
    return HierarchyArtifactInput(
        artifact_id=artifact_id,
        job_kind=descriptor.spec.kind,
        claim_ids=claim_ids,
        estimated_tokens=estimated_tokens,
        path=descriptor.path,
        chronology_index=descriptor.chronology_index,
        temporal_anchor=context.temporal_anchor or descriptor.spec.owner_id,
        chapter_id=context.chapter_id,
        chapter_ordinal=descriptor.chapter_ordinal,
        occurrence_id=context.occurrence_id,
        call_site_id=context.call_site_id,
        loop_id=context.loop_id,
        available=available,
        expected_leaf_count=descriptor.expected_leaf_count,
        covered_leaf_count=descriptor.covered_leaf_count if available else 0,
        contains_structured_alternatives=(
            descriptor.chronology_policy is not ChronologyPolicy.LINEAR
            or any(
                entry.contains_structured_alternatives
                or entry.path.section is StorySection.TEMPORARY_BRANCH
                for entry in descriptor.section_entries
            )
        ),
        structure_manifest_id=descriptor.structure_manifest_id,
    )


def _single_level_plan(
    result: tuple[HierarchyJobDescriptor | None, HierarchyReductionRequirement | None],
) -> HierarchyLevelPlan:
    job, reduction = result
    return HierarchyLevelPlan(
        jobs=() if job is None else (job,),
        reductions=() if reduction is None else (reduction,),
    )


def _plan_one_job(
    *,
    kind: LogicalJobKind,
    owner_id: str,
    path: HierarchyPathContext,
    chronology_policy: ChronologyPolicy,
    children: tuple[HierarchyArtifactInput, ...],
    authority_leaves: tuple[M12AuthorityLeaf, ...],
    config: HierarchyPartitionConfig,
    chapter_id: str | None,
    chapter_ordinal: int | None,
    chronology_index: int,
    temporal_anchor: str,
) -> tuple[HierarchyJobDescriptor | None, HierarchyReductionRequirement | None]:
    if not children:
        raise ValueError(f"{kind.value} planning requires at least one child artifact.")
    entries = tuple(HierarchySectionEntry.from_child(child) for child in children)
    token_count = config.prompt_overhead_tokens + sum(
        child.estimated_tokens for child in children if child.available
    )
    reasons: list[str] = []
    if len(children) > config.maximum_children:
        reasons.append("child_count_limit")
    if token_count > config.maximum_input_tokens:
        reasons.append("input_token_limit")
    if reasons:
        return None, HierarchyReductionRequirement(
            intended_kind=kind,
            owner_id=owner_id,
            path=path,
            chronology_policy=chronology_policy,
            section_entries=entries,
            reason_codes=tuple(reasons),
            partition_version=config.partition_version,
            locale=config.locale,
            perspective=config.perspective,
            maximum_children=config.maximum_children,
            maximum_input_tokens=config.maximum_input_tokens,
        )

    child_claim_ids = tuple(
        claim_id for child in children if child.available for claim_id in child.claim_ids
    )
    mandatory_child_claim_ids = tuple(
        claim_id
        for child in children
        if child.available
        for claim_id in child.mandatory_claim_ids
    )
    if len(child_claim_ids) != len(set(child_claim_ids)):
        raise ValueError("A child claim cannot be owned by multiple direct artifacts.")
    authority_claim_ids = tuple(
        claim_id for leaf in authority_leaves for claim_id in leaf.claim_ids
    )
    if len(authority_claim_ids) != len(set(authority_claim_ids)):
        raise ValueError("M12 authority leaf claims must be unique.")

    child_contexts = [child.context_dict() for child in children]
    fingerprint = canonical_hash(
        {
            "partition_version": config.partition_version,
            "intended_kind": kind.value,
            "owner_id": owner_id,
            "path": path.to_dict(),
            "chronology_policy": chronology_policy.value,
            "ordered_child_contexts": child_contexts,
            "m12_result_identities": [leaf.authority.result_identity for leaf in authority_leaves],
            "m12_authority_identities": [
                leaf.authority.authority_identity for leaf in authority_leaves
            ],
        }
    )
    occurrence_id = _shared_optional(children, "occurrence_id")
    call_site_id = _shared_optional(children, "call_site_id")
    loop_id = _shared_optional(children, "loop_id")
    spec = LogicalJobSpec(
        kind=kind,
        owner_id=owner_id,
        context=StructuralContext(
            chapter_id=chapter_id,
            lane_id=path.persistent_lane_id,
            route_id=path.route_id,
            temporary_container_id=path.temporary_container_id,
            temporary_arm_id=path.temporary_arm_id,
            occurrence_id=occurrence_id,
            call_site_id=call_site_id,
            loop_id=loop_id,
            temporal_anchor=temporal_anchor,
            structural_fingerprint=fingerprint,
        ),
        ordered_child_artifact_ids=tuple(child.artifact_id for child in children),
        locale=config.locale,
        perspective=config.perspective,
        partition_version=config.partition_version,
    )
    expected_leaf_count = sum(child.expected_leaf_count for child in children)
    covered_leaf_count = sum(
        child.covered_leaf_count if child.covered_leaf_count is not None else 0
        for child in children
    )
    return HierarchyJobDescriptor(
        spec=spec,
        path=path,
        chronology_policy=chronology_policy,
        section_entries=entries,
        child_claim_ids=child_claim_ids,
        mandatory_child_claim_ids=mandatory_child_claim_ids,
        authority_leaf_claim_ids=authority_claim_ids,
        m12_authority=tuple(leaf.authority for leaf in authority_leaves),
        estimated_input_tokens=token_count,
        expected_leaf_count=expected_leaf_count,
        covered_leaf_count=covered_leaf_count,
        chapter_ordinal=chapter_ordinal,
        chronology_index=chronology_index,
    ), None


def _shared_optional(children: tuple[HierarchyArtifactInput, ...], field_name: str) -> str | None:
    values = {getattr(child, field_name) for child in children}
    if len(values) != 1:
        return None
    value = next(iter(values))
    return value if isinstance(value, str) else None


def _require_globally_unique_artifacts(
    children: tuple[HierarchyArtifactInput, ...],
) -> None:
    artifact_ids = tuple(child.artifact_id for child in children)
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("Hierarchy child artifact IDs must be globally unique.")

"""Immutable Phase 04 generation publication and deterministic path-fact comparison."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from renpy_story_mapper.story_map_v2.contracts import canonical_hash
from renpy_story_mapper.story_map_v2.phase04_sections import (
    DerivedSemanticAssembly,
    MeaningfulSection,
)
from renpy_story_mapper.story_map_v2.phase04_semantics import SemanticAssembly

PHASE04_GENERATION_SCHEMA = "story-map-v2-phase04-generation-v1"
FaultInjector = Callable[[str], None]


class PublicationConflictError(ValueError):
    """A candidate no longer matches the atomic generation pointers."""


class GenerationKind(StrEnum):
    STRUCTURAL = "structural"
    CANDIDATE = "candidate"
    COMPLETE = "complete"


@dataclass(frozen=True)
class GenerationDescriptor:
    generation_id: str
    run_id: str
    plan_id: str
    authority_identity: str
    kind: GenerationKind
    descriptor: object


@dataclass(frozen=True)
class GenerationPointers:
    current_complete_generation: str | None
    active_build_generation: str | None
    map_revision: int


class GenerationRepository(Protocol):
    def create_generation(self, generation: GenerationDescriptor) -> None: ...

    def load_generation(self, generation_id: str) -> GenerationDescriptor | None:
        """Load one immutable generation envelope and its authoritative descriptor."""
        ...

    def is_run_publishable(
        self,
        run_id: str,
        plan_id: str,
        authority_identity: str,
    ) -> bool:
        """Provide advisory preflight only; each pointer CAS must revalidate atomically."""
        ...

    def set_active_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str | None,
        expected_complete_generation_id: str | None,
    ) -> GenerationPointers:
        """Atomically revalidate target run authority plus both pointers, then activate."""
        ...

    def generation_pointers(self) -> GenerationPointers: ...

    def publish_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str,
        expected_complete_generation_id: str | None,
        fault: FaultInjector | None = None,
    ) -> GenerationPointers:
        """Atomically revalidate run/lineage plus both pointers, then publish COMPLETE."""
        ...


class Phase03EventRecord(Protocol):
    selection_id: str
    title: str
    summary: str


class Phase03SectionRecord(Protocol):
    id: str
    title: str
    summary: str
    events: Sequence[Phase03EventRecord]


class Phase03ReadRecord(Protocol):
    status: str
    title: str
    overview: str
    sections: Sequence[Phase03SectionRecord]


class GenerationBuildState(StrEnum):
    STRUCTURAL = "structural"
    BUILDING = "building"
    COMPLETE = "complete"


class GenerationFreshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    BUILDING = "building"


class PathFactKind(StrEnum):
    ARM = "arm"
    ROUTE = "route"
    ENDING = "ending"


def _trimmed(value: str, label: str, *, maximum: int = 2_000) -> str:
    if not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be non-empty, trimmed, and bounded")
    return value


@dataclass(frozen=True, order=True)
class PathFact:
    kind: PathFactKind
    fact_id: str
    section_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _trimmed(self.fact_id, "path fact ID")
        if not self.section_ids or len(self.section_ids) != len(set(self.section_ids)):
            raise ValueError("path fact sections must be non-empty and unique")
        for section_id in self.section_ids:
            _trimmed(section_id, "path fact section ID")


@dataclass(frozen=True)
class PathFactSnapshot:
    generation_id: str
    facts: tuple[PathFact, ...]

    def __post_init__(self) -> None:
        _trimmed(self.generation_id, "path fact generation ID")
        keys = tuple((fact.kind, fact.fact_id) for fact in self.facts)
        if len(keys) != len(set(keys)):
            raise ValueError("path fact snapshot contains duplicate facts")


@dataclass(frozen=True)
class NewPathFact:
    kind: PathFactKind
    fact_id: str
    section_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _trimmed(self.fact_id, "NEW path fact ID")
        if not self.section_ids or len(self.section_ids) != len(set(self.section_ids)):
            raise ValueError("NEW path fact sections must be non-empty and unique")
        for section_id in self.section_ids:
            _trimmed(section_id, "NEW path fact section ID")


def derive_new_path_facts(
    current: tuple[PathFact, ...],
    immediately_previous: PathFactSnapshot | None,
) -> tuple[NewPathFact, ...]:
    """Compare deterministic arm/route/ending identity only, never generated prose."""

    current_keys = tuple((fact.kind, fact.fact_id) for fact in current)
    if len(current_keys) != len(set(current_keys)):
        raise ValueError("current path facts must be unique")
    if immediately_previous is None:
        return ()
    previous_keys = {(fact.kind, fact.fact_id) for fact in immediately_previous.facts}
    return tuple(
        NewPathFact(fact.kind, fact.fact_id, fact.section_ids)
        for fact in current
        if (fact.kind, fact.fact_id) not in previous_keys
    )


@dataclass(frozen=True)
class GenerationArtifact:
    generation_id: str
    run_id: str
    plan_id: str
    authority_identity: str
    story_chunk_plan_identity: str
    source_identity: str
    coverage_hash: str
    kind: GenerationKind
    state: GenerationBuildState
    title: str
    overview: str
    sections: tuple[MeaningfulSection, ...]
    path_facts: tuple[PathFact, ...]
    baseline_generation_id: str | None
    baseline_path_facts: tuple[PathFact, ...] | None
    new_path_facts: tuple[NewPathFact, ...]
    reader_manifest: Mapping[str, object] | None = None
    schema: str = PHASE04_GENERATION_SCHEMA

    def __post_init__(self) -> None:
        for value, label in (
            (self.generation_id, "generation ID"),
            (self.run_id, "run ID"),
            (self.plan_id, "plan ID"),
            (self.authority_identity, "authority identity"),
            (self.story_chunk_plan_identity, "StoryChunkPlan identity"),
            (self.source_identity, "source identity"),
            (self.coverage_hash, "coverage hash"),
            (self.title, "generation title"),
            (self.overview, "generation overview"),
        ):
            _trimmed(value, label, maximum=2_000)
        if self.schema != PHASE04_GENERATION_SCHEMA:
            raise ValueError("unsupported Phase 04 generation schema")
        if not self.sections:
            raise ValueError("generation requires at least one section")
        section_ids = tuple(section.section_id for section in self.sections)
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("generation section IDs must be unique")
        path_fact_keys = tuple((fact.kind, fact.fact_id) for fact in self.path_facts)
        if len(path_fact_keys) != len(set(path_fact_keys)):
            raise ValueError("generation path facts must be unique")
        if any(
            section_id not in set(section_ids)
            for fact in self.path_facts
            for section_id in fact.section_ids
        ):
            raise ValueError("path facts must reference existing generation sections")
        if self.kind is GenerationKind.COMPLETE:
            if self.state is not GenerationBuildState.COMPLETE:
                raise ValueError("complete generation requires complete build state")
        elif self.state is GenerationBuildState.COMPLETE:
            raise ValueError("non-complete generation cannot claim complete state")
        if self.baseline_generation_id is None:
            if self.baseline_path_facts is not None or self.new_path_facts:
                raise ValueError("initial generation cannot carry a baseline or NEW path facts")
        else:
            _trimmed(self.baseline_generation_id, "baseline generation ID")
            if self.baseline_path_facts is None:
                raise ValueError("successor generation requires exact baseline path facts")
            baseline_keys = tuple(
                (fact.kind, fact.fact_id) for fact in self.baseline_path_facts
            )
            if len(baseline_keys) != len(set(baseline_keys)):
                raise ValueError("baseline path facts must be unique")
        new_keys = tuple((fact.kind, fact.fact_id) for fact in self.new_path_facts)
        if len(new_keys) != len(set(new_keys)):
            raise ValueError("generation NEW path facts must be unique")
        current_by_key = {(fact.kind, fact.fact_id): fact for fact in self.path_facts}
        if any(
            key not in current_by_key
            or current_by_key[key].section_ids != fact.section_ids
            for key, fact in zip(new_keys, self.new_path_facts, strict=True)
        ):
            raise ValueError("NEW path facts must be an exact subset of current facts")

    @property
    def descriptor(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": self.schema,
            "generation_id": self.generation_id,
            "state": self.state.value,
            "story_chunk_plan_identity": self.story_chunk_plan_identity,
            "source_identity": self.source_identity,
            "coverage_hash": self.coverage_hash,
            "title": self.title,
            "overview": self.overview,
            "sections": [
                {
                    "section_id": section.section_id,
                    "corridor_id": section.corridor_id,
                    "route_owner": section.route_owner,
                    "event_ids": list(section.event_ids),
                    "title": section.title,
                    "summary": section.summary,
                    "origin": section.origin.value,
                }
                for section in self.sections
            ],
            "path_facts": [
                {
                    "kind": fact.kind.value,
                    "fact_id": fact.fact_id,
                    "section_ids": list(fact.section_ids),
                }
                for fact in self.path_facts
            ],
            "baseline_generation_id": self.baseline_generation_id,
            "new_path_facts": [
                {
                    "kind": fact.kind.value,
                    "fact_id": fact.fact_id,
                    "section_ids": list(fact.section_ids),
                }
                for fact in self.new_path_facts
            ],
        }
        if self.reader_manifest is not None:
            value.update(
                {
                    "workflow_run_id": self.run_id,
                    "workflow_plan_id": self.plan_id,
                    "workflow_authority_identity": self.authority_identity,
                }
            )
            value["reader_manifest"] = dict(self.reader_manifest)
        return value

    def durable_descriptor(self) -> GenerationDescriptor:
        return GenerationDescriptor(
            generation_id=self.generation_id,
            run_id=self.run_id,
            plan_id=self.plan_id,
            authority_identity=self.authority_identity,
            kind=self.kind,
            descriptor=self.descriptor,
        )


@dataclass(frozen=True)
class _StoredGeneration:
    generation_id: str
    run_id: str
    plan_id: str
    authority_identity: str
    kind: GenerationKind
    story_chunk_plan_identity: str
    source_identity: str
    coverage_hash: str
    baseline_generation_id: str | None
    path_facts: tuple[PathFact, ...]


def _stored_string(value: object, label: str) -> str:
    if type(value) is not str:
        raise PublicationConflictError(f"stored generation {label} is invalid")
    try:
        return _trimmed(value, f"stored generation {label}")
    except ValueError as exc:
        raise PublicationConflictError(f"stored generation {label} is invalid") from exc


def _stored_generation(record: GenerationDescriptor) -> _StoredGeneration:
    if type(record.descriptor) is not dict:
        raise PublicationConflictError("stored generation descriptor is invalid")
    descriptor = cast(Mapping[str, object], record.descriptor)
    required = {
        "schema",
        "generation_id",
        "story_chunk_plan_identity",
        "source_identity",
        "coverage_hash",
        "path_facts",
        "baseline_generation_id",
    }
    if not required.issubset(descriptor):
        raise PublicationConflictError("stored generation descriptor is incomplete")
    if descriptor["schema"] != PHASE04_GENERATION_SCHEMA:
        raise PublicationConflictError("stored generation schema is unsupported")
    generation_id = _stored_string(descriptor["generation_id"], "generation ID")
    if generation_id != record.generation_id:
        raise PublicationConflictError("stored generation envelope and payload disagree")
    baseline = descriptor["baseline_generation_id"]
    if baseline is not None:
        baseline = _stored_string(baseline, "baseline generation ID")
    raw_facts = descriptor["path_facts"]
    if type(raw_facts) is not list:
        raise PublicationConflictError("stored generation path facts are invalid")
    facts: list[PathFact] = []
    try:
        for raw_fact in raw_facts:
            if type(raw_fact) is not dict or set(raw_fact) != {
                "kind",
                "fact_id",
                "section_ids",
            }:
                raise ValueError("path fact shape")
            fact = cast(Mapping[str, object], raw_fact)
            raw_sections = fact["section_ids"]
            if type(raw_sections) is not list:
                raise ValueError("path fact sections")
            facts.append(
                PathFact(
                    PathFactKind(_stored_string(fact["kind"], "path fact kind")),
                    _stored_string(fact["fact_id"], "path fact ID"),
                    tuple(
                        _stored_string(section_id, "path fact section ID")
                        for section_id in raw_sections
                    ),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise PublicationConflictError("stored generation path facts are invalid") from exc
    fact_keys = tuple((fact.kind, fact.fact_id) for fact in facts)
    if len(fact_keys) != len(set(fact_keys)):
        raise PublicationConflictError("stored generation path facts are duplicated")
    try:
        kind = GenerationKind(record.kind)
    except ValueError as exc:
        raise PublicationConflictError("stored generation kind is invalid") from exc
    return _StoredGeneration(
        generation_id=generation_id,
        run_id=record.run_id,
        plan_id=record.plan_id,
        authority_identity=record.authority_identity,
        kind=kind,
        story_chunk_plan_identity=_stored_string(
            descriptor["story_chunk_plan_identity"], "StoryChunkPlan identity"
        ),
        source_identity=_stored_string(descriptor["source_identity"], "source identity"),
        coverage_hash=_stored_string(descriptor["coverage_hash"], "coverage hash"),
        baseline_generation_id=baseline,
        path_facts=tuple(facts),
    )


def _load_generation(
    repository: GenerationRepository,
    generation_id: str,
) -> _StoredGeneration:
    record = repository.load_generation(generation_id)
    if record is None:
        raise PublicationConflictError("generation lineage record is unavailable")
    return _stored_generation(record)


def _lineage(artifact: GenerationArtifact) -> tuple[str, ...]:
    return (
        artifact.run_id,
        artifact.plan_id,
        artifact.authority_identity,
        artifact.story_chunk_plan_identity,
        artifact.source_identity,
        artifact.coverage_hash,
        artifact.baseline_generation_id or "",
    )


def _stored_lineage(generation: _StoredGeneration) -> tuple[str, ...]:
    return (
        generation.run_id,
        generation.plan_id,
        generation.authority_identity,
        generation.story_chunk_plan_identity,
        generation.source_identity,
        generation.coverage_hash,
        generation.baseline_generation_id or "",
    )


def _validate_derived_binding(
    generation_id: str,
    authority_identity: str,
    semantic_assembly: SemanticAssembly,
    derived: DerivedSemanticAssembly,
) -> None:
    if derived.candidate_generation_identity != generation_id:
        raise ValueError("derived output belongs to a different candidate generation")
    if (
        derived.semantic_plan.story_chunk_plan_identity
        != semantic_assembly.story_chunk_plan_identity
        or derived.semantic_plan.authority_identity != authority_identity
        or derived.semantic_plan_identity != derived.semantic_plan.semantic_plan_identity
    ):
        raise ValueError("derived output has foreign semantic-plan authority")
    expected_corridors = tuple(chunk.chunk_id for chunk in semantic_assembly.chunks)
    if tuple(corridor.corridor_id for corridor in derived.semantic_plan.corridors) != (
        expected_corridors
    ) or tuple(result.corridor_id for result in derived.corridor_results) != expected_corridors:
        raise ValueError("derived output changed exact semantic corridor membership or order")
    semantic_event_ids = tuple(event.event_id for event in semantic_assembly.events)
    if len(semantic_event_ids) != len(set(semantic_event_ids)):
        raise ValueError("semantic assembly event identity is duplicated")
    section_ids: list[str] = []
    derived_event_ids: list[str] = []
    for chunk, corridor, result in zip(
        semantic_assembly.chunks,
        derived.semantic_plan.corridors,
        derived.corridor_results,
        strict=True,
    ):
        expected_event_ids = tuple(event.event_id for event in chunk.events)
        if result.route_owner != corridor.route_owner or not result.sections:
            raise ValueError("derived corridor result changed frozen ownership or is empty")
        corridor_event_ids: list[str] = []
        for section in result.sections:
            if (
                section.corridor_id != corridor.corridor_id
                or section.route_owner != corridor.route_owner
            ):
                raise ValueError("derived section changed frozen corridor ownership")
            section_ids.append(section.section_id)
            corridor_event_ids.extend(section.event_ids)
        if tuple(corridor_event_ids) != expected_event_ids:
            raise ValueError(
                "derived sections must cover exact existing corridor events once and in order"
            )
        derived_event_ids.extend(corridor_event_ids)
    if len(section_ids) != len(set(section_ids)) or tuple(derived_event_ids) != semantic_event_ids:
        raise ValueError("derived section publication has duplicate or foreign coverage")


def build_generation_artifact(
    *,
    generation_id: str,
    run_id: str,
    plan_id: str,
    authority_identity: str,
    semantic_assembly: SemanticAssembly,
    derived: DerivedSemanticAssembly,
    kind: GenerationKind,
    path_facts: tuple[PathFact, ...] = (),
    immediately_previous: PathFactSnapshot | None = None,
) -> GenerationArtifact:
    if not derived.sections:
        raise ValueError("derived semantic assembly is incomplete")
    _validate_derived_binding(
        generation_id,
        authority_identity,
        semantic_assembly,
        derived,
    )
    if kind is GenerationKind.STRUCTURAL:
        state = GenerationBuildState.STRUCTURAL
    elif kind is GenerationKind.CANDIDATE:
        state = GenerationBuildState.BUILDING
    else:
        state = GenerationBuildState.COMPLETE
    overview = derived.overview
    title = "Whole story overview" if overview is None else overview.title
    summary = (
        "Deterministic story sections are available while synthesis progresses."
        if overview is None
        else overview.summary
    )
    return GenerationArtifact(
        generation_id=generation_id,
        run_id=run_id,
        plan_id=plan_id,
        authority_identity=authority_identity,
        story_chunk_plan_identity=semantic_assembly.story_chunk_plan_identity,
        source_identity=semantic_assembly.source_identity,
        coverage_hash=semantic_assembly.coverage_hash,
        kind=kind,
        state=state,
        title=title,
        overview=summary,
        sections=derived.sections,
        path_facts=path_facts,
        baseline_generation_id=(
            None if immediately_previous is None else immediately_previous.generation_id
        ),
        baseline_path_facts=(
            None if immediately_previous is None else immediately_previous.facts
        ),
        new_path_facts=derive_new_path_facts(path_facts, immediately_previous),
    )


class AtomicGenerationPublisher:
    """Thin CAS publisher over Track B's existing immutable generation primitives."""

    def __init__(self, repository: GenerationRepository) -> None:
        self._repository = repository

    def _require_publishable_run(self, artifact: GenerationArtifact) -> None:
        if not self._repository.is_run_publishable(
            artifact.run_id,
            artifact.plan_id,
            artifact.authority_identity,
        ):
            raise PublicationConflictError(
                "generation run is cancelled, terminal, or has stale authority"
            )

    def _validate_current_baseline(
        self,
        artifact: GenerationArtifact,
        pointers: GenerationPointers,
    ) -> _StoredGeneration | None:
        if artifact.baseline_generation_id != pointers.current_complete_generation:
            raise PublicationConflictError(
                "generation does not descend from the immediately prior accepted generation"
            )
        if pointers.current_complete_generation is None:
            if artifact.baseline_path_facts is not None or artifact.new_path_facts:
                raise PublicationConflictError("initial generation supplied a false baseline")
            return None
        previous = _load_generation(
            self._repository,
            pointers.current_complete_generation,
        )
        if previous.kind is not GenerationKind.COMPLETE:
            raise PublicationConflictError("current generation pointer is not complete")
        if artifact.baseline_path_facts != previous.path_facts:
            raise PublicationConflictError(
                "caller baseline path facts differ from the accepted generation"
            )
        authoritative_snapshot = PathFactSnapshot(previous.generation_id, previous.path_facts)
        expected_new = derive_new_path_facts(artifact.path_facts, authoritative_snapshot)
        if artifact.new_path_facts != expected_new:
            raise PublicationConflictError(
                "NEW path facts differ from the authoritative accepted baseline"
            )
        return previous

    def activate_progressive(
        self,
        artifact: GenerationArtifact,
        *,
        expected_active_generation_id: str | None,
    ) -> GenerationPointers:
        if artifact.kind is GenerationKind.COMPLETE:
            raise ValueError("complete generations use publish_complete")
        self._require_publishable_run(artifact)
        pointers = self._repository.generation_pointers()
        self._validate_current_baseline(artifact, pointers)
        if expected_active_generation_id is not None:
            active = _load_generation(self._repository, expected_active_generation_id)
            if _stored_lineage(active) != _lineage(artifact):
                raise PublicationConflictError(
                    "progressive generation changed active run, authority, or source lineage"
                )
        self._repository.create_generation(artifact.durable_descriptor())
        return self._repository.set_active_generation(
            artifact.generation_id,
            expected_active_generation_id=expected_active_generation_id,
            expected_complete_generation_id=pointers.current_complete_generation,
        )

    def publish_complete(
        self,
        artifact: GenerationArtifact,
        *,
        expected_active_generation_id: str,
        fault: FaultInjector | None = None,
    ) -> GenerationPointers:
        if artifact.kind is not GenerationKind.COMPLETE:
            raise ValueError("only a complete generation can advance the complete pointer")
        pointers = self._repository.generation_pointers()
        if (
            pointers.current_complete_generation == artifact.generation_id
            and pointers.active_build_generation is None
        ):
            self._repository.create_generation(artifact.durable_descriptor())
            return pointers
        self._require_publishable_run(artifact)
        self._validate_current_baseline(artifact, pointers)
        if pointers.active_build_generation != expected_active_generation_id:
            raise PublicationConflictError("stale candidate cannot replace the active generation")
        active = _load_generation(self._repository, expected_active_generation_id)
        if _stored_lineage(active) != _lineage(artifact):
            raise PublicationConflictError(
                "complete generation changed active run, authority, or source lineage"
            )
        self._repository.create_generation(artifact.durable_descriptor())
        return self._repository.publish_generation(
            artifact.generation_id,
            expected_active_generation_id=expected_active_generation_id,
            expected_complete_generation_id=artifact.baseline_generation_id,
            fault=fault,
        )


def generation_freshness(
    generation_id: str,
    pointers: GenerationPointers,
) -> GenerationFreshness:
    if generation_id == pointers.active_build_generation:
        return GenerationFreshness.BUILDING
    if generation_id == pointers.current_complete_generation:
        return (
            GenerationFreshness.STALE
            if pointers.active_build_generation is not None
            else GenerationFreshness.CURRENT
        )
    return GenerationFreshness.STALE


@dataclass(frozen=True)
class Phase03CompatibilityEvent:
    selection_id: str
    title: str
    summary: str


@dataclass(frozen=True)
class Phase03CompatibilitySection:
    section_id: str
    title: str
    summary: str
    events: tuple[Phase03CompatibilityEvent, ...]


@dataclass(frozen=True)
class Phase03CompatibilityProjection:
    identity: str
    status: str
    title: str
    overview: str
    sections: tuple[Phase03CompatibilitySection, ...]
    read_only: bool = True


def project_phase03_read_only(page: Phase03ReadRecord) -> Phase03CompatibilityProjection:
    """Project existing Phase 03 records without rewriting or publishing their stored bytes."""

    sections = tuple(
        Phase03CompatibilitySection(
            section_id=section.id,
            title=section.title,
            summary=section.summary,
            events=tuple(
                Phase03CompatibilityEvent(event.selection_id, event.title, event.summary)
                for event in section.events
            ),
        )
        for section in page.sections
    )
    identity = canonical_hash(
        {
            "status": page.status,
            "title": page.title,
            "overview": page.overview,
            "sections": [
                {
                    "id": section.section_id,
                    "title": section.title,
                    "summary": section.summary,
                    "events": [
                        {
                            "selection_id": event.selection_id,
                            "title": event.title,
                            "summary": event.summary,
                        }
                        for event in section.events
                    ],
                }
                for section in sections
            ],
        }
    )
    return Phase03CompatibilityProjection(
        identity=identity,
        status=page.status,
        title=page.title,
        overview=page.overview,
        sections=sections,
    )

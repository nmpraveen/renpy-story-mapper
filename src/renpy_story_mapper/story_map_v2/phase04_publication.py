"""Immutable Phase 04 generation publication and deterministic path-fact comparison."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

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

    def set_active_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str | None,
    ) -> GenerationPointers: ...

    def generation_pointers(self) -> GenerationPointers: ...

    def publish_generation(
        self,
        generation_id: str,
        *,
        expected_active_generation_id: str,
        fault: FaultInjector | None = None,
    ) -> GenerationPointers: ...


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
    new_path_facts: tuple[NewPathFact, ...]
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
            if self.new_path_facts:
                raise ValueError("initial generation cannot claim NEW path facts")
        else:
            _trimmed(self.baseline_generation_id, "baseline generation ID")
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
        return {
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

    def durable_descriptor(self) -> GenerationDescriptor:
        return GenerationDescriptor(
            generation_id=self.generation_id,
            run_id=self.run_id,
            plan_id=self.plan_id,
            authority_identity=self.authority_identity,
            kind=self.kind,
            descriptor=self.descriptor,
        )


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
    if derived.semantic_plan_identity == "" or not derived.sections:
        raise ValueError("derived semantic assembly is incomplete")
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
        new_path_facts=derive_new_path_facts(path_facts, immediately_previous),
    )


class AtomicGenerationPublisher:
    """Thin CAS publisher over Track B's existing immutable generation primitives."""

    def __init__(self, repository: GenerationRepository) -> None:
        self._repository = repository

    def activate_progressive(
        self,
        artifact: GenerationArtifact,
        *,
        expected_active_generation_id: str | None,
    ) -> GenerationPointers:
        if artifact.kind is GenerationKind.COMPLETE:
            raise ValueError("complete generations use publish_complete")
        self._repository.create_generation(artifact.durable_descriptor())
        return self._repository.set_active_generation(
            artifact.generation_id,
            expected_active_generation_id=expected_active_generation_id,
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
        self._repository.create_generation(artifact.durable_descriptor())
        pointers = self._repository.generation_pointers()
        if (
            pointers.current_complete_generation == artifact.generation_id
            and pointers.active_build_generation is None
        ):
            return pointers
        if artifact.baseline_generation_id != pointers.current_complete_generation:
            raise PublicationConflictError(
                "complete generation was not compared with the immediately prior accepted "
                "generation"
            )
        if pointers.active_build_generation == expected_active_generation_id:
            pointers = self._repository.set_active_generation(
                artifact.generation_id,
                expected_active_generation_id=expected_active_generation_id,
            )
        elif pointers.active_build_generation != artifact.generation_id:
            raise PublicationConflictError("stale candidate cannot replace the active generation")
        return self._repository.publish_generation(
            artifact.generation_id,
            expected_active_generation_id=artifact.generation_id,
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

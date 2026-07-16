"""End-to-end M13 narrative hierarchy over exact current M10/M11/M12 authority.

The pipeline is deliberately dependency staged.  It first publishes independent scene jobs,
then derives internal segment identities from the *accepted* child artifact IDs at each fan-in
level.  Chapters, shared story, persistent routes, endings, the route-aware plot, and bounded
character roles are planned only from the immediately preceding validated artifacts.  Missing
children remain explicit coverage holes; no stage invents M11 membership or flattens mutually
exclusive routes into one chronology.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from renpy_story_mapper.m11_scene_model import LaneKind
from renpy_story_mapper.m12_model import RouteBadge, TechnicalStatus
from renpy_story_mapper.narrative.contracts import (
    ConsentManifest,
    JsonValue,
    LogicalJobKind,
    LogicalJobSpec,
    LogicalJobState,
    NarrativeClaim,
    StructuralContext,
    canonical_hash,
)
from renpy_story_mapper.narrative.hierarchy import (
    ChronologyPolicy,
    EndingSpec,
    HierarchyArtifactInput,
    HierarchyJobDescriptor,
    HierarchyPartitionConfig,
    HierarchyPathContext,
    HierarchySectionEntry,
    M12AuthorityLeaf,
    M12RouteAuthority,
    PersistentRouteSpec,
    StorySection,
    make_m12_authority_leaf,
    plan_chapter_jobs,
    plan_character_role_job,
    plan_common_story_job,
    plan_ending_job,
    plan_persistent_route_job,
    plan_plot_job,
)
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.narrative.preparation import ProviderPricing
from renpy_story_mapper.narrative.projection import M13_CHARACTER_PARTICIPATION_VERSION
from renpy_story_mapper.narrative.provider import NarrativeProvider
from renpy_story_mapper.narrative.reduction import (
    MAX_PROPAGATED_CLAIMS_PER_ARTIFACT,
    PreparedHierarchyJob,
    RuntimeNarrativeArtifact,
    execute_hierarchy_jobs,
    persist_m12_authority_leaf,
    prepare_hierarchy_job,
)
from renpy_story_mapper.narrative.scheduler import (
    SchedulerJobRecord,
    SchedulerPolicy,
    SchedulerRunRecord,
    SchedulerRunResult,
    SchedulerRunState,
    SchedulerUsage,
)
from renpy_story_mapper.narrative.segments import (
    SegmentChild,
    SegmentDescriptor,
    SegmentPartitionConfig,
    SegmentStructuralContext,
    plan_summary_segments,
)
from renpy_story_mapper.narrative.workflow import (
    PreparedNarrativeRun,
    run_prepared_scene_jobs,
)
from renpy_story_mapper.project import Project
from renpy_story_mapper.storage import canonical_json

CancelledCallback = Callable[[], bool]


@dataclass(frozen=True)
class ScenePlacement:
    """Provider-free M11 ownership used only to organize M13 artifacts."""

    scene_id: str
    deterministic_title: str
    chapter_id: str
    chapter_ordinal: int
    scene_ordinal: int
    lane_id: str
    path: HierarchyPathContext
    segment_context: SegmentStructuralContext
    speaker_ids: tuple[str, ...]


@dataclass(frozen=True)
class PipelineArtifactSet:
    scene_artifact_ids: tuple[str, ...] = ()
    segment_artifact_ids: tuple[str, ...] = ()
    chapter_artifact_ids: tuple[str, ...] = ()
    common_story_artifact_id: str | None = None
    route_artifact_ids: tuple[str, ...] = ()
    ending_artifact_ids: tuple[str, ...] = ()
    plot_artifact_id: str | None = None
    character_artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrativePipelineResult:
    """One complete run view; every child result remains independently durable."""

    record: SchedulerRunRecord
    jobs: tuple[SchedulerJobRecord, ...]
    phases: tuple[SchedulerRunResult, ...]
    artifacts: PipelineArtifactSet
    unresolved_codes: tuple[str, ...]


@dataclass(frozen=True)
class _ArtifactCandidate:
    """Accepted runtime artifact or a stable expected-but-missing child."""

    artifact_id: str
    job_kind: LogicalJobKind
    path: HierarchyPathContext
    chronology_index: int
    temporal_anchor: str
    chapter_id: str | None
    chapter_ordinal: int | None
    occurrence_id: str | None
    call_site_id: str | None
    loop_id: str | None
    expected_leaf_count: int
    covered_leaf_count: int
    estimated_tokens: int
    runtime: RuntimeNarrativeArtifact | None = None
    segment_context: SegmentStructuralContext | None = None

    @property
    def available(self) -> bool:
        return self.runtime is not None

    @property
    def claim_ids(self) -> tuple[str, ...]:
        return () if self.runtime is None else self.runtime.claim_ids

    def hierarchy_input(self) -> HierarchyArtifactInput:
        return HierarchyArtifactInput(
            artifact_id=self.artifact_id,
            job_kind=self.job_kind,
            claim_ids=self.claim_ids,
            estimated_tokens=self.estimated_tokens,
            path=self.path,
            chronology_index=self.chronology_index,
            temporal_anchor=self.temporal_anchor,
            chapter_id=self.chapter_id,
            chapter_ordinal=self.chapter_ordinal,
            occurrence_id=self.occurrence_id,
            call_site_id=self.call_site_id,
            loop_id=self.loop_id,
            available=self.available,
            expected_leaf_count=self.expected_leaf_count,
            covered_leaf_count=(self.covered_leaf_count if self.available else 0),
            contains_structured_alternatives=(
                False if self.runtime is None else self.runtime.contains_structured_alternatives
            ),
            structure_manifest_id=(
                None if self.runtime is None else self.runtime.structure_manifest_id
            ),
        )

    def segment_child(self) -> SegmentChild:
        if self.segment_context is None:
            raise ValueError("segment candidates require exact structural context")
        return SegmentChild(
            artifact_id=self.artifact_id,
            chronology_index=self.chronology_index,
            estimated_tokens=self.estimated_tokens,
            context=self.segment_context,
            available=self.available,
            expected_leaf_count=self.expected_leaf_count,
            covered_leaf_count=(self.covered_leaf_count if self.available else 0),
        )


@dataclass(frozen=True)
class _ExecutedLevel:
    scheduler: SchedulerRunResult
    candidates: tuple[_ArtifactCandidate, ...]


def run_complete_narrative(
    project: Project,
    provider: NarrativeProvider,
    prepared: PreparedNarrativeRun,
    consent: ConsentManifest,
    *,
    policy: SchedulerPolicy,
    segment_config: SegmentPartitionConfig | None = None,
    hierarchy_config: HierarchyPartitionConfig | None = None,
    pricing: ProviderPricing | None = None,
    include_characters: bool = True,
    cancelled: CancelledCallback = lambda: False,
) -> NarrativePipelineResult:
    """Run the consented scope automatically until completion, cancellation, or a hard limit."""

    if not consent.consent_granted:
        raise ValueError("complete narrative execution requires explicit cloud consent")
    if replace(consent, consent_granted=False) != prepared.consent_preview:
        raise ValueError("complete narrative consent differs from its exact preparation")
    locale = prepared.scene_run.jobs[0].job.spec.locale
    perspective = prepared.scene_run.jobs[0].job.spec.perspective
    segment_config = segment_config or SegmentPartitionConfig(locale, perspective)
    hierarchy_config = hierarchy_config or HierarchyPartitionConfig(locale, perspective)
    if (
        segment_config.locale != locale
        or segment_config.perspective != perspective
        or hierarchy_config.locale != locale
        or hierarchy_config.perspective != perspective
    ):
        raise ValueError("hierarchy configuration differs from the consented narrative scope")

    selected_scene_ids = tuple(item.job.spec.owner_id for item in prepared.scene_run.jobs)
    placements = project_scene_placements(
        prepared.authority.scene_model,
        selected_scene_ids,
        character_ids_by_scene=_prepared_character_ids(prepared),
    )
    placement_by_scene = {item.scene_id: item for item in placements}
    scope_id = consent.selected_scope_ids[0]
    phases: list[SchedulerRunResult] = []
    unresolved: list[str] = []
    all_segment_ids: list[str] = []

    scene_run = run_prepared_scene_jobs(
        project,
        provider,
        prepared,
        consent,
        policy=policy,
        cancelled=cancelled,
    )
    phases.append(scene_run)
    usage = scene_run.record.usage
    scene_candidates = _scene_candidates(
        project,
        prepared,
        scene_run,
        placement_by_scene,
    )
    scene_artifact_ids = tuple(item.artifact_id for item in scene_candidates if item.available)
    if _terminal_phase(scene_run.record, cancelled):
        return _finish_pipeline(
            project,
            consent,
            phases,
            PipelineArtifactSet(scene_artifact_ids=scene_artifact_ids),
            ("scene_phase_stopped",),
        )

    segment_roots, segment_phases, accepted_segment_ids, usage = _reduce_scenes_to_segments(
        project,
        provider,
        prepared,
        consent,
        scene_candidates,
        policy=policy,
        config=segment_config,
        pricing=pricing,
        scope_id=scope_id,
        initial_usage=usage,
        cancelled=cancelled,
    )
    phases.extend(segment_phases)
    all_segment_ids.extend(accepted_segment_ids)
    if any(_terminal_phase(item.record, cancelled) for item in segment_phases):
        return _finish_pipeline(
            project,
            consent,
            phases,
            PipelineArtifactSet(
                scene_artifact_ids=scene_artifact_ids,
                segment_artifact_ids=tuple(dict.fromkeys(all_segment_ids)),
            ),
            ("segment_phase_stopped",),
        )

    chapter_plan = plan_chapter_jobs(
        tuple(item.hierarchy_input() for item in segment_roots),
        hierarchy_config,
    )
    if chapter_plan.reductions:
        unresolved.append("chapter_reduction_required")
    chapter_level = _execute_descriptors(
        project,
        provider,
        prepared,
        consent,
        chapter_plan.jobs,
        {item.artifact_id: item for item in segment_roots},
        policy=policy,
        scope_id=scope_id,
        initial_usage=usage,
        pricing=pricing,
        cancelled=cancelled,
        title=lambda descriptor: _chapter_title(prepared, descriptor),
        summary=lambda _descriptor: "Chapter summary unavailable.",
    )
    chapter_candidates: tuple[_ArtifactCandidate, ...] = ()
    if chapter_level is not None:
        phases.append(chapter_level.scheduler)
        usage = chapter_level.scheduler.record.usage
        chapter_candidates = chapter_level.candidates
    if chapter_level is not None and _terminal_phase(chapter_level.scheduler.record, cancelled):
        return _finish_pipeline(
            project,
            consent,
            phases,
            PipelineArtifactSet(
                scene_artifact_ids,
                tuple(dict.fromkeys(all_segment_ids)),
                tuple(item.artifact_id for item in chapter_candidates if item.available),
            ),
            tuple((*unresolved, "chapter_phase_stopped")),
        )

    shared_chapters = tuple(
        item
        for item in chapter_candidates
        if item.path.route_id is None
        and item.path.section
        in {StorySection.COMMON, StorySection.TEMPORARY_BRANCH, StorySection.UNRESOLVED}
    )
    common_candidate: _ArtifactCandidate | None = None
    if shared_chapters:
        common_plan = plan_common_story_job(
            tuple(item.hierarchy_input() for item in shared_chapters),
            hierarchy_config,
        )
        if common_plan.reductions:
            unresolved.append("common_story_reduction_required")
        common_level = _execute_descriptors(
            project,
            provider,
            prepared,
            consent,
            common_plan.jobs,
            {item.artifact_id: item for item in shared_chapters},
            policy=policy,
            scope_id=scope_id,
            initial_usage=usage,
            pricing=pricing,
            cancelled=cancelled,
            title=lambda _descriptor: "Shared story",
            summary=lambda _descriptor: "Shared-story summary unavailable.",
        )
        if common_level is not None:
            phases.append(common_level.scheduler)
            usage = common_level.scheduler.record.usage
            common_candidate = common_level.candidates[0]
    else:
        unresolved.append("common_story_missing")
    if common_candidate is None or not common_candidate.available:
        unresolved.append("common_story_unavailable")
        return _finish_pipeline(
            project,
            consent,
            phases,
            PipelineArtifactSet(
                scene_artifact_ids,
                tuple(dict.fromkeys(all_segment_ids)),
                tuple(item.artifact_id for item in chapter_candidates if item.available),
            ),
            tuple(dict.fromkeys(unresolved)),
        )

    selected_route_ids = {
        item.path.route_id for item in placements if item.path.route_id is not None
    }
    route_specs = _route_specs(prepared.authority.scene_model, selected_route_ids)
    m12_leaves = _m12_leaves(
        prepared.authority.m12_results,
        route_specs,
        locale=locale,
        perspective=perspective,
    )
    for leaves in m12_leaves.values():
        for leaf in leaves:
            persist_m12_authority_leaf(project, prepared.authority, leaf)

    route_descriptors: list[HierarchyJobDescriptor] = []
    route_children: dict[str, _ArtifactCandidate] = {common_candidate.artifact_id: common_candidate}
    for route in route_specs:
        route_chapter_children = tuple(
            item
            for item in chapter_candidates
            if item.path.route_id == route.route_id
            and item.path.section
            in {
                StorySection.PERSISTENT_ROUTE,
                StorySection.TEMPORARY_BRANCH,
                StorySection.UNRESOLVED,
            }
        )
        plan = plan_persistent_route_job(
            route,
            common_candidate.hierarchy_input(),
            tuple(item.hierarchy_input() for item in route_chapter_children),
            hierarchy_config,
            m12_authority_leaves=m12_leaves.get(route.route_id, ()),
        )
        if plan.reductions:
            unresolved.append("route_reduction_required")
            continue
        route_descriptors.extend(plan.jobs)
        route_children.update({item.artifact_id: item for item in route_chapter_children})
    route_level = _execute_descriptors(
        project,
        provider,
        prepared,
        consent,
        tuple(route_descriptors),
        route_children,
        policy=policy,
        scope_id=scope_id,
        initial_usage=usage,
        pricing=pricing,
        cancelled=cancelled,
        title=lambda descriptor: _route_title(route_specs, descriptor),
        summary=lambda _descriptor: "Persistent-route summary unavailable.",
        authority_claims={
            claim.claim_id: claim
            for leaves in m12_leaves.values()
            for leaf in leaves
            for claim in leaf.claims
        },
    )
    route_candidates: tuple[_ArtifactCandidate, ...] = ()
    if route_level is not None:
        phases.append(route_level.scheduler)
        usage = route_level.scheduler.record.usage
        route_candidates = route_level.candidates
    route_by_id = {
        item.path.route_id: item
        for item in route_candidates
        if item.path.route_id is not None and item.available
    }

    ending_groups: dict[tuple[str | None, str], list[_ArtifactCandidate]] = defaultdict(list)
    for item in chapter_candidates:
        if item.path.section is StorySection.ENDING and item.path.ending_id is not None:
            ending_groups[(item.path.route_id, item.path.ending_id)].append(item)
    ending_descriptors: list[HierarchyJobDescriptor] = []
    ending_children: dict[str, _ArtifactCandidate] = {}
    ending_specs: list[EndingSpec] = []
    for ordinal, ((route_id, ending_id), ending_members) in enumerate(
        sorted(
            ending_groups.items(),
            key=lambda item: (item[0][0] or "", item[0][1]),
        )
    ):
        lane_id = None if route_id is None else route_id
        spec = EndingSpec(
            ending_id,
            ordinal,
            _ending_title(prepared, ending_members),
            route_id,
            lane_id,
        )
        route_candidate = None if route_id is None else route_by_id.get(route_id)
        if route_id is not None and route_candidate is None:
            unresolved.append("ending_route_unavailable")
            continue
        plan = plan_ending_job(
            spec,
            tuple(item.hierarchy_input() for item in ending_members),
            hierarchy_config,
            route_artifact=(None if route_candidate is None else route_candidate.hierarchy_input()),
            m12_authority_leaves=(
                () if route_id is None else m12_leaves.get(route_id, ())
            ),
        )
        if plan.reductions:
            unresolved.append("ending_reduction_required")
            continue
        ending_specs.append(spec)
        ending_descriptors.extend(plan.jobs)
        ending_children.update({item.artifact_id: item for item in ending_members})
        if route_candidate is not None:
            ending_children[route_candidate.artifact_id] = route_candidate
    ending_level = _execute_descriptors(
        project,
        provider,
        prepared,
        consent,
        tuple(ending_descriptors),
        ending_children,
        policy=policy,
        scope_id=scope_id,
        initial_usage=usage,
        pricing=pricing,
        cancelled=cancelled,
        title=lambda descriptor: _planned_ending_title(ending_specs, descriptor),
        summary=lambda _descriptor: "Ending summary unavailable.",
        authority_claims={
            claim.claim_id: claim
            for leaves in m12_leaves.values()
            for leaf in leaves
            for claim in leaf.claims
        },
    )
    ending_candidates: tuple[_ArtifactCandidate, ...] = ()
    if ending_level is not None:
        phases.append(ending_level.scheduler)
        usage = ending_level.scheduler.record.usage
        ending_candidates = ending_level.candidates

    plot_candidate: _ArtifactCandidate | None = None
    accepted_routes = tuple(item for item in route_candidates if item.available)
    accepted_endings = tuple(item for item in ending_candidates if item.available)
    unresolved_inputs = _unresolved_plot_inputs(
        (*segment_roots, *chapter_candidates, *route_candidates, *ending_candidates),
        common_candidate,
    )
    plot_plan = plan_plot_job(
        common_candidate.hierarchy_input(),
        tuple(item.hierarchy_input() for item in accepted_routes),
        tuple(item.hierarchy_input() for item in accepted_endings),
        tuple(item.hierarchy_input() for item in unresolved_inputs),
        hierarchy_config,
    )
    if plot_plan.reductions:
        unresolved.append("plot_reduction_required")
    else:
        plot_children = {
            item.artifact_id: item
            for item in (
                common_candidate,
                *accepted_routes,
                *accepted_endings,
                *unresolved_inputs,
            )
        }
        plot_level = _execute_descriptors(
            project,
            provider,
            prepared,
            consent,
            plot_plan.jobs,
            plot_children,
            policy=policy,
            scope_id=scope_id,
            initial_usage=usage,
            pricing=pricing,
            cancelled=cancelled,
            title=lambda _descriptor: "Whole plot",
            summary=lambda _descriptor: "Whole-plot summary unavailable.",
        )
        if plot_level is not None:
            phases.append(plot_level.scheduler)
            usage = plot_level.scheduler.record.usage
            plot_candidate = plot_level.candidates[0]

    character_candidates: tuple[_ArtifactCandidate, ...] = ()
    if include_characters and not cancelled():
        character_descriptors, character_children = _character_plans(
            placements,
            common_candidate,
            route_candidates,
            ending_candidates,
            hierarchy_config,
        )
        if character_descriptors:
            character_level = _execute_descriptors(
                project,
                provider,
                prepared,
                consent,
                character_descriptors,
                character_children,
                policy=policy,
                scope_id=scope_id,
                initial_usage=usage,
                pricing=pricing,
                cancelled=cancelled,
                title=lambda descriptor: _character_title(descriptor),
                summary=lambda _descriptor: "Character participation summary unavailable.",
            )
            if character_level is not None:
                phases.append(character_level.scheduler)
                character_candidates = character_level.candidates

    artifacts = PipelineArtifactSet(
        scene_artifact_ids=scene_artifact_ids,
        segment_artifact_ids=tuple(dict.fromkeys(all_segment_ids)),
        chapter_artifact_ids=tuple(
            item.artifact_id for item in chapter_candidates if item.available
        ),
        common_story_artifact_id=common_candidate.artifact_id,
        route_artifact_ids=tuple(item.artifact_id for item in route_candidates if item.available),
        ending_artifact_ids=tuple(item.artifact_id for item in ending_candidates if item.available),
        plot_artifact_id=(
            None
            if plot_candidate is None or not plot_candidate.available
            else plot_candidate.artifact_id
        ),
        character_artifact_ids=tuple(
            item.artifact_id for item in character_candidates if item.available
        ),
    )
    return _finish_pipeline(
        project,
        consent,
        phases,
        artifacts,
        tuple(dict.fromkeys(unresolved)),
    )


def _prepared_character_ids(
    prepared: PreparedNarrativeRun,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for item in prepared.scene_run.jobs:
        context = item.payload.get("structural_context")
        if not isinstance(context, Mapping):
            raise ValueError("prepared scene structural context is malformed")
        participation = context.get("m13_character_participation")
        if (
            not isinstance(participation, Mapping)
            or participation.get("version") != M13_CHARACTER_PARTICIPATION_VERSION
        ):
            raise ValueError("prepared scene character participation is missing or stale")
        result[item.job.spec.owner_id] = _string_tuple(
            participation.get("character_ids"),
            "prepared character IDs",
        )
    return result


def project_scene_placements(
    scene_model: Mapping[str, object],
    selected_scene_ids: Sequence[str] | None = None,
    *,
    character_ids_by_scene: Mapping[str, Sequence[str]] | None = None,
) -> tuple[ScenePlacement, ...]:
    """Derive route-safe M13 organization from M11 records without mutating membership."""

    scenes = _records(scene_model, "scenes")
    atoms = _index(_records(scene_model, "atoms"), "M11 atom")
    chapters = _index(_records(scene_model, "chapters"), "M11 chapter")
    lanes = _index(_records(scene_model, "lanes"), "M11 lane")
    occurrences = _index(_records(scene_model, "occurrences"), "M11 occurrence")
    branches = _records(scene_model, "temporary_branches")
    selected = None if selected_scene_ids is None else set(selected_scene_ids)
    known_scene_ids = {_text(item, "id") for item in scenes}
    if selected is not None and (not selected or selected - known_scene_ids):
        raise ValueError("M13 placement scope contains an unknown M11 scene")
    projected_characters: dict[str, tuple[str, ...]] = {}
    for scene_id, values in (character_ids_by_scene or {}).items():
        if scene_id not in known_scene_ids:
            raise ValueError("M13 character participation owns an unknown M11 scene")
        normalized = tuple(values)
        if (
            len(normalized) != len(set(normalized))
            or any(not isinstance(item, str) or not item.strip() for item in normalized)
        ):
            raise ValueError("M13 character participation IDs are malformed")
        projected_characters[scene_id] = normalized
    branch_membership = _temporary_membership(branches)
    ordered = sorted(
        (item for item in scenes if selected is None or _text(item, "id") in selected),
        key=lambda item: (
            _integer(_known(chapters, _text(item, "chapter_id")), "ordinal"),
            _integer(item, "ordinal"),
            _text(item, "lane_id"),
            _text(item, "id"),
        ),
    )
    provisional: list[
        tuple[Mapping[str, object], HierarchyPathContext, str | None, str | None]
    ] = []
    for scene in ordered:
        scene_id = _text(scene, "id")
        lane_id = _text(scene, "lane_id")
        lane = _known(lanes, lane_id)
        ancestry = _lane_ancestry(lane_id, lanes)
        route_lane = next(
            (
                item
                for item in reversed(ancestry)
                if _text(_known(lanes, item), "kind")
                in {LaneKind.PERSISTENT_ROUTE.value, LaneKind.TERMINAL_SPLIT.value}
            ),
            None,
        )
        root_lane = ancestry[0]
        terminal_atoms = tuple(
            atom_id
            for atom_id in _string_tuple(scene.get("atom_ids"), "scene atom IDs")
            if _known(atoms, atom_id).get("kind") == "terminal"
        )
        lane_kind = _text(lane, "kind")
        temporary = branch_membership.get(scene_id)
        if lane_kind == LaneKind.TERMINAL_SPLIT.value:
            path = HierarchyPathContext(
                StorySection.ENDING,
                persistent_lane_id=lane_id,
                route_id=lane_id,
                ending_id=lane_id,
            )
        elif terminal_atoms:
            ending_id = (
                terminal_atoms[0]
                if len(terminal_atoms) == 1
                else ("terminal-set:" + canonical_hash({"atom_ids": terminal_atoms})[:24])
            )
            path = HierarchyPathContext(
                StorySection.ENDING,
                persistent_lane_id=route_lane,
                route_id=route_lane,
                ending_id=ending_id,
            )
        elif temporary is not None:
            path = HierarchyPathContext(
                StorySection.TEMPORARY_BRANCH,
                persistent_lane_id=route_lane or root_lane,
                route_id=route_lane,
                temporary_container_id=temporary[0],
                temporary_arm_id=temporary[1],
                rejoin_anchor_id=temporary[2],
            )
        elif route_lane is not None:
            path = HierarchyPathContext(
                StorySection.PERSISTENT_ROUTE,
                persistent_lane_id=route_lane,
                route_id=route_lane,
            )
        else:
            path = HierarchyPathContext(
                StorySection.COMMON,
                persistent_lane_id=root_lane,
            )
        occurrence_ids = _string_tuple(scene.get("occurrence_ids"), "occurrence IDs")
        occurrence_id = _composite_identity("occurrence-set", occurrence_ids)
        call_ids = tuple(
            _text(_known(occurrences, occurrence), "call_atom_id") for occurrence in occurrence_ids
        )
        call_id = _composite_identity("call-set", call_ids)
        provisional.append((scene, path, occurrence_id, call_id))

    result: list[ScenePlacement] = []
    prior_key: object = None
    anchor = ""
    for scene, path, occurrence_id, call_id in provisional:
        chapter_id = _text(scene, "chapter_id")
        chapter = _known(chapters, chapter_id)
        scene_id = _text(scene, "id")
        lane_id = _text(scene, "lane_id")
        loop_id = _optional_text(scene.get("loop_hub_id"))
        structural_key = (
            chapter_id,
            lane_id,
            path.identity,
            occurrence_id,
            call_id,
            loop_id,
        )
        if structural_key != prior_key:
            anchor = f"chronology:{scene_id}"
            prior_key = structural_key
        segment_context = SegmentStructuralContext(
            chapter_id=chapter_id,
            chronology_anchor_id=anchor,
            persistent_lane_id=lane_id,
            temporary_container_id=path.temporary_container_id,
            temporary_arm_id=path.temporary_arm_id,
            occurrence_id=occurrence_id,
            call_context_id=call_id,
            loop_id=loop_id,
        )
        m11_speakers = tuple(
            speaker
            for atom_id in _string_tuple(scene.get("atom_ids"), "scene atom IDs")
            if (speaker := _optional_text(_known(atoms, atom_id).get("speaker"))) is not None
        )
        speakers = tuple(
            dict.fromkeys((*m11_speakers, *projected_characters.get(scene_id, ())))
        )
        result.append(
            ScenePlacement(
                scene_id,
                _text(scene, "title"),
                chapter_id,
                _integer(chapter, "ordinal"),
                _integer(scene, "ordinal"),
                lane_id,
                path,
                segment_context,
                speakers,
            )
        )
    return tuple(result)


def _scene_candidates(
    project: Project,
    prepared: PreparedNarrativeRun,
    run: SchedulerRunResult,
    placements: Mapping[str, ScenePlacement],
) -> tuple[_ArtifactCandidate, ...]:
    by_job = {item.job.spec.job_id: item for item in prepared.scene_run.jobs}
    candidates: list[_ArtifactCandidate] = []
    for record in run.jobs:
        scene_job = by_job[record.logical_job_id]
        placement = placements[scene_job.job.spec.owner_id]
        runtime: RuntimeNarrativeArtifact | None = None
        artifact_id = _expected_artifact_id(record.logical_job_id, record.input_revision_id)
        if record.artifact_id is not None:
            lookup = project.m13_persistence().lookup(
                RecordKind.ARTIFACT,
                record.artifact_id,
                authority_binding=prepared.authority.binding.to_dict(),
            )
            if lookup.state is not LookupState.HIT or lookup.payload is None:
                raise ValueError("published scene artifact is not durably readable")
            artifact_id = record.artifact_id
            payload = lookup.payload
            claim_ids = _artifact_claim_ids(payload)
            runtime = RuntimeNarrativeArtifact(
                artifact_id,
                record.logical_job_id,
                payload,
                claim_ids,
                _artifact_tokens(payload),
                placement.path,
                placement.scene_ordinal,
                placement.segment_context.chronology_anchor_id,
                chapter_id=placement.chapter_id,
                chapter_ordinal=placement.chapter_ordinal,
                occurrence_id=placement.segment_context.occurrence_id,
                call_site_id=placement.segment_context.call_context_id,
                loop_id=placement.segment_context.loop_id,
            )
        candidates.append(
            _ArtifactCandidate(
                artifact_id,
                LogicalJobKind.SCENE,
                placement.path,
                placement.scene_ordinal,
                placement.segment_context.chronology_anchor_id,
                placement.chapter_id,
                placement.chapter_ordinal,
                placement.segment_context.occurrence_id,
                placement.segment_context.call_context_id,
                placement.segment_context.loop_id,
                1,
                1 if runtime is not None else 0,
                scene_job.estimated_output_tokens if runtime is None else runtime.estimated_tokens,
                runtime,
                placement.segment_context,
            )
        )
    return tuple(sorted(candidates, key=_candidate_order))


def _reduce_scenes_to_segments(
    project: Project,
    provider: NarrativeProvider,
    prepared_run: PreparedNarrativeRun,
    consent: ConsentManifest,
    scenes: tuple[_ArtifactCandidate, ...],
    *,
    policy: SchedulerPolicy,
    config: SegmentPartitionConfig,
    pricing: ProviderPricing | None,
    scope_id: str,
    initial_usage: SchedulerUsage,
    cancelled: CancelledCallback,
) -> tuple[
    tuple[_ArtifactCandidate, ...],
    tuple[SchedulerRunResult, ...],
    tuple[str, ...],
    SchedulerUsage,
]:
    contexts: dict[SegmentStructuralContext, list[_ArtifactCandidate]] = defaultdict(list)
    for item in scenes:
        if item.segment_context is None:
            raise ValueError("scene candidate lost its M11 segment context")
        contexts[item.segment_context].append(item)
    pending = {key: tuple(value) for key, value in contexts.items()}
    roots: list[_ArtifactCandidate] = []
    phases: list[SchedulerRunResult] = []
    accepted_ids: list[str] = []
    usage = initial_usage
    first_level = True
    while pending:
        descriptors: list[SegmentDescriptor] = []
        child_index: dict[str, _ArtifactCandidate] = {}
        next_pending_contexts: set[SegmentStructuralContext] = set()
        for context, children in sorted(
            pending.items(), key=lambda item: min(child.chronology_index for child in item[1])
        ):
            requires = first_level or _segment_reduction_required(children, config)
            if not requires:
                roots.extend(children)
                continue
            plan = plan_summary_segments(
                tuple(child.segment_child() for child in children),
                config,
            )
            planned_descriptors = tuple(item for item in plan.descriptors if item.level == 0)
            if not planned_descriptors:
                raise ValueError("segment planner produced no first reduction level")
            descriptors.extend(planned_descriptors)
            child_index.update({child.artifact_id: child for child in children})
            next_pending_contexts.add(context)
        if not descriptors:
            break
        hierarchy_descriptors = tuple(
            _segment_hierarchy_descriptor(item, child_index)
            for item in sorted(
                descriptors,
                key=lambda value: (
                    value.context.chronology_anchor_id,
                    value.ordinal,
                    value.segment_id,
                ),
            )
        )
        executed = _execute_descriptors(
            project,
            provider,
            prepared_run,
            consent,
            hierarchy_descriptors,
            child_index,
            policy=policy,
            scope_id=scope_id,
            initial_usage=usage,
            pricing=pricing,
            cancelled=cancelled,
            title=lambda _descriptor: "Internal summary segment",
            summary=lambda _descriptor: "Bounded internal summary unavailable.",
        )
        if executed is None:
            break
        phases.append(executed.scheduler)
        usage = executed.scheduler.record.usage
        accepted_ids.extend(item.artifact_id for item in executed.candidates if item.available)
        by_context: dict[SegmentStructuralContext, list[_ArtifactCandidate]] = defaultdict(list)
        for item in executed.candidates:
            if item.segment_context is None:
                raise ValueError("segment result lost deterministic structural context")
            by_context[item.segment_context].append(item)
        pending = {
            context: tuple(sorted(by_context[context], key=_candidate_order))
            for context in next_pending_contexts
        }
        first_level = False
        if _terminal_phase(executed.scheduler.record, cancelled):
            roots.extend(item for values in pending.values() for item in values)
            break
    return (
        tuple(sorted(roots, key=_candidate_order)),
        tuple(phases),
        tuple(accepted_ids),
        usage,
    )


def _segment_hierarchy_descriptor(
    segment: SegmentDescriptor,
    children: Mapping[str, _ArtifactCandidate],
) -> HierarchyJobDescriptor:
    ordered = tuple(children[item] for item in segment.child_artifact_ids)
    if any(item.segment_context != segment.context for item in ordered):
        raise ValueError("segment descriptor crossed a deterministic M11 boundary")
    path = ordered[0].path
    if any(item.path != path for item in ordered):
        raise ValueError("segment descriptor crossed route or temporary-arm ownership")
    entries = tuple(
        HierarchySectionEntry(
            artifact_id=item.artifact_id,
            job_kind=item.job_kind,
            path=item.path,
            chapter_id=item.chapter_id,
            chapter_ordinal=item.chapter_ordinal,
            chronology_index=item.chronology_index,
            temporal_anchor=item.temporal_anchor,
            available=item.available,
            contains_structured_alternatives=(
                False if item.runtime is None else item.runtime.contains_structured_alternatives
            ),
            structure_manifest_id=(
                None if item.runtime is None else item.runtime.structure_manifest_id
            ),
        )
        for item in ordered
    )
    context = segment.context
    spec = LogicalJobSpec(
        kind=LogicalJobKind.SUMMARY_SEGMENT,
        owner_id=segment.segment_id,
        context=StructuralContext(
            chapter_id=context.chapter_id,
            lane_id=context.persistent_lane_id,
            route_id=path.route_id,
            temporary_container_id=context.temporary_container_id,
            temporary_arm_id=context.temporary_arm_id,
            occurrence_id=context.occurrence_id,
            call_site_id=context.call_context_id,
            loop_id=context.loop_id,
            temporal_anchor=context.chronology_anchor_id,
            structural_fingerprint=canonical_hash(
                {
                    "segment_id": segment.segment_id,
                    "context": context.identity_fields(),
                    "partition_version": segment.partition_version,
                }
            ),
        ),
        ordered_child_artifact_ids=segment.child_artifact_ids,
        locale=segment.locale,
        perspective=segment.perspective,
        partition_version=segment.partition_version,
    )
    return HierarchyJobDescriptor(
        spec,
        path,
        ChronologyPolicy.LINEAR,
        entries,
        tuple(claim_id for item in ordered if item.available for claim_id in item.claim_ids),
        (),
        (),
        segment.estimated_input_tokens,
        segment.expected_leaf_count,
        segment.covered_leaf_count,
        chapter_ordinal=ordered[0].chapter_ordinal,
        chronology_index=min(item.chronology_index for item in ordered),
    )


def _execute_descriptors(
    project: Project,
    provider: NarrativeProvider,
    prepared_run: PreparedNarrativeRun,
    consent: ConsentManifest,
    descriptors: Sequence[HierarchyJobDescriptor],
    children: Mapping[str, _ArtifactCandidate],
    *,
    policy: SchedulerPolicy,
    scope_id: str,
    initial_usage: SchedulerUsage,
    pricing: ProviderPricing | None,
    cancelled: CancelledCallback,
    title: Callable[[HierarchyJobDescriptor], str],
    summary: Callable[[HierarchyJobDescriptor], str],
    authority_claims: Mapping[str, NarrativeClaim] | None = None,
) -> _ExecutedLevel | None:
    if not descriptors:
        return None
    runtime_children: dict[str, RuntimeNarrativeArtifact] = {}
    for item_id, candidate in children.items():
        if candidate.runtime is not None:
            runtime_children[item_id] = candidate.runtime
    accepted_authority = {} if authority_claims is None else dict(authority_claims)
    prepared: list[PreparedHierarchyJob] = []
    for ordinal, descriptor in enumerate(descriptors):
        allowed_authority = {
            claim_id: accepted_authority[claim_id]
            for claim_id in descriptor.authority_leaf_claim_ids
        }
        prepared.append(
            prepare_hierarchy_job(
                descriptor,
                runtime_children,
                prepared_run.authority,
                scope_id=scope_id,
                ordinal=ordinal,
                deterministic_title=title(descriptor),
                deterministic_summary=summary(descriptor),
                authority_claims=allowed_authority,
            )
        )
    result = execute_hierarchy_jobs(
        project,
        provider,
        tuple(prepared),
        consent,
        policy=policy,
        initial_usage=initial_usage,
        pricing=pricing,
        cancelled=cancelled,
    )
    runtime_by_job = {item.logical_job_id: item for item in result.artifacts}
    record_by_job = {item.logical_job_id: item for item in result.scheduler.jobs}
    candidates: list[_ArtifactCandidate] = []
    for item in prepared:
        descriptor = item.descriptor
        runtime = runtime_by_job.get(descriptor.job_id)
        record = record_by_job[descriptor.job_id]
        artifact_id = (
            runtime.artifact_id
            if runtime is not None
            else _expected_artifact_id(descriptor.job_id, record.input_revision_id)
        )
        segment_context = None
        if descriptor.spec.kind is LogicalJobKind.SUMMARY_SEGMENT:
            context = descriptor.spec.context
            if context.chapter_id is None or context.temporal_anchor is None:
                raise ValueError("summary segment lost its deterministic context")
            segment_context = SegmentStructuralContext(
                context.chapter_id,
                context.temporal_anchor,
                context.lane_id,
                context.temporary_container_id,
                context.temporary_arm_id,
                context.occurrence_id,
                context.call_site_id,
                context.loop_id,
            )
        candidates.append(
            _ArtifactCandidate(
                artifact_id,
                descriptor.spec.kind,
                descriptor.path,
                descriptor.chronology_index,
                descriptor.spec.context.temporal_anchor or descriptor.spec.owner_id,
                descriptor.spec.context.chapter_id,
                descriptor.chapter_ordinal,
                descriptor.spec.context.occurrence_id,
                descriptor.spec.context.call_site_id,
                descriptor.spec.context.loop_id,
                descriptor.expected_leaf_count,
                descriptor.covered_leaf_count if runtime is not None else 0,
                (item.estimated_output_tokens if runtime is None else runtime.estimated_tokens),
                runtime,
                segment_context,
            )
        )
    return _ExecutedLevel(result.scheduler, tuple(candidates))


def _m12_leaves(
    results: Sequence[Mapping[str, object]],
    routes: Sequence[PersistentRouteSpec],
    *,
    locale: str,
    perspective: str,
) -> dict[str, tuple[M12AuthorityLeaf, ...]]:
    route_ids = {item.route_id for item in routes}
    selected: dict[str, list[M12AuthorityLeaf]] = defaultdict(list)
    for result in results:
        result_identity = _text(result, "request_identity")
        status = TechnicalStatus(_text(result, "status"))
        badge = RouteBadge(_text(result, "badge"))
        route_records = tuple(
            item
            for key in ("recommended", "alternatives")
            for item in _route_result_records(result.get(key), key)
        )
        for route_id in sorted(route_ids):
            relevant = tuple(
                item
                for item in route_records
                if route_id
                in _string_tuple(
                    item.get("persistent_lane_ids"),
                    "M12 persistent lane IDs",
                )
            )
            if not relevant:
                continue
            prerequisites = _exact_m12_texts(
                relevant,
                ("requirements", "persistent_commitment_claims", "uncertainty_warnings"),
            )
            diagnostics = result.get("diagnostics", [])
            if not isinstance(diagnostics, list):
                raise ValueError("M12 diagnostics must be an array")
            conclusions = tuple(
                dict.fromkeys(
                    (
                        *(
                            (str(result["termination_reason"]),)
                            if isinstance(result.get("termination_reason"), str)
                            else ()
                        ),
                        *tuple(
                            item for item in diagnostics if isinstance(item, str) and item.strip()
                        ),
                    )
                )
            )
            authority = M12RouteAuthority(
                result_identity,
                route_id,
                route_id,
                status,
                badge,
                prerequisites,
                conclusions,
            )
            selected[route_id].append(
                make_m12_authority_leaf(
                    authority,
                    locale=locale,
                    perspective=perspective,
                )
            )
    grouped: dict[str, tuple[M12AuthorityLeaf, ...]] = {}
    for route_id, leaves in selected.items():
        ordered = tuple(sorted(leaves, key=lambda item: item.authority.result_identity))
        if len(ordered) > 32:
            raise ValueError("A route cannot bind more than 32 current M12 results.")
        grouped[route_id] = ordered
    return grouped


def _route_result_records(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if label == "recommended":
        return (value,) if isinstance(value, Mapping) else ()
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"M12 {label} records are malformed")
    return tuple(cast(Mapping[str, object], item) for item in value)


def _exact_m12_texts(
    records: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> tuple[str, ...]:
    texts: list[str] = []
    for record in records:
        for field in fields:
            raw = record.get(field, [])
            if not isinstance(raw, list):
                raise ValueError(f"M12 {field} must be an array")
            for item in raw:
                if isinstance(item, str):
                    text = item
                elif isinstance(item, Mapping):
                    value = item.get("text")
                    text = value if isinstance(value, str) else ""
                else:
                    text = ""
                if text.strip() and text not in texts:
                    texts.append(text)
    return tuple(texts)


def _route_specs(
    scene_model: Mapping[str, object],
    selected_route_ids: set[str] | None = None,
) -> tuple[PersistentRouteSpec, ...]:
    lanes = _records(scene_model, "lanes")
    routes = [
        item
        for item in lanes
        if item.get("kind") in {LaneKind.PERSISTENT_ROUTE.value, LaneKind.TERMINAL_SPLIT.value}
        and (selected_route_ids is None or _text(item, "id") in selected_route_ids)
    ]
    routes.sort(key=lambda item: (_integer(item, "arm_ordinal", default=0), _text(item, "id")))
    return tuple(
        PersistentRouteSpec(
            route_id=_text(item, "id"),
            persistent_lane_id=_text(item, "id"),
            ordinal=ordinal,
            title=f"Route {ordinal + 1}",
        )
        for ordinal, item in enumerate(routes)
    )


def _character_plans(
    placements: Sequence[ScenePlacement],
    common: _ArtifactCandidate,
    routes: Sequence[_ArtifactCandidate],
    endings: Sequence[_ArtifactCandidate],
    config: HierarchyPartitionConfig,
) -> tuple[tuple[HierarchyJobDescriptor, ...], dict[str, _ArtifactCandidate]]:
    character_paths: dict[str, set[tuple[str | None, str | None]]] = defaultdict(set)
    common_characters: set[str] = set()
    for placement in placements:
        for speaker in placement.speaker_ids:
            character_paths[speaker].add((placement.path.route_id, placement.path.ending_id))
            if placement.path.route_id is None:
                common_characters.add(speaker)
    route_by_id = {item.path.route_id: item for item in routes if item.available}
    ending_by_key = {
        (item.path.route_id, item.path.ending_id): item for item in endings if item.available
    }
    descriptors: list[HierarchyJobDescriptor] = []
    children: dict[str, _ArtifactCandidate] = {}
    for character in sorted(character_paths):
        selected: list[_ArtifactCandidate] = []
        if character in common_characters:
            selected.append(common)
        for route_id, ending_id in sorted(
            character_paths[character], key=lambda item: (item[0] or "", item[1] or "")
        ):
            if route_id is not None and route_id in route_by_id:
                selected.append(route_by_id[route_id])
            if ending_id is not None and (route_id, ending_id) in ending_by_key:
                selected.append(ending_by_key[(route_id, ending_id)])
        selected = list({item.artifact_id: item for item in selected}.values())
        if not selected:
            continue
        plan = plan_character_role_job(
            character,
            tuple(item.hierarchy_input() for item in selected),
            config,
        )
        if plan.reductions:
            continue
        descriptors.extend(plan.jobs)
        children.update({item.artifact_id: item for item in selected})
    return tuple(descriptors), children


def _unresolved_plot_inputs(
    candidates: Sequence[_ArtifactCandidate],
    common: _ArtifactCandidate,
) -> tuple[_ArtifactCandidate, ...]:
    result: list[_ArtifactCandidate] = []
    seen: set[str] = set()
    for item in candidates:
        if item.available or item.artifact_id in seen:
            continue
        seen.add(item.artifact_id)
        result.append(
            replace(
                item,
                job_kind=(
                    item.job_kind
                    if item.job_kind in {LogicalJobKind.SUMMARY_SEGMENT, LogicalJobKind.CHAPTER}
                    else LogicalJobKind.SUMMARY_SEGMENT
                ),
                path=HierarchyPathContext(
                    StorySection.UNRESOLVED,
                    persistent_lane_id=common.path.persistent_lane_id,
                ),
                runtime=None,
                covered_leaf_count=0,
                segment_context=None,
            )
        )
    return tuple(sorted(result, key=_candidate_order))


def _finish_pipeline(
    project: Project,
    consent: ConsentManifest,
    phases: Sequence[SchedulerRunResult],
    artifacts: PipelineArtifactSet,
    unresolved: tuple[str, ...],
) -> NarrativePipelineResult:
    jobs = tuple(item for phase in phases for item in phase.jobs)
    if len({item.logical_job_id for item in jobs}) != len(jobs):
        raise ValueError("one M13 pipeline run repeated a logical job")
    states = Counter(item.state for item in jobs)
    usage = phases[-1].record.usage if phases else SchedulerUsage()
    hard = next(
        (phase.record for phase in phases if phase.record.state is SchedulerRunState.HARD_LIMIT),
        None,
    )
    cancelled = any(phase.record.state is SchedulerRunState.CANCELLED for phase in phases)
    accepted = states[LogicalJobState.SUCCEEDED] + states[LogicalJobState.PARTIAL]
    if hard is not None:
        state = SchedulerRunState.HARD_LIMIT
        error_code = hard.error_code
    elif cancelled:
        state = SchedulerRunState.CANCELLED
        error_code = "cancelled"
    elif unresolved or accepted < len(jobs) or states[LogicalJobState.PARTIAL]:
        state = SchedulerRunState.PARTIAL if accepted else SchedulerRunState.FAILED
        error_code = None
    else:
        state = SchedulerRunState.SUCCEEDED
        error_code = None
    record = SchedulerRunRecord(
        consent.run_id,
        consent.manifest_id,
        state,
        consent.provider,
        usage,
        states[LogicalJobState.SUCCEEDED],
        states[LogicalJobState.PARTIAL],
        states[LogicalJobState.FAILED],
        states[LogicalJobState.REFUSED],
        states[LogicalJobState.CANCELLED],
        error_code,
    )
    payload = record.to_dict()
    payload["pipeline"] = cast(
        JsonValue,
        {
            "schema": "m13-complete-pipeline-v1",
            "unresolved_codes": list(unresolved),
            "artifacts": {
                "scene_artifact_ids": list(artifacts.scene_artifact_ids),
                "segment_artifact_ids": list(artifacts.segment_artifact_ids),
                "chapter_artifact_ids": list(artifacts.chapter_artifact_ids),
                "common_story_artifact_id": artifacts.common_story_artifact_id,
                "route_artifact_ids": list(artifacts.route_artifact_ids),
                "ending_artifact_ids": list(artifacts.ending_artifact_ids),
                "plot_artifact_id": artifacts.plot_artifact_id,
                "character_artifact_ids": list(artifacts.character_artifact_ids),
            },
        },
    )
    project.m13_persistence().put_run(
        consent.run_id,
        payload,
        authority_binding=project_scene_authority_binding(project),
    )
    return NarrativePipelineResult(record, jobs, tuple(phases), artifacts, unresolved)


def project_scene_authority_binding(project: Project) -> Mapping[str, object]:
    """Late import-free binding check used by the final aggregate write."""

    from renpy_story_mapper.narrative.authority import load_narrative_authority

    return load_narrative_authority(project, include_m12=True).binding.to_dict()


def _terminal_phase(record: SchedulerRunRecord, cancelled: CancelledCallback) -> bool:
    return cancelled() or record.state in {
        SchedulerRunState.CANCELLED,
        SchedulerRunState.HARD_LIMIT,
    }


def _segment_reduction_required(
    children: Sequence[_ArtifactCandidate],
    config: SegmentPartitionConfig,
) -> bool:
    return (
        len(children) > config.maximum_children
        or config.prompt_overhead_tokens
        + sum(item.estimated_tokens for item in children if item.available)
        > config.maximum_input_tokens
    )


def _temporary_membership(
    branches: Sequence[Mapping[str, object]],
) -> dict[str, tuple[str, str, str]]:
    by_id = {_text(item, "id"): item for item in branches}

    def depth(branch_id: str) -> int:
        result = 0
        seen: set[str] = set()
        current: str | None = branch_id
        while current is not None:
            if current in seen:
                raise ValueError("M11 temporary-container ancestry contains a cycle")
            seen.add(current)
            result += 1
            current = _optional_text(_known(by_id, current).get("parent_branch_id"))
        return result

    candidates: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
    for branch in branches:
        branch_id = _text(branch, "id")
        rejoin = _optional_text(branch.get("continuation_atom_id")) or _text(
            branch,
            "merge_node_id",
        )
        for arm in _mapping_records(branch, "arms"):
            arm_id = _text(arm, "id")
            for scene_id in _string_tuple(arm.get("scene_ids"), "branch arm scene IDs"):
                candidates[scene_id].append((depth(branch_id), branch_id, arm_id, rejoin))
    result: dict[str, tuple[str, str, str]] = {}
    for scene_id, values in candidates.items():
        _depth, branch_id, arm_id, rejoin = sorted(values, reverse=True)[0]
        result[scene_id] = (branch_id, arm_id, rejoin)
    return result


def _lane_ancestry(
    lane_id: str,
    lanes: Mapping[str, Mapping[str, object]],
) -> tuple[str, ...]:
    result: list[str] = []
    current: str | None = lane_id
    seen: set[str] = set()
    while current is not None:
        if current in seen:
            raise ValueError("M11 lane ancestry contains a cycle")
        seen.add(current)
        result.append(current)
        current = _optional_text(_known(lanes, current).get("parent_lane_id"))
    result.reverse()
    return tuple(result)


def _chapter_title(
    prepared: PreparedNarrativeRun,
    descriptor: HierarchyJobDescriptor,
) -> str:
    chapter_id = descriptor.spec.context.chapter_id
    for chapter in _records(prepared.authority.scene_model, "chapters"):
        if chapter.get("id") == chapter_id:
            return _text(chapter, "label")
    return "Chapter"


def _route_title(
    routes: Sequence[PersistentRouteSpec],
    descriptor: HierarchyJobDescriptor,
) -> str:
    route_id = descriptor.path.route_id
    return next((item.title for item in routes if item.route_id == route_id), "Route")


def _ending_title(
    prepared: PreparedNarrativeRun,
    children: Sequence[_ArtifactCandidate],
) -> str:
    ending_id = children[0].path.ending_id
    for scene in _records(prepared.authority.scene_model, "scenes"):
        if scene.get("lane_id") == ending_id:
            return _text(scene, "title")
    return "Ending"


def _planned_ending_title(
    endings: Sequence[EndingSpec],
    descriptor: HierarchyJobDescriptor,
) -> str:
    ending_id = descriptor.path.ending_id
    return next((item.title for item in endings if item.ending_id == ending_id), "Ending")


def _character_title(descriptor: HierarchyJobDescriptor) -> str:
    prefix = "character-role:"
    owner = descriptor.spec.owner_id
    return owner[len(prefix) :] if owner.startswith(prefix) else "Character"


def _artifact_claim_ids(payload: Mapping[str, object]) -> tuple[str, ...]:
    raw = payload.get("claims")
    if not isinstance(raw, list):
        raise ValueError("published artifact claims are malformed")
    result: list[str] = []
    for item in raw[:MAX_PROPAGATED_CLAIMS_PER_ARTIFACT]:
        if not isinstance(item, Mapping):
            raise ValueError("published artifact claim is malformed")
        result.append(_text(item, "claim_id"))
    return tuple(result)


def _artifact_tokens(payload: Mapping[str, object]) -> int:
    return max(1, math.ceil(len(canonical_json(dict(payload))) / 4))


def _expected_artifact_id(job_id: str, input_revision_id: str) -> str:
    return "m13_expected_artifact_" + canonical_hash(
        {"logical_job_id": job_id, "input_revision_id": input_revision_id}
    )


def _candidate_order(item: _ArtifactCandidate) -> tuple[int, int, str]:
    return (
        item.chapter_ordinal if item.chapter_ordinal is not None else 1_000_000_000,
        item.chronology_index,
        item.artifact_id,
    )


def _composite_identity(prefix: str, values: tuple[str, ...]) -> str | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return f"{prefix}:{canonical_hash({'values': values})[:24]}"


def _records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    value = owner.get(key)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{key} must be an array of records")
    return tuple(cast(Mapping[str, object], item) for item in value)


def _mapping_records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    return _records(owner, key)


def _index(
    values: Sequence[Mapping[str, object]],
    label: str,
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for item in values:
        item_id = _text(item, "id")
        if item_id in result:
            raise ValueError(f"{label} IDs must be unique")
        result[item_id] = item
    return result


def _known(
    values: Mapping[str, Mapping[str, object]],
    item_id: str,
) -> Mapping[str, object]:
    try:
        return values[item_id]
    except KeyError as exc:
        raise ValueError(f"unknown authority record {item_id}") from exc


def _text(owner: Mapping[str, object], key: str) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("optional authority ID must be a non-empty string")
    return value


def _integer(
    owner: Mapping[str, object],
    key: str,
    *,
    default: int | None = None,
) -> int:
    value = owner.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{label} must be an array of non-empty strings")
    return tuple(cast(list[str], value))

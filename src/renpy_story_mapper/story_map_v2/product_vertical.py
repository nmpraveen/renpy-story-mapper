"""Thin Phase 04 product composer from an approved run to one readable generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path

from renpy_story_mapper import storage
from renpy_story_mapper.canonical_graph_contract import CanonicalGraph
from renpy_story_mapper.m11_scene_model import SceneModel
from renpy_story_mapper.story_map_v2.durable_repository import (
    GenerationDescriptor,
    GenerationPointers,
    SectionPageRecord,
    SelectionIndexRecord,
    SqliteStoryMapV2Repository,
    StoryMapV2RepositoryError,
    _validate_private_content,
)
from renpy_story_mapper.story_map_v2.phase04_publication import (
    AtomicGenerationPublisher,
    GenerationArtifact,
    GenerationKind,
    PathFact,
    PathFactKind,
    PathFactSnapshot,
    build_generation_artifact,
)
from renpy_story_mapper.story_map_v2.phase04_sections import (
    DerivedSemanticAssembly,
    DerivedSemanticJob,
    assemble_derived_semantics,
    build_derived_semantic_plan,
)
from renpy_story_mapper.story_map_v2.phase04_semantics import (
    ExactChoiceOverlay,
    SemanticAssembly,
    SemanticEvent,
    assemble_semantic_corridors,
)
from renpy_story_mapper.story_map_v2.product_workflow import (
    FrozenProductRequestMaterializer,
    PreparedProductWorkflow,
    ProductWorkflowProject,
    adapt_derived_semantic_job,
    create_product_workflow_service,
    prepare_product_workflow_from_authority,
)
from renpy_story_mapper.story_map_v2.reader import (
    BRANCH_PAGE_ENDPOINT,
    SECTION_PAGE_ENDPOINT,
)
from renpy_story_mapper.story_map_v2.reader_store import reader_storage_page
from renpy_story_mapper.story_map_v2.story_plan import StoryPlacement
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    ProviderCallKind,
    WorkflowApproval,
    WorkflowPreview,
    WorkflowStatus,
    workflow_digest,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import ProviderFactory
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)

_PAGE_ITEMS = 30
ProjectOpener = Callable[[Path], AbstractContextManager[ProductWorkflowProject]]


def execute_product_vertical(
    project_path: Path,
    prepared: PreparedProductWorkflow,
    *,
    preview_identity: str,
    cloud_factory: ProviderFactory,
    project_opener: ProjectOpener,
    authority_graph: CanonicalGraph,
) -> None:
    """Execute approved work, assemble accepted prose/fallbacks, and publish one map."""

    with project_opener(project_path) as project:
        repository = project.story_map_v2_repository()
        current = repository.generation_pointers().current_complete_generation
        published = None if current is None else repository.load_generation(current)
        if (
            published is not None
            and isinstance(published.descriptor, Mapping)
            and published.descriptor.get("workflow_run_id") == prepared.run_id
        ):
            return
        materializer = FrozenProductRequestMaterializer(prepared)
        service = create_product_workflow_service(
            project,
            prepared,
            cloud_factory=cloud_factory,
            request_materializer=materializer,
        )
        service.execute(
            prepared.run_id,
            preview_identity=preview_identity,
            authority_identity=prepared.plan.authority_identity,
        )
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        status = adapter.status(prepared.run_id)
        terminal_fallback = _terminal_indeterminate_fallback(status)
        if _execution_blocked(status) and not terminal_fallback:
            return

        semantic = _semantic_assembly(adapter, prepared)
        semantic_plan = build_derived_semantic_plan(
            prepared.frozen_plans.story_chunk_plan,
            prepared.plan.authority_identity.value,
        )
        generation_id = _generation_id("complete", prepared, semantic)
        derived = assemble_derived_semantics(semantic_plan, semantic, generation_id)
        if terminal_fallback:
            _publish_generation(
                project,
                prepared,
                semantic,
                derived,
                generation_id,
                authority_graph=authority_graph,
            )
            return

        for job in derived.section_jobs:
            _register_job(service, materializer, prepared, preview_identity, job)
        if derived.section_jobs:
            service.execute(
                prepared.run_id,
                preview_identity=preview_identity,
                authority_identity=prepared.plan.authority_identity,
            )
        status = adapter.status(prepared.run_id)
        if _execution_blocked(status):
            return

        section_payloads = _published_payloads(adapter, prepared.run_id, derived.section_jobs)
        rollup_payloads: dict[str, bytes] = {}
        rollup_slots = (
            semantic_plan.ceilings.rollup_synthesis_calls
            if len(section_payloads) == len(derived.section_jobs)
            else 0
        )
        for _ in range(rollup_slots):
            derived = assemble_derived_semantics(
                semantic_plan,
                semantic,
                generation_id,
                section_payloads=section_payloads,
                rollup_payloads=rollup_payloads,
            )
            next_job = next(
                (
                    job
                    for job in derived.rollup_jobs
                    if adapter.load_job_descriptor(prepared.run_id, job.job_id) is None
                ),
                None,
            )
            if next_job is None:
                break
            _register_job(service, materializer, prepared, preview_identity, next_job)
            service.execute(
                prepared.run_id,
                preview_identity=preview_identity,
                authority_identity=prepared.plan.authority_identity,
            )
            status = adapter.status(prepared.run_id)
            if _execution_blocked(status):
                return
            result = adapter.load_published_result(prepared.run_id, next_job.job_id)
            if result is None:
                break
            rollup_payloads[next_job.job_id] = result.normalized_payload

        derived = assemble_derived_semantics(
            semantic_plan,
            semantic,
            generation_id,
            section_payloads=section_payloads,
            rollup_payloads=rollup_payloads,
        )
        _publish_generation(
            project,
            prepared,
            semantic,
            derived,
            generation_id,
            authority_graph=authority_graph,
        )


def project_workflow_reader_status(
    repository: SqliteStoryMapV2Repository,
    generation: GenerationDescriptor,
    _pointers: GenerationPointers,
) -> Mapping[str, object]:
    """Plain provider-free status projection for the existing durable reader."""

    descriptor = generation.descriptor
    run_id = (
        descriptor.get("workflow_run_id")
        if isinstance(descriptor, Mapping)
        else None
    )
    if not isinstance(run_id, str):
        run_id = generation.run_id
    try:
        status = DurableWorkflowRepositoryAdapter(repository).status(run_id)
    except StoryMapV2RepositoryError:
        return {
            "run_id": run_id,
            "state": "unavailable",
            "coverage": {},
            "progress": {
                "completed_jobs": 0,
                "total_jobs": 0,
                "failed_jobs": 0,
                "indeterminate_jobs": 0,
            },
            "actions": {
                "can_cancel": False,
                "can_resume": False,
                "retry_approval_required": False,
            },
        }
    total = (
        status.pending_jobs
        + status.active_jobs
        + status.accepted_jobs
        + status.structural_fallback_jobs
        + status.resumable_jobs
        + status.indeterminate_jobs
    )
    finished = status.accepted_jobs + status.structural_fallback_jobs
    complete = generation.kind.value == GenerationKind.COMPLETE.value
    return {
        "run_id": status.run_id,
        "state": "complete" if complete else "building",
        "coverage": {
            "completed_chunks": finished,
            "total_chunks": total,
            "event_fraction": 1.0 if complete else (finished / total if total else 0.0),
        },
        "progress": {
            "completed_jobs": finished,
            "total_jobs": total,
            "failed_jobs": status.structural_fallback_jobs,
            "indeterminate_jobs": status.indeterminate_jobs,
        },
        "actions": {
            "can_cancel": not complete and not status.cancelled and total > finished,
            "can_resume": (
                not complete
                and status.approved
                and not status.cancelled
                and status.active_jobs == 0
                and status.resumable_jobs > 0
            ),
            "retry_approval_required": any(
                item.can_approve_retry for item in status.indeterminate_retries
            ),
        },
    }


def load_product_workflow(
    project: ProductWorkflowProject,
    run_id: str,
    *,
    authority_graph: CanonicalGraph,
    scene_model: SceneModel,
) -> tuple[PreparedProductWorkflow, WorkflowPreview, WorkflowApproval | None, WorkflowStatus]:
    """Rebuild ephemeral request bytes and verify them against one durable preview."""

    prepared = prepare_product_workflow_from_authority(
        authority_graph,
        scene_model,
        run_id=run_id,
    )
    adapter = DurableWorkflowRepositoryAdapter.from_project(project)
    preview = adapter.load_preview(run_id)
    if (
        preview.plan != prepared.plan
        or preview.policy != prepared.policy
        or preview.ceilings != prepared.ceilings
    ):
        raise ValueError("the current project authority differs from the workflow preview")
    return prepared, preview, adapter.load_approval(run_id), adapter.status(run_id)


def _execution_blocked(status: WorkflowStatus) -> bool:
    return status.cancelled or bool(
        status.pending_jobs
        or status.active_jobs
        or status.resumable_jobs
        or status.indeterminate_jobs
    )


def _terminal_indeterminate_fallback(status: WorkflowStatus) -> bool:
    return (
        status.approved
        and not status.cancelled
        and status.indeterminate_jobs > 0
        and status.pending_jobs == 0
        and status.active_jobs == 0
        and status.resumable_jobs == 0
        and len(status.indeterminate_retries) == status.indeterminate_jobs
        and all(
            item.call_kind is ProviderCallKind.MAPPING
            for item in status.indeterminate_retries
        )
    )


def _semantic_assembly(
    adapter: DurableWorkflowRepositoryAdapter,
    prepared: PreparedProductWorkflow,
) -> SemanticAssembly:
    payloads = tuple(
        result.normalized_payload
        for job in prepared.plan.jobs
        if (result := adapter.load_published_result(prepared.run_id, job.job_id)) is not None
    )
    return assemble_semantic_corridors(
        prepared.frozen_plans.story_chunk_plan,
        payloads,
    )


def _published_payloads(
    adapter: DurableWorkflowRepositoryAdapter,
    run_id: str,
    jobs: Sequence[DerivedSemanticJob],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for raw_job in jobs:
        job_id = raw_job.job_id
        result = adapter.load_published_result(run_id, job_id)
        if result is not None:
            payloads[job_id] = result.normalized_payload
    return payloads


def _register_job(
    service: object,
    materializer: FrozenProductRequestMaterializer,
    prepared: PreparedProductWorkflow,
    preview_identity: str,
    job: object,
) -> None:
    from renpy_story_mapper.story_map_v2.phase04_sections import DerivedSemanticJob
    from renpy_story_mapper.story_map_v2.workflow_service import StoryMapWorkflowService

    if not isinstance(service, StoryMapWorkflowService) or not isinstance(
        job, DerivedSemanticJob
    ):
        raise TypeError("unsupported derived workflow composition")
    durable_job = adapt_derived_semantic_job(prepared, job)
    materializer.register(durable_job.serialized_request_identity, job.request)
    service.register_derived_job(
        prepared.run_id,
        preview_identity=preview_identity,
        job=durable_job,
    )


def _generation_id(
    kind: str,
    prepared: PreparedProductWorkflow,
    semantic: SemanticAssembly,
) -> str:
    return workflow_digest(
        {
            "run_id": prepared.run_id,
            "plan_id": prepared.plan.plan_id,
            "authority_identity": prepared.plan.authority_identity.value,
            "coverage_hash": semantic.coverage_hash,
            "kind": kind,
        }
    )


def _publish_generation(
    project: ProductWorkflowProject,
    prepared: PreparedProductWorkflow,
    semantic: SemanticAssembly,
    derived: DerivedSemanticAssembly,
    generation_id: str,
    *,
    authority_graph: CanonicalGraph,
) -> None:
    repository = project.story_map_v2_repository()
    graph = authority_graph
    generation_repository = DurableWorkflowRepositoryAdapter.from_project(project)
    pointers = generation_repository.generation_pointers()
    previous = _previous_path_facts(repository, pointers.current_complete_generation)
    path_facts: tuple[PathFact, ...] = ()
    complete = build_generation_artifact(
        generation_id=generation_id,
        run_id=prepared.run_id,
        plan_id=prepared.plan.plan_id,
        authority_identity=prepared.plan.authority_identity.value,
        semantic_assembly=semantic,
        derived=derived,
        kind=GenerationKind.COMPLETE,
        path_facts=path_facts,
        immediately_previous=previous,
    )
    complete = replace(complete, reader_manifest=_reader_manifest(complete, semantic))

    build_id = _generation_id("build", prepared, semantic)
    build_derived = assemble_derived_semantics(
        derived.semantic_plan,
        semantic,
        build_id,
    )
    build = build_generation_artifact(
        generation_id=build_id,
        run_id=prepared.run_id,
        plan_id=prepared.plan.plan_id,
        authority_identity=prepared.plan.authority_identity.value,
        semantic_assembly=semantic,
        derived=build_derived,
        kind=GenerationKind.CANDIDATE,
        path_facts=path_facts,
        immediately_previous=previous,
    )
    build = replace(build, reader_manifest=_reader_manifest(build, semantic))
    publisher = AtomicGenerationPublisher(generation_repository)

    generation_repository.create_generation(build.durable_descriptor())
    _store_reader_material(repository, build, prepared, semantic, graph)
    active = repository.generation_pointers().active_build_generation
    publisher.activate_progressive(build, expected_active_generation_id=active)

    generation_repository.create_generation(complete.durable_descriptor())
    _store_reader_material(repository, complete, prepared, semantic, graph)
    publisher.publish_complete(complete, expected_active_generation_id=build_id)


def _previous_path_facts(
    repository: SqliteStoryMapV2Repository,
    generation_id: str | None,
) -> PathFactSnapshot | None:
    if generation_id is None:
        return None
    generation = repository.load_generation(generation_id)
    if generation is None or not isinstance(generation.descriptor, Mapping):
        raise ValueError("the previous generation descriptor is unavailable")
    facts: list[PathFact] = []
    raw_facts = generation.descriptor.get("path_facts")
    if not isinstance(raw_facts, list):
        raise ValueError("the previous generation path facts are unavailable")
    for raw in raw_facts:
        if not isinstance(raw, Mapping):
            raise ValueError("the previous generation path facts are invalid")
        section_ids = raw.get("section_ids")
        if not isinstance(section_ids, list) or not all(
            isinstance(item, str) for item in section_ids
        ):
            raise ValueError("the previous generation path facts are invalid")
        facts.append(
            PathFact(
                PathFactKind(str(raw.get("kind"))),
                str(raw.get("fact_id")),
                tuple(section_ids),
            )
        )
    return PathFactSnapshot(generation_id, tuple(facts))


def _reader_manifest(
    artifact: GenerationArtifact,
    semantic: SemanticAssembly,
) -> Mapping[str, object]:
    event_by_id = {event.event_id: event for event in semantic.events}
    sections: list[dict[str, object]] = [
        {
            "id": section.section_id,
            "order": order,
            "title": section.title,
            "summary": section.summary,
            "route_id": section.route_owner,
            "status": "complete",
            "event_count": len(section.event_ids),
            "is_new": False,
            "new_facts": [],
        }
        for order, section in enumerate(artifact.sections)
    ]
    choices = sum(len(chunk.choices) for chunk in semantic.chunks)
    arms = sum(len(choice.arm_orders) for chunk in semantic.chunks for choice in chunk.choices)
    endings = sum(
        "terminal" in event.structural_flags for event in event_by_id.values()
    )
    landmarks = [
        {
            "kind": "route",
            "id": section.route_owner,
            "section_id": section.section_id,
            "selection_id": section.event_ids[0],
            "title": section.route_owner,
        }
        for section in artifact.sections
        if section.route_owner is not None
    ]
    return {
        "status": "complete" if artifact.kind is GenerationKind.COMPLETE else "building",
        "overview": {"title": artifact.title, "summary": artifact.overview},
        "counts": {
            "sections": len(artifact.sections),
            "events": len(event_by_id),
            "choices": choices,
            "arms": arms,
            "endings": endings,
        },
        "sections": sections,
        "landmarks": landmarks,
        "new_facts": {
            "baseline_generation_id": artifact.baseline_generation_id,
            "facts": [
                {
                    "kind": fact.kind.value,
                    "fact_id": fact.fact_id,
                    "section_ids": list(fact.section_ids),
                }
                for fact in artifact.new_path_facts
            ],
        },
    }


def _store_reader_material(
    repository: SqliteStoryMapV2Repository,
    artifact: GenerationArtifact,
    prepared: PreparedProductWorkflow,
    semantic: SemanticAssembly,
    graph: CanonicalGraph,
) -> None:
    events = {event.event_id: event for event in semantic.events}
    placements = {
        placement.id: placement for placement in prepared.frozen_plans.story_plan.placements
    }
    choices = {
        choice.choice_key: choice
        for chunk in semantic.chunks
        for choice in chunk.choices
    }
    emitted_choices: set[str] = set()
    for section in artifact.sections:
        items: list[dict[str, object]] = []
        section_choice_keys: list[str] = []
        for event_id in section.event_ids:
            event = events[event_id]
            placement = placements[event.placement_ids[0]]
            items.append(
                _event_item(
                    event,
                    placement,
                    len(items),
                    _event_effects(graph, event, placements),
                )
            )
            for choice_key in placement.choice_keys:
                choice = choices.get(choice_key)
                if choice is not None and choice_key not in emitted_choices:
                    items.append(_choice_item(choice, len(items)))
                    emitted_choices.add(choice_key)
                    section_choice_keys.append(choice_key)
        page_ordinal = 0
        resource_offset = 0
        for page_items in _chunks(items, _PAGE_ITEMS):
            shell_id = f"shell:{section.section_id}:{page_ordinal}"
            page = reader_storage_page(
                endpoint=SECTION_PAGE_ENDPOINT,
                resource_id=section.section_id,
                resource_offset=resource_offset,
                items=page_items,
                shells=(
                    {
                        "id": shell_id,
                        "kind": "timeline",
                        "item_ids": [str(item["id"]) for item in page_items],
                        "parent_shell_id": None,
                        "route_id": section.route_owner,
                        "rejoin_selection_id": None,
                    },
                ),
            )
            _store_page(repository, artifact.generation_id, section.section_id, page_ordinal, page)
            for item_ordinal, item in enumerate(page_items):
                if item["kind"] == "choice":
                    continue
                repository.store_selection(
                    SelectionIndexRecord(
                        artifact.generation_id,
                        str(item["selection_id"]),
                        section.section_id,
                        page_ordinal,
                        item_ordinal,
                        str(item["kind"]),
                    )
                )
            resource_offset += len(page_items)
            page_ordinal += 1

        for choice in (choices[key] for key in section_choice_keys):
            arm_items, branch_shells = _arm_items(
                prepared, semantic, choice, placements
            )
            page = reader_storage_page(
                endpoint=BRANCH_PAGE_ENDPOINT,
                resource_id=choice.choice_key,
                resource_offset=0,
                items=arm_items,
                shells=branch_shells,
            )
            _store_page(repository, artifact.generation_id, section.section_id, page_ordinal, page)
            repository.store_selection(
                SelectionIndexRecord(
                    artifact.generation_id,
                    choice.choice_key,
                    section.section_id,
                    page_ordinal,
                    0,
                    "branch_resource",
                )
            )
            for item_ordinal, item in enumerate(arm_items):
                repository.store_selection(
                    SelectionIndexRecord(
                        artifact.generation_id,
                        str(item["selection_id"]),
                        section.section_id,
                        page_ordinal,
                        item_ordinal,
                        "arm",
                    )
                )
            page_ordinal += 1


def _event_item(
    event: SemanticEvent,
    placement: StoryPlacement,
    order: int,
    effects: tuple[str, ...],
) -> dict[str, object]:
    kind = "ending" if "terminal" in event.structural_flags else "event"
    return {
        "id": event.event_id,
        "kind": kind,
        "order": order,
        "title": event.title,
        "summary": event.summary,
        "effects": list(effects),
        "selection_id": event.event_id,
        "is_new": False,
        "new_facts": [],
        "_reader_navigation": _navigation(placement),
    }


def _event_effects(
    graph: CanonicalGraph,
    event: SemanticEvent,
    placements: Mapping[str, StoryPlacement],
) -> tuple[str, ...]:
    node_ids = {
        node_id
        for placement_id in event.placement_ids
        for node_id in placements[placement_id].canonical_node_ids
    }
    fact_ids: set[str] = set()
    for node in graph.nodes:
        raw_fact_ids = node.attributes.get("fact_ids")
        if node.id in node_ids and isinstance(raw_fact_ids, (list, tuple)):
            fact_ids.update(item for item in raw_fact_ids if isinstance(item, str))
    return tuple(
        str(fact.attributes["original_expression"])
        for fact in graph.facts
        if fact.id in fact_ids
        and fact.kind == "effect"
        and fact.status == "proven"
        and isinstance(fact.attributes.get("original_expression"), str)
    )


def _choice_item(choice: ExactChoiceOverlay, order: int) -> dict[str, object]:
    mechanics = _choice_mechanics(choice)
    title = mechanics.get("caption")
    return {
        "id": choice.choice_key,
        "kind": "choice",
        "order": order,
        "title": title if isinstance(title, str) and title else choice.choice_key,
        "summary": choice.summary,
        "selection_id": choice.choice_key,
        "is_new": False,
        "new_facts": [],
    }


def _arm_items(
    prepared: PreparedProductWorkflow,
    semantic: SemanticAssembly,
    choice: ExactChoiceOverlay,
    placements: Mapping[str, StoryPlacement],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    mechanics = _choice_mechanics(choice)
    raw_arms = mechanics.get("arms")
    arms = raw_arms if isinstance(raw_arms, list) else []
    result: list[dict[str, object]] = []
    shells: list[dict[str, object]] = []
    all_placements = tuple(placements.values())
    fallback = all_placements[0]
    scope_bindings = {
        item.scope_id: item for item in prepared.frozen_plans.story_chunk_plan.scope_bindings
    }
    for order in choice.arm_orders:
        raw = next(
            (
                item
                for item in arms
                if isinstance(item, Mapping) and item.get("order") == order
            ),
            {},
        )
        placement = next(
            (
                item
                for item in all_placements
                if any(
                    step.choice_key == choice.choice_key and step.arm_order == order
                    for step in item.arm_lineage
                )
            ),
            fallback,
        )
        title = raw.get("caption") if isinstance(raw, Mapping) else None
        condition = raw.get("condition") if isinstance(raw, Mapping) else None
        effects = raw.get("effects") if isinstance(raw, Mapping) else None
        destination_id = raw.get("destination_id") if isinstance(raw, Mapping) else None
        rejoin_node_id = raw.get("rejoin_node_id") if isinstance(raw, Mapping) else None
        rejoin_selection_id = (
            _selection_for_node(semantic, placements, rejoin_node_id)
            if isinstance(rejoin_node_id, str)
            else None
        )
        arm_id = _arm_id(choice.choice_key, order)
        result.append(
            {
                "id": arm_id,
                "kind": "arm",
                "order": order - 1,
                "title": title if isinstance(title, str) and title else f"Outcome {order}",
                "summary": choice.summary,
                "selection_id": arm_id,
                "condition": condition if isinstance(condition, str) else None,
                "effects": (
                    _durable_reader_effects(effects)
                    if isinstance(effects, list)
                    else []
                ),
                "destination_id": (
                    destination_id if isinstance(destination_id, str) else None
                ),
                "rejoin_node_id": (
                    rejoin_node_id if isinstance(rejoin_node_id, str) else None
                ),
                "rejoin_line": raw.get("rejoin_line") if isinstance(raw, Mapping) else None,
                "reachability": raw.get("reachability") if isinstance(raw, Mapping) else None,
                "unresolved_warnings": (
                    [item for item in raw.get("unresolved_warnings", []) if isinstance(item, str)]
                    if isinstance(raw, Mapping)
                    and isinstance(raw.get("unresolved_warnings", []), list)
                    else []
                ),
                "is_new": False,
                "new_facts": [],
                "_reader_navigation": _navigation(placement),
            }
        )
        binding = scope_bindings[placement.scope_id]
        shells.append(
            {
                "id": f"shell:{choice.choice_key}:{order}",
                "kind": "branch",
                "item_ids": [arm_id],
                "parent_shell_id": None,
                "route_id": binding.lane_id if binding.persistent_lane else None,
                "rejoin_selection_id": rejoin_selection_id,
            }
        )
    return result, shells


def _durable_reader_effects(effects: Sequence[object]) -> list[str]:
    result: list[str] = []
    for effect in effects:
        if not isinstance(effect, str):
            continue
        try:
            _validate_private_content(effect, "reader choice-arm effect")
        except ValueError:
            continue
        result.append(effect)
    return result


def _selection_for_node(
    semantic: SemanticAssembly,
    placements: Mapping[str, StoryPlacement],
    node_id: str,
) -> str | None:
    return next(
        (
            event.event_id
            for event in semantic.events
            if any(node_id in placements[item].canonical_node_ids for item in event.placement_ids)
        ),
        None,
    )


def _navigation(placement: StoryPlacement) -> dict[str, object]:
    return {
        "destination_kind": "generic_scene",
        "target_id": placement.scene_id,
        "detail_service_kind": "m11_scene",
        "detail_service_id": placement.scene_id,
        "evidence_id": placement.anchor_id,
        "relative_path": placement.relative_path,
        "start_line": placement.start_line,
        "end_line": placement.end_line,
        "line_basis": "physical",
        "effects": [],
    }


def _event_has_choice(
    prepared: PreparedProductWorkflow,
    event: SemanticEvent,
    choice_key: str,
) -> bool:
    placements = {
        placement.id: placement for placement in prepared.frozen_plans.story_plan.placements
    }
    return any(choice_key in placements[item].choice_keys for item in event.placement_ids)


def _choice_mechanics(choice: ExactChoiceOverlay) -> Mapping[str, object]:
    value = json.loads(choice.canonical_mechanics)
    return value if isinstance(value, Mapping) else {}


def _arm_id(choice_key: str, order: int) -> str:
    return f"{choice_key}:arm:{order}"


def _chunks(
    values: Sequence[dict[str, object]],
    size: int,
) -> tuple[tuple[dict[str, object], ...], ...]:
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


def _store_page(
    repository: SqliteStoryMapV2Repository,
    generation_id: str,
    section_id: str,
    page_ordinal: int,
    page: Mapping[str, object],
) -> None:
    page_bytes = storage.canonical_json(dict(page))
    repository.store_section_page(
        SectionPageRecord(
            generation_id,
            section_id,
            page_ordinal,
            len(page["items"]),  # type: ignore[arg-type]
            dict(page),
            hashlib.sha256(page_bytes).hexdigest(),
        )
    )


__all__ = [
    "execute_product_vertical",
    "load_product_workflow",
    "project_workflow_reader_status",
]

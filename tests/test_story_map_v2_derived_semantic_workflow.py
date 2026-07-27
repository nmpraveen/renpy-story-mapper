from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from renpy_story_mapper.project import Project
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    AttemptAccounting,
    AuthorityIdentity,
    DerivedSemanticNodeRole,
    ProviderCallKind,
    ProviderInputIdentity,
    ProviderMode,
    SerializedRequestIdentity,
    TransmissionDisposition,
    WorkflowCorridorDescriptor,
    WorkflowDerivedSemanticJobDescriptor,
    WorkflowDerivedSemanticPlanDescriptor,
    WorkflowFailure,
    WorkflowPlanDescriptor,
    WorkflowResourceCeilings,
    WorkflowRouteMembership,
    workflow_digest,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import WorkflowProviderError
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)
from renpy_story_mapper.story_map_v2.workflow_service import StoryMapWorkflowService
from test_story_map_v2_phase04_workflow import (
    ConstructionTrap,
    DictMaterializer,
    RecordingFactory,
    SyntheticValidator,
    _plan,
    _policy,
    _reply,
)


def _semantic_plan(authority: AuthorityIdentity) -> WorkflowDerivedSemanticPlanDescriptor:
    return WorkflowDerivedSemanticPlanDescriptor(
        semantic_plan_identity=workflow_digest("semantic-plan-public"),
        story_chunk_plan_identity=workflow_digest("chunk-plan-public"),
        authority_identity=authority,
        corridors=(WorkflowCorridorDescriptor("chunk-0", None, 1, 0),),
        route_memberships=(),
        section_synthesis_calls=1,
        route_reduction_calls=0,
        route_summary_calls=0,
        whole_game_reduction_calls=0,
        final_overview_calls=1,
        rollup_synthesis_calls=1,
    )


def _plan_and_ceilings() -> tuple[
    WorkflowPlanDescriptor, WorkflowResourceCeilings, dict[str, bytes]
]:
    policy = _policy()
    mapping_plan, requests = _plan(1, policy)
    semantic = _semantic_plan(mapping_plan.authority_identity)
    plan = WorkflowPlanDescriptor(
        mapping_plan.plan_id,
        mapping_plan.authority_identity,
        mapping_plan.jobs,
        semantic,
    )
    ceilings = WorkflowResourceCeilings(
        mapping_calls=1,
        review_calls=0,
        fallback_calls=0,
        input_tokens=1_000,
        output_tokens=1_000,
        elapsed_ms=10_000,
        indeterminate_retry_calls=1,
        section_synthesis_calls=1,
        route_reduction_calls=0,
        route_summary_calls=0,
        whole_game_reduction_calls=0,
        final_overview_calls=1,
        rollup_synthesis_calls=1,
    )
    return plan, ceilings, requests


def _derived_job(
    plan: WorkflowPlanDescriptor,
    request: bytes,
    *,
    child_hash: str,
) -> WorkflowDerivedSemanticJobDescriptor:
    semantic = plan.derived_semantic_plan
    assert semantic is not None
    request_identity = SerializedRequestIdentity(
        "request-derived-section",
        hashlib.sha256(request).hexdigest(),
        len(request),
    )
    provider_input = ProviderInputIdentity(
        serialized_request_identity=request_identity,
        prompt_version="section-synthesis-prompt-v1",
        schema_version="section-synthesis-schema-v1",
        adapter_version="sterile-cloud-v1",
        provider="codex-cli",
        model="gpt-5.6-terra",
        reasoning="high",
        fast_mode=False,
        mode=ProviderMode.CLOUD,
    )
    return WorkflowDerivedSemanticJobDescriptor(
        plan_id=plan.plan_id,
        semantic_plan_identity=semantic.semantic_plan_identity,
        story_chunk_plan_identity=semantic.story_chunk_plan_identity,
        candidate_generation_identity=workflow_digest("candidate-generation-public"),
        authority_identity=plan.authority_identity,
        job_id="derived-section-0",
        call_kind=ProviderCallKind.SECTION_SYNTHESIS,
        node_role=None,
        corridor_id="chunk-0",
        route_owner=None,
        child_ids=("job-0",),
        child_prose_hashes=(child_hash,),
        ordinal=0,
        serialized_request_identity=request_identity,
        provider_input_identity=provider_input,
        cache_identity=provider_input.cache_identity,
    )


def _service(
    adapter: DurableWorkflowRepositoryAdapter,
    requests: dict[str, bytes],
    factory: RecordingFactory,
) -> StoryMapWorkflowService:
    return StoryMapWorkflowService(
        adapter,
        DictMaterializer(requests),
        SyntheticValidator(),
        cloud_factory=factory,
    )


def test_semantic_plan_rejects_route_and_formula_drift() -> None:
    authority = AuthorityIdentity("authority-public")
    with pytest.raises(ValueError, match="unknown corridor"):
        WorkflowDerivedSemanticPlanDescriptor(
            semantic_plan_identity=workflow_digest("semantic"),
            story_chunk_plan_identity=workflow_digest("chunks"),
            authority_identity=authority,
            corridors=(WorkflowCorridorDescriptor("chunk-0", "route-a", 1, 0),),
            route_memberships=(WorkflowRouteMembership("route-a", ("missing",)),),
            section_synthesis_calls=1,
            route_reduction_calls=0,
            route_summary_calls=1,
            whole_game_reduction_calls=0,
            final_overview_calls=1,
            rollup_synthesis_calls=2,
        )
    with pytest.raises(ValueError, match="component ceilings"):
        replace(_semantic_plan(authority), section_synthesis_calls=0)


def test_real_adapter_registers_dependency_ready_section_without_mutating_mapping_jobs(
    tmp_path: Path,
) -> None:
    plan, ceilings, requests = _plan_and_ceilings()
    policy = _policy()
    cloud = RecordingFactory(
        policy.cloud,
        [_reply(policy.cloud, b"mapping"), _reply(policy.cloud, b"section")],
    )
    with Project.create(tmp_path / "derived.rsmp") as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-derived", plan, policy, ceilings)
        service.approve(preview.run_id, preview.identity)
        service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        published_mapping = adapter.load_published_result(preview.run_id, "job-0")
        assert published_mapping is not None
        derived_request = b'{"public":"derived-section"}'
        derived = _derived_job(
            plan, derived_request, child_hash=published_mapping.result_identity
        )
        requests[derived.serialized_request_identity.value] = derived_request
        service.register_derived_job(
            preview.run_id, preview_identity=preview.identity, job=derived
        )
        assert adapter.load_preview(preview.run_id).plan.jobs == plan.jobs

        status = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert status.accepted_jobs == 2
        assert cloud.calls == 2
        assert adapter.load_job_descriptor(preview.run_id, derived.job_id) == derived


def test_derived_indeterminate_retry_is_exact_detailed_and_finite(tmp_path: Path) -> None:
    plan, ceilings, requests = _plan_and_ceilings()
    policy = _policy()
    uncertain = WorkflowProviderError(
        WorkflowFailure.INDETERMINATE,
        TransmissionDisposition.INDETERMINATE,
        AttemptAccounting(1, 1, 0, 1),
    )
    cloud = RecordingFactory(
        policy.cloud,
        [_reply(policy.cloud, b"mapping"), uncertain, _reply(policy.cloud, b"section")],
    )
    with Project.create(tmp_path / "derived-retry.rsmp") as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-retry", plan, policy, ceilings)
        service.approve(preview.run_id, preview.identity)
        service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        mapping = adapter.load_published_result(preview.run_id, "job-0")
        assert mapping is not None
        request = b'{"public":"retry-section"}'
        derived = _derived_job(plan, request, child_hash=mapping.result_identity)
        requests[derived.serialized_request_identity.value] = request
        service.register_derived_job(
            preview.run_id, preview_identity=preview.identity, job=derived
        )

        first = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert first.indeterminate_jobs == 1
        assert len(first.indeterminate_retries) == 1
        detail = first.indeterminate_retries[0]
        assert (detail.job_id, detail.call_kind, detail.can_approve_retry) == (
            derived.job_id,
            ProviderCallKind.SECTION_SYNTHESIS,
            True,
        )
        unchanged = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert unchanged.indeterminate_jobs == 1
        assert cloud.calls == 2

        service.approve_indeterminate_retry(
            preview.run_id,
            preview_identity=preview.identity,
            job_id=detail.job_id,
            indeterminate_attempt_id=detail.attempt_id,
        )
        approved_status = service.status(preview.run_id)
        assert approved_status.indeterminate_jobs == 1
        assert approved_status.indeterminate_retries[0].retry_approval_identity is not None
        assert not approved_status.indeterminate_retries[0].can_approve_retry
        final = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert final.accepted_jobs == 2
        assert final.accounting.calls == 3
        assert cloud.calls == 3


@pytest.mark.parametrize(
    "derived_outcome",
    (
        b"invalid",
        WorkflowProviderError(
            WorkflowFailure.CONTENT_REFUSAL,
            TransmissionDisposition.TRANSMITTED,
            AttemptAccounting(1, 1, 0, 1),
        ),
    ),
)
def test_semantic_invalid_or_refused_result_is_one_call_structural_without_loopback(
    tmp_path: Path,
    derived_outcome: bytes | WorkflowProviderError,
) -> None:
    plan, ceilings, requests = _plan_and_ceilings()
    policy = _policy()
    cloud = RecordingFactory(
        policy.cloud,
        [_reply(policy.cloud, b"mapping"), (
            _reply(policy.cloud, derived_outcome)
            if isinstance(derived_outcome, bytes)
            else derived_outcome
        )],
    )
    loopback = ConstructionTrap()
    with Project.create(tmp_path / "derived-structural.rsmp") as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        service = StoryMapWorkflowService(
            adapter,
            DictMaterializer(requests),
            SyntheticValidator(),
            cloud_factory=cloud,
            loopback_factory=loopback,
        )
        preview = service.prepare("run-derived-structural", plan, policy, ceilings)
        service.approve(preview.run_id, preview.identity)
        service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        mapping = adapter.load_published_result(preview.run_id, "job-0")
        assert mapping is not None
        request = b'{"public":"derived-structural"}'
        derived = _derived_job(plan, request, child_hash=mapping.result_identity)
        requests[derived.serialized_request_identity.value] = request
        service.register_derived_job(
            preview.run_id, preview_identity=preview.identity, job=derived
        )

        status = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )

        assert status.accepted_jobs == 1
        assert status.structural_fallback_jobs == 1
        assert status.accounting.calls == 2
        assert cloud.calls == 2
        assert loopback.constructions == 0


def test_reopened_derived_status_is_provider_free(tmp_path: Path) -> None:
    path = tmp_path / "derived-reopen.rsmp"
    plan, ceilings, requests = _plan_and_ceilings()
    policy = _policy()
    cloud = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"mapping")])
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-derived-reopen", plan, policy, ceilings)
        service.approve(preview.run_id, preview.identity)
        service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )

    trap = ConstructionTrap()
    with Project.open(path) as reopened:
        adapter = DurableWorkflowRepositoryAdapter.from_project(reopened)
        service = StoryMapWorkflowService(
            adapter,
            DictMaterializer(requests),
            SyntheticValidator(),
            cloud_factory=trap,
            loopback_factory=trap,
        )
        status = service.status(preview.run_id)
        loaded = adapter.load_preview(preview.run_id)

    assert status.accepted_jobs == 1
    assert loaded.plan.derived_semantic_plan == plan.derived_semantic_plan
    assert trap.constructions == 0


def test_rollup_descriptor_requires_role_and_exact_cloud_identity() -> None:
    plan, _, _ = _plan_and_ceilings()
    request = b"public"
    section = _derived_job(plan, request, child_hash=workflow_digest("child"))
    with pytest.raises(ValueError, match="node role"):
        replace(
            section,
            call_kind=ProviderCallKind.ROLLUP_SYNTHESIS,
            corridor_id=None,
            node_role=None,
        )
    rollup = replace(
        section,
        call_kind=ProviderCallKind.ROLLUP_SYNTHESIS,
        node_role=DerivedSemanticNodeRole.FINAL_OVERVIEW,
        corridor_id=None,
    )
    foreign_input = replace(rollup.provider_input_identity, model="foreign-model")
    with pytest.raises(ValueError, match="Terra"):
        replace(
            rollup,
            provider_input_identity=foreign_input,
            cache_identity=foreign_input.cache_identity,
        )

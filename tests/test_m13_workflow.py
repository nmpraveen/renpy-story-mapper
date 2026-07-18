from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import (
    AttemptMetrics,
    AttemptOutcome,
    BudgetLimits,
    ProviderIdentity,
    ProviderSettings,
)
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.narrative.presentation import (
    narrative_claim_citations,
    narrative_snapshot,
)
from renpy_story_mapper.narrative.projection import NarrativeInputMode
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    ProviderOutputItem,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderTimeoutError,
    ProviderUsage,
)
from renpy_story_mapper.narrative.scheduler import (
    SchedulerAttemptRecord,
    SchedulerCallFinalization,
    SchedulerCallReservation,
    SchedulerConfigurationError,
    SchedulerPolicy,
    SchedulerRunRecord,
    SchedulerRunState,
    SchedulerUsage,
    scheduler_compatibility_id,
)
from renpy_story_mapper.narrative.sizing import budget_limits_with_headroom
from renpy_story_mapper.narrative.workflow import (
    M13SchedulerPersistenceSink,
    grant_narrative_consent,
    prepare_narrative_scene_run,
    run_prepared_scene_jobs,
)
from renpy_story_mapper.organization.sterile_runner import TransmissionDisposition
from renpy_story_mapper.project import Project, create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


@dataclass
class DeterministicNarrativeProvider:
    calls: list[ProviderRequest] = field(default_factory=list)
    partial_first_item: bool = False
    claim_value_prefix: str = "scene"
    cancel_calls: int = 0

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            "approved-test-cloud",
            "test-structured-adapter",
            "test-adapter-v1",
            "test-cli-v1",
        )

    def submit(
        self,
        request: ProviderRequest,
        cancelled: object,
    ) -> ProviderResponse:
        del cancelled
        self.calls.append(request)
        identity = ProviderIdentity(
            provider="approved-test-cloud",
            adapter="test-structured-adapter",
            adapter_version="test-adapter-v1",
            requested_model=request.requested_model,
            resolved_model=request.requested_model,
            settings=request.settings,
        )
        output: list[ProviderOutputItem] = []
        for index, item in enumerate(request.items):
            claims = [_claim("E1", value=f"{self.claim_value_prefix}-{index}")]
            if self.partial_first_item and not self.calls[:-1] and index == 0:
                claims.append(_claim("E999", value="unsupported"))
            output.append(
                ProviderOutputItem(
                    item.logical_job_id,
                    index,
                    {
                        "logical_job_id": item.logical_job_id,
                        "title": f"Narrative {index + 1}",
                        "summary": f"Validated independent scene {index + 1}.",
                        "claims": claims,
                    },
                )
            )
        return ProviderResponse(
            request.request_id,
            identity,
            tuple(output),
            ProviderUsage(20, 10, 5),
            PROMPT_TEMPLATE_VERSION,
            RESPONSE_SCHEMA_VERSION,
        )

    def cancel(self) -> None:
        self.cancel_calls += 1


def _claim(handle: str, *, value: str) -> dict[str, object]:
    return {
        "claim_class": "factual",
        "context_scope": "atomic",
        "text": f"The scene has supported value {value}.",
        "evidence_handles": [handle],
        "child_claim_handles": [],
        "subject": "scene",
        "predicate": "supported value",
        "polarity": "positive",
        "normalized_value": value,
    }


def _project(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "m13-workflow.rsmproj", source)


def _limits() -> BudgetLimits:
    return BudgetLimits(
        max_provider_calls=100,
        max_input_tokens=10_000_000,
        max_output_tokens=10_000_000,
        max_total_tokens=20_000_000,
        timeout_seconds=300,
        max_concurrency=2,
    )


def _batch_limits() -> BatchLimits:
    return BatchLimits(8, 500_000, 100_000)


def _policy() -> SchedulerPolicy:
    return SchedulerPolicy(_batch_limits())


def _add_m12_result(project: Project) -> None:
    service = M12RouteService(project)
    nodes = service.destinations(limit=50)["nodes"]
    assert isinstance(nodes, list)
    destination = next(
        item
        for item in nodes
        if isinstance(item, dict) and item.get("kind") == "generic_scene"
    )
    outcome = service.solve(
        service.prepare(str(destination["kind"]), str(destination["target_id"]))
    )
    assert outcome.result is not None


def test_prepare_is_disabled_and_can_exclude_m12_material_without_losing_binding(
    tmp_path: Path,
) -> None:
    provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        _add_m12_result(project)
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-preview",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        current_m12 = prepared.authority.binding.m12_result_identities
        support = [
            record
            for job in prepared.scene_run.jobs
            for record in job.payload["support_records"]  # type: ignore[union-attr]
            if isinstance(record, dict) and record.get("authority") == "m12"
        ]

        assert current_m12
        assert support == []
        assert prepared.consent_preview.consent_granted is False
        assert prepared.preview_dict()["includes_m12_material"] is False
        assert provider.calls == []
        assert project.m13_persistence().list_records(RecordKind.CONSENT) == ()


def test_live_shape_complete_estimate_rejects_old_budget_and_binds_headroom(
    tmp_path: Path,
) -> None:
    provider = DeterministicNarrativeProvider()
    old_under_budget = BudgetLimits(
        max_provider_calls=80,
        max_input_tokens=400_000,
        max_output_tokens=150_000,
        max_total_tokens=550_000,
        timeout_seconds=1_800,
        max_concurrency=1,
    )

    with _project(tmp_path) as project:
        _add_m12_result(project)
        with pytest.raises(ValueError, match="estimated input tokens exceed"):
            prepare_narrative_scene_run(
                project,
                provider,
                run_id="run-old-under-budget",
                requested_model="runtime-selected-model",
                mode=NarrativeInputMode.FACT_ONLY,
                include_m12_material=True,
                limits=old_under_budget,
                batch_limits=_batch_limits(),
                locale="en-US",
                perspective="reader",
            )

        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-headroom",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=True,
            limits=lambda estimate: budget_limits_with_headroom(
                estimate,
                timeout_seconds=1_800,
                max_concurrency=1,
            ),
            batch_limits=_batch_limits(),
            locale="en-US",
            perspective="reader",
        )
        wider = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-headroom",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=True,
            limits=lambda estimate: budget_limits_with_headroom(
                estimate,
                timeout_seconds=1_800,
                max_concurrency=1,
                numerator=3,
                denominator=2,
            ),
            batch_limits=_batch_limits(),
            locale="en-US",
            perspective="reader",
        )

    estimate = prepared.consent_preview.estimate
    limits = prepared.consent_preview.limits
    assert estimate.input_tokens > 2_250_000
    assert limits.max_input_tokens > 2_800_000
    assert limits.max_input_tokens * 4 >= estimate.input_tokens * 5
    assert limits.max_input_tokens * 4 >= prepared.scene_run.estimate.input_tokens * 5
    assert limits.max_provider_calls > 0
    assert limits.max_output_tokens > 0
    assert limits.max_total_tokens >= limits.max_input_tokens
    assert limits.timeout_seconds == 1_800
    assert limits.max_concurrency == 1
    assert prepared.consent_preview.manifest_id != wider.consent_preview.manifest_id
    assert provider.calls == []


def test_granted_scene_run_persists_partial_items_claims_attempts_and_lazy_citations(
    tmp_path: Path,
) -> None:
    provider = DeterministicNarrativeProvider(partial_first_item=True)
    with _project(tmp_path) as project:
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-published",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        preview_id = prepared.consent_preview.manifest_id
        consent = grant_narrative_consent(project, prepared)
        assert consent.manifest_id == preview_id
        persisted_consents = project.m13_persistence().list_records(RecordKind.CONSENT)
        assert len(persisted_consents) == 1
        assert persisted_consents[0].record_id == preview_id
        assert persisted_consents[0].payload is not None
        assert persisted_consents[0].payload["consent_granted"] is True
        result = run_prepared_scene_jobs(
            project,
            provider,
            prepared,
            consent,
            policy=_policy(),
        )

        assert result.record.partial_jobs == 1
        assert result.record.succeeded_jobs == len(prepared.scheduled_jobs) - 1
        assert provider.calls
        assert {request.consent_manifest_id for request in provider.calls} == {preview_id}
        assert result.record.consent_manifest_id == preview_id
        persisted_run = project.m13_persistence().lookup(
            RecordKind.RUN,
            consent.run_id,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        assert persisted_run.state is LookupState.HIT
        assert persisted_run.payload is not None
        assert persisted_run.payload["consent_manifest_id"] == preview_id
        attempts = project.m13_persistence().list_records(
            RecordKind.ATTEMPT,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        assert len(attempts) == len(prepared.scheduled_jobs)
        assert all(item.state is LookupState.HIT for item in attempts)
        snapshot = narrative_snapshot(project, limit=200)
        assert snapshot["status"] == "available"
        coverage = snapshot["coverage"]
        assert isinstance(coverage, dict)
        assert coverage["published_scene_jobs"] == len(prepared.scheduled_jobs)
        jobs = snapshot["jobs"]
        assert isinstance(jobs, list)
        artifacts = [item["artifact"] for item in jobs]
        assert any(
            isinstance(artifact, dict) and artifact["publication"] == "partial"
            for artifact in artifacts
        )
        claims = project.m13_persistence().list_records(
            RecordKind.CLAIM,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        first_claim = next(item for item in claims if item.payload is not None)
        assert first_claim.payload is not None
        citations = narrative_claim_citations(
            project,
            str(first_claim.payload["claim_id"]),
        )
        assert citations["citations"]


def test_ungranted_and_tampered_consent_submit_zero_provider_calls(tmp_path: Path) -> None:
    provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-rejected-consent",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        with pytest.raises(ValueError, match="was not granted"):
            run_prepared_scene_jobs(
                project,
                provider,
                prepared,
                prepared.consent_preview,
                policy=_policy(),
            )
        tampered = replace(
            prepared.consent_preview,
            selected_scope_ids=("tampered-scope",),
            consent_granted=True,
        )
        with pytest.raises(ValueError, match="ID differs"):
            run_prepared_scene_jobs(
                project,
                provider,
                prepared,
                tampered,
                policy=_policy(),
            )

        assert provider.calls == []
        assert project.m13_persistence().list_records(RecordKind.CONSENT) == ()


def test_authority_invalidated_work_cannot_resume_under_prior_consent(
    tmp_path: Path,
) -> None:
    provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-authority-invalidated",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        _add_m12_result(project)

        with pytest.raises(ValueError, match="authority changed"):
            run_prepared_scene_jobs(
                project,
                provider,
                prepared,
                consent,
                policy=_policy(),
            )

    assert provider.calls == []


def test_runtime_settings_bind_consent_cache_requests_and_run_identity(
    tmp_path: Path,
) -> None:
    provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        default = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-settings",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        first_settings = ProviderSettings(
            (("fast_mode", False), ("model_reasoning_effort", "runtime-a"))
        )
        first = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-settings",
            requested_model="runtime-selected-model",
            settings=first_settings,
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        second = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-settings",
            requested_model="runtime-selected-model",
            settings=ProviderSettings(
                (("fast_mode", False), ("model_reasoning_effort", "runtime-b"))
            ),
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )

        assert default.consent_preview.provider.settings == ProviderSettings()
        assert first.consent_preview.provider.settings == first_settings
        assert first.consent_preview.manifest_id != second.consent_preview.manifest_id
        assert tuple(item.logical_job_id for item in first.scheduled_jobs) == tuple(
            item.logical_job_id for item in second.scheduled_jobs
        )
        assert tuple(item.input_revision_id for item in first.scheduled_jobs) == tuple(
            item.input_revision_id for item in second.scheduled_jobs
        )
        assert tuple(item.cache_identity.key for item in first.scheduled_jobs) != tuple(
            item.cache_identity.key for item in second.scheduled_jobs
        )

        consent = grant_narrative_consent(project, first)
        result = run_prepared_scene_jobs(
            project,
            provider,
            first,
            consent,
            policy=_policy(),
        )
        assert provider.calls
        assert all(request.settings == first_settings for request in provider.calls)
        assert result.record.provider.settings == first_settings
        persisted_run = project.m13_persistence().lookup(
            RecordKind.RUN,
            consent.run_id,
            authority_binding=first.authority.binding.to_dict(),
        )
        assert persisted_run.payload is not None
        assert persisted_run.payload["provider"]["settings"] == first_settings.to_dict()
        caches = project.m13_persistence().list_records(
            RecordKind.CACHE,
            authority_binding=first.authority.binding.to_dict(),
        )
        assert caches
        assert all(
            item.payload is not None
            and item.payload["cache_identity"]["provider"]["settings"]
            == first_settings.to_dict()
            and item.payload["provider"]["settings"] == first_settings.to_dict()
            for item in caches
        )


def test_exact_replay_after_reopen_makes_zero_provider_calls(tmp_path: Path) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    first_provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        first = prepare_narrative_scene_run(
            project,
            first_provider,
            run_id="run-first",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        first_result = run_prepared_scene_jobs(
            project,
            first_provider,
            first,
            grant_narrative_consent(project, first),
            policy=_policy(),
        )
        artifact_ids = tuple(item.artifact_id for item in first_result.jobs)
    assert first_provider.calls

    replay_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        replay = prepare_narrative_scene_run(
            project,
            replay_provider,
            run_id="run-replay",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        replay_result = run_prepared_scene_jobs(
            project,
            replay_provider,
            replay,
            grant_narrative_consent(project, replay),
            policy=_policy(),
        )

        assert replay_provider.calls == []
        assert replay_result.record.usage.provider_calls == 0
        assert all(item.cache_replay for item in replay_result.jobs)
        assert tuple(item.artifact_id for item in replay_result.jobs) == artifact_ids


def test_exact_same_run_reopen_restores_cumulative_usage_with_zero_new_calls(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    first_provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        first = prepare_narrative_scene_run(
            project,
            first_provider,
            run_id="run-durable-replay",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        first_result = run_prepared_scene_jobs(
            project,
            first_provider,
            first,
            grant_narrative_consent(project, first),
            policy=_policy(),
        )
    assert first_result.record.usage.provider_calls > 0

    replay_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        replay = prepare_narrative_scene_run(
            project,
            replay_provider,
            run_id="run-durable-replay",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        replay_result = run_prepared_scene_jobs(
            project,
            replay_provider,
            replay,
            grant_narrative_consent(project, replay),
            policy=_policy(),
        )

    assert replay_provider.calls == []
    assert replay_result.record.usage.provider_calls == 0
    assert replay_result.record.cumulative_usage == first_result.record.cumulative_usage
    assert all(item.cache_replay for item in replay_result.jobs)


def test_checkpoint_adds_only_durable_events_written_after_it_once(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    first_provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        prepared = prepare_narrative_scene_run(
            project,
            first_provider,
            run_id="run-checkpoint-later-durable",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        first = run_prepared_scene_jobs(
            project,
            first_provider,
            prepared,
            consent,
            policy=_policy(),
        )
        assert first.record.current_phase_usage is not None
        checkpoint_phase = first.record.current_phase_usage
        compatibility_id = scheduler_compatibility_id(
            consent, prepared.scheduled_jobs
        )
        job = prepared.scheduled_jobs[0]
        later_usage = SchedulerUsage(
            provider_calls=1,
            input_tokens=9,
            output_tokens=4,
            elapsed_ms=6,
            cost_micros=2,
            peak_concurrency=1,
            usage_estimated=True,
        )
        sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            prepared.scheduled_jobs,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        sink.reserve_call(
            SchedulerCallReservation(
                reservation_id="m13_reservation_after_checkpoint",
                run_id=consent.run_id,
                consent_manifest_id=consent.manifest_id,
                compatibility_id=compatibility_id,
                batch_id="batch:after-checkpoint",
                logical_job_ids=(job.logical_job_id,),
                logical_attempt_numbers=(2,),
                provider_call_number=checkpoint_phase.provider_calls + 1,
                provider=consent.provider,
                usage=later_usage,
            )
        )
        resumed_phase = sink.resume_usage(
            consent, prepared.scheduled_jobs, compatibility_id
        ).current_phase_usage

    expected = SchedulerUsage(
        provider_calls=checkpoint_phase.provider_calls + 1,
        input_tokens=checkpoint_phase.input_tokens + 9,
        output_tokens=checkpoint_phase.output_tokens + 4,
        elapsed_ms=checkpoint_phase.elapsed_ms + 6,
        cost_micros=(
            None
            if checkpoint_phase.cost_micros is None
            else checkpoint_phase.cost_micros + 2
        ),
        peak_concurrency=max(checkpoint_phase.peak_concurrency, 1),
        usage_estimated=True,
    )
    assert resumed_phase == expected

    replay_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        replay = prepare_narrative_scene_run(
            project,
            replay_provider,
            run_id="run-checkpoint-later-durable",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        replay_consent = grant_narrative_consent(project, replay)
        replay_result = run_prepared_scene_jobs(
            project,
            replay_provider,
            replay,
            replay_consent,
            policy=_policy(),
        )

    assert replay_provider.calls == []
    assert replay_result.record.cumulative_usage == expected

    with Project.open(project_path) as project:
        repeated = prepare_narrative_scene_run(
            project,
            DeterministicNarrativeProvider(),
            run_id="run-checkpoint-later-durable",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        repeated_consent = grant_narrative_consent(project, repeated)
        repeated_sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            repeated.scheduled_jobs,
            authority_binding=repeated.authority.binding.to_dict(),
        )
        repeated_phase = repeated_sink.resume_usage(
            repeated_consent,
            repeated.scheduled_jobs,
            scheduler_compatibility_id(repeated_consent, repeated.scheduled_jobs),
        ).current_phase_usage

    assert repeated_phase == expected


def test_opaque_legacy_checkpoint_fails_closed_before_submit(tmp_path: Path) -> None:
    provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-opaque-legacy-checkpoint",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        compatibility_id = scheduler_compatibility_id(
            consent, prepared.scheduled_jobs
        )
        legacy_usage = SchedulerUsage(
            provider_calls=1,
            input_tokens=20,
            output_tokens=10,
            elapsed_ms=5,
            cost_micros=3,
            peak_concurrency=1,
        )
        legacy = SchedulerRunRecord(
            run_id=consent.run_id,
            consent_manifest_id=consent.manifest_id,
            state=SchedulerRunState.FAILED,
            provider=consent.provider,
            usage=legacy_usage,
            succeeded_jobs=0,
            partial_jobs=0,
            failed_jobs=len(prepared.scheduled_jobs),
            refused_jobs=0,
            cancelled_jobs=0,
            compatibility_id=compatibility_id,
            cumulative_usage=legacy_usage,
        ).to_dict()
        project.m13_persistence().put_run(
            consent.run_id,
            legacy,
            authority_binding=prepared.authority.binding.to_dict(),
        )

        with pytest.raises(
            SchedulerConfigurationError,
            match="legacy cumulative usage overlaps durable state without provenance",
        ):
            run_prepared_scene_jobs(
                project,
                provider,
                prepared,
                consent,
                policy=_policy(),
            )

    assert provider.calls == []


def test_opaque_legacy_checkpoint_allows_zero_submit_cache_replay(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    first_provider = DeterministicNarrativeProvider()
    with _project(tmp_path) as project:
        prepared = prepare_narrative_scene_run(
            project,
            first_provider,
            run_id="run-legacy-cache-replay",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        first = run_prepared_scene_jobs(
            project,
            first_provider,
            prepared,
            consent,
            policy=_policy(),
        )
        lookup = project.m13_persistence().lookup(
            RecordKind.RUN,
            consent.run_id,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        assert lookup.state is LookupState.HIT
        assert lookup.payload is not None
        legacy = dict(lookup.payload)
        legacy.pop("usage_checkpoint", None)
        legacy.pop("prior_cumulative_usage", None)
        legacy.pop("current_phase_usage", None)
        project.m13_persistence().put_run(
            consent.run_id,
            legacy,
            authority_binding=prepared.authority.binding.to_dict(),
        )

    replay_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        replay = prepare_narrative_scene_run(
            project,
            replay_provider,
            run_id="run-legacy-cache-replay",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        replay_result = run_prepared_scene_jobs(
            project,
            replay_provider,
            replay,
            grant_narrative_consent(project, replay),
            policy=_policy(),
        )

    assert replay_provider.calls == []
    assert replay_result.record.usage.provider_calls == 0
    assert replay_result.record.cumulative_usage == first.record.cumulative_usage
    assert all(item.cache_replay for item in replay_result.jobs)

    repeated_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        retained = project.m13_persistence().lookup(
            RecordKind.RUN,
            consent.run_id,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        assert retained.state is LookupState.HIT
        assert retained.payload is not None
        assert "usage_checkpoint" not in retained.payload
        repeated = prepare_narrative_scene_run(
            project,
            repeated_provider,
            run_id="run-legacy-cache-replay",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        repeated_result = run_prepared_scene_jobs(
            project,
            repeated_provider,
            repeated,
            grant_narrative_consent(project, repeated),
            policy=_policy(),
        )

    assert repeated_provider.calls == []
    assert repeated_result.record.cumulative_usage == first.record.cumulative_usage


@pytest.mark.parametrize("mutation", ["duplicate", "changed_state"])
def test_checkpoint_rejects_duplicate_or_changed_covered_event(
    tmp_path: Path,
    mutation: str,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    with _project(tmp_path) as project:
        provider = DeterministicNarrativeProvider()
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-checkpoint-covered-event-validation",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        run_prepared_scene_jobs(
            project,
            provider,
            prepared,
            consent,
            policy=_policy(),
        )
        lookup = project.m13_persistence().lookup(
            RecordKind.RUN,
            consent.run_id,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        assert lookup.state is LookupState.HIT
        assert lookup.payload is not None
        payload = deepcopy(dict(lookup.payload))
        checkpoint = payload["usage_checkpoint"]
        assert isinstance(checkpoint, dict)
        covered = checkpoint["covered_events"]
        assert isinstance(covered, list) and covered
        if mutation == "duplicate":
            covered.append(deepcopy(covered[0]))
        else:
            assert isinstance(covered[0], dict)
            covered[0]["state"] = "finalized:changed"
        project.m13_persistence().put_run(
            consent.run_id,
            payload,
            authority_binding=prepared.authority.binding.to_dict(),
        )

    with Project.open(project_path) as project:
        resumed = prepare_narrative_scene_run(
            project,
            DeterministicNarrativeProvider(),
            run_id="run-checkpoint-covered-event-validation",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        resumed_consent = grant_narrative_consent(project, resumed)
        sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            resumed.scheduled_jobs,
            authority_binding=resumed.authority.binding.to_dict(),
        )
        expected = "malformed" if mutation == "duplicate" else "covered event changed"
        with pytest.raises(ValueError, match=expected):
            sink.resume_usage(
                resumed_consent,
                resumed.scheduled_jobs,
                scheduler_compatibility_id(
                    resumed_consent, resumed.scheduled_jobs
                ),
            )


def test_restart_after_timeout_includes_failed_usage_before_retry(tmp_path: Path) -> None:
    @dataclass
    class TimeoutProvider(DeterministicNarrativeProvider):
        def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
            del cancelled
            self.calls.append(request)
            raise ProviderTimeoutError(
                "provider_timeout",
                "SECRET-STORY timeout detail",
                transient=True,
            )

    project_path = tmp_path / "m13-workflow.rsmproj"
    timeout_provider = TimeoutProvider()
    with _project(tmp_path) as project:
        first = prepare_narrative_scene_run(
            project,
            timeout_provider,
            run_id="run-timeout-resume",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, first)
        failed = run_prepared_scene_jobs(
            project,
            timeout_provider,
            first,
            consent,
            policy=SchedulerPolicy(
                _batch_limits(),
                maximum_transient_attempts_per_job=1,
            ),
        )
    failed_call_count = len(timeout_provider.calls)
    assert failed_call_count > 0
    assert failed.record.usage.provider_calls == failed_call_count
    assert failed.record.usage.input_tokens > 0

    retry_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        resumed = prepare_narrative_scene_run(
            project,
            retry_provider,
            run_id="run-timeout-resume",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        retried = run_prepared_scene_jobs(
            project,
            retry_provider,
            resumed,
            grant_narrative_consent(project, resumed),
            policy=SchedulerPolicy(
                _batch_limits(),
                maximum_transient_attempts_per_job=2,
            ),
        )

        attempts = project.m13_persistence().list_records(
            RecordKind.ATTEMPT,
            authority_binding=resumed.authority.binding.to_dict(),
        )

    assert retry_provider.calls
    assert retried.record.usage.provider_calls == (
        failed.record.usage.provider_calls + len(retry_provider.calls)
    )
    assert retried.record.usage.input_tokens > failed.record.usage.input_tokens
    assert all(
        item.payload is not None
        and "SECRET-STORY" not in repr(item.payload)
        and item.payload["metrics"]["input_tokens"] > 0
        for item in attempts
    )


def test_unresolved_call_reservation_recovers_once_and_finalizes_idempotently(
    tmp_path: Path,
) -> None:
    with _project(tmp_path) as project:
        provider = DeterministicNarrativeProvider()
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-reservation-recovery",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        compatibility_id = scheduler_compatibility_id(consent, prepared.scheduled_jobs)
        sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            prepared.scheduled_jobs,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        job = prepared.scheduled_jobs[0]
        legacy_attempt = SchedulerAttemptRecord(
            attempt_id="m13_attempt_test_legacy",
            run_id=consent.run_id,
            logical_job_id=job.logical_job_id,
            attempt_number=1,
            batch_id="batch:legacy",
            outcome=AttemptOutcome.TIMEOUT,
            provider=consent.provider,
            metrics=AttemptMetrics(100, 20, 4, cost_micros=5),
            error_code="timeout",
            consent_manifest_id=consent.manifest_id,
            input_revision_id=job.input_revision_id,
            cache_key=job.cache_identity.key,
            provider_call_number=1,
            transmitted=True,
        )
        sink.record_attempt(legacy_attempt)
        reservation = SchedulerCallReservation(
            reservation_id="m13_reservation_test_recovery",
            run_id=consent.run_id,
            consent_manifest_id=consent.manifest_id,
            compatibility_id=compatibility_id,
            batch_id="batch:test",
            logical_job_ids=(job.logical_job_id,),
            logical_attempt_numbers=(2,),
            provider_call_number=2,
            provider=consent.provider,
            usage=SchedulerUsage(
                provider_calls=1,
                input_tokens=50,
                output_tokens=10,
                elapsed_ms=7,
                cost_micros=3,
                peak_concurrency=1,
                usage_estimated=True,
            ),
        )

        sink.reserve_call(reservation)
        sink.reserve_call(reservation)
        unresolved = sink.resume_usage(
            consent, prepared.scheduled_jobs, compatibility_id
        ).current_phase_usage
        assert unresolved == SchedulerUsage(
            provider_calls=2,
            input_tokens=150,
            output_tokens=30,
            elapsed_ms=11,
            cost_micros=8,
            peak_concurrency=1,
            usage_estimated=True,
        )

        covered_attempt = SchedulerAttemptRecord(
            attempt_id="m13_attempt_test_reserved",
            run_id=consent.run_id,
            logical_job_id=job.logical_job_id,
            attempt_number=2,
            batch_id=reservation.batch_id,
            outcome=AttemptOutcome.TIMEOUT,
            provider=consent.provider,
            metrics=AttemptMetrics(40, 8, 6, cost_micros=2),
            error_code="timeout",
            consent_manifest_id=consent.manifest_id,
            input_revision_id=job.input_revision_id,
            cache_key=job.cache_identity.key,
            provider_call_number=2,
            transmitted=True,
        )
        sink.record_attempt(covered_attempt)
        still_unresolved = sink.resume_usage(
            consent,
            prepared.scheduled_jobs,
            compatibility_id,
        ).current_phase_usage
        assert still_unresolved == unresolved

        finalization = SchedulerCallFinalization(
            reservation_id=reservation.reservation_id,
            run_id=reservation.run_id,
            consent_manifest_id=reservation.consent_manifest_id,
            compatibility_id=reservation.compatibility_id,
            transmission_disposition=TransmissionDisposition.UNKNOWN,
            usage=SchedulerUsage(
                provider_calls=1,
                input_tokens=40,
                output_tokens=8,
                elapsed_ms=6,
                cost_micros=2,
                peak_concurrency=1,
                usage_estimated=True,
            ),
        )
        sink.finalize_call(finalization)
        sink.finalize_call(finalization)
        finalized = sink.resume_usage(
            consent, prepared.scheduled_jobs, compatibility_id
        ).current_phase_usage
        assert finalized == SchedulerUsage(
            provider_calls=2,
            input_tokens=140,
            output_tokens=28,
            elapsed_ms=10,
            cost_micros=7,
            peak_concurrency=1,
            usage_estimated=True,
        )

        with pytest.raises(ValueError, match="conflicting call finalization"):
            sink.finalize_call(
                replace(
                    finalization,
                    usage=replace(finalization.usage, input_tokens=91),
                )
            )


def test_cross_phase_reopen_adds_prior_usage_to_unfinished_durable_call(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    limits = replace(_limits(), max_provider_calls=5)
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        raw_scenes = authority.scene_model.get("scenes")
        assert isinstance(raw_scenes, list) and raw_scenes
        first_scene = raw_scenes[0]
        assert isinstance(first_scene, dict)
        scene_id = first_scene.get("id")
        assert isinstance(scene_id, str)
        provider = DeterministicNarrativeProvider()
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-cross-phase-unfinished-call",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=limits,
            batch_limits=_batch_limits(),
            selected_scene_ids=(scene_id,),
        )
        consent = grant_narrative_consent(project, prepared)
        compatibility_id = scheduler_compatibility_id(
            consent, prepared.scheduled_jobs
        )
        job = prepared.scheduled_jobs[0]
        sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            prepared.scheduled_jobs,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        sink.reserve_call(
            SchedulerCallReservation(
                reservation_id="m13_reservation_cross_phase_interrupted",
                run_id=consent.run_id,
                consent_manifest_id=consent.manifest_id,
                compatibility_id=compatibility_id,
                batch_id="batch:cross-phase-interrupted",
                logical_job_ids=(job.logical_job_id,),
                logical_attempt_numbers=(1,),
                provider_call_number=1,
                provider=consent.provider,
                usage=SchedulerUsage(
                    provider_calls=1,
                    input_tokens=40,
                    output_tokens=20,
                    elapsed_ms=7,
                    cost_micros=3,
                    peak_concurrency=2,
                    usage_estimated=True,
                ),
            )
        )

    resumed_provider = DeterministicNarrativeProvider()
    prior = SchedulerUsage(
        provider_calls=4,
        input_tokens=60,
        output_tokens=30,
        elapsed_ms=11,
        cost_micros=5,
        peak_concurrency=4,
    )
    with Project.open(project_path) as project:
        resumed = prepare_narrative_scene_run(
            project,
            resumed_provider,
            run_id="run-cross-phase-unfinished-call",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=limits,
            batch_limits=_batch_limits(),
            selected_scene_ids=(scene_id,),
        )
        result = run_prepared_scene_jobs(
            project,
            resumed_provider,
            resumed,
            grant_narrative_consent(project, resumed),
            policy=_policy(),
            initial_usage=prior,
        )

    assert resumed_provider.calls == []
    assert result.record.state is SchedulerRunState.HARD_LIMIT
    assert result.record.cumulative_usage is not None
    assert replace(result.record.cumulative_usage, elapsed_ms=18) == SchedulerUsage(
        provider_calls=5,
        input_tokens=100,
        output_tokens=50,
        elapsed_ms=18,
        cost_micros=8,
        peak_concurrency=4,
        usage_estimated=True,
    )
    assert result.record.cumulative_usage.elapsed_ms >= 18
    assert result.jobs[0].attempt_count == 1
    assert result.jobs[0].error_code == "hard_limit"

    repeated_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        repeated = prepare_narrative_scene_run(
            project,
            repeated_provider,
            run_id="run-cross-phase-unfinished-call",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=limits,
            batch_limits=_batch_limits(),
            selected_scene_ids=(scene_id,),
        )
        repeated_result = run_prepared_scene_jobs(
            project,
            repeated_provider,
            repeated,
            grant_narrative_consent(project, repeated),
            policy=_policy(),
        )

    assert repeated_provider.calls == []
    assert repeated_result.record.cumulative_usage is not None
    assert result.record.cumulative_usage is not None
    assert replace(
        repeated_result.record.cumulative_usage,
        elapsed_ms=result.record.cumulative_usage.elapsed_ms,
    ) == result.record.cumulative_usage
    assert repeated_result.record.cumulative_usage.elapsed_ms >= (
        result.record.cumulative_usage.elapsed_ms
    )


def test_not_transmitted_reservation_matches_zero_call_attempt_after_reopen(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    with _project(tmp_path) as project:
        provider = DeterministicNarrativeProvider()
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-not-transmitted-reservation",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        compatibility_id = scheduler_compatibility_id(consent, prepared.scheduled_jobs)
        job = prepared.scheduled_jobs[0]
        sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            prepared.scheduled_jobs,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        reservation = SchedulerCallReservation(
            reservation_id="m13_reservation_test_not_transmitted",
            run_id=consent.run_id,
            consent_manifest_id=consent.manifest_id,
            compatibility_id=compatibility_id,
            batch_id="batch:not-transmitted",
            logical_job_ids=(job.logical_job_id,),
            logical_attempt_numbers=(1,),
            provider_call_number=1,
            provider=consent.provider,
            usage=SchedulerUsage(
                provider_calls=1,
                input_tokens=50,
                output_tokens=10,
                elapsed_ms=7,
                cost_micros=3,
                peak_concurrency=1,
                usage_estimated=True,
            ),
        )
        sink.reserve_call(reservation)
        sink.record_attempt(
            SchedulerAttemptRecord(
                attempt_id="m13_attempt_test_not_transmitted",
                run_id=consent.run_id,
                logical_job_id=job.logical_job_id,
                attempt_number=1,
                batch_id=reservation.batch_id,
                outcome=AttemptOutcome.MALFORMED,
                provider=consent.provider,
                metrics=AttemptMetrics(0, 0, 6, cost_micros=0),
                error_code="internal_error",
                consent_manifest_id=consent.manifest_id,
                input_revision_id=job.input_revision_id,
                cache_key=job.cache_identity.key,
                provider_call_number=0,
                transmitted=False,
            )
        )
        sink.finalize_call(
            SchedulerCallFinalization(
                reservation_id=reservation.reservation_id,
                run_id=reservation.run_id,
                consent_manifest_id=reservation.consent_manifest_id,
                compatibility_id=reservation.compatibility_id,
                transmission_disposition=TransmissionDisposition.NOT_TRANSMITTED,
                usage=SchedulerUsage(elapsed_ms=6),
            )
        )

    with Project.open(project_path) as project:
        resumed = prepare_narrative_scene_run(
            project,
            DeterministicNarrativeProvider(),
            run_id="run-not-transmitted-reservation",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        resumed_consent = grant_narrative_consent(project, resumed)
        resumed_sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            resumed.scheduled_jobs,
            authority_binding=resumed.authority.binding.to_dict(),
        )
        resumed_compatibility_id = scheduler_compatibility_id(
            resumed_consent,
            resumed.scheduled_jobs,
        )
        usage = resumed_sink.resume_usage(
            resumed_consent,
            resumed.scheduled_jobs,
            resumed_compatibility_id,
        ).current_phase_usage
        resumed_job = next(
            item
            for item in resumed.scheduled_jobs
            if item.logical_job_id == job.logical_job_id
        )
        history = resumed_sink.attempt_history(
            resumed_consent.run_id,
            resumed_consent.manifest_id,
            resumed_job,
        )

    assert usage == SchedulerUsage(elapsed_ms=6)
    assert history == (AttemptOutcome.MALFORMED,)


def test_unresolved_call_reservation_consumes_attempt_ceiling_after_reopen(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    with _project(tmp_path) as project:
        provider = DeterministicNarrativeProvider()
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-reservation-attempt-ceiling",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        compatibility_id = scheduler_compatibility_id(consent, prepared.scheduled_jobs)
        job = prepared.scheduled_jobs[0]
        sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            prepared.scheduled_jobs,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        sink.reserve_call(
            SchedulerCallReservation(
                reservation_id="m13_reservation_test_attempt_ceiling",
                run_id=consent.run_id,
                consent_manifest_id=consent.manifest_id,
                compatibility_id=compatibility_id,
                batch_id="batch:interrupted",
                logical_job_ids=(job.logical_job_id,),
                logical_attempt_numbers=(1,),
                provider_call_number=1,
                provider=consent.provider,
                usage=SchedulerUsage(
                    provider_calls=1,
                    input_tokens=50,
                    output_tokens=10,
                    elapsed_ms=7,
                    cost_micros=3,
                    peak_concurrency=1,
                    usage_estimated=True,
                ),
            )
        )
        reserved_job_id = job.logical_job_id

    retry_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        resumed = prepare_narrative_scene_run(
            project,
            retry_provider,
            run_id="run-reservation-attempt-ceiling",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        resumed_consent = grant_narrative_consent(project, resumed)
        run_prepared_scene_jobs(
            project,
            retry_provider,
            resumed,
            resumed_consent,
            policy=SchedulerPolicy(
                _batch_limits(),
                maximum_attempts_per_job=1,
                maximum_transient_attempts_per_job=1,
                maximum_malformed_attempts_per_job=1,
            ),
        )

    submitted_job_ids = {
        item.logical_job_id
        for request in retry_provider.calls
        for item in request.items
    }
    assert reserved_job_id not in submitted_job_ids


@pytest.mark.parametrize("persist_second_attempt", [False, True])
def test_duplicate_unresolved_reservations_preserve_attempt_multiplicity_after_reopen(
    tmp_path: Path,
    persist_second_attempt: bool,
) -> None:
    project_path = tmp_path / "m13-workflow.rsmproj"
    with _project(tmp_path) as project:
        provider = DeterministicNarrativeProvider()
        prepared = prepare_narrative_scene_run(
            project,
            provider,
            run_id="run-duplicate-reservation-attempt-ceiling",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        consent = grant_narrative_consent(project, prepared)
        compatibility_id = scheduler_compatibility_id(consent, prepared.scheduled_jobs)
        job = prepared.scheduled_jobs[0]
        sink = M13SchedulerPersistenceSink(
            project.m13_persistence(),
            prepared.scheduled_jobs,
            authority_binding=prepared.authority.binding.to_dict(),
        )
        for call_number in (1, 2):
            sink.reserve_call(
                SchedulerCallReservation(
                    reservation_id=f"m13_reservation_test_duplicate_{call_number}",
                    run_id=consent.run_id,
                    consent_manifest_id=consent.manifest_id,
                    compatibility_id=compatibility_id,
                    batch_id="batch:interrupted",
                    logical_job_ids=(job.logical_job_id,),
                    logical_attempt_numbers=(1,),
                    provider_call_number=call_number,
                    provider=consent.provider,
                    usage=SchedulerUsage(
                        provider_calls=1,
                        input_tokens=50,
                        output_tokens=10,
                        elapsed_ms=7,
                        cost_micros=3,
                        peak_concurrency=1,
                        usage_estimated=True,
                    ),
                )
            )
        if persist_second_attempt:
            sink.record_attempt(
                SchedulerAttemptRecord(
                    attempt_id="m13_attempt_test_duplicate_2",
                    run_id=consent.run_id,
                    logical_job_id=job.logical_job_id,
                    attempt_number=1,
                    batch_id="batch:interrupted",
                    outcome=AttemptOutcome.TIMEOUT,
                    provider=consent.provider,
                    metrics=AttemptMetrics(40, 8, 6, cost_micros=2),
                    error_code="timeout",
                    consent_manifest_id=consent.manifest_id,
                    input_revision_id=job.input_revision_id,
                    cache_key=job.cache_identity.key,
                    provider_call_number=2,
                    transmitted=True,
                )
            )
        reserved_job_id = job.logical_job_id

    retry_provider = DeterministicNarrativeProvider()
    with Project.open(project_path) as project:
        resumed = prepare_narrative_scene_run(
            project,
            retry_provider,
            run_id="run-duplicate-reservation-attempt-ceiling",
            requested_model="runtime-selected-model",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
        )
        resumed_consent = grant_narrative_consent(project, resumed)
        run_prepared_scene_jobs(
            project,
            retry_provider,
            resumed,
            resumed_consent,
            policy=SchedulerPolicy(
                _batch_limits(),
                maximum_attempts_per_job=2,
                maximum_transient_attempts_per_job=2,
                maximum_malformed_attempts_per_job=2,
            ),
        )

    submitted_job_ids = {
        item.logical_job_id
        for request in retry_provider.calls
        for item in request.items
    }
    assert reserved_job_id not in submitted_job_ids


def test_model_invalidation_can_persist_different_accepted_claim_content(
    tmp_path: Path,
) -> None:
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=False)
        raw_scenes = authority.scene_model["scenes"]
        assert isinstance(raw_scenes, list)
        scene_id = str(raw_scenes[0]["id"])

        first_provider = DeterministicNarrativeProvider(claim_value_prefix="first")
        first = prepare_narrative_scene_run(
            project,
            first_provider,
            run_id="claim-generation-first",
            requested_model="simulated-provider-identity-a",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
            selected_scene_ids=(scene_id,),
        )
        first_result = run_prepared_scene_jobs(
            project,
            first_provider,
            first,
            grant_narrative_consent(project, first),
            policy=_policy(),
        )

        second_provider = DeterministicNarrativeProvider(claim_value_prefix="second")
        second = prepare_narrative_scene_run(
            project,
            second_provider,
            run_id="claim-generation-second",
            requested_model="simulated-provider-identity-b",
            mode=NarrativeInputMode.FACT_ONLY,
            include_m12_material=False,
            limits=_limits(),
            batch_limits=_batch_limits(),
            selected_scene_ids=(scene_id,),
        )
        second_result = run_prepared_scene_jobs(
            project,
            second_provider,
            second,
            grant_narrative_consent(project, second),
            policy=_policy(),
        )

        assert first_provider.calls and second_provider.calls
        assert first_result.jobs[0].artifact_id != second_result.jobs[0].artifact_id
        claim_records = project.m13_persistence().list_records(RecordKind.CLAIM)
        texts = {
            str(item.payload["text"])
            for item in claim_records
            if item.state is LookupState.HIT and item.payload is not None
        }
        assert any("first-0" in text for text in texts)
        assert any("second-0" in text for text in texts)

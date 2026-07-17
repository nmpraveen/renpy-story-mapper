from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import BudgetLimits, ProviderIdentity, ProviderSettings
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
    ProviderUsage,
)
from renpy_story_mapper.narrative.scheduler import SchedulerPolicy
from renpy_story_mapper.narrative.workflow import (
    grant_narrative_consent,
    prepare_narrative_scene_run,
    run_prepared_scene_jobs,
)
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

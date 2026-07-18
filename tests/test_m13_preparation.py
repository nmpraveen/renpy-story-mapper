from __future__ import annotations

from pathlib import Path

import pytest

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import (
    BudgetLimits,
    PrivacyMode,
    ProviderIdentity,
    ProviderSettings,
)
from renpy_story_mapper.narrative.preparation import (
    ProviderPricing,
    build_cloud_consent,
    plan_scene_run,
    prepare_scene_jobs,
)
from renpy_story_mapper.narrative.projection import NarrativeInputMode
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


def _project(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "m13-preparation.rsmproj", source)


def _provider() -> ProviderIdentity:
    return ProviderIdentity(
        provider="approved-cloud",
        adapter="structured-adapter",
        adapter_version="adapter-v1",
        requested_model="selected-model",
        resolved_model="selected-model",
        settings=ProviderSettings(),
    )


def _limits(*, max_calls: int = 100) -> BudgetLimits:
    return BudgetLimits(
        max_provider_calls=max_calls,
        max_input_tokens=10_000_000,
        max_output_tokens=10_000_000,
        max_total_tokens=20_000_000,
        timeout_seconds=300,
        max_concurrency=4,
        max_cost_micros=10_000_000,
    )


def test_scene_jobs_bind_exact_context_and_prompt_local_support(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=False)

    jobs = prepare_scene_jobs(authority, mode=NarrativeInputMode.FACT_ONLY)
    raw_scenes = authority.scene_model["scenes"]
    assert isinstance(raw_scenes, list)
    assert len(jobs) == len(raw_scenes)
    assert len({item.job.spec.job_id for item in jobs}) == len(jobs)
    assert len({item.job.input_revision.identity for item in jobs}) == len(jobs)
    assert all(item.job.spec.context.structural_fingerprint for item in jobs)
    assert all(item.payload["privacy_mode"] == "fact_only" for item in jobs)
    assert all("provider" not in item.payload for item in jobs)

    first = jobs[0]
    handles = [item.handle for item in first.handles.evidence_handles]
    assert handles == [f"E{ordinal}" for ordinal in range(1, len(handles) + 1)]
    assert all(
        item.reference.owner_id == first.job.spec.owner_id
        for item in first.handles.evidence_handles
    )
    assert {item.reference.authority.value for item in first.handles.evidence_handles} <= {
        "m10",
        "m11",
    }
    assert canonical_json(first.payload) == canonical_json(first.payload)
    assert first.job.input_revision.normalized_input_hash


def test_scene_selection_is_stable_and_rejects_unknown_scope(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=False)

    all_jobs = prepare_scene_jobs(authority, mode=NarrativeInputMode.FACT_ONLY)
    selected_id = all_jobs[-1].job.spec.owner_id
    selected = prepare_scene_jobs(
        authority,
        mode=NarrativeInputMode.FACT_ONLY,
        selected_scene_ids=(selected_id,),
    )

    assert len(selected) == 1
    assert selected[0].job.spec.job_id == all_jobs[-1].job.spec.job_id
    assert selected[0].ordinal == all_jobs[-1].ordinal
    with pytest.raises(ValueError, match="outside current M11"):
        prepare_scene_jobs(
            authority,
            mode=NarrativeInputMode.FACT_ONLY,
            selected_scene_ids=("unknown-scene",),
        )


def test_batch_estimate_and_cloud_consent_cover_one_selected_run(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        authority = load_narrative_authority(project, include_m12=False)
    jobs = prepare_scene_jobs(authority, mode=NarrativeInputMode.FACT_ONLY)
    run = plan_scene_run(
        jobs,
        batch_limits=BatchLimits(2, 1_000_000, 1_000_000),
        pricing=ProviderPricing(500_000, 1_500_000),
    )

    assert run.estimate.logical_job_count == len(jobs)
    assert run.estimate.provider_call_count == (len(jobs) + 1) // 2
    assert run.estimate.estimated_cost_micros is not None
    manifest = build_cloud_consent(
        run,
        run_id="run-scene-scope",
        provider=_provider(),
        selected_scope_ids=("all-scenes",),
        privacy_mode=PrivacyMode.FACT_ONLY,
        includes_m12_material=False,
        limits=_limits(),
    )
    assert manifest.consent_granted is False
    assert manifest.estimate.provider_call_count == len(run.batches)
    assert manifest.includes_m12_material is False

    with pytest.raises(ValueError, match="calls exceed"):
        build_cloud_consent(
            run,
            run_id="run-too-small",
            provider=_provider(),
            selected_scope_ids=("all-scenes",),
            privacy_mode=PrivacyMode.FACT_ONLY,
            includes_m12_material=False,
            limits=_limits(max_calls=1),
            consent_granted=True,
        )


def test_relevant_m12_status_is_an_exact_owned_support_record(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        service = M12RouteService(project)
        nodes = service.destinations(limit=50)["nodes"]
        assert isinstance(nodes, list)
        destination = next(
            item
            for item in nodes
            if isinstance(item, dict) and item["kind"] == "generic_scene"
        )
        outcome = service.solve(
            service.prepare(str(destination["kind"]), str(destination["target_id"]))
        )
        assert outcome.result is not None
        authority = load_narrative_authority(project, include_m12=True)

    jobs = prepare_scene_jobs(authority, mode=NarrativeInputMode.FACT_ONLY)
    m12_records = [
        record
        for job in jobs
        for record in job.payload["support_records"]  # type: ignore[union-attr]
        if isinstance(record, dict) and record.get("authority") == "m12"
    ]
    assert m12_records
    route_record = m12_records[0]["record"]
    assert isinstance(route_record, dict)
    assert route_record["status"] == outcome.result["status"]
    assert route_record["badge"] == outcome.result["badge"]


def test_scene_jobs_bind_exact_prompt_local_m12_claims_and_disable_cleanly(
    tmp_path: Path,
) -> None:
    with _project(tmp_path) as project:
        service = M12RouteService(project)
        destination = next(
            item
            for item in service.destinations(limit=50)["nodes"]
            if item["kind"] == "generic_scene"
        )
        outcome = service.solve(
            service.prepare(str(destination["kind"]), str(destination["target_id"]))
        )
        assert outcome.result is not None
        authority = load_narrative_authority(project, include_m12=True)

    enabled = prepare_scene_jobs(
        authority,
        mode=NarrativeInputMode.FACT_ONLY,
        include_m12_material=True,
    )
    enabled_with_m12 = [item for item in enabled if item.authority_claims]
    assert enabled_with_m12
    for job in enabled_with_m12:
        prompt_claims = job.payload["exact_m12_authority_claims"]
        assert isinstance(prompt_claims, list)
        assert len(prompt_claims) == len(job.authority_claims)
        assert {str(item["text"]) for item in prompt_claims} == {
            claim.text for claim in job.authority_claims
        }
        assert all(
            reference.owner_id == job.job.spec.owner_id
            for claim in job.authority_claims
            for reference in claim.support.direct_evidence
        )

    disabled = prepare_scene_jobs(
        authority,
        mode=NarrativeInputMode.FACT_ONLY,
        include_m12_material=False,
    )
    assert all(not item.authority_claims for item in disabled)
    assert all(item.payload["exact_m12_authority_claims"] == [] for item in disabled)
    assert all(
        handle.reference.authority.value != "m12"
        for item in disabled
        for handle in item.handles.evidence_handles
    )

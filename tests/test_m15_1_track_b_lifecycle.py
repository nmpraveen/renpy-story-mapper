from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    EvidenceNavigation,
    Provenance,
    SourceLocator,
)
from renpy_story_mapper.narrative_map.persistence import NarrativeMapRepository
from renpy_story_mapper.narrative_map.provider import (
    NarrativeConsentManifest,
    NarrativeMapProviderError,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    ProviderProfile,
    SterileNarrativeMapProvider,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    ChoiceComposition,
    FineNarrativeUnit,
    MajorCluster,
    NarrativeGapCandidate,
    SemanticBeat,
    SemanticBuildState,
    SemanticOutline,
)
from renpy_story_mapper.narrative_map.semantic_projection import (
    FrozenSummaryInput,
    SemanticEvidenceRecord,
    prepare_semantic_boundary_jobs,
    prepare_semantic_summary_jobs,
)
from renpy_story_mapper.narrative_map.semantic_validation import (
    validate_semantic_boundary_response,
    validate_semantic_summary_response,
)
from renpy_story_mapper.narrative_map.service import NarrativeMapService
from renpy_story_mapper.narrative_map.workflow import NarrativeWorkflowReport
from renpy_story_mapper.organization.sterile_runner import SterileRunRequest, SterileRunResult
from renpy_story_mapper.project import Project


def _authority() -> AuthorityBinding:
    return AuthorityBinding("generation", "m10-v1", "m10-hash", "m11-v1", "m11-hash")


def _profile() -> ProviderProfile:
    return ProviderProfile(
        "fake",
        "deterministic-fake",
        "2",
        "fake-semantic-model",
        ProviderSettings((("reasoning_effort", "high"),)),
    )


def _consent(jobs: tuple[object, ...]) -> NarrativeConsentManifest:
    return NarrativeConsentManifest.for_jobs(
        run_id="synthetic-semantic-run",
        profile=_profile(),
        jobs=jobs,
        consent_granted=True,
    )


def _units(count: int = 3) -> tuple[FineNarrativeUnit, ...]:
    return tuple(
        FineNarrativeUnit(
            authority=_authority(),
            sequence_id="day-1",
            ordinal=index,
            story_atom_id=f"atom-{index}",
            story_locator=SourceLocator("game/day1.rpy", index + 1, index + 1, "reconstructed"),
            technical_context_atom_ids=(),
            node_ids=(f"node-{index}",),
            evidence_ids=(f"evidence-{index}",),
            speaker_ids=("Ava",),
            context_ids=("day-1",),
            lane_id="main",
            call_occurrence_id=None,
            loop_id=None,
            parent_choice_id=None,
            parent_arm_id=None,
            entry_node_id=f"node-{index}",
            exit_node_id=f"node-{index}",
            incident_edge_ids=(),
            provenance=Provenance(
                atom_ids=(f"atom-{index}",),
                node_ids=(f"node-{index}",),
                evidence_ids=(f"evidence-{index}",),
            ),
        )
        for index in range(count)
    )


def _candidates(units: tuple[FineNarrativeUnit, ...]) -> tuple[NarrativeGapCandidate, ...]:
    return tuple(
        NarrativeGapCandidate(
            _authority(),
            "day-1",
            index,
            left.unit_id,
            right.unit_id,
            "main",
            None,
            None,
            None,
            None,
            (left.evidence_ids[0], right.evidence_ids[0]),
        )
        for index, (left, right) in enumerate(pairwise(units))
    )


def _windows(
    units: tuple[FineNarrativeUnit, ...],
    candidates: tuple[NarrativeGapCandidate, ...],
    *,
    batched: bool = True,
) -> tuple[BoundaryWindow, ...]:
    if batched:
        return (
            BoundaryWindow(
                _authority(),
                0,
                tuple(item.candidate_id for item in candidates),
                tuple(item.unit_id for item in units),
                len(units),
            ),
        )
    return tuple(
        BoundaryWindow(
            _authority(),
            index,
            (candidate.candidate_id,),
            (units[index].unit_id, units[index + 1].unit_id),
            2,
        )
        for index, candidate in enumerate(candidates)
    )


def _evidence(
    units: tuple[FineNarrativeUnit, ...],
) -> dict[str, tuple[SemanticEvidenceRecord, ...]]:
    return {
        unit.unit_id: (
            SemanticEvidenceRecord(
                unit.unit_id,
                unit.story_atom_id,
                unit.evidence_ids[0],
                unit.ordinal,
                "dialogue",
                f"Ava takes story action {unit.ordinal}.",
                "Ava",
                unit.story_locator,
            ),
        )
        for unit in units
    }


def _boundary_payload(window: BoundaryWindow) -> dict[str, object]:
    return {
        "window_id": window.window_id,
        "decisions": [
            {
                "candidate_id": candidate_id,
                "decision": ("new_beat_same_cluster" if index == 0 else "new_major_cluster"),
                "reason": "The immediate story objective changes.",
                "confidence": 0.9,
                "warnings": [],
            }
            for index, candidate_id in enumerate(window.owned_candidate_ids)
        ],
    }


class _FakeProvider:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.requests: list[NarrativeMapProviderRequest] = []
        self.cancel_count = 0

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        payload = self.payloads.pop(0)
        profile = request.profile
        return NarrativeMapProviderResponse(
            request.request_id,
            ProviderIdentity(
                profile.provider,
                profile.adapter,
                profile.adapter_version,
                profile.requested_model,
                profile.requested_model,
                profile.settings,
            ),
            payload,
            ProviderUsage(100, 20, 5),
        )

    def cancel(self) -> None:
        self.cancel_count += 1


class _FakeSterileRunner:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[SterileRunRequest] = []

    def execute(
        self,
        request: SterileRunRequest,
        cancelled: Callable[[], bool],
    ) -> SterileRunResult:
        assert not cancelled()
        self.requests.append(request)
        return SterileRunResult(
            (
                {"item": {"type": "agent_message", "text": json.dumps(self.payload)}},
                {
                    "model": "fake-semantic-model",
                    "usage": {"input_tokens": 100, "output_tokens": 20, "cost_micros": 0},
                },
            ),
            "fake-cli",
        )

    def cancel(self) -> None:
        pass


class _BlockingProvider(_FakeProvider):
    def __init__(self, payload: dict[str, object], entered: Event, release: Event) -> None:
        super().__init__([payload])
        self.entered = entered
        self.release = release

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().submit(request, cancelled)


class _BlockingSequenceProvider(_FakeProvider):
    def __init__(
        self,
        payloads: list[dict[str, object]],
        entered: Event,
        release: Event,
    ) -> None:
        super().__init__(payloads)
        self.entered = entered
        self.release = release

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        if not self.requests:
            self.entered.set()
            assert self.release.wait(timeout=5)
        return super().submit(request, cancelled)


class _BlockAfterFirstProvider(_FakeProvider):
    def __init__(
        self,
        payloads: list[dict[str, object]],
        entered: Event,
        release: Event,
    ) -> None:
        super().__init__(payloads)
        self.entered = entered
        self.release = release

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        if len(self.requests) == 1:
            self.entered.set()
            assert self.release.wait(timeout=5)
        return super().submit(request, cancelled)


class _EscapingProvider(_FakeProvider):
    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        if self.requests:
            self.requests.append(request)
            raise KeyboardInterrupt("synthetic task escape after durable reservation")
        return super().submit(request, cancelled)


def _outline(
    units: tuple[FineNarrativeUnit, ...],
    candidates: tuple[NarrativeGapCandidate, ...],
    service: NarrativeMapService,
    preparation: object,
) -> SemanticOutline:
    from renpy_story_mapper.narrative_map.semantic_lifecycle import SemanticStagePreparation

    assert isinstance(preparation, SemanticStagePreparation)
    boundary = service.semantic_boundary_output(preparation)
    beat = SemanticBeat(
        "beat-story",
        "cluster-day",
        tuple(item.unit_id for item in units),
        None,
        None,
        EvidenceNavigation("beat", "beat-story"),
    )
    cluster = MajorCluster(
        "cluster-day",
        0,
        (beat.beat_id,),
        (),
        EvidenceNavigation("major_cluster", "cluster-day"),
    )
    return SemanticOutline(
        _authority(),
        tuple(item.unit_id for item in units),
        tuple(item.candidate_id for item in candidates),
        (beat,),
        (cluster,),
        (),
        boundary.provenance,
    )


def _summary_inputs(
    outline: SemanticOutline,
    units: tuple[FineNarrativeUnit, ...],
) -> tuple[FrozenSummaryInput, ...]:
    unit_ids = tuple(item.unit_id for item in units)
    evidence_ids = tuple(item.evidence_ids[0] for item in units)
    return (
        FrozenSummaryInput("beat", outline.beats[0].beat_id, unit_ids, evidence_ids, ("Ava",)),
        FrozenSummaryInput(
            "major_cluster",
            outline.clusters[0].cluster_id,
            unit_ids,
            evidence_ids,
            ("Ava",),
        ),
    )


def _topology(outline: SemanticOutline) -> dict[str, object]:
    return {
        "schema": "m15-semantic-quotient-topology-v2",
        "canonical_hash": outline.authority.canonical_hash,
        "nodes": [],
        "edges": [],
    }


def _summary_payload(job: object, index: int) -> dict[str, object]:
    from renpy_story_mapper.narrative_map.provider import PreparedNarrativeJob

    assert isinstance(job, PreparedNarrativeJob)
    kind = "beat" if index == 0 else "major_cluster"
    return {
        "subject_kind": kind,
        "subject_id": job.subject_id,
        "membership_hash": job.membership_hash,
        "title": "A Difficult Arrival" if index == 0 else "The Day Begins",
        "summary": "Ava arrives, faces a difficult moment, and chooses how to continue.",
        "characters": ["Ava"],
        "claims": [
            {
                "claim_class": "factual",
                "text": "Ava takes the next supported action.",
                "evidence_ids": [job.known_evidence_ids[0]],
            }
        ],
        "warnings": [],
    }


def test_two_stage_build_publishes_atomically_and_reopens_with_zero_submit(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates)
    path = tmp_path / "semantic.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        boundaries = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="boundary-run",
            source_hash="source-hash",
            correction_id="m15.1",
            replay_existing=True,
        )
        assert boundaries.consent.consent_granted is False
        assert boundaries.consent.maximum_provider_calls == 2
        boundary_provider = _FakeProvider([_boundary_payload(windows[0])])
        boundary_report = service.start_boundaries(
            boundaries,
            provider=boundary_provider,
            consent=boundaries.granted_consent(),
        )
        assert boundary_report.provider_calls == 1
        assert len(boundary_provider.requests[0].job.subject.owned_candidate_ids) == 2
        boundary_output = service.semantic_boundary_output(boundaries)
        assert tuple(
            (item.candidate_id, item.window_id) for item in boundary_output.provenance
        ) == tuple(
            (candidate_id, window.window_id)
            for window in windows
            for candidate_id in window.owned_candidate_ids
        )

        outline = _outline(units, candidates, service, boundaries)
        quotient_topology = {
            "schema": "m15-semantic-quotient-topology-v2",
            "canonical_hash": outline.authority.canonical_hash,
            "nodes": [],
            "edges": [],
        }
        frozen = service.freeze_semantic_membership(
            boundaries,
            outline,
            quotient_topology,
        )
        assert frozen.record.state is SemanticBuildState.MEMBERSHIP_FROZEN
        summaries = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
            quotient_topology=quotient_topology,
            profile=_profile(),
            run_id="summary-run",
            source_hash="source-hash",
            correction_id="m15.1",
            replay_existing=True,
        )
        assert summaries.consent.manifest_id != boundaries.consent.manifest_id
        summary_provider = _FakeProvider(
            [_summary_payload(job, index) for index, job in enumerate(summaries.jobs)]
        )
        summary_report = service.start_summaries(
            summaries,
            provider=summary_provider,
            consent=summaries.granted_consent(),
        )
        assert summary_report.provider_calls == 2
        status = service.semantic_status()
        assert status is not None and status.record.state is SemanticBuildState.COMPLETE
        first_hash = status.record.published_map_hash
        first_publication = service.read_current_semantic_publication()
        assert first_publication is not None
        assert first_publication["publication_hash"] == first_hash
        assert first_publication["quotient_topology"] == quotient_topology
        assert all(
            item["subject_kind"] in {"beat", "major_cluster", "choice"}
            and item["subject_id"]
            for item in first_publication["summary_provenance"]
        )
        assert all(
            item["candidate_id"] and item["window_id"]
            for item in first_publication["outline"]["boundary_provenance"]
        )

    with Project.open(path) as reopened:
        service = NarrativeMapService(NarrativeMapRepository(reopened))
        replay_boundaries = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="ignored-because-exact-reopen",
            source_hash="source-hash",
            correction_id="m15.1",
            replay_existing=True,
        )
        boundary_provider = _FakeProvider([])
        boundary_report = service.start_boundaries(
            replay_boundaries,
            provider=boundary_provider,
            consent=replay_boundaries.consent,
        )
        assert boundary_report.provider_calls == 0
        assert boundary_provider.requests == []
        replay_outline = _outline(units, candidates, service, replay_boundaries)
        replay_summaries = service.prepare_summaries(
            replay_outline,
            _summary_inputs(replay_outline, units),
            _evidence(units),
            quotient_topology=quotient_topology,
            profile=_profile(),
            run_id="also-ignored-because-exact-reopen",
            source_hash="source-hash",
            correction_id="m15.1",
            replay_existing=True,
        )
        summary_provider = _FakeProvider([])
        summary_report = service.start_summaries(
            replay_summaries,
            provider=summary_provider,
            consent=replay_summaries.consent,
        )
        assert summary_report.provider_calls == 0
        assert summary_provider.requests == []
        status = service.semantic_status()
        assert status is not None and status.record.published_map_hash == first_hash
        assert service.read_current_semantic_publication() == first_publication

        changed = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="changed-correction-preview",
            source_hash="source-hash",
            correction_id="m15.1-revised",
        )
        failed = service.start_boundaries(
            changed,
            provider=_FakeProvider([{"bad": True}, {"still_bad": True}]),
            consent=changed.granted_consent(),
        )
        assert failed.failed_job_ids == (changed.jobs[0].job_id,)
        assert service.semantic_status().record.state is SemanticBuildState.FAILED
        assert service.read_current_semantic_publication() == first_publication


def test_sterile_adapter_uses_versioned_boundary_prompt_and_schema(tmp_path: Path) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    with Project.create(tmp_path / "sterile-routing.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="sterile-routing",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        consent = preparation.granted_consent()
        request = NarrativeMapProviderRequest(
            "semantic-boundary-request",
            consent,
            _profile(),
            preparation.jobs[0],
        )
        runner = _FakeSterileRunner(_boundary_payload(window))
        response = SterileNarrativeMapProvider(runner=runner).submit(request, lambda: False)

    assert response.payload == _boundary_payload(window)
    assert runner.requests[0].schema_path.name == "boundary_window_v3.schema.json"
    assert consent.version == "m15-narrative-consent-v1"
    assert consent.repair_policy_version is None
    with pytest.raises(ValueError, match="repair policy"):
        replace(consent, version="m15-narrative-consent-v2")
    assert preparation.jobs[0].response_schema == "m15-boundary-window-v3"
    stale_job = replace(preparation.jobs[0], response_schema="m15-boundary-window-v2")
    assert stale_job.job_id != preparation.jobs[0].job_id
    stale_runner = _FakeSterileRunner(_boundary_payload(window))
    stale_request = NarrativeMapProviderRequest(
        "semantic-boundary-stale",
        _consent((stale_job,)),
        _profile(),
        stale_job,
    )
    with pytest.raises(NarrativeMapProviderError) as exc_info:
        SterileNarrativeMapProvider(runner=stale_runner).submit(
            stale_request, lambda: False
        )
    assert not exc_info.value.provider_call_reserved
    assert stale_runner.requests == []
    prompt = json.loads(runner.requests[0].stdin)
    assert prompt["version"] == "m15-semantic-boundary-prompt-v2"
    assert prompt["request"]["job"]["window_id"] == window.window_id
    assert "private oracle" not in json.dumps(prompt["request"]["job"]).casefold()


def test_semantic_summary_routes_exact_schema_and_rejects_stale_identity() -> None:
    units = _units()
    beat = SemanticBeat(
        "beat-story",
        "cluster-day",
        tuple(item.unit_id for item in units),
        None,
        None,
        EvidenceNavigation("beat", "beat-story"),
    )
    cluster = MajorCluster(
        "cluster-day",
        0,
        (beat.beat_id,),
        (),
        EvidenceNavigation("major_cluster", "cluster-day"),
    )
    outline = SemanticOutline(
        _authority(),
        tuple(item.unit_id for item in units),
        (),
        (beat,),
        (cluster,),
        (),
        (),
    )
    current_job = prepare_semantic_summary_jobs(
        outline,
        _summary_inputs(outline, units),
        _evidence(units),
        source_hash="source-hash",
        correction_id="m15.1",
        privacy_scope="story_evidence_only",
    )[0]
    payload = _summary_payload(current_job, 0)
    runner = _FakeSterileRunner(payload)
    request = NarrativeMapProviderRequest(
        "semantic-summary-route",
        _consent((current_job,)),
        _profile(),
        current_job,
    )

    SterileNarrativeMapProvider(runner=runner).submit(request, lambda: False)

    assert runner.requests[0].schema_path.name == "semantic_summary_v3.schema.json"
    prompt = json.loads(runner.requests[0].stdin)
    assert prompt["version"] == "m15-semantic-summary-prompt-v2"
    assert "repair_guidance" not in prompt["request"]
    repair_runner = _FakeSterileRunner(payload)
    repair_request = NarrativeMapProviderRequest(
        "semantic-summary-repair-route",
        _consent((current_job,)),
        _profile(),
        current_job,
        ("invalid_title", "invalid_characters"),
        {},
    )
    SterileNarrativeMapProvider(runner=repair_runner).submit(
        repair_request, lambda: False
    )
    repair_prompt = json.loads(repair_runner.requests[0].stdin)
    assert repair_request.consent.version == "m15-narrative-consent-v2"
    assert repair_request.consent.repair_policy_version == (
        "m15-semantic-repair-guidance-v2"
    )
    assert repair_request.consent.identity_dict()["repair_policy_version"] == (
        "m15-semantic-repair-guidance-v2"
    )
    stale_repair_consent = replace(
        repair_request.consent,
        repair_policy_version="m15-semantic-repair-guidance-v1",
    )
    assert stale_repair_consent.manifest_id != repair_request.consent.manifest_id
    with pytest.raises(ValueError, match="repair policy"):
        stale_repair_consent.validate_for((current_job,), _profile())
    assert repair_prompt["version"] == prompt["version"]
    assert repair_prompt["request"]["repair_guidance_version"] == (
        "m15-semantic-repair-guidance-v2"
    )
    repair_guidance = " ".join(repair_prompt["request"]["repair_guidance"])
    assert "exactly" in repair_prompt["request"]["locked_semantics_policy"]
    assert "BOUNDARY and LINE" in repair_guidance
    assert "known_characters" in repair_guidance
    assert "at most once" in repair_guidance
    assert "atom" in repair_guidance
    assert "source" in repair_guidance
    assert current_job.response_schema == "m15-semantic-summary-v3"
    stale_job = replace(current_job, response_schema="m15-semantic-summary-v2")
    stale_runner = _FakeSterileRunner(payload)
    stale_request = NarrativeMapProviderRequest(
        "semantic-summary-stale",
        _consent((stale_job,)),
        _profile(),
        stale_job,
    )
    with pytest.raises(NarrativeMapProviderError) as exc_info:
        SterileNarrativeMapProvider(runner=stale_runner).submit(
            stale_request, lambda: False
        )
    assert not exc_info.value.provider_call_reserved
    assert stale_runner.requests == []


def test_v2_validators_reject_duplicates_delegated_by_provider_schemas() -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    boundary_job = prepare_semantic_boundary_jobs(
        units,
        candidates,
        (window,),
        _evidence(units),
        source_hash="source-hash",
        correction_id="m15.1",
        privacy_scope="story_evidence_only",
    )[0]
    boundary_payload = _boundary_payload(window)
    boundary_payload["decisions"][0]["warnings"] = ["duplicate", "duplicate"]
    boundary = validate_semantic_boundary_response(boundary_payload, boundary_job)
    assert "invalid_warnings" in {finding.code for finding in boundary.findings}

    beat = SemanticBeat(
        "beat-story",
        "cluster-day",
        tuple(item.unit_id for item in units),
        None,
        None,
        EvidenceNavigation("beat", "beat-story"),
    )
    cluster = MajorCluster(
        "cluster-day",
        0,
        (beat.beat_id,),
        (),
        EvidenceNavigation("major_cluster", "cluster-day"),
    )
    outline = SemanticOutline(
        _authority(), tuple(item.unit_id for item in units), (), (beat,), (cluster,), (), ()
    )
    summary_job = prepare_semantic_summary_jobs(
        outline,
        _summary_inputs(outline, units),
        _evidence(units),
        source_hash="source-hash",
        correction_id="m15.1",
        privacy_scope="story_evidence_only",
    )[0]
    base_payload = _summary_payload(summary_job, 0)
    for field, value, expected_code in (
        ("characters", ["Ava", "Ava"], "invalid_characters"),
        ("warnings", ["duplicate", "duplicate"], "invalid_warnings"),
    ):
        payload = json.loads(json.dumps(base_payload))
        payload[field] = value
        result = validate_semantic_summary_response(payload, summary_job)
        assert expected_code in {finding.code for finding in result.findings}
    evidence_payload = json.loads(json.dumps(base_payload))
    evidence_payload["claims"][0]["evidence_ids"] *= 2
    evidence_result = validate_semantic_summary_response(evidence_payload, summary_job)
    assert "invalid_claim" in {finding.code for finding in evidence_result.findings}


def test_boundary_consent_cannot_start_summaries_and_changed_identity_is_stale(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates)
    with Project.create(tmp_path / "separate-consent.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        boundaries = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        service.start_boundaries(
            boundaries,
            provider=_FakeProvider([_boundary_payload(windows[0])]),
            consent=boundaries.granted_consent(),
        )
        outline = _outline(units, candidates, service, boundaries)
        topology = _topology(outline)
        service.freeze_semantic_membership(boundaries, outline, topology)
        summaries = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
            quotient_topology=topology,
            profile=_profile(),
            run_id="summaries",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        with pytest.raises(ValueError, match="summaries start requires the exact reviewed consent"):
            service.start_summaries(
                summaries,
                provider=_FakeProvider([]),
                consent=boundaries.granted_consent(),
            )
        status = service.semantic_status(source_hash="changed-source")
        assert status is not None
        assert status.record.state is SemanticBuildState.STALE
        assert status.record.failure_codes == ("identity_changed",)


def test_summary_preparation_requires_prior_durable_membership_freeze(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates)
    with Project.create(tmp_path / "freeze-gate.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        boundaries = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        service.start_boundaries(
            boundaries,
            provider=_FakeProvider([_boundary_payload(windows[0])]),
            consent=boundaries.granted_consent(),
        )
        outline = _outline(units, candidates, service, boundaries)
        with pytest.raises(ValueError, match="durable membership freeze"):
            service.prepare_summaries(
                outline,
                _summary_inputs(outline, units),
                _evidence(units),
                quotient_topology=_topology(outline),
                profile=_profile(),
                run_id="summaries",
                source_hash="source-hash",
                correction_id="m15.1",
            )


def test_changed_preview_run_or_limits_never_reuse_prior_consent(tmp_path: Path) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates)
    with Project.create(tmp_path / "changed-preview.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        first = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="preview-a",
            source_hash="source-hash",
            correction_id="m15.1",
            maximum_provider_calls=2,
        )
        narrowed = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="preview-a",
            source_hash="source-hash",
            correction_id="m15.1",
            maximum_provider_calls=1,
        )
        renamed = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="preview-b",
            source_hash="source-hash",
            correction_id="m15.1",
            maximum_provider_calls=1,
        )

    assert first.consent.maximum_provider_calls == 2
    assert narrowed.consent.maximum_provider_calls == 1
    assert len(
        {
            first.consent.manifest_id,
            narrowed.consent.manifest_id,
            renamed.consent.manifest_id,
        }
    ) == 3


def test_cluster_summary_requires_its_complete_exact_frozen_beat_membership() -> None:
    units = _units()
    beat = SemanticBeat(
        "beat-story",
        "cluster-day",
        tuple(item.unit_id for item in units),
        None,
        None,
        EvidenceNavigation("beat", "beat-story"),
    )
    cluster = MajorCluster(
        "cluster-day",
        0,
        (beat.beat_id,),
        (),
        EvidenceNavigation("major_cluster", "cluster-day"),
    )
    outline = SemanticOutline(
        _authority(),
        beat.ordered_unit_ids,
        (),
        (beat,),
        (cluster,),
        (),
        (),
    )
    inputs = (
        FrozenSummaryInput(
            "beat",
            beat.beat_id,
            beat.ordered_unit_ids,
            tuple(item.evidence_ids[0] for item in units),
            ("Ava",),
        ),
        FrozenSummaryInput(
            "major_cluster",
            cluster.cluster_id,
            (units[-1].unit_id,),
            (units[-1].evidence_ids[0],),
            ("Ava",),
        ),
    )
    with pytest.raises(ValueError, match="exact frozen subject membership"):
        prepare_semantic_summary_jobs(
            outline,
            inputs,
            _evidence(units),
            source_hash="source-hash",
            correction_id="m15.1",
            privacy_scope="story_evidence_only",
        )


def test_choice_summary_requires_only_its_exact_owned_beat_membership() -> None:
    units = _units()
    choice_beat = SemanticBeat(
        "beat-choice",
        "cluster-day",
        (units[1].unit_id, units[2].unit_id),
        "choice-route",
        "arm-a",
        EvidenceNavigation("beat", "beat-choice"),
    )
    context_beat = SemanticBeat(
        "beat-context",
        "cluster-day",
        (units[0].unit_id,),
        None,
        None,
        EvidenceNavigation("beat", "beat-context"),
    )
    cluster = MajorCluster(
        "cluster-day",
        0,
        (context_beat.beat_id, choice_beat.beat_id),
        ("choice-route",),
        EvidenceNavigation("major_cluster", "cluster-day"),
    )
    choice = ChoiceComposition(
        "choice-route",
        cluster.cluster_id,
        None,
        None,
        ("arm-a", "arm-b"),
        ("Take A", "Take B"),
        (),
        ("rejoin-route",),
        "node-rejoin",
        "node-after",
    )
    outline = SemanticOutline(
        _authority(),
        tuple(item.unit_id for item in units),
        (),
        (context_beat, choice_beat),
        (cluster,),
        (choice,),
        (),
    )
    all_evidence = tuple(item.evidence_ids[0] for item in units)
    inputs = (
        FrozenSummaryInput(
            "beat",
            context_beat.beat_id,
            context_beat.ordered_unit_ids,
            (all_evidence[0],),
            ("Ava",),
        ),
        FrozenSummaryInput(
            "beat",
            choice_beat.beat_id,
            choice_beat.ordered_unit_ids,
            all_evidence[1:],
            ("Ava",),
        ),
        FrozenSummaryInput(
            "major_cluster",
            cluster.cluster_id,
            tuple(item.unit_id for item in units),
            all_evidence,
            ("Ava",),
        ),
        FrozenSummaryInput(
            "choice",
            choice.choice_id,
            tuple(item.unit_id for item in units),
            all_evidence,
            ("Ava",),
        ),
    )
    with pytest.raises(ValueError, match="exact frozen subject membership"):
        prepare_semantic_summary_jobs(
            outline,
            inputs,
            _evidence(units),
            source_hash="source-hash",
            correction_id="m15.1",
            privacy_scope="story_evidence_only",
        )


def test_partial_boundary_failure_retries_cached_success_with_one_submit(tmp_path: Path) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates, batched=False)
    path = tmp_path / "partial.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="partial-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        consent = preparation.granted_consent()
        provider = _FakeProvider(
            [_boundary_payload(windows[0]), {"bad": True}, {"still_bad": True}]
        )
        report = service.start_boundaries(
            preparation,
            provider=provider,
            consent=consent,
        )
        assert report.provider_calls == 3
        assert len(report.validated_job_ids) == 1
        assert len(report.failed_job_ids) == 1
        status = service.semantic_status()
        assert status is not None and status.record.state is SemanticBuildState.PARTIAL
        assert service.read_current_semantic_publication() is None

    with Project.open(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="partial-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        consent = preparation.granted_consent()
        retry_provider = _FakeProvider([_boundary_payload(windows[1])])
        retry = service.retry_semantic_build(
            preparation,
            provider=retry_provider,
            consent=consent,
        )
        assert retry.provider_calls == 1
        assert retry.cache_hits == 1
        assert len(retry.validated_job_ids) == 2
        status = service.semantic_status()
        assert status is not None and status.record.state is SemanticBuildState.VALIDATING
        assert status.accounting.provider_calls == 4


def test_mid_run_expiry_checkpoints_partial_and_fresh_manifest_resumes_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates, batched=False)
    path = tmp_path / "expired-resume.rsmproj"
    with Project.create(path) as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        preparation = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="expiring-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        consent = preparation.granted_consent()
        original_validate_fresh = NarrativeConsentManifest.validate_fresh

        def expire_after_first_validation(current: NarrativeConsentManifest) -> None:
            first_record = repository.get(
                preparation.jobs[0].kind,
                preparation.jobs[0].job_id,
            )
            if first_record is not None and first_record.status.value == "validated":
                raise ValueError("M15 provider consent is not fresh")
            original_validate_fresh(current)

        monkeypatch.setattr(
            NarrativeConsentManifest,
            "validate_fresh",
            expire_after_first_validation,
        )
        first_provider = _FakeProvider(
            [_boundary_payload(windows[0]), _boundary_payload(windows[1])]
        )
        first_report = service.start_boundaries(
            preparation,
            provider=first_provider,
            consent=consent,
        )

        assert first_report.validated_job_ids == (preparation.jobs[0].job_id,)
        assert first_report.failed_job_ids == (preparation.jobs[1].job_id,)
        assert first_report.provider_calls == 1
        assert len(first_provider.requests) == 1
        first_status = service.semantic_status()
        assert first_status is not None
        assert first_status.record.state is SemanticBuildState.PARTIAL
        assert first_status.record.completed_boundary_job_ids == (
            preparation.jobs[0].job_id,
        )
        assert first_status.record.failure_codes == ("consent_expired",)
        assert first_status.accounting.provider_calls == 1
        assert first_status.accounting.reserved_provider_calls == 1

        monkeypatch.setattr(
            NarrativeConsentManifest,
            "validate_fresh",
            original_validate_fresh,
        )
        resumed = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="resumed-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
            replay_existing=True,
        )
        resumed_status = service.semantic_status()
        assert resumed.consent.manifest_id != preparation.consent.manifest_id
        assert resumed_status is not None
        assert resumed_status.accounting.provider_calls == 1
        assert resumed_status.accounting.reserved_provider_calls == 1
        assert resumed_status.record.completed_boundary_job_ids == (
            preparation.jobs[0].job_id,
        )

        retry_provider = _FakeProvider([_boundary_payload(windows[1])])
        retry_report = service.start_boundaries(
            resumed,
            provider=retry_provider,
            consent=resumed.granted_consent(),
        )
        final_status = service.semantic_status()

    assert retry_report.provider_calls == 1
    assert retry_report.cache_hits == 1
    assert retry_report.validated_job_ids == tuple(job.job_id for job in resumed.jobs)
    assert len(retry_provider.requests) == 1
    assert final_status is not None
    assert final_status.record.state is SemanticBuildState.VALIDATING
    assert final_status.accounting.provider_calls == 2
    assert final_status.accounting.reserved_provider_calls == 2
    assert final_status.accounting.cache_hits == 1


def test_escaped_boundary_task_reconciles_once_across_repeated_manifest_rotation(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates, batched=False)
    path = tmp_path / "escaped-boundary.rsmproj"
    with Project.create(path) as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        preparation = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="escaped-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        escaping = _EscapingProvider([_boundary_payload(windows[0])])
        with pytest.raises(KeyboardInterrupt, match="synthetic task escape"):
            service.start_boundaries(
                preparation,
                provider=escaping,
                consent=preparation.granted_consent(),
            )

        escaped_status = service.semantic_status()
        assert escaped_status is not None
        assert escaped_status.record.state is SemanticBuildState.BOUNDARIES_RUNNING
        assert escaped_status.accounting.provider_calls == 0
        assert escaped_status.accounting.reserved_provider_calls == 0
        assert repository.semantic_reserved_call_count(
            manifest_id=preparation.consent.manifest_id,
            maximum_provider_calls=preparation.consent.maximum_provider_calls,
        ) == 2

        for _ in range(2):
            same_manifest = service.prepare_boundaries(
                units,
                candidates,
                windows,
                _evidence(units),
                profile=_profile(),
                run_id="escaped-boundaries",
                source_hash="source-hash",
                correction_id="m15.1",
                valid_for=timedelta(hours=1),
                replay_existing=True,
            )
            assert same_manifest.consent.manifest_id == preparation.consent.manifest_id
        same_status = service.semantic_status()
        same_raw = repository.read_semantic_build()
        assert same_status is not None
        assert same_status.accounting.provider_calls == 1
        assert same_status.accounting.reserved_provider_calls == 2
        assert same_raw is not None
        assert same_raw["boundary_accounted_manifest_id"] == preparation.consent.manifest_id
        assert same_raw["boundary_accounted_reservation_count"] == 2

        first_rotation = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="first-rotation",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
            replay_existing=True,
        )
        first_status = service.semantic_status()
        assert first_status is not None
        assert first_status.record.completed_boundary_job_ids == (
            preparation.jobs[0].job_id,
        )
        assert first_status.accounting.provider_calls == 1
        assert first_status.accounting.reserved_provider_calls == 2

        second_rotation = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="second-rotation",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=59),
            replay_existing=True,
        )
        second_status = service.semantic_status()
        assert second_rotation.consent.manifest_id != first_rotation.consent.manifest_id
        assert second_status is not None
        assert second_status.accounting.provider_calls == 1
        assert second_status.accounting.reserved_provider_calls == 2

        retry_provider = _FakeProvider([_boundary_payload(windows[1])])
        retry = service.start_boundaries(
            second_rotation,
            provider=retry_provider,
            consent=second_rotation.granted_consent(),
        )
        final_status = service.semantic_status()
        final_raw = repository.read_semantic_build()

    assert retry.provider_calls == 1
    assert retry.cache_hits == 1
    assert len(retry_provider.requests) == 1
    assert final_status is not None
    assert final_status.record.state is SemanticBuildState.VALIDATING
    assert final_status.accounting.provider_calls == 2
    assert final_status.accounting.reserved_provider_calls == 3
    assert final_status.accounting.cache_hits == 1
    assert final_raw is not None
    assert final_raw["boundary_accounting"]["provider_calls"] == 2
    assert final_raw["boundary_accounting"]["reserved_provider_calls"] == 3
    assert final_raw["boundary_accounting"]["cache_hits"] == 1


def test_missing_legacy_reservation_markers_are_migrated_on_exact_replay(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    with Project.create(tmp_path / "legacy-accounting-markers.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        preparation = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="legacy-accounting-markers",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        service.start_boundaries(
            preparation,
            provider=_FakeProvider([_boundary_payload(window)]),
            consent=preparation.granted_consent(),
        )
        legacy = repository.read_semantic_build()
        assert legacy is not None
        legacy.pop("boundary_accounted_manifest_id")
        legacy.pop("boundary_accounted_reservation_count")
        repository.write_semantic_build(legacy)

        replay_provider = _FakeProvider([])
        replay = service.start_boundaries(
            preparation,
            provider=replay_provider,
            consent=preparation.granted_consent(),
        )
        migrated = repository.read_semantic_build()

    assert replay.provider_calls == 0
    assert replay.cache_hits == 1
    assert replay_provider.requests == []
    assert migrated is not None
    assert migrated["boundary_accounted_manifest_id"] == preparation.consent.manifest_id
    assert migrated["boundary_accounted_reservation_count"] == 1
    assert migrated["boundary_accounting"]["provider_calls"] == 1
    assert migrated["boundary_accounting"]["reserved_provider_calls"] == 1


def test_missing_legacy_markers_do_not_double_count_during_manifest_rotation(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates, batched=False)
    with Project.create(tmp_path / "legacy-marker-rotation.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        original = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="legacy-marker-original",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        service.start_boundaries(
            original,
            provider=_FakeProvider(
                [_boundary_payload(windows[0]), {"bad": True}, {"still_bad": True}]
            ),
            consent=original.granted_consent(),
        )
        legacy = repository.read_semantic_build()
        assert legacy is not None
        legacy.pop("boundary_accounted_manifest_id")
        legacy.pop("boundary_accounted_reservation_count")
        repository.write_semantic_build(legacy)

        rotated = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="legacy-marker-rotated",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=59),
            replay_existing=True,
        )
        recovered = repository.read_semantic_build()

    assert rotated.consent.manifest_id != original.consent.manifest_id
    assert recovered is not None
    assert recovered["accounting"]["provider_calls"] == 3
    assert recovered["accounting"]["reserved_provider_calls"] == 3
    assert recovered["boundary_accounting"]["provider_calls"] == 3
    assert recovered["boundary_accounting"]["reserved_provider_calls"] == 3
    assert recovered["boundary_accounted_manifest_id"] == rotated.consent.manifest_id
    assert recovered["boundary_accounted_reservation_count"] == 0


def test_reusable_recovery_does_not_skip_reservation_after_ledger_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    with Project.create(tmp_path / "late-reusable-reservation.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        preparation = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="late-reusable-reservation",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        original_count = repository.semantic_reserved_call_count
        inserted = False

        def snapshot_then_reserve(
            *,
            manifest_id: str,
            maximum_provider_calls: int,
        ) -> int:
            nonlocal inserted
            snapshot = original_count(
                manifest_id=manifest_id,
                maximum_provider_calls=maximum_provider_calls,
            )
            if not inserted:
                inserted = True
                repository.reserve_semantic_provider_call(
                    manifest_id=manifest_id,
                    maximum_provider_calls=maximum_provider_calls,
                    job_id=preparation.jobs[0].job_id,
                    attempt=1,
                )
            return snapshot

        monkeypatch.setattr(
            repository,
            "semantic_reserved_call_count",
            snapshot_then_reserve,
        )
        service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="late-reusable-reservation",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
            replay_existing=True,
        )
        first = repository.read_semantic_build()
        monkeypatch.setattr(
            repository,
            "semantic_reserved_call_count",
            original_count,
        )
        for _ in range(2):
            service.prepare_boundaries(
                units,
                candidates,
                (window,),
                _evidence(units),
                profile=_profile(),
                run_id="late-reusable-reservation",
                source_hash="source-hash",
                correction_id="m15.1",
                valid_for=timedelta(hours=1),
                replay_existing=True,
            )
        final = repository.read_semantic_build()

    assert first is not None
    assert first["boundary_accounting"]["reserved_provider_calls"] == 0
    assert first["boundary_accounted_reservation_count"] == 0
    assert final is not None
    assert final["boundary_accounting"]["provider_calls"] == 0
    assert final["boundary_accounting"]["reserved_provider_calls"] == 1
    assert final["accounting"]["reserved_provider_calls"] == 1
    assert final["boundary_accounted_reservation_count"] == 1


def test_replacement_start_waits_through_expired_manifest_timeout_grace(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    with Project.create(tmp_path / "expired-manifest-grace.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        prior = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="expired-grace-prior",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        service.confirm_semantic_consent(prior, prior.granted_consent())
        repository.reserve_semantic_provider_call(
            manifest_id=prior.consent.manifest_id,
            maximum_provider_calls=prior.consent.maximum_provider_calls,
            job_id=prior.jobs[0].job_id,
            attempt=1,
        )
        replacement = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="expired-grace-replacement",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=59),
            replay_existing=True,
        )
        raw = repository.read_semantic_build()
        assert raw is not None
        snapshots = raw["confirmed_manifests"]
        prior_snapshot = snapshots[prior.consent.manifest_id]
        within_grace_expiry = datetime.now(UTC) - timedelta(seconds=1)
        prior_snapshot["issued_utc"] = (
            within_grace_expiry - timedelta(hours=1)
        ).isoformat()
        prior_snapshot["expires_utc"] = within_grace_expiry.isoformat()
        repository.write_semantic_build(raw)

        blocked_provider = _FakeProvider([_boundary_payload(window)])
        with pytest.raises(ValueError, match="prior confirmed boundary manifest"):
            service.start_boundaries(
                replacement,
                provider=blocked_provider,
                consent=replacement.granted_consent(),
            )
        assert blocked_provider.requests == []

        raw = repository.read_semantic_build()
        assert raw is not None
        snapshots = raw["confirmed_manifests"]
        after_grace_expiry = datetime.now(UTC) - timedelta(seconds=301)
        snapshots[prior.consent.manifest_id]["issued_utc"] = (
            after_grace_expiry - timedelta(hours=1)
        ).isoformat()
        snapshots[prior.consent.manifest_id]["expires_utc"] = after_grace_expiry.isoformat()
        repository.write_semantic_build(raw)
        allowed_provider = _FakeProvider([_boundary_payload(window)])
        report = service.start_boundaries(
            replacement,
            provider=allowed_provider,
            consent=replacement.granted_consent(),
        )

    assert report.provider_calls == 1
    assert len(allowed_provider.requests) == 1


def test_escaped_summary_task_reconciles_once_across_repeated_manifest_rotation(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates)
    with Project.create(tmp_path / "escaped-summary.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        boundaries = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="summary-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        service.start_boundaries(
            boundaries,
            provider=_FakeProvider([_boundary_payload(windows[0])]),
            consent=boundaries.granted_consent(),
        )
        outline = _outline(units, candidates, service, boundaries)
        topology = _topology(outline)
        service.freeze_semantic_membership(boundaries, outline, topology)
        summaries = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
            quotient_topology=topology,
            profile=_profile(),
            run_id="escaped-summaries",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        escaping = _EscapingProvider([_summary_payload(summaries.jobs[0], 0)])
        with pytest.raises(KeyboardInterrupt, match="synthetic task escape"):
            service.start_summaries(
                summaries,
                provider=escaping,
                consent=summaries.granted_consent(),
            )

        escaped = repository.read_semantic_build()
        assert escaped is not None
        assert escaped["state"] == SemanticBuildState.SUMMARIES_RUNNING.value
        assert escaped["completed_summary_job_ids"] == []
        assert escaped["summary_accounting"]["provider_calls"] == 0
        assert escaped["summary_accounting"]["reserved_provider_calls"] == 0

        first_rotation = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
            quotient_topology=topology,
            profile=_profile(),
            run_id="summary-first-rotation",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
            replay_existing=True,
        )
        first = repository.read_semantic_build()
        assert first is not None
        assert first["completed_summary_job_ids"] == [summaries.jobs[0].job_id]
        assert first["summary_accounting"]["provider_calls"] == 1
        assert first["summary_accounting"]["reserved_provider_calls"] == 2
        assert first["accounting"]["provider_calls"] == 2
        assert first["accounting"]["reserved_provider_calls"] == 3

        second_rotation = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
            quotient_topology=topology,
            profile=_profile(),
            run_id="summary-second-rotation",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=59),
            replay_existing=True,
        )
        second = repository.read_semantic_build()
        assert second_rotation.consent.manifest_id != first_rotation.consent.manifest_id
        assert second is not None
        assert second["summary_accounting"]["provider_calls"] == 1
        assert second["summary_accounting"]["reserved_provider_calls"] == 2

        retry_provider = _FakeProvider([_summary_payload(second_rotation.jobs[1], 1)])
        retry = service.start_summaries(
            second_rotation,
            provider=retry_provider,
            consent=second_rotation.granted_consent(),
        )
        final = service.semantic_status()
        final_raw = repository.read_semantic_build()

    assert retry.provider_calls == 1
    assert retry.cache_hits == 1
    assert len(retry_provider.requests) == 1
    assert final is not None
    assert final.record.state is SemanticBuildState.COMPLETE
    assert final.accounting.provider_calls == 3
    assert final.accounting.reserved_provider_calls == 4
    assert final.accounting.cache_hits == 1
    assert final_raw is not None
    assert final_raw["summary_accounting"]["provider_calls"] == 2
    assert final_raw["summary_accounting"]["reserved_provider_calls"] == 3
    assert final_raw["summary_accounting"]["cache_hits"] == 1


def test_rebuilt_boundary_stage_preserves_settled_manifest_reconciliation(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates, batched=False)
    with Project.create(tmp_path / "settled-boundary-manifest.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        prior = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="settled-boundary-prior",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        service.confirm_semantic_consent(prior, prior.granted_consent())
        first = service.start_boundaries(
            prior,
            provider=_FakeProvider(
                [_boundary_payload(windows[0]), {"bad": True}, {"bad": True}]
            ),
            consent=prior.granted_consent(),
        )
        assert first.provider_calls == 3

        replacement = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="settled-boundary-replacement",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=59),
            replay_existing=True,
        )
        service.confirm_semantic_consent(replacement, replacement.granted_consent())
        second = service.start_boundaries(
            replacement,
            provider=_FakeProvider([{"bad": True}, {"bad": True}]),
            consent=replacement.granted_consent(),
        )
        assert second.provider_calls == 2

        rebuilt = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="settled-boundary-rebuilt",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=58),
            replay_existing=True,
        )
        rebuilt_raw = repository.read_semantic_build()
        assert rebuilt_raw is not None
        assert prior.consent.manifest_id in rebuilt_raw[
            "boundary_reconciled_manifest_ids"
        ]
        service.confirm_semantic_consent(rebuilt, rebuilt.granted_consent())
        final = service.start_boundaries(
            rebuilt,
            provider=_FakeProvider([_boundary_payload(windows[1])]),
            consent=rebuilt.granted_consent(),
        )
        status = service.semantic_status()

    assert final.provider_calls == 1
    assert status is not None
    assert status.record.state is SemanticBuildState.VALIDATING


def test_settled_summary_manifest_stays_reconciled_after_later_record_replacement(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates)
    with Project.create(tmp_path / "settled-summary-manifest.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        boundaries = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="settled-summary-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        service.confirm_semantic_consent(boundaries, boundaries.granted_consent())
        service.start_boundaries(
            boundaries,
            provider=_FakeProvider([_boundary_payload(windows[0])]),
            consent=boundaries.granted_consent(),
        )
        outline = _outline(units, candidates, service, boundaries)
        topology = _topology(outline)
        service.freeze_semantic_membership(boundaries, outline, topology)
        prior = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
            quotient_topology=topology,
            profile=_profile(),
            run_id="settled-summary-prior",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        service.confirm_semantic_consent(prior, prior.granted_consent())
        first = service.start_summaries(
            prior,
            provider=_FakeProvider(
                [_summary_payload(prior.jobs[0], 0), {"bad": True}, {"bad": True}]
            ),
            consent=prior.granted_consent(),
        )
        assert first.provider_calls == 3

        replacement = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
            quotient_topology=topology,
            profile=_profile(),
            run_id="settled-summary-replacement",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=59),
            replay_existing=True,
        )
        service.confirm_semantic_consent(replacement, replacement.granted_consent())
        second = service.start_summaries(
            replacement,
            provider=_FakeProvider([{"bad": True}, {"bad": True}]),
            consent=replacement.granted_consent(),
        )
        assert second.provider_calls == 2
        after_replacement = repository.read_semantic_build()
        assert after_replacement is not None
        assert prior.consent.manifest_id in after_replacement[
            "summary_reconciled_manifest_ids"
        ]

        final = service.start_summaries(
            replacement,
            provider=_FakeProvider([_summary_payload(replacement.jobs[1], 1)]),
            consent=replacement.granted_consent(),
        )
        status = service.semantic_status()

    assert final.provider_calls == 1
    assert status is not None
    assert status.record.state is SemanticBuildState.COMPLETE


def test_concurrent_reopen_cannot_cross_the_atomic_durable_consent_ceiling(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    path = tmp_path / "atomic-calls.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="one-call-only",
            source_hash="source-hash",
            correction_id="m15.1",
            maximum_provider_calls=1,
        )
    consent = preparation.granted_consent()
    entered = Event()
    release = Event()
    first_provider = _BlockingProvider(_boundary_payload(window), entered, release)
    second_provider = _FakeProvider([_boundary_payload(window)])

    def run(provider: _FakeProvider) -> NarrativeWorkflowReport:
        with Project.open(path) as project:
            return NarrativeMapService(NarrativeMapRepository(project)).start_boundaries(
                preparation,
                provider=provider,
                consent=consent,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run, first_provider)
        assert entered.wait(timeout=5)
        second_future = executor.submit(run, second_provider)
        try:
            second_report = second_future.result(timeout=5)
            with Project.open(path) as project:
                interim = NarrativeMapService(
                    NarrativeMapRepository(project)
                ).semantic_status()
                assert interim is not None
                assert interim.record.state is SemanticBuildState.BOUNDARIES_RUNNING
                assert interim.record.failure_codes == ()
        finally:
            release.set()
        first_report = first_future.result(timeout=5)

    assert first_report.provider_calls + second_report.provider_calls == 1
    assert len(first_provider.requests) + len(second_provider.requests) == 1
    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        assert repository.semantic_reserved_call_count(
            manifest_id=consent.manifest_id,
            maximum_provider_calls=1,
        ) == 1
        status = NarrativeMapService(repository).semantic_status()
        assert status is not None
        assert status.accounting.reserved_provider_calls == 1


def test_reusable_prepare_recovers_calls_finished_under_rotated_manifest(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates, batched=False)
    path = tmp_path / "rotated-while-running.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        original = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="rotated-original",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )
        first = service.start_boundaries(
            original,
            provider=_FakeProvider(
                [_boundary_payload(windows[0]), {"bad": True}, {"still_bad": True}]
            ),
            consent=original.granted_consent(),
        )
        assert first.provider_calls == 3

        active = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="rotated-active",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
            replay_existing=True,
        )

    entered = Event()
    release = Event()
    provider = _BlockingProvider(_boundary_payload(windows[1]), entered, release)

    def finish_active_manifest() -> NarrativeWorkflowReport:
        with Project.open(path) as project:
            service = NarrativeMapService(NarrativeMapRepository(project))
            service.confirm_semantic_consent(active, active.granted_consent())
            return service.start_boundaries(
                active,
                provider=provider,
                consent=active.granted_consent(),
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(finish_active_manifest)
        assert entered.wait(timeout=5)
        with Project.open(path) as project:
            replacement_service = NarrativeMapService(NarrativeMapRepository(project))
            rotated = replacement_service.prepare_boundaries(
                units,
                candidates,
                windows,
                _evidence(units),
                profile=_profile(),
                run_id="rotated-replacement",
                source_hash="source-hash",
                correction_id="m15.1",
                valid_for=timedelta(minutes=59),
                replay_existing=True,
            )
            replacement_provider = _FakeProvider([_boundary_payload(windows[1])])
            with pytest.raises(ValueError, match="prior confirmed boundary manifest"):
                replacement_service.start_boundaries(
                    rotated,
                    provider=replacement_provider,
                    consent=rotated.granted_consent(),
                )
            assert replacement_provider.requests == []
        release.set()
        finished = future.result(timeout=5)
        assert finished.provider_calls == 1

    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        recovered = NarrativeMapService(repository).prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="rotated-replacement",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(minutes=59),
            replay_existing=True,
        )
        replacement_provider = _FakeProvider([_boundary_payload(windows[1])])
        replacement_report = NarrativeMapService(repository).start_boundaries(
            recovered,
            provider=replacement_provider,
            consent=recovered.granted_consent(),
        )
        raw = repository.read_semantic_build()

    assert recovered.consent.manifest_id == rotated.consent.manifest_id
    assert replacement_report.provider_calls == 1
    assert len(replacement_provider.requests) == 1
    assert raw is not None
    assert len(raw["completed_boundary_job_ids"]) == 2
    assert raw["boundary_accounting"]["provider_calls"] == 5
    assert raw["boundary_accounting"]["reserved_provider_calls"] == 5
    assert raw["accounting"]["provider_calls"] == 5
    assert raw["accounting"]["reserved_provider_calls"] == 5


def test_runner_finalization_does_not_recharge_concurrently_recovered_record(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates, batched=False)
    path = tmp_path / "same-manifest-concurrent-recovery.rsmproj"
    with Project.create(path) as project:
        active = NarrativeMapService(
            NarrativeMapRepository(project)
        ).prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="same-manifest-concurrent-recovery",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )

    entered = Event()
    release = Event()
    provider = _BlockAfterFirstProvider(
        [_boundary_payload(windows[0]), _boundary_payload(windows[1])],
        entered,
        release,
    )

    def finish() -> NarrativeWorkflowReport:
        with Project.open(path) as project:
            return NarrativeMapService(NarrativeMapRepository(project)).start_boundaries(
                active,
                provider=provider,
                consent=active.granted_consent(),
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(finish)
        assert entered.wait(timeout=5)
        with Project.open(path) as project:
            repository = NarrativeMapRepository(project)
            service = NarrativeMapService(repository)
            same = service.prepare_boundaries(
                units,
                candidates,
                windows,
                _evidence(units),
                profile=_profile(),
                run_id="same-manifest-concurrent-recovery",
                source_hash="source-hash",
                correction_id="m15.1",
                valid_for=timedelta(hours=1),
                replay_existing=True,
            )
            interim = repository.read_semantic_build()
        assert same.consent.manifest_id == active.consent.manifest_id
        assert interim is not None
        assert interim["boundary_accounting"]["provider_calls"] == 1
        assert interim["boundary_accounting"]["reserved_provider_calls"] == 2
        release.set()
        report = future.result(timeout=5)

    with Project.open(path) as project:
        raw = NarrativeMapRepository(project).read_semantic_build()

    assert report.provider_calls == 2
    assert len(provider.requests) == 2
    assert raw is not None
    assert raw["boundary_accounting"]["provider_calls"] == 2
    assert raw["boundary_accounting"]["reserved_provider_calls"] == 2
    assert raw["boundary_accounting"]["input_tokens"] == 200
    assert raw["boundary_accounting"]["output_tokens"] == 40
    assert raw["boundary_accounting"]["elapsed_ms"] == 10


def test_late_boundary_finalizer_preserves_prepared_summary_phase(tmp_path: Path) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    path = tmp_path / "late-boundary-after-summary-prepare.rsmproj"
    profile = _profile()
    with Project.create(path) as project:
        active = NarrativeMapService(
            NarrativeMapRepository(project)
        ).prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=profile,
            run_id="late-boundary-active",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )

    entered = Event()
    release = Event()
    provider = _BlockingProvider(_boundary_payload(window), entered, release)

    def finish() -> NarrativeWorkflowReport:
        with Project.open(path) as project:
            return NarrativeMapService(NarrativeMapRepository(project)).start_boundaries(
                active,
                provider=provider,
                consent=active.granted_consent(),
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(finish)
        assert entered.wait(timeout=5)
        with Project.open(path) as project:
            repository = NarrativeMapRepository(project)
            advanced = repository.read_semantic_build()
            assert advanced is not None
            advanced["state"] = SemanticBuildState.AWAITING_SUMMARY_CONSENT.value
            advanced["membership_hash"] = "frozen-membership-hash"
            advanced["summary_manifest_id"] = "consent_summary_phase"
            advanced["summary_job_ids"] = ["semantic_summary_job"]
            repository.write_semantic_build(advanced)
            before_release = repository.read_semantic_build()
        release.set()
        report = future.result(timeout=5)

    with Project.open(path) as project:
        final = NarrativeMapRepository(project).read_semantic_build()

    assert report.provider_calls == 1
    assert before_release is not None
    assert final is not None
    assert final["state"] == SemanticBuildState.AWAITING_SUMMARY_CONSENT.value
    assert final["state"] == before_release["state"]
    assert final["membership_hash"] == before_release["membership_hash"]
    assert final["summary_manifest_id"] == before_release["summary_manifest_id"]
    assert final["summary_job_ids"] == before_release["summary_job_ids"]


def test_reusable_prepare_recovers_terminal_failure_under_rotated_manifest(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    path = tmp_path / "rotated-failure-while-running.rsmproj"
    with Project.create(path) as project:
        active = NarrativeMapService(
            NarrativeMapRepository(project)
        ).prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="rotated-failure-active",
            source_hash="source-hash",
            correction_id="m15.1",
            valid_for=timedelta(hours=1),
        )

    entered = Event()
    release = Event()
    provider = _BlockingSequenceProvider(
        [{"bad": True}, {"still_bad": True}],
        entered,
        release,
    )

    def finish_active_manifest() -> NarrativeWorkflowReport:
        with Project.open(path) as project:
            service = NarrativeMapService(NarrativeMapRepository(project))
            service.confirm_semantic_consent(active, active.granted_consent())
            return service.start_boundaries(
                active,
                provider=provider,
                consent=active.granted_consent(),
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(finish_active_manifest)
        assert entered.wait(timeout=5)
        with Project.open(path) as project:
            rotated = NarrativeMapService(
                NarrativeMapRepository(project)
            ).prepare_boundaries(
                units,
                candidates,
                (window,),
                _evidence(units),
                profile=_profile(),
                run_id="rotated-failure-replacement",
                source_hash="source-hash",
                correction_id="m15.1",
                valid_for=timedelta(minutes=59),
                replay_existing=True,
            )
        release.set()
        finished = future.result(timeout=5)
        assert finished.provider_calls == 1

    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        for _ in range(2):
            recovered = service.prepare_boundaries(
                units,
                candidates,
                (window,),
                _evidence(units),
                profile=_profile(),
                run_id="rotated-failure-replacement",
                source_hash="source-hash",
                correction_id="m15.1",
                valid_for=timedelta(minutes=59),
                replay_existing=True,
            )
        raw = repository.read_semantic_build()

    assert recovered.consent.manifest_id == rotated.consent.manifest_id
    assert raw is not None
    assert raw["completed_boundary_job_ids"] == []
    assert raw["boundary_accounting"]["provider_calls"] == 1
    assert raw["boundary_accounting"]["reserved_provider_calls"] == 1
    assert raw["boundary_accounting"]["input_tokens"] == 0
    assert raw["boundary_accounting"]["output_tokens"] == 0
    assert raw["boundary_accounting"]["elapsed_ms"] == 0
    assert raw["accounting"] == raw["boundary_accounting"]


def test_concurrent_reopen_cannot_submit_the_same_logical_job_attempt_twice(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    path = tmp_path / "atomic-job-attempt.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="two-calls-but-one-logical-attempt",
            source_hash="source-hash",
            correction_id="m15.1",
            maximum_provider_calls=2,
        )
    consent = preparation.granted_consent()
    entered = Event()
    release = Event()
    first_provider = _BlockingProvider(_boundary_payload(window), entered, release)
    divergent = _boundary_payload(window)
    cast(list[dict[str, object]], divergent["decisions"])[0][
        "decision"
    ] = "new_major_cluster"
    second_provider = _FakeProvider([divergent])

    def run(provider: _FakeProvider) -> NarrativeWorkflowReport:
        with Project.open(path) as project:
            return NarrativeMapService(NarrativeMapRepository(project)).start_boundaries(
                preparation,
                provider=provider,
                consent=consent,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run, first_provider)
        assert entered.wait(timeout=5)
        second_future = executor.submit(run, second_provider)
        try:
            second_report = second_future.result(timeout=5)
            with Project.open(path) as project:
                interim = NarrativeMapService(
                    NarrativeMapRepository(project)
                ).semantic_status()
                assert interim is not None
                assert interim.record.state is SemanticBuildState.BOUNDARIES_RUNNING
                assert interim.record.failure_codes == ()
        finally:
            release.set()
        first_report = first_future.result(timeout=5)

    assert first_report.provider_calls == 1
    assert second_report.provider_calls == 0
    assert second_report.failed_job_ids == ()
    assert second_report.deferred_job_ids == (preparation.jobs[0].job_id,)
    assert len(first_provider.requests) == 1
    assert second_provider.requests == []
    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        assert repository.semantic_reserved_call_count(
            manifest_id=consent.manifest_id,
            maximum_provider_calls=2,
        ) == 1
        assert service.semantic_boundary_output(preparation).decisions[0].decision.value == (
            "new_beat_same_cluster"
        )
        status = service.semantic_status()
        assert status is not None
        assert status.accounting.provider_calls == 1
        assert status.accounting.reserved_provider_calls == 1


def test_boundary_repair_is_bounded_and_cannot_reinterpret_a_valid_decision(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    window = _windows(units, candidates)[0]
    valid = _boundary_payload(window)
    first_decision = cast(dict[str, object], cast(list[object], valid["decisions"])[0])
    incomplete = {"window_id": window.window_id, "decisions": [first_decision]}
    changed = _boundary_payload(window)
    cast(dict[str, object], cast(list[object], changed["decisions"])[0])["decision"] = (
        "same_beat"
    )
    with Project.create(tmp_path / "repair-lock.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="repair-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        provider = _FakeProvider([incomplete, changed])
        report = service.start_boundaries(
            preparation,
            provider=provider,
            consent=preparation.granted_consent(),
        )
        assert report.provider_calls == 2
        assert report.validated_job_ids == ()
        assert report.failed_job_ids == (preparation.jobs[0].job_id,)
        status = service.semantic_status()
        assert status is not None and status.record.state is SemanticBuildState.FAILED
        assert status.record.failure_codes == ("semantic_reinterpretation",)

    with Project.create(tmp_path / "repair-fill.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            (window,),
            _evidence(units),
            profile=_profile(),
            run_id="repair-fill",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        provider = _FakeProvider([incomplete, valid])
        report = service.start_boundaries(
            preparation,
            provider=provider,
            consent=preparation.granted_consent(),
        )
        assert report.provider_calls == 2
        assert report.validated_job_ids == (preparation.jobs[0].job_id,)


def test_cancel_before_submit_is_durable_and_current_publication_is_untouched(
    tmp_path: Path,
) -> None:
    units = _units()
    candidates = _candidates(units)
    windows = _windows(units, candidates)
    with Project.create(tmp_path / "cancel.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = service.prepare_boundaries(
            units,
            candidates,
            windows,
            _evidence(units),
            profile=_profile(),
            run_id="cancel-boundaries",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        provider = _FakeProvider([])
        report = service.start_boundaries(
            preparation,
            provider=provider,
            consent=preparation.granted_consent(),
            cancelled=lambda: True,
        )
        assert report.cancelled is True
        assert report.provider_calls == 0
        assert provider.requests == []
        status = service.semantic_status()
        assert status is not None and status.record.state is SemanticBuildState.CANCELLED
        assert service.read_current_semantic_publication() is None

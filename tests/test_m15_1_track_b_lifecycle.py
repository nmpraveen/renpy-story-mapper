from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
    prepare_semantic_summary_jobs,
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

        outline = _outline(units, candidates, service, boundaries)
        summaries = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
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


def test_sterile_adapter_uses_the_v2_boundary_prompt_and_schema(tmp_path: Path) -> None:
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
    assert runner.requests[0].schema_path.name == "boundary_window_v2.schema.json"
    prompt = json.loads(runner.requests[0].stdin)
    assert prompt["version"] == "m15-semantic-boundary-prompt-v2"
    assert prompt["request"]["job"]["window_id"] == window.window_id
    assert "private oracle" not in json.dumps(prompt["request"]["job"]).casefold()


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
        summaries = service.prepare_summaries(
            outline,
            _summary_inputs(outline, units),
            _evidence(units),
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

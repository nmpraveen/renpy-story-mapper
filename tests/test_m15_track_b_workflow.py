from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.ai_projection import (
    EvidenceRecord,
    prepare_boundary_jobs,
    prepare_event_summary_jobs,
)
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    BoundaryCandidate,
    BoundarySignal,
    CoverageState,
    NarrativeCorridor,
    NarrativeEvent,
    Provenance,
    SourceLocator,
)
from renpy_story_mapper.narrative_map.persistence import (
    NarrativeJobStatus,
    NarrativeMapRepository,
)
from renpy_story_mapper.narrative_map.provider import (
    NarrativeConsentManifest,
    NarrativeMapProviderError,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    ProviderProfile,
    SterileNarrativeMapProvider,
)
from renpy_story_mapper.narrative_map.service import NarrativeMapService
from renpy_story_mapper.narrative_map.validation import (
    validate_boundary_response,
    validate_event_summary_response,
)
from renpy_story_mapper.narrative_map.workflow import NarrativeBoundaryWorkflow
from renpy_story_mapper.organization.sterile_runner import (
    SterileRunnerError,
    SterileRunRequest,
    SterileRunResult,
)
from renpy_story_mapper.project import Project


def _authority() -> AuthorityBinding:
    return AuthorityBinding(
        source_generation="generation-1",
        canonical_schema="m10-canonical-graph-v1",
        canonical_hash="canonical-hash",
        atom_schema="m11-story-atoms-v1",
        atom_hash="atom-hash",
    )


def _corridor(
    name: str,
    ordinal: int,
    *,
    hard_before: bool = False,
    hard_after: bool = False,
) -> NarrativeCorridor:
    atom_id = f"atom-{name}"
    evidence_id = f"evidence-{name}"
    return NarrativeCorridor(
        authority=_authority(),
        lane_id="lane-1",
        chapter_id="day-1",
        call_occurrence_id="call-1",
        loop_id=None,
        temporary_container_id=None,
        temporary_arm_id=None,
        ordered_atom_ids=(atom_id,),
        entry_node_id=f"node-{ordinal}",
        exit_node_id=f"node-{ordinal + 1}",
        incident_edge_ids=(f"edge-{ordinal}",),
        hard_boundary_before=hard_before,
        hard_boundary_after=hard_after,
        soft_boundary_signals=(BoundarySignal.NARRATIVE_OBJECTIVE,),
        provenance=Provenance(
            atom_ids=(atom_id,),
            node_ids=(f"node-{ordinal}", f"node-{ordinal + 1}"),
            edge_ids=(f"edge-{ordinal}",),
            evidence_ids=(evidence_id,),
            locators=(SourceLocator("game/story.rpy", ordinal + 1, ordinal + 1, "physical"),),
        ),
    )


def _candidate(left: NarrativeCorridor, right: NarrativeCorridor) -> BoundaryCandidate:
    return BoundaryCandidate(
        authority=_authority(),
        left_corridor_id=left.corridor_id,
        right_corridor_id=right.corridor_id,
        signals=(BoundarySignal.NARRATIVE_OBJECTIVE,),
        evidence_ids=(left.provenance.evidence_ids[0], right.provenance.evidence_ids[0]),
    )


def _evidence(*corridors: NarrativeCorridor) -> dict[str, EvidenceRecord]:
    return {
        corridor.ordered_atom_ids[0]: EvidenceRecord(
            atom_id=corridor.ordered_atom_ids[0],
            evidence_id=corridor.provenance.evidence_ids[0],
            ordinal=index,
            kind="dialogue",
            text=f"Synthetic story text {index}",
            speaker="Narrator",
            locator=corridor.provenance.locators[0],
        )
        for index, corridor in enumerate(corridors)
    }


def _event(*corridors: NarrativeCorridor) -> NarrativeEvent:
    atom_ids = tuple(corridor.ordered_atom_ids[0] for corridor in corridors)
    evidence_ids = tuple(corridor.provenance.evidence_ids[0] for corridor in corridors)
    return NarrativeEvent(
        authority=_authority(),
        ordered_corridor_ids=tuple(corridor.corridor_id for corridor in corridors),
        ordered_atom_ids=atom_ids,
        chapter_id="day-1",
        lane_id="lane-1",
        call_occurrence_id="call-1",
        temporary_container_id=None,
        temporary_arm_id=None,
        loop_id=None,
        entry_node_id=corridors[0].entry_node_id,
        exit_node_id=corridors[-1].exit_node_id,
        nested_choice_ids=(),
        rejoin_node_ids=(),
        deterministic_title="Event at line 1",
        coverage_state=CoverageState.COMPLETE,
        provenance=Provenance(atom_ids=atom_ids, evidence_ids=evidence_ids),
    )


def _profile() -> ProviderProfile:
    return ProviderProfile(
        provider="fake",
        adapter="deterministic-fake",
        adapter_version="1",
        requested_model="fake-model",
        settings=ProviderSettings((("reasoning_effort", "high"),)),
    )


def _consent(
    jobs: tuple[object, ...],
    *,
    profile: ProviderProfile | None = None,
    granted: bool = True,
) -> NarrativeConsentManifest:
    return NarrativeConsentManifest.for_jobs(
        run_id="synthetic-run-1",
        profile=profile or _profile(),
        jobs=jobs,
        consent_granted=granted,
    )


class _FakeProvider:
    def __init__(
        self,
        payloads: list[dict[str, object]],
        *,
        identity_profile: ProviderProfile | None = None,
    ) -> None:
        self.payloads = list(payloads)
        self.requests: list[NarrativeMapProviderRequest] = []
        self.cancel_count = 0
        self.identity_profile = identity_profile or _profile()

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        payload = self.payloads.pop(0)
        return NarrativeMapProviderResponse(
            request_id=request.request_id,
            provider=ProviderIdentity(
                provider=self.identity_profile.provider,
                adapter=self.identity_profile.adapter,
                adapter_version=self.identity_profile.adapter_version,
                requested_model=self.identity_profile.requested_model,
                resolved_model=self.identity_profile.requested_model,
                settings=self.identity_profile.settings,
            ),
            payload=payload,
            usage=ProviderUsage(10, 5, 1),
        )

    def cancel(self) -> None:
        self.cancel_count += 1


class _FakeSterileRunner:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[SterileRunRequest] = []
        self.cancel_count = 0

    def execute(
        self, request: SterileRunRequest, cancelled: Callable[[], bool]
    ) -> SterileRunResult:
        assert not cancelled()
        self.requests.append(request)
        return SterileRunResult(
            events=(
                {
                    "item": {
                        "type": "agent_message",
                        "text": json.dumps(self.payload),
                    }
                },
                {
                    "model": "fake-model",
                    "usage": {"input_tokens": 10, "output_tokens": 5, "cost_micros": 0},
                },
            ),
            cli_version="fake-cli",
        )

    def cancel(self) -> None:
        self.cancel_count += 1


class _FailingSterileRunner:
    def __init__(self) -> None:
        self.requests: list[SterileRunRequest] = []

    def execute(
        self, request: SterileRunRequest, cancelled: Callable[[], bool]
    ) -> SterileRunResult:
        assert not cancelled()
        self.requests.append(request)
        raise SterileRunnerError("synthetic_failure", "Synthetic sterile failure.")

    def cancel(self) -> None:
        pass


def test_boundary_projection_covers_each_adjacent_soft_candidate_once() -> None:
    first, second, third = _corridor("a", 0), _corridor("b", 1), _corridor("c", 2)
    candidates = (_candidate(first, second), _candidate(second, third))

    jobs = prepare_boundary_jobs(
        (first, second, third),
        candidates,
        _evidence(first, second, third),
    )

    assert tuple(job.subject_id for job in jobs) == tuple(
        candidate.candidate_id for candidate in candidates
    )
    assert len({job.job_id for job in jobs}) == 2
    assert all(job.payload["candidate_id"] == job.subject_id for job in jobs)
    assert all("hard_boundary" not in str(job.payload) for job in jobs)


def test_sterile_provider_uses_m15_prompt_and_schema_without_process_authority() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    runner = _FakeSterileRunner(payload)
    request = NarrativeMapProviderRequest(
        request_id="request-1",
        consent=_consent((job,)),
        profile=_profile(),
        job=job,
    )

    response = SterileNarrativeMapProvider(runner=runner).submit(request, lambda: False)

    assert response.payload == payload
    assert len(runner.requests) == 1
    sterile_request = runner.requests[0]
    assert sterile_request.schema_path.name == "boundary_decision_v1.schema.json"
    prompt = json.loads(sterile_request.stdin)
    assert prompt["version"] == "m15-boundary-prompt-v1"
    assert prompt["request"]["job"]["candidate_id"] == candidate.candidate_id
    assert "use filesystem, web, tools, MCP, or application authority" in prompt["forbidden"]


def test_sterile_provider_revalidates_consent_freshness_at_submit() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    job = prepare_boundary_jobs(
        (first, second), (_candidate(first, second),), _evidence(first, second)
    )[0]
    consent = _consent((job,))
    request = NarrativeMapProviderRequest(
        request_id="request-expiry",
        consent=consent,
        profile=_profile(),
        job=job,
    )
    object.__setattr__(
        consent,
        "expires_utc",
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    runner = _FakeSterileRunner({"decisions": []})

    with pytest.raises(ValueError, match="fresh"):
        SterileNarrativeMapProvider(runner=runner).submit(request, lambda: False)
    assert runner.requests == []


def test_provider_request_cannot_exceed_exact_consent_transport_bounds() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    job = prepare_boundary_jobs(
        (first, second), (_candidate(first, second),), _evidence(first, second)
    )[0]
    consent = NarrativeConsentManifest.for_jobs(
        run_id="bounded-request",
        profile=_profile(),
        jobs=(job,),
        consent_granted=True,
        maximum_provider_calls=1,
        maximum_input_bytes=100,
        maximum_output_bytes=200,
        timeout_seconds=1.0,
    )
    common = {
        "request_id": "bounded-request-1",
        "consent": consent,
        "profile": _profile(),
        "job": job,
    }

    with pytest.raises(ValueError, match=r"input.*consent"):
        NarrativeMapProviderRequest(
            **common,
            maximum_input_bytes=101,
            maximum_output_bytes=200,
            timeout_seconds=1.0,
        )
    with pytest.raises(ValueError, match=r"output.*consent"):
        NarrativeMapProviderRequest(
            **common,
            maximum_input_bytes=100,
            maximum_output_bytes=201,
            timeout_seconds=1.0,
        )
    with pytest.raises(ValueError, match=r"timeout.*consent"):
        NarrativeMapProviderRequest(
            **common,
            maximum_input_bytes=100,
            maximum_output_bytes=200,
            timeout_seconds=2.0,
        )


def test_sterile_provider_consumes_one_call_consent_before_sequential_reuse() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    runner = _FakeSterileRunner(payload)
    consent = NarrativeConsentManifest.for_jobs(
        run_id="single-call",
        profile=_profile(),
        jobs=(job,),
        consent_granted=True,
        maximum_provider_calls=1,
    )
    request = NarrativeMapProviderRequest(
        request_id="single-call-request",
        consent=consent,
        profile=_profile(),
        job=job,
    )
    provider = SterileNarrativeMapProvider(runner=runner)

    provider.submit(request, lambda: False)
    with pytest.raises(NarrativeMapProviderError, match="provider call grant") as exc_info:
        provider.submit(request, lambda: False)
    assert exc_info.value.error_code == "consent_call_limit"
    assert len(runner.requests) == 1


def test_consent_call_ledger_survives_manifest_copy_and_provider_instance() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    consent = NarrativeConsentManifest.for_jobs(
        run_id="copied-single-call",
        profile=_profile(),
        jobs=(job,),
        consent_granted=True,
        maximum_provider_calls=1,
    )
    copied_consent = replace(consent)
    first_request = NarrativeMapProviderRequest(
        request_id="copied-single-call-1",
        consent=consent,
        profile=_profile(),
        job=job,
    )
    second_request = NarrativeMapProviderRequest(
        request_id="copied-single-call-2",
        consent=copied_consent,
        profile=_profile(),
        job=job,
    )
    first_runner = _FakeSterileRunner(payload)
    second_runner = _FakeSterileRunner(payload)

    SterileNarrativeMapProvider(runner=first_runner).submit(first_request, lambda: False)
    with pytest.raises(NarrativeMapProviderError) as exc_info:
        SterileNarrativeMapProvider(runner=second_runner).submit(
            second_request, lambda: False
        )

    assert exc_info.value.error_code == "consent_call_limit"
    assert len(first_runner.requests) == 1
    assert second_runner.requests == []


def test_sterile_provider_atomically_reserves_one_call_under_double_submit() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    runner = _FakeSterileRunner(payload)
    consent = NarrativeConsentManifest.for_jobs(
        run_id="concurrent-single-call",
        profile=_profile(),
        jobs=(job,),
        consent_granted=True,
        maximum_provider_calls=1,
    )
    request = NarrativeMapProviderRequest(
        request_id="concurrent-single-call-request",
        consent=consent,
        profile=_profile(),
        job=job,
    )
    provider = SterileNarrativeMapProvider(runner=runner)
    ready = Barrier(3)

    def submit() -> object:
        ready.wait()
        try:
            return provider.submit(request, lambda: False)
        except NarrativeMapProviderError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(submit), executor.submit(submit))
        ready.wait()
        outcomes = tuple(future.result() for future in futures)

    assert sum(isinstance(outcome, NarrativeMapProviderResponse) for outcome in outcomes) == 1
    failures = [
        outcome for outcome in outcomes if isinstance(outcome, NarrativeMapProviderError)
    ]
    assert len(failures) == 1
    assert "provider call grant" in str(failures[0])
    assert failures[0].error_code == "consent_call_limit"
    assert len(runner.requests) == 1


def test_sterile_provider_does_not_refund_grant_after_runner_failure() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    job = prepare_boundary_jobs(
        (first, second), (_candidate(first, second),), _evidence(first, second)
    )[0]
    consent = NarrativeConsentManifest.for_jobs(
        run_id="failed-single-call",
        profile=_profile(),
        jobs=(job,),
        consent_granted=True,
        maximum_provider_calls=1,
    )
    request = NarrativeMapProviderRequest(
        request_id="failed-single-call-request",
        consent=consent,
        profile=_profile(),
        job=job,
    )
    runner = _FailingSterileRunner()
    provider = SterileNarrativeMapProvider(runner=runner)

    with pytest.raises(NarrativeMapProviderError) as first_error:
        provider.submit(request, lambda: False)
    assert first_error.value.error_code == "synthetic_failure"
    with pytest.raises(NarrativeMapProviderError) as second_error:
        provider.submit(request, lambda: False)
    assert second_error.value.error_code == "consent_call_limit"
    assert len(runner.requests) == 1


def test_submit_revalidates_mutated_bounds_without_consuming_call_grant() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    consent = NarrativeConsentManifest.for_jobs(
        run_id="mutated-bounds",
        profile=_profile(),
        jobs=(job,),
        consent_granted=True,
        maximum_provider_calls=1,
        maximum_input_bytes=10_000,
    )
    request = NarrativeMapProviderRequest(
        request_id="mutated-bounds-request",
        consent=consent,
        profile=_profile(),
        job=job,
        maximum_input_bytes=10_000,
    )
    runner = _FakeSterileRunner(payload)
    provider = SterileNarrativeMapProvider(runner=runner)

    object.__setattr__(request, "maximum_input_bytes", 10_001)
    with pytest.raises(ValueError, match=r"input.*consent"):
        provider.submit(request, lambda: False)
    assert runner.requests == []

    object.__setattr__(request, "maximum_input_bytes", 10_000)
    provider.submit(request, lambda: False)
    assert len(runner.requests) == 1


def test_cancellation_before_reservation_does_not_consume_call_grant() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    consent = NarrativeConsentManifest.for_jobs(
        run_id="cancel-before-reserve",
        profile=_profile(),
        jobs=(job,),
        consent_granted=True,
        maximum_provider_calls=1,
    )
    request = NarrativeMapProviderRequest(
        request_id="cancel-before-reserve-request",
        consent=consent,
        profile=_profile(),
        job=job,
    )
    runner = _FakeSterileRunner(payload)
    provider = SterileNarrativeMapProvider(runner=runner)

    with pytest.raises(NarrativeMapProviderError) as cancelled_error:
        provider.submit(request, lambda: True)
    assert cancelled_error.value.error_code == "cancelled"
    provider.submit(request, lambda: False)
    assert len(runner.requests) == 1


def test_boundary_projection_rejects_nonadjacent_and_hard_candidates() -> None:
    first, second, third = _corridor("a", 0), _corridor("b", 1), _corridor("c", 2)
    try:
        prepare_boundary_jobs(
            (first, second, third),
            (_candidate(first, third),),
            _evidence(first, second, third),
        )
    except ValueError as exc:
        assert "adjacent" in str(exc)
    else:
        raise AssertionError("non-adjacent boundary entered a provider job")

    hard_left = _corridor("hard-left", 3, hard_after=True)
    hard_right = _corridor("hard-right", 4, hard_before=True)
    try:
        prepare_boundary_jobs(
            (hard_left, hard_right),
            (_candidate(hard_left, hard_right),),
            _evidence(hard_left, hard_right),
        )
    except ValueError as exc:
        assert "hard boundary" in str(exc)
    else:
        raise AssertionError("hard boundary entered a provider job")


def test_boundary_validation_is_item_isolated_and_detects_omissions_duplicates_and_extras() -> None:
    first, second, third = _corridor("a", 0), _corridor("b", 1), _corridor("c", 2)
    left, right = _candidate(first, second), _candidate(second, third)
    result = validate_boundary_response(
        {
            "decisions": [
                {
                    "candidate_id": left.candidate_id,
                    "decision": "merge",
                    "reason": "The action continues.",
                    "confidence": 0.9,
                    "warnings": [],
                },
                {
                    "candidate_id": left.candidate_id,
                    "decision": "split",
                    "reason": "Duplicate reinterpretation.",
                    "confidence": 0.8,
                    "warnings": [],
                },
                {
                    "candidate_id": "unknown",
                    "decision": "split",
                    "reason": "Wrong scope.",
                    "confidence": 0.5,
                    "warnings": [],
                    "edges": [],
                },
            ]
        },
        (left, right),
        provider_identity=None,
    )

    assert result.decisions == ()
    assert result.omitted_candidate_ids == (right.candidate_id,)
    assert {finding.code for finding in result.findings} >= {
        "duplicate_candidate",
        "unknown_candidate",
        "extra_field",
        "omitted_candidate",
    }


def test_event_summary_validation_checks_exact_evidence_and_fields() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    valid = validate_event_summary_response(
        {
            "event_id": event.event_id,
            "title": "A difficult conversation",
            "summary": "The characters discuss a difficult choice.",
            "characters": ["Narrator"],
            "claims": [
                {
                    "claim_class": "factual",
                    "text": "A choice is discussed.",
                    "evidence_ids": [first.provenance.evidence_ids[0]],
                }
            ],
            "warnings": [],
        },
        event,
        known_characters=("Narrator",),
        provider_identity=None,
    )
    assert valid.summary is not None

    invalid = validate_event_summary_response(
        {
            "event_id": event.event_id,
            "title": "Start",
            "summary": "Unsupported.",
            "characters": ["Unknown"],
            "claims": [
                {
                    "claim_class": "factual",
                    "text": "Invented.",
                    "evidence_ids": ["foreign-evidence"],
                }
            ],
            "warnings": [],
            "members": ["invented-membership"],
        },
        event,
        known_characters=("Narrator",),
        provider_identity=None,
        story_facing=True,
    )
    assert invalid.summary is None
    assert {finding.code for finding in invalid.findings} >= {
        "blocked_title",
        "unknown_character",
        "unknown_evidence",
        "extra_field",
    }


def test_repository_round_trip_is_independent_and_does_not_retain_source_packets(
    tmp_path: Path,
) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    job = prepare_boundary_jobs(
        (first, second),
        (_candidate(first, second),),
        _evidence(first, second),
    )[0]
    project_path = tmp_path / "track-b.rsmproj"
    with Project.create(project_path) as project:
        repository = NarrativeMapRepository(project)
        repository.stage(job, _profile())
        record = repository.get(job.kind, job.job_id)
        assert record is not None
        assert record.status is NarrativeJobStatus.PENDING
        assert "Synthetic story text" not in project.canonical_export().decode("utf-8")
        assert "source_packet" not in project.canonical_export().decode("utf-8")

    with Project.open(project_path) as project:
        record = NarrativeMapRepository(project).get(job.kind, job.job_id)
        assert record is not None
        assert record.input_hash == job.input_hash


def test_workflow_allows_one_schema_repair_and_exact_reopen_cache_is_zero_submit(
    tmp_path: Path,
) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second),
        (candidate,),
        _evidence(first, second),
    )[0]
    provider = _FakeProvider(
        [
            {"decisions": [{"candidate_id": candidate.candidate_id, "decision": "merge"}]},
            {
                "decisions": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "decision": "merge",
                        "reason": "The same action continues.",
                        "confidence": 0.9,
                        "warnings": [],
                    }
                ]
            },
        ]
    )
    project_path = tmp_path / "repair.rsmproj"
    with Project.create(project_path) as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_boundary_jobs((job,), consent=_consent((job,)))
        assert report.validated_job_ids == (job.job_id,)
        assert report.provider_calls == 2
        assert provider.requests[0].repair_codes == ()
        assert provider.requests[1].repair_codes
        assert provider.requests[0].job.subject_id == provider.requests[1].job.subject_id

    replay_provider = _FakeProvider([])
    with Project.open(project_path) as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), replay_provider, _profile()
        ).run_boundary_jobs((job,), consent=_consent((job,)))
        assert report.validated_job_ids == (job.job_id,)
        assert report.provider_calls == 0
        assert report.cache_hits == 1
        assert replay_provider.requests == []


def test_cancellation_preserves_validated_work_and_resume_retries_only_missing_jobs(
    tmp_path: Path,
) -> None:
    first, second, third = _corridor("a", 0), _corridor("b", 1), _corridor("c", 2)
    candidates = (_candidate(first, second), _candidate(second, third))
    jobs = prepare_boundary_jobs(
        (first, second, third), candidates, _evidence(first, second, third)
    )
    def good_payload(candidate: BoundaryCandidate) -> dict[str, object]:
        return {
            "decisions": [
                {
                    "candidate_id": candidate.candidate_id,
                    "decision": "split",
                    "reason": "The narrative objective changes.",
                    "confidence": 0.8,
                    "warnings": [],
                }
            ]
        }
    provider = _FakeProvider([good_payload(candidates[0])])
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 3

    project_path = tmp_path / "cancel.rsmproj"
    with Project.create(project_path) as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_boundary_jobs(
            jobs,
            consent=_consent(jobs),
            cancelled=cancelled,
        )
        assert report.validated_job_ids == (jobs[0].job_id,)
        assert report.cancelled

    resume_provider = _FakeProvider([good_payload(candidates[1])])
    with Project.open(project_path) as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), resume_provider, _profile()
        ).run_boundary_jobs(jobs, consent=_consent(jobs))
        assert report.provider_calls == 1
        assert len(resume_provider.requests) == 1
        assert resume_provider.requests[0].job.job_id == jobs[1].job_id


def test_summary_failure_preserves_event_and_service_reads_never_call_provider(
    tmp_path: Path,
) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    summary_job = prepare_event_summary_jobs(
        (event,), _evidence(first, second), known_characters={event.event_id: ("Narrator",)}
    )[0]
    provider = _FakeProvider([{"event_id": event.event_id, "title": "Missing fields"}])
    with Project.create(tmp_path / "summary.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        report = NarrativeBoundaryWorkflow(repository, provider, _profile()).run_event_summary_jobs(
            (summary_job,), consent=_consent((summary_job,))
        )
        assert report.failed_job_ids == (summary_job.job_id,)
        service = NarrativeMapService(repository)
        summaries = service.read_event_summaries((event,))
        assert summaries[0].event_id == event.event_id
        assert summaries[0].title == event.deterministic_title
        assert summaries[0].summary is None
        assert len(provider.requests) == 2  # initial invalid response plus one bounded repair
        failed_record = repository.get(summary_job.kind, summary_job.job_id)
        assert failed_record is not None
        assert failed_record.attempt_count == 2
        assert failed_record.provider_identity is not None
        assert failed_record.usage is not None
        assert failed_record.usage["provider_calls"] == 2
        durable = project.canonical_export().decode("utf-8")
        assert "Missing fields" not in durable


def test_cache_identity_includes_exact_provider_settings(tmp_path: Path) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The narrative objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    project_path = tmp_path / "identity.rsmproj"
    with Project.create(project_path) as project:
        first_provider = _FakeProvider([payload])
        NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), first_provider, _profile()
        ).run_boundary_jobs((job,), consent=_consent((job,)))

    changed_profile = ProviderProfile(
        provider="fake",
        adapter="deterministic-fake",
        adapter_version="1",
        requested_model="fake-model",
        settings=ProviderSettings((("reasoning_effort", "xhigh"),)),
    )
    changed_provider = _FakeProvider([payload], identity_profile=changed_profile)
    with Project.open(project_path) as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), changed_provider, changed_profile
        ).run_boundary_jobs(
            (job,), consent=_consent((job,), profile=changed_profile)
        )
        assert report.provider_calls == 1
        assert report.cache_hits == 0


def test_exact_consent_is_granted_and_bound_to_jobs_and_profile(tmp_path: Path) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    provider = _FakeProvider([])
    with Project.create(tmp_path / "consent.rsmproj") as project:
        workflow = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        )
        with pytest.raises(ValueError, match="granted"):
            workflow.run_boundary_jobs((job,), consent=_consent((job,), granted=False))
        with pytest.raises(ValueError, match="scope"):
            workflow.run_boundary_jobs((job,), consent=_consent((), granted=True))
    assert provider.requests == []


def test_schema_repair_cannot_change_a_valid_boundary_decision(tmp_path: Path) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    provider = _FakeProvider(
        [
            {
                "decisions": [
                    {"candidate_id": candidate.candidate_id, "decision": "merge"}
                ]
            },
            {
                "decisions": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "decision": "split",
                        "reason": "Changed meaning.",
                        "confidence": 0.9,
                        "warnings": [],
                    }
                ]
            },
        ]
    )
    with Project.create(tmp_path / "semantic-repair.rsmproj") as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_boundary_jobs((job,), consent=_consent((job,)))
        assert report.validated_job_ids == ()
        assert report.failed_job_ids == (job.job_id,)
        assert report.provider_calls == 2


def test_mutated_prepared_payload_fails_before_submit(tmp_path: Path) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    job = prepare_boundary_jobs(
        (first, second), (_candidate(first, second),), _evidence(first, second)
    )[0]
    mutated_payload = dict(job.payload)
    mutated_payload["invented_membership"] = ["foreign-atom"]
    with pytest.raises(ValueError, match="input hash"):
        replace(job, payload=mutated_payload)

    consent = _consent((job,))
    job.payload["invented_membership"] = ["foreign-atom"]
    provider = _FakeProvider([])
    with (
        Project.create(tmp_path / "mutated-input.rsmproj") as project,
        pytest.raises(ValueError, match="input hash"),
    ):
        NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_boundary_jobs((job,), consent=consent)
    assert provider.requests == []


def test_summary_schema_repair_cannot_change_valid_title_semantics(tmp_path: Path) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    job = prepare_event_summary_jobs(
        (event,), _evidence(first, second), known_characters={event.event_id: ("Narrator",)}
    )[0]
    provider = _FakeProvider(
        [
            {"event_id": event.event_id, "title": "Original action"},
            {
                "event_id": event.event_id,
                "title": "Different action",
                "summary": "A complete synthetic summary.",
                "characters": ["Narrator"],
                "claims": [],
                "warnings": [],
            },
        ]
    )
    with Project.create(tmp_path / "summary-repair-lock.rsmproj") as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_event_summary_jobs((job,), consent=_consent((job,)))
        assert report.validated_job_ids == ()
        assert report.failed_job_ids == (job.job_id,)


def test_summary_repair_cannot_replace_valid_claim_when_sibling_is_invalid(
    tmp_path: Path,
) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    job = prepare_event_summary_jobs(
        (event,), _evidence(first, second), known_characters={event.event_id: ("Narrator",)}
    )[0]
    original_claim = {
        "claim_class": "factual",
        "text": "The first supported fact remains fixed.",
        "evidence_ids": [first.provenance.evidence_ids[0]],
    }
    replacement_claim = {
        "claim_class": "factual",
        "text": "A different supported fact replaces it.",
        "evidence_ids": [second.provenance.evidence_ids[0]],
    }
    repaired_sibling = {
        "claim_class": "interpretive",
        "text": "The exchange suggests a difficult choice.",
        "evidence_ids": [second.provenance.evidence_ids[0]],
    }
    provider = _FakeProvider(
        [
            {
                "event_id": event.event_id,
                "title": "A difficult exchange",
                "summary": "The characters discuss a difficult choice.",
                "characters": ["Narrator"],
                "claims": [
                    original_claim,
                    {
                        "claim_class": "factual",
                        "text": "Unsupported sibling.",
                        "evidence_ids": ["foreign-evidence"],
                    },
                ],
                "warnings": [],
            },
            {
                "event_id": event.event_id,
                "title": "A difficult exchange",
                "summary": "The characters discuss a difficult choice.",
                "characters": ["Narrator"],
                "claims": [replacement_claim, repaired_sibling],
                "warnings": [],
            },
        ]
    )

    with Project.create(tmp_path / "summary-claim-reinterpretation.rsmproj") as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_event_summary_jobs((job,), consent=_consent((job,)))

    assert report.validated_job_ids == ()
    assert report.failed_job_ids == (job.job_id,)
    assert report.provider_calls == 2


def test_summary_repair_preserves_valid_claim_slot_and_exact_evidence_identity(
    tmp_path: Path,
) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    job = prepare_event_summary_jobs(
        (event,), _evidence(first, second), known_characters={event.event_id: ("Narrator",)}
    )[0]
    original_claim = {
        "claim_class": "factual",
        "text": "The supported fact remains in its original slot.",
        "evidence_ids": [first.provenance.evidence_ids[0]],
    }
    repaired_sibling = {
        "claim_class": "interpretive",
        "text": "The exchange suggests a difficult choice.",
        "evidence_ids": [second.provenance.evidence_ids[0]],
    }
    common = {
        "event_id": event.event_id,
        "title": "A difficult exchange",
        "summary": "The characters discuss a difficult choice.",
        "characters": ["Narrator"],
        "warnings": [],
    }
    provider = _FakeProvider(
        [
            {
                **common,
                "claims": [
                    original_claim,
                    {
                        "claim_class": "factual",
                        "text": "Unsupported sibling.",
                        "evidence_ids": ["foreign-evidence"],
                    },
                ],
            },
            {**common, "claims": [original_claim, repaired_sibling]},
        ]
    )

    with Project.create(tmp_path / "summary-claim-repair.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        report = NarrativeBoundaryWorkflow(
            repository, provider, _profile()
        ).run_event_summary_jobs((job,), consent=_consent((job,)))
        record = repository.get(job.kind, job.job_id)

    assert report.validated_job_ids == (job.job_id,)
    assert report.failed_job_ids == ()
    assert record is not None
    assert record.result is not None
    claims = record.result["claims"]
    assert isinstance(claims, list)
    assert tuple(claim["text"] for claim in claims if isinstance(claim, dict)) == (
        original_claim["text"],
        repaired_sibling["text"],
    )
    first_claim = claims[0]
    assert isinstance(first_claim, dict)
    assert first_claim["evidence_ids"] == [first.provenance.evidence_ids[0]]


def test_event_summary_validation_rejects_duplicate_claims() -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    claim = {
        "claim_class": "factual",
        "text": "The same supported fact.",
        "evidence_ids": [first.provenance.evidence_ids[0]],
    }
    result = validate_event_summary_response(
        {
            "event_id": event.event_id,
            "title": "A difficult exchange",
            "summary": "The characters discuss a difficult choice.",
            "characters": ["Narrator"],
            "claims": [claim, claim],
            "warnings": [],
        },
        event,
        known_characters=("Narrator",),
        provider_identity=None,
    )

    assert result.summary is None
    assert [finding.code for finding in result.findings].count("duplicate_claim") == 2


@pytest.mark.parametrize("mutation", ["reorder", "evidence", "append", "duplicate"])
def test_summary_claim_slots_reject_order_evidence_and_invention_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    job = prepare_event_summary_jobs(
        (event,), _evidence(first, second), known_characters={event.event_id: ("Narrator",)}
    )[0]
    claim_a = {
        "claim_class": "factual",
        "text": "The first supported fact stays ordered.",
        "evidence_ids": [
            first.provenance.evidence_ids[0],
            second.provenance.evidence_ids[0],
        ],
    }
    claim_b = {
        "claim_class": "interpretive",
        "text": "The second supported claim stays ordered.",
        "evidence_ids": [second.provenance.evidence_ids[0]],
    }
    fixed = {
        "claim_class": "factual",
        "text": "The invalid slot is repaired in place.",
        "evidence_ids": [first.provenance.evidence_ids[0]],
    }
    repair_claims = [claim_a, fixed, claim_b]
    if mutation == "reorder":
        repair_claims = [claim_b, fixed, claim_a]
    elif mutation == "evidence":
        repair_claims = [
            {**claim_a, "evidence_ids": list(reversed(claim_a["evidence_ids"]))},
            fixed,
            claim_b,
        ]
    elif mutation == "append":
        repair_claims = [claim_a, fixed, claim_b, {**fixed, "text": "Invented append."}]
    elif mutation == "duplicate":
        repair_claims = [claim_a, claim_a, claim_b]
    common = {
        "event_id": event.event_id,
        "title": "An ordered exchange",
        "summary": "The exchange retains only evidence-backed claims.",
        "characters": ["Narrator"],
        "warnings": [],
    }
    provider = _FakeProvider(
        [
            {
                **common,
                "claims": [
                    claim_a,
                    {
                        "claim_class": "factual",
                        "text": "Unsupported middle slot.",
                        "evidence_ids": ["foreign-evidence"],
                    },
                    claim_b,
                ],
            },
            {**common, "claims": repair_claims},
        ]
    )

    with Project.create(tmp_path / f"claim-{mutation}.rsmproj") as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_event_summary_jobs((job,), consent=_consent((job,)))

    assert report.validated_job_ids == ()
    assert report.failed_job_ids == (job.job_id,)


def test_summary_repair_cannot_invent_claims_when_claims_array_was_missing(
    tmp_path: Path,
) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    event = _event(first, second)
    job = prepare_event_summary_jobs(
        (event,), _evidence(first, second), known_characters={event.event_id: ("Narrator",)}
    )[0]
    common = {
        "event_id": event.event_id,
        "title": "A bounded repair",
        "summary": "The repair cannot invent an unrequested claim slot.",
        "characters": ["Narrator"],
        "warnings": [],
    }
    provider = _FakeProvider(
        [
            common,
            {
                **common,
                "claims": [
                    {
                        "claim_class": "factual",
                        "text": "Invented during repair.",
                        "evidence_ids": [first.provenance.evidence_ids[0]],
                    }
                ],
            },
        ]
    )

    with Project.create(tmp_path / "claim-invention.rsmproj") as project:
        report = NarrativeBoundaryWorkflow(
            NarrativeMapRepository(project), provider, _profile()
        ).run_event_summary_jobs((job,), consent=_consent((job,)))

    assert report.validated_job_ids == ()
    assert report.failed_job_ids == (job.job_id,)


def test_fabricated_soft_signal_cannot_enter_projection() -> None:
    first = replace(_corridor("a", 0), soft_boundary_signals=())
    second = replace(_corridor("b", 1), soft_boundary_signals=())
    with pytest.raises(ValueError, match="soft signal"):
        prepare_boundary_jobs(
            (first, second), (_candidate(first, second),), _evidence(first, second)
        )


def test_cache_replay_restores_service_visible_validated_record(tmp_path: Path) -> None:
    first, second = _corridor("a", 0), _corridor("b", 1)
    candidate = _candidate(first, second)
    job = prepare_boundary_jobs(
        (first, second), (candidate,), _evidence(first, second)
    )[0]
    payload = {
        "decisions": [
            {
                "candidate_id": candidate.candidate_id,
                "decision": "split",
                "reason": "The objective changes.",
                "confidence": 0.8,
                "warnings": [],
            }
        ]
    }
    profile_b = ProviderProfile(
        provider="fake",
        adapter="deterministic-fake",
        adapter_version="1",
        requested_model="fake-model",
        settings=ProviderSettings((("reasoning_effort", "xhigh"),)),
    )
    project_path = tmp_path / "cache-restore.rsmproj"
    with Project.create(project_path) as project:
        repository = NarrativeMapRepository(project)
        NarrativeBoundaryWorkflow(
            repository, _FakeProvider([payload]), _profile()
        ).run_boundary_jobs((job,), consent=_consent((job,)))
        NarrativeBoundaryWorkflow(
            repository,
            _FakeProvider([payload], identity_profile=profile_b),
            profile_b,
        ).run_boundary_jobs((job,), consent=_consent((job,), profile=profile_b))
        replay = NarrativeBoundaryWorkflow(
            repository, _FakeProvider([]), _profile()
        ).run_boundary_jobs((job,), consent=_consent((job,)))
        assert replay.provider_calls == 0
        assert replay.cache_hits == 1
        decision = NarrativeMapService(repository).read_boundary_decisions((candidate,))[0]
        assert decision.decision.value == "split"

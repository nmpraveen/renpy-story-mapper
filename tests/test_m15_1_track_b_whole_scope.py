from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.contracts import AuthorityBinding, canonical_hash
from renpy_story_mapper.narrative_map.persistence import (
    NarrativeMapRepository,
    SemanticCallLimitError,
)
from renpy_story_mapper.narrative_map.provider import (
    SEMANTIC_BOUNDARY_PROMPT_VERSION,
    SEMANTIC_BOUNDARY_RESPONSE_SCHEMA,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
    SterileNarrativeMapProvider,
    WholeScopeEditorialSubject,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    M15_WHOLE_SCOPE_EDITORIAL_INPUT_SCHEMA,
    M15_WHOLE_SCOPE_HIERARCHY_INPUT_SCHEMA,
    BoundaryWindow,
)
from renpy_story_mapper.narrative_map.service import NarrativeMapService
from renpy_story_mapper.organization.sterile_runner import SterileRunRequest, SterileRunResult
from renpy_story_mapper.project import Project


def _authority() -> AuthorityBinding:
    return AuthorityBinding("generation", "m10-v1", "m10-hash", "m11-v1", "m11-hash")


def _profile(model: str = "fake-semantic-model") -> ProviderProfile:
    return ProviderProfile(
        "fake",
        "deterministic-fake",
        "1",
        model,
        ProviderSettings((("reasoning_effort", "high"),)),
    )


def _hierarchy_input() -> dict[str, object]:
    return {
        "schema": M15_WHOLE_SCOPE_HIERARCHY_INPUT_SCHEMA,
        "scope_id": "scope-day-1",
        "authority": _authority().to_dict(),
        "ordered_unit_ids": ["unit-a", "unit-b"],
        "units": [
            {"unit_id": "unit-a", "evidence_ids": ["evidence-a"]},
            {"unit_id": "unit-b", "evidence_ids": ["evidence-b"]},
        ],
        "hard_locks": [],
    }


def _hierarchy_output() -> dict[str, object]:
    return {
        "scope_id": "scope-day-1",
        "beat_groups": [
            {
                "proposal_key": "proposal-a",
                "ordered_unit_ids": ["unit-a"],
                "confidence": 0.9,
                "reason": "The first synthetic action stands alone.",
                "warnings": [],
            },
            {
                "proposal_key": "proposal-b",
                "ordered_unit_ids": ["unit-b"],
                "confidence": 0.9,
                "reason": "The second synthetic action stands alone.",
                "warnings": [],
            },
        ],
        "major_clusters": [
            {
                "proposal_key": "cluster-day",
                "ordered_beat_keys": ["proposal-a", "proposal-b"],
                "confidence": 0.9,
                "reason": "Both actions belong to the same synthetic period.",
                "warnings": [],
            }
        ],
        "uncertain_unit_ids": [],
        "warnings": [],
    }


def _subjects() -> tuple[WholeScopeEditorialSubject, ...]:
    return (
        WholeScopeEditorialSubject(
            "beat", "beat-a", "membership-a", ("evidence-a",), ("Ava",)
        ),
        WholeScopeEditorialSubject(
            "major_cluster",
            "cluster-day",
            "membership-cluster",
            ("evidence-a", "evidence-b"),
            ("Ava",),
        ),
    )


def _editorial_input(hierarchy_hash: str) -> dict[str, object]:
    return {
        "schema": M15_WHOLE_SCOPE_EDITORIAL_INPUT_SCHEMA,
        "scope_id": "scope-day-1",
        "authority": _authority().to_dict(),
        "hierarchy_hash": hierarchy_hash,
        "subjects": [item.to_dict() for item in _subjects()],
        "evidence": [
            {"evidence_id": "evidence-a", "text": "Ava arrives."},
            {"evidence_id": "evidence-b", "text": "Ava settles in."},
        ],
    }


def _editorial_record(subject: WholeScopeEditorialSubject) -> dict[str, object]:
    return {
        "subject_kind": subject.subject_kind,
        "subject_id": subject.subject_id,
        "membership_hash": subject.membership_hash,
        "presentation_role": "story",
        "title": "Ava Arrives" if subject.subject_kind == "beat" else "A New Day Begins",
        "summary": "Ava arrives and then settles into the beginning of the day.",
        "characters": ["Ava"],
        "claims": [
            {
                "claim_class": "factual",
                "text": "Ava completes the supported synthetic action.",
                "evidence_ids": [subject.evidence_ids[0]],
            }
        ],
        "warnings": [],
    }


def _editorial_output(hierarchy_hash: str) -> dict[str, object]:
    return {
        "scope_id": "scope-day-1",
        "hierarchy_hash": hierarchy_hash,
        "records": [_editorial_record(item) for item in _subjects()],
        "warnings": [],
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
        self, request: SterileRunRequest, cancelled: Callable[[], bool]
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


def _prepare_hierarchy(service: NarrativeMapService, *, replay: bool = False):
    return service.prepare_whole_scope_hierarchy(
        _authority(),
        "scope-day-1",
        ("unit-a", "unit-b"),
        _hierarchy_input(),
        known_evidence_ids=("evidence-a", "evidence-b"),
        known_characters=("Ava",),
        profile=_profile(),
        run_id="stage-h-run",
        source_hash="source-hash",
        correction_id="m15.1",
        replay_existing=replay,
    )


def _run_valid_hierarchy(service: NarrativeMapService):
    preparation = _prepare_hierarchy(service)
    consent = preparation.granted_consent()
    service.confirm_whole_scope_consent(preparation, consent)
    report = service.start_whole_scope_hierarchy(
        preparation,
        provider=_FakeProvider([_hierarchy_output()]),
        consent=consent,
    )
    assert report.provider_calls == 1
    hierarchy = {"schema": "synthetic-authoritative-hierarchy-v1", "beats": ["beat-a"]}
    status = service.freeze_whole_scope_hierarchy(preparation, hierarchy)
    assert status.hierarchy_hash == canonical_hash(hierarchy)
    return preparation, status.hierarchy_hash


@pytest.mark.parametrize("fault", ["malformed", "partial", "duplicate", "foreign", "stale"])
def test_stage_h_fake_provider_fault_matrix_allows_only_one_targeted_repair(
    tmp_path: Path, fault: str
) -> None:
    valid = _hierarchy_output()
    invalid = copy.deepcopy(valid)
    if fault == "malformed":
        invalid = {"unexpected": True}
    elif fault == "partial":
        invalid["beat_groups"] = copy.deepcopy(valid["beat_groups"][:1])  # type: ignore[index]
    elif fault == "duplicate":
        invalid["beat_groups"][0]["ordered_unit_ids"] = ["unit-a", "unit-a"]  # type: ignore[index]
    elif fault == "foreign":
        invalid["beat_groups"][0]["ordered_unit_ids"] = ["foreign-unit"]  # type: ignore[index]
    else:
        invalid["scope_id"] = "stale-scope"

    with Project.create(tmp_path / f"{fault}.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        provider = _FakeProvider([invalid, valid])
        report = service.start_whole_scope_hierarchy(
            preparation, provider=provider, consent=consent
        )
        status = service.whole_scope_semantic_status()

    assert report.provider_calls == 2
    assert report.validated_job_ids == (preparation.job.job_id,)
    assert len(provider.requests) == 2
    assert status is not None
    assert status.hierarchy_state == "validated"
    assert status.accounting.transport_submissions == 2
    assert status.accounting.combined_submission_count == 2


def test_stage_h_sterile_fake_routes_the_exact_frozen_prompt_and_schema(tmp_path: Path) -> None:
    with Project.create(tmp_path / "sterile-stage-h.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        runner = _FakeSterileRunner(_hierarchy_output())
        report = service.start_whole_scope_hierarchy(
            preparation,
            provider=SterileNarrativeMapProvider(runner=runner),
            consent=consent,
        )

    assert report.provider_calls == 1
    assert len(runner.requests) == 1
    request = runner.requests[0]
    assert request.schema_path.name == "whole_scope_hierarchy_v1.schema.json"
    envelope = json.loads(request.stdin)
    assert envelope["version"] == "m15-whole-scope-hierarchy-prompt-v1"
    assert envelope["request"]["job"]["schema"] == M15_WHOLE_SCOPE_HIERARCHY_INPUT_SCHEMA


def test_whole_scope_prepare_rejects_external_authority_and_credential_keys(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "sterile-input.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        for forbidden_key in ("private_oracle", "secretValue"):
            payload = _hierarchy_input()
            payload[forbidden_key] = "forbidden"
            with pytest.raises(ValueError):
                service.prepare_whole_scope_hierarchy(
                    _authority(),
                    "scope-day-1",
                    ("unit-a", "unit-b"),
                    payload,
                    known_evidence_ids=("evidence-a", "evidence-b"),
                    profile=_profile(),
                    run_id="sterile-input",
                    source_hash="source-hash",
                    correction_id="m15.1",
                )


def test_two_exact_consents_logical_provenance_accounting_and_zero_submit_reopen(
    tmp_path: Path,
) -> None:
    path = tmp_path / "whole-scope.rsmproj"
    with Project.create(path) as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        hierarchy_preparation, hierarchy_hash = _run_valid_hierarchy(service)
        assert hierarchy_hash is not None
        editorial_preparation = service.prepare_whole_scope_editorial(
            _authority(),
            "scope-day-1",
            hierarchy_hash,
            _subjects(),
            _editorial_input(hierarchy_hash),
            profile=_profile(),
            run_id="stage-e-run",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        assert editorial_preparation.consent.manifest_id != (
            hierarchy_preparation.consent.manifest_id
        )
        with pytest.raises(ValueError, match="exact reviewed manifest"):
            service.confirm_whole_scope_consent(
                editorial_preparation, hierarchy_preparation.granted_consent()
            )
        consent = editorial_preparation.granted_consent()
        service.confirm_whole_scope_consent(editorial_preparation, consent)
        valid = _editorial_output(hierarchy_hash)
        partial = copy.deepcopy(valid)
        partial["records"] = copy.deepcopy(valid["records"][:1])  # type: ignore[index]
        provider = _FakeProvider([partial, valid])
        report = service.start_whole_scope_editorial(
            editorial_preparation, provider=provider, consent=consent
        )
        status = service.whole_scope_semantic_status()
        publication = service.read_current_whole_scope_publication()
        logical_records = repository.read_whole_scope_logical_records()
        hierarchy_cache = repository.cache_key(
            hierarchy_preparation.job, hierarchy_preparation.consent.profile
        )
        editorial_cache = repository.cache_key(
            editorial_preparation.job, editorial_preparation.consent.profile
        )

    assert report.provider_calls == 2
    assert status is not None and status.editorial_state == "complete"
    assert status.accounting.logical_jobs == 3
    assert status.accounting.transport_submissions == 3
    assert status.accounting.combined_submission_count == 3
    assert publication is not None and publication["publication_hash"] == status.publication_hash
    assert len(logical_records) == 3
    assert len({item["logical_job_id"] for item in logical_records}) == 3
    assert all(item["logical_job_id"] != item["transport_batch_id"] for item in logical_records)
    assert hierarchy_cache != editorial_cache

    with Project.open(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        replay_hierarchy = _prepare_hierarchy(service, replay=True)
        hierarchy_report = service.start_whole_scope_hierarchy(replay_hierarchy)
        replay_editorial = service.prepare_whole_scope_editorial(
            _authority(),
            "scope-day-1",
            cast(str, status.hierarchy_hash),
            _subjects(),
            _editorial_input(cast(str, status.hierarchy_hash)),
            profile=_profile(),
            run_id="stage-e-run",
            source_hash="source-hash",
            correction_id="m15.1",
            replay_existing=True,
        )
        editorial_report = service.start_whole_scope_editorial(replay_editorial)
        reopened = service.whole_scope_semantic_status()

    assert hierarchy_report.provider_calls == editorial_report.provider_calls == 0
    assert hierarchy_report.cache_hits == editorial_report.cache_hits == 1
    assert reopened is not None
    assert reopened.publication_hash == status.publication_hash
    assert reopened.accounting.combined_submission_count == 3


def test_repair_ceiling_and_cancel_resume_are_durable(tmp_path: Path) -> None:
    with Project.create(tmp_path / "repair-ceiling.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        provider = _FakeProvider([{"bad": True}, {"still_bad": True}])
        failed = service.start_whole_scope_hierarchy(
            preparation, provider=provider, consent=consent
        )
        retry_provider = _FakeProvider([_hierarchy_output()])
        retried = service.retry_whole_scope_semantic_build(
            preparation, provider=retry_provider, consent=consent
        )
        status = service.whole_scope_semantic_status()

    assert failed.provider_calls == 2
    assert retried.provider_calls == 0
    assert retry_provider.requests == []
    assert status is not None
    assert status.accounting.combined_submission_count == 2

    with Project.create(tmp_path / "cancel-resume.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        cancelled = service.start_whole_scope_hierarchy(
            preparation,
            provider=_FakeProvider([]),
            consent=consent,
            cancelled=lambda: True,
        )
        resumed_provider = _FakeProvider([_hierarchy_output()])
        resumed = service.resume_whole_scope_semantic_build(
            preparation, provider=resumed_provider, consent=consent
        )
        resumed_status = service.whole_scope_semantic_status()

    assert cancelled.cancelled is True and cancelled.provider_calls == 0
    assert resumed.provider_calls == 1
    assert resumed_status is not None and resumed_status.hierarchy_state == "validated"


def test_combined_four_submission_ceiling_is_durable_and_atomic(tmp_path: Path) -> None:
    with Project.create(tmp_path / "four-submission-ceiling.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        for stage, manifest, batch in (
            ("hierarchy", "manifest-h", "batch-h"),
            ("editorial", "manifest-e", "batch-e"),
        ):
            for attempt in (1, 2):
                repository.reserve_whole_scope_provider_submission(
                    stage=stage,
                    manifest_id=manifest,
                    maximum_manifest_calls=2,
                    transport_batch_id=batch,
                    attempt=attempt,
                    combined_limit=4,
                )
        with pytest.raises(SemanticCallLimitError, match="combined"):
            repository.reserve_whole_scope_provider_submission(
                stage="hierarchy",
                manifest_id="new-explicit-manifest",
                maximum_manifest_calls=2,
                transport_batch_id="batch-fifth",
                attempt=1,
                combined_limit=4,
            )
        assert repository.whole_scope_submission_count() == 4


def test_historical_boundary_records_remain_original_and_stale(tmp_path: Path) -> None:
    authority = _authority()
    window = BoundaryWindow(authority, 0, ("candidate-a",), ("unit-a", "unit-b"), 2)
    payload: dict[str, object] = {"window_id": window.window_id, "units": []}
    job = PreparedNarrativeJob(
        ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW,
        authority,
        window,
        window.window_id,
        canonical_hash(payload),
        SEMANTIC_BOUNDARY_PROMPT_VERSION,
        SEMANTIC_BOUNDARY_RESPONSE_SCHEMA,
        payload,  # type: ignore[arg-type]
        ("evidence-a",),
        source_hash="source-hash",
        correction_id="m15.1-historical",
        privacy_scope="story_evidence_only",
    )
    with Project.create(tmp_path / "historical.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        repository.stage(job, _profile())
        historical = repository.read_historical_semantic_records()
        assert repository.list(ProviderJobKind.WHOLE_SCOPE_HIERARCHY) == ()

    assert historical == (
        {
            "original_kind": "semantic_boundary_window",
            "job_id": job.job_id,
            "status": "pending",
            "production_identity_status": "historical_stale",
        },
    )

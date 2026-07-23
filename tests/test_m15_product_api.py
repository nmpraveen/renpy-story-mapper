from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.assembly import assemble_semantic_outline
from renpy_story_mapper.narrative_map.contracts import BoundaryProviderIdentity, canonical_hash
from renpy_story_mapper.narrative_map.persistence import NarrativeMapRepository
from renpy_story_mapper.narrative_map.provider import (
    NarrativeMapProviderError,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
    WholeScopeProviderSubject,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    SemanticBoundaryDecision,
    SemanticBoundaryKind,
    WholeScopeSemanticStage,
)
from renpy_story_mapper.narrative_map.semantic_lifecycle import WholeScopeStagePreparation
from renpy_story_mapper.narrative_map.service import NarrativeMapService
from renpy_story_mapper.narrative_map.validation import ValidationFinding
from renpy_story_mapper.project import Project, refresh_ingested_project
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.contracts import (
    M15_API_ROUTES,
    M15_WHOLE_SCOPE_SEMANTIC_ROUTES,
    JsonValue,
)
from renpy_story_mapper.web.launcher import build_project_api
from renpy_story_mapper.web.m15_semantic_api import (
    M15_WHOLE_SCOPE_CORRECTION_ID,
    M15WholeScopeProductController,
    _validate_hierarchy_for_current_authority,
    _whole_scope_hierarchy_input,
    load_m15_semantic_inputs,
    m15_provider_profile,
)
from renpy_story_mapper.web.state import UserStateStore
from test_m15_track_c import _Dialogs, _project


class _ProductFakeProvider:
    def __init__(self, requests: list[NarrativeMapProviderRequest]) -> None:
        self.requests = requests
        self.cancel_count = 0

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        job = request.job
        if job.kind is ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW:
            assert isinstance(job.subject, BoundaryWindow)
            payload: dict[str, object] = {
                "window_id": job.subject_id,
                "decisions": [
                    {
                        "candidate_id": candidate_id,
                        "decision": "new_beat_same_cluster",
                        "reason": "The immediate story objective changes.",
                        "confidence": 0.9,
                        "warnings": [],
                    }
                    for candidate_id in job.subject.owned_candidate_ids
                ],
            }
        else:
            payload = {
                "subject_kind": job.payload["subject_kind"],
                "subject_id": job.subject_id,
                "membership_hash": job.membership_hash,
                "title": "Supported story section",
                "summary": "This section presents the supported story progression.",
                "characters": [],
                "claims": [
                    {
                        "claim_class": "factual",
                        "text": "The section contains supported story action.",
                        "evidence_ids": [job.known_evidence_ids[0]],
                    }
                ],
                "warnings": [],
            }
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


def test_shipped_launcher_wires_durable_stage_h_without_constructing_provider(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    provider_constructions = 0

    def forbidden_provider() -> _ProductFakeProvider:
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("provider construction is forbidden during product preparation")

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_provider)
    api._retain_project_path(project_path, source)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        status = api.dispatch("POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["status"], {})
    finally:
        api.close()

    assert bootstrap["routes"]["m15_whole_scope_semantic"] == (M15_WHOLE_SCOPE_SEMANTIC_ROUTES)
    assert prepared["state"] == "awaiting_hierarchy_consent"
    assert prepared["manifest_id"]
    assert status["state"] == "awaiting_hierarchy_consent"
    assert provider_constructions == 0


class _WholeScopeProductFakeProvider(_ProductFakeProvider):
    def __init__(
        self,
        requests: list[NarrativeMapProviderRequest],
        hierarchy_payload: dict[str, object],
    ) -> None:
        super().__init__(requests)
        self.hierarchy_payload = hierarchy_payload

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        subject = request.job.subject
        assert isinstance(subject, WholeScopeProviderSubject)
        if subject.stage is WholeScopeSemanticStage.HIERARCHY:
            payload: dict[str, object] = dict(self.hierarchy_payload)
            payload["scope_id"] = subject.scope_id
        else:
            payload = {
                "scope_id": subject.scope_id,
                "hierarchy_hash": subject.hierarchy_hash,
                "records": [
                    {
                        "subject_kind": item.subject_kind,
                        "subject_id": item.subject_id,
                        "membership_hash": item.membership_hash,
                        "presentation_role": "story",
                        "title": f"Supported Story Action {index + 1}",
                        "summary": (
                            f"Supported story action {index + 1} begins and reaches its result."
                        ),
                        "characters": list(item.known_characters),
                        "claims": [
                            {
                                "claim_class": "factual",
                                "text": (
                                    f"Supported story action {index + 1} occurs in this scope."
                                ),
                                "evidence_ids": [item.evidence_ids[0]],
                            }
                        ],
                        "warnings": [],
                    }
                    for index, item in enumerate(subject.editorial_subjects)
                ],
                "warnings": [],
            }
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


class _CancellableWholeScopeProductProvider(_WholeScopeProductFakeProvider):
    def __init__(
        self,
        requests: list[NarrativeMapProviderRequest],
        hierarchy_payload: dict[str, object],
        entered: threading.Event,
    ) -> None:
        super().__init__(requests, hierarchy_payload)
        self.entered = entered

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        self.requests.append(request)
        self.entered.set()
        deadline = time.monotonic() + 5
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert cancelled()
        raise NarrativeMapProviderError("cancelled", "The fake request was cancelled.")


class _SequencedWholeScopeProductProvider(_WholeScopeProductFakeProvider):
    def __init__(
        self,
        requests: list[NarrativeMapProviderRequest],
        outcomes: list[dict[str, object] | NarrativeMapProviderError],
    ) -> None:
        super().__init__(requests, {})
        self.outcomes = outcomes

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, NarrativeMapProviderError):
            self.requests.append(request)
            raise outcome
        self.hierarchy_payload = outcome
        return super().submit(request, cancelled)


def _whole_scope_hierarchy_payload(project_path: Path) -> dict[str, object]:
    with Project.open(project_path) as project:
        inputs = load_m15_semantic_inputs(project)
    decisions = tuple(
        SemanticBoundaryDecision(
            item.candidate_id,
            SemanticBoundaryKind.NEW_BEAT_SAME_CLUSTER,
            "The deterministic synthetic action changes.",
            0.9,
        )
        for item in inputs.candidates
    )
    outline = assemble_semantic_outline(inputs.units, inputs.candidates, decisions)
    beat_keys = {
        item.beat_id: f"whole-scope-beat-{index + 1}"
        for index, item in enumerate(outline.beats)
    }
    return {
        "scope_id": "replaced-by-provider",
        "beat_groups": [
            {
                "proposal_key": beat_keys[item.beat_id],
                "ordered_unit_ids": list(item.ordered_unit_ids),
                "confidence": 0.9,
                "reason": "This supported synthetic action is one bounded beat.",
                "warnings": [],
            }
            for item in outline.beats
        ],
        "major_clusters": [
            {
                "proposal_key": f"whole-scope-cluster-{index + 1}",
                "ordered_beat_keys": [beat_keys[item] for item in cluster.ordered_beat_ids],
                "confidence": 0.9,
                "reason": "These supported synthetic actions form one story section.",
                "warnings": [],
            }
            for index, cluster in enumerate(outline.clusters)
        ],
        "uncertain_unit_ids": [],
        "warnings": [],
    }


def _unrepresentable_whole_scope_hierarchy_payload(
    project_path: Path,
) -> dict[str, object]:
    payload = _whole_scope_hierarchy_payload(project_path)
    beat_groups = payload["beat_groups"]
    assert isinstance(beat_groups, list)
    payload["major_clusters"] = [
        {
            "proposal_key": "whole-scope-unrepresentable-cluster",
            "ordered_beat_keys": [item["proposal_key"] for item in beat_groups],
            "confidence": 0.9,
            "reason": "These supported synthetic actions form one story section.",
            "warnings": [],
        }
    ]
    return payload


def _persist_legacy_unfrozen_invalid_hierarchy(
    project_path: Path,
) -> tuple[WholeScopeStagePreparation, str, str, str]:
    invalid = _unrepresentable_whole_scope_hierarchy_payload(project_path)
    with Project.open(project_path) as project:
        inputs = load_m15_semantic_inputs(project)
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        profile = m15_provider_profile()
        scope_id, payload, _hard_locks = _whole_scope_hierarchy_input(inputs)
        preparation = service.prepare_whole_scope_hierarchy(
            inputs.units[0].authority,
            scope_id,
            tuple(item.unit_id for item in inputs.units),
            payload,
            known_evidence_ids=tuple(
                dict.fromkeys(
                    item.evidence_id
                    for unit in inputs.units
                    for item in inputs.evidence_by_unit[unit.unit_id]
                )
            ),
            known_characters=tuple(
                dict.fromkeys(
                    speaker for unit in inputs.units for speaker in unit.speaker_ids
                )
            ),
            profile=profile,
            run_id="legacy-live-invalid-stage-h",
            source_hash=inputs.source_hash,
            correction_id="m15.1-product-path-v1",
            valid_for=timedelta(hours=1),
            timeout_seconds=300.0,
        )
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        for attempt in (1, 2):
            repository.reserve_whole_scope_provider_submission(
                stage="hierarchy",
                manifest_id=consent.manifest_id,
                maximum_manifest_calls=2,
                transport_batch_id=preparation.job.job_id,
                attempt=attempt,
                combined_limit=4,
            )
        repository.settle_whole_scope_provider_submissions(
            transport_batch_id=preparation.job.job_id,
            attempts=(1, 2),
        )
        invalid["scope_id"] = scope_id
        provider_identity = BoundaryProviderIdentity(
            provider=profile.provider,
            adapter_version=f"{profile.adapter}:{profile.adapter_version}",
            requested_model=profile.requested_model,
            resolved_model=profile.requested_model,
            settings_hash=canonical_hash(profile.settings.to_dict()),
            prompt_version=preparation.job.prompt_version,
            response_schema=preparation.job.response_schema,
            input_hash=preparation.job.input_hash,
        )
        repository.record_validated(
            preparation.job,
            profile,
            attempt_count=2,
            provider_calls=2,
            result=invalid,
            provider_identity=provider_identity.to_dict(),
            usage=ProviderUsage(100, 20, 297_000),
            consent_manifest_id=consent.manifest_id,
        )
        raw = repository.read_whole_scope_build()
        assert raw is not None
        legacy_build = dict(raw)
        legacy_build["hierarchy_state"] = "validated"
        legacy_build["hierarchy_result"] = invalid
        legacy_build["failure_codes"] = []
        repository.write_whole_scope_build(legacy_build)
    return (
        preparation,
        consent.manifest_id,
        preparation.build_id,
        consent.job_identity_hash,
    )


@pytest.mark.parametrize(
    ("action", "body"),
    (
        ("prepare_hierarchy", {"action": "prepare_hierarchy"}),
        ("start_hierarchy", {"confirm_cloud": True}),
        ("prepare_editorial", {"action": "prepare_editorial"}),
        ("status", {}),
        ("resume", {}),
        ("retry", {}),
    ),
)
def test_legacy_quarantine_repeated_cas_loss_fails_closed_on_every_product_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    body: dict[str, JsonValue],
) -> None:
    source, project_path = _project(tmp_path)
    old_preparation, old_manifest_id, _old_build_id, _old_job_identity = (
        _persist_legacy_unfrozen_invalid_hierarchy(project_path)
    )
    if action == "start_hierarchy":
        body = {
            "action": "start_hierarchy",
            "manifest_id": old_manifest_id,
            "confirm_cloud": True,
        }
    original = NarrativeMapRepository.quarantine_invalid_whole_scope_hierarchy
    losses = 0

    def force_repeated_loss(
        repository: NarrativeMapRepository,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
        **kwargs: object,
    ) -> bool:
        nonlocal losses
        losses += 1
        raw = repository.read_whole_scope_build()
        assert raw is not None
        drifted = dict(raw)
        drifted["failure_codes"] = [f"concurrent_update_{losses}"]
        repository.write_whole_scope_build(drifted)
        return original(repository, job, profile, **kwargs)

    monkeypatch.setattr(
        NarrativeMapRepository,
        "quarantine_invalid_whole_scope_hierarchy",
        force_repeated_loss,
    )
    constructions = 0

    def forbidden_factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        raise AssertionError("lost legacy quarantine CAS must remain zero-submit")

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_factory)
    api._retain_project_path(project_path, source)
    try:
        result = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES[action],
            body,
        )
    finally:
        api.close()

    assert result["state"] == "stale"
    assert result["stage"] == "hierarchy"
    assert result["build_id"] is None
    assert result["manifest_id"] is None
    assert result["requires_fresh_preparation"] is True
    assert result["accounting"]["provider_calls"] == 0
    assert constructions == 0
    assert losses == 2
    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        raw = repository.read_whole_scope_build()
        record = repository.get(
            ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
            old_preparation.job.job_id,
        )
        cache = repository.load_cache(old_preparation.job, m15_provider_profile())
        assert raw is not None
        assert raw["correction_id"] == "m15.1-product-path-v1"
        assert raw["hierarchy_state"] == "validated"
        assert raw["hierarchy_result"] is not None
        assert record is not None and record.status.value == "validated"
        assert record.consent_manifest_id == old_manifest_id
        assert cache is not None
        assert repository.whole_scope_reserved_attempts(
            old_preparation.job.job_id
        ) == (1, 2)


def test_legacy_quarantine_retries_one_safe_cas_loss_before_v2_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path = _project(tmp_path)
    old_preparation, old_manifest_id, _old_build_id, _old_job_identity = (
        _persist_legacy_unfrozen_invalid_hierarchy(project_path)
    )
    original = NarrativeMapRepository.quarantine_invalid_whole_scope_hierarchy
    calls = 0

    def lose_once(
        repository: NarrativeMapRepository,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
        **kwargs: object,
    ) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raw = repository.read_whole_scope_build()
            assert raw is not None
            drifted = dict(raw)
            drifted["failure_codes"] = ["concurrent_update_once"]
            repository.write_whole_scope_build(drifted)
        return original(repository, job, profile, **kwargs)

    monkeypatch.setattr(
        NarrativeMapRepository,
        "quarantine_invalid_whole_scope_hierarchy",
        lose_once,
    )
    constructions = 0

    def forbidden_factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        raise AssertionError("migration and preview must remain zero-submit")

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_factory)
    api._retain_project_path(project_path, source)
    try:
        result = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
    finally:
        api.close()

    assert result["state"] == "awaiting_hierarchy_consent"
    assert result["manifest_id"] != old_manifest_id
    assert result["manifest"]["limits"]["timeout_seconds"] == 900.0
    assert calls == 2
    assert constructions == 0
    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        old_record = repository.get(
            ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
            old_preparation.job.job_id,
        )
        raw = repository.read_whole_scope_build()
        assert old_record is not None and old_record.status.value == "failed"
        assert old_record.result is None
        assert old_record.consent_manifest_id is None
        assert raw is not None
        assert raw["correction_id"] == M15_WHOLE_SCOPE_CORRECTION_ID
        assert raw["hierarchy_state"] == "awaiting_consent"
        assert repository.whole_scope_reserved_attempts(
            old_preparation.job.job_id
        ) == (1, 2)


def test_legacy_quarantine_loses_to_concurrent_publication_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path = _project(tmp_path)
    old_preparation, old_manifest_id, _old_build_id, _old_job_identity = (
        _persist_legacy_unfrozen_invalid_hierarchy(project_path)
    )
    original = NarrativeMapRepository.quarantine_invalid_whole_scope_hierarchy
    publication = {
        "schema": "m15-whole-scope-concurrent-publication-test-v1",
        "publication_hash": "concurrent-publication",
    }
    calls = 0

    def publish_before_quarantine(
        repository: NarrativeMapRepository,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
        **kwargs: object,
    ) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raw = repository.read_whole_scope_build()
            assert raw is not None
            concurrent = dict(raw)
            concurrent["hierarchy_state"] = "frozen"
            concurrent["hierarchy_hash"] = "concurrent-hierarchy"
            concurrent["authoritative_hierarchy"] = {
                "schema": "m15-whole-scope-concurrent-hierarchy-test-v1"
            }
            repository.publish_whole_scope_current(
                build=concurrent,
                publication=publication,
                logical_records=(),
            )
        return original(repository, job, profile, **kwargs)

    monkeypatch.setattr(
        NarrativeMapRepository,
        "quarantine_invalid_whole_scope_hierarchy",
        publish_before_quarantine,
    )
    constructions = 0

    def forbidden_factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        raise AssertionError("concurrent publication must remain zero-submit")

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_factory)
    api._retain_project_path(project_path, source)
    try:
        result = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
    finally:
        api.close()

    assert result["state"] == "stale"
    assert result["build_id"] is None
    assert result["manifest_id"] is None
    assert result["accounting"]["provider_calls"] == 0
    assert calls == 1
    assert constructions == 0
    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        raw = repository.read_whole_scope_build()
        record = repository.get(
            ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
            old_preparation.job.job_id,
        )
        assert raw is not None
        assert raw["correction_id"] == "m15.1-product-path-v1"
        assert raw["hierarchy_state"] == "frozen"
        assert raw["hierarchy_hash"] == "concurrent-hierarchy"
        assert record is not None and record.status.value == "validated"
        assert record.consent_manifest_id == old_manifest_id
        assert repository.read_whole_scope_current() == publication
        assert repository.whole_scope_reserved_attempts(
            old_preparation.job.job_id
        ) == (1, 2)


def test_reopen_quarantines_legacy_unfrozen_invalid_hierarchy_and_rolls_identity(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    old_preparation, old_manifest_id, old_build_id, old_job_identity = (
        _persist_legacy_unfrozen_invalid_hierarchy(project_path)
    )
    constructions = 0

    def forbidden_factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        raise AssertionError("legacy migration and preview must remain zero-submit")

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_factory)
    api._retain_project_path(project_path, source)
    try:
        quarantined = api.dispatch(
            "POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["status"], {}
        )
        resumed = api.dispatch(
            "POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["resume"], {}
        )
        retried = api.dispatch(
            "POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["retry"], {}
        )
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            old_record = repository.get(
                ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
                old_preparation.job.job_id,
            )
            quarantined_build = repository.read_whole_scope_build()
            old_cache = repository.load_cache(
                old_preparation.job, m15_provider_profile()
            )
        preview = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        controller = api._m15_whole_scope_controller
        assert isinstance(controller, M15WholeScopeProductController)
        corrected = controller._preparations[WholeScopeSemanticStage.HIERARCHY]
    finally:
        api.close()

    assert quarantined["state"] == "failed"
    assert quarantined["progress"]["failure_codes"] == [
        "hierarchy_not_representable"
    ]
    assert resumed["state"] == retried["state"] == "stale"
    assert resumed["accounting"]["provider_calls"] == 0
    assert retried["accounting"]["provider_calls"] == 0
    assert old_record is not None and old_record.status.value == "failed"
    assert old_record.result is None
    assert old_record.consent_manifest_id is None
    assert old_record.attempt_count == old_record.provider_calls == 2
    assert old_cache is None
    assert quarantined_build is not None
    assert quarantined_build["hierarchy_state"] == "failed"
    assert quarantined_build["hierarchy_result"] is None
    assert quarantined_build["confirmed_hierarchy_manifest_id"] is None
    assert quarantined_build["hierarchy_hash"] is None
    assert quarantined_build["authoritative_hierarchy"] is None
    assert preview["manifest"]["limits"]["timeout_seconds"] == 900.0
    assert preview["manifest_id"] != old_manifest_id
    assert corrected.build_id != old_build_id
    assert corrected.job.job_id != old_preparation.job.job_id
    assert corrected.consent.job_identity_hash != old_job_identity
    assert constructions == 0
    requests: list[NarrativeMapProviderRequest] = []
    outcomes: list[dict[str, object] | NarrativeMapProviderError] = [
        _unrepresentable_whole_scope_hierarchy_payload(project_path),
        _whole_scope_hierarchy_payload(project_path),
    ]
    execution_api = build_project_api(
        _Dialogs(),
        m15_provider_factory=lambda: _SequencedWholeScopeProductProvider(
            requests, outcomes
        ),
    )
    execution_api._retain_project_path(project_path, source)
    try:
        corrected_result = execution_api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": corrected.consent.manifest_id,
                "confirm_cloud": True,
            },
        )
    finally:
        execution_api.close()
    assert corrected_result["state"] == "hierarchy_frozen"
    assert len(requests) == 2
    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        assert repository.whole_scope_reserved_attempts(
            old_preparation.job.job_id
        ) == (1, 2)
        assert repository.whole_scope_reserved_attempts(corrected.job.job_id) == (1, 2)
        status = NarrativeMapService(repository).whole_scope_semantic_status()
        assert status is not None
        assert status.accounting.combined_submission_count == 4


def test_direct_service_replay_quarantines_legacy_invalid_validated_result(
    tmp_path: Path,
) -> None:
    _source, project_path = _project(tmp_path)
    preparation, _manifest_id, _build_id, _job_identity = (
        _persist_legacy_unfrozen_invalid_hierarchy(project_path)
    )
    with Project.open(project_path) as project:
        inputs = load_m15_semantic_inputs(project)
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        _scope_id, _payload, hard_locks = _whole_scope_hierarchy_input(inputs)

        def exact_validator(
            job: PreparedNarrativeJob,
            result: Mapping[str, object],
        ) -> tuple[ValidationFinding, ...]:
            _validated, findings = _validate_hierarchy_for_current_authority(
                inputs,
                job,
                result,
                scope_id=preparation.scope_id,
                authority=preparation.authority,
                hard_locks=hard_locks,
            )
            return findings

        report = service.start_whole_scope_hierarchy(
            preparation,
            authority_validator=exact_validator,
        )
        record = repository.get(preparation.job.kind, preparation.job.job_id)
        build = repository.read_whole_scope_build()

    assert report.provider_calls == 0
    assert report.failed_job_ids == (preparation.job.job_id,)
    assert record is not None and record.status.value == "failed"
    assert record.result is None
    assert record.consent_manifest_id is None
    assert record.attempt_count == record.provider_calls == 2
    assert build is not None and build["hierarchy_state"] == "failed"
    assert build["failure_codes"] == ["hierarchy_not_representable"]
    assert build["confirmed_hierarchy_manifest_id"] is None


def test_stage_h_full_authority_validation_repairs_before_durable_acceptance(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    outcomes: list[dict[str, object] | NarrativeMapProviderError] = [
        _unrepresentable_whole_scope_hierarchy_payload(project_path),
        _whole_scope_hierarchy_payload(project_path),
    ]

    api = build_project_api(
        _Dialogs(),
        m15_provider_factory=lambda: _SequencedWholeScopeProductProvider(
            requests, outcomes
        ),
    )
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        completed = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
    finally:
        api.close()

    assert completed["state"] == "hierarchy_frozen"
    assert completed["hierarchy_hash"]
    assert completed["accounting"]["provider_calls"] == 2
    assert len(requests) == 2
    assert requests[1].repair_codes == ("hierarchy_not_representable",)


def test_direct_service_exact_authority_validator_rejects_unrepresentable_result(
    tmp_path: Path,
) -> None:
    _source, project_path = _project(tmp_path)
    invalid = _unrepresentable_whole_scope_hierarchy_payload(project_path)
    with Project.open(project_path) as project:
        inputs = load_m15_semantic_inputs(project)
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        profile = m15_provider_profile()
        scope_id, payload, hard_locks = _whole_scope_hierarchy_input(inputs)
        preparation = service.prepare_whole_scope_hierarchy(
            inputs.units[0].authority,
            scope_id,
            tuple(item.unit_id for item in inputs.units),
            payload,
            known_evidence_ids=tuple(
                dict.fromkeys(
                    item.evidence_id
                    for unit in inputs.units
                    for item in inputs.evidence_by_unit[unit.unit_id]
                )
            ),
            known_characters=tuple(
                dict.fromkeys(
                    speaker for unit in inputs.units for speaker in unit.speaker_ids
                )
            ),
            profile=profile,
            run_id="direct-exact-authority-validation",
            source_hash=inputs.source_hash,
            correction_id=M15_WHOLE_SCOPE_CORRECTION_ID,
            timeout_seconds=900.0,
        )
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)

        def exact_validator(
            job: PreparedNarrativeJob,
            result: Mapping[str, object],
        ) -> tuple[ValidationFinding, ...]:
            _validated, findings = _validate_hierarchy_for_current_authority(
                inputs,
                job,
                result,
                scope_id=scope_id,
                authority=inputs.units[0].authority,
                hard_locks=hard_locks,
            )
            return findings

        provider = _SequencedWholeScopeProductProvider(
            [], [deepcopy(invalid), deepcopy(invalid)]
        )
        report = service.start_whole_scope_hierarchy(
            preparation,
            provider=provider,
            consent=consent,
            authority_validator=exact_validator,
        )
        record = repository.get(preparation.job.kind, preparation.job.job_id)

    assert report.failed_job_ids == (preparation.job.job_id,)
    assert report.validated_job_ids == ()
    assert report.provider_calls == 2
    assert record is not None and record.status.value == "failed"
    assert record.error_code == "hierarchy_not_representable"
    assert record.result is None


def test_stage_h_exhausted_authority_failure_is_sanitized_and_not_retryable(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    invalid = _unrepresentable_whole_scope_hierarchy_payload(project_path)
    outcomes: list[dict[str, object] | NarrativeMapProviderError] = [
        deepcopy(invalid),
        deepcopy(invalid),
    ]
    constructions = 0

    def factory() -> _SequencedWholeScopeProductProvider:
        nonlocal constructions
        constructions += 1
        return _SequencedWholeScopeProductProvider(requests, outcomes)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        failed = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        with pytest.raises(ValueError, match="frozen Stage H"):
            api.dispatch(
                "POST",
                M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
                {"action": "prepare_editorial"},
            )
        retried = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["retry"],
            {},
        )
    finally:
        api.close()

    assert failed["state"] == "failed"
    assert failed["hierarchy_hash"] is None
    assert failed["progress"]["failure_codes"] == ["hierarchy_not_representable"]
    assert failed["accounting"]["provider_calls"] == 2
    assert retried["state"] == "stale"
    assert retried["requires_fresh_preparation"] is True
    assert retried["manifest_id"] is None
    assert retried["accounting"]["provider_calls"] == 0
    assert constructions == 1
    assert len(requests) == 2
    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        records = repository.list(ProviderJobKind.WHOLE_SCOPE_HIERARCHY)
        durable_build = repository.read_whole_scope_build()
        logical_records = repository.read_whole_scope_logical_records()
    assert len(records) == 1
    assert records[0].status.value == "failed"
    assert records[0].result is None
    assert durable_build is not None
    assert durable_build["hierarchy_result"] is None
    assert durable_build["authoritative_hierarchy"] is None
    assert logical_records == ()


def test_stage_h_timeout_recovery_uses_second_attempt_and_cumulative_accounting(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    outcomes: list[dict[str, object] | NarrativeMapProviderError] = [
        NarrativeMapProviderError(
            "timeout",
            "The synthetic request reached its finite deadline.",
            transient=True,
            provider_call_reserved=True,
        ),
        _whole_scope_hierarchy_payload(project_path),
    ]
    constructions = 0

    def factory() -> _SequencedWholeScopeProductProvider:
        nonlocal constructions
        constructions += 1
        return _SequencedWholeScopeProductProvider(requests, outcomes)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        timed_out = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        recovered = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["retry"],
            {},
        )
    finally:
        api.close()

    assert timed_out["state"] == "failed"
    assert timed_out["progress"]["failure_codes"] == ["timeout"]
    assert timed_out["accounting"]["provider_calls"] == 1
    assert recovered["state"] == "hierarchy_frozen"
    assert recovered["accounting"]["provider_calls"] == 2
    assert recovered["accounting"]["reserved_provider_calls"] == 2
    assert constructions == 2
    assert len(requests) == 2
    assert {request.timeout_seconds for request in requests} == {900.0}


def test_stage_h_preview_exposes_timeout_and_binds_it_to_manifest_identity(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    api = build_project_api(
        _Dialogs(),
        m15_provider_factory=lambda: (_ for _ in ()).throw(
            AssertionError("preparation must not construct a provider")
        ),
    )
    api._retain_project_path(project_path, source)
    try:
        preview = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        controller = api._m15_whole_scope_controller
        assert isinstance(controller, M15WholeScopeProductController)
        preparation = controller._preparations[WholeScopeSemanticStage.HIERARCHY]
        prior_timeout_manifest = replace(preparation.consent, timeout_seconds=300.0)
    finally:
        api.close()

    assert preview["manifest"]["limits"]["timeout_seconds"] == 900.0
    assert preparation.consent.manifest_id != prior_timeout_manifest.manifest_id


def test_shipped_controller_completes_fake_stage_h_and_e_through_durable_lifecycle(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    constructions = 0
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(requests, hierarchy_payload)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        hierarchy = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        hierarchy_status = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        editorial_status = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
    finally:
        api.close()

    assert hierarchy_status["state"] == "hierarchy_frozen"
    assert editorial_status["state"] == "complete"
    assert editorial_status["publication_hash"]
    assert constructions == 2
    assert len(requests) == 2

    replay_constructions = 0

    def forbidden_replay_provider() -> _WholeScopeProductFakeProvider:
        nonlocal replay_constructions
        replay_constructions += 1
        raise AssertionError("unchanged whole-scope replay must not construct a provider")

    reopened = build_project_api(_Dialogs(), m15_provider_factory=forbidden_replay_provider)
    reopened._retain_project_path(project_path, source)
    try:
        replay_hierarchy = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        replay_hierarchy_status = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": replay_hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        replay_editorial = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        replay_editorial_status = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": replay_editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
    finally:
        reopened.close()

    assert replay_hierarchy_status["state"] == "complete"
    assert replay_editorial_status["state"] == "complete"
    assert replay_editorial_status["publication_hash"] == editorial_status["publication_hash"]
    assert replay_constructions == 0


def test_whole_scope_stage_h_authority_drift_is_stale_before_any_provider_effect(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    constructions = 0
    requests: list[NarrativeMapProviderRequest] = []

    def forbidden_factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(
            requests, _whole_scope_hierarchy_payload(project_path)
        )

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_factory)
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        with Project.open(project_path) as project:
            build = NarrativeMapRepository(project).read_whole_scope_build()
            assert build is not None
            transport_batch_id = str(build["hierarchy_transport_batch_id"])
        _change_current_m10_m11_authority(source, project_path)
        stale = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        with Project.open(project_path) as project:
            reservations = NarrativeMapRepository(project).whole_scope_reserved_attempts(
                transport_batch_id
            )
    finally:
        api.close()

    assert stale["state"] == "stale"
    assert stale["failure_codes"] == ["m15_preparation_stale"]
    assert stale["requires_fresh_preparation"] is True
    assert stale["accounting"] == {
        "provider_calls": 0,
        "reserved_provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "elapsed_ms": 0,
        "cache_hits": 0,
    }
    assert constructions == 0
    assert requests == []
    assert reservations == ()


def test_whole_scope_stage_e_subject_drift_is_stale_before_any_new_provider_effect(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    constructions = 0
    requests: list[NarrativeMapProviderRequest] = []
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(requests, hierarchy_payload)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        hierarchy = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            build = repository.read_whole_scope_build()
            assert build is not None
            transport_batch_id = str(build["editorial_transport_batch_id"])
            drifted = deepcopy(dict(build))
            subjects = drifted["frozen_editorial_subjects"]
            assert isinstance(subjects, list) and isinstance(subjects[0], dict)
            subjects[0]["membership_hash"] = "drifted-frozen-membership"
            repository.write_whole_scope_build(drifted)
        stale = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
        with Project.open(project_path) as project:
            reservations = NarrativeMapRepository(project).whole_scope_reserved_attempts(
                transport_batch_id
            )
    finally:
        api.close()

    assert stale["state"] == "stale"
    assert stale["failure_codes"] == ["m15_preparation_stale"]
    assert stale["requires_fresh_preparation"] is True
    assert stale["accounting"]["provider_calls"] == 0
    assert stale["accounting"]["reserved_provider_calls"] == 0
    assert constructions == 1
    assert len(requests) == 1
    assert reservations == ()


@pytest.mark.parametrize("action", ["resume", "retry"])
def test_whole_scope_stale_hierarchy_cannot_be_reprepared_by_recovery(
    tmp_path: Path,
    action: str,
) -> None:
    source, project_path = _project(tmp_path)
    constructions = 0
    requests: list[NarrativeMapProviderRequest] = []

    def forbidden_factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(
            requests, _whole_scope_hierarchy_payload(project_path)
        )

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_factory)
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        with Project.open(project_path) as project:
            build = NarrativeMapRepository(project).read_whole_scope_build()
            assert build is not None
            transport_batch_id = str(build["hierarchy_transport_batch_id"])
        _change_current_m10_m11_authority(source, project_path)
        stale_start = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        recovered = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES[action],
            {},
        )
        status = api.dispatch("POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["status"], {})
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            durable = repository.read_whole_scope_build()
            reservations = repository.whole_scope_reserved_attempts(transport_batch_id)
    finally:
        api.close()

    assert stale_start["state"] == "stale"
    assert recovered["state"] == "stale"
    assert recovered["build_id"] is None
    assert recovered["manifest_id"] is None
    assert recovered["requires_fresh_preparation"] is True
    assert recovered["accounting"] == {
        "provider_calls": 0,
        "reserved_provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "elapsed_ms": 0,
        "cache_hits": 0,
    }
    assert status["state"] == "failed"
    assert constructions == 0
    assert requests == []
    assert reservations == ()
    assert durable is not None
    assert durable["hierarchy_state"] == "failed"
    assert durable["confirmed_hierarchy_manifest_id"] is None
    assert durable["failure_codes"] == ["m15_preparation_stale"]


@pytest.mark.parametrize("action", ["resume", "retry"])
def test_whole_scope_stale_editorial_membership_cannot_be_reprepared_by_recovery(
    tmp_path: Path,
    action: str,
) -> None:
    source, project_path = _project(tmp_path)
    constructions = 0
    requests: list[NarrativeMapProviderRequest] = []
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(requests, hierarchy_payload)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        hierarchy = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            build = repository.read_whole_scope_build()
            assert build is not None
            transport_batch_id = str(build["editorial_transport_batch_id"])
            drifted = deepcopy(dict(build))
            subjects = drifted["frozen_editorial_subjects"]
            assert isinstance(subjects, list) and isinstance(subjects[0], dict)
            subjects[0]["membership_hash"] = "synthetic-membership-mismatch"
            repository.write_whole_scope_build(drifted)
        stale_start = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
        recovered = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES[action],
            {},
        )
        status = api.dispatch("POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["status"], {})
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            durable = repository.read_whole_scope_build()
            reservations = repository.whole_scope_reserved_attempts(transport_batch_id)
    finally:
        api.close()

    assert stale_start["state"] == "stale"
    assert recovered["state"] == "stale"
    assert recovered["build_id"] is None
    assert recovered["manifest_id"] is None
    assert recovered["requires_fresh_preparation"] is True
    assert recovered["accounting"] == {
        "provider_calls": 0,
        "reserved_provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "elapsed_ms": 0,
        "cache_hits": 0,
    }
    assert status["state"] == "failed"
    assert constructions == 1
    assert len(requests) == 1
    assert reservations == ()
    assert durable is not None
    assert durable["editorial_state"] == "failed"
    assert durable["confirmed_editorial_manifest_id"] is None
    assert durable["failure_codes"] == ["m15_preparation_stale"]


def test_whole_scope_stage_e_rejects_only_authoritative_hierarchy_payload_drift(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    constructions = 0
    requests: list[NarrativeMapProviderRequest] = []
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(requests, hierarchy_payload)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        hierarchy = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            build = repository.read_whole_scope_build()
            assert build is not None
            transport_batch_id = str(build["editorial_transport_batch_id"])
            drifted = deepcopy(dict(build))
            hierarchy_authority = drifted["authoritative_hierarchy"]
            assert isinstance(hierarchy_authority, dict)
            hierarchy_authority["schema"] = "synthetic-hierarchy-mismatch"
            repository.write_whole_scope_build(drifted)
        stale = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            reservations = repository.whole_scope_reserved_attempts(transport_batch_id)
            publication = repository.read_whole_scope_current()
    finally:
        api.close()

    assert stale["state"] == "stale"
    assert stale["requires_fresh_preparation"] is True
    assert stale["accounting"]["reserved_provider_calls"] == 0
    assert constructions == 1
    assert len(requests) == 1
    assert reservations == ()
    assert publication is None


def test_whole_scope_lazy_provider_preserves_concurrent_cancellation(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    entered = threading.Event()
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _CancellableWholeScopeProductProvider:
        return _CancellableWholeScopeProductProvider(requests, hierarchy_payload, entered)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    result: dict[str, object] = {}
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )

        def start() -> None:
            result.update(
                api.dispatch(
                    "POST",
                    M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
                    {
                        "action": "start_hierarchy",
                        "manifest_id": prepared["manifest_id"],
                        "confirm_cloud": True,
                    },
                )
            )

        worker = threading.Thread(target=start)
        worker.start()
        assert entered.wait(timeout=5)
        cancelled = api.dispatch(
            "POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["cancel"], {}
        )
        worker.join(timeout=5)
        assert not worker.is_alive()
    finally:
        api.close()

    assert cancelled["state"] == "cancelled"
    assert result["state"] == "cancelled"
    assert len(requests) == 1


def test_reopened_whole_scope_resume_reconstructs_only_confirmed_cancelled_manifest(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    entered = threading.Event()
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def cancellable_factory() -> _CancellableWholeScopeProductProvider:
        return _CancellableWholeScopeProductProvider(requests, hierarchy_payload, entered)

    api = build_project_api(_Dialogs(), m15_provider_factory=cancellable_factory)
    api._retain_project_path(project_path, source)
    worker_result: dict[str, object] = {}
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )

        def start() -> None:
            worker_result.update(
                api.dispatch(
                    "POST",
                    M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
                    {
                        "action": "start_hierarchy",
                        "manifest_id": prepared["manifest_id"],
                        "confirm_cloud": True,
                    },
                )
            )

        worker = threading.Thread(target=start)
        worker.start()
        assert entered.wait(timeout=5)
        api.dispatch("POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["cancel"], {})
        worker.join(timeout=5)
        assert not worker.is_alive()
    finally:
        api.close()

    assert worker_result["state"] == "cancelled"
    with Project.open(project_path) as project:
        before = NarrativeMapRepository(project).read_whole_scope_build()
    assert before is not None
    original_manifest_id = before["hierarchy_manifest_id"]
    original_transport_id = before["hierarchy_transport_batch_id"]

    reopened = build_project_api(
        _Dialogs(),
        m15_provider_factory=lambda: _WholeScopeProductFakeProvider(
            requests, hierarchy_payload
        ),
    )
    reopened._retain_project_path(project_path, source)
    try:
        resumed = reopened.dispatch(
            "POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["resume"], {}
        )
    finally:
        reopened.close()

    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        after = repository.read_whole_scope_build()
        reservations = repository.whole_scope_reserved_attempts(str(original_transport_id))
    assert resumed["state"] == "hierarchy_frozen"
    assert len(requests) == 2
    assert after is not None
    assert after["hierarchy_manifest_id"] == original_manifest_id
    assert after["hierarchy_transport_batch_id"] == original_transport_id
    assert reservations == (1, 2)


def test_whole_scope_routes_validate_and_delegate_to_the_track_b_controller(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, JsonValue]]] = []

    def controller(
        action: str,
        body: dict[str, JsonValue],
    ) -> dict[str, object]:
        calls.append((action, dict(body)))
        return {
            "state": f"{action}_handled",
            "manifest_id": "manifest-synthetic",
            "requires_confirmation": action.startswith("prepare_"),
        }

    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m15_whole_scope_controller=controller,
    )
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert isinstance(bootstrap, dict)
        routes = bootstrap["routes"]
        assert isinstance(routes, dict)
        assert routes["m15_whole_scope_semantic"] == M15_WHOLE_SCOPE_SEMANTIC_ROUTES
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        assert isinstance(prepared, dict) and prepared["state"] == "prepare_hierarchy_handled"
        started = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": "manifest-synthetic",
                "confirm_cloud": True,
            },
        )
        assert isinstance(started, dict) and started["state"] == "start_hierarchy_handled"
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        assert isinstance(editorial, dict) and editorial["state"] == "prepare_editorial_handled"
        editorial_started = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": "manifest-editorial-synthetic",
                "confirm_cloud": True,
            },
        )
        assert (
            isinstance(editorial_started, dict)
            and editorial_started["state"] == "start_editorial_handled"
        )
        for action in ("status", "cancel", "resume", "retry"):
            response = api.dispatch(
                "POST",
                M15_WHOLE_SCOPE_SEMANTIC_ROUTES[action],
                {},
            )
            assert isinstance(response, dict) and response["state"] == f"{action}_handled"
        assert [item[0] for item in calls] == [
            "prepare_hierarchy",
            "start_hierarchy",
            "prepare_editorial",
            "start_editorial",
            "status",
            "cancel",
            "resume",
            "retry",
        ]
        assert all(body == {} for _action, body in calls[-4:])
        with pytest.raises(ValueError, match="exact confirmation"):
            api.dispatch(
                "POST",
                M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
                {
                    "action": "start_editorial",
                    "manifest_id": "manifest-editorial-synthetic",
                    "confirm_cloud": False,
                },
            )
    finally:
        api.close()


def test_whole_scope_lifecycle_routes_fall_back_to_legacy_when_controller_is_absent(
    tmp_path: Path,
) -> None:
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        with pytest.raises(ApiProblem) as unavailable:
            api.dispatch(
                "POST",
                M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
                {"action": "prepare_hierarchy"},
            )
        assert unavailable.value.status == 409
        assert unavailable.value.code == "m15_whole_scope_not_integrated"

        for action in ("status", "cancel", "resume", "retry"):
            with pytest.raises(ApiProblem) as legacy_response:
                api.dispatch(
                    "POST",
                    M15_WHOLE_SCOPE_SEMANTIC_ROUTES[action],
                    {},
                )
            assert legacy_response.value.status == 409
            assert legacy_response.value.code == "no_project"
    finally:
        api.close()


def test_explicit_legacy_prepare_keeps_shared_lifecycle_on_legacy_controller(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    whole_scope_calls: list[str] = []

    def controller(action: str, _body: dict[str, JsonValue]) -> dict[str, object]:
        whole_scope_calls.append(action)
        return {"state": f"{action}_handled"}

    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m15_whole_scope_controller=controller,
    )
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        status = api.dispatch("POST", M15_API_ROUTES["status"], {})
        assert isinstance(prepared, dict)
        assert isinstance(status, dict)
        assert whole_scope_calls == []
    finally:
        api.close()


class _FailingProductProvider(_ProductFakeProvider):
    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        raise NarrativeMapProviderError(
            "provider_unavailable",
            "The fake provider is unavailable for this attempt.",
        )


class _CancellableProductProvider(_ProductFakeProvider):
    def __init__(
        self,
        requests: list[NarrativeMapProviderRequest],
        entered: threading.Event,
    ) -> None:
        super().__init__(requests)
        self.entered = entered

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        self.requests.append(request)
        self.entered.set()
        deadline = time.monotonic() + 5
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert cancelled()
        raise NarrativeMapProviderError("cancelled", "The fake request was cancelled.")


def _api(
    tmp_path: Path,
    source: Path,
    project_path: Path,
    provider_factory: Callable[[], _ProductFakeProvider],
) -> ProjectApi:
    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m15_provider_factory=provider_factory,
    )
    api._retain_project_path(project_path, source)
    return api


def _wait(api: ProjectApi) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        progress = api.dispatch("GET", "/api/v1/analysis/progress", {})
        assert isinstance(progress, dict)
        if progress.get("state") not in {"pending", "running"}:
            return progress
        time.sleep(0.01)
    raise AssertionError("M15 web operation did not finish")


def _change_current_m10_m11_authority(source: Path, project_path: Path) -> None:
    story = source / "story.rpy"
    story.write_bytes(
        story.read_bytes() + b'\nlabel post_preview_change:\n    "Changed authority."\n    return\n'
    )
    refresh_ingested_project(project_path, source)


def test_semantic_prepare_review_cancel_is_strict_and_zero_submit(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    factory_calls = 0

    def prohibited_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("prepare, review, and cancel must not construct a provider")

    api = _api(tmp_path, source, project_path, prohibited_factory)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert bootstrap["routes"]["m15"] == M15_API_ROUTES
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        assert prepared["state"] == "awaiting_boundary_consent"
        assert prepared["requires_confirmation"] is True
        assert prepared["manifest"]["provider"] == {
            "provider": "openai",
            "adapter": "codex_cli_structured",
            "adapter_version": "m13-codex-cli-adapter-v3",
            "requested_model": "gpt-5.6-sol",
            "resolved_model": "gpt-5.6-sol",
            "settings": {"model_reasoning_effort": "medium", "fast_mode": False},
        }
        issued = datetime.fromisoformat(prepared["manifest"]["issued_at"])
        expires = datetime.fromisoformat(prepared["manifest"]["expires_at"])
        assert expires - issued == timedelta(hours=1)
        serialized = repr(prepared)
        assert "payload" not in serialized
        assert "Opening line" not in serialized

        for body in (
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": False,
            },
            {
                "action": "start_boundaries",
                "manifest_id": "consent_wrong",
                "confirm_cloud": True,
            },
        ):
            with pytest.raises(ApiProblem) as raised:
                api.dispatch("POST", M15_API_ROUTES["start_boundaries"], body)
            assert raised.value.status == 409

        with pytest.raises(ValueError):
            api.dispatch(
                "POST",
                M15_API_ROUTES["prepare_boundaries"],
                {"action": "prepare_boundaries", "unexpected": True},
            )
        cancelled = api.dispatch("POST", M15_API_ROUTES["cancel"], {})
        assert cancelled["state"] == "cancelled"
        assert factory_calls == 0
    finally:
        api.close()


def test_authority_change_after_preview_rejects_start_before_provider_construction(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    factory_calls = 0

    def prohibited_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("stale consent must not construct a provider")

    api = _api(tmp_path, source, project_path, prohibited_factory)
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        _change_current_m10_m11_authority(source, project_path)
        with pytest.raises(ApiProblem) as raised:
            api.dispatch(
                "POST",
                M15_API_ROUTES["start_boundaries"],
                {
                    "action": "start_boundaries",
                    "manifest_id": prepared["manifest_id"],
                    "confirm_cloud": True,
                },
            )
        assert raised.value.status == 409
        assert raised.value.code == "m15_preparation_stale"
        assert factory_calls == 0
    finally:
        api.close()


def test_fake_provider_two_stage_publication_and_reopen_are_exact_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    factory_calls = 0

    def provider_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        return _ProductFakeProvider(requests)

    api = _api(tmp_path, source, project_path, provider_factory)

    def prohibited_m12(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("M15 product production must not invoke M12")

    monkeypatch.setattr(api, "_m12_solve", prohibited_m12)
    try:
        boundaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        boundary_manifest = boundaries["manifest_id"]
        assert boundaries["manifest"]["repair_policy_version"] is None
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": boundary_manifest,
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("membership_frozen")

        summaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_summaries"],
            {"action": "prepare_summaries"},
        )
        summary_manifest = summaries["manifest_id"]
        assert summary_manifest != boundary_manifest
        assert summaries["requires_confirmation"] is True
        assert summaries["manifest"]["repair_policy_version"] == ("m15-semantic-repair-guidance-v2")
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_summaries"],
            {
                "action": "start_summaries",
                "manifest_id": summary_manifest,
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        complete = api.dispatch("POST", M15_API_ROUTES["status"], {})
        assert complete["state"] == "complete"
        assert complete["manifest_id"] == summary_manifest
        assert complete["publication_hash"]
        publication_hash = complete["publication_hash"]
        assert factory_calls == 2
        assert requests
        assert all(
            request.profile.provider == "openai"
            and request.profile.adapter == "codex_cli_structured"
            and request.profile.adapter_version == "m13-codex-cli-adapter-v3"
            and request.profile.requested_model == "gpt-5.6-sol"
            and request.profile.settings.to_dict()
            == {"fast_mode": False, "reasoning_effort": "medium"}
            for request in requests
        )
    finally:
        api.close()

    replay_factory_calls = 0

    def replay_prohibited_factory() -> _ProductFakeProvider:
        nonlocal replay_factory_calls
        replay_factory_calls += 1
        raise AssertionError("an exact reopened replay must not construct a provider")

    reopened = _api(tmp_path, source, project_path, replay_prohibited_factory)
    monkeypatch.setattr(reopened, "_m12_solve", prohibited_m12)
    try:
        replay_boundaries = reopened.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        assert replay_boundaries["replay_only"] is True
        reopened.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": replay_boundaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(reopened)["state"] == "completed"
        replay_summaries = reopened.dispatch(
            "POST",
            M15_API_ROUTES["prepare_summaries"],
            {"action": "prepare_summaries"},
        )
        assert replay_summaries["replay_only"] is True
        reopened.dispatch(
            "POST",
            M15_API_ROUTES["start_summaries"],
            {
                "action": "start_summaries",
                "manifest_id": replay_summaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(reopened)["state"] == "completed"
        replayed = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert replayed["state"] == "complete"
        assert replayed["publication_hash"] == publication_hash
        assert replay_factory_calls == 0
    finally:
        reopened.close()


def test_reopened_retry_recovers_confirmed_boundary_stage_and_freezes_membership(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    failed_requests: list[NarrativeMapProviderRequest] = []
    api = _api(
        tmp_path,
        source,
        project_path,
        lambda: _FailingProductProvider(failed_requests),
    )
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == "failed"
        assert len(failed_requests) == 1
    finally:
        api.close()

    retry_requests: list[NarrativeMapProviderRequest] = []
    reopened = _api(
        tmp_path,
        source,
        project_path,
        lambda: _ProductFakeProvider(retry_requests),
    )
    try:
        reopened.dispatch("POST", M15_API_ROUTES["retry"], {})
        assert _wait(reopened)["state"] == "completed"
        status = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert status["state"] == "membership_frozen"
        assert len(retry_requests) == 1
    finally:
        reopened.close()


def test_authority_change_after_failure_rejects_retry_before_provider_construction(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    failed_requests: list[NarrativeMapProviderRequest] = []
    factory_calls = 0

    def provider_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls > 1:
            raise AssertionError("stale retry must not construct another provider")
        return _FailingProductProvider(failed_requests)

    api = _api(tmp_path, source, project_path, provider_factory)
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == "failed"
        _change_current_m10_m11_authority(source, project_path)
        with pytest.raises(ApiProblem) as raised:
            api.dispatch("POST", M15_API_ROUTES["retry"], {})
        assert raised.value.status == 409
        assert raised.value.code == "m15_fresh_preparation_required"
        assert factory_calls == 1
        assert len(failed_requests) == 1
    finally:
        api.close()


def test_reopened_resume_recovers_confirmed_cancelled_boundary_stage(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    cancelled_requests: list[NarrativeMapProviderRequest] = []
    entered = threading.Event()
    api = _api(
        tmp_path,
        source,
        project_path,
        lambda: _CancellableProductProvider(cancelled_requests, entered),
    )
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert entered.wait(timeout=5)
        api.dispatch("POST", M15_API_ROUTES["cancel"], {})
        assert _wait(api)["state"] == "cancelled"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("cancelled")
        assert len(cancelled_requests) == 1
    finally:
        api.close()

    resume_requests: list[NarrativeMapProviderRequest] = []
    reopened = _api(
        tmp_path,
        source,
        project_path,
        lambda: _ProductFakeProvider(resume_requests),
    )
    try:
        reopened.dispatch("POST", M15_API_ROUTES["resume"], {})
        assert _wait(reopened)["state"] == "completed"
        status = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert status["state"] == "membership_frozen"
        assert len(resume_requests) == 1
    finally:
        reopened.close()


def test_reopened_resume_recovers_confirmed_cancelled_summary_stage(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    boundary_requests: list[NarrativeMapProviderRequest] = []
    cancelled_requests: list[NarrativeMapProviderRequest] = []
    entered = threading.Event()
    factory_calls = 0

    def staged_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            return _ProductFakeProvider(boundary_requests)
        return _CancellableProductProvider(cancelled_requests, entered)

    api = _api(tmp_path, source, project_path, staged_factory)
    try:
        boundaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": boundaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("membership_frozen")
        summaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_summaries"],
            {"action": "prepare_summaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_summaries"],
            {
                "action": "start_summaries",
                "manifest_id": summaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert entered.wait(timeout=5)
        api.dispatch("POST", M15_API_ROUTES["cancel"], {})
        assert _wait(api)["state"] == "cancelled"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("cancelled")
        assert boundary_requests
        assert len(cancelled_requests) == 1
    finally:
        api.close()

    resume_requests: list[NarrativeMapProviderRequest] = []
    reopened = _api(
        tmp_path,
        source,
        project_path,
        lambda: _ProductFakeProvider(resume_requests),
    )
    try:
        reopened.dispatch("POST", M15_API_ROUTES["resume"], {})
        assert _wait(reopened)["state"] == "completed"
        status = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert status["state"] == "complete"
        assert status["publication_hash"]
        assert resume_requests
    finally:
        reopened.close()

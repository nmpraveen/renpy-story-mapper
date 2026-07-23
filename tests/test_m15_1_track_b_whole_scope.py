from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from typing import cast

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.assembly import assemble_semantic_outline
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    Provenance,
    SourceLocator,
    canonical_hash,
)
from renpy_story_mapper.narrative_map.corridors import build_all_eligible_gap_candidates
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
    FineNarrativeUnit,
    ProposedBeatGroup,
    ProposedMajorCluster,
    WholeScopeHierarchyProposal,
)
from renpy_story_mapper.narrative_map.semantic_hierarchy import (
    HierarchyHardLock,
    HierarchyHardLockKind,
    ValidatedWholeScopeHierarchy,
    compile_hierarchy_to_gap_decisions,
    validate_whole_scope_hierarchy,
)
from renpy_story_mapper.narrative_map.semantic_lifecycle import (
    WholeScopeSemanticLifecycle,
    WholeScopeSemanticStatus,
)
from renpy_story_mapper.narrative_map.semantic_projection import (
    SemanticEvidenceRecord,
    semantic_outline_hash,
)
from renpy_story_mapper.narrative_map.semantic_validation import (
    validate_whole_scope_hierarchy_response,
)
from renpy_story_mapper.narrative_map.service import NarrativeMapService
from renpy_story_mapper.narrative_map.validation import ValidationFinding
from renpy_story_mapper.narrative_map.workflow import NarrativeWorkflowReport
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
    units = _validated_hierarchy().units
    unit_ids = tuple(item.unit_id for item in units)
    return {
        "schema": M15_WHOLE_SCOPE_HIERARCHY_INPUT_SCHEMA,
        "scope_id": "scope-day-1",
        "authority": _authority().to_dict(),
        "ordered_unit_ids": list(unit_ids),
        "units": [
            {
                "unit_id": unit.unit_id,
                "sequence_id": unit.sequence_id,
                "ordinal": unit.ordinal,
                "story_atom_id": unit.story_atom_id,
                "evidence_ids": list(unit.evidence_ids),
                "speaker_ids": list(unit.speaker_ids),
                "lane_id": unit.lane_id,
                "call_occurrence_id": unit.call_occurrence_id,
                "call_occurrence_path": list(unit.call_occurrence_path),
                "call_site_path": list(unit.call_site_path),
                "loop_id": unit.loop_id,
                "parent_choice_id": unit.parent_choice_id,
                "parent_arm_id": unit.parent_arm_id,
                "entry_node_id": unit.entry_node_id,
                "exit_node_id": unit.exit_node_id,
            }
            for unit in units
        ],
        "evidence": [
            {
                "unit_id": unit.unit_id,
                "atom_id": unit.story_atom_id,
                "evidence_id": unit.evidence_ids[0],
                "ordinal": unit.ordinal,
                "kind": "dialogue",
                "text": "Ava arrives." if unit.ordinal == 0 else "Ava settles in.",
                "speaker": "Ava",
                "locator": unit.story_locator.to_dict(),
            }
            for unit in units
        ],
        "hard_locks": [],
    }


def _hierarchy_evidence_by_unit() -> dict[str, tuple[SemanticEvidenceRecord, ...]]:
    units = _validated_hierarchy().units
    return {
        unit.unit_id: (
            SemanticEvidenceRecord(
                unit.unit_id,
                unit.story_atom_id,
                unit.evidence_ids[0],
                unit.ordinal,
                "dialogue",
                "Ava arrives." if unit.ordinal == 0 else "Ava settles in.",
                "Ava",
                unit.story_locator,
            ),
        )
        for unit in units
    }


def _hierarchy_output() -> dict[str, object]:
    unit_ids = _validated_hierarchy().ordered_unit_ids
    return {
        "scope_id": "scope-day-1",
        "beat_groups": [
            {
                "proposal_key": "proposal-a",
                "ordered_unit_ids": [unit_ids[0]],
                "confidence": 0.9,
                "reason": "The first synthetic action stands alone.",
                "warnings": [],
            },
            {
                "proposal_key": "proposal-b",
                "ordered_unit_ids": [unit_ids[1]],
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
    hierarchy = _validated_hierarchy()
    outline = assemble_semantic_outline(
        hierarchy.units,
        hierarchy.candidates,
        compile_hierarchy_to_gap_decisions(hierarchy),
    )
    hierarchy_hash = semantic_outline_hash(outline)

    def membership_hash(subject_kind: str, subject_id: str, unit_ids: tuple[str, ...]) -> str:
        return canonical_hash(
            {
                "hierarchy_hash": hierarchy_hash,
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "ordered_unit_ids": list(unit_ids),
            }
        )

    return (
        WholeScopeEditorialSubject(
            "beat",
            outline.beats[0].beat_id,
            membership_hash("beat", outline.beats[0].beat_id, (hierarchy.units[0].unit_id,)),
            ("evidence-a",),
            ("Ava",),
        ),
        WholeScopeEditorialSubject(
            "beat",
            outline.beats[1].beat_id,
            membership_hash("beat", outline.beats[1].beat_id, (hierarchy.units[1].unit_id,)),
            ("evidence-b",),
            ("Ava",),
        ),
        WholeScopeEditorialSubject(
            "major_cluster",
            outline.clusters[0].cluster_id,
            membership_hash(
                "major_cluster", outline.clusters[0].cluster_id, hierarchy.ordered_unit_ids
            ),
            ("evidence-a", "evidence-b"),
            ("Ava",),
        ),
    )


def _unit(key: str, ordinal: int) -> FineNarrativeUnit:
    locator = SourceLocator("game/synthetic.rpy", ordinal + 1, ordinal + 1, "physical_source")
    return FineNarrativeUnit(
        authority=_authority(),
        sequence_id="scope-day-1",
        ordinal=ordinal,
        story_atom_id=f"atom-{key}",
        story_locator=locator,
        technical_context_atom_ids=(),
        node_ids=(f"node-{key}",),
        evidence_ids=(f"evidence-{key}",),
        speaker_ids=("Ava",),
        context_ids=(),
        lane_id="lane-main",
        call_occurrence_id=None,
        loop_id=None,
        parent_choice_id=None,
        parent_arm_id=None,
        entry_node_id=f"node-{key}",
        exit_node_id=f"node-{key}",
        incident_edge_ids=(),
        provenance=Provenance(
            atom_ids=(f"atom-{key}",),
            node_ids=(f"node-{key}",),
            evidence_ids=(f"evidence-{key}",),
            locators=(locator,),
        ),
    )


def _validated_hierarchy() -> ValidatedWholeScopeHierarchy:
    units = (_unit("a", 0), _unit("b", 1))
    proposal = WholeScopeHierarchyProposal(
        "scope-day-1",
        (
            ProposedBeatGroup(
                "proposal-a", (units[0].unit_id,), 0.9, "The first action stands alone."
            ),
            ProposedBeatGroup(
                "proposal-b", (units[1].unit_id,), 0.9, "The second action stands alone."
            ),
        ),
        (
            ProposedMajorCluster(
                "cluster-day",
                ("proposal-a", "proposal-b"),
                0.9,
                "Both actions form the same period.",
            ),
        ),
    )
    return validate_whole_scope_hierarchy(
        proposal,
        units,
        build_all_eligible_gap_candidates(units),
        scope_id="scope-day-1",
        authority=_authority(),
    )


def _frozen_evidence() -> tuple[dict[str, object], ...]:
    return (
        {"evidence_id": "evidence-a", "text": "Ava arrives."},
        {"evidence_id": "evidence-b", "text": "Ava settles in."},
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
    title = (
        "Ava Arrives"
        if subject.evidence_ids == ("evidence-a",)
        else "Ava Settles In"
        if subject.evidence_ids == ("evidence-b",)
        else "A New Day Begins"
    )
    return {
        "subject_kind": subject.subject_kind,
        "subject_id": subject.subject_id,
        "membership_hash": subject.membership_hash,
        "presentation_role": "story",
        "title": title,
        "summary": f"{title} as the supported synthetic story progresses.",
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


class _BlockingFakeProvider(_FakeProvider):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__([payload])
        self.entered = Event()
        self.release = Event()

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        self.entered.set()
        assert self.release.wait(5)
        return super().submit(request, cancelled)


class _PausingTransitionRepository(NarrativeMapRepository):
    def __init__(
        self,
        project: Project,
        predicate: Callable[[object], bool],
        entered: Event,
        release: Event,
    ) -> None:
        super().__init__(project)
        self._predicate = predicate
        self._entered = entered
        self._release = release

    def _pause(self, payload: object) -> None:
        if self._predicate(payload):
            self._entered.set()
            assert self._release.wait(5)

    def write_whole_scope_build(self, payload):  # type: ignore[no-untyped-def,override]
        self._pause(payload)
        return super().write_whole_scope_build(payload)

    def write_whole_scope_build_if_stage(  # type: ignore[no-untyped-def,override]
        self, payload, **kwargs
    ):
        self._pause(payload)
        return super().write_whole_scope_build_if_stage(payload, **kwargs)


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


def _prepare_hierarchy(
    service: NarrativeMapService, *, replay: bool = False, run_id: str = "stage-h-run"
):
    return service.prepare_whole_scope_hierarchy(
        _authority(),
        "scope-day-1",
        _validated_hierarchy().ordered_unit_ids,
        _hierarchy_input(),
        known_evidence_ids=("evidence-a", "evidence-b"),
        known_characters=("Ava",),
        profile=_profile(),
        run_id=run_id,
        source_hash="source-hash",
        correction_id="m15.1",
        replay_existing=replay,
    )


def _accept_synthetic_hierarchy_authority(
    _job: PreparedNarrativeJob,
    _result: object,
) -> tuple[ValidationFinding, ...]:
    return ()


@pytest.mark.parametrize("boundary", ("service", "lifecycle"))
def test_stage_h_missing_authority_validator_fails_before_reservation(
    tmp_path: Path,
    boundary: str,
) -> None:
    with Project.create(tmp_path / f"missing-hierarchy-validator-{boundary}.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        provider = _FakeProvider([_hierarchy_output()])
        with pytest.raises(ValueError, match="authority validator"):
            if boundary == "service":
                service.start_whole_scope_hierarchy(
                    preparation,
                    provider=provider,
                    consent=consent,
                )
            else:
                WholeScopeSemanticLifecycle(repository).start(
                    preparation,
                    provider=provider,
                    consent=consent,
                )
        attempts = repository.whole_scope_reserved_attempts(preparation.job.job_id)

    assert provider.requests == []
    assert attempts == ()


def _run_valid_hierarchy(service: NarrativeMapService):
    preparation = _prepare_hierarchy(service)
    consent = preparation.granted_consent()
    service.confirm_whole_scope_consent(preparation, consent)
    report = service.start_whole_scope_hierarchy(
        preparation,
        provider=_FakeProvider([_hierarchy_output()]),
        consent=consent,
        authority_validator=_accept_synthetic_hierarchy_authority,
    )
    assert report.provider_calls == 1
    status = service.freeze_whole_scope_hierarchy(
        preparation, _validated_hierarchy(), _frozen_evidence()
    )
    assert status.hierarchy_hash == semantic_outline_hash(
        assemble_semantic_outline(
            _validated_hierarchy().units,
            _validated_hierarchy().candidates,
            compile_hierarchy_to_gap_decisions(_validated_hierarchy()),
        )
    )
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
            preparation,
            provider=provider,
            consent=consent,
            authority_validator=_accept_synthetic_hierarchy_authority,
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
            authority_validator=_accept_synthetic_hierarchy_authority,
        )

    assert report.provider_calls == 1
    assert len(runner.requests) == 1
    request = runner.requests[0]
    assert request.schema_path.name == "whole_scope_hierarchy_v1.schema.json"
    envelope = json.loads(request.stdin)
    assert envelope["version"] == "m15-whole-scope-hierarchy-prompt-v2"
    assert envelope["request"]["job"]["schema"] == M15_WHOLE_SCOPE_HIERARCHY_INPUT_SCHEMA


@pytest.mark.parametrize("target", ("beat", "cluster"))
def test_boolean_whole_scope_confidence_is_rejected_directly_and_by_fake_provider(
    tmp_path: Path,
    target: str,
) -> None:
    malformed = _hierarchy_output()
    key = "beat_groups" if target == "beat" else "major_clusters"
    cast(list[dict[str, object]], malformed[key])[0]["confidence"] = True
    with Project.create(tmp_path / f"boolean-confidence-{target}.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        direct = validate_whole_scope_hierarchy_response(malformed, preparation.job)
        assert not direct.valid
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        provider = _FakeProvider([malformed, _hierarchy_output()])
        report = service.start_whole_scope_hierarchy(
            preparation,
            provider=provider,
            consent=consent,
            authority_validator=_accept_synthetic_hierarchy_authority,
        )

    assert report.provider_calls == 2
    assert report.validated_job_ids == (preparation.job.job_id,)
    assert len(provider.requests) == 2
    assert provider.requests[1].repair_codes


def test_hierarchy_freeze_and_editorial_preparation_reject_authority_substitution(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "authority-substitution.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        report = service.start_whole_scope_hierarchy(
            preparation,
            provider=_FakeProvider([_hierarchy_output()]),
            consent=consent,
            authority_validator=_accept_synthetic_hierarchy_authority,
        )
        assert report.validated_job_ids == (preparation.job.job_id,)

        unrelated = replace(_validated_hierarchy(), scope_id="scope-unrelated")
        with pytest.raises(ValueError, match="foreign"):
            service.freeze_whole_scope_hierarchy(preparation, unrelated, _frozen_evidence())
        assert service.whole_scope_semantic_status().hierarchy_state == "validated"  # type: ignore[union-attr]

        frozen = service.freeze_whole_scope_hierarchy(
            preparation, _validated_hierarchy(), _frozen_evidence()
        )
        assert frozen.hierarchy_hash is not None
        exact_subjects = service.frozen_whole_scope_editorial_subjects()
        assert len({item.membership_hash for item in exact_subjects}) == len(exact_subjects)
        assert all(item.membership_hash != frozen.hierarchy_hash for item in exact_subjects)
        foreign_subjects = list(_subjects())
        foreign_subjects[0] = WholeScopeEditorialSubject(
            "beat",
            "foreign-beat",
            cast(str, frozen.hierarchy_hash),
            ("foreign-evidence",),
        )
        foreign_payload = _editorial_input(cast(str, frozen.hierarchy_hash))
        foreign_payload["subjects"] = [item.to_dict() for item in foreign_subjects]
        foreign_payload["evidence"] = [
            {"evidence_id": "foreign-evidence", "text": "Synthetic foreign evidence."}
        ]
        with pytest.raises(ValueError, match="exact frozen hierarchy authority"):
            service.prepare_whole_scope_editorial(
                _authority(),
                "scope-day-1",
                cast(str, frozen.hierarchy_hash),
                foreign_subjects,
                foreign_payload,
                profile=_profile(),
                run_id="foreign-stage-e",
                source_hash="source-hash",
                correction_id="m15.1",
            )
        final = service.whole_scope_semantic_status()
        assert final is not None and final.editorial_state == "not_started"


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
    assert status.accounting.logical_jobs == 4
    assert status.accounting.transport_submissions == 3
    assert status.accounting.combined_submission_count == 3
    assert publication is not None and publication["publication_hash"] == status.publication_hash
    assert len(logical_records) == 4
    assert len({item["logical_job_id"] for item in logical_records}) == 4
    assert all(item["logical_job_id"] != item["transport_batch_id"] for item in logical_records)
    assert hierarchy_cache != editorial_cache

    with Project.open(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        replay_hierarchy = _prepare_hierarchy(service, replay=True)
        hierarchy_report = service.start_whole_scope_hierarchy(
            replay_hierarchy,
            authority_validator=_accept_synthetic_hierarchy_authority,
        )
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
            preparation,
            provider=provider,
            consent=consent,
            authority_validator=_accept_synthetic_hierarchy_authority,
        )
        retry_provider = _FakeProvider([_hierarchy_output()])
        retried = service.retry_whole_scope_semantic_build(
            preparation,
            provider=retry_provider,
            consent=consent,
            hierarchy_authority_validator=_accept_synthetic_hierarchy_authority,
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
            authority_validator=_accept_synthetic_hierarchy_authority,
        )
        resumed_provider = _FakeProvider([_hierarchy_output()])
        resumed = service.resume_whole_scope_semantic_build(
            preparation,
            provider=resumed_provider,
            consent=consent,
            hierarchy_authority_validator=_accept_synthetic_hierarchy_authority,
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


def test_concurrent_cancel_is_a_durable_fence_against_provider_completion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cancel-fence.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)

    provider = _BlockingFakeProvider(_hierarchy_output())
    reports: list[NarrativeWorkflowReport] = []

    def run_provider() -> None:
        with Project.open(path) as project:
            service = NarrativeMapService(NarrativeMapRepository(project))
            reports.append(
                service.start_whole_scope_hierarchy(
                    preparation,
                    provider=provider,
                    consent=consent,
                    authority_validator=_accept_synthetic_hierarchy_authority,
                )
            )

    worker = Thread(target=run_provider)
    worker.start()
    assert provider.entered.wait(5)
    with Project.open(path) as project:
        cancelling = NarrativeMapService(NarrativeMapRepository(project))
        cancelled = cancelling.cancel_whole_scope_semantic_build()
        assert cancelled is not None and cancelled.hierarchy_state == "cancelled"
    provider.release.set()
    worker.join(5)
    assert not worker.is_alive() and len(reports) == 1

    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        status = NarrativeMapService(repository).whole_scope_semantic_status()
        publication = repository.read_whole_scope_current()
        logical = repository.read_whole_scope_logical_records()

    assert status is not None and status.hierarchy_state == "cancelled"
    assert publication is None
    assert logical == ()


@pytest.mark.parametrize("iteration", range(3))
def test_settlement_and_reservation_are_one_transactional_read_modify_write(
    tmp_path: Path, iteration: int
) -> None:
    path = tmp_path / f"settlement-race-{iteration}.rsmproj"
    with Project.create(path) as project:
        NarrativeMapRepository(project).reserve_whole_scope_provider_submission(
            stage="hierarchy",
            manifest_id="manifest-h",
            maximum_manifest_calls=2,
            transport_batch_id="batch-h",
            attempt=1,
            combined_limit=4,
        )

    settlement_read = Event()
    reservation_finished = Event()

    class _PausingLegacySettlementRepository(NarrativeMapRepository):
        def _write_payloads(self, records):  # type: ignore[no-untyped-def,override]
            if records and records[0][1] == "combined":
                settlement_read.set()
                assert reservation_finished.wait(5)
            return super()._write_payloads(records)

    def settle() -> None:
        with Project.open(path) as project:
            _PausingLegacySettlementRepository(project).settle_whole_scope_provider_submissions(
                transport_batch_id="batch-h", attempts=(1,)
            )

    worker = Thread(target=settle)
    worker.start()
    legacy_interleaving = settlement_read.wait(0.2)
    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        repository.reserve_whole_scope_provider_submission(
            stage="hierarchy",
            manifest_id="manifest-h",
            maximum_manifest_calls=2,
            transport_batch_id="batch-h",
            attempt=2,
            combined_limit=4,
        )
    reservation_finished.set()
    worker.join(5)
    assert not worker.is_alive()
    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        assert repository.whole_scope_submission_ordinals("batch-h") == {1: 1, 2: 2}
        assert repository.whole_scope_submission_count() == 2
    assert legacy_interleaving is False


def test_crash_reserved_attempt_is_recovered_as_consumed_history(tmp_path: Path) -> None:
    with Project.create(tmp_path / "crash-reserved.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        repository.reserve_whole_scope_provider_submission(
            stage="hierarchy",
            manifest_id=consent.manifest_id,
            maximum_manifest_calls=2,
            transport_batch_id=preparation.job.job_id,
            attempt=1,
            combined_limit=4,
        )
        provider = _FakeProvider([_hierarchy_output()])
        report = service.resume_whole_scope_semantic_build(
            preparation,
            provider=provider,
            consent=consent,
            hierarchy_authority_validator=_accept_synthetic_hierarchy_authority,
        )
        record = repository.get(preparation.job.kind, preparation.job.job_id)

    assert report.provider_calls == 1
    assert len(provider.requests) == 1
    assert record is not None and record.attempt_count == 2
    assert record.provider_calls == 2


def test_retry_accumulates_durable_calls_and_usage_across_manifests(tmp_path: Path) -> None:
    with Project.create(tmp_path / "cumulative-retry.rsmproj") as project:
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        first = service.prepare_whole_scope_hierarchy(
            _authority(),
            "scope-day-1",
            _validated_hierarchy().ordered_unit_ids,
            _hierarchy_input(),
            known_evidence_ids=("evidence-a", "evidence-b"),
            known_characters=("Ava",),
            profile=_profile(),
            run_id="first-manifest",
            source_hash="source-hash",
            correction_id="m15.1",
            maximum_provider_calls=1,
        )
        first_consent = first.granted_consent()
        service.confirm_whole_scope_consent(first, first_consent)
        failed = service.start_whole_scope_hierarchy(
            first,
            provider=_FakeProvider([{"bad": True}]),
            consent=first_consent,
            authority_validator=_accept_synthetic_hierarchy_authority,
        )
        second = _prepare_hierarchy(service)
        second_consent = second.granted_consent()
        service.confirm_whole_scope_consent(second, second_consent)
        succeeded = service.retry_whole_scope_semantic_build(
            second,
            provider=_FakeProvider([_hierarchy_output()]),
            consent=second_consent,
            hierarchy_authority_validator=_accept_synthetic_hierarchy_authority,
        )
        status = service.whole_scope_semantic_status()

    assert failed.provider_calls == succeeded.provider_calls == 1
    assert status is not None
    assert status.accounting.transport_submissions == 2
    assert status.accounting.input_tokens == 200
    assert status.accounting.output_tokens == 40
    assert status.accounting.elapsed_ms == 10


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.update({"external_context": {"reference": "synthetic"}}),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"credential_hint": "synthetic"}
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].pop(
            "story_atom_id"
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"speaker_ids": []}
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].pop(
            "lane_id"
        ),
        lambda payload: cast(list[dict[str, object]], payload["evidence"]).pop(),
        lambda payload: cast(
            dict[str, object],
            cast(list[dict[str, object]], payload["evidence"])[0]["locator"],
        ).pop("line_basis"),
        lambda payload: cast(list[dict[str, object]], payload["hard_locks"]).append(
            {"lock_id": "lock-a", "tool": {"name": "synthetic"}}
        ),
    ),
)
def test_stage_h_input_projection_fails_closed_before_preparation(
    tmp_path: Path, mutate: Callable[[dict[str, object]], object]
) -> None:
    with Project.create(tmp_path / "stage-h-sterile-shape.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        payload = _hierarchy_input()
        mutate(payload)
        with pytest.raises(ValueError):
            service.prepare_whole_scope_hierarchy(
                _authority(),
                "scope-day-1",
                _validated_hierarchy().ordered_unit_ids,
                payload,
                known_evidence_ids=("evidence-a", "evidence-b"),
                known_characters=("Ava",),
                profile=_profile(),
                run_id="sterile-shape",
                source_hash="source-hash",
                correction_id="m15.1",
            )
        assert service.whole_scope_semantic_status() is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: cast(list[dict[str, object]], payload["evidence"])[0].update(
            {"text": "Altered same-shaped story evidence."}
        ),
        lambda payload: cast(list[dict[str, object]], payload["evidence"])[0].update(
            {"atom_id": "atom-altered"}
        ),
        lambda payload: cast(list[dict[str, object]], payload["evidence"])[0].update(
            {"kind": "narration"}
        ),
        lambda payload: cast(
            dict[str, object],
            cast(list[dict[str, object]], payload["evidence"])[0]["locator"],
        ).update({"start_line": 99, "end_line": 99}),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"sequence_id": "sequence-altered"}
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"lane_id": "lane-altered"}
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"call_occurrence_id": "call-altered"}
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"loop_id": "loop-altered"}
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"parent_choice_id": "choice-altered", "parent_arm_id": "arm-altered"}
        ),
        lambda payload: cast(list[dict[str, object]], payload["units"])[0].update(
            {"entry_node_id": "entry-altered", "exit_node_id": "exit-altered"}
        ),
    ),
)
def test_stage_h_same_shape_authority_mutation_fails_before_consent(
    tmp_path: Path, mutate: Callable[[dict[str, object]], object]
) -> None:
    with Project.create(tmp_path / "stage-h-exact-authority.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        payload = _hierarchy_input()
        mutate(payload)
        units = _validated_hierarchy().units
        with pytest.raises(ValueError, match="exact typed authority"):
            service.prepare_whole_scope_hierarchy(
                _authority(),
                "scope-day-1",
                tuple(item.unit_id for item in units),
                payload,
                hierarchy_units=units,
                evidence_by_unit=_hierarchy_evidence_by_unit(),
                hierarchy_hard_locks=(),
                known_evidence_ids=("evidence-a", "evidence-b"),
                known_characters=("Ava",),
                profile=_profile(),
                run_id="same-shape-authority-mutation",
                source_hash="source-hash",
                correction_id="m15.1",
            )
        assert service.whole_scope_semantic_status() is None


@pytest.mark.parametrize("mutation", ("omitted", "reordered", "changed"))
def test_stage_h_exact_hard_lock_order_is_bound_before_consent(
    tmp_path: Path, mutation: str
) -> None:
    with Project.create(tmp_path / f"stage-h-lock-{mutation}.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        units = _validated_hierarchy().units
        locks = (
            HierarchyHardLock(
                "lock-a",
                HierarchyHardLockKind.SCOPE_MARKER,
                unit_ids=(units[0].unit_id,),
            ),
            HierarchyHardLock(
                "lock-b",
                HierarchyHardLockKind.SCOPE_MARKER,
                unit_ids=(units[1].unit_id,),
            ),
        )
        payload = _hierarchy_input()
        exact_locks = [
            {
                "lock_id": item.lock_id,
                "kind": item.kind.value,
                "unit_ids": list(item.unit_ids),
                "left_unit_id": item.left_unit_id,
                "right_unit_id": item.right_unit_id,
                "choice_id": item.choice_id,
                "arm_ids": list(item.arm_ids),
            }
            for item in locks
        ]
        payload["hard_locks"] = (
            []
            if mutation == "omitted"
            else list(reversed(exact_locks))
            if mutation == "reordered"
            else [*exact_locks[:-1], {**exact_locks[-1], "lock_id": "lock-changed"}]
        )
        with pytest.raises(ValueError, match="exact typed authority"):
            service.prepare_whole_scope_hierarchy(
                _authority(),
                "scope-day-1",
                tuple(item.unit_id for item in units),
                payload,
                hierarchy_units=units,
                evidence_by_unit=_hierarchy_evidence_by_unit(),
                hierarchy_hard_locks=locks,
                known_evidence_ids=("evidence-a", "evidence-b"),
                known_characters=("Ava",),
                profile=_profile(),
                run_id=f"hard-lock-{mutation}",
                source_hash="source-hash",
                correction_id="m15.1",
            )
        assert service.whole_scope_semantic_status() is None


def test_stage_e_input_projection_fails_closed_before_prompt_serialization(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "stage-e-sterile-shape.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        _, hierarchy_hash = _run_valid_hierarchy(service)
        assert hierarchy_hash is not None
        payload = _editorial_input(hierarchy_hash)
        cast(list[dict[str, object]], payload["evidence"])[0]["transport_tool"] = {
            "name": "synthetic"
        }
        with pytest.raises(ValueError, match="Stage E input shape"):
            service.prepare_whole_scope_editorial(
                _authority(),
                "scope-day-1",
                hierarchy_hash,
                _subjects(),
                payload,
                profile=_profile(),
                run_id="sterile-editorial-shape",
                source_hash="source-hash",
                correction_id="m15.1",
            )
        status = service.whole_scope_semantic_status()
        assert status is not None and status.editorial_state == "not_started"


def test_targeted_repair_may_replace_only_rejected_hierarchy_groups(tmp_path: Path) -> None:
    invalid = _hierarchy_output()
    cast(list[dict[str, object]], invalid["beat_groups"])[1]["ordered_unit_ids"] = ["unit-a"]
    with Project.create(tmp_path / "targeted-hierarchy-repair.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        provider = _FakeProvider([invalid, _hierarchy_output()])
        report = service.start_whole_scope_hierarchy(
            preparation,
            provider=provider,
            consent=consent,
            authority_validator=_accept_synthetic_hierarchy_authority,
        )

    assert report.validated_job_ids == (preparation.job.job_id,)
    assert report.provider_calls == 2


def test_targeted_repair_may_replace_rejected_editorial_record(tmp_path: Path) -> None:
    with Project.create(tmp_path / "targeted-editorial-repair.rsmproj") as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        _, hierarchy_hash = _run_valid_hierarchy(service)
        assert hierarchy_hash is not None
        preparation = service.prepare_whole_scope_editorial(
            _authority(),
            "scope-day-1",
            hierarchy_hash,
            _subjects(),
            _editorial_input(hierarchy_hash),
            profile=_profile(),
            run_id="targeted-editorial",
            source_hash="source-hash",
            correction_id="m15.1",
        )
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        invalid = _editorial_output(hierarchy_hash)
        cast(list[dict[str, object]], invalid["records"])[0]["title"] = "Evidence Node"
        provider = _FakeProvider([invalid, _editorial_output(hierarchy_hash)])
        report = service.start_whole_scope_editorial(
            preparation, provider=provider, consent=consent
        )

    assert report.validated_job_ids == (preparation.job.job_id,)
    assert report.provider_calls == 2


@pytest.mark.parametrize("stage", ("hierarchy", "editorial"))
@pytest.mark.parametrize("completion_first", (False, True))
def test_cancel_and_completion_are_atomic_in_both_orders(
    tmp_path: Path, stage: str, completion_first: bool
) -> None:
    path = tmp_path / f"cancel-{stage}-{completion_first}.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        if stage == "hierarchy":
            preparation = _prepare_hierarchy(service)
            payload = _hierarchy_output()
        else:
            _, hierarchy_hash = _run_valid_hierarchy(service)
            assert hierarchy_hash is not None
            preparation = service.prepare_whole_scope_editorial(
                _authority(),
                "scope-day-1",
                hierarchy_hash,
                _subjects(),
                _editorial_input(hierarchy_hash),
                profile=_profile(),
                run_id="reverse-cancel-editorial",
                source_hash="source-hash",
                correction_id="m15.1",
            )
            payload = _editorial_output(hierarchy_hash)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)

    provider = _BlockingFakeProvider(payload)
    errors: list[BaseException] = []
    cancel_statuses: list[WholeScopeSemanticStatus | None] = []
    stage_reports: list[NarrativeWorkflowReport] = []

    def run_stage() -> None:
        try:
            with Project.open(path) as project:
                service = NarrativeMapService(NarrativeMapRepository(project))
                if stage == "hierarchy":
                    stage_reports.append(
                        service.start_whole_scope_hierarchy(
                            preparation,
                            provider=provider,
                            consent=consent,
                            authority_validator=_accept_synthetic_hierarchy_authority,
                        )
                    )
                else:
                    stage_reports.append(
                        service.start_whole_scope_editorial(
                            preparation, provider=provider, consent=consent
                        )
                    )
        except BaseException as exc:
            errors.append(exc)

    stage_thread = Thread(target=run_stage)
    stage_thread.start()
    assert provider.entered.wait(5)

    cancel_thread: Thread | None = None
    cancel_release = Event()
    if completion_first:
        cancel_entered = Event()

        def cancel_late() -> None:
            try:
                with Project.open(path) as project:
                    repository = _PausingTransitionRepository(
                        project,
                        lambda value: (
                            isinstance(value, dict)
                            and "cancelled"
                            in {
                                value.get("hierarchy_state"),
                                value.get("editorial_state"),
                            }
                        ),
                        cancel_entered,
                        cancel_release,
                    )
                    cancel_statuses.append(
                        NarrativeMapService(repository).cancel_whole_scope_semantic_build()
                    )
            except BaseException as exc:
                errors.append(exc)

        cancel_thread = Thread(target=cancel_late)
        cancel_thread.start()
        assert cancel_entered.wait(5)
        provider.release.set()
        stage_thread.join(5)
        assert not stage_thread.is_alive()
        cancel_release.set()
        cancel_thread.join(5)
    else:
        with Project.open(path) as project:
            cancel_statuses.append(
                NarrativeMapService(
                    NarrativeMapRepository(project)
                ).cancel_whole_scope_semantic_build()
            )
        provider.release.set()
        stage_thread.join(5)

    assert not stage_thread.is_alive()
    assert cancel_thread is None or not cancel_thread.is_alive()
    assert errors == [] and len(cancel_statuses) == len(stage_reports) == 1
    with Project.open(path) as project:
        repository = NarrativeMapRepository(project)
        status = NarrativeMapService(repository).whole_scope_semantic_status()
        publication = repository.read_whole_scope_current()
        logical_records = repository.read_whole_scope_logical_records()

    assert status is not None
    stage_report = stage_reports[0]
    assert cancel_statuses[0] is not None
    if completion_first:
        assert cancel_statuses[0] == status
        assert stage_report.validated_job_ids == (preparation.job.job_id,)
        assert stage_report.deferred_job_ids == ()
        assert stage_report.cancelled is False
    else:
        assert stage_report.validated_job_ids == ()
        assert stage_report.deferred_job_ids == (preparation.job.job_id,)
        assert stage_report.cancelled is True
    assert stage_report.provider_calls == 1
    assert stage_report.input_tokens == 100
    assert stage_report.output_tokens == 20
    assert stage_report.elapsed_ms == 5
    assert stage_report.terminal_reservations == ((preparation.job.job_id, 1),)
    if completion_first:
        if stage == "hierarchy":
            assert status.hierarchy_state == "validated"
            assert publication is None and len(logical_records) == 1
        else:
            assert status.editorial_state == "complete"
            assert publication is not None
            assert publication["publication_hash"] == status.publication_hash
            assert len(logical_records) == 4
    elif stage == "hierarchy":
        assert cancel_statuses[0].hierarchy_state == "cancelled"
        assert status.hierarchy_state == "cancelled"
        assert publication is None and logical_records == ()
    else:
        assert cancel_statuses[0].editorial_state == "cancelled"
        assert status.editorial_state == "cancelled"
        assert publication is None and len(logical_records) == 1


@pytest.mark.parametrize("stage", ("hierarchy", "editorial"))
@pytest.mark.parametrize("stale_confirmation_last", (False, True))
def test_consent_confirmation_cannot_overwrite_newer_preparation(
    tmp_path: Path, stage: str, stale_confirmation_last: bool
) -> None:
    path = tmp_path / f"confirm-{stage}-{stale_confirmation_last}.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        if stage == "hierarchy":
            preparation = _prepare_hierarchy(service, run_id="old-h-confirmation")
            hierarchy_hash = None
        else:
            _, hierarchy_hash = _run_valid_hierarchy(service)
            assert hierarchy_hash is not None
            preparation = service.prepare_whole_scope_editorial(
                _authority(),
                "scope-day-1",
                hierarchy_hash,
                _subjects(),
                _editorial_input(hierarchy_hash),
                profile=_profile(),
                run_id="old-e-confirmation",
                source_hash="source-hash",
                correction_id="m15.1",
            )
        consent = preparation.granted_consent()

    statuses: list[WholeScopeSemanticStatus] = []
    errors: list[BaseException] = []
    confirm_release = Event()
    confirm_thread: Thread | None = None
    if stale_confirmation_last:
        confirm_entered = Event()

        def confirm_late() -> None:
            try:
                with Project.open(path) as project:
                    repository = _PausingTransitionRepository(
                        project,
                        lambda value: (
                            isinstance(value, dict)
                            and value.get(f"{stage}_state") == "awaiting_start"
                        ),
                        confirm_entered,
                        confirm_release,
                    )
                    statuses.append(
                        NarrativeMapService(repository).confirm_whole_scope_consent(
                            preparation, consent
                        )
                    )
            except BaseException as exc:
                errors.append(exc)

        confirm_thread = Thread(target=confirm_late)
        confirm_thread.start()
        assert confirm_entered.wait(5)
    else:
        with Project.open(path) as project:
            statuses.append(
                NarrativeMapService(NarrativeMapRepository(project)).confirm_whole_scope_consent(
                    preparation, consent
                )
            )

    with Project.open(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        if stage == "hierarchy":
            changed = _prepare_hierarchy(service, run_id="new-h-preparation")
        else:
            assert hierarchy_hash is not None
            changed = service.prepare_whole_scope_editorial(
                _authority(),
                "scope-day-1",
                hierarchy_hash,
                _subjects(),
                _editorial_input(hierarchy_hash),
                profile=_profile(),
                run_id="new-e-preparation",
                source_hash="source-hash",
                correction_id="m15.1",
            )
    if confirm_thread is not None:
        confirm_release.set()
        confirm_thread.join(5)
        assert not confirm_thread.is_alive()

    assert errors == [] and len(statuses) == 1
    with Project.open(path) as project:
        final = NarrativeMapRepository(project).read_whole_scope_build()
    assert final is not None
    assert final[f"{stage}_manifest_id"] == changed.consent.manifest_id
    assert final[f"{stage}_state"] == "awaiting_consent"
    assert final[f"confirmed_{stage}_manifest_id"] is None
    if stale_confirmation_last:
        if stage == "hierarchy":
            assert statuses[0].hierarchy_state == "awaiting_consent"
        else:
            assert statuses[0].editorial_state == "awaiting_consent"
    elif stage == "hierarchy":
        assert statuses[0].hierarchy_state == "awaiting_start"
    else:
        assert statuses[0].editorial_state == "awaiting_start"


@pytest.mark.parametrize("stale_replay_last", (False, True))
def test_zero_submit_replay_cannot_overwrite_changed_preparation(
    tmp_path: Path, stale_replay_last: bool
) -> None:
    path = tmp_path / f"replay-preparation-{stale_replay_last}.rsmproj"
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        _run_valid_hierarchy(service)
        replay = _prepare_hierarchy(service, replay=True)

    reports: list[NarrativeWorkflowReport] = []
    errors: list[BaseException] = []
    replay_release = Event()
    replay_thread: Thread | None = None
    if stale_replay_last:
        replay_entered = Event()

        def replay_late() -> None:
            try:
                with Project.open(path) as project:
                    repository = _PausingTransitionRepository(
                        project,
                        lambda value: (
                            isinstance(value, dict)
                            and value.get("hierarchy_state") == "frozen"
                            and value.get("cache_hits") == 1
                        ),
                        replay_entered,
                        replay_release,
                    )
                    reports.append(
                        NarrativeMapService(repository).start_whole_scope_hierarchy(
                            replay,
                            authority_validator=_accept_synthetic_hierarchy_authority,
                        )
                    )
            except BaseException as exc:
                errors.append(exc)

        replay_thread = Thread(target=replay_late)
        replay_thread.start()
        assert replay_entered.wait(5)
    else:
        with Project.open(path) as project:
            reports.append(
                NarrativeMapService(NarrativeMapRepository(project)).start_whole_scope_hierarchy(
                    replay,
                    authority_validator=_accept_synthetic_hierarchy_authority,
                )
            )

    with Project.open(path) as project:
        changed = _prepare_hierarchy(
            NarrativeMapService(NarrativeMapRepository(project)),
            run_id="changed-replay-preparation",
        )
    if replay_thread is not None:
        replay_release.set()
        replay_thread.join(5)
        assert not replay_thread.is_alive()

    assert errors == [] and len(reports) == 1
    with Project.open(path) as project:
        final = NarrativeMapRepository(project).read_whole_scope_build()
    assert final is not None
    assert final["hierarchy_manifest_id"] == changed.consent.manifest_id
    assert final["hierarchy_state"] == "awaiting_consent"
    if stale_replay_last:
        report = reports[0]
        assert report.cache_hits == 0
        assert report.deferred_job_ids == (replay.job.job_id,)


@pytest.mark.parametrize("stale_freeze_last", (False, True))
def test_freeze_cannot_overwrite_changed_preparation(
    tmp_path: Path, stale_freeze_last: bool
) -> None:
    path = tmp_path / f"freeze-preparation-{stale_freeze_last}.rsmproj"
    hierarchy = _validated_hierarchy()
    with Project.create(path) as project:
        service = NarrativeMapService(NarrativeMapRepository(project))
        preparation = _prepare_hierarchy(service)
        consent = preparation.granted_consent()
        service.confirm_whole_scope_consent(preparation, consent)
        service.start_whole_scope_hierarchy(
            preparation,
            provider=_FakeProvider([_hierarchy_output()]),
            consent=consent,
            authority_validator=_accept_synthetic_hierarchy_authority,
        )

    errors: list[BaseException] = []
    freeze_statuses: list[WholeScopeSemanticStatus] = []
    freeze_release = Event()
    freeze_thread: Thread | None = None
    if stale_freeze_last:
        freeze_entered = Event()

        def freeze_late() -> None:
            try:
                with Project.open(path) as project:
                    repository = _PausingTransitionRepository(
                        project,
                        lambda value: (
                            isinstance(value, dict) and value.get("hierarchy_state") == "frozen"
                        ),
                        freeze_entered,
                        freeze_release,
                    )
                    freeze_statuses.append(
                        NarrativeMapService(repository).freeze_whole_scope_hierarchy(
                            preparation, hierarchy, _frozen_evidence()
                        )
                    )
            except BaseException as exc:
                errors.append(exc)

        freeze_thread = Thread(target=freeze_late)
        freeze_thread.start()
        assert freeze_entered.wait(5)
    else:
        with Project.open(path) as project:
            freeze_statuses.append(
                NarrativeMapService(NarrativeMapRepository(project)).freeze_whole_scope_hierarchy(
                    preparation, hierarchy, _frozen_evidence()
                )
            )

    with Project.open(path) as project:
        changed = _prepare_hierarchy(
            NarrativeMapService(NarrativeMapRepository(project)),
            run_id="changed-freeze-preparation",
        )
    if freeze_thread is not None:
        freeze_release.set()
        freeze_thread.join(5)
        assert not freeze_thread.is_alive()

    assert errors == [] and len(freeze_statuses) == 1
    with Project.open(path) as project:
        final = NarrativeMapRepository(project).read_whole_scope_build()
    assert final is not None
    assert final["hierarchy_manifest_id"] == changed.consent.manifest_id
    assert final["hierarchy_state"] == "awaiting_consent"
    assert final["hierarchy_hash"] is None
    if stale_freeze_last:
        assert freeze_statuses[0].hierarchy_state == "awaiting_consent"
        assert freeze_statuses[0].hierarchy_hash is None
    else:
        assert freeze_statuses[0].hierarchy_state == "frozen"

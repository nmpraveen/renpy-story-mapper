"""Strict product adapter for the M15.1 semantic production lifecycle.

This module is the only web-facing bridge from current M10/M11 authority to the
transient semantic provider inputs.  Prepared prompt payloads and source text
never enter its response serializers.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from typing import Final, Protocol, cast

from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CanonicalGraph,
    SourceEvidence,
)
from renpy_story_mapper.m11_persistence import M11Availability
from renpy_story_mapper.m11_scene_model import SceneModel, StoryAtom
from renpy_story_mapper.m11_scene_projection import scene_model_from_stored_results
from renpy_story_mapper.m12_service import canonical_graph_from_mapping
from renpy_story_mapper.narrative.contracts import ProviderSettings
from renpy_story_mapper.narrative.provider import ADAPTER_NAME, ADAPTER_VERSION
from renpy_story_mapper.narrative_map import (
    BoundaryWindow,
    FineNarrativeUnit,
    FrozenSummaryInput,
    NarrativeGapCandidate,
    NarrativeMapRepository,
    NarrativeMapService,
    SemanticEvidenceRecord,
    SemanticOutline,
    SemanticStage,
    SemanticStagePreparation,
    SemanticStatusView,
    assemble_semantic_outline,
    assemble_semantic_outline_from_authority,
    build_all_eligible_gap_candidates,
    build_boundary_windows,
    build_fine_narrative_units,
    build_semantic_quotient_topology,
    compile_hierarchy_to_gap_decisions,
)
from renpy_story_mapper.narrative_map.adapters import bind_m15_authority
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    SourceLocator,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.persistence import NarrativeJobStatus
from renpy_story_mapper.narrative_map.provider import (
    WHOLE_SCOPE_EDITORIAL_PROMPT_VERSION,
    WHOLE_SCOPE_EDITORIAL_RESPONSE_SCHEMA,
    WHOLE_SCOPE_HIERARCHY_PROMPT_VERSION,
    WHOLE_SCOPE_HIERARCHY_RESPONSE_SCHEMA,
    NarrativeConsentManifest,
    NarrativeMapProvider,
    NarrativeMapProviderError,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
    SterileNarrativeMapProvider,
    WholeScopeEditorialSubject,
    WholeScopeProviderSubject,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    M15_WHOLE_SCOPE_EDITORIAL_INPUT_SCHEMA,
    MAXIMUM_DAY1_PROVIDER_SUBMISSIONS,
    WholeScopeSemanticStage,
)
from renpy_story_mapper.narrative_map.semantic_hierarchy import (
    HierarchyHardLock,
    HierarchyHardLockKind,
    ValidatedWholeScopeHierarchy,
    validate_whole_scope_hierarchy_from_authority,
)
from renpy_story_mapper.narrative_map.semantic_lifecycle import (
    WholeScopeLogicalJob,
    WholeScopeStagePreparation,
    derive_frozen_editorial_authority,
    whole_scope_hierarchy_input_payload,
)
from renpy_story_mapper.narrative_map.semantic_projection import (
    semantic_outline_hash,
    semantic_outline_payload,
)
from renpy_story_mapper.narrative_map.semantic_validation import (
    validate_whole_scope_hierarchy_response,
)
from renpy_story_mapper.narrative_map.validation import ValidationFinding
from renpy_story_mapper.project import Project
from renpy_story_mapper.web.contracts import JsonValue

M15_SEMANTIC_RESPONSE_SCHEMA: Final = "m15-semantic-production-v1"
M15_SEMANTIC_CORRECTION_ID: Final = "m15.1-product-path-v1"
M15_WHOLE_SCOPE_CORRECTION_ID: Final = "m15.1-whole-scope-product-v4"
M15_SEMANTIC_PRIVACY_SCOPE: Final = "story_evidence_only"
M15_SEMANTIC_MODEL: Final = "gpt-5.6-sol"
M15_SEMANTIC_REASONING: Final = "medium"
M15_SEMANTIC_MAXIMUM_CONCURRENCY: Final = 1
M15_SEMANTIC_CONSENT_VALID_FOR: Final = timedelta(hours=1)
M15_SEMANTIC_STAGE_H_TIMEOUT_SECONDS: Final = 900.0


class M15ProviderFactory(Protocol):
    def __call__(self) -> NarrativeMapProvider: ...


class _LegacyHierarchyConcurrentUpdate(RuntimeError):
    """An invalid legacy hierarchy changed while fail-closed quarantine ran."""


class _NoSubmitProvider:
    """Fail closed if a supposedly cache-only replay attempts transmission."""

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        del request, cancelled
        raise AssertionError("an exact M15 replay attempted provider submission")

    def cancel(self) -> None:
        return None


class _LazyM15Provider:
    """Delay provider construction until the durable lifecycle is ready to submit."""

    def __init__(self, factory: M15ProviderFactory) -> None:
        self._factory = factory
        self._provider: NarrativeMapProvider | None = None
        self._lock = Lock()
        self._cancelled = False

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        with self._lock:
            if self._cancelled or cancelled():
                raise NarrativeMapProviderError(
                    "cancelled",
                    "The semantic request was cancelled before provider construction.",
                    provider_call_reserved=False,
                )
            if self._provider is None:
                self._provider = self._factory()
            provider = self._provider
        return provider.submit(request, cancelled)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            provider = self._provider
        if provider is not None:
            provider.cancel()


@dataclass(frozen=True)
class M15SemanticInputs:
    canonical: CanonicalGraph
    scene_model: SceneModel
    units: tuple[FineNarrativeUnit, ...]
    candidates: tuple[NarrativeGapCandidate, ...]
    windows: tuple[BoundaryWindow, ...]
    evidence_by_unit: Mapping[str, tuple[SemanticEvidenceRecord, ...]]

    @property
    def source_hash(self) -> str:
        return self.canonical.source_generation


@dataclass(frozen=True)
class _FrozenEditorialAuthority:
    hierarchy_hash: str
    hierarchy_payload: Mapping[str, object]
    subjects: tuple[WholeScopeEditorialSubject, ...]
    evidence: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class M15SemanticAuthority:
    canonical: CanonicalGraph
    scene_model: SceneModel

    @property
    def source_hash(self) -> str:
        return self.canonical.source_generation

    @property
    def authority(self) -> AuthorityBinding:
        return bind_m15_authority(self.canonical, self.scene_model)


@dataclass(frozen=True)
class M15SummaryInputs:
    outline: SemanticOutline
    inputs: tuple[FrozenSummaryInput, ...]


@dataclass(frozen=True)
class RecoveredSemanticRun:
    preparation: SemanticStagePreparation
    consent: NarrativeConsentManifest
    replay_only: bool


def m15_provider_profile() -> ProviderProfile:
    """Return the single supported, non-configurable M15 product profile."""

    return ProviderProfile(
        provider="openai",
        adapter=ADAPTER_NAME,
        adapter_version=ADAPTER_VERSION,
        requested_model=M15_SEMANTIC_MODEL,
        settings=ProviderSettings(
            (
                ("fast_mode", False),
                ("reasoning_effort", M15_SEMANTIC_REASONING),
            )
        ),
    )


def default_m15_provider_factory() -> NarrativeMapProvider:
    """Construct the sterile adapter lazily, after exact web confirmation."""

    return SterileNarrativeMapProvider()


class M15WholeScopeProductController:
    """Shipped Stage H/E adapter over current project authority and durable lifecycle state."""

    def __init__(
        self,
        project_path: Callable[[], Path],
        provider_factory: M15ProviderFactory = default_m15_provider_factory,
    ) -> None:
        self._project_path = project_path
        self._provider_factory = provider_factory
        self._preparations: dict[WholeScopeSemanticStage, WholeScopeStagePreparation] = {}
        self._lock = Lock()
        self._execution_lock = Lock()
        self._cancel_event = Event()
        self._active_provider: NarrativeMapProvider | None = None

    def __call__(self, action: str, body: dict[str, JsonValue]) -> Mapping[str, object]:
        if action == "prepare_hierarchy":
            try:
                with self._execution_lock:
                    preparation = self._prepare_hierarchy()
            except _LegacyHierarchyConcurrentUpdate:
                return self._legacy_reconciliation_stale_response()
            return whole_scope_preparation_response(preparation)
        if action == "prepare_editorial":
            try:
                with self._execution_lock:
                    preparation = self._prepare_editorial()
            except _LegacyHierarchyConcurrentUpdate:
                return self._legacy_reconciliation_stale_response()
            return whole_scope_preparation_response(preparation)
        if action in {"start_hierarchy", "start_editorial"}:
            stage = (
                WholeScopeSemanticStage.HIERARCHY
                if action == "start_hierarchy"
                else WholeScopeSemanticStage.EDITORIAL
            )
            manifest_id = body.get("manifest_id")
            if not isinstance(manifest_id, str) or body.get("confirm_cloud") is not True:
                raise ValueError("whole-scope start requires exact manifest confirmation")
            try:
                with self._execution_lock:
                    with self._lock:
                        current_preparation = self._preparations.get(stage)
                    if current_preparation is None:
                        current_preparation = (
                            self._prepare_hierarchy()
                            if stage is WholeScopeSemanticStage.HIERARCHY
                            else self._prepare_editorial()
                        )
                    if current_preparation.consent.manifest_id != manifest_id:
                        return self._stale_preparation(stage, current_preparation)
                    return self._execute(current_preparation, operation="start")
            except _LegacyHierarchyConcurrentUpdate:
                return self._legacy_reconciliation_stale_response()
        if action == "status":
            try:
                return self._status()
            except _LegacyHierarchyConcurrentUpdate:
                return self._legacy_reconciliation_stale_response()
        if action == "cancel":
            self._cancel_event.set()
            with self._lock:
                provider = self._active_provider
            if provider is not None:
                with suppress(Exception):
                    provider.cancel()
            with Project.open(self._project_path()) as project:
                service = NarrativeMapService(NarrativeMapRepository(project))
                status = service.cancel_whole_scope_semantic_build()
            return whole_scope_status_response(status)
        if action in {"resume", "retry"}:
            try:
                with self._execution_lock:
                    stage, recovery_preparation = self._current_preparation()
                    if recovery_preparation is None:
                        return self._stale_preparation(stage, None)
                    return self._execute(recovery_preparation, operation=action)
            except _LegacyHierarchyConcurrentUpdate:
                return self._legacy_reconciliation_stale_response()
        raise ValueError("unsupported whole-scope semantic action")

    def _prepare_hierarchy(
        self, *, recover_confirmed: bool = False
    ) -> WholeScopeStagePreparation:
        with Project.open(self._project_path()) as project:
            inputs = load_m15_semantic_inputs(project)
            repository = NarrativeMapRepository(project)
            service = NarrativeMapService(repository)
            self._reconcile_legacy_invalid_hierarchy(
                project,
                repository,
                service,
                inputs=inputs,
            )
            scope_id, payload, hard_locks = _whole_scope_hierarchy_input(inputs)
            preparation = service.prepare_whole_scope_hierarchy(
                inputs.units[0].authority,
                scope_id,
                tuple(item.unit_id for item in inputs.units),
                payload,
                hierarchy_units=inputs.units,
                evidence_by_unit=inputs.evidence_by_unit,
                hierarchy_hard_locks=hard_locks,
                known_evidence_ids=tuple(
                    dict.fromkeys(
                        item.evidence_id
                        for unit_id in tuple(item.unit_id for item in inputs.units)
                        for item in inputs.evidence_by_unit[unit_id]
                    )
                ),
                known_characters=tuple(
                    dict.fromkeys(speaker for item in inputs.units for speaker in item.speaker_ids)
                ),
                profile=m15_provider_profile(),
                run_id=f"m15-web-whole-scope-h-{uuid.uuid4().hex}",
                source_hash=inputs.source_hash,
                correction_id=M15_WHOLE_SCOPE_CORRECTION_ID,
                privacy_scope=M15_SEMANTIC_PRIVACY_SCOPE,
                valid_for=M15_SEMANTIC_CONSENT_VALID_FOR,
                timeout_seconds=M15_SEMANTIC_STAGE_H_TIMEOUT_SECONDS,
                replay_existing=True,
                recover_confirmed=recover_confirmed,
            )
        with self._lock:
            self._preparations[WholeScopeSemanticStage.HIERARCHY] = preparation
        return preparation

    def _prepare_editorial(
        self, *, recover_confirmed: bool = False
    ) -> WholeScopeStagePreparation:
        with Project.open(self._project_path()) as project:
            inputs = load_m15_semantic_inputs(project)
            repository = NarrativeMapRepository(project)
            service = NarrativeMapService(repository)
            self._reconcile_legacy_invalid_hierarchy(
                project,
                repository,
                service,
                inputs=inputs,
            )
            status = service.whole_scope_semantic_status()
            if status is None or status.hierarchy_state != "frozen" or not status.hierarchy_hash:
                raise ValueError("Stage E requires the exact frozen Stage H hierarchy")
            frozen = _reconstruct_frozen_editorial_authority(inputs, repository)
            if status.hierarchy_hash != frozen.hierarchy_hash:
                raise ValueError("Stage E hierarchy is stale for current authority")
            subjects = frozen.subjects
            evidence = list(frozen.evidence)
            payload = {
                "schema": M15_WHOLE_SCOPE_EDITORIAL_INPUT_SCHEMA,
                "scope_id": status.scope_id,
                "authority": status.authority.to_dict(),
                "hierarchy_hash": status.hierarchy_hash,
                "subjects": [item.to_dict() for item in subjects],
                "evidence": evidence,
            }
            preparation = service.prepare_whole_scope_editorial(
                status.authority,
                status.scope_id,
                status.hierarchy_hash,
                subjects,
                payload,
                profile=m15_provider_profile(),
                run_id=f"m15-web-whole-scope-e-{uuid.uuid4().hex}",
                source_hash=inputs.source_hash,
                correction_id=M15_WHOLE_SCOPE_CORRECTION_ID,
                privacy_scope=M15_SEMANTIC_PRIVACY_SCOPE,
                valid_for=M15_SEMANTIC_CONSENT_VALID_FOR,
                replay_existing=True,
                recover_confirmed=recover_confirmed,
            )
        with self._lock:
            self._preparations[WholeScopeSemanticStage.EDITORIAL] = preparation
        return preparation

    def _reconcile_legacy_invalid_hierarchy(
        self,
        project: Project,
        repository: NarrativeMapRepository,
        service: NarrativeMapService,
        *,
        inputs: M15SemanticInputs | None = None,
    ) -> None:
        current_inputs = inputs if inputs is not None else load_m15_semantic_inputs(project)
        lost_quarantine_cas = False
        for _attempt in range(2):
            raw = repository.read_whole_scope_build()
            is_legacy_unfrozen = (
                raw is not None
                and raw.get("correction_id") == M15_SEMANTIC_CORRECTION_ID
                and raw.get("hierarchy_state") == "validated"
                and isinstance(raw.get("hierarchy_result"), Mapping)
                and raw.get("hierarchy_hash") is None
                and raw.get("authoritative_hierarchy") is None
                and raw.get("publication_hash") is None
                and raw.get("editorial_state") == "not_started"
            )
            if not is_legacy_unfrozen:
                if lost_quarantine_cas:
                    raise _LegacyHierarchyConcurrentUpdate
                return
            assert raw is not None
            if repository.read_whole_scope_current() is not None:
                raise _LegacyHierarchyConcurrentUpdate
            job, logical_jobs = _whole_scope_hierarchy_job(
                current_inputs,
                correction_id=M15_SEMANTIC_CORRECTION_ID,
            )
            expected_logical_jobs = [
                {
                    "stage": item.stage.value,
                    "logical_job_id": item.logical_job_id,
                    "subject_kind": item.subject_kind,
                    "subject_id": item.subject_id,
                    "membership_hash": item.membership_hash,
                }
                for item in logical_jobs
            ]
            expected_build_id = stable_m15_id(
                "whole_scope_build",
                {
                    "authority": job.authority.to_dict(),
                    "scope_id": job.subject_id,
                    "source_hash": current_inputs.source_hash,
                    "correction_id": M15_SEMANTIC_CORRECTION_ID,
                    "privacy_scope": M15_SEMANTIC_PRIVACY_SCOPE,
                    "profile": m15_provider_profile().to_dict(),
                    "hierarchy_transport_batch_id": job.job_id,
                },
            )
            record = repository.get(job.kind, job.job_id)
            if (
                record is None
                or record.status is not NarrativeJobStatus.VALIDATED
                or record.result is None
                or raw.get("build_id") != expected_build_id
                or raw.get("scope_id") != job.subject_id
                or raw.get("authority") != job.authority.to_dict()
                or raw.get("source_hash") != current_inputs.source_hash
                or raw.get("privacy_scope") != M15_SEMANTIC_PRIVACY_SCOPE
                or raw.get("hierarchy_transport_batch_id") != job.job_id
                or raw.get("hierarchy_logical_jobs") != expected_logical_jobs
                or raw.get("hierarchy_result") != record.result
                or raw.get("confirmed_hierarchy_manifest_id")
                != record.consent_manifest_id
            ):
                raise _LegacyHierarchyConcurrentUpdate
            validated, findings = _validate_hierarchy_for_current_authority(
                current_inputs,
                job,
                record.result,
                scope_id=job.subject_id,
                authority=job.authority,
            )
            if validated is not None:
                return
            error_code = (
                findings[0].code if findings else "hierarchy_authority_invalid"
            )
            if service.quarantine_invalid_whole_scope_hierarchy(
                job,
                m15_provider_profile(),
                error_code=error_code,
                logical_job_ids=tuple(item.logical_job_id for item in logical_jobs),
            ):
                return
            lost_quarantine_cas = True
        raise _LegacyHierarchyConcurrentUpdate

    def _legacy_reconciliation_stale_response(self) -> Mapping[str, object]:
        with self._lock:
            self._preparations.pop(WholeScopeSemanticStage.HIERARCHY, None)
            self._preparations.pop(WholeScopeSemanticStage.EDITORIAL, None)
        return whole_scope_stale_preparation_response(
            WholeScopeSemanticStage.HIERARCHY
        )

    def _execute(
        self,
        preparation: WholeScopeStagePreparation,
        *,
        operation: str,
    ) -> Mapping[str, object]:
        self._cancel_event.clear()
        with Project.open(self._project_path()) as project:
            repository = NarrativeMapRepository(project)
            service = NarrativeMapService(repository)
            inputs = self._current_inputs(preparation, project, repository, service)
            if inputs is None:
                return self._stale_preparation(
                    preparation.stage, preparation, service=service
                )
            status = service.whole_scope_semantic_status()
            prefix_state = (
                None
                if status is None
                else status.hierarchy_state
                if preparation.stage is WholeScopeSemanticStage.HIERARCHY
                else status.editorial_state
            )
            record = repository.get(preparation.job.kind, preparation.job.job_id)
            replay_only = bool(
                record is not None
                and record.status is NarrativeJobStatus.VALIDATED
                and prefix_state in {"validated", "frozen", "complete"}
            )
            consent = preparation.consent if replay_only else preparation.granted_consent()
            raw = repository.read_whole_scope_build()
            prefix = preparation.stage.value
            if operation in {"resume", "retry"} and (
                replay_only
                or prefix_state not in {"cancelled", "failed"}
                or raw is None
                or raw.get(f"confirmed_{prefix}_manifest_id") != consent.manifest_id
            ):
                return self._stale_preparation(
                    preparation.stage, preparation, service=service
                )
            if operation == "start" and not replay_only and prefix_state == "awaiting_consent":
                service.confirm_whole_scope_consent(preparation, consent)
            refreshed_inputs = self._current_inputs(preparation, project, repository, service)
            if refreshed_inputs is None:
                return self._stale_preparation(
                    preparation.stage, preparation, service=service
                )
            inputs = refreshed_inputs
            validated_hierarchies: dict[str, ValidatedWholeScopeHierarchy] = {}
            hierarchy_authority_validator: (
                Callable[
                    [PreparedNarrativeJob, Mapping[str, object]],
                    tuple[ValidationFinding, ...],
                ]
                | None
            ) = None
            if preparation.stage is WholeScopeSemanticStage.HIERARCHY:
                _scope_id, _payload, hard_locks = _whole_scope_hierarchy_input(inputs)

                def validate_current_hierarchy(
                    job: PreparedNarrativeJob,
                    result: Mapping[str, object],
                ) -> tuple[ValidationFinding, ...]:
                    validated, findings = _validate_hierarchy_for_current_authority(
                        inputs,
                        job,
                        result,
                        scope_id=preparation.scope_id,
                        authority=preparation.authority,
                        hard_locks=hard_locks,
                    )
                    if validated is None:
                        return findings
                    validated_hierarchies[canonical_hash(result)] = validated
                    return ()

                hierarchy_authority_validator = validate_current_hierarchy
            provider = None if replay_only else _LazyM15Provider(self._provider_factory)
            with self._lock:
                self._active_provider = provider
            try:
                if operation == "resume":
                    report = service.resume_whole_scope_semantic_build(
                        preparation,
                        provider=provider,
                        consent=consent,
                        cancelled=self._cancel_event.is_set,
                        hierarchy_authority_validator=hierarchy_authority_validator,
                    )
                elif operation == "retry":
                    report = service.retry_whole_scope_semantic_build(
                        preparation,
                        provider=provider,
                        consent=consent,
                        cancelled=self._cancel_event.is_set,
                        hierarchy_authority_validator=hierarchy_authority_validator,
                    )
                elif preparation.stage is WholeScopeSemanticStage.HIERARCHY:
                    report = service.start_whole_scope_hierarchy(
                        preparation,
                        provider=provider,
                        consent=consent,
                        cancelled=self._cancel_event.is_set,
                        authority_validator=hierarchy_authority_validator,
                    )
                else:
                    report = service.start_whole_scope_editorial(
                        preparation,
                        provider=provider,
                        consent=consent,
                        cancelled=self._cancel_event.is_set,
                    )
            finally:
                with self._lock:
                    if self._active_provider is provider:
                        self._active_provider = None
            if (
                preparation.stage is WholeScopeSemanticStage.HIERARCHY
                and preparation.job.job_id in report.validated_job_ids
            ):
                refreshed = service.whole_scope_semantic_status()
                if refreshed is not None and refreshed.hierarchy_state == "validated":
                    record = repository.get(preparation.job.kind, preparation.job.job_id)
                    if record is None or record.result is None:
                        raise ValueError("validated Stage H result is unavailable")
                    validated = validated_hierarchies.get(canonical_hash(record.result))
                    if validated is None:
                        return self._stale_preparation(
                            preparation.stage, preparation, service=service
                        )
                    service.freeze_whole_scope_hierarchy(
                        preparation,
                        validated,
                        _whole_scope_editorial_evidence_from_inputs(inputs),
                    )
            return whole_scope_status_response(service.whole_scope_semantic_status())

    def _current_inputs(
        self,
        preparation: WholeScopeStagePreparation,
        project: Project,
        repository: NarrativeMapRepository,
        service: NarrativeMapService,
    ) -> M15SemanticInputs | None:
        try:
            inputs = load_m15_semantic_inputs(project)
            if not _whole_scope_preparation_matches_current(
                preparation,
                inputs,
                repository,
                service,
            ):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        return inputs

    def _stale_preparation(
        self,
        stage: WholeScopeSemanticStage,
        preparation: WholeScopeStagePreparation | None,
        *,
        service: NarrativeMapService | None = None,
    ) -> Mapping[str, object]:
        with self._lock:
            if preparation is None or self._preparations.get(stage) is preparation:
                self._preparations.pop(stage, None)
        if service is None:
            with Project.open(self._project_path()) as project:
                NarrativeMapService(
                    NarrativeMapRepository(project)
                ).fence_stale_whole_scope_preparation(stage, preparation)
        else:
            service.fence_stale_whole_scope_preparation(stage, preparation)
        return whole_scope_stale_preparation_response(stage)

    def _status(self) -> Mapping[str, object]:
        with Project.open(self._project_path()) as project:
            repository = NarrativeMapRepository(project)
            service = NarrativeMapService(repository)
            self._reconcile_legacy_invalid_hierarchy(project, repository, service)
            status = service.whole_scope_semantic_status()
        return whole_scope_status_response(status)

    def _current_preparation(
        self,
    ) -> tuple[WholeScopeSemanticStage, WholeScopeStagePreparation | None]:
        with Project.open(self._project_path()) as project:
            repository = NarrativeMapRepository(project)
            service = NarrativeMapService(repository)
            self._reconcile_legacy_invalid_hierarchy(project, repository, service)
            status = service.whole_scope_semantic_status()
        if status is None:
            raise ValueError("no whole-scope semantic build is available")
        stage = (
            WholeScopeSemanticStage.EDITORIAL
            if status.editorial_state != "not_started"
            else WholeScopeSemanticStage.HIERARCHY
        )
        try:
            preparation = (
                self._prepare_editorial(recover_confirmed=True)
                if stage is WholeScopeSemanticStage.EDITORIAL
                else self._prepare_hierarchy(recover_confirmed=True)
            )
        except (KeyError, TypeError, ValueError):
            return stage, None
        return stage, preparation


def _whole_scope_preparation_matches_current(
    preparation: WholeScopeStagePreparation,
    inputs: M15SemanticInputs,
    repository: NarrativeMapRepository,
    service: NarrativeMapService,
) -> bool:
    authority = inputs.units[0].authority
    profile = m15_provider_profile()
    job = preparation.job
    raw = repository.read_whole_scope_build()
    if raw is None:
        return False
    common_matches = (
        preparation.authority == authority
        and preparation.source_hash == inputs.source_hash
        and preparation.correction_id == M15_WHOLE_SCOPE_CORRECTION_ID
        and preparation.privacy_scope == M15_SEMANTIC_PRIVACY_SCOPE
        and job.authority == authority
        and job.source_hash == inputs.source_hash
        and job.correction_id == M15_WHOLE_SCOPE_CORRECTION_ID
        and job.privacy_scope == M15_SEMANTIC_PRIVACY_SCOPE
        and job.story_facing is True
        and job.combined_submission_limit == MAXIMUM_DAY1_PROVIDER_SUBMISSIONS
        and raw.get("build_id") == preparation.build_id
        and raw.get("scope_id") == preparation.scope_id
        and raw.get("authority") == authority.to_dict()
        and raw.get("source_hash") == inputs.source_hash
        and raw.get("correction_id") == M15_WHOLE_SCOPE_CORRECTION_ID
        and raw.get("privacy_scope") == M15_SEMANTIC_PRIVACY_SCOPE
    )
    if not common_matches:
        return False

    logical_jobs: tuple[WholeScopeLogicalJob, ...]
    if preparation.stage is WholeScopeSemanticStage.HIERARCHY:
        scope_id, payload, _hard_locks = _whole_scope_hierarchy_input(inputs)
        ordered_unit_ids = tuple(item.unit_id for item in inputs.units)
        evidence_ids = tuple(
            dict.fromkeys(
                item.evidence_id
                for unit_id in ordered_unit_ids
                for item in inputs.evidence_by_unit[unit_id]
            )
        )
        characters = tuple(
            dict.fromkeys(speaker for item in inputs.units for speaker in item.speaker_ids)
        )
        logical_id = stable_m15_id(
            "whole_scope_hierarchy_logical_job",
            {
                "authority": authority.to_dict(),
                "scope_id": scope_id,
                "source_hash": inputs.source_hash,
                "correction_id": M15_WHOLE_SCOPE_CORRECTION_ID,
                "input_hash": canonical_hash(payload),
            },
        )
        logical_jobs = (
            WholeScopeLogicalJob(
                WholeScopeSemanticStage.HIERARCHY,
                logical_id,
                "scope",
                scope_id,
                None,
            ),
        )
        subject = WholeScopeProviderSubject(
            WholeScopeSemanticStage.HIERARCHY,
            scope_id,
            ordered_unit_ids,
        )
        job_matches = (
            preparation.scope_id == scope_id
            and preparation.hierarchy_hash is None
            and job.kind is ProviderJobKind.WHOLE_SCOPE_HIERARCHY
            and job.subject == subject
            and job.subject_id == scope_id
            and job.prompt_version == WHOLE_SCOPE_HIERARCHY_PROMPT_VERSION
            and job.response_schema == WHOLE_SCOPE_HIERARCHY_RESPONSE_SCHEMA
            and job.payload == payload
            and job.input_hash == canonical_hash(payload)
            and job.known_evidence_ids == evidence_ids
            and job.known_characters == characters
            and job.membership_hash is None
        )
    else:
        status = service.whole_scope_semantic_status()
        frozen = _reconstruct_frozen_editorial_authority(inputs, repository)
        if (
            status is None
            or status.authority != authority
            or status.source_hash != inputs.source_hash
            or status.correction_id != M15_WHOLE_SCOPE_CORRECTION_ID
            or status.scope_id != preparation.scope_id
            or status.hierarchy_state != "frozen"
            or status.hierarchy_hash != frozen.hierarchy_hash
        ):
            return False
        subjects = frozen.subjects
        evidence = list(frozen.evidence)
        payload = {
            "schema": M15_WHOLE_SCOPE_EDITORIAL_INPUT_SCHEMA,
            "scope_id": status.scope_id,
            "authority": status.authority.to_dict(),
            "hierarchy_hash": status.hierarchy_hash,
            "subjects": [item.to_dict() for item in subjects],
            "evidence": evidence,
        }
        logical_jobs = tuple(
            WholeScopeLogicalJob(
                WholeScopeSemanticStage.EDITORIAL,
                stable_m15_id(
                    "whole_scope_editorial_logical_job",
                    {
                        "authority": authority.to_dict(),
                        "scope_id": status.scope_id,
                        "hierarchy_hash": status.hierarchy_hash,
                        "subject": item.to_dict(),
                        "source_hash": inputs.source_hash,
                        "correction_id": M15_WHOLE_SCOPE_CORRECTION_ID,
                    },
                ),
                item.subject_kind,
                item.subject_id,
                item.membership_hash,
            )
            for item in subjects
        )
        subject = WholeScopeProviderSubject(
            WholeScopeSemanticStage.EDITORIAL,
            status.scope_id,
            hierarchy_hash=status.hierarchy_hash,
            editorial_subjects=subjects,
        )
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id for item in subjects for evidence_id in item.evidence_ids
            )
        )
        characters = tuple(
            dict.fromkeys(
                character for item in subjects for character in item.known_characters
            )
        )
        job_matches = (
            preparation.hierarchy_hash == status.hierarchy_hash
            and job.kind is ProviderJobKind.WHOLE_SCOPE_EDITORIAL
            and job.subject == subject
            and job.subject_id == status.scope_id
            and job.prompt_version == WHOLE_SCOPE_EDITORIAL_PROMPT_VERSION
            and job.response_schema == WHOLE_SCOPE_EDITORIAL_RESPONSE_SCHEMA
            and job.payload == payload
            and job.input_hash == canonical_hash(payload)
            and job.known_evidence_ids == evidence_ids
            and job.known_characters == characters
            and job.membership_hash == status.hierarchy_hash
            and raw.get("hierarchy_hash") == status.hierarchy_hash
            and raw.get("authoritative_hierarchy") == frozen.hierarchy_payload
            and raw.get("frozen_editorial_subjects")
            == [item.to_dict() for item in subjects]
            and raw.get("frozen_editorial_evidence_hash") == canonical_hash(evidence)
        )
    if not job_matches or preparation.logical_jobs != logical_jobs:
        return False
    prefix = preparation.stage.value
    hierarchy_transport_batch_id = (
        job.job_id
        if preparation.stage is WholeScopeSemanticStage.HIERARCHY
        else raw.get("hierarchy_transport_batch_id")
    )
    if not isinstance(hierarchy_transport_batch_id, str):
        return False
    expected_build_id = stable_m15_id(
        "whole_scope_build",
        {
            "authority": authority.to_dict(),
            "scope_id": preparation.scope_id,
            "source_hash": inputs.source_hash,
            "correction_id": M15_WHOLE_SCOPE_CORRECTION_ID,
            "privacy_scope": M15_SEMANTIC_PRIVACY_SCOPE,
            "profile": profile.to_dict(),
            "hierarchy_transport_batch_id": hierarchy_transport_batch_id,
        },
    )
    expected_logical_jobs = [
        {
            "stage": item.stage.value,
            "logical_job_id": item.logical_job_id,
            "subject_kind": item.subject_kind,
            "subject_id": item.subject_id,
            "membership_hash": item.membership_hash,
        }
        for item in logical_jobs
    ]
    try:
        job.validate_integrity()
        preparation.granted_consent().validate_for((job,), profile)
    except ValueError:
        return False
    return (
        preparation.build_id == expected_build_id
        and raw.get("build_id") == expected_build_id
        and job.logical_job_ids == tuple(item.logical_job_id for item in logical_jobs)
        and raw.get(f"{prefix}_transport_batch_id") == job.job_id
        and raw.get(f"{prefix}_logical_jobs") == expected_logical_jobs
        and raw.get(f"{prefix}_manifest_id") == preparation.consent.manifest_id
        and raw.get(f"{prefix}_manifest") == preparation.consent.identity_dict()
        and raw.get(f"{prefix}_profile") == profile.to_dict()
    )


def whole_scope_preparation_response(
    preparation: WholeScopeStagePreparation,
) -> dict[str, object]:
    consent = preparation.consent
    settings = consent.profile.settings.to_dict()
    manifest = {
        "manifest_id": consent.manifest_id,
        "stage": preparation.stage.value,
        "expires_at": consent.expires_utc,
        "source_hash": preparation.source_hash,
        "authority_hash": canonical_hash(preparation.authority.to_dict()),
        "correction_hash": canonical_hash({"correction_id": preparation.correction_id}),
        "prompt_hash": canonical_hash(
            {
                "prompt_version": preparation.job.prompt_version,
                "repair_policy_version": consent.repair_policy_version,
            }
        ),
        "schema_hash": canonical_hash({"response_schema": preparation.job.response_schema}),
        "membership_hash": preparation.hierarchy_hash,
        "input_hash": consent.job_identity_hash,
        "privacy_scope": preparation.privacy_scope,
        "provider": {
            "provider": consent.profile.provider,
            "adapter": consent.profile.adapter,
            "adapter_version": consent.profile.adapter_version,
            "requested_model": consent.profile.requested_model,
            "resolved_model": consent.profile.requested_model,
            "settings": {
                "model_reasoning_effort": settings.get("reasoning_effort"),
                "fast_mode": settings.get("fast_mode"),
            },
        },
        "job_count": len(preparation.logical_jobs),
        "limits": {
            "max_provider_calls": consent.maximum_provider_calls,
            "max_input_bytes": consent.maximum_input_bytes,
            "max_output_bytes": consent.maximum_output_bytes,
            "timeout_seconds": consent.timeout_seconds,
            "max_concurrency": 1,
        },
    }
    stage_name = preparation.stage.value
    return {
        "schema": M15_SEMANTIC_RESPONSE_SCHEMA,
        "state": f"awaiting_{stage_name}_consent",
        "stage": stage_name,
        "build_id": preparation.build_id,
        "manifest_id": consent.manifest_id,
        "consent_id": consent.manifest_id,
        "requires_confirmation": True,
        "replay_only": False,
        "manifest": manifest,
        **manifest,
        "progress": {"logical_jobs": len(preparation.logical_jobs), "completed": 0},
        "accounting": _whole_scope_empty_accounting(),
        "publication_hash": None,
    }


def whole_scope_stale_preparation_response(
    stage: WholeScopeSemanticStage,
) -> dict[str, object]:
    """Return a sanitized zero-submit result that requires a fresh exact preview."""

    return {
        "schema": M15_SEMANTIC_RESPONSE_SCHEMA,
        "state": "stale",
        "stage": stage.value,
        "build_id": None,
        "manifest_id": None,
        "requires_confirmation": False,
        "requires_fresh_preparation": True,
        "next_action": f"prepare_{stage.value}",
        "progress": {
            "logical_jobs": 0,
            "completed": 0,
            "failure_codes": ["m15_preparation_stale"],
        },
        "failure_codes": ["m15_preparation_stale"],
        "accounting": _whole_scope_empty_accounting(),
        "publication_hash": None,
    }


def whole_scope_status_response(status: object) -> dict[str, object]:
    from renpy_story_mapper.narrative_map.semantic_lifecycle import WholeScopeSemanticStatus

    if not isinstance(status, WholeScopeSemanticStatus):
        return {
            "schema": M15_SEMANTIC_RESPONSE_SCHEMA,
            "state": "not_started",
            "stage": None,
            "build_id": None,
            "manifest_id": None,
            "requires_confirmation": False,
            "progress": {"logical_jobs": 0, "completed": 0},
            "accounting": _whole_scope_empty_accounting(),
            "publication_hash": None,
        }
    if status.editorial_state != "not_started":
        stage = "editorial"
        raw_state = status.editorial_state
    else:
        stage = "hierarchy"
        raw_state = status.hierarchy_state
    if raw_state in {"awaiting_consent", "awaiting_start"}:
        state = f"awaiting_{stage}_consent"
    elif raw_state == "running":
        state = f"{stage}_running"
    elif stage == "hierarchy" and raw_state == "frozen":
        state = "hierarchy_frozen"
    elif stage == "editorial" and raw_state == "complete":
        state = "complete"
    else:
        state = raw_state
    accounting = status.accounting
    return {
        "schema": M15_SEMANTIC_RESPONSE_SCHEMA,
        "state": state,
        "stage": stage,
        "build_id": status.build_id,
        "manifest_id": None,
        "requires_confirmation": raw_state == "awaiting_consent",
        "progress": {
            "logical_jobs": accounting.logical_jobs,
            "completed": (
                accounting.logical_jobs if state in {"hierarchy_frozen", "complete"} else 0
            ),
            "failure_codes": list(status.failure_codes),
        },
        "accounting": {
            "provider_calls": accounting.transport_submissions,
            "reserved_provider_calls": accounting.combined_submission_count,
            "input_tokens": accounting.input_tokens,
            "output_tokens": accounting.output_tokens,
            "elapsed_ms": accounting.elapsed_ms,
            "cache_hits": accounting.cache_hits,
        },
        "hierarchy_hash": status.hierarchy_hash,
        "publication_hash": status.publication_hash,
    }


def _whole_scope_empty_accounting() -> dict[str, int]:
    return {
        "provider_calls": 0,
        "reserved_provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "elapsed_ms": 0,
        "cache_hits": 0,
    }


def _whole_scope_hierarchy_input(
    inputs: M15SemanticInputs,
) -> tuple[str, dict[str, object], tuple[HierarchyHardLock, ...]]:
    authority = inputs.units[0].authority
    ordered_unit_ids = tuple(item.unit_id for item in inputs.units)
    scope_id = stable_m15_id(
        "whole_scope",
        {"authority": authority.to_dict(), "ordered_unit_ids": list(ordered_unit_ids)},
    )
    arms_by_choice: dict[str, list[str]] = {}
    for unit in inputs.units:
        if unit.parent_choice_id is not None and unit.parent_arm_id is not None:
            arms = arms_by_choice.setdefault(unit.parent_choice_id, [])
            if unit.parent_arm_id not in arms:
                arms.append(unit.parent_arm_id)
    hard_locks = tuple(
        HierarchyHardLock(
            stable_m15_id(
                "whole_scope_choice_lock",
                {"choice_id": choice_id, "arm_ids": arm_ids},
            ),
            HierarchyHardLockKind.CHOICE_OWNERSHIP,
            choice_id=choice_id,
            arm_ids=tuple(arm_ids),
        )
        for choice_id, arm_ids in arms_by_choice.items()
    )
    payload = whole_scope_hierarchy_input_payload(
        authority,
        scope_id,
        inputs.units,
        inputs.evidence_by_unit,
        hard_locks,
    )
    return scope_id, payload, hard_locks


def _validate_hierarchy_for_current_authority(
    inputs: M15SemanticInputs,
    job: PreparedNarrativeJob,
    result: Mapping[str, object],
    *,
    scope_id: str,
    authority: AuthorityBinding,
    hard_locks: Sequence[HierarchyHardLock] | None = None,
) -> tuple[ValidatedWholeScopeHierarchy | None, tuple[ValidationFinding, ...]]:
    parsed = validate_whole_scope_hierarchy_response(result, job)
    if parsed.proposal is None or not parsed.valid:
        return None, parsed.findings
    locks = (
        tuple(hard_locks)
        if hard_locks is not None
        else _whole_scope_hierarchy_input(inputs)[2]
    )
    try:
        validated = validate_whole_scope_hierarchy_from_authority(
            inputs.canonical,
            inputs.scene_model,
            parsed.proposal,
            locks,
            scope_id=scope_id,
            authority=authority,
        )
    except ValueError as exc:
        code = (
            "hierarchy_not_representable"
            if "representable" in str(exc)
            else "hierarchy_authority_invalid"
        )
        return None, (ValidationFinding(code, job.job_id),)
    return validated, ()


def _whole_scope_hierarchy_job(
    inputs: M15SemanticInputs,
    *,
    correction_id: str = M15_WHOLE_SCOPE_CORRECTION_ID,
) -> tuple[PreparedNarrativeJob, tuple[WholeScopeLogicalJob, ...]]:
    authority = inputs.units[0].authority
    scope_id, payload, _hard_locks = _whole_scope_hierarchy_input(inputs)
    ordered_unit_ids = tuple(item.unit_id for item in inputs.units)
    evidence_ids = tuple(
        dict.fromkeys(
            item.evidence_id
            for unit_id in ordered_unit_ids
            for item in inputs.evidence_by_unit[unit_id]
        )
    )
    characters = tuple(
        dict.fromkeys(speaker for item in inputs.units for speaker in item.speaker_ids)
    )
    logical_id = stable_m15_id(
        "whole_scope_hierarchy_logical_job",
        {
            "authority": authority.to_dict(),
            "scope_id": scope_id,
            "source_hash": inputs.source_hash,
            "correction_id": correction_id,
            "input_hash": canonical_hash(payload),
        },
    )
    logical_jobs = (
        WholeScopeLogicalJob(
            WholeScopeSemanticStage.HIERARCHY,
            logical_id,
            "scope",
            scope_id,
            None,
        ),
    )
    return (
        PreparedNarrativeJob(
            kind=ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
            authority=authority,
            subject=WholeScopeProviderSubject(
                WholeScopeSemanticStage.HIERARCHY,
                scope_id,
                ordered_unit_ids,
            ),
            subject_id=scope_id,
            input_hash=canonical_hash(payload),
            prompt_version=WHOLE_SCOPE_HIERARCHY_PROMPT_VERSION,
            response_schema=WHOLE_SCOPE_HIERARCHY_RESPONSE_SCHEMA,
            payload=cast(dict[str, JsonValue], payload),
            known_evidence_ids=evidence_ids,
            known_characters=characters,
            source_hash=inputs.source_hash,
            correction_id=correction_id,
            privacy_scope=M15_SEMANTIC_PRIVACY_SCOPE,
            logical_job_ids=(logical_id,),
            combined_submission_limit=MAXIMUM_DAY1_PROVIDER_SUBMISSIONS,
        ),
        logical_jobs,
    )


def _reconstruct_frozen_editorial_authority(
    inputs: M15SemanticInputs,
    repository: NarrativeMapRepository,
) -> _FrozenEditorialAuthority:
    raw = repository.read_whole_scope_build()
    if raw is None or raw.get("hierarchy_state") != "frozen":
        raise ValueError("Stage E requires a frozen Stage H build")
    hierarchy_job, logical_jobs = _whole_scope_hierarchy_job(inputs)
    record = repository.get(ProviderJobKind.WHOLE_SCOPE_HIERARCHY, hierarchy_job.job_id)
    if (
        record is None
        or record.status is not NarrativeJobStatus.VALIDATED
        or record.result is None
        or record.input_hash != hierarchy_job.input_hash
        or record.subject_id != hierarchy_job.subject_id
        or record.prompt_version != hierarchy_job.prompt_version
        or record.response_schema != hierarchy_job.response_schema
        or record.authority_hash != hierarchy_job.authority.identity
        or record.profile_hash != canonical_hash(m15_provider_profile().to_dict())
        or record.consent_manifest_id != raw.get("confirmed_hierarchy_manifest_id")
        or raw.get("hierarchy_result") != record.result
    ):
        raise ValueError("sealed Stage H result is unavailable or stale")
    hierarchy_result = record.result
    expected_logical_jobs = [
        {
            "stage": item.stage.value,
            "logical_job_id": item.logical_job_id,
            "subject_kind": item.subject_kind,
            "subject_id": item.subject_id,
            "membership_hash": item.membership_hash,
        }
        for item in logical_jobs
    ]
    if (
        raw.get("scope_id") != hierarchy_job.subject_id
        or raw.get("authority") != hierarchy_job.authority.to_dict()
        or raw.get("source_hash") != inputs.source_hash
        or raw.get("correction_id") != M15_WHOLE_SCOPE_CORRECTION_ID
        or raw.get("privacy_scope") != M15_SEMANTIC_PRIVACY_SCOPE
        or raw.get("hierarchy_transport_batch_id") != hierarchy_job.job_id
        or raw.get("hierarchy_logical_jobs") != expected_logical_jobs
    ):
        raise ValueError("sealed Stage H identity is stale for current authority")
    parsed = validate_whole_scope_hierarchy_response(hierarchy_result, hierarchy_job)
    if parsed.proposal is None or not parsed.valid:
        raise ValueError("sealed Stage H result cannot be reconstructed")
    scope_id, _payload, hard_locks = _whole_scope_hierarchy_input(inputs)
    validated = validate_whole_scope_hierarchy_from_authority(
        inputs.canonical,
        inputs.scene_model,
        parsed.proposal,
        hard_locks,
        scope_id=scope_id,
        authority=hierarchy_job.authority,
    )
    outline = assemble_semantic_outline(
        validated.units,
        validated.candidates,
        compile_hierarchy_to_gap_decisions(validated),
        choices=validated.choices,
    )
    hierarchy_payload = semantic_outline_payload(outline)
    hierarchy_hash = semantic_outline_hash(outline)
    subjects, evidence = derive_frozen_editorial_authority(
        outline,
        validated.units,
        _whole_scope_editorial_evidence_from_inputs(inputs),
        hierarchy_hash,
    )
    if (
        raw.get("hierarchy_hash") != hierarchy_hash
        or raw.get("authoritative_hierarchy") != hierarchy_payload
        or raw.get("frozen_editorial_subjects")
        != [item.to_dict() for item in subjects]
        or raw.get("frozen_editorial_evidence_hash") != canonical_hash(evidence)
    ):
        raise ValueError("frozen Stage E authority is stale or non-canonical")
    return _FrozenEditorialAuthority(
        hierarchy_hash,
        hierarchy_payload,
        subjects,
        tuple(evidence),
    )


def _whole_scope_editorial_evidence_from_inputs(
    inputs: M15SemanticInputs,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    seen: dict[str, str] = {}
    for unit_id in tuple(item.unit_id for item in inputs.units):
        for item in inputs.evidence_by_unit[unit_id]:
            previous = seen.get(item.evidence_id)
            if previous is not None:
                if previous != item.text:
                    raise ValueError("current evidence identity resolves to conflicting text")
                continue
            seen[item.evidence_id] = item.text
            values.append({"evidence_id": item.evidence_id, "text": item.text})
    return values


def load_m15_semantic_inputs(project: Project) -> M15SemanticInputs:
    """Build deterministic semantic inputs from the exact current M10/M11 pair."""

    current = load_m15_semantic_authority(project)
    canonical = current.canonical
    scene_model = current.scene_model
    units = build_fine_narrative_units(canonical, scene_model)
    candidates = build_all_eligible_gap_candidates(units)
    windows = build_boundary_windows(units, candidates)
    evidence_by_unit = _semantic_evidence(canonical, scene_model, units)
    if not units or not candidates or not windows:
        raise ValueError("the current project has no eligible semantic boundary work")
    return M15SemanticInputs(
        canonical,
        scene_model,
        units,
        candidates,
        windows,
        evidence_by_unit,
    )


def load_m15_semantic_authority(project: Project) -> M15SemanticAuthority:
    """Load and bind current M10/M11 authority without constructing semantic work."""

    raw_state = project.payload("m10_analysis_state", "authoritative")
    raw_canonical = project.payload("m10_canonical_graph", "authoritative")
    if not isinstance(raw_state, Mapping) or not isinstance(raw_canonical, Mapping):
        raise ValueError("the project has no current M10 authority")
    canonical = canonical_graph_from_mapping(raw_canonical)
    if (
        raw_state.get("canonical_availability") != "current_complete"
        or raw_state.get("source_generation") != canonical.source_generation
        or raw_state.get("canonical_generation") != canonical.source_generation
        or raw_state.get("canonical_hash") != canonical.authority_hash
    ):
        raise ValueError("the project M10 authority is not current")
    selection = project.m11_persistence().select_current(
        source_generation=canonical.source_generation,
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=canonical.authority_hash,
    )
    if (
        selection.availability is not M11Availability.CURRENT_COMPLETE
        or selection.phase_results is None
    ):
        raise ValueError("the project has no current M11 SceneModel")
    scene_model = scene_model_from_stored_results(selection.phase_results)
    bind_m15_authority(canonical, scene_model)
    return M15SemanticAuthority(canonical, scene_model)


def prepare_boundaries(
    service: NarrativeMapService,
    inputs: M15SemanticInputs,
    *,
    run_id: str,
    replay_existing: bool,
) -> SemanticStagePreparation:
    return service.prepare_boundaries(
        inputs.units,
        inputs.candidates,
        inputs.windows,
        inputs.evidence_by_unit,
        profile=m15_provider_profile(),
        run_id=run_id,
        source_hash=inputs.source_hash,
        correction_id=M15_SEMANTIC_CORRECTION_ID,
        privacy_scope=M15_SEMANTIC_PRIVACY_SCOPE,
        valid_for=M15_SEMANTIC_CONSENT_VALID_FOR,
        replay_existing=replay_existing,
    )


def prepare_summaries(
    service: NarrativeMapService,
    inputs: M15SemanticInputs,
    *,
    run_id: str,
    replay_existing: bool,
) -> SemanticStagePreparation:
    boundary = prepare_boundaries(
        service,
        inputs,
        run_id=f"{run_id}-boundary-reconstruction",
        replay_existing=True,
    )
    output = service.semantic_boundary_output(boundary)
    _units, _candidates, outline = assemble_semantic_outline_from_authority(
        inputs.canonical,
        inputs.scene_model,
        output.decisions,
        boundary_windows=inputs.windows,
        boundary_provenance=output.provenance,
    )
    summary_inputs = build_frozen_summary_inputs(outline, inputs.units)
    quotient_topology = build_semantic_quotient_topology(
        inputs.canonical,
        inputs.units,
        outline,
    ).to_dict()
    return service.prepare_summaries(
        outline,
        summary_inputs.inputs,
        inputs.evidence_by_unit,
        quotient_topology=quotient_topology,
        profile=m15_provider_profile(),
        run_id=run_id,
        source_hash=inputs.source_hash,
        correction_id=M15_SEMANTIC_CORRECTION_ID,
        privacy_scope=M15_SEMANTIC_PRIVACY_SCOPE,
        valid_for=M15_SEMANTIC_CONSENT_VALID_FOR,
        replay_existing=replay_existing,
    )


def freeze_boundary_membership(
    service: NarrativeMapService,
    inputs: M15SemanticInputs,
    preparation: SemanticStagePreparation,
) -> SemanticStatusView:
    """Assemble and freeze deterministic membership/topology after boundary validation."""

    output = service.semantic_boundary_output(preparation)
    _units, _candidates, outline = assemble_semantic_outline_from_authority(
        inputs.canonical,
        inputs.scene_model,
        output.decisions,
        boundary_windows=inputs.windows,
        boundary_provenance=output.provenance,
    )
    quotient_topology = build_semantic_quotient_topology(
        inputs.canonical,
        inputs.units,
        outline,
    ).to_dict()
    return service.freeze_semantic_membership(preparation, outline, quotient_topology)


def recover_confirmed_semantic_run(project: Project) -> RecoveredSemanticRun:
    """Rebuild one exact, durably confirmed active stage after a web-process reopen."""

    repository = NarrativeMapRepository(project)
    raw = repository.read_semantic_build()
    if raw is None:
        raise ValueError("no semantic build is available for recovery")
    has_summaries = bool(raw.get("summary_manifest_id")) and bool(raw.get("summary_job_ids"))
    stage = SemanticStage.SUMMARIES if has_summaries else SemanticStage.BOUNDARIES
    prefix = "summary" if stage is SemanticStage.SUMMARIES else "boundary"
    manifest_id = raw.get(f"{prefix}_manifest_id")
    manifest = raw.get(f"{prefix}_manifest")
    confirmed = raw.get("confirmed_manifest_ids")
    if (
        not isinstance(manifest_id, str)
        or not isinstance(manifest, Mapping)
        or not isinstance(confirmed, list)
        or not all(isinstance(item, str) for item in confirmed)
        or manifest_id not in confirmed
    ):
        raise ValueError("the active semantic stage has no durable consent acknowledgement")
    expires_utc = manifest.get("expires_utc")
    run_id = manifest.get("run_id")
    if not isinstance(expires_utc, str) or not isinstance(run_id, str):
        raise ValueError("the active semantic consent identity is invalid")
    expires = datetime.fromisoformat(expires_utc)
    if expires.tzinfo is None or expires <= datetime.now(UTC):
        raise ValueError("the active semantic consent has expired")
    inputs = load_m15_semantic_inputs(project)
    service = NarrativeMapService(repository)
    preparation = (
        prepare_summaries(
            service,
            inputs,
            run_id=run_id,
            replay_existing=True,
        )
        if stage is SemanticStage.SUMMARIES
        else prepare_boundaries(
            service,
            inputs,
            run_id=run_id,
            replay_existing=True,
        )
    )
    if preparation.consent.manifest_id != manifest_id:
        raise ValueError("the reconstructed semantic preparation is not the confirmed manifest")
    replay_only = preparation_is_exact_replay(repository, preparation)
    consent = preparation.consent if replay_only else preparation.granted_consent()
    if not replay_only:
        consent.validate_for(preparation.jobs, m15_provider_profile())
    return RecoveredSemanticRun(preparation, consent, replay_only)


def build_frozen_summary_inputs(
    outline: SemanticOutline,
    units: Sequence[FineNarrativeUnit],
) -> M15SummaryInputs:
    """Cover each visible frozen subject exactly once in provider job order."""

    unit_by_id = {item.unit_id: item for item in units}
    beat_by_id = {item.beat_id: item for item in outline.beats}
    choice_by_id = {item.choice_id: item for item in outline.choices}

    def cluster_units(cluster_id: str) -> tuple[str, ...]:
        cluster = next(item for item in outline.clusters if item.cluster_id == cluster_id)
        return tuple(
            unit_id
            for beat_id in cluster.ordered_beat_ids
            for unit_id in beat_by_id[beat_id].ordered_unit_ids
        )

    def choice_units(choice_id: str) -> tuple[str, ...]:
        owned: set[str] = set()
        visiting: set[str] = set()

        def collect(current_id: str) -> None:
            if current_id in visiting:
                raise ValueError("choice summary membership contains a cycle")
            if current_id in owned:
                return
            current = choice_by_id.get(current_id)
            if current is None:
                raise ValueError("choice summary references an unknown choice")
            visiting.add(current_id)
            for child_id in current.child_choice_ids:
                collect(child_id)
            visiting.remove(current_id)
            owned.add(current_id)

        collect(choice_id)
        selected = {
            unit_id
            for beat in outline.beats
            if beat.parent_choice_id in owned
            for unit_id in beat.ordered_unit_ids
        }
        ordered = tuple(item for item in outline.ordered_unit_ids if item in selected)
        if not ordered or len(ordered) != len(selected):
            raise ValueError("choice summary has invalid frozen membership")
        return ordered

    subjects: list[tuple[str, str, tuple[str, ...]]] = [
        *(("beat", item.beat_id, item.ordered_unit_ids) for item in outline.beats),
        *(
            ("major_cluster", item.cluster_id, cluster_units(item.cluster_id))
            for item in outline.clusters
        ),
        *(("choice", item.choice_id, choice_units(item.choice_id)) for item in outline.choices),
    ]
    frozen: list[FrozenSummaryInput] = []
    for subject_kind, subject_id, ordered_unit_ids in subjects:
        selected_units = tuple(unit_by_id[item] for item in ordered_unit_ids)
        evidence_ids = _ordered_unique(
            evidence_id for unit in selected_units for evidence_id in unit.evidence_ids
        )
        characters = _ordered_unique(
            speaker for unit in selected_units for speaker in unit.speaker_ids
        )
        frozen.append(
            FrozenSummaryInput(
                subject_kind,
                subject_id,
                ordered_unit_ids,
                evidence_ids,
                characters,
            )
        )
    return M15SummaryInputs(outline, tuple(frozen))


def preparation_is_exact_replay(
    repository: NarrativeMapRepository,
    preparation: SemanticStagePreparation,
) -> bool:
    """Conservatively identify a complete exact cache replay without source payload reads."""

    profile = preparation.consent.profile
    identity_prefix: dict[str, object] = {
        "provider": profile.provider,
        "adapter_version": f"{profile.adapter}:{profile.adapter_version}",
        "requested_model": profile.requested_model,
        "resolved_model": profile.requested_model,
        "settings_hash": profile.settings_hash,
    }
    for job in preparation.jobs:
        record = repository.get(job.kind, job.job_id)
        expected = {
            **identity_prefix,
            "prompt_version": job.prompt_version,
            "response_schema": job.response_schema,
            "input_hash": job.input_hash,
        }
        if (
            record is None
            or record.status is not NarrativeJobStatus.VALIDATED
            or record.result is None
            or record.consent_manifest_id is None
            or record.provider_identity != expected
        ):
            return False
    return True


def no_submit_provider() -> NarrativeMapProvider:
    return _NoSubmitProvider()


def preparation_response(
    preparation: SemanticStagePreparation,
    *,
    replay_only: bool,
) -> dict[str, object]:
    state = (
        "awaiting_boundary_consent"
        if preparation.stage is SemanticStage.BOUNDARIES
        else "awaiting_summary_consent"
    )
    manifest = _safe_manifest(preparation)
    return {
        "schema": M15_SEMANTIC_RESPONSE_SCHEMA,
        "state": state,
        "stage": preparation.stage.value,
        "build_id": preparation.build_id,
        "manifest_id": preparation.consent.manifest_id,
        "requires_confirmation": not replay_only,
        "replay_only": replay_only,
        "manifest": manifest,
        "progress": _empty_progress(preparation),
        "accounting": _empty_accounting(),
        "publication_hash": None,
    }


def semantic_status_response(
    status: SemanticStatusView | None,
    *,
    active_stage: SemanticStage | None = None,
) -> dict[str, object]:
    if status is None:
        return {
            "schema": M15_SEMANTIC_RESPONSE_SCHEMA,
            "state": "not_started",
            "stage": None,
            "build_id": None,
            "manifest_id": None,
            "requires_confirmation": False,
            "replay_only": False,
            "manifest": None,
            "progress": {
                "boundary_jobs": {"total": 0, "completed": 0},
                "summary_jobs": {"total": 0, "completed": 0},
                "failure_codes": [],
            },
            "accounting": _empty_accounting(),
            "publication_hash": None,
        }
    state = status.record.state.value
    if active_stage is SemanticStage.BOUNDARIES:
        state = "boundaries_running"
    elif active_stage is SemanticStage.SUMMARIES:
        state = "summaries_running"
    stage = _status_stage(status, active_stage)
    manifest_id = (
        status.record.summary_manifest_id
        if stage == SemanticStage.SUMMARIES.value
        else status.record.boundary_manifest_id
    )
    return {
        "schema": M15_SEMANTIC_RESPONSE_SCHEMA,
        "state": state,
        "stage": stage,
        "build_id": status.build_id,
        "manifest_id": manifest_id,
        "requires_confirmation": state
        in {"awaiting_boundary_consent", "awaiting_summary_consent"},
        "replay_only": False,
        "manifest": None,
        "progress": {
            "boundary_jobs": {
                "total": len(status.boundary_job_ids),
                "completed": len(status.record.completed_boundary_job_ids),
            },
            "summary_jobs": {
                "total": len(status.summary_job_ids),
                "completed": len(status.record.completed_summary_job_ids),
            },
            "failure_codes": list(status.record.failure_codes),
        },
        "accounting": {
            "provider_calls": status.accounting.provider_calls,
            "reserved_provider_calls": status.accounting.reserved_provider_calls,
            "input_tokens": status.accounting.input_tokens,
            "output_tokens": status.accounting.output_tokens,
            "elapsed_ms": status.accounting.elapsed_ms,
            "cache_hits": status.accounting.cache_hits,
        },
        "publication_hash": status.current_publication_hash,
    }


def _safe_manifest(preparation: SemanticStagePreparation) -> dict[str, object]:
    consent = preparation.consent
    prompt_hash = canonical_hash(
        [[item.job_id, item.prompt_version] for item in preparation.jobs]
    )
    if consent.repair_policy_version is not None:
        prompt_hash = canonical_hash(
            {
                "base_prompt_hash": prompt_hash,
                "repair_policy_version": consent.repair_policy_version,
            }
        )
    schema_hash = canonical_hash(
        [[item.job_id, item.response_schema] for item in preparation.jobs]
    )
    scope_hash = canonical_hash([item.job_id for item in preparation.jobs])
    settings = consent.profile.settings.to_dict()
    maximum_input_tokens = getattr(consent, "maximum_input_tokens", None)
    maximum_output_tokens = getattr(consent, "maximum_output_tokens", None)
    maximum_total_tokens = getattr(consent, "maximum_total_tokens", None)
    maximum_concurrency = getattr(
        consent,
        "maximum_concurrency",
        M15_SEMANTIC_MAXIMUM_CONCURRENCY,
    )
    return {
        "schema": "m15-semantic-consent-preview-v1",
        "manifest_id": consent.manifest_id,
        "stage": preparation.stage.value,
        "issued_at": consent.issued_utc,
        "expires_at": consent.expires_utc,
        "source_hash": preparation.source_hash,
        "authority_hash": canonical_hash(preparation.authority.to_dict()),
        "correction_hash": canonical_hash({"correction_id": preparation.correction_id}),
        "prompt_hash": prompt_hash,
        "repair_policy_version": consent.repair_policy_version,
        "schema_hash": schema_hash,
        "membership_hash": preparation.membership_hash,
        "scope_hash": scope_hash,
        "input_hash": consent.job_identity_hash,
        "privacy_scope": preparation.privacy_scope,
        "provider": {
            "provider": consent.profile.provider,
            "adapter": consent.profile.adapter,
            "adapter_version": consent.profile.adapter_version,
            "requested_model": consent.profile.requested_model,
            "resolved_model": consent.profile.requested_model,
            "settings": {
                "model_reasoning_effort": settings.get("reasoning_effort"),
                "fast_mode": settings.get("fast_mode"),
            },
        },
        "job_count": len(preparation.jobs),
        "job_ids": [item.job_id for item in preparation.jobs],
        "limits": {
            "max_provider_calls": consent.maximum_provider_calls,
            "max_input_bytes": consent.maximum_input_bytes,
            "max_output_bytes": consent.maximum_output_bytes,
            "max_input_tokens": maximum_input_tokens,
            "max_output_tokens": maximum_output_tokens,
            "max_total_tokens": maximum_total_tokens,
            "timeout_seconds": consent.timeout_seconds,
            "max_concurrency": maximum_concurrency,
        },
    }


def _empty_progress(preparation: SemanticStagePreparation) -> dict[str, object]:
    boundary = len(preparation.jobs) if preparation.stage is SemanticStage.BOUNDARIES else 0
    summaries = len(preparation.jobs) if preparation.stage is SemanticStage.SUMMARIES else 0
    return {
        "boundary_jobs": {"total": boundary, "completed": 0},
        "summary_jobs": {"total": summaries, "completed": 0},
        "failure_codes": [],
    }


def _empty_accounting() -> dict[str, int]:
    return {
        "provider_calls": 0,
        "reserved_provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "elapsed_ms": 0,
        "cache_hits": 0,
    }


def _status_stage(
    status: SemanticStatusView,
    active_stage: SemanticStage | None,
) -> str | None:
    if active_stage is not None:
        return active_stage.value
    state = status.record.state.value
    if state.startswith("boundar") or state in {"membership_frozen"}:
        return "boundaries"
    if state.startswith("summar") or state in {"validating", "complete", "partial"}:
        return "summaries"
    if state in {"cancelled", "failed"}:
        return (
            "summaries"
            if status.record.summary_manifest_id is not None
            else "boundaries"
        )
    return None


def _semantic_evidence(
    canonical: CanonicalGraph,
    scene_model: SceneModel,
    units: Sequence[FineNarrativeUnit],
) -> dict[str, tuple[SemanticEvidenceRecord, ...]]:
    evidence_by_id = {item.id: item for item in canonical.evidence}
    atom_by_id = {item.id: item for item in scene_model.atoms}
    result: dict[str, tuple[SemanticEvidenceRecord, ...]] = {}
    evidence_ordinal = 0
    for unit in units:
        member_atoms = tuple(
            atom_by_id[item]
            for item in (unit.story_atom_id, *unit.technical_context_atom_ids)
            if item in atom_by_id
        )
        owner_by_evidence: dict[str, StoryAtom] = {}
        for atom in member_atoms:
            for evidence_id in atom.provenance.evidence_ids:
                owner_by_evidence.setdefault(evidence_id, atom)
        records: list[SemanticEvidenceRecord] = []
        for evidence_id in unit.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            owner = owner_by_evidence.get(evidence_id)
            if evidence is None or owner is None:
                raise ValueError("fine-unit evidence is not owned by its M10/M11 authority")
            records.append(
                SemanticEvidenceRecord(
                    unit.unit_id,
                    owner.id,
                    evidence.id,
                    evidence_ordinal,
                    owner.source_kind or owner.kind.value,
                    _evidence_text(evidence, owner),
                    owner.speaker,
                    _source_locator(evidence),
                )
            )
            evidence_ordinal += 1
        if not records:
            raise ValueError("each fine narrative unit requires exact provider evidence")
        result[unit.unit_id] = tuple(records)
    return result


def _evidence_text(evidence: SourceEvidence, atom: StoryAtom) -> str:
    text = evidence.source_text.strip()
    if text:
        return text
    label = atom.label.strip()
    if not label:
        raise ValueError("semantic evidence has no story-facing text")
    return label


def _source_locator(evidence: SourceEvidence) -> SourceLocator:
    source = evidence.source
    path = source.get("path")
    start = source.get("start")
    end = source.get("end")
    if not isinstance(path, str) or not isinstance(start, Mapping) or not isinstance(end, Mapping):
        raise ValueError("semantic evidence has no exact source locator")
    start_line = start.get("line")
    end_line = end.get("line")
    if (
        not isinstance(start_line, int)
        or isinstance(start_line, bool)
        or not isinstance(end_line, int)
        or isinstance(end_line, bool)
    ):
        raise ValueError("semantic evidence source lines are invalid")
    return SourceLocator(path, start_line, end_line, evidence.line_basis or "source")


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)

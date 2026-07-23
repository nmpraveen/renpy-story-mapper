"""Supported durable M15.1 two-stage semantic production lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from renpy_story_mapper import storage
from renpy_story_mapper.narrative.privacy import validate_privacy_safe_keys
from renpy_story_mapper.narrative_map.assembly import assemble_semantic_outline
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    JsonValue,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.persistence import (
    NarrativeJobRecord,
    NarrativeJobStatus,
    NarrativeMapRepository,
)
from renpy_story_mapper.narrative_map.provider import (
    WHOLE_SCOPE_EDITORIAL_PROMPT_VERSION,
    WHOLE_SCOPE_EDITORIAL_RESPONSE_SCHEMA,
    WHOLE_SCOPE_HIERARCHY_PROMPT_VERSION,
    WHOLE_SCOPE_HIERARCHY_RESPONSE_SCHEMA,
    NarrativeConsentManifest,
    NarrativeMapProvider,
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
    WholeScopeEditorialSubject,
    WholeScopeProviderSubject,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    M15_WHOLE_SCOPE_EDITORIAL_INPUT_SCHEMA,
    M15_WHOLE_SCOPE_HIERARCHY_INPUT_SCHEMA,
    MAXIMUM_DAY1_PROVIDER_SUBMISSIONS,
    LiveSemanticProvenance,
    SemanticBoundaryDecision,
    SemanticBuildRecord,
    SemanticBuildState,
    SemanticOutline,
    SemanticSummary,
    WholeScopeLogicalProvenance,
    WholeScopeSemanticStage,
)
from renpy_story_mapper.narrative_map.semantic_hierarchy import (
    ValidatedWholeScopeHierarchy,
    compile_hierarchy_to_gap_decisions,
)
from renpy_story_mapper.narrative_map.semantic_projection import (
    FrozenSummaryInput,
    SemanticEvidenceRecord,
    prepare_semantic_boundary_jobs,
    prepare_semantic_summary_jobs,
    semantic_outline_hash,
    semantic_outline_payload,
)
from renpy_story_mapper.narrative_map.semantic_validation import (
    validate_semantic_boundary_response,
    validate_semantic_summary_response,
)
from renpy_story_mapper.narrative_map.workflow import (
    NarrativeBoundaryWorkflow,
    NarrativeWorkflowReport,
    WholeScopeHierarchyAuthorityValidator,
)

SEMANTIC_BUILD_ENVELOPE = "m15-semantic-build-envelope-v2"
SEMANTIC_PUBLICATION_SCHEMA = "m15-semantic-publication-v2"
DEFAULT_PRIVACY_SCOPE = "story_evidence_only"
WHOLE_SCOPE_BUILD_ENVELOPE = "m15-whole-scope-semantic-build-v1"
WHOLE_SCOPE_PUBLICATION_SCHEMA = "m15-whole-scope-semantic-publication-v1"

CancelledCallback = Callable[[], bool]


class SemanticStage(StrEnum):
    BOUNDARIES = "boundaries"
    SUMMARIES = "summaries"


@dataclass(frozen=True)
class SemanticStagePreparation:
    stage: SemanticStage
    build_id: str
    authority: AuthorityBinding
    source_hash: str
    correction_id: str
    privacy_scope: str
    membership_hash: str | None
    jobs: tuple[PreparedNarrativeJob, ...]
    consent: NarrativeConsentManifest
    outline: SemanticOutline | None = None
    quotient_topology: Mapping[str, object] | None = None

    def granted_consent(self) -> NarrativeConsentManifest:
        """Grant exactly the reviewed immutable manifest without changing its identity."""

        return replace(self.consent, consent_granted=True)


@dataclass(frozen=True)
class SemanticAccounting:
    provider_calls: int = 0
    reserved_provider_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    cache_hits: int = 0


@dataclass(frozen=True)
class SemanticStatusView:
    build_id: str
    record: SemanticBuildRecord
    source_hash: str
    correction_id: str
    privacy_scope: str
    boundary_job_ids: tuple[str, ...]
    summary_job_ids: tuple[str, ...]
    accounting: SemanticAccounting
    current_publication_hash: str | None


@dataclass(frozen=True)
class BoundaryStageOutput:
    decisions: tuple[SemanticBoundaryDecision, ...]
    provenance: tuple[LiveSemanticProvenance, ...]


@dataclass(frozen=True)
class WholeScopeLogicalJob:
    stage: WholeScopeSemanticStage
    logical_job_id: str
    subject_kind: str
    subject_id: str
    membership_hash: str | None


@dataclass(frozen=True)
class WholeScopeStagePreparation:
    stage: WholeScopeSemanticStage
    build_id: str
    authority: AuthorityBinding
    scope_id: str
    source_hash: str
    correction_id: str
    privacy_scope: str
    hierarchy_hash: str | None
    job: PreparedNarrativeJob
    logical_jobs: tuple[WholeScopeLogicalJob, ...]
    consent: NarrativeConsentManifest

    def granted_consent(self) -> NarrativeConsentManifest:
        return replace(self.consent, consent_granted=True)


@dataclass(frozen=True)
class WholeScopeSemanticAccounting:
    logical_jobs: int = 0
    transport_submissions: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    combined_submission_count: int = 0

    def __post_init__(self) -> None:
        values = (
            self.logical_jobs,
            self.transport_submissions,
            self.cache_hits,
            self.input_tokens,
            self.output_tokens,
            self.elapsed_ms,
            self.combined_submission_count,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values
        ):
            raise ValueError("whole-scope accounting values must be non-negative integers")
        if self.combined_submission_count > MAXIMUM_DAY1_PROVIDER_SUBMISSIONS:
            raise ValueError("whole-scope accounting exceeds the four-submission ceiling")


@dataclass(frozen=True)
class WholeScopeSemanticStatus:
    build_id: str
    scope_id: str
    authority: AuthorityBinding
    source_hash: str
    correction_id: str
    hierarchy_state: str
    editorial_state: str
    hierarchy_hash: str | None
    publication_hash: str | None
    failure_codes: tuple[str, ...]
    accounting: WholeScopeSemanticAccounting


class SemanticLifecycle:
    """Orchestrate explicit preview/consent/run stages over durable exact job records."""

    def __init__(self, repository: NarrativeMapRepository) -> None:
        self._repository = repository
        self._active_workflow: NarrativeBoundaryWorkflow | None = None

    def prepare_boundaries(
        self,
        units: Sequence[object],
        candidates: Sequence[object],
        windows: Sequence[object],
        evidence_by_unit: Mapping[str, Sequence[SemanticEvidenceRecord]],
        *,
        profile: ProviderProfile,
        run_id: str,
        source_hash: str,
        correction_id: str,
        privacy_scope: str = DEFAULT_PRIVACY_SCOPE,
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int | None = None,
        maximum_input_bytes: int = 1_000_000,
        maximum_output_bytes: int = 2_000_000,
        timeout_seconds: float = 300.0,
        replay_existing: bool = False,
    ) -> SemanticStagePreparation:
        from renpy_story_mapper.narrative_map.semantic_contracts import (
            BoundaryWindow,
            FineNarrativeUnit,
            NarrativeGapCandidate,
        )

        typed_units = _typed(units, FineNarrativeUnit, "fine narrative unit")
        typed_candidates = _typed(candidates, NarrativeGapCandidate, "narrative gap")
        typed_windows = _typed(windows, BoundaryWindow, "boundary window")
        jobs = prepare_semantic_boundary_jobs(
            typed_units,
            typed_candidates,
            typed_windows,
            evidence_by_unit,
            source_hash=source_hash,
            correction_id=correction_id,
            privacy_scope=privacy_scope,
        )
        if not jobs:
            raise ValueError("the M15.1 production boundary stage requires eligible gaps")
        authority = typed_units[0].authority
        reusable = self._reusable_preparation(
            SemanticStage.BOUNDARIES,
            jobs,
            profile,
            authority,
            source_hash,
            correction_id,
            privacy_scope,
            membership_hash=None,
            outline=None,
            quotient_topology=None,
            run_id=run_id,
            valid_for=valid_for,
            maximum_provider_calls=(
                maximum_provider_calls
                if maximum_provider_calls is not None
                else 2 * len(jobs)
            ),
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
            replay_existing=replay_existing,
        )
        if reusable is not None:
            return reusable
        previous_build = self._repository.read_semantic_build()
        consent = NarrativeConsentManifest.for_jobs(
            run_id=run_id,
            profile=profile,
            jobs=jobs,
            consent_granted=False,
            valid_for=valid_for,
            maximum_provider_calls=maximum_provider_calls,
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
        )
        build_id = stable_m15_id(
            "semantic_build",
            {
                "authority": authority.to_dict(),
                "source_hash": source_hash,
                "correction_id": correction_id,
                "privacy_scope": privacy_scope,
                "boundary_manifest_id": consent.manifest_id,
            },
        )
        for job in jobs:
            self._repository.stage(job, profile)
        payload = _new_build_payload(
            build_id,
            authority,
            source_hash,
            correction_id,
            privacy_scope,
            jobs,
            consent,
            profile,
        )
        recovered = self._recover_stage_progress(
            previous_build,
            jobs,
            profile,
            SemanticStage.BOUNDARIES,
        )
        if recovered is not None:
            (
                recovered_accounting,
                recovered_total,
                completed,
                confirmed,
                _reserved_snapshot,
                recovered_record_hashes,
            ) = recovered
            payload["accounting"] = _accounting_payload(recovered_total)
            payload["boundary_accounting"] = _accounting_payload(recovered_accounting)
            payload["completed_boundary_job_ids"] = list(completed)
            payload["confirmed_manifest_ids"] = list(confirmed)
            payload["boundary_accounted_record_hashes"] = recovered_record_hashes
            if previous_build is not None:
                payload["confirmed_manifests"] = _manifest_snapshot_mapping(
                    previous_build.get("confirmed_manifests")
                )
                payload["confirmed_manifest_stages"] = _manifest_stage_mapping(
                    previous_build.get("confirmed_manifest_stages")
                )
                payload["boundary_reconciled_manifest_ids"] = list(
                    _strings(
                        previous_build.get("boundary_reconciled_manifest_ids", []),
                        "reconciled boundary manifest IDs",
                    )
                )
            payload["boundary_accounted_manifest_id"] = consent.manifest_id
            payload["boundary_accounted_reservation_count"] = 0
        self._repository.write_semantic_build(payload)
        return SemanticStagePreparation(
            SemanticStage.BOUNDARIES,
            build_id,
            authority,
            source_hash,
            correction_id,
            privacy_scope,
            None,
            jobs,
            consent,
        )

    def start_boundaries(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        self._require_stage(preparation, SemanticStage.BOUNDARIES, consent)
        return self._run_stage(preparation, provider, consent, cancelled)

    def confirm_consent(
        self,
        preparation: SemanticStagePreparation,
        consent: NarrativeConsentManifest,
    ) -> SemanticStatusView:
        """Persist an explicit safe acknowledgement of one exact fresh web manifest."""

        consent.validate_for(preparation.jobs, preparation.consent.profile)
        if consent.manifest_id != preparation.consent.manifest_id:
            raise ValueError("semantic consent acknowledgement is stale")
        raw = self._require_build(preparation.build_id)
        prefix = "boundary" if preparation.stage is SemanticStage.BOUNDARIES else "summary"
        if (
            raw.get(f"{prefix}_manifest_id") != consent.manifest_id
            or raw.get(f"{prefix}_job_identity_hash") != _jobs_hash(preparation.jobs)
        ):
            raise ValueError("semantic consent acknowledgement is stale")
        confirmed = _string_list(raw.get("confirmed_manifest_ids", []))
        if consent.manifest_id not in confirmed:
            confirmed.append(consent.manifest_id)
        updated = dict(raw)
        updated["confirmed_manifest_ids"] = confirmed
        confirmed_manifests = _manifest_snapshot_mapping(raw.get("confirmed_manifests"))
        confirmed_manifests[consent.manifest_id] = consent.identity_dict()
        updated["confirmed_manifests"] = confirmed_manifests
        confirmed_stages = _manifest_stage_mapping(raw.get("confirmed_manifest_stages"))
        confirmed_stages[consent.manifest_id] = prefix
        updated["confirmed_manifest_stages"] = confirmed_stages
        self._repository.write_semantic_build(updated)
        return _status_from_payload(updated)

    def boundary_output(
        self,
        preparation: SemanticStagePreparation,
    ) -> BoundaryStageOutput:
        if preparation.stage is not SemanticStage.BOUNDARIES:
            raise ValueError("boundary output requires a boundary preparation")
        raw_build = self._require_build(preparation.build_id)
        if (
            raw_build.get("boundary_manifest_id") != preparation.consent.manifest_id
            or raw_build.get("boundary_job_identity_hash") != _jobs_hash(preparation.jobs)
        ):
            raise ValueError("boundary output preparation is no longer current")
        decisions: list[SemanticBoundaryDecision] = []
        provenance: list[LiveSemanticProvenance] = []
        for job in preparation.jobs:
            record = self._repository.get(job.kind, job.job_id)
            if (
                record is None
                or record.status is not NarrativeJobStatus.VALIDATED
                or record.result is None
                or record.provider_identity is None
            ):
                raise ValueError("boundary output is incomplete")
            validation = validate_semantic_boundary_response(record.result, job)
            if not validation.valid:
                raise ValueError("validated boundary output is corrupt")
            for decision in validation.decisions:
                decisions.append(decision)
                provenance.append(
                    LiveSemanticProvenance(
                        "boundaries",
                        job.job_id,
                        job.input_hash,
                        record.consent_manifest_id or preparation.consent.manifest_id,
                        canonical_hash(record.provider_identity),
                        self._repository.cache_key(job, preparation.consent.profile),
                        candidate_id=decision.candidate_id,
                        window_id=job.subject_id,
                    )
                )
        return BoundaryStageOutput(tuple(decisions), tuple(provenance))

    def freeze_membership(
        self,
        preparation: SemanticStagePreparation,
        outline: SemanticOutline,
        quotient_topology: Mapping[str, object],
    ) -> SemanticStatusView:
        """Durably freeze deterministic hierarchy/topology after all windows validate."""

        if preparation.stage is not SemanticStage.BOUNDARIES:
            raise ValueError("membership freeze requires the boundary preparation")
        raw = self._require_build(preparation.build_id)
        boundary_ids = _strings(raw.get("boundary_job_ids"), "boundary job IDs")
        completed = _strings(raw.get("completed_boundary_job_ids"), "completed boundary jobs")
        if completed != boundary_ids:
            raise ValueError("membership cannot freeze before every boundary window validates")
        expected_candidates = tuple(
            candidate_id
            for job_id in boundary_ids
            for candidate_id in self._window_candidate_ids(job_id)
        )
        if outline.authority != preparation.authority:
            raise ValueError("frozen outline authority differs from its boundary preparation")
        if outline.ordered_candidate_ids != expected_candidates:
            raise ValueError("frozen outline does not cover the exact boundary candidate order")
        expected_provenance = self._expected_boundary_provenance(
            raw,
            boundary_ids,
            preparation.consent.profile,
        )
        if outline.boundary_provenance != expected_provenance:
            raise ValueError("frozen outline lacks one-to-one live boundary provenance")
        topology = dict(quotient_topology)
        if (
            topology.get("schema") != "m15-semantic-quotient-topology-v2"
            or topology.get("canonical_hash") != preparation.authority.canonical_hash
        ):
            raise ValueError("semantic topology is not bound to the exact M10 authority")
        membership_hash = semantic_outline_hash(outline)
        updated = _updated_state(raw, SemanticBuildState.MEMBERSHIP_FROZEN)
        updated["membership_hash"] = membership_hash
        updated["outline"] = semantic_outline_payload(outline)
        updated["quotient_topology"] = topology
        updated["failure_codes"] = []
        self._repository.write_semantic_build(updated)
        return _status_from_payload(updated)

    def prepare_summaries(
        self,
        outline: SemanticOutline,
        inputs: Sequence[FrozenSummaryInput],
        evidence_by_unit: Mapping[str, Sequence[SemanticEvidenceRecord]],
        *,
        quotient_topology: Mapping[str, object] | None = None,
        profile: ProviderProfile,
        run_id: str,
        source_hash: str,
        correction_id: str,
        privacy_scope: str = DEFAULT_PRIVACY_SCOPE,
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int | None = None,
        maximum_input_bytes: int = 1_000_000,
        maximum_output_bytes: int = 2_000_000,
        timeout_seconds: float = 300.0,
        replay_existing: bool = False,
    ) -> SemanticStagePreparation:
        raw = self._require_build()
        if (
            raw.get("source_hash") != source_hash
            or raw.get("correction_id") != correction_id
            or raw.get("privacy_scope") != privacy_scope
            or raw.get("authority") != outline.authority.to_dict()
            or raw.get("profile_hash") != canonical_hash(profile.to_dict())
        ):
            self._mark_stale(raw, "summary_identity_changed")
            raise ValueError("summary preparation identity differs from the boundary build")
        boundary_ids = _strings(raw.get("boundary_job_ids"), "boundary job IDs")
        completed = _strings(raw.get("completed_boundary_job_ids"), "completed boundary jobs")
        if completed != boundary_ids:
            raise ValueError("summaries require all boundary windows to validate")
        expected_candidates = tuple(
            candidate_id
            for job_id in boundary_ids
            for candidate_id in self._window_candidate_ids(job_id)
        )
        if outline.ordered_candidate_ids != expected_candidates:
            raise ValueError("frozen outline does not cover the exact boundary candidate order")
        expected_provenance = self._expected_boundary_provenance(
            raw,
            boundary_ids,
            profile,
        )
        if outline.boundary_provenance != expected_provenance:
            raise ValueError("frozen outline lacks one-to-one live boundary provenance")
        state = SemanticBuildState(cast(str, raw["state"]))
        has_existing_summary_stage = isinstance(raw.get("summary_manifest_id"), str)
        if state is not SemanticBuildState.MEMBERSHIP_FROZEN and not has_existing_summary_stage:
            raise ValueError("summaries require a durable membership freeze")
        jobs = prepare_semantic_summary_jobs(
            outline,
            inputs,
            evidence_by_unit,
            source_hash=source_hash,
            correction_id=correction_id,
            privacy_scope=privacy_scope,
        )
        if not jobs:
            raise ValueError("the frozen outline has no visible summary subjects")
        membership_hash = semantic_outline_hash(outline)
        stored_outline = raw.get("outline")
        if stored_outline != semantic_outline_payload(outline):
            self._mark_stale(raw, "frozen_membership_changed")
            raise ValueError("summary preparation differs from frozen semantic membership")
        stored_topology = raw.get("quotient_topology")
        supplied_topology = dict(quotient_topology) if quotient_topology is not None else None
        if (
            raw.get("membership_hash") != membership_hash
            or not isinstance(stored_topology, Mapping)
            or supplied_topology is None
            or stored_topology != supplied_topology
        ):
            self._mark_stale(raw, "frozen_topology_changed")
            raise ValueError("summary preparation differs from frozen quotient topology")
        final_topology = supplied_topology
        reusable = self._reusable_preparation(
            SemanticStage.SUMMARIES,
            jobs,
            profile,
            outline.authority,
            source_hash,
            correction_id,
            privacy_scope,
            membership_hash=membership_hash,
            outline=outline,
            quotient_topology=final_topology,
            run_id=run_id,
            valid_for=valid_for,
            maximum_provider_calls=(
                maximum_provider_calls
                if maximum_provider_calls is not None
                else 2 * len(jobs)
            ),
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
            replay_existing=replay_existing,
        )
        if reusable is not None:
            return reusable
        consent = NarrativeConsentManifest.for_jobs(
            run_id=run_id,
            profile=profile,
            jobs=jobs,
            consent_granted=False,
            valid_for=valid_for,
            maximum_provider_calls=maximum_provider_calls,
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
        )
        if consent.manifest_id == raw.get("boundary_manifest_id"):
            raise ValueError("summary consent must be distinct from boundary consent")
        recovered = self._recover_stage_progress(
            raw,
            jobs,
            profile,
            SemanticStage.SUMMARIES,
        )
        recovered_summary = _accounting_from_payload(raw.get("summary_accounting"))
        recovered_total = _accounting_from_payload(raw.get("accounting"))
        completed_summaries: tuple[str, ...] = ()
        confirmed_manifests = _strings(
            raw.get("confirmed_manifest_ids", []),
            "confirmed manifest IDs",
        )
        if recovered is not None:
            (
                recovered_summary,
                recovered_total,
                completed_summaries,
                confirmed_manifests,
                _reserved_snapshot,
                recovered_record_hashes,
            ) = recovered
        else:
            recovered_record_hashes = _record_hash_mapping(
                raw.get("summary_accounted_record_hashes")
            )
        for job in jobs:
            self._repository.stage(job, profile)
        updated = dict(raw)
        updated.update(
            {
                "state": SemanticBuildState.AWAITING_SUMMARY_CONSENT.value,
                "state_history": [
                    *_string_list(raw.get("state_history")),
                    SemanticBuildState.MEMBERSHIP_FROZEN.value,
                    SemanticBuildState.SUMMARIES_PREPARED.value,
                    SemanticBuildState.AWAITING_SUMMARY_CONSENT.value,
                ],
                "membership_hash": membership_hash,
                "summary_manifest_id": consent.manifest_id,
                "summary_manifest": consent.identity_dict(),
                "summary_job_ids": [job.job_id for job in jobs],
                "summary_job_identity_hash": _jobs_hash(jobs),
                "completed_summary_job_ids": list(completed_summaries),
                "outline": semantic_outline_payload(outline),
                "quotient_topology": final_topology,
                "failure_codes": [],
                "cancel_requested": False,
                "accounting": _accounting_payload(recovered_total),
                "summary_accounting": _accounting_payload(recovered_summary),
                "confirmed_manifest_ids": list(confirmed_manifests),
                "summary_accounted_manifest_id": consent.manifest_id,
                "summary_accounted_reservation_count": 0,
                "summary_accounted_record_hashes": recovered_record_hashes,
            }
        )
        self._repository.write_semantic_build(updated)
        return SemanticStagePreparation(
            SemanticStage.SUMMARIES,
            cast(str, raw["build_id"]),
            outline.authority,
            source_hash,
            correction_id,
            privacy_scope,
            membership_hash,
            jobs,
            consent,
            outline,
            final_topology,
        )

    def start_summaries(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        self._require_stage(preparation, SemanticStage.SUMMARIES, consent)
        return self._run_stage(preparation, provider, consent, cancelled)

    def status(
        self,
        *,
        authority: AuthorityBinding | None = None,
        source_hash: str | None = None,
        correction_id: str | None = None,
    ) -> SemanticStatusView | None:
        raw = self._repository.read_semantic_build()
        if raw is None:
            return None
        if (
            (authority is not None and raw.get("authority") != authority.to_dict())
            or (source_hash is not None and raw.get("source_hash") != source_hash)
            or (correction_id is not None and raw.get("correction_id") != correction_id)
        ):
            raw = self._mark_stale(raw, "identity_changed")
        return _status_from_payload(raw)

    def cancel(self) -> SemanticStatusView | None:
        raw = self._repository.read_semantic_build()
        if raw is None:
            return None
        state = SemanticBuildState(cast(str, raw["state"]))
        if state not in {SemanticBuildState.COMPLETE, SemanticBuildState.STALE}:
            updated = dict(raw)
            updated["cancel_requested"] = True
            updated["state"] = SemanticBuildState.CANCELLED.value
            updated["state_history"] = [
                *_string_list(raw.get("state_history")),
                SemanticBuildState.CANCELLED.value,
            ]
            self._repository.write_semantic_build(updated)
            raw = updated
        if self._active_workflow is not None:
            self._active_workflow.cancel()
        return _status_from_payload(raw)

    def resume(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        return self._resume_or_retry(preparation, provider, consent, cancelled)

    def retry(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None = None,
    ) -> NarrativeWorkflowReport:
        return self._resume_or_retry(preparation, provider, consent, cancelled)

    def _resume_or_retry(
        self,
        preparation: SemanticStagePreparation,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None,
    ) -> NarrativeWorkflowReport:
        if preparation.stage is SemanticStage.BOUNDARIES:
            return self.start_boundaries(
                preparation, provider=provider, consent=consent, cancelled=cancelled
            )
        return self.start_summaries(
            preparation, provider=provider, consent=consent, cancelled=cancelled
        )

    def _run_stage(
        self,
        preparation: SemanticStagePreparation,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: CancelledCallback | None,
    ) -> NarrativeWorkflowReport:
        raw = self._require_build(preparation.build_id)
        prefix = "boundary" if preparation.stage is SemanticStage.BOUNDARIES else "summary"
        prior_reconciled = _strings(
            raw.get(f"{prefix}_reconciled_manifest_ids", []),
            f"reconciled {prefix} manifest IDs",
        )
        reconciled_manifest_ids = self._reject_overlapping_confirmed_run(
            raw,
            prefix=prefix,
            profile=consent.profile,
            current_manifest_id=consent.manifest_id,
        )
        newly_reconciled = tuple(
            item for item in reconciled_manifest_ids if item not in prior_reconciled
        )
        if newly_reconciled:
            raw = self._repository.reconcile_semantic_manifests(
                stage=prefix,
                manifest_ids=newly_reconciled,
            )
        stage_accounting_key = (
            "boundary_accounting"
            if preparation.stage is SemanticStage.BOUNDARIES
            else "summary_accounting"
        )
        stage_accounting = _accounting_from_payload(raw.get(stage_accounting_key))
        reserved_before = self._repository.semantic_reserved_call_count(
            manifest_id=consent.manifest_id,
            maximum_provider_calls=consent.maximum_provider_calls,
        )
        _reservation_accounting_checkpoint(
            raw,
            prefix=prefix,
            manifest_id=consent.manifest_id,
            durable_reservations=reserved_before,
            stage_accounting=stage_accounting,
        )
        was_complete = raw.get("state") == SemanticBuildState.COMPLETE.value
        if not was_complete:
            running = (
                SemanticBuildState.BOUNDARIES_RUNNING
                if preparation.stage is SemanticStage.BOUNDARIES
                else SemanticBuildState.SUMMARIES_RUNNING
            )
            expected_running_build = raw
            raw = _updated_state(raw, running)
            raw["cancel_requested"] = False
            if not self._repository.write_semantic_build_if_manifest(
                raw,
                expected_build=expected_running_build,
                stage=prefix,
                manifest_id=consent.manifest_id,
            ):
                raise ValueError("semantic preparation became stale before execution")
        if not consent.consent_granted:
            if not self._exact_replay(preparation.jobs, consent.profile):
                raise ValueError("ungranted consent permits only an exact zero-submit replay")
            report = NarrativeWorkflowReport(
                tuple(job.job_id for job in preparation.jobs),
                (),
                len(preparation.jobs),
                0,
                0,
                0,
                0,
                False,
            )
        else:
            workflow = NarrativeBoundaryWorkflow(
                self._repository,
                provider,
                consent.profile,
                timeout_seconds=consent.timeout_seconds,
            )
            self._active_workflow = workflow

            def is_cancelled() -> bool:
                latest = self._repository.read_semantic_build()
                persisted = bool(latest and latest.get("cancel_requested") is True)
                manifest_changed = bool(
                    latest
                    and latest.get(f"{prefix}_manifest_id") != consent.manifest_id
                )
                return persisted or manifest_changed or bool(cancelled and cancelled())

            try:
                if preparation.stage is SemanticStage.BOUNDARIES:
                    report = workflow.run_semantic_boundary_jobs(
                        preparation.jobs,
                        consent=consent,
                        cancelled=is_cancelled,
                        consumed_provider_calls=reserved_before,
                    )
                else:
                    report = workflow.run_semantic_summary_jobs(
                        preparation.jobs,
                        consent=consent,
                        cancelled=is_cancelled,
                        consumed_provider_calls=reserved_before,
                    )
            finally:
                self._active_workflow = None

        def settle_finalized_reservations() -> None:
            self._repository.settle_semantic_provider_calls(
                manifest_id=consent.manifest_id,
                maximum_provider_calls=consent.maximum_provider_calls,
                reservations_to_settle=report.terminal_reservations,
            )

        latest = self._require_build()
        if latest.get(f"{prefix}_manifest_id") != consent.manifest_id:
            settle_finalized_reservations()
            return report
        recovered = self._recover_stage_progress(
            latest,
            preparation.jobs,
            consent.profile,
            preparation.stage,
        )
        if recovered is None:
            raise ValueError("semantic preparation became stale during execution")
        (
            stage_accounting,
            accounting,
            recovered_completed,
            confirmed,
            reserved_snapshot,
            record_hashes,
        ) = recovered
        records = tuple(self._repository.get(job.kind, job.job_id) for job in preparation.jobs)
        completed = tuple(
            job.job_id
            for job, record in zip(preparation.jobs, records, strict=True)
            if record is not None and record.status is NarrativeJobStatus.VALIDATED
        )
        if completed != recovered_completed:
            raise ValueError("semantic terminal records changed during finalization")
        failures = tuple(
            record.error_code
            for record in records
            if record is not None and record.error_code is not None
        )
        updated = dict(latest)
        stage_accounting_key = (
            "boundary_accounting"
            if preparation.stage is SemanticStage.BOUNDARIES
            else "summary_accounting"
        )
        updated_accounting = replace(
            accounting,
            cache_hits=accounting.cache_hits + report.cache_hits,
        )
        updated["accounting"] = _accounting_payload(updated_accounting)
        updated_stage_accounting = replace(
            stage_accounting,
            cache_hits=stage_accounting.cache_hits + report.cache_hits,
        )
        updated[stage_accounting_key] = _accounting_payload(updated_stage_accounting)
        current_manifest_id = latest.get(f"{prefix}_manifest_id")
        if not isinstance(current_manifest_id, str) or not current_manifest_id:
            raise ValueError("semantic finalization manifest is invalid")
        updated[f"{prefix}_accounted_manifest_id"] = current_manifest_id
        updated[f"{prefix}_accounted_reservation_count"] = reserved_snapshot
        updated[f"{prefix}_accounted_record_hashes"] = record_hashes
        updated["confirmed_manifest_ids"] = list(confirmed)
        latest_was_complete = latest.get("state") == SemanticBuildState.COMPLETE.value
        boundary_phase_advanced = (
            preparation.stage is SemanticStage.BOUNDARIES
            and (
                isinstance(latest.get("membership_hash"), str)
                or isinstance(latest.get("summary_manifest_id"), str)
            )
        )
        if latest_was_complete or boundary_phase_advanced:
            self._repository.write_semantic_build_if_manifest(
                updated,
                expected_build=latest,
                stage=prefix,
                manifest_id=consent.manifest_id,
            )
            settle_finalized_reservations()
            return report
        target_key = (
            "completed_boundary_job_ids"
            if preparation.stage is SemanticStage.BOUNDARIES
            else "completed_summary_job_ids"
        )
        updated[target_key] = list(completed)
        updated["failure_codes"] = list(dict.fromkeys(failures))
        updated["cancel_requested"] = False
        if report.cancelled:
            updated = _updated_state(updated, SemanticBuildState.CANCELLED)
        elif len(completed) == len(preparation.jobs):
            updated = _updated_state(updated, SemanticBuildState.VALIDATING)
            if preparation.stage is SemanticStage.SUMMARIES:
                self._publish(preparation, updated, expected_build=latest)
                settle_finalized_reservations()
                return report
        elif report.deferred_job_ids:
            updated["state"] = (
                SemanticBuildState.BOUNDARIES_RUNNING.value
                if preparation.stage is SemanticStage.BOUNDARIES
                else SemanticBuildState.SUMMARIES_RUNNING.value
            )
        elif not completed:
            updated = _updated_state(updated, SemanticBuildState.FAILED)
        else:
            updated = _updated_state(updated, SemanticBuildState.PARTIAL)
        self._repository.write_semantic_build_if_manifest(
            updated,
            expected_build=latest,
            stage=prefix,
            manifest_id=consent.manifest_id,
        )
        settle_finalized_reservations()
        return report

    def _reject_overlapping_confirmed_run(
        self,
        raw: Mapping[str, object],
        *,
        prefix: str,
        profile: ProviderProfile,
        current_manifest_id: str,
    ) -> tuple[str, ...]:
        snapshots = _manifest_snapshot_mapping(raw.get("confirmed_manifests"))
        stages = _manifest_stage_mapping(raw.get("confirmed_manifest_stages"))
        reconciled = list(
            _strings(
                raw.get(f"{prefix}_reconciled_manifest_ids", []),
                f"reconciled {prefix} manifest IDs",
            )
        )
        reconciled_set = set(reconciled)
        if any(
            manifest_id not in snapshots or stages.get(manifest_id) != prefix
            for manifest_id in reconciled
        ):
            raise ValueError("semantic reconciled manifest checkpoint is stale")
        for manifest_id, identity in snapshots.items():
            if (
                manifest_id == current_manifest_id
                or stages.get(manifest_id) != prefix
                or manifest_id in reconciled_set
            ):
                continue
            prior = _restore_manifest(identity, profile)
            latest_possible_completion = datetime.fromisoformat(
                prior.expires_utc
            ) + timedelta(seconds=prior.timeout_seconds)
            if datetime.now(UTC) > latest_possible_completion:
                continue
            sealed = self._repository.seal_semantic_manifest_if_settled(
                manifest_id=manifest_id,
                maximum_provider_calls=prior.maximum_provider_calls,
            )
            if sealed is not True:
                raise ValueError(
                    f"a prior confirmed {prefix} manifest still has an in-flight call"
                )
            reconciled.append(manifest_id)
            reconciled_set.add(manifest_id)
        return tuple(reconciled)

    def _recover_stage_progress(
        self,
        raw: Mapping[str, object] | None,
        jobs: Sequence[PreparedNarrativeJob],
        profile: ProviderProfile,
        stage: SemanticStage,
    ) -> tuple[
        SemanticAccounting,
        SemanticAccounting,
        tuple[str, ...],
        tuple[str, ...],
        int,
        dict[str, str],
    ] | None:
        """Recover exact durable progress when a prior web task escaped before checkpointing."""

        prefix = "boundary" if stage is SemanticStage.BOUNDARIES else "summary"
        if raw is None or raw.get(f"{prefix}_job_ids") != [job.job_id for job in jobs]:
            return None
        if raw.get("profile_hash") != canonical_hash(profile.to_dict()):
            return None
        prior_stage = _accounting_from_payload(raw.get(f"{prefix}_accounting"))
        prior_total = _accounting_from_payload(raw.get("accounting"))
        prior_completed = set(
            _strings(raw.get(f"completed_{prefix}_job_ids"), f"completed {prefix} jobs")
        )
        records = tuple(self._repository.get(job.kind, job.job_id) for job in jobs)
        completed = tuple(
            job.job_id
            for job, record in zip(jobs, records, strict=True)
            if record is not None and record.status is NarrativeJobStatus.VALIDATED
        )
        record_hashes = _record_hash_mapping(
            raw.get(f"{prefix}_accounted_record_hashes")
        )
        if not record_hashes and f"{prefix}_accounted_record_hashes" not in raw:
            remaining_prior_calls = prior_stage.provider_calls
            for job, record in zip(jobs, records, strict=True):
                if record is None or job.job_id not in prior_completed:
                    continue
                record_hashes[job.job_id] = _record_accounting_fingerprint(record)
                remaining_prior_calls -= record.provider_calls
            for job, record in zip(jobs, records, strict=True):
                if (
                    record is None
                    or record.status is NarrativeJobStatus.PENDING
                    or job.job_id in record_hashes
                    or record.provider_calls > remaining_prior_calls
                ):
                    continue
                record_hashes[job.job_id] = _record_accounting_fingerprint(record)
                remaining_prior_calls -= record.provider_calls
            if remaining_prior_calls != 0:
                raise ValueError("legacy semantic record accounting cannot be reconciled")
        provider_calls = 0
        input_tokens = 0
        output_tokens = 0
        elapsed_ms = 0
        for job, record in zip(jobs, records, strict=True):
            if record is None or record.status is NarrativeJobStatus.PENDING:
                continue
            fingerprint = _record_accounting_fingerprint(record)
            if record_hashes.get(job.job_id) == fingerprint:
                continue
            provider_calls += record.provider_calls
            record_hashes[job.job_id] = fingerprint
            if record.usage is None:
                continue
            input_tokens += _usage_integer(record.usage, "input_tokens")
            output_tokens += _usage_integer(record.usage, "output_tokens")
            elapsed_ms += _usage_integer(record.usage, "elapsed_ms")
        reserved_delta = 0
        reserved_snapshot = 0
        manifest_value = raw.get(f"{prefix}_manifest")
        if isinstance(manifest_value, Mapping):
            previous_consent = _restore_manifest(manifest_value, profile)
            reserved = self._repository.semantic_reserved_call_count(
                manifest_id=previous_consent.manifest_id,
                maximum_provider_calls=previous_consent.maximum_provider_calls,
            )
            accounted_reservations = _reservation_accounting_checkpoint(
                raw,
                prefix=prefix,
                manifest_id=previous_consent.manifest_id,
                durable_reservations=reserved,
                stage_accounting=prior_stage,
            )
            reserved_delta = reserved - accounted_reservations
            reserved_snapshot = reserved
        reservation_headroom = (
            prior_stage.reserved_provider_calls - prior_stage.provider_calls
        )
        reserved_delta = max(
            reserved_delta,
            max(0, provider_calls - reservation_headroom),
        )

        def add_delta(prior: SemanticAccounting) -> SemanticAccounting:
            return SemanticAccounting(
                provider_calls=prior.provider_calls + provider_calls,
                reserved_provider_calls=prior.reserved_provider_calls + reserved_delta,
                input_tokens=prior.input_tokens + input_tokens,
                output_tokens=prior.output_tokens + output_tokens,
                elapsed_ms=prior.elapsed_ms + elapsed_ms,
                cache_hits=prior.cache_hits,
            )

        stage_accounting = add_delta(prior_stage)
        total_accounting = add_delta(prior_total)
        if stage_accounting.reserved_provider_calls < stage_accounting.provider_calls:
            raise ValueError("recovered semantic calls exceed durable reservations")
        confirmed = _strings(
            raw.get("confirmed_manifest_ids", []),
            "confirmed manifest IDs",
        )
        return (
            stage_accounting,
            total_accounting,
            completed,
            confirmed,
            reserved_snapshot,
            record_hashes,
        )

    def _publish(
        self,
        preparation: SemanticStagePreparation,
        build: dict[str, object],
        *,
        expected_build: Mapping[str, object],
    ) -> bool:
        if preparation.outline is None or preparation.membership_hash is None:
            raise ValueError("semantic publication requires the frozen outline")
        summaries: list[dict[str, object]] = []
        summary_provenance: list[dict[str, JsonValue]] = []
        for job in preparation.jobs:
            record = self._repository.get(job.kind, job.job_id)
            if record is None or record.result is None or record.provider_identity is None:
                raise ValueError("semantic publication cannot use an incomplete summary")
            validation = validate_semantic_summary_response(record.result, job)
            if not validation.valid or validation.summary is None:
                raise ValueError("semantic publication cannot use an invalid summary")
            summaries.append(_summary_payload(validation.summary))
            summary_provenance.append(
                {
                    "subject_kind": validation.summary.subject_kind,
                    "subject_id": job.subject_id,
                    "stage": "summaries",
                    "job_id": job.job_id,
                    "input_hash": job.input_hash,
                    "manifest_id": (
                        record.consent_manifest_id or preparation.consent.manifest_id
                    ),
                    "provider_identity_hash": canonical_hash(record.provider_identity),
                    "cache_identity": self._repository.cache_key(job, preparation.consent.profile),
                }
            )
        boundary_manifest_id = cast(str, build["boundary_manifest_id"])
        publication: dict[str, object] = {
            "schema": SEMANTIC_PUBLICATION_SCHEMA,
            "build_id": preparation.build_id,
            "authority": preparation.authority.to_dict(),
            "source_hash": preparation.source_hash,
            "correction_id": preparation.correction_id,
            "privacy_scope": preparation.privacy_scope,
            "boundary_manifest_id": boundary_manifest_id,
            "summary_manifest_id": preparation.consent.manifest_id,
            "membership_hash": preparation.membership_hash,
            "outline": semantic_outline_payload(preparation.outline),
            "summaries": summaries,
            "summary_provenance": summary_provenance,
        }
        if preparation.quotient_topology is not None:
            publication["quotient_topology"] = dict(preparation.quotient_topology)
        publication_hash = canonical_hash(publication)
        publication["publication_hash"] = publication_hash
        completed = _updated_state(build, SemanticBuildState.COMPLETE)
        completed["published_map_hash"] = publication_hash
        completed["failure_codes"] = []
        return self._repository.publish_semantic_current_if_manifest(
            build=completed,
            publication=publication,
            expected_build=expected_build,
            stage="summary",
            manifest_id=preparation.consent.manifest_id,
        )

    def _require_stage(
        self,
        preparation: SemanticStagePreparation,
        expected: SemanticStage,
        consent: NarrativeConsentManifest,
    ) -> None:
        if preparation.stage is not expected:
            raise ValueError(f"{expected.value} start requires its own preparation")
        if consent.manifest_id != preparation.consent.manifest_id:
            raise ValueError(f"{expected.value} start requires the exact reviewed consent")
        raw = self._require_build(preparation.build_id)
        prefix = "boundary" if expected is SemanticStage.BOUNDARIES else "summary"
        if (
            raw.get(f"{prefix}_manifest_id") != preparation.consent.manifest_id
            or raw.get(f"{prefix}_job_identity_hash") != _jobs_hash(preparation.jobs)
            or (
                expected is SemanticStage.SUMMARIES
                and raw.get("membership_hash") != preparation.membership_hash
            )
        ):
            raise ValueError("semantic preparation is no longer the active exact stage")
        kinds = {job.kind for job in preparation.jobs}
        expected_kind = (
            ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW
            if expected is SemanticStage.BOUNDARIES
            else ProviderJobKind.SEMANTIC_SUMMARY
        )
        if kinds != {expected_kind}:
            raise ValueError("semantic consent stage does not match its jobs")
        if consent.consent_granted:
            consent.validate_for(preparation.jobs, consent.profile)
        elif not self._exact_replay(preparation.jobs, consent.profile):
            raise ValueError("semantic production requires granted fresh consent")

    def _require_build(self, build_id: str | None = None) -> Mapping[str, object]:
        raw = self._repository.read_semantic_build()
        if raw is None or raw.get("schema") != SEMANTIC_BUILD_ENVELOPE:
            raise ValueError("no supported M15.1 semantic build is prepared")
        if build_id is not None and raw.get("build_id") != build_id:
            raise ValueError("semantic preparation is stale")
        return raw

    def _reusable_preparation(
        self,
        stage: SemanticStage,
        jobs: tuple[PreparedNarrativeJob, ...],
        profile: ProviderProfile,
        authority: AuthorityBinding,
        source_hash: str,
        correction_id: str,
        privacy_scope: str,
        *,
        membership_hash: str | None,
        outline: SemanticOutline | None,
        quotient_topology: Mapping[str, object] | None,
        run_id: str,
        valid_for: timedelta,
        maximum_provider_calls: int,
        maximum_input_bytes: int,
        maximum_output_bytes: int,
        timeout_seconds: float,
        replay_existing: bool,
    ) -> SemanticStagePreparation | None:
        raw = self._repository.read_semantic_build()
        if raw is None or raw.get("schema") != SEMANTIC_BUILD_ENVELOPE:
            return None
        prefix = "boundary" if stage is SemanticStage.BOUNDARIES else "summary"
        if any(
            (
                raw.get("authority") != authority.to_dict(),
                raw.get("source_hash") != source_hash,
                raw.get("correction_id") != correction_id,
                raw.get("privacy_scope") != privacy_scope,
                raw.get(f"{prefix}_job_identity_hash") != _jobs_hash(jobs),
                raw.get("profile_hash") != canonical_hash(profile.to_dict()),
                membership_hash is not None and raw.get("membership_hash") != membership_hash,
            )
        ):
            return None
        manifest_value = raw.get(f"{prefix}_manifest")
        if not isinstance(manifest_value, Mapping):
            return None
        consent = _restore_manifest(manifest_value, profile)
        if consent.manifest_id != raw.get(f"{prefix}_manifest_id"):
            return None

        def checkpoint_reusable(current: Mapping[str, object]) -> Mapping[str, object]:
            recovered = self._recover_stage_progress(current, jobs, profile, stage)
            if recovered is None:
                return current
            (
                recovered_stage,
                recovered_total,
                completed,
                confirmed,
                reserved_snapshot,
                record_hashes,
            ) = recovered
            updated = dict(current)
            updated["accounting"] = _accounting_payload(recovered_total)
            updated[f"{prefix}_accounting"] = _accounting_payload(recovered_stage)
            updated[f"completed_{prefix}_job_ids"] = list(completed)
            updated["confirmed_manifest_ids"] = list(confirmed)
            updated[f"{prefix}_accounted_manifest_id"] = consent.manifest_id
            updated[f"{prefix}_accounted_reservation_count"] = reserved_snapshot
            updated[f"{prefix}_accounted_record_hashes"] = record_hashes
            if updated != current:
                self._repository.write_semantic_build(updated)
                return updated
            return current

        requested_identity_matches = (
            consent.run_id == run_id
            and _manifest_duration(consent) == valid_for
            and consent.maximum_provider_calls == maximum_provider_calls
            and consent.maximum_input_bytes == maximum_input_bytes
            and consent.maximum_output_bytes == maximum_output_bytes
            and consent.timeout_seconds == timeout_seconds
        )
        if not requested_identity_matches:
            if not replay_existing or not self._exact_replay(jobs, profile):
                return None
            raw = checkpoint_reusable(raw)
            return SemanticStagePreparation(
                stage,
                cast(str, raw["build_id"]),
                authority,
                source_hash,
                correction_id,
                privacy_scope,
                membership_hash,
                jobs,
                consent,
                outline,
                quotient_topology,
            )
        try:
            consent.validate_fresh()
        except ValueError:
            if not replay_existing or not self._exact_replay(jobs, profile):
                return None
        raw = checkpoint_reusable(raw)
        return SemanticStagePreparation(
            stage,
            cast(str, raw["build_id"]),
            authority,
            source_hash,
            correction_id,
            privacy_scope,
            membership_hash,
            jobs,
            consent,
            outline,
            quotient_topology,
        )

    def _window_candidate_ids(self, job_id: str) -> tuple[str, ...]:
        record = self._repository.get(ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW, job_id)
        if record is None or record.result is None:
            raise ValueError("boundary membership cannot freeze before validated windows")
        decisions = record.result.get("decisions")
        if record.result.get("window_id") != record.subject_id or not isinstance(decisions, list):
            raise ValueError("validated boundary window is corrupt")
        candidate_ids: list[str] = []
        for item in decisions:
            candidate_id = item.get("candidate_id") if isinstance(item, Mapping) else None
            if not isinstance(candidate_id, str) or not candidate_id:
                raise ValueError("validated boundary window candidate identity is corrupt")
            candidate_ids.append(candidate_id)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("validated boundary window candidate identities are duplicated")
        return tuple(candidate_ids)

    def _expected_boundary_provenance(
        self,
        raw: Mapping[str, object],
        boundary_ids: Sequence[str],
        profile: ProviderProfile,
    ) -> tuple[LiveSemanticProvenance, ...]:
        authority = _authority(raw.get("authority"))
        expected: list[LiveSemanticProvenance] = []
        for job_id in boundary_ids:
            record = self._repository.get(ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW, job_id)
            if record is None or record.result is None or record.provider_identity is None:
                raise ValueError("boundary provenance requires validated durable jobs")
            cache_identity: dict[str, JsonValue] = {
                "kind": ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW.value,
                "authority": authority.to_dict(),
                "subject_id": record.subject_id,
                "input_hash": record.input_hash,
                "provider": profile.to_dict(),
                "prompt_version": record.prompt_version,
                "response_schema": record.response_schema,
                "source_hash": cast(str, raw["source_hash"]),
                "correction_id": cast(str, raw["correction_id"]),
                "privacy_scope": cast(str, raw["privacy_scope"]),
            }
            for candidate_id in self._window_candidate_ids(job_id):
                expected.append(
                    LiveSemanticProvenance(
                        "boundaries",
                        job_id,
                        record.input_hash,
                        record.consent_manifest_id or cast(str, raw["boundary_manifest_id"]),
                        canonical_hash(record.provider_identity),
                        f"m15_cache_{canonical_hash(cache_identity)}",
                        candidate_id=candidate_id,
                        window_id=record.subject_id,
                    )
                )
        return tuple(expected)

    def _exact_replay(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        profile: ProviderProfile,
    ) -> bool:
        expected_identity_prefix = {
            "provider": profile.provider,
            "adapter_version": f"{profile.adapter}:{profile.adapter_version}",
            "requested_model": profile.requested_model,
            "resolved_model": profile.requested_model,
            "settings_hash": profile.settings_hash,
        }
        for job in jobs:
            record = self._repository.get(job.kind, job.job_id)
            if (
                record is None
                or record.status is not NarrativeJobStatus.VALIDATED
                or record.result is None
                or record.provider_identity is None
                or record.consent_manifest_id is None
            ):
                return False
            expected_identity = {
                **expected_identity_prefix,
                "prompt_version": job.prompt_version,
                "response_schema": job.response_schema,
                "input_hash": job.input_hash,
            }
            if dict(record.provider_identity) != expected_identity:
                return False
            if job.kind is ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW:
                if not validate_semantic_boundary_response(record.result, job).valid:
                    return False
            elif job.kind is ProviderJobKind.SEMANTIC_SUMMARY:
                if not validate_semantic_summary_response(record.result, job).valid:
                    return False
            else:
                return False
        return True

    def _mark_stale(
        self,
        raw: Mapping[str, object],
        code: str,
    ) -> Mapping[str, object]:
        updated = _updated_state(raw, SemanticBuildState.STALE)
        updated["failure_codes"] = [code]
        self._repository.write_semantic_build(updated)
        return updated


class WholeScopeSemanticLifecycle:
    """Durable two-gate Stage H/Stage E lifecycle over one transport batch per stage."""

    def __init__(self, repository: NarrativeMapRepository) -> None:
        self._repository = repository
        self._active_workflow: NarrativeBoundaryWorkflow | None = None

    def prepare_hierarchy(
        self,
        authority: AuthorityBinding,
        scope_id: str,
        ordered_unit_ids: Sequence[str],
        input_payload: Mapping[str, object],
        *,
        known_evidence_ids: Sequence[str],
        known_characters: Sequence[str] = (),
        profile: ProviderProfile,
        run_id: str,
        source_hash: str,
        correction_id: str,
        privacy_scope: str = DEFAULT_PRIVACY_SCOPE,
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int = 2,
        maximum_input_bytes: int = 1_000_000,
        maximum_output_bytes: int = 2_000_000,
        timeout_seconds: float = 300.0,
        replay_existing: bool = False,
        recover_confirmed: bool = False,
    ) -> WholeScopeStagePreparation:
        ordered = _whole_scope_strings(ordered_unit_ids, "Stage H unit ID", allow_empty=False)
        evidence = _whole_scope_strings(
            known_evidence_ids, "Stage H evidence ID", allow_empty=False
        )
        characters = _whole_scope_strings(known_characters, "Stage H character")
        payload = _whole_scope_mapping(input_payload, "Stage H input")
        _validate_stage_h_input(payload, authority, scope_id, ordered, evidence)
        _validate_whole_scope_limits(maximum_provider_calls)
        logical_id = stable_m15_id(
            "whole_scope_hierarchy_logical_job",
            {
                "authority": authority.to_dict(),
                "scope_id": scope_id,
                "source_hash": source_hash,
                "correction_id": correction_id,
                "input_hash": canonical_hash(payload),
            },
        )
        subject = WholeScopeProviderSubject(
            WholeScopeSemanticStage.HIERARCHY,
            scope_id,
            ordered,
        )
        job = PreparedNarrativeJob(
            kind=ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
            authority=authority,
            subject=subject,
            subject_id=scope_id,
            input_hash=canonical_hash(payload),
            prompt_version=WHOLE_SCOPE_HIERARCHY_PROMPT_VERSION,
            response_schema=WHOLE_SCOPE_HIERARCHY_RESPONSE_SCHEMA,
            payload=cast(dict[str, JsonValue], payload),
            known_evidence_ids=evidence,
            known_characters=characters,
            source_hash=_whole_scope_text(source_hash, "source hash"),
            correction_id=_whole_scope_text(correction_id, "correction ID"),
            privacy_scope=_whole_scope_text(privacy_scope, "privacy scope"),
            logical_job_ids=(logical_id,),
            combined_submission_limit=MAXIMUM_DAY1_PROVIDER_SUBMISSIONS,
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
        consent = NarrativeConsentManifest.for_jobs(
            run_id=run_id,
            profile=profile,
            jobs=(job,),
            valid_for=valid_for,
            maximum_provider_calls=maximum_provider_calls,
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
        )
        build_id = stable_m15_id(
            "whole_scope_build",
            {
                "authority": authority.to_dict(),
                "scope_id": scope_id,
                "source_hash": source_hash,
                "correction_id": correction_id,
                "privacy_scope": privacy_scope,
                "profile": profile.to_dict(),
                "hierarchy_transport_batch_id": job.job_id,
            },
        )
        existing = self._repository.read_whole_scope_build()
        exact_existing = bool(
            replay_existing
            and existing is not None
            and existing.get("build_id") == build_id
            and existing.get("hierarchy_transport_batch_id") == job.job_id
        )
        if recover_confirmed:
            if not exact_existing or existing is None:
                raise ValueError("confirmed Stage H preparation is unavailable")
            manifest = existing.get("hierarchy_manifest")
            if not isinstance(manifest, Mapping):
                raise ValueError("persisted Stage H manifest is unavailable")
            consent = _restore_manifest(manifest, profile)
            if (
                existing.get("hierarchy_state") not in {"cancelled", "failed"}
                or existing.get("confirmed_hierarchy_manifest_id") != consent.manifest_id
                or "m15_preparation_stale"
                in cast(list[object], existing.get("failure_codes", []))
                or 2 in self._repository.whole_scope_reserved_attempts(job.job_id)
            ):
                raise ValueError("confirmed Stage H preparation is not recoverable")
        elif not exact_existing:
            build: dict[str, object] = {
                "schema": WHOLE_SCOPE_BUILD_ENVELOPE,
                "build_id": build_id,
                "scope_id": scope_id,
                "authority": authority.to_dict(),
                "source_hash": source_hash,
                "correction_id": correction_id,
                "privacy_scope": privacy_scope,
                "hierarchy_state": "awaiting_consent",
                "editorial_state": "not_started",
                "hierarchy_transport_batch_id": job.job_id,
                "hierarchy_logical_jobs": [
                    _whole_scope_logical_job_payload(item) for item in logical_jobs
                ],
                "hierarchy_manifest_id": consent.manifest_id,
                "hierarchy_manifest": consent.identity_dict(),
                "hierarchy_profile": profile.to_dict(),
                "hierarchy_hash": None,
                "hierarchy_result": None,
                "authoritative_hierarchy": None,
                "frozen_editorial_subjects": [],
                "frozen_editorial_evidence_hash": None,
                "editorial_transport_batch_id": None,
                "editorial_logical_jobs": [],
                "editorial_manifest_id": None,
                "editorial_manifest": None,
                "editorial_profile": None,
                "editorial_result": None,
                "confirmed_hierarchy_manifest_id": None,
                "confirmed_editorial_manifest_id": None,
                "failure_codes": [],
                "cache_hits": 0,
                "publication_hash": None,
            }
            self._repository.write_whole_scope_build(build)
        else:
            assert existing is not None
            manifest = existing.get("hierarchy_manifest")
            if not isinstance(manifest, Mapping):
                raise ValueError("persisted Stage H manifest is unavailable")
            consent = _restore_manifest(manifest, profile)
        return WholeScopeStagePreparation(
            WholeScopeSemanticStage.HIERARCHY,
            build_id,
            authority,
            scope_id,
            source_hash,
            correction_id,
            privacy_scope,
            None,
            job,
            logical_jobs,
            consent,
        )

    def prepare_editorial(
        self,
        authority: AuthorityBinding,
        scope_id: str,
        hierarchy_hash: str,
        subjects: Sequence[WholeScopeEditorialSubject],
        input_payload: Mapping[str, object],
        *,
        profile: ProviderProfile,
        run_id: str,
        source_hash: str,
        correction_id: str,
        privacy_scope: str = DEFAULT_PRIVACY_SCOPE,
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int = 2,
        maximum_input_bytes: int = 1_000_000,
        maximum_output_bytes: int = 2_000_000,
        timeout_seconds: float = 300.0,
        replay_existing: bool = False,
        recover_confirmed: bool = False,
    ) -> WholeScopeStagePreparation:
        frozen_subjects = tuple(subjects)
        if not frozen_subjects:
            raise ValueError("Stage E requires at least one frozen subject")
        identities = tuple(item.identity for item in frozen_subjects)
        if len(identities) != len(set(identities)):
            raise ValueError("Stage E frozen subject identities must be unique")
        raw = self._require_build(authority, scope_id, source_hash, correction_id)
        if raw.get("hierarchy_state") != "frozen" or raw.get("hierarchy_hash") != hierarchy_hash:
            raise ValueError("Stage E requires the exact durable frozen hierarchy")
        expected_subjects = _frozen_editorial_subjects(raw)
        if tuple(item.to_dict() for item in frozen_subjects) != tuple(
            item.to_dict() for item in expected_subjects
        ):
            raise ValueError("Stage E subjects are not the exact frozen hierarchy authority")
        payload = _whole_scope_mapping(input_payload, "Stage E input")
        _validate_stage_e_input(payload, authority, scope_id, hierarchy_hash, frozen_subjects)
        if canonical_hash(payload.get("evidence")) != raw.get("frozen_editorial_evidence_hash"):
            raise ValueError("Stage E evidence is not the exact frozen authority projection")
        _validate_whole_scope_limits(maximum_provider_calls)
        logical_jobs = tuple(
            WholeScopeLogicalJob(
                WholeScopeSemanticStage.EDITORIAL,
                stable_m15_id(
                    "whole_scope_editorial_logical_job",
                    {
                        "authority": authority.to_dict(),
                        "scope_id": scope_id,
                        "hierarchy_hash": hierarchy_hash,
                        "subject": item.to_dict(),
                        "source_hash": source_hash,
                        "correction_id": correction_id,
                    },
                ),
                item.subject_kind,
                item.subject_id,
                item.membership_hash,
            )
            for item in frozen_subjects
        )
        subject = WholeScopeProviderSubject(
            WholeScopeSemanticStage.EDITORIAL,
            scope_id,
            hierarchy_hash=hierarchy_hash,
            editorial_subjects=frozen_subjects,
        )
        known_evidence_ids = tuple(
            dict.fromkeys(
                evidence_id for item in frozen_subjects for evidence_id in item.evidence_ids
            )
        )
        known_characters = tuple(
            dict.fromkeys(
                character for item in frozen_subjects for character in item.known_characters
            )
        )
        job = PreparedNarrativeJob(
            kind=ProviderJobKind.WHOLE_SCOPE_EDITORIAL,
            authority=authority,
            subject=subject,
            subject_id=scope_id,
            input_hash=canonical_hash(payload),
            prompt_version=WHOLE_SCOPE_EDITORIAL_PROMPT_VERSION,
            response_schema=WHOLE_SCOPE_EDITORIAL_RESPONSE_SCHEMA,
            payload=cast(dict[str, JsonValue], payload),
            known_evidence_ids=known_evidence_ids,
            known_characters=known_characters,
            source_hash=_whole_scope_text(source_hash, "source hash"),
            correction_id=_whole_scope_text(correction_id, "correction ID"),
            membership_hash=_whole_scope_text(hierarchy_hash, "hierarchy hash"),
            privacy_scope=_whole_scope_text(privacy_scope, "privacy scope"),
            logical_job_ids=tuple(item.logical_job_id for item in logical_jobs),
            combined_submission_limit=MAXIMUM_DAY1_PROVIDER_SUBMISSIONS,
        )
        consent = NarrativeConsentManifest.for_jobs(
            run_id=run_id,
            profile=profile,
            jobs=(job,),
            valid_for=valid_for,
            maximum_provider_calls=maximum_provider_calls,
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
        )
        exact_existing = bool(
            replay_existing and raw.get("editorial_transport_batch_id") == job.job_id
        )
        if recover_confirmed:
            if not exact_existing:
                raise ValueError("confirmed Stage E preparation is unavailable")
            manifest = raw.get("editorial_manifest")
            if not isinstance(manifest, Mapping):
                raise ValueError("persisted Stage E manifest is unavailable")
            consent = _restore_manifest(manifest, profile)
            if (
                raw.get("editorial_state") not in {"cancelled", "failed"}
                or raw.get("confirmed_editorial_manifest_id") != consent.manifest_id
                or "m15_preparation_stale"
                in cast(list[object], raw.get("failure_codes", []))
                or 2 in self._repository.whole_scope_reserved_attempts(job.job_id)
            ):
                raise ValueError("confirmed Stage E preparation is not recoverable")
        elif exact_existing:
            manifest = raw.get("editorial_manifest")
            if not isinstance(manifest, Mapping):
                raise ValueError("persisted Stage E manifest is unavailable")
            consent = _restore_manifest(manifest, profile)
        else:
            updated = dict(raw)
            updated.update(
                {
                    "editorial_state": "awaiting_consent",
                    "editorial_transport_batch_id": job.job_id,
                    "editorial_logical_jobs": [
                        _whole_scope_logical_job_payload(item) for item in logical_jobs
                    ],
                    "editorial_manifest_id": consent.manifest_id,
                    "editorial_manifest": consent.identity_dict(),
                    "editorial_profile": profile.to_dict(),
                    "confirmed_editorial_manifest_id": None,
                    "editorial_result": None,
                    "failure_codes": [],
                }
            )
            self._repository.write_whole_scope_build(updated)
        return WholeScopeStagePreparation(
            WholeScopeSemanticStage.EDITORIAL,
            cast(str, raw["build_id"]),
            authority,
            scope_id,
            source_hash,
            correction_id,
            privacy_scope,
            hierarchy_hash,
            job,
            logical_jobs,
            consent,
        )

    def confirm_consent(
        self,
        preparation: WholeScopeStagePreparation,
        consent: NarrativeConsentManifest,
    ) -> WholeScopeSemanticStatus:
        if consent.manifest_id != preparation.consent.manifest_id:
            raise ValueError("whole-scope consent does not match the exact reviewed manifest")
        consent.validate_for((preparation.job,), preparation.consent.profile)
        raw = self._require_preparation(preparation)
        prefix = preparation.stage.value
        if (
            raw.get(f"{prefix}_state") != "awaiting_consent"
            or raw.get(f"{prefix}_manifest") != preparation.consent.identity_dict()
        ):
            return self.status_required()
        updated = dict(raw)
        updated[f"confirmed_{prefix}_manifest_id"] = consent.manifest_id
        updated[f"{prefix}_state"] = "awaiting_start"
        self._repository.write_whole_scope_build_if_stage(
            updated,
            expected_build=raw,
            stage=prefix,
            manifest_id=consent.manifest_id,
            expected_state="awaiting_consent",
        )
        return self.status_required()

    def start(
        self,
        preparation: WholeScopeStagePreparation,
        *,
        provider: NarrativeMapProvider | None,
        consent: NarrativeConsentManifest | None,
        cancelled: CancelledCallback | None = None,
        hierarchy_authority_validator: WholeScopeHierarchyAuthorityValidator | None = None,
    ) -> NarrativeWorkflowReport:
        raw = self._require_preparation(preparation)
        prefix = preparation.stage.value
        state = raw.get(f"{prefix}_state")
        record = self._repository.get(preparation.job.kind, preparation.job.job_id)
        if (
            record is not None
            and record.status is NarrativeJobStatus.VALIDATED
            and record.result is not None
            and state in {"validated", "frozen", "complete"}
        ):
            replayed = dict(raw)
            replayed["cache_hits"] = cast(int, replayed.get("cache_hits", 0)) + 1
            if not self._repository.write_whole_scope_build_if_stage(
                replayed,
                expected_build=raw,
                stage=prefix,
                manifest_id=preparation.consent.manifest_id,
                expected_state=state,
            ):
                return NarrativeWorkflowReport(
                    (), (), 0, 0, 0, 0, 0, False, (preparation.job.job_id,)
                )
            return NarrativeWorkflowReport(
                (preparation.job.job_id,), (), 1, 0, 0, 0, 0, False
            )
        if record is not None and record.attempt_count >= 2:
            return NarrativeWorkflowReport(
                (), (preparation.job.job_id,), 0, 0, 0, 0, 0, False
            )
        if provider is None or consent is None:
            raise ValueError("a cache miss requires an explicitly consented fake/live provider")
        if consent.manifest_id != preparation.consent.manifest_id:
            raise ValueError("whole-scope start consent is stale")
        consent.validate_for((preparation.job,), preparation.consent.profile)
        if raw.get(f"confirmed_{prefix}_manifest_id") != consent.manifest_id:
            raise ValueError("whole-scope consent must be confirmed before start")
        if state not in {"awaiting_start", "cancelled", "failed"}:
            return NarrativeWorkflowReport(
                (), (), 0, 0, 0, 0, 0, False, (preparation.job.job_id,)
            )
        updated = dict(raw)
        updated[f"{prefix}_state"] = "running"
        updated["failure_codes"] = []
        if not self._repository.write_whole_scope_build_if_stage(
            updated,
            expected_build=raw,
            stage=prefix,
            manifest_id=consent.manifest_id,
            expected_state=state,
        ):
            return NarrativeWorkflowReport(
                (), (), 0, 0, 0, 0, 0, False, (preparation.job.job_id,)
            )
        running = updated
        workflow = NarrativeBoundaryWorkflow(
            self._repository,
            provider,
            preparation.consent.profile,
            timeout_seconds=consent.timeout_seconds,
        )
        self._active_workflow = workflow
        try:
            if preparation.stage is WholeScopeSemanticStage.HIERARCHY:
                report = workflow.run_whole_scope_hierarchy_job(
                    preparation.job,
                    consent=consent,
                    cancelled=cancelled,
                    authority_validator=hierarchy_authority_validator,
                )
            else:
                report = workflow.run_whole_scope_editorial_job(
                    preparation.job,
                    consent=consent,
                    cancelled=cancelled,
                )
        finally:
            self._active_workflow = None
        attempts = tuple(
            attempt
            for job_id, attempt in report.terminal_reservations
            if job_id == preparation.job.job_id
        )
        self._repository.settle_whole_scope_provider_submissions(
            transport_batch_id=preparation.job.job_id,
            attempts=attempts,
        )
        final = dict(running)
        final["cache_hits"] = cast(int, final.get("cache_hits", 0)) + report.cache_hits
        record = self._repository.get(preparation.job.kind, preparation.job.job_id)
        logical_records: tuple[Mapping[str, object], ...] = ()
        if report.cancelled:
            final[f"{prefix}_state"] = "cancelled"
            final["failure_codes"] = ["cancelled"]
        elif (
            record is not None
            and record.status is NarrativeJobStatus.VALIDATED
            and record.result is not None
        ):
            final[f"{prefix}_state"] = "validated"
            final[f"{prefix}_result"] = dict(record.result)
            final["failure_codes"] = []
            logical_records = self._logical_records(preparation, record)
            if preparation.stage is WholeScopeSemanticStage.EDITORIAL:
                final["editorial_state"] = "complete"
                published = self._publish(
                    final,
                    preparation,
                    logical_records,
                    expected_running=running,
                )
                return (
                    report
                    if published
                    else self._deferred_completion_report(report, preparation)
                )
        else:
            final[f"{prefix}_state"] = "failed"
            error_code = record.error_code if record is not None else None
            final["failure_codes"] = [error_code or "stage_failed"]
        committed = self._repository.write_whole_scope_build_if_stage(
            final,
            expected_build=running,
            stage=prefix,
            manifest_id=consent.manifest_id,
            expected_state="running",
            logical_records=(
                logical_records
                if preparation.stage is WholeScopeSemanticStage.HIERARCHY
                else ()
            ),
        )
        return (
            report
            if committed
            else self._deferred_completion_report(report, preparation)
        )

    def freeze_hierarchy(
        self,
        preparation: WholeScopeStagePreparation,
        validated_hierarchy: ValidatedWholeScopeHierarchy,
        evidence: Sequence[Mapping[str, object]],
        hierarchy_hash: str | None = None,
    ) -> WholeScopeSemanticStatus:
        if preparation.stage is not WholeScopeSemanticStage.HIERARCHY:
            raise ValueError("only Stage H can freeze hierarchy membership")
        raw = self._require_preparation(preparation)
        if raw.get("hierarchy_state") != "validated" or not isinstance(
            raw.get("hierarchy_result"), Mapping
        ):
            raise ValueError("hierarchy cannot freeze before validated Stage H output")
        if not isinstance(validated_hierarchy, ValidatedWholeScopeHierarchy):
            raise ValueError("hierarchy freeze requires Track A validated authority")
        if (
            validated_hierarchy.scope_id != preparation.scope_id
            or validated_hierarchy.authority != preparation.authority
            or validated_hierarchy.ordered_unit_ids
            != cast(WholeScopeProviderSubject, preparation.job.subject).ordered_unit_ids
        ):
            raise ValueError("validated hierarchy is foreign to the exact Stage H preparation")
        hierarchy_result = cast(Mapping[str, object], raw["hierarchy_result"])
        expected_groups = [
            {
                "proposal_key": item.proposal_key,
                "ordered_unit_ids": list(item.ordered_unit_ids),
            }
            for item in validated_hierarchy.beat_groups
        ]
        expected_clusters = [
            {
                "proposal_key": item.proposal_key,
                "ordered_beat_keys": list(item.ordered_beat_keys),
            }
            for item in validated_hierarchy.major_clusters
        ]
        actual_groups = (
            [
                {
                    "proposal_key": item.get("proposal_key"),
                    "ordered_unit_ids": item.get("ordered_unit_ids"),
                }
                for item in cast(list[Mapping[str, object]], hierarchy_result.get("beat_groups"))
            ]
            if isinstance(hierarchy_result.get("beat_groups"), list)
            else None
        )
        actual_clusters = (
            [
                {
                    "proposal_key": item.get("proposal_key"),
                    "ordered_beat_keys": item.get("ordered_beat_keys"),
                }
                for item in cast(list[Mapping[str, object]], hierarchy_result.get("major_clusters"))
            ]
            if isinstance(hierarchy_result.get("major_clusters"), list)
            else None
        )
        if (
            hierarchy_result.get("scope_id") != preparation.scope_id
            or actual_groups != expected_groups
            or actual_clusters != expected_clusters
            or hierarchy_result.get("uncertain_unit_ids") != []
        ):
            raise ValueError("validated hierarchy does not match the exact Stage H result")
        outline = assemble_semantic_outline(
            validated_hierarchy.units,
            validated_hierarchy.candidates,
            compile_hierarchy_to_gap_decisions(validated_hierarchy),
            choices=validated_hierarchy.choices,
        )
        normalized = semantic_outline_payload(outline)
        exact_hash = semantic_outline_hash(outline)
        if hierarchy_hash is not None and hierarchy_hash != exact_hash:
            raise ValueError("frozen hierarchy hash does not match its exact payload")
        frozen_subjects, frozen_evidence = derive_frozen_editorial_authority(
            outline,
            validated_hierarchy.units,
            evidence,
            exact_hash,
        )
        updated = dict(raw)
        updated["hierarchy_state"] = "frozen"
        updated["hierarchy_hash"] = exact_hash
        updated["authoritative_hierarchy"] = normalized
        updated["frozen_editorial_subjects"] = [item.to_dict() for item in frozen_subjects]
        updated["frozen_editorial_evidence_hash"] = canonical_hash(frozen_evidence)
        self._repository.write_whole_scope_build_if_stage(
            updated,
            expected_build=raw,
            stage="hierarchy",
            manifest_id=preparation.consent.manifest_id,
            expected_state="validated",
        )
        return self.status_required()

    def fence_stale_preparation(
        self,
        stage: WholeScopeSemanticStage,
        preparation: WholeScopeStagePreparation | None = None,
    ) -> WholeScopeSemanticStatus | None:
        """Atomically make an unreviewable stage ineligible for recovery."""

        raw = self._repository.read_whole_scope_build()
        if raw is None:
            return None
        prefix = stage.value
        state = raw.get(f"{prefix}_state")
        manifest_id = raw.get(f"{prefix}_manifest_id")
        if (
            state not in {"awaiting_consent", "awaiting_start", "cancelled", "failed"}
            or not isinstance(manifest_id, str)
            or not manifest_id
        ):
            return self.status_required()
        if preparation is not None and (
            preparation.stage is not stage
            or raw.get("build_id") != preparation.build_id
            or raw.get(f"{prefix}_transport_batch_id") != preparation.job.job_id
            or manifest_id != preparation.consent.manifest_id
        ):
            return self.status_required()
        updated = dict(raw)
        updated[f"{prefix}_state"] = "failed"
        updated[f"confirmed_{prefix}_manifest_id"] = None
        updated["failure_codes"] = ["m15_preparation_stale"]
        self._repository.write_whole_scope_build_if_stage(
            updated,
            expected_build=raw,
            stage=prefix,
            manifest_id=manifest_id,
            expected_state=state,
        )
        return self.status_required()

    def cancel(self) -> WholeScopeSemanticStatus | None:
        raw = self._repository.read_whole_scope_build()
        if raw is None:
            return None
        expected_publication = self._repository.read_whole_scope_current()
        updated = dict(raw)
        stage: str | None = None
        state: str | None = None
        if isinstance(updated.get("editorial_state"), str) and updated.get(
            "editorial_state"
        ) in {"awaiting_consent", "awaiting_start", "running"}:
            stage = "editorial"
            state = cast(str, updated["editorial_state"])
            updated["editorial_state"] = "cancelled"
        elif isinstance(updated.get("hierarchy_state"), str) and updated.get(
            "hierarchy_state"
        ) in {"awaiting_consent", "awaiting_start", "running"}:
            stage = "hierarchy"
            state = cast(str, updated["hierarchy_state"])
            updated["hierarchy_state"] = "cancelled"
        if stage is None or state is None:
            return self.status_required()
        manifest_id = raw.get(f"{stage}_manifest_id")
        if not isinstance(manifest_id, str) or not manifest_id:
            raise ValueError("whole-scope cancellable stage manifest is unavailable")
        updated["failure_codes"] = ["cancelled"]
        cancelled = self._repository.write_whole_scope_build_if_stage(
            updated,
            expected_build=raw,
            stage=stage,
            manifest_id=manifest_id,
            expected_state=state,
            check_expected_publication=True,
            expected_publication=expected_publication,
        )
        if cancelled and self._active_workflow is not None:
            self._active_workflow.cancel()
        return self.status_required()

    def status(self) -> WholeScopeSemanticStatus | None:
        raw = self._repository.read_whole_scope_build()
        return None if raw is None else self._status(raw)

    def status_required(self) -> WholeScopeSemanticStatus:
        status = self.status()
        if status is None:
            raise ValueError("whole-scope semantic build is unavailable")
        return status

    def read_current(self) -> Mapping[str, object] | None:
        return self._repository.read_whole_scope_current()

    def frozen_editorial_subjects(self) -> tuple[WholeScopeEditorialSubject, ...]:
        raw = self._repository.read_whole_scope_build()
        if raw is None or raw.get("hierarchy_state") != "frozen":
            raise ValueError("Stage E requires a frozen whole-scope hierarchy")
        return _frozen_editorial_subjects(raw)

    def resume(
        self,
        preparation: WholeScopeStagePreparation,
        *,
        provider: NarrativeMapProvider | None,
        consent: NarrativeConsentManifest | None,
        cancelled: CancelledCallback | None = None,
        hierarchy_authority_validator: WholeScopeHierarchyAuthorityValidator | None = None,
    ) -> NarrativeWorkflowReport:
        return self.start(
            preparation,
            provider=provider,
            consent=consent,
            cancelled=cancelled,
            hierarchy_authority_validator=hierarchy_authority_validator,
        )

    def retry(
        self,
        preparation: WholeScopeStagePreparation,
        *,
        provider: NarrativeMapProvider | None,
        consent: NarrativeConsentManifest | None,
        cancelled: CancelledCallback | None = None,
        hierarchy_authority_validator: WholeScopeHierarchyAuthorityValidator | None = None,
    ) -> NarrativeWorkflowReport:
        return self.resume(
            preparation,
            provider=provider,
            consent=consent,
            cancelled=cancelled,
            hierarchy_authority_validator=hierarchy_authority_validator,
        )

    def _require_build(
        self,
        authority: AuthorityBinding,
        scope_id: str,
        source_hash: str,
        correction_id: str,
    ) -> Mapping[str, object]:
        raw = self._repository.read_whole_scope_build()
        if (
            raw is None
            or raw.get("schema") != WHOLE_SCOPE_BUILD_ENVELOPE
            or raw.get("scope_id") != scope_id
            or raw.get("authority") != authority.to_dict()
            or raw.get("source_hash") != source_hash
            or raw.get("correction_id") != correction_id
        ):
            raise ValueError("whole-scope build identity is stale")
        return raw

    def _require_preparation(
        self, preparation: WholeScopeStagePreparation
    ) -> Mapping[str, object]:
        raw = self._require_build(
            preparation.authority,
            preparation.scope_id,
            preparation.source_hash,
            preparation.correction_id,
        )
        prefix = preparation.stage.value
        if (
            raw.get("build_id") != preparation.build_id
            or raw.get(f"{prefix}_transport_batch_id") != preparation.job.job_id
            or raw.get(f"{prefix}_manifest_id") != preparation.consent.manifest_id
        ):
            raise ValueError("whole-scope stage preparation is stale")
        return raw

    def _logical_records(
        self,
        preparation: WholeScopeStagePreparation,
        record: NarrativeJobRecord,
    ) -> tuple[Mapping[str, object], ...]:
        if record.result is None or record.provider_identity is None:
            raise ValueError("whole-scope logical provenance requires validated transport output")
        ordinals = self._repository.whole_scope_submission_ordinals(preparation.job.job_id)
        submission_number = ordinals.get(record.attempt_count)
        if submission_number is None:
            raise ValueError(
                "whole-scope validated transport is missing durable submission identity"
            )
        cache_identity = self._repository.cache_key(
            preparation.job, preparation.consent.profile
        )
        results_by_subject: dict[str, Mapping[str, object]] = {}
        if preparation.stage is WholeScopeSemanticStage.EDITORIAL:
            raw_records = record.result.get("records")
            if not isinstance(raw_records, list):
                raise ValueError("validated editorial batch is missing records")
            for value in raw_records:
                if isinstance(value, Mapping):
                    results_by_subject[
                        f"{value.get('subject_kind')}:{value.get('subject_id')}"
                    ] = value
        payloads: list[Mapping[str, object]] = []
        for logical in preparation.logical_jobs:
            result = (
                record.result
                if logical.stage is WholeScopeSemanticStage.HIERARCHY
                else results_by_subject.get(f"{logical.subject_kind}:{logical.subject_id}")
            )
            if not isinstance(result, Mapping):
                raise ValueError("whole-scope logical result coverage is incomplete")
            provenance = WholeScopeLogicalProvenance(
                logical.stage,
                logical.logical_job_id,
                preparation.job.job_id,
                preparation.job.input_hash,
                record.consent_manifest_id or preparation.consent.manifest_id,
                canonical_hash(record.provider_identity),
                cache_identity,
                preparation.scope_id,
                record.attempt_count,
                submission_number,
            )
            payloads.append(
                {
                    "schema": "m15-whole-scope-logical-job-v1",
                    "build_id": preparation.build_id,
                    "stage": logical.stage.value,
                    "logical_job_id": provenance.logical_job_id,
                    "transport_batch_id": provenance.transport_batch_id,
                    "subject_kind": logical.subject_kind,
                    "subject_id": logical.subject_id,
                    "membership_hash": logical.membership_hash,
                    "input_hash": provenance.input_hash,
                    "manifest_id": provenance.manifest_id,
                    "provider_identity_hash": provenance.provider_identity_hash,
                    "cache_identity": provenance.cache_identity,
                    "scope_id": provenance.scope_id,
                    "attempt": provenance.attempt,
                    "submission_number": provenance.submission_number,
                    "result": dict(result),
                    "result_hash": canonical_hash(result),
                }
            )
        return tuple(payloads)

    def _deferred_completion_report(
        self,
        report: NarrativeWorkflowReport,
        preparation: WholeScopeStagePreparation,
    ) -> NarrativeWorkflowReport:
        current = self._repository.read_whole_scope_build()
        durable_cancelled = bool(
            current is not None
            and current.get(f"{preparation.stage.value}_state") == "cancelled"
        )
        job_id = preparation.job.job_id
        return NarrativeWorkflowReport(
            validated_job_ids=tuple(
                value for value in report.validated_job_ids if value != job_id
            ),
            failed_job_ids=tuple(value for value in report.failed_job_ids if value != job_id),
            cache_hits=report.cache_hits,
            provider_calls=report.provider_calls,
            input_tokens=report.input_tokens,
            output_tokens=report.output_tokens,
            elapsed_ms=report.elapsed_ms,
            cancelled=report.cancelled or durable_cancelled,
            deferred_job_ids=tuple(dict.fromkeys((*report.deferred_job_ids, job_id))),
            terminal_reservations=report.terminal_reservations,
        )

    def _publish(
        self,
        build: dict[str, object],
        preparation: WholeScopeStagePreparation,
        editorial_records: Sequence[Mapping[str, object]],
        *,
        expected_running: Mapping[str, object],
    ) -> bool:
        hierarchy = build.get("authoritative_hierarchy")
        hierarchy_result = build.get("hierarchy_result")
        editorial_result = build.get("editorial_result")
        if not all(
            isinstance(item, Mapping)
            for item in (hierarchy, hierarchy_result, editorial_result)
        ):
            raise ValueError("whole-scope publication requires frozen hierarchy and editorial data")
        all_records = tuple(
            item
            for item in self._repository.read_whole_scope_logical_records()
            if item.get("build_id") == preparation.build_id
        )
        logical_records = tuple(
            item for item in (*all_records, *editorial_records) if isinstance(item, Mapping)
        )
        by_id = {cast(str, item["logical_job_id"]): item for item in logical_records}
        expected_ids = tuple(
            cast(str, item["logical_job_id"])
            for key in ("hierarchy_logical_jobs", "editorial_logical_jobs")
            for item in cast(list[Mapping[str, object]], build.get(key, []))
        )
        if set(by_id) != set(expected_ids):
            raise ValueError("whole-scope publication logical provenance is incomplete")
        publication: dict[str, object] = {
            "schema": WHOLE_SCOPE_PUBLICATION_SCHEMA,
            "build_id": preparation.build_id,
            "scope_id": preparation.scope_id,
            "authority": preparation.authority.to_dict(),
            "source_hash": preparation.source_hash,
            "correction_id": preparation.correction_id,
            "hierarchy_hash": build["hierarchy_hash"],
            "hierarchy_proposal": dict(cast(Mapping[str, object], hierarchy_result)),
            "authoritative_hierarchy": dict(cast(Mapping[str, object], hierarchy)),
            "editorial_batch": dict(cast(Mapping[str, object], editorial_result)),
            "logical_provenance": [
                dict(by_id[logical_id]) for logical_id in expected_ids
            ],
        }
        publication_hash = canonical_hash(publication)
        publication["publication_hash"] = publication_hash
        build["publication_hash"] = publication_hash
        return self._repository.write_whole_scope_build_if_stage(
            build,
            expected_build=expected_running,
            stage="editorial",
            manifest_id=preparation.consent.manifest_id,
            expected_state="running",
            logical_records=editorial_records,
            publication=publication,
        )

    def _status(self, raw: Mapping[str, object]) -> WholeScopeSemanticStatus:
        authority = _authority(raw.get("authority"))
        records = tuple(
            record
            for kind, key in (
                (ProviderJobKind.WHOLE_SCOPE_HIERARCHY, "hierarchy_transport_batch_id"),
                (ProviderJobKind.WHOLE_SCOPE_EDITORIAL, "editorial_transport_batch_id"),
            )
            for job_id in (raw.get(key),)
            if isinstance(job_id, str)
            for record in (self._repository.get(kind, job_id),)
            if record is not None
        )
        usage_values = tuple(record.usage for record in records if record.usage is not None)
        logical_jobs = sum(
            len(cast(list[object], raw.get(key, [])))
            for key in ("hierarchy_logical_jobs", "editorial_logical_jobs")
        )
        return WholeScopeSemanticStatus(
            cast(str, raw["build_id"]),
            cast(str, raw["scope_id"]),
            authority,
            cast(str, raw["source_hash"]),
            cast(str, raw["correction_id"]),
            cast(str, raw["hierarchy_state"]),
            cast(str, raw["editorial_state"]),
            cast(str | None, raw.get("hierarchy_hash")),
            cast(str | None, raw.get("publication_hash")),
            tuple(cast(list[str], raw.get("failure_codes", []))),
            WholeScopeSemanticAccounting(
                logical_jobs=logical_jobs,
                transport_submissions=sum(record.provider_calls for record in records),
                cache_hits=cast(int, raw.get("cache_hits", 0)),
                input_tokens=sum(cast(int, item.get("input_tokens", 0)) for item in usage_values),
                output_tokens=sum(cast(int, item.get("output_tokens", 0)) for item in usage_values),
                elapsed_ms=sum(cast(int, item.get("elapsed_ms", 0)) for item in usage_values),
                combined_submission_count=self._repository.whole_scope_submission_count(),
            ),
        )


def _whole_scope_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    try:
        decoded = storage.decode_json(storage.canonical_json(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must contain canonical JSON values") from None
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} must be an object")
    validate_privacy_safe_keys(decoded, label=label, allow_raw_content=True)
    return cast(dict[str, object], decoded)


def _whole_scope_strings(
    values: Sequence[str], label: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    result = tuple(values)
    if (not allow_empty and not result) or len(result) != len(set(result)) or any(
        not value or value != value.strip() for value in result
    ):
        raise ValueError(f"{label} values must be unique non-empty strings")
    return result


def _whole_scope_text(value: str, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"whole-scope {label} must be non-empty and trimmed")
    return value


def _validate_whole_scope_limits(maximum_provider_calls: int) -> None:
    if (
        not isinstance(maximum_provider_calls, int)
        or isinstance(maximum_provider_calls, bool)
        or not 1 <= maximum_provider_calls <= 2
    ):
        raise ValueError("each whole-scope stage permits one initial and at most one repair")


def _validate_stage_h_input(
    payload: Mapping[str, object],
    authority: AuthorityBinding,
    scope_id: str,
    ordered_unit_ids: tuple[str, ...],
    known_evidence_ids: tuple[str, ...],
) -> None:
    expected_fields = {
        "schema",
        "scope_id",
        "authority",
        "ordered_unit_ids",
        "units",
        "hard_locks",
    }
    units = payload.get("units")
    hard_locks = payload.get("hard_locks")
    if set(payload) != expected_fields or not isinstance(units, list) or not isinstance(
        hard_locks, list
    ):
        raise ValueError("Stage H input shape is not exact")
    unit_fields = {
        "unit_id",
        "sequence_id",
        "ordinal",
        "parent_choice_id",
        "parent_arm_id",
        "evidence_ids",
    }
    supplied_units: list[str] = []
    allowed_evidence = set(known_evidence_ids)
    for item in units:
        item_evidence = item.get("evidence_ids") if isinstance(item, Mapping) else None
        if (
            not isinstance(item, Mapping)
            or not {"unit_id", "evidence_ids"} <= set(item) <= unit_fields
            or not isinstance(item.get("unit_id"), str)
            or not isinstance(item_evidence, list)
            or not item_evidence
            or any(
                not isinstance(evidence_id, str) or evidence_id not in allowed_evidence
                for evidence_id in item_evidence
            )
            or len(item_evidence) != len(set(cast(list[str], item_evidence)))
            or (
                "sequence_id" in item
                and (not isinstance(item["sequence_id"], str) or not item["sequence_id"])
            )
            or (
                "ordinal" in item
                and (
                    not isinstance(item["ordinal"], int)
                    or isinstance(item["ordinal"], bool)
                    or item["ordinal"] < 0
                )
            )
            or any(
                key in item
                and item[key] is not None
                and (not isinstance(item[key], str) or not item[key])
                for key in ("parent_choice_id", "parent_arm_id")
            )
        ):
            raise ValueError("Stage H input shape is not exact")
        supplied_units.append(cast(str, item.get("unit_id")))
    lock_variants = (
        {"lock_id", "kind", "choice_id", "arm_ids"},
        {"lock_id", "kind", "unit_ids"},
    )
    allowed_choices = {
        cast(str, item["parent_choice_id"])
        for item in cast(list[Mapping[str, object]], units)
        if isinstance(item.get("parent_choice_id"), str)
    }
    allowed_arms = {
        cast(str, item["parent_arm_id"])
        for item in cast(list[Mapping[str, object]], units)
        if isinstance(item.get("parent_arm_id"), str)
    }
    for item in hard_locks:
        if (
            not isinstance(item, Mapping)
            or set(item) not in lock_variants
            or not isinstance(item.get("lock_id"), str)
            or not item.get("lock_id")
            or not isinstance(item.get("kind"), str)
        ):
            raise ValueError("Stage H input shape is not exact")
        if any(
            key in item
            and (
                not isinstance(item[key], list)
                or any(not isinstance(value, str) for value in cast(list[object], item[key]))
            )
            for key in ("arm_ids", "unit_ids")
        ):
            raise ValueError("Stage H input shape is not exact")
        if set(item) == lock_variants[0] and (
            item.get("kind") != "choice_ownership"
            or item.get("choice_id") not in allowed_choices
            or not cast(list[object], item.get("arm_ids"))
            or any(arm_id not in allowed_arms for arm_id in cast(list[object], item["arm_ids"]))
        ):
            raise ValueError("Stage H input shape is not exact")
        if set(item) == lock_variants[1] and (
            item.get("kind") != "scope_marker"
            or not cast(list[object], item.get("unit_ids"))
            or any(
                unit_id not in ordered_unit_ids
                for unit_id in cast(list[object], item["unit_ids"])
            )
        ):
            raise ValueError("Stage H input shape is not exact")
    if (
        payload.get("schema") != M15_WHOLE_SCOPE_HIERARCHY_INPUT_SCHEMA
        or payload.get("scope_id") != scope_id
        or payload.get("authority") != authority.to_dict()
        or payload.get("ordered_unit_ids") != list(ordered_unit_ids)
        or supplied_units != list(ordered_unit_ids)
    ):
        raise ValueError("Stage H input identity is not exact")


def _validate_stage_e_input(
    payload: Mapping[str, object],
    authority: AuthorityBinding,
    scope_id: str,
    hierarchy_hash: str,
    subjects: Sequence[WholeScopeEditorialSubject],
) -> None:
    if set(payload) != {
        "schema",
        "scope_id",
        "authority",
        "hierarchy_hash",
        "subjects",
        "evidence",
    }:
        raise ValueError("Stage E input shape is not exact")
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("Stage E input shape is not exact")
    allowed_evidence = {evidence_id for item in subjects for evidence_id in item.evidence_ids}
    supplied_evidence: list[str] = []
    for item in evidence:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"evidence_id", "text"}
            or not isinstance(item.get("evidence_id"), str)
            or item.get("evidence_id") not in allowed_evidence
            or not isinstance(item.get("text"), str)
            or not cast(str, item.get("text")).strip()
        ):
            raise ValueError("Stage E input shape is not exact")
        supplied_evidence.append(cast(str, item.get("evidence_id")))
    if len(supplied_evidence) != len(set(supplied_evidence)):
        raise ValueError("Stage E input shape is not exact")
    if (
        payload.get("schema") != M15_WHOLE_SCOPE_EDITORIAL_INPUT_SCHEMA
        or payload.get("scope_id") != scope_id
        or payload.get("authority") != authority.to_dict()
        or payload.get("hierarchy_hash") != hierarchy_hash
        or payload.get("subjects") != [item.to_dict() for item in subjects]
        or set(supplied_evidence) != allowed_evidence
    ):
        raise ValueError("Stage E input identity is not exact")


def derive_frozen_editorial_authority(
    outline: SemanticOutline,
    units: Sequence[object],
    evidence: Sequence[Mapping[str, object]],
    hierarchy_hash: str,
) -> tuple[tuple[WholeScopeEditorialSubject, ...], list[dict[str, object]]]:
    from renpy_story_mapper.narrative_map.semantic_contracts import FineNarrativeUnit

    materialized_units = tuple(units)
    if not all(isinstance(item, FineNarrativeUnit) for item in materialized_units):
        raise ValueError("frozen editorial authority requires fine narrative units")
    typed_units = cast(tuple[FineNarrativeUnit, ...], materialized_units)
    unit_by_id = {item.unit_id: item for item in typed_units}
    if tuple(unit_by_id) != outline.ordered_unit_ids:
        raise ValueError("frozen editorial units do not match the authoritative outline")
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
                raise ValueError("frozen editorial choice authority contains a cycle")
            if current_id in owned:
                return
            current = choice_by_id.get(current_id)
            if current is None:
                raise ValueError("frozen editorial choice authority is incomplete")
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
        if not ordered:
            parent_cluster = choice_by_id[choice_id].parent_cluster_id
            return cluster_units(parent_cluster)
        return ordered

    subject_memberships: list[tuple[str, str, tuple[str, ...]]] = [
        *(("beat", item.beat_id, item.ordered_unit_ids) for item in outline.beats),
        *(
            ("major_cluster", item.cluster_id, cluster_units(item.cluster_id))
            for item in outline.clusters
        ),
        *(("choice", item.choice_id, choice_units(item.choice_id)) for item in outline.choices),
    ]
    subjects = tuple(
        WholeScopeEditorialSubject(
            subject_kind,
            subject_id,
            canonical_hash(
                {
                    "hierarchy_hash": hierarchy_hash,
                    "subject_kind": subject_kind,
                    "subject_id": subject_id,
                    "ordered_unit_ids": list(ordered_unit_ids),
                }
            ),
            tuple(
                dict.fromkeys(
                    evidence_id
                    for unit_id in ordered_unit_ids
                    for evidence_id in unit_by_id[unit_id].evidence_ids
                )
            ),
            tuple(
                dict.fromkeys(
                    speaker
                    for unit_id in ordered_unit_ids
                    for speaker in unit_by_id[unit_id].speaker_ids
                )
            ),
        )
        for subject_kind, subject_id, ordered_unit_ids in subject_memberships
    )
    expected_evidence_ids = tuple(
        dict.fromkeys(evidence_id for item in subjects for evidence_id in item.evidence_ids)
    )
    normalized_evidence: list[dict[str, object]] = []
    for item in evidence:
        if (
            set(item) != {"evidence_id", "text"}
            or not isinstance(item.get("evidence_id"), str)
            or not isinstance(item.get("text"), str)
            or not cast(str, item["text"]).strip()
        ):
            raise ValueError("frozen editorial evidence shape is not exact")
        normalized_evidence.append(dict(item))
    if tuple(item["evidence_id"] for item in normalized_evidence) != expected_evidence_ids:
        raise ValueError("frozen editorial evidence is foreign, missing, duplicate, or reordered")
    return subjects, normalized_evidence


def _frozen_editorial_subjects(
    raw: Mapping[str, object],
) -> tuple[WholeScopeEditorialSubject, ...]:
    values = raw.get("frozen_editorial_subjects")
    if not isinstance(values, list) or not values:
        raise ValueError("frozen editorial subject authority is unavailable")
    subjects: list[WholeScopeEditorialSubject] = []
    for item in values:
        if not isinstance(item, Mapping) or set(item) != {
            "subject_kind",
            "subject_id",
            "membership_hash",
            "evidence_ids",
            "known_characters",
        }:
            raise ValueError("frozen editorial subject authority is malformed")
        evidence_ids = item.get("evidence_ids")
        characters = item.get("known_characters")
        if not isinstance(evidence_ids, list) or not isinstance(characters, list):
            raise ValueError("frozen editorial subject authority is malformed")
        subjects.append(
            WholeScopeEditorialSubject(
                cast(str, item.get("subject_kind")),
                cast(str, item.get("subject_id")),
                cast(str, item.get("membership_hash")),
                tuple(cast(list[str], evidence_ids)),
                tuple(cast(list[str], characters)),
            )
        )
    return tuple(subjects)


def _whole_scope_logical_job_payload(job: WholeScopeLogicalJob) -> dict[str, object]:
    return {
        "stage": job.stage.value,
        "logical_job_id": job.logical_job_id,
        "subject_kind": job.subject_kind,
        "subject_id": job.subject_id,
        "membership_hash": job.membership_hash,
    }


def _new_build_payload(
    build_id: str,
    authority: AuthorityBinding,
    source_hash: str,
    correction_id: str,
    privacy_scope: str,
    jobs: Sequence[PreparedNarrativeJob],
    consent: NarrativeConsentManifest,
    profile: ProviderProfile,
) -> dict[str, object]:
    return {
        "schema": SEMANTIC_BUILD_ENVELOPE,
        "build_id": build_id,
        "authority": authority.to_dict(),
        "source_hash": source_hash,
        "correction_id": correction_id,
        "privacy_scope": privacy_scope,
        "profile_hash": canonical_hash(profile.to_dict()),
        "state": SemanticBuildState.AWAITING_BOUNDARY_CONSENT.value,
        "state_history": [
            SemanticBuildState.BOUNDARIES_PREPARED.value,
            SemanticBuildState.AWAITING_BOUNDARY_CONSENT.value,
        ],
        "boundary_manifest_id": consent.manifest_id,
        "boundary_manifest": consent.identity_dict(),
        "boundary_accounted_manifest_id": consent.manifest_id,
        "boundary_accounted_reservation_count": 0,
        "boundary_accounted_record_hashes": {},
        "boundary_job_ids": [job.job_id for job in jobs],
        "boundary_job_identity_hash": _jobs_hash(jobs),
        "membership_hash": None,
        "summary_manifest_id": None,
        "summary_manifest": None,
        "summary_accounted_manifest_id": None,
        "summary_accounted_reservation_count": 0,
        "summary_accounted_record_hashes": {},
        "boundary_reconciled_manifest_ids": [],
        "summary_reconciled_manifest_ids": [],
        "summary_job_ids": [],
        "summary_job_identity_hash": None,
        "published_map_hash": None,
        "completed_boundary_job_ids": [],
        "completed_summary_job_ids": [],
        "failure_codes": [],
        "accounting": _accounting_payload(SemanticAccounting()),
        "boundary_accounting": _accounting_payload(SemanticAccounting()),
        "summary_accounting": _accounting_payload(SemanticAccounting()),
        "confirmed_manifest_ids": [],
        "confirmed_manifests": {},
        "confirmed_manifest_stages": {},
        "outline": None,
        "quotient_topology": None,
        "cancel_requested": False,
    }


def _status_from_payload(raw: Mapping[str, object]) -> SemanticStatusView:
    authority = _authority(raw.get("authority"))
    record = SemanticBuildRecord(
        authority,
        SemanticBuildState(cast(str, raw["state"])),
        _optional_string(raw.get("boundary_manifest_id")),
        _optional_string(raw.get("membership_hash")),
        _optional_string(raw.get("summary_manifest_id")),
        _optional_string(raw.get("published_map_hash")),
        _strings(raw.get("completed_boundary_job_ids"), "completed boundary jobs"),
        _strings(raw.get("completed_summary_job_ids"), "completed summary jobs"),
        _strings(raw.get("failure_codes"), "semantic failure codes"),
    )
    current = raw.get("published_map_hash")
    return SemanticStatusView(
        cast(str, raw["build_id"]),
        record,
        cast(str, raw["source_hash"]),
        cast(str, raw["correction_id"]),
        cast(str, raw["privacy_scope"]),
        _strings(raw.get("boundary_job_ids"), "boundary job IDs"),
        _strings(raw.get("summary_job_ids"), "summary job IDs"),
        _accounting_from_payload(raw.get("accounting")),
        cast(str | None, current),
    )


def _updated_state(
    raw: Mapping[str, object],
    state: SemanticBuildState,
) -> dict[str, object]:
    updated = dict(raw)
    updated["state"] = state.value
    history = _string_list(raw.get("state_history"))
    if not history or history[-1] != state.value:
        history.append(state.value)
    updated["state_history"] = history
    return updated


def _restore_manifest(
    value: Mapping[str, object],
    profile: ProviderProfile,
) -> NarrativeConsentManifest:
    if value.get("profile") != profile.to_dict():
        raise ValueError("persisted semantic consent profile does not match")
    return NarrativeConsentManifest(
        run_id=cast(str, value["run_id"]),
        profile=profile,
        job_ids=_strings(value.get("job_ids"), "manifest job IDs"),
        job_identity_hashes=_strings(
            value.get("job_identity_hashes"), "manifest job identity hashes"
        ),
        job_identity_hash=cast(str, value["job_identity_hash"]),
        issued_utc=cast(str, value["issued_utc"]),
        expires_utc=cast(str, value["expires_utc"]),
        maximum_provider_calls=cast(int, value["maximum_provider_calls"]),
        maximum_input_bytes=cast(int, value["maximum_input_bytes"]),
        maximum_output_bytes=cast(int, value["maximum_output_bytes"]),
        timeout_seconds=float(cast(float, value["timeout_seconds"])),
        consent_granted=False,
        repair_policy_version=cast(str | None, value.get("repair_policy_version")),
        version=cast(str, value["version"]),
    )


def _manifest_duration(consent: NarrativeConsentManifest) -> timedelta:
    from datetime import datetime

    issued = datetime.fromisoformat(consent.issued_utc)
    expires = datetime.fromisoformat(consent.expires_utc)
    return expires - issued


def _jobs_hash(jobs: Sequence[PreparedNarrativeJob]) -> str:
    return canonical_hash([job.durable_metadata() for job in jobs])


def _accounting_from_payload(value: object) -> SemanticAccounting:
    if not isinstance(value, Mapping):
        raise ValueError("semantic accounting is unavailable")
    names = (
        "provider_calls",
        "reserved_provider_calls",
        "input_tokens",
        "output_tokens",
        "elapsed_ms",
        "cache_hits",
    )
    if any(
        not isinstance(value.get(name), int)
        or isinstance(value.get(name), bool)
        or cast(int, value.get(name)) < 0
        for name in names
    ):
        raise ValueError("semantic accounting is invalid")
    return SemanticAccounting(
        provider_calls=cast(int, value["provider_calls"]),
        reserved_provider_calls=cast(int, value["reserved_provider_calls"]),
        input_tokens=cast(int, value["input_tokens"]),
        output_tokens=cast(int, value["output_tokens"]),
        elapsed_ms=cast(int, value["elapsed_ms"]),
        cache_hits=cast(int, value["cache_hits"]),
    )


def _accounting_payload(value: SemanticAccounting) -> dict[str, int]:
    return {
        "provider_calls": value.provider_calls,
        "reserved_provider_calls": value.reserved_provider_calls,
        "input_tokens": value.input_tokens,
        "output_tokens": value.output_tokens,
        "elapsed_ms": value.elapsed_ms,
        "cache_hits": value.cache_hits,
    }


def _record_hash_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(
        not isinstance(job_id, str)
        or not job_id
        or not isinstance(fingerprint, str)
        or not fingerprint
        for job_id, fingerprint in value.items()
    ):
        raise ValueError("semantic accounted record hashes are invalid")
    return {cast(str, job_id): cast(str, fingerprint) for job_id, fingerprint in value.items()}


def _manifest_snapshot_mapping(value: object) -> dict[str, Mapping[str, object]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(
        not isinstance(manifest_id, str)
        or not manifest_id
        or not isinstance(identity, Mapping)
        for manifest_id, identity in value.items()
    ):
        raise ValueError("confirmed semantic manifest snapshots are invalid")
    return {
        cast(str, manifest_id): dict(cast(Mapping[str, object], identity))
        for manifest_id, identity in value.items()
    }


def _manifest_stage_mapping(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or any(
        not isinstance(manifest_id, str)
        or not manifest_id
        or stage not in {"boundary", "summary"}
        for manifest_id, stage in value.items()
    ):
        raise ValueError("confirmed semantic manifest stages are invalid")
    return {cast(str, manifest_id): cast(str, stage) for manifest_id, stage in value.items()}


def _record_accounting_fingerprint(record: NarrativeJobRecord) -> str:
    return canonical_hash(
        {
            "job_id": record.job_id,
            "status": record.status.value,
            "attempt_count": record.attempt_count,
            "provider_calls": record.provider_calls,
            "usage": None if record.usage is None else dict(record.usage),
            "error_code": record.error_code,
            "consent_manifest_id": record.consent_manifest_id,
        }
    )


def _reservation_accounting_checkpoint(
    payload: Mapping[str, object],
    *,
    prefix: str,
    manifest_id: str,
    durable_reservations: int,
    stage_accounting: SemanticAccounting,
) -> int:
    accounted_manifest_id = payload.get(f"{prefix}_accounted_manifest_id")
    accounted_reservations = payload.get(f"{prefix}_accounted_reservation_count")
    if accounted_manifest_id is None and accounted_reservations is None:
        return min(stage_accounting.reserved_provider_calls, durable_reservations)
    if accounted_manifest_id != manifest_id:
        raise ValueError("semantic reservation accounting manifest is stale")
    if (
        not isinstance(accounted_reservations, int)
        or isinstance(accounted_reservations, bool)
        or not 0 <= accounted_reservations <= durable_reservations
    ):
        raise ValueError("semantic reservation accounting checkpoint is invalid")
    return accounted_reservations


def _usage_integer(value: Mapping[str, object], name: str) -> int:
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError("durable semantic job usage is invalid")
    return item


def _summary_payload(summary: SemanticSummary) -> dict[str, object]:
    return {
        "subject_kind": summary.subject_kind,
        "subject_id": summary.subject_id,
        "membership_hash": summary.membership_hash,
        "title": summary.title,
        "summary": summary.summary,
        "characters": list(summary.characters),
        "claims": [
            {
                "claim_class": claim.claim_class.value,
                "text": claim.text,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in summary.claims
        ],
        "warnings": list(summary.warnings),
    }


def _authority(value: object) -> AuthorityBinding:
    if not isinstance(value, Mapping):
        raise ValueError("semantic build authority is invalid")
    return AuthorityBinding(
        cast(str, value["source_generation"]),
        cast(str, value["canonical_schema"]),
        cast(str, value["canonical_hash"]),
        cast(str, value["atom_schema"]),
        cast(str, value["atom_hash"]),
    )


def _typed[T](values: Sequence[object], kind: type[T], label: str) -> tuple[T, ...]:
    if any(not isinstance(value, kind) for value in values):
        raise TypeError(f"{label} input has the wrong contract type")
    return cast(tuple[T, ...], tuple(values))


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} are invalid")
    return tuple(cast(list[str], value))


def _string_list(value: object) -> list[str]:
    return list(_strings(value, "state history"))


def _optional_string(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError("semantic build optional identity is invalid")

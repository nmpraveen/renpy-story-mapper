"""Supported durable M15.1 two-stage semantic production lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from typing import cast

from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    JsonValue,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.persistence import (
    NarrativeJobStatus,
    NarrativeMapRepository,
)
from renpy_story_mapper.narrative_map.provider import (
    NarrativeConsentManifest,
    NarrativeMapProvider,
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    LiveSemanticProvenance,
    SemanticBoundaryDecision,
    SemanticBuildRecord,
    SemanticBuildState,
    SemanticOutline,
    SemanticSummary,
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
)

SEMANTIC_BUILD_ENVELOPE = "m15-semantic-build-envelope-v2"
SEMANTIC_PUBLICATION_SCHEMA = "m15-semantic-publication-v2"
DEFAULT_PRIVACY_SCOPE = "story_evidence_only"

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
            recovered_accounting, recovered_total, completed, confirmed = recovered
            payload["accounting"] = _accounting_payload(recovered_total)
            payload["boundary_accounting"] = _accounting_payload(recovered_accounting)
            payload["completed_boundary_job_ids"] = list(completed)
            payload["confirmed_manifest_ids"] = list(confirmed)
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
            ) = recovered
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
            raw = _updated_state(raw, running)
            raw["cancel_requested"] = False
            self._repository.write_semantic_build(raw)
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
                return persisted or bool(cancelled and cancelled())

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
        latest = self._require_build(preparation.build_id)
        records = tuple(self._repository.get(job.kind, job.job_id) for job in preparation.jobs)
        completed = tuple(
            job.job_id
            for job, record in zip(preparation.jobs, records, strict=True)
            if record is not None and record.status is NarrativeJobStatus.VALIDATED
        )
        failures = tuple(
            record.error_code
            for record in records
            if record is not None and record.error_code is not None
        )
        updated = dict(latest)
        accounting = _accounting_from_payload(latest.get("accounting"))
        stage_accounting_key = (
            "boundary_accounting"
            if preparation.stage is SemanticStage.BOUNDARIES
            else "summary_accounting"
        )
        stage_accounting = _accounting_from_payload(latest.get(stage_accounting_key))
        reserved_after = self._repository.semantic_reserved_call_count(
            manifest_id=consent.manifest_id,
            maximum_provider_calls=consent.maximum_provider_calls,
        )
        latest_accounted_reservation_count = _reservation_accounting_checkpoint(
            latest,
            prefix=prefix,
            manifest_id=consent.manifest_id,
            durable_reservations=reserved_after,
            stage_accounting=stage_accounting,
        )
        if reserved_after < latest_accounted_reservation_count:
            raise ValueError("durable semantic call accounting moved backwards")
        reserved_delta = reserved_after - latest_accounted_reservation_count
        updated_accounting = _add_report(accounting, report)
        updated_accounting = replace(
            updated_accounting,
            reserved_provider_calls=(
                updated_accounting.reserved_provider_calls + reserved_delta
            ),
        )
        updated["accounting"] = _accounting_payload(updated_accounting)
        updated_stage_accounting = replace(
            _add_report(stage_accounting, report),
            reserved_provider_calls=(
                stage_accounting.reserved_provider_calls + reserved_delta
            ),
        )
        updated[stage_accounting_key] = _accounting_payload(updated_stage_accounting)
        updated[f"{prefix}_accounted_manifest_id"] = consent.manifest_id
        updated[f"{prefix}_accounted_reservation_count"] = reserved_after
        target_key = (
            "completed_boundary_job_ids"
            if preparation.stage is SemanticStage.BOUNDARIES
            else "completed_summary_job_ids"
        )
        updated[target_key] = list(completed)
        updated["failure_codes"] = list(dict.fromkeys(failures))
        updated["cancel_requested"] = False
        if was_complete and not report.failed_job_ids and not report.cancelled:
            if preparation.stage is SemanticStage.SUMMARIES:
                self._publish(preparation, updated)
            return report
        if report.cancelled:
            updated = _updated_state(updated, SemanticBuildState.CANCELLED)
        elif len(completed) == len(preparation.jobs):
            updated = _updated_state(updated, SemanticBuildState.VALIDATING)
            if preparation.stage is SemanticStage.SUMMARIES:
                self._publish(preparation, updated)
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
        self._repository.write_semantic_build(updated)
        return report

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
        provider_calls = 0
        input_tokens = 0
        output_tokens = 0
        elapsed_ms = 0
        for job, record in zip(jobs, records, strict=True):
            if (
                record is None
                or record.status is not NarrativeJobStatus.VALIDATED
                or job.job_id in prior_completed
            ):
                continue
            provider_calls += record.provider_calls
            if record.usage is None:
                continue
            input_tokens += _usage_integer(record.usage, "input_tokens")
            output_tokens += _usage_integer(record.usage, "output_tokens")
            elapsed_ms += _usage_integer(record.usage, "elapsed_ms")
        reserved_delta = 0
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
        return stage_accounting, total_accounting, completed, confirmed

    def _publish(
        self,
        preparation: SemanticStagePreparation,
        build: dict[str, object],
    ) -> None:
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
        self._repository.publish_semantic_current(
            build=completed,
            publication=publication,
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
        "boundary_job_ids": [job.job_id for job in jobs],
        "boundary_job_identity_hash": _jobs_hash(jobs),
        "membership_hash": None,
        "summary_manifest_id": None,
        "summary_manifest": None,
        "summary_accounted_manifest_id": None,
        "summary_accounted_reservation_count": 0,
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


def _add_report(value: SemanticAccounting, report: NarrativeWorkflowReport) -> SemanticAccounting:
    return SemanticAccounting(
        provider_calls=value.provider_calls + report.provider_calls,
        reserved_provider_calls=value.reserved_provider_calls,
        input_tokens=value.input_tokens + report.input_tokens,
        output_tokens=value.output_tokens + report.output_tokens,
        elapsed_ms=value.elapsed_ms + report.elapsed_ms,
        cache_hits=value.cache_hits + report.cache_hits,
    )


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

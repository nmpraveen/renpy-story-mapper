"""Integrated, privacy-safe M13 scene workflow over the durable scheduler.

Preparation is provider-free apart from a local adapter availability check.  It creates one
exact in-memory scope and a disabled consent preview.  Only an explicitly granted copy may enter
the scheduler.  Structured provider packets and provider responses remain memory-only; the sink
persists normalized identities, metrics, sanitized errors, validated claims, and artifacts.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, cast

from renpy_story_mapper.narrative.authority import NarrativeAuthority, load_narrative_authority
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    AttemptOutcome,
    BudgetLimits,
    CacheIdentity,
    ConsentManifest,
    JsonValue,
    PrivacyMode,
    ProviderIdentity,
    ProviderSettings,
    canonical_hash,
)
from renpy_story_mapper.narrative.persistence import (
    LookupState,
    M13Persistence,
    RecordKind,
    sanitized_error,
)
from renpy_story_mapper.narrative.preparation import (
    PreparedSceneJob,
    PreparedSceneRun,
    ProviderPricing,
    build_cloud_consent,
    plan_scene_run,
    prepare_scene_jobs,
)
from renpy_story_mapper.narrative.projection import NarrativeInputMode
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    NarrativeProvider,
    ProviderStatus,
)
from renpy_story_mapper.narrative.scheduler import (
    CacheReplay,
    NarrativeScheduler,
    ScheduledSceneJob,
    SchedulerAttemptRecord,
    SchedulerBatchRecord,
    SchedulerJobRecord,
    SchedulerPolicy,
    SchedulerRunRecord,
    SchedulerRunResult,
    ValidatedLogicalOutput,
)
from renpy_story_mapper.narrative.sizing import estimate_complete_run
from renpy_story_mapper.narrative.validation import ValidationContext, validate_and_salvage
from renpy_story_mapper.project import Project

CancelledCallback = Callable[[], bool]
_EMPTY_PROVIDER_SETTINGS: Final = ProviderSettings()


@dataclass(frozen=True)
class PreparedNarrativeRun:
    """One exact, memory-only scene run awaiting a single explicit consent."""

    authority: NarrativeAuthority
    scene_run: PreparedSceneRun
    scheduled_jobs: tuple[ScheduledSceneJob, ...]
    consent_preview: ConsentManifest
    provider_status: ProviderStatus
    include_m12_material: bool

    def __post_init__(self) -> None:
        if self.consent_preview.consent_granted:
            raise ValueError("a prepared run must remain disabled until explicit consent")
        if len(self.scheduled_jobs) != len(self.scene_run.jobs):
            raise ValueError("prepared scene and scheduled job counts differ")
        if any(
            scheduled.logical_job_id != prepared.job.spec.job_id
            for scheduled, prepared in zip(
                self.scheduled_jobs,
                self.scene_run.jobs,
                strict=True,
            )
        ):
            raise ValueError("prepared scene ownership changed before scheduling")

    @property
    def preparation_id(self) -> str:
        material = {
            "authority": self.authority.binding.to_dict(),
            "consent_preview": self.consent_preview.to_dict(),
            "cache_keys": [item.cache_identity.key for item in self.scheduled_jobs],
        }
        return f"m13_preparation_{canonical_hash(material)}"

    def preview_dict(self) -> dict[str, JsonValue]:
        consent = self.consent_preview
        status = self.provider_status
        return {
            "schema": "m13-run-preparation-v1",
            "preparation_id": self.preparation_id,
            "run_id": consent.run_id,
            "authority_hash": self.authority.binding.identity,
            "provider": consent.provider.to_dict(),
            "provider_available": status.available,
            "provider_cli_version": status.cli_version,
            "provider_message_code": status.message_code,
            "selected_scope_ids": list(consent.selected_scope_ids),
            "privacy_mode": consent.privacy_mode.value,
            "includes_m12_material": consent.includes_m12_material,
            "estimate": consent.estimate.to_dict(),
            "limits": consent.limits.to_dict(),
            "consent_granted": False,
        }


def prepare_narrative_scene_run(
    project: Project,
    provider: NarrativeProvider,
    *,
    run_id: str,
    requested_model: str,
    settings: ProviderSettings = _EMPTY_PROVIDER_SETTINGS,
    mode: NarrativeInputMode,
    include_m12_material: bool,
    limits: BudgetLimits,
    batch_limits: BatchLimits,
    selected_scene_ids: tuple[str, ...] | None = None,
    locale: str = "und",
    perspective: str = "default",
    pricing: ProviderPricing | None = None,
) -> PreparedNarrativeRun:
    """Prepare exact scene work and a disabled manifest without sending story material."""

    if not run_id.strip() or not requested_model.strip():
        raise ValueError("run ID and requested model must be non-empty")
    status = provider.status()
    identity = ProviderIdentity(
        provider=status.provider,
        adapter=status.adapter,
        adapter_version=status.adapter_version,
        requested_model=requested_model,
        resolved_model=requested_model,
        settings=settings,
    )
    # Always bind the complete current M12 selection.  The material toggle controls provider
    # projection only, so a later route-result change still invalidates an older artifact.
    authority = load_narrative_authority(project, include_m12=True)
    prepared_jobs = prepare_scene_jobs(
        authority,
        mode=mode,
        include_m12_material=include_m12_material,
        selected_scene_ids=selected_scene_ids,
        locale=locale,
        perspective=perspective,
    )
    scene_run = plan_scene_run(prepared_jobs, batch_limits=batch_limits, pricing=pricing)
    scope_id = (
        "project:all-current-scenes"
        if selected_scene_ids is None
        else "scene-selection:" + canonical_hash({"scene_ids": sorted(selected_scene_ids)})[:24]
    )
    scheduled = tuple(
        _scheduled_scene_job(item, identity, pricing, scope_id=scope_id) for item in scene_run.jobs
    )
    complete_estimate = estimate_complete_run(
        scene_run,
        authority.scene_model,
        pricing=pricing,
    )
    manifest_run = replace(scene_run, estimate=complete_estimate)
    consent = build_cloud_consent(
        manifest_run,
        run_id=run_id,
        provider=identity,
        selected_scope_ids=(scope_id,),
        privacy_mode=(
            PrivacyMode.FACT_ONLY
            if mode is NarrativeInputMode.FACT_ONLY
            else PrivacyMode.STORY_TEXT
        ),
        includes_m12_material=include_m12_material,
        limits=limits,
        consent_granted=False,
    )
    return PreparedNarrativeRun(
        authority,
        scene_run,
        scheduled,
        consent,
        status,
        include_m12_material,
    )


def grant_narrative_consent(
    project: Project,
    prepared: PreparedNarrativeRun,
) -> ConsentManifest:
    """Persist the one exact manifest only after the caller explicitly confirms it."""

    consent = replace(prepared.consent_preview, consent_granted=True)
    if consent.manifest_id != prepared.consent_preview.manifest_id:
        raise ValueError("granted consent ID differs from the prepared manifest ID")
    project.m13_persistence().put_consent(
        consent.manifest_id,
        consent.to_dict(),
        authority_binding=prepared.authority.binding.to_dict(),
    )
    return consent


def run_prepared_scene_jobs(
    project: Project,
    provider: NarrativeProvider,
    prepared: PreparedNarrativeRun,
    consent: ConsentManifest,
    *,
    policy: SchedulerPolicy,
    cancelled: CancelledCallback = lambda: False,
) -> SchedulerRunResult:
    """Run the exact granted scene scope and atomically retain every valid item."""

    if not consent.consent_granted:
        raise ValueError("narrative cloud consent was not granted")
    if consent.manifest_id != prepared.consent_preview.manifest_id:
        raise ValueError("granted consent ID differs from the prepared manifest ID")
    if replace(consent, consent_granted=False) != prepared.consent_preview:
        raise ValueError("granted consent differs from the prepared manifest")
    current = load_narrative_authority(project, include_m12=True)
    if current.binding != prepared.authority.binding:
        raise ValueError("narrative authority changed after consent preparation")
    sink = M13SchedulerPersistenceSink(
        project.m13_persistence(),
        prepared.scheduled_jobs,
        authority_binding=current.binding.to_dict(),
        cancelled=cancelled,
    )
    contexts = {
        item.job.spec.job_id: ValidationContext(
            job=item.job.spec,
            input_revision_id=item.job.input_revision.identity,
            handles=item.handles,
            deterministic_title=item.deterministic_title,
        )
        for item in prepared.scene_run.jobs
    }

    def validate(
        job: ScheduledSceneJob,
        raw: Mapping[str, JsonValue],
    ) -> ValidatedLogicalOutput:
        result = validate_and_salvage(raw, contexts[job.logical_job_id])
        if result.artifact is None:
            raise ValueError(result.rejected_reason or "provider output is not publishable")
        artifact = result.artifact
        return ValidatedLogicalOutput(
            logical_job_id=job.logical_job_id,
            artifact_id=artifact.artifact_id,
            publication=artifact.publication,
            payload=artifact.normalized_dict(),
            validated_claim_count=len(artifact.claims),
            invalid_claim_count=artifact.coverage.invalid_claim_count,
        )

    return NarrativeScheduler(provider, sink, policy).run(
        prepared.scheduled_jobs,
        consent,
        validate,
        cancelled=cancelled,
    )


class M13SchedulerPersistenceSink:
    """Scheduler sink over independently keyed, authority-bound M13 payloads."""

    def __init__(
        self,
        persistence: M13Persistence,
        jobs: Sequence[ScheduledSceneJob],
        *,
        authority_binding: Mapping[str, object],
        cancelled: CancelledCallback = lambda: False,
    ) -> None:
        self._persistence = persistence
        self._jobs = {item.logical_job_id: item for item in jobs}
        if len(self._jobs) != len(jobs):
            raise ValueError("persistence sink jobs must have unique logical identities")
        self._authority = dict(authority_binding)
        self._cancelled = cancelled
        self._histories: dict[tuple[str, str], list[AttemptOutcome]] | None = None

    def lookup_exact_cache(self, job: ScheduledSceneJob) -> CacheReplay | None:
        result = self._persistence.lookup_cache(
            job.cache_identity.to_dict(),
            authority_binding=self._authority,
        )
        if result.state is not LookupState.HIT or result.artifact is None:
            return None
        artifact_id = result.entry.get("artifact_id") if result.entry is not None else None
        publication = result.artifact.get("publication")
        if not isinstance(artifact_id, str) or not isinstance(publication, str):
            raise ValueError("exact cache hit has invalid artifact metadata")
        return CacheReplay(artifact_id, ArtifactPublication(publication))

    def attempt_history(
        self,
        run_id: str,
        logical_job_id: str,
    ) -> tuple[AttemptOutcome, ...]:
        if self._histories is None:
            self._histories = self._load_histories()
        return tuple(self._histories.get((run_id, logical_job_id), ()))

    def record_job(self, record: SchedulerJobRecord) -> None:
        job = self._require_job(record.logical_job_id)
        payload = job.logical_job.to_dict()
        payload.update(record.to_dict())
        payload["status"] = record.state.value
        if record.error_code is not None:
            payload["latest_error"] = cast(JsonValue, sanitized_error(record.error_code))
        self._persistence.put_job(
            record.logical_job_id,
            payload,
            authority_binding=self._authority,
        )

    def record_attempt(self, record: SchedulerAttemptRecord) -> None:
        payload = record.to_dict()
        if record.error_code is not None:
            payload["error"] = cast(JsonValue, sanitized_error(record.error_code))
        self._persistence.put_attempt(
            record.attempt_id,
            payload,
            authority_binding=self._authority,
        )
        if self._histories is not None:
            self._histories.setdefault((record.run_id, record.logical_job_id), []).append(
                record.outcome
            )

    def record_batch(self, record: SchedulerBatchRecord) -> None:
        record_id = "m13_batch_" + canonical_hash(
            {
                "run_id": record.run_id,
                "batch_id": record.batch_id,
                "provider_call_number": record.provider_call_number,
                "state": record.state.value,
            }
        )
        payload = record.to_dict()
        if record.error_code is not None:
            payload["error"] = cast(JsonValue, sanitized_error(record.error_code))
        self._persistence.put_batch(
            record_id,
            payload,
            authority_binding=self._authority,
        )

    def publish_validated(
        self,
        job: ScheduledSceneJob,
        output: ValidatedLogicalOutput,
        attempt: SchedulerAttemptRecord,
        job_record: SchedulerJobRecord,
    ) -> None:
        claims, edges = _publication_claims(output.payload)
        job_payload = job.logical_job.to_dict()
        job_payload.update(job_record.to_dict())
        job_payload["status"] = job_record.state.value
        self._persistence.publish_validated(
            job_id=job.logical_job_id,
            job=job_payload,
            claims=claims,
            claim_edges=edges,
            artifact_id=output.artifact_id,
            artifact=output.payload,
            cache_identity=job.cache_identity.to_dict(),
            cache_metadata={
                "publication": output.publication.value,
                "provider": attempt.provider.to_dict(),
                "attempt_id": attempt.attempt_id,
                "metrics": attempt.metrics.to_dict(),
            },
            attempt_id=attempt.attempt_id,
            attempt=attempt.to_dict(),
            authority_binding=self._authority,
            cancelled=self._cancelled,
        )

    def record_run(self, record: SchedulerRunRecord) -> None:
        payload = record.to_dict()
        if record.error_code is not None:
            payload["error"] = cast(JsonValue, sanitized_error(record.error_code))
        self._persistence.put_run(
            record.run_id,
            payload,
            authority_binding=self._authority,
        )

    def _require_job(self, logical_job_id: str) -> ScheduledSceneJob:
        try:
            return self._jobs[logical_job_id]
        except KeyError as exc:
            raise ValueError("scheduler attempted to persist an unknown logical job") from exc

    def _load_histories(self) -> dict[tuple[str, str], list[AttemptOutcome]]:
        indexed: dict[tuple[str, str], list[tuple[int, AttemptOutcome]]] = {}
        for result in self._persistence.list_records(
            RecordKind.ATTEMPT,
            authority_binding=self._authority,
        ):
            if result.state is not LookupState.HIT or result.payload is None:
                continue
            payload = result.payload
            run_id = payload.get("run_id")
            logical_job_id = payload.get("logical_job_id")
            attempt_number = payload.get("attempt_number")
            outcome = payload.get("outcome")
            if (
                not isinstance(run_id, str)
                or not isinstance(logical_job_id, str)
                or not isinstance(attempt_number, int)
                or isinstance(attempt_number, bool)
                or not isinstance(outcome, str)
            ):
                continue
            try:
                parsed = AttemptOutcome(outcome)
            except ValueError:
                continue
            indexed.setdefault((run_id, logical_job_id), []).append((attempt_number, parsed))
        return {
            key: [outcome for _number, outcome in sorted(values)] for key, values in indexed.items()
        }


def _scheduled_scene_job(
    prepared: PreparedSceneJob,
    provider: ProviderIdentity,
    pricing: ProviderPricing | None,
    *,
    scope_id: str,
) -> ScheduledSceneJob:
    revision = prepared.job.input_revision
    identity = CacheIdentity(
        logical_job_id=prepared.job.spec.job_id,
        input_revision_id=revision.identity,
        normalized_input_hash=revision.normalized_input_hash,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        response_schema_version=RESPONSE_SCHEMA_VERSION,
        provider=provider,
    )
    cost = None
    if pricing is not None:
        cost = math.ceil(
            (
                prepared.estimated_input_tokens * pricing.input_micros_per_million_tokens
                + prepared.estimated_output_tokens * pricing.output_micros_per_million_tokens
            )
            / 1_000_000
        )
    return ScheduledSceneJob(
        logical_job=prepared.job,
        cache_identity=identity,
        scope_id=scope_id,
        provider_input=prepared.payload,
        ordinal=prepared.ordinal,
        estimated_input_tokens=prepared.estimated_input_tokens,
        estimated_output_tokens=prepared.estimated_output_tokens,
        estimated_cost_micros=cost,
    )


def _publication_claims(
    payload: Mapping[str, object],
) -> tuple[dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]:
    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list):
        raise ValueError("validated artifact claims are malformed")
    claims: dict[str, Mapping[str, object]] = {}
    edges: dict[str, Mapping[str, object]] = {}
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, Mapping):
            raise ValueError("validated artifact claim is malformed")
        claim = dict(raw_claim)
        claim_id = claim.get("claim_id")
        support = claim.get("support")
        if not isinstance(claim_id, str) or not isinstance(support, Mapping):
            raise ValueError("validated artifact claim identity is malformed")
        if claim_id in claims:
            raise ValueError("validated artifact repeats a claim identity")
        claims[claim_id] = claim
        child_ids = support.get("child_claim_ids", ())
        if not isinstance(child_ids, list):
            raise ValueError("validated child claim support is malformed")
        for ordinal, child_id in enumerate(child_ids):
            if not isinstance(child_id, str):
                raise ValueError("validated child claim identity is malformed")
            material = {
                "parent_claim_id": claim_id,
                "child_claim_id": child_id,
                "ordinal": ordinal,
            }
            edge_id = f"m13_claim_edge_{canonical_hash(material)}"
            edges[edge_id] = {"edge_id": edge_id, **material}
    return claims, edges

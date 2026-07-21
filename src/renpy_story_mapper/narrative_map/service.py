"""Read-only-by-default service facade for M15 Narrative Map enrichment."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta

from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    BoundaryCandidate,
    BoundaryDecision,
    BoundaryDecisionKind,
    BoundaryProviderIdentity,
    NarrativeEvent,
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
    BoundaryWindow,
    FineNarrativeUnit,
    NarrativeGapCandidate,
    SemanticOutline,
)
from renpy_story_mapper.narrative_map.semantic_lifecycle import (
    BoundaryStageOutput,
    SemanticLifecycle,
    SemanticStagePreparation,
    SemanticStatusView,
)
from renpy_story_mapper.narrative_map.semantic_projection import (
    FrozenSummaryInput,
    SemanticEvidenceRecord,
)
from renpy_story_mapper.narrative_map.workflow import (
    NarrativeBoundaryWorkflow,
    NarrativeWorkflowReport,
)


@dataclass(frozen=True)
class NarrativeEventSummaryView:
    event_id: str
    title: str
    summary: str | None
    characters: tuple[str, ...]
    enriched: bool


class NarrativeMapService:
    """Normal reads cannot submit because this object intentionally owns no provider."""

    SUMMARY_CONSENT_IS_SEPARATE = True

    def __init__(self, repository: NarrativeMapRepository) -> None:
        self._repository = repository
        self._semantic = SemanticLifecycle(repository)

    def prepare_boundaries(
        self,
        units: Sequence[FineNarrativeUnit],
        candidates: Sequence[NarrativeGapCandidate],
        windows: Sequence[BoundaryWindow],
        evidence_by_unit: Mapping[str, Sequence[SemanticEvidenceRecord]],
        *,
        profile: ProviderProfile,
        run_id: str,
        source_hash: str,
        correction_id: str,
        privacy_scope: str = "story_evidence_only",
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int | None = None,
        maximum_input_bytes: int = 1_000_000,
        maximum_output_bytes: int = 2_000_000,
        timeout_seconds: float = 300.0,
        replay_existing: bool = False,
    ) -> SemanticStagePreparation:
        return self._semantic.prepare_boundaries(
            units,
            candidates,
            windows,
            evidence_by_unit,
            profile=profile,
            run_id=run_id,
            source_hash=source_hash,
            correction_id=correction_id,
            privacy_scope=privacy_scope,
            valid_for=valid_for,
            maximum_provider_calls=maximum_provider_calls,
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
            replay_existing=replay_existing,
        )

    def start_boundaries(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return self._semantic.start_boundaries(
            preparation,
            provider=provider,
            consent=consent,
            cancelled=cancelled,
        )

    def semantic_boundary_output(
        self,
        preparation: SemanticStagePreparation,
    ) -> BoundaryStageOutput:
        return self._semantic.boundary_output(preparation)

    def prepare_summaries(
        self,
        outline: SemanticOutline,
        inputs: Sequence[FrozenSummaryInput],
        evidence_by_unit: Mapping[str, Sequence[SemanticEvidenceRecord]],
        *,
        profile: ProviderProfile,
        run_id: str,
        source_hash: str,
        correction_id: str,
        privacy_scope: str = "story_evidence_only",
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int | None = None,
        maximum_input_bytes: int = 1_000_000,
        maximum_output_bytes: int = 2_000_000,
        timeout_seconds: float = 300.0,
        replay_existing: bool = False,
    ) -> SemanticStagePreparation:
        return self._semantic.prepare_summaries(
            outline,
            inputs,
            evidence_by_unit,
            profile=profile,
            run_id=run_id,
            source_hash=source_hash,
            correction_id=correction_id,
            privacy_scope=privacy_scope,
            valid_for=valid_for,
            maximum_provider_calls=maximum_provider_calls,
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
            replay_existing=replay_existing,
        )

    def start_summaries(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return self._semantic.start_summaries(
            preparation,
            provider=provider,
            consent=consent,
            cancelled=cancelled,
        )

    def semantic_status(
        self,
        *,
        authority: AuthorityBinding | None = None,
        source_hash: str | None = None,
        correction_id: str | None = None,
    ) -> SemanticStatusView | None:
        return self._semantic.status(
            authority=authority,
            source_hash=source_hash,
            correction_id=correction_id,
        )

    def cancel_semantic_build(self) -> SemanticStatusView | None:
        return self._semantic.cancel()

    def resume_semantic_build(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return self._semantic.resume(
            preparation,
            provider=provider,
            consent=consent,
            cancelled=cancelled,
        )

    def retry_semantic_build(
        self,
        preparation: SemanticStagePreparation,
        *,
        provider: NarrativeMapProvider,
        consent: NarrativeConsentManifest,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return self._semantic.retry(
            preparation,
            provider=provider,
            consent=consent,
            cancelled=cancelled,
        )

    def read_current_semantic_publication(self) -> Mapping[str, object] | None:
        """Read the atomically published current build; this can never submit."""

        return self._repository.read_semantic_current()

    def read_boundary_decisions(
        self, candidates: Sequence[BoundaryCandidate]
    ) -> tuple[BoundaryDecision, ...]:
        records = {
            record.subject_id: record
            for record in self._repository.list(ProviderJobKind.BOUNDARY)
            if record.status is NarrativeJobStatus.VALIDATED
        }
        decisions: list[BoundaryDecision] = []
        for candidate in candidates:
            record = records.get(candidate.candidate_id)
            decision = (
                _decision_from_record(candidate, record.result, record.provider_identity)
                if record
                else None
            )
            decisions.append(
                decision
                if decision is not None
                else BoundaryDecision(
                    candidate=candidate,
                    decision=BoundaryDecisionKind.UNCERTAIN,
                    reason="Provider result unavailable; retain the conservative boundary.",
                    confidence=0.0,
                    provider_identity=None,
                )
            )
        return tuple(decisions)

    def read_event_summaries(
        self, events: Sequence[NarrativeEvent]
    ) -> tuple[NarrativeEventSummaryView, ...]:
        records = {
            record.subject_id: record
            for record in self._repository.list(ProviderJobKind.EVENT_SUMMARY)
            if record.status is NarrativeJobStatus.VALIDATED and record.result is not None
        }
        views: list[NarrativeEventSummaryView] = []
        for event in events:
            record = records.get(event.event_id)
            result = record.result if record is not None else None
            if isinstance(result, Mapping):
                title = result.get("title")
                summary = result.get("summary")
                characters = result.get("characters")
                if (
                    isinstance(title, str)
                    and isinstance(summary, str)
                    and isinstance(characters, list)
                    and all(isinstance(item, str) for item in characters)
                ):
                    views.append(
                        NarrativeEventSummaryView(
                            event.event_id,
                            title,
                            summary,
                            tuple(characters),
                            True,
                        )
                    )
                    continue
            views.append(
                NarrativeEventSummaryView(
                    event.event_id,
                    event.deterministic_title,
                    None,
                    (),
                    False,
                )
            )
        return tuple(views)

    def enrich_boundaries(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        *,
        provider: NarrativeMapProvider,
        profile: ProviderProfile,
        consent: NarrativeConsentManifest,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return NarrativeBoundaryWorkflow(self._repository, provider, profile).run_boundary_jobs(
            jobs,
            consent=consent,
            cancelled=cancelled,
        )

    def enrich_event_summaries(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        *,
        provider: NarrativeMapProvider,
        profile: ProviderProfile,
        consent: NarrativeConsentManifest,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return NarrativeBoundaryWorkflow(
            self._repository, provider, profile
        ).run_event_summary_jobs(
            jobs,
            consent=consent,
            cancelled=cancelled,
        )


def _decision_from_record(
    candidate: BoundaryCandidate,
    result: Mapping[str, object] | None,
    identity_payload: Mapping[str, object] | None,
) -> BoundaryDecision | None:
    if result is None or identity_payload is None:
        return None
    raw_decisions = result.get("decisions")
    if not isinstance(raw_decisions, list) or len(raw_decisions) != 1:
        return None
    item = raw_decisions[0]
    if not isinstance(item, Mapping) or item.get("candidate_id") != candidate.candidate_id:
        return None
    try:
        identity = BoundaryProviderIdentity(
            provider=str(identity_payload["provider"]),
            adapter_version=str(identity_payload["adapter_version"]),
            requested_model=str(identity_payload["requested_model"]),
            resolved_model=str(identity_payload["resolved_model"]),
            settings_hash=str(identity_payload["settings_hash"]),
            prompt_version=str(identity_payload["prompt_version"]),
            response_schema=str(identity_payload["response_schema"]),
            input_hash=str(identity_payload["input_hash"]),
        )
        decision_value = item.get("decision")
        if not isinstance(decision_value, str):
            return None
        decision = BoundaryDecisionKind(decision_value)
        reason = item.get("reason")
        confidence = item.get("confidence")
        warnings = item.get("warnings")
        if (
            not isinstance(reason, str)
            or not isinstance(confidence, int | float)
            or isinstance(confidence, bool)
            or not isinstance(warnings, list)
            or not all(isinstance(warning, str) for warning in warnings)
        ):
            return None
        return BoundaryDecision(
            candidate=candidate,
            decision=decision,
            reason=reason,
            confidence=float(confidence),
            provider_identity=identity,
            warnings=tuple(warnings),
        )
    except (KeyError, TypeError, ValueError):
        return None

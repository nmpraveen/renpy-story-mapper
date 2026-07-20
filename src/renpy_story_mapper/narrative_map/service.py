"""Read-only-by-default service facade for M15 Narrative Map enrichment."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from renpy_story_mapper.narrative_map.contracts import (
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
    NarrativeMapProvider,
    PreparedNarrativeJob,
    ProviderJobKind,
    ProviderProfile,
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

    def __init__(self, repository: NarrativeMapRepository) -> None:
        self._repository = repository

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
        consent_manifest_id: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return NarrativeBoundaryWorkflow(self._repository, provider, profile).run_boundary_jobs(
            jobs,
            consent_manifest_id=consent_manifest_id,
            cancelled=cancelled,
        )

    def enrich_event_summaries(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        *,
        provider: NarrativeMapProvider,
        profile: ProviderProfile,
        consent_manifest_id: str,
        cancelled: Callable[[], bool] | None = None,
    ) -> NarrativeWorkflowReport:
        return NarrativeBoundaryWorkflow(
            self._repository, provider, profile
        ).run_event_summary_jobs(
            jobs,
            consent_manifest_id=consent_manifest_id,
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

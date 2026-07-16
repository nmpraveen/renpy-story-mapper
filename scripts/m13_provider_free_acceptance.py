"""Run the complete M13 corpus shape with an offline structured provider simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import runpy
import shutil
import socket
import subprocess
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from renpy_story_mapper.narrative.authority import (
    NarrativeAuthority,
    load_narrative_authority,
)
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import (
    BudgetLimits,
    JsonValue,
    ProviderIdentity,
    ProviderSettings,
)
from renpy_story_mapper.narrative.persistence import (
    M13_PAYLOAD_COLLECTIONS,
    LookupState,
    RecordKind,
)
from renpy_story_mapper.narrative.pipeline import (
    NarrativePipelineResult,
    project_scene_placements,
    run_complete_narrative,
)
from renpy_story_mapper.narrative.projection import NarrativeInputMode
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    ProviderCancelledError,
    ProviderOutputItem,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderUsage,
)
from renpy_story_mapper.narrative.scheduler import SchedulerPolicy, SchedulerRunState
from renpy_story_mapper.narrative.workflow import (
    PreparedNarrativeRun,
    grant_narrative_consent,
    prepare_narrative_scene_run,
    run_prepared_scene_jobs,
)
from renpy_story_mapper.project import Project
from renpy_story_mapper.storage import canonical_json

REPORT_SCHEMA = "m13-provider-free-acceptance-v1"
SIMULATOR_PROVIDER = "provider-free-simulator"
SIMULATOR_ADAPTER = "structured-offline-simulator"
SIMULATOR_ADAPTER_VERSION = "m13-offline-simulator-v1"
SIMULATOR_MODEL = "synthetic-provider-identity"
FORBIDDEN_DURABLE_KEYS = frozenset(
    {
        "child_artifacts",
        "complete_prompt",
        "full_prompt",
        "prompt",
        "prompt_text",
        "provider_input",
        "provider_response",
        "raw_prompt",
        "raw_provider_response",
        "raw_response",
        "response_body",
        "source_packet",
        "source_text",
        "support_records",
    }
)


@dataclass(frozen=True)
class SimulationFaults:
    refuse_first_batch: bool = False
    malformed_item_once: bool = False
    transient_retry_once: bool = False
    content_refusal_once: bool = False
    partial_item_once: bool = False
    cancel_on_call: int | None = None


@dataclass
class SimulatedNarrativeProvider:
    faults: SimulationFaults = SimulationFaults()
    content_variant: str = "accepted"
    call_item_counts: list[int] = field(default_factory=list)
    status_calls: int = 0
    successful_responses: int = 0
    cancel_calls: int = 0
    batch_refusal_emitted: bool = False
    malformed_emitted: bool = False
    transient_emitted: bool = False
    content_refusal_emitted: bool = False
    partial_emitted: bool = False
    automatic_refusals: int = 0
    cancel_requested: bool = False
    _malformed_job_id: str | None = None

    def status(self) -> ProviderStatus:
        self.status_calls += 1
        return ProviderStatus(
            True,
            SIMULATOR_PROVIDER,
            SIMULATOR_ADAPTER,
            SIMULATOR_ADAPTER_VERSION,
            "in-process-v1",
        )

    def submit(
        self,
        request: ProviderRequest,
        cancelled: Callable[[], bool],
    ) -> ProviderResponse:
        if cancelled():
            raise ProviderCancelledError("cancelled", "simulated cancellation")
        self.call_item_counts.append(len(request.items))
        call_number = len(self.call_item_counts)
        if self.faults.cancel_on_call == call_number:
            self.cancel_requested = True
            raise ProviderCancelledError("cancelled", "simulated cancellation")
        if (
            self.faults.refuse_first_batch
            and not self.batch_refusal_emitted
            and len(request.items) > 1
        ):
            self.batch_refusal_emitted = True
            raise ProviderRefusalError(
                "provider_refusal",
                "simulated batch refusal",
            )
        if (
            self.faults.transient_retry_once
            and self._malformed_job_id is not None
            and len(request.items) == 1
            and request.items[0].logical_job_id == self._malformed_job_id
            and not self.transient_emitted
        ):
            self.transient_emitted = True
            raise ProviderRateLimitError(
                "rate_limited",
                "simulated transient rate limit",
                transient=True,
            )

        outputs: list[ProviderOutputItem] = []
        for index, item in enumerate(request.items):
            job_kind = _required_text(item.payload, "job_kind")
            if (
                job_kind == "scene"
                and self.faults.content_refusal_once
                and not self.content_refusal_emitted
            ):
                self.content_refusal_emitted = True
                outputs.append(
                    ProviderOutputItem(
                        item.logical_job_id,
                        index,
                        None,
                        error_code="content_refusal",
                    )
                )
                continue
            if (
                job_kind == "scene"
                and self.faults.malformed_item_once
                and not self.malformed_emitted
            ):
                self.malformed_emitted = True
                self._malformed_job_id = item.logical_job_id
                outputs.append(
                    ProviderOutputItem(
                        item.logical_job_id,
                        index,
                        _artifact_payload(
                            item.logical_job_id,
                            job_kind,
                            "E999",
                            self.content_variant,
                        ),
                    )
                )
                continue
            handle = _first_support_handle(item.payload)
            if handle is None:
                self.automatic_refusals += 1
                outputs.append(
                    ProviderOutputItem(
                        item.logical_job_id,
                        index,
                        None,
                        error_code="content_refusal",
                    )
                )
                continue
            payload = _artifact_payload(
                item.logical_job_id,
                job_kind,
                handle,
                self.content_variant,
            )
            if (
                job_kind == "scene"
                and self.faults.partial_item_once
                and not self.partial_emitted
            ):
                self.partial_emitted = True
                claims = payload["claims"]
                assert isinstance(claims, list)
                claims.append(
                    _claim_payload(
                        job_kind,
                        "E999",
                        f"{self.content_variant}-invalid",
                    )
                )
            outputs.append(ProviderOutputItem(item.logical_job_id, index, payload))

        self.successful_responses += 1
        identity = ProviderIdentity(
            SIMULATOR_PROVIDER,
            SIMULATOR_ADAPTER,
            SIMULATOR_ADAPTER_VERSION,
            request.requested_model,
            request.requested_model,
            ProviderSettings(),
        )
        input_tokens = sum(
            max(1, math.ceil(len(canonical_json(item.payload)) / 4))
            for item in request.items
        )
        return ProviderResponse(
            request.request_id,
            identity,
            tuple(outputs),
            ProviderUsage(input_tokens, 64 * len(outputs), 1, 0),
            PROMPT_TEMPLATE_VERSION,
            RESPONSE_SCHEMA_VERSION,
        )

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.cancel_requested = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--minimum-scenes", type=int, default=1)
    args = parser.parse_args()
    report = run(
        baseline_path=args.baseline,
        output_path=args.output,
        source_path=args.source,
        archive_path=args.archive,
        minimum_scenes=args.minimum_scenes,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run(
    *,
    baseline_path: Path,
    output_path: Path,
    source_path: Path | None = None,
    archive_path: Path | None = None,
    minimum_scenes: int = 1,
) -> dict[str, object]:
    if minimum_scenes < 1:
        raise ValueError("minimum scene count must be positive")
    baseline = baseline_path.resolve(strict=True)
    source = source_path.resolve(strict=True) if source_path is not None else None
    archive = archive_path.resolve(strict=True) if archive_path is not None else None
    output = output_path.resolve()
    inputs = tuple(path for path in (baseline, source, archive) if path is not None)
    _require_isolated_output(output, inputs)
    if output.exists():
        raise FileExistsError("M13 provider-free output must not already exist")
    before_inputs = {path: _fingerprint(path) for path in inputs}
    adjacent_before = _adjacent_snapshots(inputs)
    output.mkdir(parents=True, exist_ok=False)
    working = output / "working.rsmproj"
    shutil.copy2(baseline, working)

    report: dict[str, object] | None = None
    try:
        with _offline_nonexecution_boundary() as safety, Project.open(working) as project:
            authority_before = load_narrative_authority(project, include_m12=True)
            scenes = _records(authority_before.scene_model, "scenes")
            if len(scenes) < minimum_scenes:
                raise AssertionError("provider-free corpus is below the required scene count")
            scene_ids = tuple(_required_text(item, "id") for item in scenes)
            source_snapshot_before = _source_snapshot(project)
            non_m13_before = _non_m13_payload_digest(project)
            m12_before = _m12_digest(authority_before)

            initial_provider = SimulatedNarrativeProvider(
                SimulationFaults(
                    refuse_first_batch=True,
                    malformed_item_once=True,
                    transient_retry_once=True,
                    content_refusal_once=True,
                ),
                content_variant="full",
            )
            initial_prepared = _prepare(
                project,
                initial_provider,
                run_id="provider-free-full-initial",
                model=SIMULATOR_MODEL,
            )
            if initial_provider.call_item_counts:
                raise AssertionError("provider-free preparation transmitted story material")
            initial = _run_complete(project, initial_provider, initial_prepared)
            _require_faults_exercised(initial_provider)
            if initial.record.refused_jobs < 1:
                raise AssertionError("content refusal did not remain job-local")
            if not initial.artifacts.scene_artifact_ids:
                raise AssertionError("initial fault run discarded all valid scene work")

            recovery_provider = SimulatedNarrativeProvider(content_variant="full")
            recovery_prepared = _prepare(
                project,
                recovery_provider,
                run_id="provider-free-full-recovery",
                model=SIMULATOR_MODEL,
            )
            recovery = _run_complete(project, recovery_provider, recovery_prepared)
            if recovery.record.state is not SchedulerRunState.SUCCEEDED:
                raise AssertionError("full recovery did not reach a successful terminal state")
            if len(recovery.artifacts.scene_artifact_ids) != len(scene_ids):
                raise AssertionError("full recovery did not publish every current scene")
            if recovery.artifacts.plot_artifact_id is None:
                raise AssertionError("full recovery did not publish a route-aware plot")

            replay_provider = SimulatedNarrativeProvider(content_variant="full")
            replay_prepared = _prepare(
                project,
                replay_provider,
                run_id="provider-free-full-replay",
                model=SIMULATOR_MODEL,
            )
            replay = _run_complete(project, replay_provider, replay_prepared)
            if replay_provider.call_item_counts or replay.record.usage.provider_calls:
                raise AssertionError("exact cache replay made a provider call")
            if replay.artifacts != recovery.artifacts:
                raise AssertionError("exact cache replay changed accepted artifact identities")
            if not all(item.cache_replay for item in replay.jobs):
                raise AssertionError("exact cache replay missed a completed logical job")

            cancellation_count = min(64, len(scene_ids))
            cancellation_provider = SimulatedNarrativeProvider(
                SimulationFaults(cancel_on_call=2),
                content_variant="cancelled",
            )
            cancellation_prepared = _prepare(
                project,
                cancellation_provider,
                run_id="provider-free-cancellation",
                model=f"{SIMULATOR_MODEL}-cancel",
                selected_scene_ids=scene_ids[:cancellation_count],
            )
            cancelled = _run_complete(
                project,
                cancellation_provider,
                cancellation_prepared,
                cancelled=lambda: cancellation_provider.cancel_requested,
            )
            if cancelled.record.state is not SchedulerRunState.CANCELLED:
                raise AssertionError("simulated cancellation did not stop the run")
            if not 0 < len(cancelled.artifacts.scene_artifact_ids) < cancellation_count:
                raise AssertionError("cancellation did not preserve only validated prior work")

            partial_provider = SimulatedNarrativeProvider(
                SimulationFaults(partial_item_once=True),
                content_variant="partial",
            )
            partial_prepared = _prepare(
                project,
                partial_provider,
                run_id="provider-free-partial",
                model=f"{SIMULATOR_MODEL}-partial",
                selected_scene_ids=(scene_ids[0],),
            )
            partial = run_prepared_scene_jobs(
                project,
                partial_provider,
                partial_prepared,
                grant_narrative_consent(project, partial_prepared),
                policy=_policy(),
            )
            if partial.record.partial_jobs != 1 or not partial_provider.partial_emitted:
                raise AssertionError("claim-local partial salvage was not retained")

            invalidation_provider = SimulatedNarrativeProvider(
                content_variant="regenerated"
            )
            invalidation_prepared = _prepare(
                project,
                invalidation_provider,
                run_id="provider-free-invalidation",
                model=f"{SIMULATOR_MODEL}-regenerated",
                selected_scene_ids=(scene_ids[0],),
            )
            invalidated = run_prepared_scene_jobs(
                project,
                invalidation_provider,
                invalidation_prepared,
                grant_narrative_consent(project, invalidation_prepared),
                policy=_policy(),
            )
            if not invalidation_provider.call_item_counts:
                raise AssertionError("provider/model identity did not invalidate the cache")
            if invalidated.record.succeeded_jobs != 1:
                raise AssertionError("regenerated provider identity did not publish safely")

            original_probe = SimulatedNarrativeProvider(content_variant="full")
            original_probe_prepared = _prepare(
                project,
                original_probe,
                run_id="provider-free-original-cache-probe",
                model=SIMULATOR_MODEL,
                selected_scene_ids=(scene_ids[0],),
            )
            original_probe_result = run_prepared_scene_jobs(
                project,
                original_probe,
                original_probe_prepared,
                grant_narrative_consent(project, original_probe_prepared),
                policy=_policy(),
            )
            if original_probe.call_item_counts or not original_probe_result.jobs[0].cache_replay:
                raise AssertionError("cache invalidation damaged the prior exact cache entry")

            authority_after = load_narrative_authority(project, include_m12=True)
            if authority_after.binding != authority_before.binding:
                raise AssertionError("M13 changed an M10, M11, or M12 authority binding")
            if _m12_digest(authority_after) != m12_before:
                raise AssertionError("M13 changed normalized M12 result bytes")
            if _source_snapshot(project) != source_snapshot_before:
                raise AssertionError("M13 changed tracked source/archive fingerprints")
            if _non_m13_payload_digest(project) != non_m13_before:
                raise AssertionError("M13 changed a non-M13 project payload")

            route_evidence = _route_invariants(project, authority_after, recovery)
            claim_evidence = _claim_invariants(project, authority_after)
            storage_evidence = _privacy_and_growth(project, authority_after, len(scene_ids))
            counts = _corpus_counts(authority_after)
            report = {
                "schema": REPORT_SCHEMA,
                "status": "passed",
                "authority": {
                    "source_archive_hash": authority_after.binding.source_archive_hash,
                    "canonical_hash": authority_after.binding.canonical_hash,
                    "scene_hash": authority_after.binding.scene_hash,
                    "m12_result_count": len(authority_after.m12_results),
                    "m12_normalized_hash": m12_before,
                    "non_m13_payload_hash": non_m13_before[0],
                    "tracked_source_snapshot_hash": source_snapshot_before[0],
                },
                "corpus": counts,
                "full_scale": {
                    "selected_scene_jobs": len(scene_ids),
                    "consent_estimate": recovery_prepared.consent_preview.estimate.to_dict(),
                    "initial_state": initial.record.state.value,
                    "initial_simulated_calls": len(initial_provider.call_item_counts),
                    "initial_max_batch_items": max(initial_provider.call_item_counts),
                    "recovery_state": recovery.record.state.value,
                    "recovery_simulated_calls": len(recovery_provider.call_item_counts),
                    "replay_state": replay.record.state.value,
                    "replay_simulated_calls": 0,
                    "replay_provider_calls": replay.record.usage.provider_calls,
                    "scene_artifacts": len(recovery.artifacts.scene_artifact_ids),
                    "segment_artifacts": len(recovery.artifacts.segment_artifact_ids),
                    "chapter_artifacts": len(recovery.artifacts.chapter_artifact_ids),
                    "route_artifacts": len(recovery.artifacts.route_artifact_ids),
                    "ending_artifacts": len(recovery.artifacts.ending_artifact_ids),
                    "character_artifacts": len(recovery.artifacts.character_artifact_ids),
                    "plot_published": recovery.artifacts.plot_artifact_id is not None,
                },
                "faults": {
                    "batch_refusal_split": initial_provider.batch_refusal_emitted,
                    "malformed_item_retried": initial_provider.malformed_emitted,
                    "transient_item_retried": initial_provider.transient_emitted,
                    "content_refusal_recovered": initial_provider.content_refusal_emitted,
                    "valid_prior_artifacts_preserved": bool(
                        initial.artifacts.scene_artifact_ids
                    ),
                    "partial_claim_artifact_published": partial.record.partial_jobs == 1,
                    "cancellation_preserved_scene_artifacts": len(
                        cancelled.artifacts.scene_artifact_ids
                    ),
                    "provider_identity_invalidation_called": bool(
                        invalidation_provider.call_item_counts
                    ),
                    "prior_identity_cache_survived": True,
                },
                "route_structure": route_evidence,
                "claims": claim_evidence,
                "storage": storage_evidence,
                "safety": {
                    **safety,
                    "remote_provider_calls": 0,
                    "renpy_or_game_executed": False,
                    "runtime_tracing_executed": False,
                    "private_paths_recorded": False,
                    "working_project_retained": False,
                },
                "input_integrity": {
                    "accepted_baseline_unchanged": True,
                    "source_file_checked": source is not None,
                    "archive_file_checked": archive is not None,
                    "adjacent_private_files_unchanged": True,
                },
                "artifacts": {"aggregate_report": "acceptance.json"},
            }
    finally:
        _remove_working_project(working)

    if report is None:
        raise AssertionError("provider-free acceptance produced no report")
    if before_inputs != {path: _fingerprint(path) for path in inputs}:
        raise AssertionError("provider-free acceptance changed an accepted input")
    if adjacent_before != _adjacent_snapshots(inputs):
        raise AssertionError("provider-free acceptance wrote beside a private input")
    encoded = json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    for path in inputs:
        if str(path).encode("utf-8") in encoded or path.name.encode("utf-8") in encoded:
            raise AssertionError("provider-free report contains a private input path")
    (output / "acceptance.json").write_bytes(encoded)
    return report


def _prepare(
    project: Project,
    provider: SimulatedNarrativeProvider,
    *,
    run_id: str,
    model: str,
    selected_scene_ids: tuple[str, ...] | None = None,
) -> PreparedNarrativeRun:
    return prepare_narrative_scene_run(
        project,
        provider,
        run_id=run_id,
        requested_model=model,
        mode=NarrativeInputMode.FACT_ONLY,
        include_m12_material=True,
        limits=BudgetLimits(
            10_000,
            100_000_000,
            100_000_000,
            200_000_000,
            3_600,
            1,
        ),
        batch_limits=BatchLimits(16, 500_000, 100_000),
        selected_scene_ids=selected_scene_ids,
    )


def _policy() -> SchedulerPolicy:
    return SchedulerPolicy(BatchLimits(16, 500_000, 100_000))


def _run_complete(
    project: Project,
    provider: SimulatedNarrativeProvider,
    prepared: PreparedNarrativeRun,
    *,
    cancelled: Callable[[], bool] = lambda: False,
) -> NarrativePipelineResult:
    return run_complete_narrative(
        project,
        provider,
        prepared,
        grant_narrative_consent(project, prepared),
        policy=_policy(),
        cancelled=cancelled,
    )


def _require_faults_exercised(provider: SimulatedNarrativeProvider) -> None:
    if not (
        provider.batch_refusal_emitted
        and provider.malformed_emitted
        and provider.transient_emitted
        and provider.content_refusal_emitted
    ):
        raise AssertionError("provider-free fault matrix did not exercise every required fault")
    if not provider.call_item_counts or max(provider.call_item_counts) <= 1:
        raise AssertionError("provider-free scene jobs were not transport-batched")


def _artifact_payload(
    logical_job_id: str,
    job_kind: str,
    handle: str,
    variant: str,
) -> dict[str, JsonValue]:
    return {
        "logical_job_id": logical_job_id,
        "title": f"Simulated {job_kind.replace('_', ' ')}",
        "summary": "A bounded provider-free acceptance artifact.",
        "claims": [_claim_payload(job_kind, handle, variant)],
    }


def _claim_payload(job_kind: str, handle: str, variant: str) -> dict[str, JsonValue]:
    scene = job_kind == "scene"
    return {
        "claim_class": "interpretive" if job_kind == "character" else "factual",
        "text": f"A supported {job_kind} claim for {variant}.",
        "evidence_handles": [handle] if scene else [],
        "child_claim_handles": [] if scene else [handle],
        "subject": job_kind,
        "predicate": "has supported narrative result",
        "polarity": "positive",
        "normalized_value": variant,
    }


def _first_support_handle(payload: Mapping[str, object]) -> str | None:
    if payload.get("job_kind") == "scene":
        for record in _mapping_records(payload.get("support_records")):
            handle = record.get("handle")
            if isinstance(handle, str) and handle.startswith("E"):
                return handle
        return None
    for child in _mapping_records(payload.get("child_artifacts")):
        for claim in _mapping_records(child.get("claims")):
            handle = claim.get("handle")
            if isinstance(handle, str) and handle.startswith("C"):
                return handle
    for claim in _mapping_records(payload.get("exact_m12_authority_claims")):
        handle = claim.get("handle")
        if isinstance(handle, str) and handle.startswith("C"):
            return handle
    return None


def _route_invariants(
    project: Project,
    authority: NarrativeAuthority,
    result: NarrativePipelineResult,
) -> dict[str, object]:
    binding = authority.binding.to_dict()
    if result.artifacts.plot_artifact_id is None:
        raise AssertionError("route invariant check requires a plot artifact")
    plot = project.m13_persistence().lookup(
        RecordKind.ARTIFACT,
        result.artifacts.plot_artifact_id,
        authority_binding=binding,
    )
    if plot.state is not LookupState.HIT or plot.payload is None:
        raise AssertionError("route-aware plot artifact is unavailable")
    hierarchy = _mapping(plot.payload.get("hierarchy"), "plot hierarchy")
    if hierarchy.get("chronology_policy") != "shared_then_separate_routes_and_endings":
        raise AssertionError("whole plot flattened route-aware chronology")

    placements = project_scene_placements(authority.scene_model)
    expected_routes = {item.path.route_id for item in placements if item.path.route_id is not None}
    if len(result.artifacts.route_artifact_ids) != len(expected_routes):
        raise AssertionError("persistent route artifacts do not cover current route contexts")
    linear_artifacts_checked = 0
    generic_reductions = 0
    for lookup in project.m13_persistence().list_records(
        RecordKind.ARTIFACT,
        authority_binding=binding,
    ):
        if lookup.state is not LookupState.HIT or lookup.payload is None:
            raise AssertionError("current M13 artifact record is unavailable")
        raw_hierarchy = lookup.payload.get("hierarchy")
        if not isinstance(raw_hierarchy, Mapping):
            continue
        entries = _mapping_records(raw_hierarchy.get("section_entries"))
        route_ids = {
            route_id
            for entry in entries
            if isinstance((path := entry.get("path")), Mapping)
            and isinstance((route_id := path.get("route_id")), str)
        }
        if raw_hierarchy.get("chronology_policy") == "one_owned_chronology":
            linear_artifacts_checked += 1
            if len(route_ids) > 1:
                raise AssertionError("mutually exclusive routes entered one linear chronology")
        if lookup.payload.get("job_kind") == "summary_segment" and any(
            entry.get("job_kind") in {"chapter", "route", "ending"} for entry in entries
        ):
            generic_reductions += 1
    if len(placements) >= 64 and generic_reductions < 1:
        raise AssertionError("large corpus did not exercise higher hierarchy reduction")
    return {
        "persistent_route_contexts": len(expected_routes),
        "route_artifacts": len(result.artifacts.route_artifact_ids),
        "ending_artifacts": len(result.artifacts.ending_artifact_ids),
        "temporary_branch_records": len(
            _records(authority.scene_model, "temporary_branches")
        ),
        "linear_artifacts_checked": linear_artifacts_checked,
        "higher_reduction_artifacts": generic_reductions,
        "plot_chronology_policy": hierarchy["chronology_policy"],
        "mutually_exclusive_routes_flattened": False,
    }


def _claim_invariants(
    project: Project,
    authority: NarrativeAuthority,
) -> dict[str, object]:
    binding = authority.binding.to_dict()
    claim_records = project.m13_persistence().list_records(
        RecordKind.CLAIM,
        authority_binding=binding,
    )
    claims: dict[str, Mapping[str, object]] = {}
    for lookup in claim_records:
        if lookup.state is not LookupState.HIT or lookup.payload is None:
            raise AssertionError("current M13 claim record is unavailable")
        claim_id = _required_text(lookup.payload, "claim_id")
        if claim_id != lookup.record_id or claim_id in claims:
            raise AssertionError("persisted claim identity is duplicate or corrupt")
        claims[claim_id] = lookup.payload
    jobs: dict[str, str] = {}
    for lookup in project.m13_persistence().list_records(
        RecordKind.JOB,
        authority_binding=binding,
    ):
        if lookup.state is not LookupState.HIT or lookup.payload is None:
            continue
        spec = _mapping(lookup.payload.get("spec"), "claim owner job spec")
        jobs[_required_text(lookup.payload, "job_id")] = _required_text(spec, "owner_id")
    known = _authority_record_ids(authority)
    memo: dict[str, int] = {}

    def terminal_support(claim_id: str, active: set[str]) -> int:
        if claim_id in memo:
            return memo[claim_id]
        if claim_id in active:
            raise AssertionError("persisted claim DAG contains a cycle")
        claim = claims.get(claim_id)
        if claim is None:
            raise AssertionError("persisted claim DAG references an unknown claim")
        active.add(claim_id)
        support = _mapping(claim.get("support"), "claim support")
        direct = _mapping_records(support.get("direct_evidence"))
        children = _strings(support.get("child_claim_ids"), "child claim IDs")
        if direct and children:
            raise AssertionError("one claim mixed direct and child support")
        if direct:
            owner = jobs.get(_required_text(claim, "logical_job_id"))
            if owner is None:
                raise AssertionError("claim owner job is unavailable")
            for reference in direct:
                authority_name = _required_text(reference, "authority")
                record_kind = _required_text(reference, "record_kind")
                record_id = _required_text(reference, "record_id")
                if reference.get("owner_id") != owner:
                    raise AssertionError("direct evidence is outside its logical job owner")
                if record_id not in known.get((authority_name, record_kind), frozenset()):
                    raise AssertionError("claim references unknown or out-of-scope authority")
            result = len(direct)
        elif children:
            result = sum(terminal_support(child, active) for child in children)
        else:
            raise AssertionError("published claim has no owned support")
        active.remove(claim_id)
        memo[claim_id] = result
        return result

    factual = 0
    interpretive = 0
    for claim_id, claim in claims.items():
        support_count = terminal_support(claim_id, set())
        if support_count < 1:
            raise AssertionError("published claim has no transitive direct evidence")
        if claim.get("claim_class") == "factual":
            factual += 1
        elif claim.get("claim_class") == "interpretive":
            interpretive += 1
    return {
        "published_claims": len(claims),
        "factual_claims": factual,
        "interpretive_claims": interpretive,
        "all_factual_claims_have_owned_evidence": True,
        "unknown_or_out_of_scope_references": 0,
        "claim_dag_cycles": 0,
    }


def _privacy_and_growth(
    project: Project,
    authority: NarrativeAuthority,
    scene_count: int,
) -> dict[str, object]:
    binding = authority.binding.to_dict()
    counts: dict[str, int] = {}
    serialized_bytes = 0
    for kind in RecordKind:
        current = project.m13_persistence().list_records(kind, authority_binding=binding)
        counts[kind.value] = len(current)
        for lookup in current:
            if lookup.state is not LookupState.HIT or lookup.payload is None:
                continue
            _assert_private_payload(lookup.payload)
            serialized_bytes += len(canonical_json(dict(lookup.payload)))
    artifact_count = counts[RecordKind.ARTIFACT.value]
    claim_count = counts[RecordKind.CLAIM.value]
    edge_count = counts[RecordKind.CLAIM_EDGE.value]
    if artifact_count > scene_count * 5 + 512:
        raise AssertionError("artifact growth exceeded the approximately linear bound")
    if claim_count > artifact_count * 2 + 64:
        raise AssertionError("claim growth exceeded the approximately linear bound")
    if edge_count > claim_count * 2 + 64:
        raise AssertionError("provenance growth exceeded the approximately linear bound")
    return {
        "record_counts": counts,
        "serialized_m13_bytes": serialized_bytes,
        "artifacts_per_scene": round(artifact_count / scene_count, 6),
        "claims_per_artifact": round(claim_count / max(1, artifact_count), 6),
        "edges_per_claim": round(edge_count / max(1, claim_count), 6),
        "approximately_linear_growth": True,
        "raw_debug_payloads_persisted": False,
    }


def _assert_private_payload(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = "".join(
                character
                for character in str(key).casefold()
                if character.isalnum() or character == "_"
            )
            if normalized in FORBIDDEN_DURABLE_KEYS:
                raise AssertionError(f"forbidden raw payload key persisted: {key}")
            _assert_private_payload(item)
    elif isinstance(value, list):
        for item in value:
            _assert_private_payload(item)
    elif isinstance(value, str) and len(value) > 2 and value[1:3] in {":\\", ":/"}:
        raise AssertionError("absolute path persisted in an M13 record")


def _authority_record_ids(
    authority: NarrativeAuthority,
) -> dict[tuple[str, str], frozenset[str]]:
    return {
        ("m10", "fact"): frozenset(
            _required_text(item, "id") for item in _records(authority.canonical, "facts")
        ),
        ("m10", "evidence"): frozenset(
            _required_text(item, "id") for item in _records(authority.canonical, "evidence")
        ),
        ("m11", "scene"): frozenset(
            _required_text(item, "id") for item in _records(authority.scene_model, "scenes")
        ),
        ("m11", "atom"): frozenset(
            _required_text(item, "id") for item in _records(authority.scene_model, "atoms")
        ),
        ("m12", "route_result"): frozenset(
            _required_text(item, "request_identity") for item in authority.m12_results
        ),
    }


def _corpus_counts(authority: NarrativeAuthority) -> dict[str, int]:
    return {
        "scenes": len(_records(authority.scene_model, "scenes")),
        "atoms": len(_records(authority.scene_model, "atoms")),
        "chapters": len(_records(authority.scene_model, "chapters")),
        "lanes": len(_records(authority.scene_model, "lanes")),
        "temporary_branches": len(
            _records(authority.scene_model, "temporary_branches")
        ),
        "occurrences": len(_records(authority.scene_model, "occurrences")),
    }


def _source_snapshot(project: Project) -> tuple[str, int]:
    records = [
        {
            "path": item.path,
            "content_hash": item.content_hash,
            "size_bytes": item.size_bytes,
            "modified_ns": item.modified_ns,
            "metadata": item.metadata,
        }
        for item in project.sources()
    ]
    return hashlib.sha256(canonical_json(records)).hexdigest(), len(records)


def _non_m13_payload_digest(project: Project) -> tuple[str, int]:
    rows = project._require_open().execute(
        "SELECT collection, record_key, payload_json FROM payloads ORDER BY collection, record_key"
    ).fetchall()
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        collection = str(row["collection"])
        if collection in M13_PAYLOAD_COLLECTIONS:
            continue
        count += 1
        digest.update(collection.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["record_key"]).encode("utf-8"))
        digest.update(b"\0")
        payload = row["payload_json"]
        digest.update(payload if isinstance(payload, bytes) else str(payload).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest(), count


def _m12_digest(authority: NarrativeAuthority) -> str:
    return hashlib.sha256(canonical_json(list(authority.m12_results))).hexdigest()


def _fingerprint(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size, stat.st_mtime_ns


def _adjacent_snapshots(
    paths: Sequence[Path],
) -> dict[Path, tuple[tuple[str, int, int], ...]]:
    return {
        parent: tuple(
            sorted(
                (item.name, item.stat().st_size, item.stat().st_mtime_ns)
                for item in parent.iterdir()
                if item.is_file()
            )
        )
        for parent in {path.parent for path in paths}
    }


def _require_isolated_output(output: Path, inputs: Sequence[Path]) -> None:
    if output in inputs or output.parent in {path.parent for path in inputs}:
        raise ValueError("M13 provider-free output must be isolated from private inputs")
    if any(output.is_relative_to(path) for path in inputs if path.is_dir()):
        raise ValueError("M13 provider-free output cannot be inside a private input")


def _remove_working_project(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            candidate.unlink()


@contextmanager
def _offline_nonexecution_boundary() -> Iterator[dict[str, int]]:
    counts = {
        "network_requests": 0,
        "subprocess_executions": 0,
        "creator_code_executions": 0,
    }

    def block(name: str) -> Callable[..., None]:
        def blocked(*_args: object, **_kwargs: object) -> None:
            counts[name] += 1
            raise AssertionError(f"provider-free acceptance crossed {name}")

        return blocked

    network = block("network_requests")
    process = block("subprocess_executions")
    creator = block("creator_code_executions")
    with (
        mock.patch.object(socket.socket, "connect", network),
        mock.patch.object(socket, "create_connection", network),
        mock.patch.object(urllib.request.OpenerDirector, "open", network),
        mock.patch.object(subprocess, "Popen", process),
        mock.patch.object(subprocess, "run", process),
        mock.patch.object(os, "system", process),
        mock.patch.object(runpy, "run_path", creator),
        mock.patch.object(runpy, "run_module", creator),
    ):
        yield counts


def _records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    value = owner.get(key)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{key} must be an array of records")
    return tuple(item for item in value if isinstance(item, Mapping))


def _mapping_records(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{label} must be an array of strings")
    return tuple(item for item in value if isinstance(item, str))


def _required_text(owner: Mapping[str, object], key: str) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

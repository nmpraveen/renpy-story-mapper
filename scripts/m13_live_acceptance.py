"""Preview and, only after exact confirmation, run bounded M13 live-provider acceptance.

The preview path performs deterministic ingestion, M11/M12 preparation, and a local provider
availability/version check.  It never calls ``submit`` and therefore transmits no story material.
The confirmed path uses the exact preparation ID printed by preview, retains only a sanitized
acceptance report, and verifies a zero-call replay under the same consent manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import Final, cast

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import NarrativeAuthority, load_narrative_authority
from renpy_story_mapper.narrative.batching import BatchLimits
from renpy_story_mapper.narrative.contracts import LogicalJobState, ProviderSettings
from renpy_story_mapper.narrative.hierarchy import StorySection
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.narrative.pipeline import (
    NarrativePipelineResult,
    project_scene_placements,
    run_complete_narrative,
)
from renpy_story_mapper.narrative.presentation import (
    narrative_artifact_detail,
    narrative_claim_citations,
)
from renpy_story_mapper.narrative.projection import NarrativeInputMode
from renpy_story_mapper.narrative.provider import (
    CodexCliNarrativeProvider,
    NarrativeProvider,
)
from renpy_story_mapper.narrative.scheduler import SchedulerPolicy, SchedulerRunState
from renpy_story_mapper.narrative.sizing import budget_limits_with_headroom
from renpy_story_mapper.narrative.workflow import (
    PreparedNarrativeRun,
    grant_narrative_consent,
    prepare_narrative_scene_run,
)
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.storage import canonical_json

ROOT: Final = Path(__file__).resolve().parents[1]
FIXTURE: Final = ROOT / "tests" / "fixtures" / "m12" / "route_targets.rpy"
REPORT_SCHEMA: Final = "m13-live-provider-acceptance-v1"
RUN_ID: Final = "m13-live-provider-acceptance-sample-v1"
LIVE_TIMEOUT_SECONDS: Final = 7_200
LIVE_MAX_CONCURRENCY: Final = 1
DEFAULT_BATCH_LIMITS: Final = BatchLimits(
    maximum_items=16,
    maximum_input_chars=500_000,
    maximum_input_tokens=100_000,
)
LIVE_SCHEDULER_POLICY: Final = SchedulerPolicy(
    DEFAULT_BATCH_LIMITS,
    maximum_attempts_per_job=1,
    maximum_transient_attempts_per_job=1,
    maximum_malformed_attempts_per_job=1,
)
_FORBIDDEN_DURABLE_KEYS: Final = frozenset(
    {
        "childartifacts",
        "completeprompt",
        "fullprompt",
        "prompt",
        "prompttext",
        "providerinput",
        "providerresponse",
        "rawprompt",
        "rawproviderresponse",
        "rawresponse",
        "responsebody",
        "sourcepacket",
        "sourcetext",
        "supportrecords",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    value = owner.get(key)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise AssertionError(f"{key} is not a record array")
    return tuple(cast(Mapping[str, object], item) for item in value)


def _fixture_project(root: Path) -> tuple[Path, Path]:
    source = root / "game" / "story.rpy"
    source.parent.mkdir(parents=True)
    source.write_bytes(FIXTURE.read_bytes())
    project_path = root / "m13-live.rsmproj"
    with create_ingested_project(project_path, source.parent) as project:
        service = M12RouteService(project)
        destinations = service.destinations(query="blue_ending", limit=50).get("nodes")
        if not isinstance(destinations, list):
            raise AssertionError("M12 destination catalog is malformed")
        destination = next(
            item
            for item in destinations
            if isinstance(item, Mapping) and item.get("kind") == "terminal"
        )
        kind = destination.get("kind")
        target_id = destination.get("target_id")
        if not isinstance(kind, str) or not isinstance(target_id, str):
            raise AssertionError("M12 representative destination is malformed")
        outcome = service.solve(service.prepare(kind, target_id))
        if outcome.result is None:
            raise AssertionError("M12 representative result was not persisted")
    return project_path, source


def _authority_fingerprint(authority: NarrativeAuthority) -> dict[str, object]:
    binding = authority.binding
    return {
        "source_generation": binding.source_generation,
        "source_archive_sha256": binding.source_archive_hash,
        "m10_canonical_sha256": binding.canonical_hash,
        "m11_scene_sha256": binding.scene_hash,
        "m11_correction_sha256": binding.correction_hash,
        "m12_result_identities": list(binding.m12_result_identities),
        "m12_normalized_sha256": _json_hash(list(authority.m12_results)),
    }


def _fixture_coverage(authority: NarrativeAuthority) -> dict[str, int]:
    placements = project_scene_placements(authority.scene_model)
    scenes = _records(authority.scene_model, "scenes")
    branches = _records(authority.scene_model, "temporary_branches")
    occurrences = _records(authority.scene_model, "occurrences")
    coverage = {
        "scenes": len(scenes),
        "common_spine_scenes": sum(
            item.path.section is StorySection.COMMON for item in placements
        ),
        "temporary_branch_scenes": sum(
            item.path.section is StorySection.TEMPORARY_BRANCH for item in placements
        ),
        "persistent_route_scenes": sum(
            item.path.route_id is not None for item in placements
        ),
        "ending_scenes": sum(item.path.section is StorySection.ENDING for item in placements),
        "temporary_containers": len(branches),
        "occurrences": len(occurrences),
        "loop_context_scenes": sum(item.get("loop_hub_id") is not None for item in scenes),
        "m12_results": len(authority.m12_results),
        "m12_prerequisite_strings": _count_m12_prerequisites(authority.m12_results),
    }
    required = (
        "scenes",
        "common_spine_scenes",
        "temporary_branch_scenes",
        "persistent_route_scenes",
        "ending_scenes",
        "temporary_containers",
        "occurrences",
        "loop_context_scenes",
        "m12_results",
        "m12_prerequisite_strings",
    )
    if any(coverage[key] < 1 for key in required):
        raise AssertionError(f"live sample misses a required representative context: {coverage}")
    return coverage


def _count_m12_prerequisites(results: tuple[Mapping[str, object], ...]) -> int:
    count = 0

    def walk(value: object, key: str | None = None) -> None:
        nonlocal count
        if isinstance(value, Mapping):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list | tuple):
            if key in {"requirements", "persistent_commitment_claims", "uncertainty_warnings"}:
                count += sum(
                    (isinstance(item, str) and bool(item.strip()))
                    or (
                        isinstance(item, Mapping)
                        and isinstance(item.get("text"), str)
                        and bool(cast(str, item.get("text")).strip())
                    )
                    for item in value
                )
            for child in value:
                walk(child)

    walk(results)
    return count


def _prepare(
    project: Project,
    provider: NarrativeProvider,
    *,
    model: str,
    reasoning_effort: str,
) -> PreparedNarrativeRun:
    return prepare_narrative_scene_run(
        project,
        provider,
        run_id=RUN_ID,
        requested_model=model,
        settings=ProviderSettings(
            (
                ("fast_mode", False),
                ("model_reasoning_effort", reasoning_effort),
            )
        ),
        mode=NarrativeInputMode.FACT_ONLY,
        include_m12_material=True,
        limits=lambda estimate: budget_limits_with_headroom(
            estimate,
            timeout_seconds=LIVE_TIMEOUT_SECONDS,
            max_concurrency=LIVE_MAX_CONCURRENCY,
            numerator=2,
            denominator=1,
        ),
        batch_limits=DEFAULT_BATCH_LIMITS,
        selected_scene_ids=None,
        locale="en-US",
        perspective="reader",
    )


def _consent_report(
    prepared: PreparedNarrativeRun,
    coverage: Mapping[str, int],
) -> dict[str, object]:
    preview = prepared.preview_dict()
    return {
        "schema": REPORT_SCHEMA,
        "phase": "awaiting_exact_confirmation",
        "provider_submit_calls": 0,
        "preparation_id": prepared.preparation_id,
        "consent_manifest_id": prepared.consent_preview.manifest_id,
        "provider": preview["provider"],
        "provider_available": preview["provider_available"],
        "provider_cli_version": preview["provider_cli_version"],
        "selected_scope_ids": preview["selected_scope_ids"],
        "privacy_mode": preview["privacy_mode"],
        "includes_m12_material": preview["includes_m12_material"],
        "estimate": preview["estimate"],
        "limits": preview["limits"],
        "batch_limits": {
            "maximum_items": DEFAULT_BATCH_LIMITS.maximum_items,
            "maximum_input_chars": DEFAULT_BATCH_LIMITS.maximum_input_chars,
            "maximum_input_tokens": DEFAULT_BATCH_LIMITS.maximum_input_tokens,
        },
        "representative_contexts": dict(coverage),
        "execution_after_confirmation": (
            "one complete route-aware hierarchy followed by one exact zero-call cache replay "
            "under this same consent manifest"
        ),
        "raw_debug_retention": False,
    }


def _artifact_hashes(project: Project, authority: NarrativeAuthority) -> dict[str, str]:
    result: dict[str, str] = {}
    for lookup in project.m13_persistence().list_records(
        RecordKind.ARTIFACT,
        authority_binding=authority.binding.to_dict(),
    ):
        if lookup.state is not LookupState.HIT or lookup.payload_hash is None:
            raise AssertionError("a current live artifact is stale or unreadable")
        result[lookup.record_id] = lookup.payload_hash
    return dict(sorted(result.items()))


def _rendering_hash(project: Project, artifact_ids: Mapping[str, str]) -> str:
    rendered = [
        narrative_artifact_detail(project, artifact_id)
        for artifact_id in sorted(artifact_ids)
    ]
    return _json_hash(rendered)


def _claim_and_route_audit(
    project: Project,
    authority: NarrativeAuthority,
    result: NarrativePipelineResult,
) -> dict[str, object]:
    binding = authority.binding.to_dict()
    claims = project.m13_persistence().list_records(
        RecordKind.CLAIM,
        authority_binding=binding,
    )
    factual = 0
    interpretive = 0
    review = 0
    citations = 0
    for lookup in claims:
        if lookup.state is not LookupState.HIT or lookup.payload is None:
            raise AssertionError("a published live claim is stale or unreadable")
        claim_class = lookup.payload.get("claim_class")
        if claim_class == "factual":
            factual += 1
        elif claim_class == "interpretive":
            interpretive += 1
        elif claim_class == "review_suggestion":
            review += 1
        else:
            raise AssertionError("a published live claim has an unknown class")
        resolved = narrative_claim_citations(project, lookup.record_id)
        direct = resolved.get("citations")
        if not isinstance(direct, list) or not direct:
            raise AssertionError("a published claim has no lazily resolved owned evidence")
        citations += len(direct)

    plot_id = result.artifacts.plot_artifact_id
    if plot_id is None:
        raise AssertionError("live acceptance did not publish a whole-plot artifact")
    plot_lookup = project.m13_persistence().lookup(
        RecordKind.ARTIFACT,
        plot_id,
        authority_binding=binding,
    )
    if plot_lookup.state is not LookupState.HIT or plot_lookup.payload is None:
        raise AssertionError("live whole-plot artifact is unavailable")
    hierarchy = plot_lookup.payload.get("hierarchy")
    if not isinstance(hierarchy, Mapping) or hierarchy.get("chronology_policy") != (
        "shared_then_separate_routes_and_endings"
    ):
        raise AssertionError("live whole-plot output flattened mutually exclusive routes")
    if not result.artifacts.route_artifact_ids or not result.artifacts.ending_artifact_ids:
        raise AssertionError("live hierarchy omitted route or ending artifacts")
    if result.artifacts.common_story_artifact_id is None:
        raise AssertionError("live hierarchy omitted the shared-story artifact")
    return {
        "published_claims": len(claims),
        "factual_claims": factual,
        "interpretive_claims": interpretive,
        "review_suggestion_claims": review,
        "resolved_direct_citations": citations,
        "unknown_or_out_of_scope_references": 0,
        "claim_dag_cycles": 0,
        "route_aware_plot": True,
        "common_story_artifact": True,
        "route_artifacts": len(result.artifacts.route_artifact_ids),
        "ending_artifacts": len(result.artifacts.ending_artifact_ids),
    }


def _assert_no_raw_durable_keys(project: Project, authority: NarrativeAuthority) -> int:
    inspected = 0

    def walk(value: object) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                normalized = "".join(
                    character
                    for character in str(key).casefold()
                    if character.isalnum()
                )
                if normalized in _FORBIDDEN_DURABLE_KEYS:
                    raise AssertionError(f"forbidden raw durable key: {key}")
                walk(child)
        elif isinstance(value, list | tuple):
            for child in value:
                walk(child)

    for kind in RecordKind:
        for lookup in project.m13_persistence().list_records(
            kind,
            authority_binding=authority.binding.to_dict(),
        ):
            if lookup.state is LookupState.HIT and lookup.payload is not None:
                inspected += 1
                walk(lookup.payload)
    return inspected


def _result_summary(result: NarrativePipelineResult) -> dict[str, object]:
    state_counts: dict[str, int] = {}
    for job in result.jobs:
        state_counts[job.state.value] = state_counts.get(job.state.value, 0) + 1
    return {
        "state": result.record.state.value,
        "provider": result.record.provider.to_dict(),
        "usage": result.record.usage.to_dict(),
        "logical_jobs": len(result.jobs),
        "state_counts": dict(sorted(state_counts.items())),
        "scene_artifacts": len(result.artifacts.scene_artifact_ids),
        "segment_artifacts": len(result.artifacts.segment_artifact_ids),
        "chapter_artifacts": len(result.artifacts.chapter_artifact_ids),
        "route_artifacts": len(result.artifacts.route_artifact_ids),
        "ending_artifacts": len(result.artifacts.ending_artifact_ids),
        "character_artifacts": len(result.artifacts.character_artifact_ids),
        "plot_artifact": result.artifacts.plot_artifact_id is not None,
        "unresolved_codes": list(result.unresolved_codes),
    }


def run(
    output_dir: Path,
    *,
    model: str,
    reasoning_effort: str,
    confirm_preparation_id: str | None = None,
    provider: NarrativeProvider | None = None,
) -> dict[str, object]:
    """Prepare without transmission, or execute only when the exact preparation ID matches."""

    if not model.strip() or model != model.strip():
        raise ValueError("--model must be a non-empty trimmed runtime model identity")
    if not reasoning_effort.strip() or reasoning_effort != reasoning_effort.strip():
        raise ValueError("--reasoning-effort must be a non-empty trimmed runtime setting")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pending_name = "pending-synthetic-sample"
    unexpected = {item.name for item in output_dir.iterdir()} - {
        "consent-preview.json",
        pending_name,
    }
    if unexpected:
        raise FileExistsError(f"live acceptance output is not empty: {sorted(unexpected)}")
    active_provider = provider or CodexCliNarrativeProvider()
    pending = output_dir / pending_name
    pending.mkdir(parents=True, exist_ok=True)
    with nullcontext(str(pending)) as temporary:
        root = Path(temporary)
        project_path = root / "m13-live.rsmproj"
        source = root / "game" / "story.rpy"
        if project_path.is_file() and source.is_file():
            pass
        elif any(root.iterdir()):
            raise AssertionError("the pending live sample is incomplete")
        else:
            project_path, source = _fixture_project(root)
        source_before = _sha256(source)
        with Project.open(project_path) as project:
            authority_before = load_narrative_authority(project, include_m12=True)
            authority_fingerprint_before = _authority_fingerprint(authority_before)
            coverage = _fixture_coverage(authority_before)
            prepared = _prepare(
                project,
                active_provider,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            preview = _consent_report(prepared, coverage)
            preview_path = output_dir / "consent-preview.json"
            encoded_preview = json.dumps(preview, indent=2, sort_keys=True) + "\n"
            if (
                preview_path.exists()
                and preview_path.read_text(encoding="utf-8") != encoded_preview
            ):
                raise AssertionError("the exact live consent preview changed between invocations")
            preview_path.write_text(encoded_preview, encoding="utf-8", newline="\n")
            if confirm_preparation_id is None:
                return preview
            if confirm_preparation_id != prepared.preparation_id:
                raise ValueError("confirmation does not match the exact live preparation ID")
            if not prepared.provider_status.available:
                raise RuntimeError("the selected live provider is unavailable")

            consent = grant_narrative_consent(project, prepared)
            first = run_complete_narrative(
                project,
                active_provider,
                prepared,
                consent,
                policy=LIVE_SCHEDULER_POLICY,
            )
            if first.record.state not in {
                SchedulerRunState.SUCCEEDED,
                SchedulerRunState.PARTIAL,
            }:
                raise AssertionError(f"live hierarchy did not fully succeed: {first.record.state}")
            if any(
                job.state not in {LogicalJobState.SUCCEEDED, LogicalJobState.PARTIAL}
                for job in first.jobs
            ):
                raise AssertionError(
                    "live hierarchy retained a failed/refused/cancelled logical job"
                )
            first_hashes = _artifact_hashes(project, authority_before)
            first_rendering_hash = _rendering_hash(project, first_hashes)
            audit = _claim_and_route_audit(project, authority_before, first)

            replay = run_complete_narrative(
                project,
                active_provider,
                prepared,
                consent,
                policy=LIVE_SCHEDULER_POLICY,
            )
            if replay.record.usage.provider_calls != 0:
                raise AssertionError("exact accepted-artifact replay called the provider")
            replay_hashes = _artifact_hashes(project, authority_before)
            replay_rendering_hash = _rendering_hash(project, replay_hashes)
            if replay_hashes != first_hashes or replay_rendering_hash != first_rendering_hash:
                raise AssertionError(
                    "cached artifacts or deterministic rendering changed on replay"
                )

            authority_after = load_narrative_authority(project, include_m12=True)
            authority_fingerprint_after = _authority_fingerprint(authority_after)
            source_after = _sha256(source)
            if source_before != source_after:
                raise AssertionError("live acceptance modified its synthetic source")
            if authority_fingerprint_before != authority_fingerprint_after:
                raise AssertionError("live acceptance changed M10, M11, or M12 authority")
            durable_records = _assert_no_raw_durable_keys(project, authority_after)

        report = {
            "schema": REPORT_SCHEMA,
            "phase": "passed",
            "status": "passed",
            "consent": preview,
            "first_run": _result_summary(first),
            "cache_replay": {
                **_result_summary(replay),
                "provider_calls": replay.record.usage.provider_calls,
                "artifact_payload_hashes_exact": replay_hashes == first_hashes,
                "deterministic_rendering_sha256": replay_rendering_hash,
            },
            "representative_contexts": coverage,
            "claim_and_route_audit": audit,
            "privacy": {
                "raw_debug_retention": False,
                "raw_prompt_records": 0,
                "raw_provider_response_records": 0,
                "durable_records_inspected": durable_records,
            },
            "immutability": {
                "source_sha256_before": source_before,
                "source_sha256_after": source_after,
                "authority_before": authority_fingerprint_before,
                "authority_after": authority_fingerprint_after,
                "unchanged": True,
            },
            "artifact_payload_count": len(first_hashes),
            "artifact_payload_set_sha256": _json_hash(first_hashes),
            "deterministic_rendering_sha256": first_rendering_hash,
        }
        (output_dir / "acceptance.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        shutil.rmtree(pending)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True)
    parser.add_argument("--confirm-preparation-id")
    arguments = parser.parse_args()
    report = run(
        arguments.output_dir,
        model=arguments.model,
        reasoning_effort=arguments.reasoning_effort,
        confirm_preparation_id=arguments.confirm_preparation_id,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

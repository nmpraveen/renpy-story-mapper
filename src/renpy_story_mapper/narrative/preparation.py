"""Deterministic scene-job preparation and one-run cloud consent estimates."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from renpy_story_mapper.narrative.authority import NarrativeAuthority
from renpy_story_mapper.narrative.batching import (
    BatchableSceneJob,
    BatchLimits,
    TransportBatch,
    pack_scene_jobs,
)
from renpy_story_mapper.narrative.contracts import (
    AuthorityBinding,
    AuthorityReference,
    AuthoritySystem,
    BudgetLimits,
    ConsentManifest,
    CostConfidence,
    InputRevision,
    JsonScalar,
    JsonValue,
    LogicalJob,
    LogicalJobKind,
    LogicalJobSpec,
    PrivacyMode,
    ProviderIdentity,
    RunEstimate,
    StructuralContext,
    canonical_hash,
)
from renpy_story_mapper.narrative.evidence import PromptHandleTable
from renpy_story_mapper.narrative.projection import (
    NarrativeInputMode,
    SceneInputPacket,
    project_scene_inputs,
)
from renpy_story_mapper.storage import canonical_json

M13_SCENE_PROVIDER_INPUT_SCHEMA = "m13-scene-provider-input-v1"
DEFAULT_SCENE_OUTPUT_TOKENS = 800
CHARS_PER_ESTIMATED_TOKEN = 4


@dataclass(frozen=True)
class ProviderPricing:
    """Optional explicit price sheet used only when its estimate is reliable."""

    input_micros_per_million_tokens: int
    output_micros_per_million_tokens: int

    def __post_init__(self) -> None:
        if self.input_micros_per_million_tokens < 0:
            raise ValueError("input token price cannot be negative")
        if self.output_micros_per_million_tokens < 0:
            raise ValueError("output token price cannot be negative")


@dataclass(frozen=True)
class PreparedSceneJob:
    """One independently identified and independently validatable scene job."""

    job: LogicalJob
    handles: PromptHandleTable
    payload: dict[str, JsonValue]
    deterministic_title: str
    ordinal: int
    estimated_input_tokens: int
    estimated_output_tokens: int = DEFAULT_SCENE_OUTPUT_TOKENS

    def __post_init__(self) -> None:
        if self.job.spec.kind is not LogicalJobKind.SCENE:
            raise ValueError("prepared scene work requires a scene logical job")
        if self.handles.scope_id != self.job.spec.job_id:
            raise ValueError("prepared handles must be bound to the logical job")
        if self.ordinal < 0:
            raise ValueError("prepared scene ordinal cannot be negative")
        if self.estimated_input_tokens < 1 or self.estimated_output_tokens < 1:
            raise ValueError("prepared token estimates must be positive")
        if canonical_hash(self.payload) != self.job.input_revision.normalized_input_hash:
            raise ValueError("prepared payload does not match its input revision")

    @property
    def input_chars(self) -> int:
        return len(canonical_json(self.payload).decode("utf-8"))

    def batchable(self) -> BatchableSceneJob:
        return BatchableSceneJob(
            logical_job_id=self.job.spec.job_id,
            input_revision=self.job.input_revision.identity,
            ordinal=self.ordinal,
            input_chars=self.input_chars,
            estimated_input_tokens=self.estimated_input_tokens,
        )


@dataclass(frozen=True)
class PreparedSceneRun:
    """A provider-neutral scene plan plus deterministic transport estimate."""

    jobs: tuple[PreparedSceneJob, ...]
    batches: tuple[TransportBatch, ...]
    estimate: RunEstimate


def prepare_scene_jobs(
    authority: NarrativeAuthority,
    *,
    mode: NarrativeInputMode,
    include_m12_material: bool = True,
    selected_scene_ids: tuple[str, ...] | None = None,
    locale: str = "und",
    perspective: str = "default",
    max_story_text_chars: int = 24_000,
    output_tokens_per_scene: int = DEFAULT_SCENE_OUTPUT_TOKENS,
) -> tuple[PreparedSceneJob, ...]:
    """Project exact authority into stable, prompt-local, independent scene work."""

    if not locale.strip() or not perspective.strip():
        raise ValueError("locale and perspective must be non-empty")
    if output_tokens_per_scene < 1:
        raise ValueError("scene output-token estimate must be positive")
    packets = project_scene_inputs(
        authority.canonical,
        authority.scene_model,
        m12_results=authority.m12_results if include_m12_material else (),
        mode=mode,
        max_story_text_chars=max_story_text_chars,
        source_archive_hash=authority.binding.source_archive_hash,
        correction_hash=authority.binding.correction_hash,
    )
    packet_ids = tuple(packet.scene_id for packet in packets)
    if selected_scene_ids is None:
        selected = set(packet_ids)
    else:
        if not selected_scene_ids or len(selected_scene_ids) != len(set(selected_scene_ids)):
            raise ValueError("selected scene IDs must be non-empty and unique")
        unknown = set(selected_scene_ids) - set(packet_ids)
        if unknown:
            raise ValueError(f"selected scene is outside current M11 authority: {min(unknown)}")
        selected = set(selected_scene_ids)

    prepared: list[PreparedSceneJob] = []
    for ordinal, packet in enumerate(packets):
        if packet.scene_id not in selected:
            continue
        prepared.append(
            _prepare_scene(
                packet,
                ordinal=ordinal,
                locale=locale,
                perspective=perspective,
                output_tokens=output_tokens_per_scene,
                authority_binding=authority.binding,
            )
        )
    return tuple(prepared)


def plan_scene_run(
    jobs: tuple[PreparedSceneJob, ...],
    *,
    batch_limits: BatchLimits,
    pricing: ProviderPricing | None = None,
) -> PreparedSceneRun:
    """Pack only the transport layer and calculate one manifest-ready estimate."""

    if not jobs:
        raise ValueError("a scene run requires at least one logical job")
    logical_ids = tuple(item.job.spec.job_id for item in jobs)
    if len(logical_ids) != len(set(logical_ids)):
        raise ValueError("a scene run cannot repeat a logical job")
    batches = pack_scene_jobs(tuple(item.batchable() for item in jobs), batch_limits)
    input_tokens = sum(item.estimated_input_tokens for item in jobs)
    output_tokens = sum(item.estimated_output_tokens for item in jobs)
    if pricing is None:
        estimated_cost = None
        confidence = CostConfidence.UNAVAILABLE
    else:
        estimated_cost = math.ceil(
            (
                input_tokens * pricing.input_micros_per_million_tokens
                + output_tokens * pricing.output_micros_per_million_tokens
            )
            / 1_000_000
        )
        confidence = CostConfidence.RELIABLE
    estimate = RunEstimate(
        logical_job_count=len(jobs),
        provider_call_count=len(batches),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_micros=estimated_cost,
        cost_confidence=confidence,
    )
    return PreparedSceneRun(jobs, batches, estimate)


def build_cloud_consent(
    run: PreparedSceneRun,
    *,
    run_id: str,
    provider: ProviderIdentity,
    selected_scope_ids: tuple[str, ...],
    privacy_mode: PrivacyMode,
    includes_m12_material: bool,
    limits: BudgetLimits,
    consent_granted: bool = False,
) -> ConsentManifest:
    """Create one scope-bound consent manifest, disabled unless explicitly granted."""

    _require_estimate_within_limits(run.estimate, limits)
    return ConsentManifest(
        run_id=run_id,
        provider=provider,
        selected_scope_ids=selected_scope_ids,
        privacy_mode=privacy_mode,
        includes_m12_material=includes_m12_material,
        estimate=run.estimate,
        limits=limits,
        consent_granted=consent_granted,
    )


def _prepare_scene(
    packet: SceneInputPacket,
    *,
    ordinal: int,
    locale: str,
    perspective: str,
    output_tokens: int,
    authority_binding: AuthorityBinding,
) -> PreparedSceneJob:
    context = _structural_context(packet)
    spec = LogicalJobSpec(
        kind=LogicalJobKind.SCENE,
        owner_id=packet.scene_id,
        context=context,
        locale=locale,
        perspective=perspective,
    )
    references, support_data = _scene_support(packet)
    handles = PromptHandleTable.build(
        scope_id=spec.job_id,
        allowed_owner_ids=(packet.scene_id,),
        evidence_references=references,
    )
    handle_by_reference = {
        item.reference: item.handle for item in handles.evidence_handles
    }
    support_records: list[JsonValue] = []
    for item in handles.evidence_handles:
        record = support_data[item.reference]
        support_records.append(
            {
                "handle": item.handle,
                "authority": item.reference.authority.value,
                "record_kind": item.reference.record_kind,
                "record": record,
            }
        )
    payload: dict[str, JsonValue] = {
        "schema": M13_SCENE_PROVIDER_INPUT_SCHEMA,
        "job_kind": LogicalJobKind.SCENE.value,
        "logical_job_id": spec.job_id,
        "owner_handle": packet.scene_id,
        "locale": locale,
        "perspective": perspective,
        "privacy_mode": packet.mode.value,
        "deterministic_title": packet.deterministic_title,
        "structural_context": _json_value(dict(packet.structural_context)),
        "support_records": support_records,
        "omitted_support_count": len(packet.omitted_evidence_ids),
        "response_contract": {
            "support_class": "evidence_handles_only",
            "interpretation_label_required": True,
            "cross_scene_chronology_forbidden": True,
        },
    }
    if set(handle_by_reference) != set(support_data):
        raise ValueError("scene support handle projection is incomplete")
    revision = InputRevision(
        authority_binding,
        M13_SCENE_PROVIDER_INPUT_SCHEMA,
        canonical_hash(payload),
    )
    estimated_input_tokens = max(
        1,
        math.ceil(len(canonical_json(payload).decode("utf-8")) / CHARS_PER_ESTIMATED_TOKEN),
    )
    return PreparedSceneJob(
        job=LogicalJob(spec, revision),
        handles=handles,
        payload=payload,
        deterministic_title=packet.deterministic_title,
        ordinal=ordinal,
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=output_tokens,
    )


def _structural_context(packet: SceneInputPacket) -> StructuralContext:
    raw = packet.structural_context
    chapter_id = _optional_text(raw.get("chapter_id"), "chapter ID")
    lane_id = _optional_text(raw.get("lane_id"), "lane ID")
    loop_id = _optional_text(raw.get("loop_hub_id"), "loop ID")
    ordinal = raw.get("ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise ValueError("scene chronology ordinal is invalid")
    return StructuralContext(
        chapter_id=chapter_id,
        lane_id=lane_id,
        loop_id=loop_id,
        temporal_anchor=f"scene-ordinal:{ordinal}",
        structural_fingerprint=canonical_hash(dict(raw)),
    )


def _scene_support(
    packet: SceneInputPacket,
) -> tuple[tuple[AuthorityReference, ...], dict[AuthorityReference, JsonValue]]:
    owner = packet.scene_id
    records: dict[AuthorityReference, JsonValue] = {}
    scene_reference = AuthorityReference(AuthoritySystem.M11, "scene", owner, owner)
    records[scene_reference] = {
        "title": packet.deterministic_title,
        "structural_context": _json_value(dict(packet.structural_context)),
    }
    for atom in packet.atom_records:
        atom_id = _record_id(atom, "M11 atom")
        reference = AuthorityReference(AuthoritySystem.M11, "atom", atom_id, owner)
        records[reference] = _record_without_ids(atom, ("id",))
    for fact in packet.fact_records:
        fact_id = _record_id(fact, "M10 fact")
        reference = AuthorityReference(AuthoritySystem.M10, "fact", fact_id, owner)
        records[reference] = _record_without_ids(fact, ("id", "evidence_ids"))
    for evidence in packet.evidence:
        reference = AuthorityReference(
            AuthoritySystem.M10,
            "evidence",
            evidence.evidence_id,
            owner,
        )
        records[reference] = {"source_text": evidence.source_text}
    for route in packet.m12_records:
        route_id = _record_id(route, "M12 route result", key="request_identity")
        reference = AuthorityReference(AuthoritySystem.M12, "route_result", route_id, owner)
        records[reference] = _record_without_ids(route, ("request_identity",))
    return tuple(records), records


def _record_id(
    record: Mapping[str, object],
    label: str,
    *,
    key: str = "id",
) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} has no stable ID")
    return value


def _record_without_ids(
    record: Mapping[str, object],
    excluded: tuple[str, ...],
) -> JsonValue:
    value = {
        str(key): item for key, item in record.items() if str(key) not in excluded
    }
    return _json_value(value)


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | bool | int):
        return cast(JsonScalar, value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("provider input cannot contain non-finite numbers")
        return value
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise ValueError("provider input contains a non-JSON value")


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string when present")
    return value


def _require_estimate_within_limits(estimate: RunEstimate, limits: BudgetLimits) -> None:
    if estimate.provider_call_count > limits.max_provider_calls:
        raise ValueError("estimated provider calls exceed the consent limit")
    if estimate.input_tokens > limits.max_input_tokens:
        raise ValueError("estimated input tokens exceed the consent limit")
    if estimate.output_tokens > limits.max_output_tokens:
        raise ValueError("estimated output tokens exceed the consent limit")
    if estimate.input_tokens + estimate.output_tokens > limits.max_total_tokens:
        raise ValueError("estimated total tokens exceed the consent limit")
    if (
        estimate.estimated_cost_micros is not None
        and limits.max_cost_micros is not None
        and estimate.estimated_cost_micros > limits.max_cost_micros
    ):
        raise ValueError("estimated provider cost exceeds the consent limit")

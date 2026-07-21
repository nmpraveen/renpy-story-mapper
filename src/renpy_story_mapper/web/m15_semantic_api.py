"""Strict product adapter for the M15.1 semantic production lifecycle.

This module is the only web-facing bridge from current M10/M11 authority to the
transient semantic provider inputs.  Prepared prompt payloads and source text
never enter its response serializers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol

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
    assemble_semantic_outline_from_authority,
    build_all_eligible_gap_candidates,
    build_boundary_windows,
    build_fine_narrative_units,
    build_semantic_quotient_topology,
)
from renpy_story_mapper.narrative_map.adapters import bind_m15_authority
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    SourceLocator,
    canonical_hash,
)
from renpy_story_mapper.narrative_map.persistence import NarrativeJobStatus
from renpy_story_mapper.narrative_map.provider import (
    NarrativeConsentManifest,
    NarrativeMapProvider,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    ProviderProfile,
    SterileNarrativeMapProvider,
)
from renpy_story_mapper.project import Project

M15_SEMANTIC_RESPONSE_SCHEMA: Final = "m15-semantic-production-v1"
M15_SEMANTIC_CORRECTION_ID: Final = "m15.1-product-path-v1"
M15_SEMANTIC_PRIVACY_SCOPE: Final = "story_evidence_only"
M15_SEMANTIC_MODEL: Final = "gpt-5.6-sol"
M15_SEMANTIC_REASONING: Final = "medium"
M15_SEMANTIC_MAXIMUM_CONCURRENCY: Final = 1
M15_SEMANTIC_CONSENT_VALID_FOR: Final = timedelta(hours=1)


class M15ProviderFactory(Protocol):
    def __call__(self) -> NarrativeMapProvider: ...


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

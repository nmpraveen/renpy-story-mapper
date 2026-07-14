"""Static project analysis pipeline over durable SQLite storage.

This module only parses inert source text. It never imports, evaluates, or executes game code.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import cast

from renpy_story_mapper import storage
from renpy_story_mapper.analysis_phases import (
    AnalysisStatus,
    PhaseBinding,
    analysis_state_payload,
    payload_bindings,
)
from renpy_story_mapper.canonical_graph import build_canonical_graph
from renpy_story_mapper.canonical_graph_contract import (
    source_generation as canonical_source_generation,
)
from renpy_story_mapper.canonical_graph_contract import (
    stable_origin_record_id,
)
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.errors import ScriptParseError, StoryMapperError
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.importer import inventory_archive
from renpy_story_mapper.inspection_projection import project_inspection_graph
from renpy_story_mapper.model import (
    Call,
    If,
    IfBranch,
    Jump,
    Label,
    LabelAnchor,
    Menu,
    MenuCaption,
    MenuChoice,
    Opaque,
    Return,
    ScriptModule,
    Simple,
    SourceSpan,
    Statement,
)
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import (
    PayloadRecord,
    Project,
    RefreshReport,
    SourceFingerprint,
)
from renpy_story_mapper.route_map import project_route_map
from renpy_story_mapper.rpa import RpaArchive, fingerprint_file
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import (
    FactStatus,
    StateAnalysis,
    StateEvidence,
    default_display_name,
    extract_state,
    infer_state_category,
)
from renpy_story_mapper.storage import ProjectOperationCancelled, canonical_json
from renpy_story_mapper.story_metadata import StoryMetadataLimitError, extract_story_metadata

CancelCheck = Callable[[], bool] | None
AnalysisProgress = Callable[[str, int], None] | None


def create_input_project(
    database_path: str | os.PathLike[str],
    input_path: str | os.PathLike[str],
    *,
    entry_label: str = "start",
    options: object | None = None,
    cancel_check: CancelCheck = None,
    progress: AnalysisProgress = None,
) -> Project:
    """Create a project through the unified schema-v5 ingestion boundary."""

    from renpy_story_mapper.ingestion import IngestionOptions, ingest_input

    configured = options if isinstance(options, IngestionOptions) else IngestionOptions()
    result = ingest_input(input_path, configured, cancel_check)
    if result.plan.existing_project is not None:
        return Project.open(result.plan.existing_project)
    project = Project.create(
        database_path,
        metadata={
            "source_kind": result.plan.input_kind.value,
            "source_path": str(result.plan.resolved_input),
            "entry_label": entry_label,
            "source_coverage_complete": result.complete,
        },
    )
    try:
        all_sources = (*result.sources, *result.secondary_sources)
        fingerprints = tuple(
            SourceFingerprint.from_bytes(
                source.path,
                source.content,
                metadata=source.provenance.to_dict(),
            )
            for source in all_sources
        )
        story_metadata = _input_story_metadata(result, cancel_check)
        _refresh_open_project(
            project,
            result.content_by_path,
            entry_label=entry_label,
            cancel_check=cancel_check,
            source_fingerprints=fingerprints,
            story_metadata=story_metadata,
            story_metadata_source_paths=tuple(source.path for source in all_sources),
            progress=progress,
        )
        project.replace_ingestion_provenance(result)
        return project
    except BaseException:
        if project.payload("m10_analysis_state", "authoritative") is None:
            project.delete()
        else:
            project.close()
        raise


def refresh_input_project(
    database_path: str | os.PathLike[str],
    input_path: str | os.PathLike[str],
    *,
    options: object | None = None,
    cancel_check: CancelCheck = None,
    progress: AnalysisProgress = None,
) -> RefreshReport:
    """Refresh an existing project through unified ingestion using atomic staging."""

    from renpy_story_mapper.ingestion import IngestionOptions, ingest_input

    configured = options if isinstance(options, IngestionOptions) else IngestionOptions()
    result = ingest_input(input_path, configured, cancel_check)
    if result.plan.existing_project is not None:
        raise ValueError(
            "an existing project input is already current and cannot refresh another project"
        )
    project_path = Path(database_path).resolve(strict=True)
    temporary = project_path.with_name(f".{project_path.name}.{uuid.uuid4().hex}.refresh.tmp")
    original = Project.open(project_path)
    try:
        original.backup(temporary)
    finally:
        original.close()
    try:
        staged = Project.open(temporary)
        try:
            entry_label = str(staged.metadata().get("entry_label", "start"))
            all_sources = (*result.sources, *result.secondary_sources)
            fingerprints = tuple(
                SourceFingerprint.from_bytes(
                    source.path,
                    source.content,
                    metadata=source.provenance.to_dict(),
                )
                for source in all_sources
            )
            story_metadata = _input_story_metadata(result, cancel_check)
            report = _refresh_open_project(
                staged,
                result.content_by_path,
                entry_label=entry_label,
                cancel_check=cancel_check,
                source_fingerprints=fingerprints,
                story_metadata=story_metadata,
                story_metadata_source_paths=tuple(source.path for source in all_sources),
                progress=progress,
            )
            staged.replace_ingestion_provenance(result)
            staged.set_metadata({"source_coverage_complete": result.complete})
        except BaseException:
            staged.close()
            with Project.open(temporary) as partial:
                publish_partial = (
                    partial.payload("m10_analysis_state", "authoritative") is not None
                )
            if publish_partial:
                os.replace(temporary, project_path)
            raise
        finally:
            staged.close()
        _check_cancelled(cancel_check)
        os.replace(temporary, project_path)
        return report
    finally:
        if temporary.exists():
            temporary.unlink()


def create_folder_project(
    database_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    *,
    cancel_check: CancelCheck = None,
) -> Project:
    root = _source_root(source_root)
    _check_cancelled(cancel_check)
    project = Project.create(
        database_path,
        metadata={"source_kind": "folder", "source_root": str(root), "entry_label": "start"},
    )
    try:
        _refresh_open_project(
            project,
            _read_source_tree(root, cancel_check=cancel_check),
            entry_label="start",
            cancel_check=cancel_check,
        )
        return project
    except BaseException:
        project.delete()
        raise


def refresh_folder_project(
    database_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    *,
    cancel_check: CancelCheck = None,
) -> RefreshReport:
    root = _source_root(source_root)
    project_path = Path(database_path).resolve(strict=True)
    _check_cancelled(cancel_check)
    content = _read_source_tree(root, cancel_check=cancel_check)
    temporary = project_path.with_name(f".{project_path.name}.{uuid.uuid4().hex}.refresh.tmp")
    _check_cancelled(cancel_check)
    original = Project.open(project_path)
    try:
        if _content_matches(original, content):
            _check_cancelled(cancel_check)
            return RefreshReport((), tuple(sorted(content)), ())
        original.backup(temporary)
    finally:
        original.close()
    try:
        staged = Project.open(temporary)
        try:
            metadata = staged.metadata()
            entry_label = str(metadata.get("entry_label", "start"))
            report = _refresh_open_project(
                staged,
                content,
                entry_label=entry_label,
                cancel_check=cancel_check,
            )
        finally:
            staged.close()
        _check_cancelled(cancel_check)
        os.replace(temporary, project_path)
        return report
    finally:
        if temporary.exists():
            temporary.unlink()


def create_rpa_project(
    database_path: str | os.PathLike[str],
    archive_path: str | os.PathLike[str],
    *,
    entry_label: str = "start",
    cancel_check: CancelCheck = None,
) -> Project:
    archive = Path(archive_path).resolve(strict=True)
    _check_cancelled(cancel_check)
    content, manifest = _read_archive_sources(archive, cancel_check=cancel_check)
    project = Project.create(
        database_path,
        metadata={
            "source_kind": "archive",
            "source_path": str(archive),
            "entry_label": entry_label,
        },
    )
    try:
        _refresh_open_project(project, content, entry_label=entry_label, cancel_check=cancel_check)
        project.write_payloads(
            [PayloadRecord("import_manifest", "authoritative", manifest, tuple(sorted(content)))],
            cancelled=cancel_check,
        )
        return project
    except BaseException:
        project.delete()
        raise


def refresh_rpa_project(
    database_path: str | os.PathLike[str],
    archive_path: str | os.PathLike[str],
    *,
    cancel_check: CancelCheck = None,
) -> RefreshReport:
    archive = Path(archive_path).resolve(strict=True)
    content, manifest = _read_archive_sources(archive, cancel_check=cancel_check)
    project_path = Path(database_path).resolve(strict=True)
    temporary = project_path.with_name(f".{project_path.name}.{uuid.uuid4().hex}.refresh.tmp")
    original = Project.open(project_path)
    try:
        if _content_matches(original, content):
            _check_cancelled(cancel_check)
            if original.payload("import_manifest", "authoritative") != manifest:
                original.write_payloads(
                    [
                        PayloadRecord(
                            "import_manifest",
                            "authoritative",
                            manifest,
                            tuple(sorted(content)),
                        )
                    ],
                    cancelled=cancel_check,
                )
            return RefreshReport((), tuple(sorted(content)), ())
        original.backup(temporary)
    finally:
        original.close()
    try:
        staged = Project.open(temporary)
        try:
            metadata = staged.metadata()
            entry_label = str(metadata.get("entry_label", "start"))
            report = _refresh_open_project(
                staged, content, entry_label=entry_label, cancel_check=cancel_check
            )
            staged.write_payloads(
                [
                    PayloadRecord(
                        "import_manifest", "authoritative", manifest, tuple(sorted(content))
                    )
                ],
                cancelled=cancel_check,
            )
        finally:
            staged.close()
        _check_cancelled(cancel_check)
        os.replace(temporary, project_path)
        return report
    finally:
        if temporary.exists():
            temporary.unlink()


def project_snapshot(project: Project) -> dict[str, object]:
    return {
        "schema_version": project.schema_version,
        "sources": [
            {
                "path": source.path,
                "sha256": source.content_hash,
                "size_bytes": source.size_bytes,
            }
            for source in project.sources()
        ],
        "graph": project.payload("m01_graph", "authoritative") or {},
        "semantic": project.payload("m02_semantic", "authoritative") or {},
        "control_flow": project.payload("m06_control_flow", "authoritative") or {},
        "route_map": project.payload("m07_route_map", "authoritative") or {},
        "import_manifest": project.payload("import_manifest", "authoritative") or {},
        "source_derivations": list(project.source_derivations()),
        "recovery_results": list(project.recovery_results()),
        "source_coverage": project.source_coverage(),
        "requirements": _payload_lists(project, "gates"),
        "effects": _payload_lists(project, "effects"),
        "state_variables": _payload_lists(project, "state_registry"),
        "unresolved": _payload_lists(project, "unresolved"),
        "diagnostics": _payload_lists(project, "diagnostics"),
    }


def persist_story_metadata(
    project: Project,
    payload: Mapping[str, object],
    *,
    source_paths: Sequence[str],
    cancel_check: CancelCheck = None,
) -> bool:
    """Persist deterministic advisory metadata and refresh only its derived presentation.

    The caller supplies logical source paths that already exist in the project source inventory.
    ``True`` means either the metadata payload/dependencies or merged state registry changed.
    """

    value = _validated_story_metadata(payload)
    dependencies = tuple(sorted(set(source_paths)))
    if len(dependencies) != len(source_paths):
        raise ValueError("story metadata source_paths must be unique")
    _check_cancelled(cancel_check)

    previous_metadata = project.payload("story_metadata", "authoritative")
    previous_registry = project.payload("state_registry", "authoritative")
    registry = _story_metadata_state_registry(previous_registry, value)
    metadata_changed = previous_metadata != value or _payload_source_paths(
        project, "story_metadata", "authoritative"
    ) != dependencies
    registry_changed = previous_registry != registry
    if not metadata_changed and not registry_changed:
        return False

    records: list[PayloadRecord] = []
    if metadata_changed:
        records.append(PayloadRecord("story_metadata", "authoritative", value, dependencies))
    if registry_changed:
        registry_dependencies = _payload_source_paths(
            project, "state_registry", "authoritative"
        )
        records.append(
            PayloadRecord(
                "state_registry", "authoritative", registry, registry_dependencies
            )
        )
    project.write_payloads(records, cancelled=cancel_check)
    from renpy_story_mapper.presentation import rebuild_presentation_index

    rebuild_presentation_index(project, cancelled=cancel_check)
    return True


def _input_story_metadata(result: object, cancel_check: CancelCheck) -> dict[str, object]:
    from renpy_story_mapper.ingestion.contracts import IngestionResult

    if not isinstance(result, IngestionResult):
        raise TypeError("result must be an IngestionResult")
    try:
        return extract_story_metadata(
            result.sources,
            result.secondary_sources,
            cancel_check=cancel_check,
        )
    except StoryMetadataLimitError as exc:
        return {
            "schema_version": 1,
            "characters": [],
            "state_hints": [],
            "scene_titles": [],
            "sources": [],
            "diagnostics": [
                {
                    "code": "metadata_limits_exceeded",
                    "message": " ".join(str(exc).split())[:500],
                }
            ],
        }


def _refresh_open_project(
    project: Project,
    content_by_path: Mapping[str, bytes],
    *,
    entry_label: str,
    cancel_check: CancelCheck,
    source_metadata: Mapping[str, object] | None = None,
    source_fingerprints: Sequence[SourceFingerprint] | None = None,
    story_metadata: Mapping[str, object] | None = None,
    story_metadata_source_paths: Sequence[str] = (),
    progress: AnalysisProgress = None,
) -> RefreshReport:
    previous_dependencies = _stored_dependencies(project)
    previous_registry = project.payload("state_registry", "authoritative")
    previous_story_metadata = project.payload("story_metadata", "authoritative")
    previous_canonical = project.payload("m10_canonical_graph", "authoritative")
    previous_inspection = project.payload("m10_inspection_projection", "authoritative")
    previous_canonical_generation, previous_canonical_hash = _canonical_identity(
        previous_canonical
    )
    if previous_canonical is not None:
        # Canonical generations are retained explicitly as stale read models rather than
        # participating in source-dependency deletion.
        project.write_payloads(
            (PayloadRecord("m10_canonical_graph", "authoritative", previous_canonical),)
        )
    if previous_inspection is not None:
        # The last-good simplified projection stays usable with its generation marker.
        project.write_payloads(
            (
                PayloadRecord(
                    "m10_inspection_projection", "authoritative", previous_inspection
                ),
            )
        )
    fingerprints = (
        tuple(source_fingerprints)
        if source_fingerprints is not None
        else tuple(
            SourceFingerprint.from_bytes(
                path,
                content_by_path[path],
                metadata=(
                    cast(Mapping[str, object], source_metadata[path])
                    if source_metadata is not None
                    else None
                ),
            )
            for path in sorted(content_by_path)
        )
    )
    source_generation = canonical_source_generation(
        tuple((item.path, item.content_hash) for item in fingerprints)
    )
    phases: list[PhaseBinding] = []
    phase = "source_inventory"
    phase_started = time.perf_counter()
    state_initialized = False
    canonical_generation = previous_canonical_generation
    canonical_hash = previous_canonical_hash
    _emit_analysis_progress(progress, phase, 5)
    try:
        refresh = project.refresh_sources(fingerprints, cancelled=cancel_check)
        inventory_hash = hashlib.sha256(
            canonical_json(
                [
                    {"path": item.path, "content_hash": item.content_hash}
                    for item in sorted(fingerprints, key=lambda item: item.path)
                ]
            )
        ).hexdigest()
        phases.append(
            PhaseBinding(
                phase,
                source_generation,
                ({"collection": "sources", "key": "inventory", "payload_hash": inventory_hash},),
                _phase_duration(phase_started),
            )
        )
        _write_analysis_state(
            project,
            source_generation,
            AnalysisStatus.CURRENT_PARTIAL,
            phases,
            canonical_generation,
            canonical_hash,
        )
        state_initialized = True

        phase = "parse"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 20)
        canonical_paths = set(content_by_path)
        parsed_paths = set(refresh.changed) & canonical_paths
        modules: dict[str, ScriptModule] = {}
        for path in sorted(content_by_path):
            _check_cancelled(cancel_check)
            if path not in parsed_paths:
                cached = project.payload("parsed_source", path)
                if cached is not None:
                    modules[path] = _module_from_value(cached)
                    continue
                parsed_paths.add(path)
            modules[path] = _parse_source(path, content_by_path[path])
        module_values = [modules[path] for path in sorted(modules)]
        dependencies = _source_dependencies(module_values)
        invalidated = _dependent_closure(
            _merge_dependencies(previous_dependencies, dependencies),
            set(refresh.changed) | set(refresh.removed),
        )
        parsed_records = _parsed_records(modules, dependencies, parsed_paths)
        _write_phase(
            project,
            source_generation,
            phase,
            parsed_records,
            phases,
            cancel_check,
            phase_started,
        )

        phase = "graph"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 35)
        graph = build_graph(module_values, entry_label=entry_label)
        diagnostics = [item for module in module_values for item in module.diagnostics]
        diagnostics.sort(key=lambda item: canonical_json(item))
        graph["diagnostics"] = diagnostics
        counts = cast(dict[str, object], graph["counts"])
        counts["diagnostics"] = len(diagnostics)
        all_paths = tuple(sorted(modules))
        graph_records = [PayloadRecord("m01_graph", "authoritative", graph, all_paths)]
        _write_phase(
            project,
            source_generation,
            phase,
            graph_records,
            phases,
            cancel_check,
            phase_started,
        )

        phase = "semantic_state"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 50)
        semantic = build_semantic_story(graph)
        state = extract_state(module_values)
        effective_story_metadata = (
            _validated_story_metadata(story_metadata)
            if story_metadata is not None
            else previous_story_metadata
        )
        semantic_records = _semantic_state_records(
            modules,
            semantic,
            state,
            previous_registry,
            effective_story_metadata,
        )
        if story_metadata is not None:
            metadata_dependencies = tuple(sorted(set(story_metadata_source_paths)))
            if len(metadata_dependencies) != len(story_metadata_source_paths):
                raise ValueError("story metadata source paths must be unique")
            semantic_records.append(
                PayloadRecord(
                    "story_metadata",
                    "authoritative",
                    effective_story_metadata,
                    metadata_dependencies,
                )
            )
        _write_phase(
            project,
            source_generation,
            phase,
            semantic_records,
            phases,
            cancel_check,
            phase_started,
        )

        phase = "control_flow"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 65)
        control_flow = analyze_control_flow(
            graph,
            semantic,
            state.requirements,
            state.effects,
        ).to_dict()
        control_records = [
            PayloadRecord("m06_control_flow", "authoritative", control_flow, all_paths)
        ]
        _write_phase(
            project,
            source_generation,
            phase,
            control_records,
            phases,
            cancel_check,
            phase_started,
        )

        phase = "route_map"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 75)
        route_map = project_route_map(
            control_flow, semantic, state.requirements, state.effects
        )
        route_records = [
            PayloadRecord("m07_route_map", "authoritative", route_map.to_dict(), all_paths)
        ]
        _write_phase(
            project,
            source_generation,
            phase,
            route_records,
            phases,
            cancel_check,
            phase_started,
        )
        project.m07_model_service().register_scopes(
            route_map.scopes, generation=route_map.authority_hash
        )

        phase = "canonical_graph"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 85)
        canonical_graph = build_canonical_graph(
            graph,
            semantic,
            control_flow,
            route_map,
            state,
            source_generation=source_generation,
        )
        canonical_records = [
            PayloadRecord(
                "m10_canonical_graph", "authoritative", canonical_graph.to_dict()
            )
        ]
        project.write_payloads(canonical_records, cancelled=cancel_check)
        canonical_generation = source_generation
        canonical_hash = canonical_graph.authority_hash
        phases.append(
            PhaseBinding(
                phase,
                source_generation,
                payload_bindings(canonical_records),
                _phase_duration(phase_started),
            )
        )
        _write_analysis_state(
            project,
            source_generation,
            AnalysisStatus.CURRENT_PARTIAL,
            phases,
            canonical_generation,
            canonical_hash,
        )

        phase = "simplified_projection"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 92)
        inspection_projection = project_inspection_graph(canonical_graph, route_map)
        inspection_records = [
            PayloadRecord(
                "m10_inspection_projection",
                "authoritative",
                inspection_projection.to_dict(),
            )
        ]
        _write_phase(
            project,
            source_generation,
            phase,
            inspection_records,
            phases,
            cancel_check,
            phase_started,
        )

        phase = "inspection_projection"
        phase_started = time.perf_counter()
        _emit_analysis_progress(progress, phase, 96)
        from renpy_story_mapper.presentation import rebuild_presentation_index

        rebuild_presentation_index(project, cancelled=cancel_check)
        project.organization_service().reconcile_after_refresh()
        phases.append(
            PhaseBinding(
                phase,
                source_generation,
                (
                    {
                        "collection": "presentation_index",
                        "key": "authoritative",
                        "payload_hash": route_map.authority_hash,
                    },
                ),
                _phase_duration(phase_started),
            )
        )
        _write_analysis_state(
            project,
            source_generation,
            AnalysisStatus.CURRENT_COMPLETE,
            phases,
            canonical_generation,
            canonical_hash,
        )
        _emit_analysis_progress(progress, "complete", 100)
        reused = (set(refresh.unchanged) & canonical_paths) - parsed_paths
        return RefreshReport(
            tuple(sorted(parsed_paths)),
            tuple(sorted(reused)),
            tuple(sorted(invalidated)),
            refresh.removed,
        )
    except BaseException as exc:
        if state_initialized:
            with suppress(Exception):
                _write_analysis_state(
                    project,
                    source_generation,
                    AnalysisStatus.FAILED,
                    phases,
                    canonical_generation,
                    canonical_hash,
                    failure_phase=phase,
                    failure_code=_failure_code(exc),
                    failure_duration_seconds=_phase_duration(phase_started),
                )
        raise


def _parsed_records(
    modules: Mapping[str, ScriptModule],
    dependencies: Mapping[str, set[str]],
    parsed_paths: set[str],
) -> list[PayloadRecord]:
    all_paths = tuple(sorted(modules))
    records: list[PayloadRecord] = []
    for path in sorted(parsed_paths):
        records.append(
            PayloadRecord("parsed_source", path, _module_to_value(modules[path]), (path,))
        )
    for path in all_paths:
        records.append(
            PayloadRecord(
                "source_dependencies", path, sorted(dependencies.get(path, set())), (path,)
            )
        )
    return records


def _semantic_state_records(
    modules: Mapping[str, ScriptModule],
    semantic: dict[str, object],
    state: StateAnalysis,
    previous_registry: object,
    story_metadata: object,
) -> list[PayloadRecord]:
    all_paths = tuple(sorted(modules))
    records: list[PayloadRecord] = [
        PayloadRecord("m02_semantic", "authoritative", semantic, all_paths)
    ]

    requirements_by_path: dict[str, list[dict[str, object]]] = {}
    effects_by_path: dict[str, list[dict[str, object]]] = {}
    unresolved_by_path: dict[str, list[dict[str, object]]] = {}
    for requirement in state.requirements:
        value = _requirement_value(requirement.to_dict(), requirement.evidence)
        destination = (
            requirements_by_path if requirement.status is FactStatus.PROVEN else unresolved_by_path
        )
        destination.setdefault(requirement.evidence.source_file, []).append(value)
    for effect in state.effects:
        value = _effect_value(effect.to_dict(), effect.evidence)
        destination = (
            effects_by_path if effect.status is not FactStatus.UNRESOLVED else unresolved_by_path
        )
        destination.setdefault(effect.evidence.source_file, []).append(value)

    for path, values in _semantic_unresolved_by_path(semantic).items():
        unresolved_by_path.setdefault(path, []).extend(values)
    for path in all_paths:
        module_diagnostics = sorted(modules[path].diagnostics, key=canonical_json)
        if module_diagnostics:
            records.append(PayloadRecord("diagnostics", path, module_diagnostics, (path,)))
        if path in requirements_by_path:
            records.append(PayloadRecord("gates", path, requirements_by_path[path], (path,)))
        if path in effects_by_path:
            records.append(PayloadRecord("effects", path, effects_by_path[path], (path,)))
        if path in unresolved_by_path:
            unique = {str(value["id"]): value for value in unresolved_by_path[path]}
            ordered = [unique[key] for key in sorted(unique)]
            records.append(PayloadRecord("unresolved", path, ordered, (path,)))
    variables = [_state_variable_value(item.to_dict()) for item in state.variables]
    variables = _merge_state_variable_metadata(variables, previous_registry)
    variables = _story_metadata_state_registry(variables, story_metadata)
    records.append(PayloadRecord("state_registry", "authoritative", variables, all_paths))
    return records


def _write_phase(
    project: Project,
    source_generation: str,
    phase: str,
    records: Sequence[PayloadRecord],
    phases: list[PhaseBinding],
    cancel_check: CancelCheck,
    phase_started: float,
) -> None:
    project.write_payloads(records, cancelled=cancel_check)
    phases.append(
        PhaseBinding(
            phase,
            source_generation,
            payload_bindings(records),
            _phase_duration(phase_started),
        )
    )
    canonical_generation, canonical_hash = _canonical_identity(
        project.payload("m10_canonical_graph", "authoritative")
    )
    _write_analysis_state(
        project,
        source_generation,
        AnalysisStatus.CURRENT_PARTIAL,
        phases,
        canonical_generation,
        canonical_hash,
    )


def _write_analysis_state(
    project: Project,
    source_generation: str,
    status: AnalysisStatus,
    phases: Sequence[PhaseBinding],
    canonical_generation: str | None,
    canonical_hash: str | None,
    *,
    failure_phase: str | None = None,
    failure_code: str | None = None,
    failure_duration_seconds: float | None = None,
) -> None:
    simplified_generation, simplified_canonical_hash = _simplified_identity(
        project.payload("m10_inspection_projection", "authoritative")
    )
    value = analysis_state_payload(
        source_generation=source_generation,
        status=status,
        phases=phases,
        canonical_generation=canonical_generation,
        canonical_hash=canonical_hash,
        simplified_generation=simplified_generation,
        simplified_canonical_hash=simplified_canonical_hash,
        failure_phase=failure_phase,
        failure_code=failure_code,
        failure_duration_seconds=failure_duration_seconds,
    )
    project.write_payloads((PayloadRecord("m10_analysis_state", "authoritative", value),))


def _canonical_identity(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None
    generation = value.get("source_generation")
    if not isinstance(generation, str):
        return None, None
    return generation, hashlib.sha256(canonical_json(dict(value))).hexdigest()


def _simplified_identity(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None
    generation = value.get("source_generation")
    canonical_hash = value.get("canonical_graph_hash")
    if not isinstance(generation, str) or not isinstance(canonical_hash, str):
        return None, None
    return generation, canonical_hash


def _emit_analysis_progress(progress: AnalysisProgress, phase: str, percent: int) -> None:
    if progress is not None:
        progress(phase, percent)


def _phase_duration(started: float) -> float:
    return round(max(0.0, time.perf_counter() - started), 6)


def _failure_code(exc: BaseException) -> str:
    if isinstance(exc, ProjectOperationCancelled):
        return "cancelled"
    return f"{type(exc).__module__}.{type(exc).__qualname__}"[:200]


def _requirement_value(value: dict[str, object], evidence: StateEvidence) -> dict[str, object]:
    result = dict(value)
    result["evidence"] = _evidence_value(evidence)
    result["id"] = _stable_record_id("requirement", result)
    return result


def _effect_value(value: dict[str, object], evidence: StateEvidence) -> dict[str, object]:
    result = dict(value)
    result["evidence"] = _evidence_value(evidence)
    result["id"] = _stable_record_id("effect", result)
    return result


def _state_variable_value(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    raw_evidence = _required_list(result.get("evidence"), "state variable evidence")
    result["evidence"] = [_evidence_mapping_value(item) for item in raw_evidence]
    result["id"] = _stable_record_id(
        "state_variable", {"original_name": result.get("original_name")}
    )
    return result


def _merge_state_variable_metadata(
    inferred: list[dict[str, object]], previous: object
) -> list[dict[str, object]]:
    if not isinstance(previous, list):
        return inferred
    by_name: dict[str, dict[str, object]] = {}
    for item in previous:
        if isinstance(item, dict) and isinstance(item.get("original_name"), str):
            by_name[cast(str, item["original_name"])] = item
    for value in inferred:
        name = value.get("original_name")
        old = by_name.get(name) if isinstance(name, str) else None
        if old is None:
            continue
        for field in ("display_name", "category", "user_override"):
            if field in old:
                value[field] = old[field]
    return inferred


def _validated_story_metadata(payload: Mapping[str, object]) -> dict[str, object]:
    if payload.get("schema_version") != 1 or isinstance(payload.get("schema_version"), bool):
        raise ValueError("story metadata schema_version must be 1")
    result = dict(payload)
    for collection in ("characters", "state_hints", "scene_titles", "sources", "diagnostics"):
        raw_items = payload.get(collection)
        if not isinstance(raw_items, list):
            raise ValueError(f"story metadata {collection} must be an array")
        items: list[dict[str, object]] = []
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, Mapping):
                raise ValueError(f"story metadata {collection}[{index}] must be an object")
            items.append(dict(raw))
        result[collection] = items

    aliases: set[str] = set()
    for index, item in enumerate(cast(list[dict[str, object]], result["characters"])):
        alias = _metadata_text(item, "alias", f"characters[{index}]")
        _metadata_text(item, "display_name", f"characters[{index}]")
        _validated_metadata_source(item.get("source"), f"characters[{index}].source", True)
        if alias in aliases:
            raise ValueError(f"story metadata characters contains duplicate alias {alias!r}")
        aliases.add(alias)

    hint_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(cast(list[dict[str, object]], result["state_hints"])):
        name = _metadata_text(item, "name", f"state_hints[{index}]")
        kind = _metadata_text(item, "kind", f"state_hints[{index}]")
        if kind == "default":
            if "default" not in item:
                raise ValueError(f"story metadata state_hints[{index}].default is required")
            storage.canonical_json(item["default"])
        elif kind in {"display_label", "semantic_label"}:
            _metadata_text(item, "display_name", f"state_hints[{index}]")
            if kind == "semantic_label":
                _metadata_text(item, "category", f"state_hints[{index}]")
        else:
            raise ValueError(f"story metadata state_hints[{index}].kind is unsupported")
        _validated_metadata_source(item.get("source"), f"state_hints[{index}].source", True)
        identity = (name, kind)
        if identity in hint_keys:
            raise ValueError(
                f"story metadata state_hints contains duplicate {kind} for {name!r}"
            )
        hint_keys.add(identity)

    for index, item in enumerate(cast(list[dict[str, object]], result["scene_titles"])):
        _metadata_text(item, "title", f"scene_titles[{index}]")
        _metadata_text(item, "collection", f"scene_titles[{index}]")
        _validated_metadata_source(item.get("source"), f"scene_titles[{index}].source", True)
        if "key" in item:
            _metadata_text(item, "key", f"scene_titles[{index}]")

    for index, item in enumerate(cast(list[dict[str, object]], result["sources"])):
        _validated_metadata_source(item, f"sources[{index}]", False)
    return result


def _metadata_text(value: Mapping[str, object], field: str, context: str) -> str:
    text = value.get(field)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"story metadata {context}.{field} must be non-empty text")
    return text


def _validated_metadata_source(value: object, context: str, require_span: bool) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"story metadata {context} must be an object")
    for field in ("path", "role", "locator", "fingerprint", "line_basis"):
        _metadata_text(value, field, context)
    if require_span and not isinstance(value.get("span"), Mapping):
        raise ValueError(f"story metadata {context}.span must be an object")


def _story_metadata_state_registry(registry: object, metadata: object) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    if isinstance(registry, list):
        for raw in registry:
            if not isinstance(raw, dict) or not isinstance(raw.get("original_name"), str):
                raise storage.ProjectCorruptError("state registry contains an invalid record")
            value = dict(raw)
            if not bool(value.get("user_override")):
                if value.get("display_name") == value.get("metadata_display_name"):
                    value["display_name"] = default_display_name(cast(str, value["original_name"]))
                if value.get("category") == value.get("metadata_category"):
                    value["category"] = infer_state_category(
                        cast(str, value["original_name"])
                    ).value
            for field in (
                "metadata_display_name",
                "metadata_category",
                "metadata_source",
                "default_value",
                "default_declared",
            ):
                value.pop(field, None)
            values.append(value)

    hints = _metadata_state_hints(metadata)

    merged: list[dict[str, object]] = []
    by_name: dict[str, dict[str, object]] = {
        cast(str, value["original_name"]): value for value in values
    }
    for name, hint in hints.items():
        state_record = by_name.get(name)
        if state_record is None:
            state_record = {
                "original_name": name,
                "display_name": default_display_name(name),
                "category": infer_state_category(name).value,
                "evidence": [],
                "id": _stable_record_id("state_variable", {"original_name": name}),
                "metadata_only": True,
            }
            values.append(state_record)
            by_name[name] = state_record
        display_name = hint.get("display_name")
        category = hint.get("category")
        if (
            isinstance(display_name, str)
            and isinstance(category, str)
            and not bool(state_record.get("user_override"))
        ):
            state_record["display_name"] = display_name
            state_record["category"] = category
        if isinstance(display_name, str) and isinstance(category, str):
            state_record["metadata_display_name"] = display_name
            state_record["metadata_category"] = category
        state_record["metadata_source"] = hint["source"]
        if "default_value" in hint:
            state_record["default_value"] = hint["default_value"]
            state_record["default_declared"] = True

    for value in values:
        name = cast(str, value["original_name"])
        if value.get("metadata_only") and name not in hints:
            continue
        merged.append(value)
    merged.sort(key=lambda item: cast(str, item["original_name"]))
    return merged


def _metadata_state_hints(metadata: object) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    if not isinstance(metadata, Mapping) or not isinstance(metadata.get("state_hints"), list):
        return result
    for raw in cast(list[object], metadata["state_hints"]):
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        kind = raw.get("kind")
        source = raw.get("source")
        if (
            not isinstance(name, str)
            or not isinstance(kind, str)
            or not isinstance(source, Mapping)
        ):
            continue
        hint = result.setdefault(name, {})
        if kind == "default" and "default" in raw:
            hint["default_value"] = raw["default"]
            hint.setdefault("source", _metadata_source_path(source))
        elif kind in {"display_label", "semantic_label"} and isinstance(
            raw.get("display_name"), str
        ):
            display_name = cast(str, raw["display_name"])
            if kind == "semantic_label" or "display_name" not in hint:
                hint["display_name"] = display_name
                hint["category"] = (
                    cast(str, raw["category"])
                    if kind == "semantic_label" and isinstance(raw.get("category"), str)
                    else infer_state_category(f"{name}_{display_name}").value
                )
                hint["source"] = _metadata_source_path(source)
    return result


def _metadata_source_path(source: Mapping[str, object]) -> str:
    path = source.get("path")
    return path if isinstance(path, str) else "metadata"


def _payload_source_paths(project: Project, collection: str, key: str) -> tuple[str, ...]:
    rows = project._require_open().execute(
        """SELECT source_path FROM payload_dependencies
           WHERE collection=? AND record_key=? ORDER BY source_path""",
        (collection, key),
    )
    return tuple(str(row[0]) for row in rows)


def _semantic_unresolved_by_path(
    semantic: Mapping[str, object],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for raw in _required_list(semantic.get("unresolved"), "semantic unresolved"):
        value = dict(_required_mapping(raw, "semantic unresolved item"))
        source = _required_mapping(value.get("source"), "semantic unresolved source")
        path = _required_string(source.get("path"), "semantic unresolved source path")
        start = _required_mapping(source.get("start"), "semantic unresolved start")
        end = _required_mapping(source.get("end"), "semantic unresolved end")
        value["status"] = "unresolved"
        value["evidence"] = {
            "source_path": path,
            "start_line": _required_int(start.get("line"), "semantic start line"),
            "end_line": _required_int(end.get("line"), "semantic end line"),
        }
        result.setdefault(path, []).append(value)
    return result


def _evidence_value(evidence: StateEvidence) -> dict[str, object]:
    return {
        "source_path": evidence.source_file,
        "start_line": evidence.span.start_line,
        "end_line": evidence.span.end_line,
    }


def _evidence_mapping_value(raw: object) -> dict[str, object]:
    value = _required_mapping(raw, "state evidence")
    source = _required_mapping(value.get("source"), "state evidence source")
    start = _required_mapping(source.get("start"), "state evidence start")
    end = _required_mapping(source.get("end"), "state evidence end")
    return {
        "source_path": _required_string(value.get("source_file"), "state evidence path"),
        "start_line": _required_int(start.get("line"), "state evidence start line"),
        "end_line": _required_int(end.get("line"), "state evidence end line"),
    }


def _stable_record_id(kind: str, value: Mapping[str, object]) -> str:
    return stable_origin_record_id(kind, value)


def _payload_lists(project: Project, collection: str) -> list[object]:
    result: list[object] = []
    for key in project.payload_keys(collection):
        value = project.payload(collection, key)
        if not isinstance(value, list):
            raise ValueError(f"project {collection}/{key} payload must be a list")
        result.extend(value)
    return result


def _read_source_tree(root: Path, *, cancel_check: CancelCheck) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for candidate in sorted(root.rglob("*.rpy"), key=lambda item: item.as_posix().casefold()):
        _check_cancelled(cancel_check)
        if not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"source path escapes the selected root: {candidate}") from exc
        result[relative] = resolved.read_bytes()
    _check_cancelled(cancel_check)
    if not result:
        raise ValueError(f"source folder contains no .rpy files: {root}")
    return result


def _read_archive_sources(
    archive_path: Path, *, cancel_check: CancelCheck
) -> tuple[dict[str, bytes], dict[str, object]]:
    _check_cancelled(cancel_check)
    before = fingerprint_file(archive_path)
    archive = RpaArchive(archive_path)
    inventory = inventory_archive(archive, before)
    _check_cancelled(cancel_check)
    content: dict[str, bytes] = {}
    for entry in inventory.selected_sources:
        _check_cancelled(cancel_check)
        content[entry.path] = b"".join(archive.iter_entry_bytes(entry))
    if not content:
        raise StoryMapperError(
            "archive contains no .rpy source; this analyzer does not decompile .rpyc"
        )
    after = fingerprint_file(archive_path)
    if before != after:
        raise StoryMapperError("archive hash, size, or modification time changed during analysis")
    manifest = dict(inventory.manifest)
    manifest["archive_integrity"] = {
        "verified_unchanged": True,
        "before": before.to_dict(),
        "after": after.to_dict(),
    }
    return content, manifest


def _content_matches(project: Project, content_by_path: Mapping[str, bytes]) -> bool:
    existing = {source.path: source.content_hash for source in project.sources()}
    incoming = {
        path: hashlib.sha256(content).hexdigest() for path, content in content_by_path.items()
    }
    return existing == incoming


def _source_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"source root is not a directory: {root}")
    return root


def _parse_source(path: str, content: bytes) -> ScriptModule:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ScriptParseError(f"{path}: source is not valid UTF-8") from exc
    return parse_script(path, text.splitlines(keepends=True))


def _stored_dependencies(project: Project) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for path in project.payload_keys("source_dependencies"):
        value = project.payload("source_dependencies", path)
        result[path] = {
            _required_string(item, "stored dependency")
            for item in _required_list(value, "stored dependencies")
        }
    return result


def _merge_dependencies(
    left: Mapping[str, set[str]], right: Mapping[str, set[str]]
) -> dict[str, set[str]]:
    result = {key: set(value) for key, value in left.items()}
    for key, value in right.items():
        result.setdefault(key, set()).update(value)
    return result


def _dependent_closure(dependencies: Mapping[str, set[str]], affected: set[str]) -> set[str]:
    reverse: dict[str, set[str]] = {}
    for source, targets in dependencies.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    result = set(affected)
    pending = list(sorted(affected))
    while pending:
        current = pending.pop()
        for dependent in sorted(reverse.get(current, set())):
            if dependent not in result:
                result.add(dependent)
                pending.append(dependent)
    return result


def _source_dependencies(modules: Sequence[ScriptModule]) -> dict[str, set[str]]:
    label_paths = {label.name: label.span.path for module in modules for label in module.labels}
    result: dict[str, set[str]] = {module.path: set() for module in modules}
    for module in modules:
        for statement in _walk_statements(module.top_level):
            if isinstance(statement, (Call, Jump)) and statement.target in label_paths:
                target_path = label_paths[statement.target]
                if target_path != module.path:
                    result[module.path].add(target_path)
    return result


def _walk_statements(statements: Iterable[Statement]) -> Iterable[Statement]:
    for statement in statements:
        yield statement
        if isinstance(statement, LabelAnchor | Opaque):
            yield from _walk_statements(statement.body)
        elif isinstance(statement, If):
            for branch in statement.branches:
                yield from _walk_statements(branch.body)
        elif isinstance(statement, Menu):
            for choice in statement.choices:
                yield from _walk_statements(choice.body)


def _module_to_value(module: ScriptModule) -> dict[str, object]:
    return {
        "schema_version": 1,
        "path": module.path,
        "top_level": [_statement_to_value(item) for item in module.top_level],
        "diagnostics": module.diagnostics,
    }


def _module_from_value(raw: object) -> ScriptModule:
    value = _required_mapping(raw, "parsed source")
    if value.get("schema_version") != 1:
        raise ValueError("parsed source schema_version must be exactly 1")
    path = _required_string(value.get("path"), "parsed source path")
    top_level = [
        _statement_from_value(item)
        for item in _required_list(value.get("top_level"), "parsed source statements")
    ]
    diagnostics = [
        dict(_required_mapping(item, "parsed source diagnostic"))
        for item in _required_list(value.get("diagnostics"), "parsed source diagnostics")
    ]
    labels: list[Label] = []
    for statement in _walk_statements(top_level):
        if isinstance(statement, LabelAnchor):
            labels.append(Label(statement.name, statement.span, statement.text, statement.body))
    return ScriptModule(path, labels, top_level, diagnostics)


def _statement_to_value(statement: Statement) -> dict[str, object]:
    value: dict[str, object] = {
        "source": _span_to_value(statement.span),
        "text": statement.text,
    }
    if isinstance(statement, Simple):
        value.update({"type": "simple", "kind": statement.kind})
    elif isinstance(statement, Jump):
        value.update(
            {"type": "jump", "target": statement.target, "expression": statement.expression}
        )
    elif isinstance(statement, Call):
        value.update(
            {"type": "call", "target": statement.target, "expression": statement.expression}
        )
    elif isinstance(statement, Return):
        value.update({"type": "return", "expression": statement.expression})
    elif isinstance(statement, Opaque):
        value.update(
            {
                "type": "opaque",
                "reason": statement.reason,
                "body": [_statement_to_value(item) for item in statement.body],
            }
        )
    elif isinstance(statement, LabelAnchor):
        value.update(
            {
                "type": "label",
                "name": statement.name,
                "body": [_statement_to_value(item) for item in statement.body],
            }
        )
    elif isinstance(statement, If):
        value.update(
            {
                "type": "if",
                "branches": [
                    {
                        "condition": branch.condition,
                        "source": _span_to_value(branch.span),
                        "text": branch.text,
                        "body": [_statement_to_value(item) for item in branch.body],
                    }
                    for branch in statement.branches
                ],
            }
        )
    elif isinstance(statement, Menu):
        value.update(
            {
                "type": "menu",
                "choices": [
                    {
                        "caption": choice.caption,
                        "condition": choice.condition,
                        "source": _span_to_value(choice.span),
                        "text": choice.text,
                        "body": [_statement_to_value(item) for item in choice.body],
                    }
                    for choice in statement.choices
                ],
                "captions": [
                    {
                        "caption": caption.caption,
                        "source": _span_to_value(caption.span),
                        "text": caption.text,
                    }
                    for caption in statement.captions
                ],
            }
        )
    else:
        raise TypeError(f"unsupported parsed statement type: {type(statement).__name__}")
    return value


def _statement_from_value(raw: object) -> Statement:
    value = _required_mapping(raw, "parsed statement")
    kind = _required_string(value.get("type"), "parsed statement type")
    span = _span_from_value(value.get("source"))
    text = _required_string(value.get("text"), "parsed statement text")
    if kind == "simple":
        return Simple(span, text, _required_string(value.get("kind"), "simple kind"))
    if kind == "jump":
        return Jump(
            span,
            text,
            _optional_string(value.get("target")),
            _optional_string(value.get("expression")),
        )
    if kind == "call":
        return Call(
            span,
            text,
            _optional_string(value.get("target")),
            _optional_string(value.get("expression")),
        )
    if kind == "return":
        return Return(span, text, _optional_string(value.get("expression")))
    if kind == "opaque":
        return Opaque(
            span,
            text,
            _required_string(value.get("reason"), "opaque reason"),
            _statement_list(value.get("body")),
        )
    if kind == "label":
        return LabelAnchor(
            span,
            text,
            _required_string(value.get("name"), "label name"),
            _statement_list(value.get("body")),
        )
    if kind == "if":
        branches = []
        for raw_branch in _required_list(value.get("branches"), "if branches"):
            branch = _required_mapping(raw_branch, "if branch")
            branches.append(
                IfBranch(
                    _optional_string(branch.get("condition")),
                    _span_from_value(branch.get("source")),
                    _required_string(branch.get("text"), "if branch text"),
                    _statement_list(branch.get("body")),
                )
            )
        return If(span, text, branches)
    if kind == "menu":
        choices = []
        for raw_choice in _required_list(value.get("choices"), "menu choices"):
            choice = _required_mapping(raw_choice, "menu choice")
            choices.append(
                MenuChoice(
                    _required_string(choice.get("caption"), "choice caption"),
                    _optional_string(choice.get("condition")),
                    _span_from_value(choice.get("source")),
                    _required_string(choice.get("text"), "choice text"),
                    _statement_list(choice.get("body")),
                )
            )
        captions = []
        for raw_caption in _required_list(value.get("captions"), "menu captions"):
            caption = _required_mapping(raw_caption, "menu caption")
            captions.append(
                MenuCaption(
                    _required_string(caption.get("caption"), "menu caption text"),
                    _span_from_value(caption.get("source")),
                    _required_string(caption.get("text"), "menu caption source text"),
                )
            )
        return Menu(span, text, choices, captions)
    raise ValueError(f"unknown parsed statement type {kind!r}")


def _statement_list(raw: object) -> list[Statement]:
    return [_statement_from_value(item) for item in _required_list(raw, "statement body")]


def _span_to_value(span: SourceSpan) -> dict[str, object]:
    return {
        "path": span.path,
        "start_line": span.start_line,
        "start_column": span.start_column,
        "end_line": span.end_line,
        "end_column": span.end_column,
    }


def _span_from_value(raw: object) -> SourceSpan:
    value = _required_mapping(raw, "source span")
    return SourceSpan(
        _required_string(value.get("path"), "source span path"),
        _required_int(value.get("start_line"), "source span start_line"),
        _required_int(value.get("start_column"), "source span start_column"),
        _required_int(value.get("end_line"), "source span end_line"),
        _required_int(value.get("end_column"), "source span end_column"),
    )


def _check_cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        raise ProjectOperationCancelled("project operation was cancelled")


def _required_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return cast(dict[str, object], value)


def _required_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError("optional string value must be a string or null")


def _required_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value

"""Exact current M10/M11/M12 authority selection for the optional M13 layer."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CANONICAL_GRAPH_SCHEMA_VERSION,
)
from renpy_story_mapper.m11_persistence import M11Availability
from renpy_story_mapper.m11_scene_model import (
    M11_SCENE_MODEL_SCHEMA,
    M11_SCENE_MODEL_SCHEMA_VERSION,
)
from renpy_story_mapper.m11_scene_projection import scene_model_from_stored_results
from renpy_story_mapper.m12_persistence import (
    ROUTE_RESULTS_COLLECTION,
    RouteCacheState,
    route_cache_identity,
)
from renpy_story_mapper.narrative.contracts import AuthorityBinding
from renpy_story_mapper.narrative.projection import bind_authority
from renpy_story_mapper.storage import canonical_json, decode_json

if TYPE_CHECKING:
    from renpy_story_mapper.project import Project

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class M12SelectionCoverage:
    selected: int
    stale: int
    invalid: int

    @property
    def complete(self) -> bool:
        return self.stale == 0 and self.invalid == 0


@dataclass(frozen=True)
class NarrativeAuthority:
    """Validated inert authority payloads and their exact M13 binding."""

    canonical: Mapping[str, object]
    scene_model: Mapping[str, object]
    m12_results: tuple[Mapping[str, object], ...]
    binding: AuthorityBinding
    m11_publication_hash: str
    m12_coverage: M12SelectionCoverage


def load_narrative_authority(
    project: Project,
    *,
    include_m12: bool,
) -> NarrativeAuthority:
    """Select exact current authority without executing or changing source-derived layers."""

    state = project.payload("m10_analysis_state", "authoritative")
    canonical = project.payload("m10_canonical_graph", "authoritative")
    if not isinstance(state, Mapping) or not isinstance(canonical, Mapping):
        raise ValueError("M13 requires current complete M10 authority")
    canonical_value = _detached(canonical, "M10 canonical graph")
    canonical_hash = hashlib.sha256(canonical_json(canonical_value)).hexdigest()
    source_generation = canonical_value.get("source_generation")
    if (
        state.get("canonical_availability") != "current_complete"
        or canonical_value.get("schema") != CANONICAL_GRAPH_SCHEMA
        or state.get("source_generation") != source_generation
        or state.get("canonical_generation") != source_generation
        or state.get("canonical_hash") != canonical_hash
    ):
        raise ValueError("M13 requires a coherent current M10 canonical graph")

    selection = project.m11_persistence().select_current(
        source_generation=_text(source_generation, "M10 source generation"),
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=canonical_hash,
    )
    if (
        selection.availability is not M11Availability.CURRENT_COMPLETE
        or selection.phase_results is None
        or selection.model_hash is None
    ):
        raise ValueError(f"M13 requires current complete M11 authority: {selection.reason}")
    model = scene_model_from_stored_results(selection.phase_results)
    model.validate()
    scene_value = model.normalized_dict()
    if (
        model.binding.source_generation != source_generation
        or model.binding.canonical_schema != CANONICAL_GRAPH_SCHEMA
        or model.binding.canonical_hash != canonical_hash
    ):
        raise ValueError("M13 requires M11 to be exactly bound to current M10")

    m12_results: tuple[Mapping[str, object], ...] = ()
    coverage = M12SelectionCoverage(0, 0, 0)
    if include_m12:
        m12_results, coverage = _select_m12_results(
            project,
            source_generation=_text(source_generation, "M10 source generation"),
            canonical_hash=canonical_hash,
            scene_hash=model.structural_hash,
            publication_hash=selection.model_hash,
        )
    correction_value = (
        {"schema": "m11-correction-overlay-none-v1"}
        if model.correction_overlay is None
        else model.correction_overlay.to_dict()
    )
    binding = bind_authority(
        canonical_value,
        scene_value,
        m12_results,
        source_archive_hash=_source_material_hash(project),
        correction_hash=hashlib.sha256(canonical_json(correction_value)).hexdigest(),
    )
    return NarrativeAuthority(
        canonical=canonical_value,
        scene_model=scene_value,
        m12_results=m12_results,
        binding=binding,
        m11_publication_hash=selection.model_hash,
        m12_coverage=coverage,
    )


def _source_material_hash(project: Project) -> str:
    sources = [
        {
            "path": item.path,
            "content_hash": item.content_hash,
            "size_bytes": item.size_bytes,
            "metadata": dict(item.metadata),
        }
        for item in project.sources()
    ]
    manifest = project.payload("import_manifest", "authoritative")
    archive: dict[str, object] | None = None
    if isinstance(manifest, Mapping):
        raw_archive = manifest.get("archive")
        if isinstance(raw_archive, Mapping):
            sha256 = raw_archive.get("sha256")
            size = raw_archive.get("size")
            if isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256):
                archive = {"sha256": sha256, "size": size}
    material = {
        "schema": "m13-source-material-v1",
        "sources": sources,
        "archive": archive,
    }
    return hashlib.sha256(canonical_json(material)).hexdigest()


def _select_m12_results(
    project: Project,
    *,
    source_generation: str,
    canonical_hash: str,
    scene_hash: str,
    publication_hash: str,
) -> tuple[tuple[Mapping[str, object], ...], M12SelectionCoverage]:
    expected_m10 = {
        "source_generation": source_generation,
        "schema": CANONICAL_GRAPH_SCHEMA,
        "schema_version": CANONICAL_GRAPH_SCHEMA_VERSION,
        "canonical_hash": canonical_hash,
    }
    expected_m11 = {
        "schema": M11_SCENE_MODEL_SCHEMA,
        "schema_version": M11_SCENE_MODEL_SCHEMA_VERSION,
        "model_hash": scene_hash,
        "publication_hash": publication_hash,
    }
    selected: list[Mapping[str, object]] = []
    stale = 0
    invalid = 0
    for key in project.payload_keys(ROUTE_RESULTS_COLLECTION):
        raw = project.payload(ROUTE_RESULTS_COLLECTION, key)
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("M12 route envelope is not an object")
            identity_document = _mapping(raw.get("identity"), "M12 route identity")
            authority = _mapping(identity_document.get("authority"), "M12 route authority")
            m10 = _mapping(authority.get("m10"), "M12 M10 authority")
            m11 = _mapping(authority.get("m11"), "M12 M11 authority")
            if (
                canonical_json(dict(m10)) != canonical_json(expected_m10)
                or canonical_json(dict(m11)) != canonical_json(expected_m11)
            ):
                stale += 1
                continue
            request = _mapping(identity_document.get("request"), "M12 route request")
            limits = _mapping(
                identity_document.get("deterministic_limits"),
                "M12 deterministic limits",
            )
            solver_version = _text(
                identity_document.get("solver_version"),
                "M12 solver version",
            )
            identity = route_cache_identity(
                request,
                limits,
                m10_provenance=m10,
                m11_provenance=m11,
                solver_version=solver_version,
            )
            if identity.cache_key != key:
                raise ValueError("M12 cache key does not match its identity")
            lookup = project.m12_persistence().lookup(identity)
            if lookup.state is not RouteCacheState.HIT or lookup.result is None:
                raise ValueError("M12 route result is not a validated hit")
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        selected.append(lookup.result)
    selected.sort(key=lambda item: str(item.get("request_identity", "")))
    return tuple(selected), M12SelectionCoverage(len(selected), stale, invalid)


def _detached(value: Mapping[str, object], label: str) -> dict[str, object]:
    decoded = decode_json(canonical_json(dict(value)))
    if not isinstance(decoded, dict):
        raise TypeError(f"{label} must be an object")
    return decoded


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value

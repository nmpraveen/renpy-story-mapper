"""Narrow, read-only adapters from exact M10/M11 authority into M15 records."""

from __future__ import annotations

from collections.abc import Iterable

from renpy_story_mapper.canonical_graph_contract import CanonicalGraph, SourceEvidence
from renpy_story_mapper.m11_scene_model import M11_SCENE_MODEL_SCHEMA, SceneModel, StoryAtom
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    SourceLocator,
)


def bind_m15_authority(canonical: CanonicalGraph, scene_model: SceneModel) -> AuthorityBinding:
    """Validate and bind one exact current M10/M11 pair without changing either layer."""

    canonical.validate()
    scene_model.validate()
    if scene_model.binding.source_generation != canonical.source_generation:
        raise ValueError("M11 source generation does not match M10 authority")
    if scene_model.binding.canonical_schema != canonical.to_dict()["schema"]:
        raise ValueError("M11 canonical schema does not match M10 authority")
    if scene_model.binding.canonical_hash != canonical.authority_hash:
        raise ValueError("M11 canonical hash does not match M10 authority")
    return AuthorityBinding(
        source_generation=canonical.source_generation,
        canonical_schema=scene_model.binding.canonical_schema,
        canonical_hash=canonical.authority_hash,
        atom_schema=M11_SCENE_MODEL_SCHEMA,
        atom_hash=scene_model.structural_hash,
    )


def atom_locators(
    atom: StoryAtom,
    evidence_by_id: dict[str, SourceEvidence],
) -> tuple[SourceLocator, ...]:
    """Return exact, de-duplicated source locators for one M11 atom."""

    result: list[SourceLocator] = []
    for evidence_id in atom.provenance.evidence_ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        locator = _locator_from_evidence(evidence)
        if locator is not None and locator not in result:
            result.append(locator)
    if not result:
        path, line, _column, _node_id = atom.source_order
        if path and line > 0:
            result.append(SourceLocator(path, line, line, "source"))
    return tuple(result)


def ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    """Preserve authoritative encounter order while removing repeated references."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _locator_from_evidence(evidence: SourceEvidence) -> SourceLocator | None:
    source = evidence.source
    path = source.get("path")
    start = source.get("start")
    end = source.get("end")
    if not isinstance(path, str) or not isinstance(start, dict) or not isinstance(end, dict):
        return None
    start_line = start.get("line")
    end_line = end.get("line")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return None
    return SourceLocator(
        relative_path=path,
        start_line=start_line,
        end_line=end_line,
        line_basis=evidence.line_basis or "source",
    )

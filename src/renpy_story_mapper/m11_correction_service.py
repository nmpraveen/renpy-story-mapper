"""Minimal split/merge correction workflow over a current M11 publication."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from renpy_story_mapper.m11_persistence import (
    M11Availability,
    M11PreconditionError,
    Publication,
    phase_input_hash,
)
from renpy_story_mapper.m11_scene_model import (
    M11_SCENE_MODEL_SCHEMA,
    CorrectionOverlay,
    SceneModel,
)
from renpy_story_mapper.m11_scene_projection import (
    SCENE_PRESENTATION_SCHEMA,
    build_scene_assembly,
    build_scene_presentation,
    scene_model_from_phase_results,
)
from renpy_story_mapper.project import Project
from renpy_story_mapper.storage import canonical_json


def apply_correction_overlay(
    project: Project,
    canonical: Mapping[str, object],
    overlay: CorrectionOverlay,
) -> tuple[Publication, SceneModel]:
    """Rebuild only assembly/presentation and atomically publish an exact-bound overlay."""

    persistence = project.m11_persistence()
    selection = persistence.select(canonical)
    if (
        selection.availability is not M11Availability.CURRENT_COMPLETE
        or selection.phase_results is None
        or selection.model_hash is None
        or selection.canonical is None
    ):
        raise M11PreconditionError("corrections require a current complete M11 publication")
    phases = selection.phase_results
    current_model = scene_model_from_phase_results(
        canonical,
        phases["story_atoms"],
        phases["scene_boundaries"],
        phases["scene_assembly"],
    )
    if overlay.binding != current_model.binding:
        raise M11PreconditionError("correction overlay is bound to another canonical graph")
    overlay_value = overlay.to_dict()
    if (
        phases["scene_assembly"].get("correction_overlay") == overlay_value
        and persistence.corrections(canonical) == overlay_value
    ):
        return (
            Publication(
                selection.canonical,
                selection.model_hash,
                {
                    phase: _content_hash(result)
                    for phase, result in selection.phase_results.items()
                },
                0,
                True,
            ),
            current_model,
        )

    story_atoms_hash = _content_hash(phases["story_atoms"])
    boundaries_hash = _content_hash(phases["scene_boundaries"])
    overlay_hash = _content_hash(overlay_value)
    assembly_input_hash = phase_input_hash(
        {
            "schema": "m11-scene-assembly-input-v1",
            "canonical_hash": current_model.binding.canonical_hash,
            "story_atoms_hash": story_atoms_hash,
            "scene_boundaries_hash": boundaries_hash,
            "scene_model_schema": M11_SCENE_MODEL_SCHEMA,
            "correction_overlay_hash": overlay_hash,
        }
    )
    assembly = build_scene_assembly(
        canonical,
        phases["story_atoms"],
        phases["scene_boundaries"],
        correction_overlay=overlay,
        canonical_binding=current_model.binding,
    )
    assembly_checkpoint = persistence.checkpoint_phase(
        canonical,
        "scene_assembly",
        assembly_input_hash,
        assembly,
        expected_working_hash=selection.model_hash,
    )
    presentation_input_hash = phase_input_hash(
        {
            "schema": "m11-scene-presentation-input-v1",
            "canonical_hash": current_model.binding.canonical_hash,
            "scene_assembly_hash": assembly_checkpoint.result_hash,
            "presentation_schema": SCENE_PRESENTATION_SCHEMA,
        }
    )
    presentation = build_scene_presentation(
        canonical,
        assembly,
        canonical_binding=current_model.binding,
    )
    presentation_checkpoint = persistence.checkpoint_phase(
        canonical,
        "scene_presentation",
        presentation_input_hash,
        presentation,
        expected_working_hash=assembly_checkpoint.working_hash,
    )
    phase_hashes = {
        "story_atoms": story_atoms_hash,
        "scene_boundaries": boundaries_hash,
        "scene_assembly": assembly_checkpoint.result_hash,
        "scene_presentation": presentation_checkpoint.result_hash,
    }
    publication = persistence.publish(
        canonical,
        expected_working_hash=presentation_checkpoint.working_hash,
        expected_phase_hashes=phase_hashes,
    )
    persistence.save_corrections(canonical, overlay_value)
    corrected = scene_model_from_phase_results(
        canonical,
        phases["story_atoms"],
        phases["scene_boundaries"],
        assembly,
        canonical_binding=current_model.binding,
    )
    return publication, corrected


def _content_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(value))).hexdigest()

from __future__ import annotations

from pathlib import Path

from renpy_story_mapper.m11_persistence import M11_PHASES

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "renpy_story_mapper"


def test_m11_consumes_m10_authority_without_importing_control_flow_builders() -> None:
    production = "\n".join(
        (PACKAGE / name).read_text(encoding="utf-8")
        for name in (
            "m11_scene_model.py",
            "m11_scene_projection.py",
            "m11_persistence.py",
            "m11_correction_service.py",
            "web/scene_api.py",
        )
    )
    forbidden = (
        "from renpy_story_mapper.graph import build_graph",
        "from renpy_story_mapper.control_flow import analyze_control_flow",
        "from renpy_story_mapper.route_map import project_route_map",
        "from renpy_story_mapper.canonical_graph import build_canonical_graph",
        "build_semantic_story(",
        "extract_state(",
    )

    assert all(item not in production for item in forbidden)
    assert "M11 consumes only the supported M10 canonical graph" in production


def test_m11_v1_has_exactly_the_approved_four_durable_phases() -> None:
    assert M11_PHASES == (
        "story_atoms",
        "scene_boundaries",
        "scene_assembly",
        "scene_presentation",
    )


def test_m11_production_excludes_deferred_narrative_and_runtime_features() -> None:
    projection = (PACKAGE / "m11_scene_projection.py").read_text(encoding="utf-8")
    persistence = (PACKAGE / "m11_persistence.py").read_text(encoding="utf-8")
    deferred_markers = (
        "route_to_target",
        "path_solver",
        "runtime_trace",
        "dynamic_framework_adapter",
        "character_motive",
        "full_plot_summary",
        "global_ai_stitch",
        "source_window_scheduler",
        "dirty_neighbor_propagation",
    )

    assert all(marker not in projection for marker in deferred_markers)
    assert all(marker not in persistence for marker in deferred_markers)

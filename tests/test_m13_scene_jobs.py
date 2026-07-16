from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping

import pytest

from renpy_story_mapper.canonical_graph_contract import CANONICAL_GRAPH_SCHEMA
from renpy_story_mapper.m11_scene_model import M11_SCENE_MODEL_SCHEMA
from renpy_story_mapper.narrative.projection import (
    NarrativeInputMode,
    bind_authority,
    project_scene_inputs,
)
from renpy_story_mapper.storage import canonical_json

_AUTHORITY_KWARGS = {
    "source_archive_hash": "archive-hash",
    "correction_hash": "no-corrections",
}


def _authority() -> tuple[dict[str, object], dict[str, object]]:
    canonical: dict[str, object] = {
        "schema_version": 1,
        "schema": CANONICAL_GRAPH_SCHEMA,
        "source_generation": "generation-1",
        "origin_generations": {"m01_graph": "generation-1"},
        "nodes": [
            {
                "id": "node-1",
                "kind": "script_unit",
                "graph_node_id": "raw-1",
                "label": "Start",
                "reachability": "proven_reachable",
                "evidence_ids": ["evidence-1"],
                "proof_ids": [],
                "origins": [],
                "attributes": {},
            },
            {
                "id": "node-2",
                "kind": "script_unit",
                "graph_node_id": "raw-2",
                "label": "Route",
                "reachability": "conditionally_reachable",
                "evidence_ids": ["evidence-2"],
                "proof_ids": [],
                "origins": [],
                "attributes": {},
            },
        ],
        "edges": [],
        "regions": [],
        "facts": [
            {
                "id": "fact-1",
                "kind": "state_value",
                "status": "known",
                "evidence_ids": ["evidence-1"],
                "origins": [],
                "attributes": {"expression": "trust = 1"},
            }
        ],
        "evidence": [
            {
                "id": "evidence-1",
                "source": {"relative_path": "private/story.rpy", "start_line": 4},
                "source_text": "Alice arrives.",
                "origins": [],
            },
            {
                "id": "evidence-2",
                "source": {"relative_path": "private/story.rpy", "start_line": 9},
                "source_text": "Bob chooses the north road.",
                "origins": [],
            },
        ],
        "proofs": [],
    }
    canonical_hash = hashlib.sha256(canonical_json(canonical)).hexdigest()
    empty_provenance = {
        "node_ids": [],
        "edge_ids": [],
        "region_ids": [],
        "fact_ids": [],
        "evidence_ids": [],
        "proof_ids": [],
    }
    scene_model: dict[str, object] = {
        "schema_version": 1,
        "schema": M11_SCENE_MODEL_SCHEMA,
        "binding": {
            "source_generation": "generation-1",
            "canonical_schema": CANONICAL_GRAPH_SCHEMA,
            "canonical_hash": canonical_hash,
        },
        "atom_rule_version": "m11-atom-rules-v2",
        "boundary_rule_version": "m11-boundary-rules-v2",
        "atoms": [
            {
                "id": "atom-1",
                "kind": "narration",
                "primary_node_id": "node-1",
                "label": "Alice arrives",
                "story_facing": True,
                "rule_id": "narration",
                "source_kind": "narration",
                "speaker": None,
                "source_order": ["story.rpy", 4, 4, "atom-1"],
                "provenance": {
                    **empty_provenance,
                    "node_ids": ["node-1"],
                    "fact_ids": ["fact-1"],
                    "evidence_ids": ["evidence-1"],
                },
            },
            {
                "id": "atom-2",
                "kind": "dialogue",
                "primary_node_id": "node-2",
                "label": "North road",
                "story_facing": True,
                "rule_id": "dialogue",
                "source_kind": "dialogue",
                "speaker": "Bob",
                "source_order": ["story.rpy", 9, 9, "atom-2"],
                "provenance": {
                    **empty_provenance,
                    "node_ids": ["node-2"],
                    "evidence_ids": ["evidence-2"],
                },
            },
        ],
        "boundaries": [],
        "scenes": [
            {
                "id": "scene-1",
                "chapter_id": "chapter-1",
                "lane_id": "lane-spine",
                "title": "Scene 1",
                "ordinal": 0,
                "atom_ids": ["atom-1"],
                "temporary_branch_ids": ["branch-1"],
                "occurrence_ids": [],
                "repeatability": "once",
                "loop_hub_id": None,
                "boundary_id": "boundary-1",
                "definition_only": False,
                "provenance": {
                    **empty_provenance,
                    "node_ids": ["node-1"],
                    "fact_ids": ["fact-1"],
                    "evidence_ids": ["evidence-1"],
                },
            },
            {
                "id": "scene-2",
                "chapter_id": "chapter-1",
                "lane_id": "lane-route",
                "title": "Scene 2",
                "ordinal": 1,
                "atom_ids": ["atom-2"],
                "temporary_branch_ids": [],
                "occurrence_ids": [],
                "repeatability": "once",
                "loop_hub_id": None,
                "boundary_id": "boundary-2",
                "definition_only": False,
                "provenance": {
                    **empty_provenance,
                    "node_ids": ["node-2"],
                    "evidence_ids": ["evidence-2"],
                },
            },
        ],
        "temporary_branches": [
            {
                "id": "branch-1",
                "canonical_region_id": "region-1",
                "split_atom_id": "atom-1",
                "arms": [
                    {
                        "id": "arm-0",
                        "ordinal": 0,
                        "atom_ids": ["atom-2"],
                        "scene_ids": ["scene-2"],
                        "nested_branch_ids": [],
                        "occurrence_ids": [],
                    }
                ],
                "merge_node_id": "node-2",
                "continuation_atom_id": None,
                "parent_scene_id": "scene-1",
                "parent_branch_id": None,
                "provenance": empty_provenance,
            }
        ],
        "occurrences": [],
        "lanes": [
            {
                "id": "lane-spine",
                "kind": "spine",
                "parent_lane_id": None,
                "canonical_region_id": None,
                "arm_ordinal": None,
                "scene_ids": ["scene-1"],
                "split_atom_id": None,
                "merge_node_id": None,
                "provenance": empty_provenance,
            },
            {
                "id": "lane-route",
                "kind": "persistent_route",
                "parent_lane_id": "lane-spine",
                "canonical_region_id": "route-region",
                "arm_ordinal": 0,
                "scene_ids": ["scene-2"],
                "split_atom_id": "atom-1",
                "merge_node_id": None,
                "provenance": empty_provenance,
            },
        ],
        "chapters": [
            {
                "id": "chapter-1",
                "label": "Chapter 1",
                "ordinal": 0,
                "lane_ids": ["lane-spine", "lane-route"],
                "scene_ids": ["scene-1", "scene-2"],
                "boundary_id": None,
                "provenance": empty_provenance,
            }
        ],
        "loop_hubs": [],
        "coverage": {
            "node_ids": ["node-1", "node-2"],
            "edge_ids": [],
            "region_ids": [],
            "fact_ids": ["fact-1"],
            "entries": [],
        },
        "correction_overlay": None,
    }
    return canonical, scene_model


def _route() -> dict[str, object]:
    prerequisite = "Requires trust = 1 before entering this route."
    return {
        "schema": "m12-route-result-v1",
        "request_identity": "r" * 64,
        "status": "route_with_prerequisites",
        "badge": "Route with prerequisites",
        "recommended": {
            "scene_ids": ["scene-2"],
            "requirements": [{"expression": prerequisite}],
            "persistent_lane_ids": ["lane-route"],
        },
        "alternatives": [],
        "complete": True,
        "termination_reason": "best_route_proven",
        "exhaustive": False,
        "closed_world": False,
        "negative_provenance": None,
    }


def test_scene_packets_are_independent_stable_and_provider_free() -> None:
    canonical, scene_model = _authority()
    before = copy.deepcopy((canonical, scene_model))

    first = project_scene_inputs(canonical, scene_model, **_AUTHORITY_KWARGS)
    second = project_scene_inputs(canonical, scene_model, **_AUTHORITY_KWARGS)

    assert [item.scene_id for item in first] == ["scene-1", "scene-2"]
    assert [item.input_hash for item in first] == [item.input_hash for item in second]
    assert first[0].input_hash != first[1].input_hash
    assert all("provider" not in item.to_dict() for item in first)
    assert all("batch" not in item.to_dict() for item in first)
    assert all(entry.source_text is None for item in first for entry in item.evidence)
    assert (canonical, scene_model) == before


def test_story_text_is_consent_mode_bounded_without_paths() -> None:
    canonical, scene_model = _authority()

    packets = project_scene_inputs(
        canonical,
        scene_model,
        mode=NarrativeInputMode.STORY_TEXT,
        max_story_text_chars=len("Alice arrives."),
        **_AUTHORITY_KWARGS,
    )

    assert packets[0].evidence[0].source_text == "Alice arrives."
    assert packets[1].evidence == ()
    assert packets[1].omitted_evidence_ids == ("evidence-2",)
    serialized = canonical_json([item.to_dict() for item in packets])
    assert b"private/story.rpy" not in serialized


def test_structural_context_preserves_lane_and_temporary_arm_ownership() -> None:
    canonical, scene_model = _authority()

    scene_2 = project_scene_inputs(canonical, scene_model, **_AUTHORITY_KWARGS)[1]

    assert scene_2.structural_context["lane_ancestry"] == ["lane-spine", "lane-route"]
    assert scene_2.structural_context["temporary_contexts"] == [
        {"container_id": "branch-1", "arm_id": "arm-0", "arm_ordinal": 0}
    ]


def test_relevant_m12_status_and_prerequisite_are_preserved_exactly() -> None:
    canonical, scene_model = _authority()
    route = _route()

    scene_1, scene_2 = project_scene_inputs(
        canonical,
        scene_model,
        m12_results=(route,),
        **_AUTHORITY_KWARGS,
    )

    assert scene_1.m12_records == ()
    assert scene_2.m12_records[0]["status"] == route["status"]
    assert scene_2.m12_records[0]["badge"] == route["badge"]
    routes = scene_2.m12_records[0]["routes"]
    assert isinstance(routes, list)
    recommended = routes[0]
    assert isinstance(recommended, Mapping)
    assert recommended["requirements"] == _route()["recommended"]["requirements"]  # type: ignore[index]


def test_binding_rejects_stale_m11_without_mutating_authority() -> None:
    canonical, scene_model = _authority()
    stale = copy.deepcopy(scene_model)
    binding = stale["binding"]
    assert isinstance(binding, dict)
    binding["canonical_hash"] = "0" * 64

    with pytest.raises(ValueError, match="exactly bound"):
        bind_authority(canonical, stale, **_AUTHORITY_KWARGS)


def test_authority_identity_is_insensitive_to_selected_m12_order() -> None:
    canonical, scene_model = _authority()
    first = _route()
    second = {**_route(), "request_identity": "s" * 64}

    left = bind_authority(canonical, scene_model, (first, second), **_AUTHORITY_KWARGS)
    right = bind_authority(canonical, scene_model, (second, first), **_AUTHORITY_KWARGS)

    assert left == right

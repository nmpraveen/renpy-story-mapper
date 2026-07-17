from __future__ import annotations

import hashlib
from collections.abc import Mapping

import pytest

from renpy_story_mapper.storage import canonical_json
from renpy_story_mapper.web.scene_api import scene_detail, scene_page


def _hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(value))).hexdigest()


def _fixture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    canonical: dict[str, object] = {
        "schema": "canonical-graph-v1",
        "schema_version": 1,
        "source_generation": "generation-1",
        "nodes": [
            {
                "id": "node-split",
                "evidence_ids": ["evidence-1"],
                "attributes": {
                    "guard_alternatives": [
                        [
                            {
                                "conditions": [
                                    {"requirement_fact_ids": ["fact-nested"]}
                                ]
                            }
                        ]
                    ]
                },
            }
        ],
        "edges": [],
        "regions": [{"id": "region-choice"}, {"id": "region-loop"}],
        "facts": [],
        "evidence": [{"id": "evidence-1", "text": "literal source"}],
        "proofs": [],
    }
    binding = {
        "source_generation": "generation-1",
        "canonical_schema": "canonical-graph-v1",
        "canonical_hash": _hash(canonical),
    }
    provenance = {
        "node_ids": ["node-split"],
        "edge_ids": [],
        "region_ids": ["region-choice"],
        "fact_ids": [],
        "evidence_ids": ["evidence-1"],
        "proof_ids": [],
    }
    atoms = [
        {
            "id": f"atom-{index}",
            "label": f"line {index}",
            "provenance": provenance,
        }
        for index in range(70)
    ]
    scenes = [
        {
            "id": "scene-parent",
            "chapter_id": "chapter-story",
            "lane_id": "lane-spine",
            "title": "Parent scene",
            "ordinal": 0,
            "atom_ids": ["atom-0"],
            "temporary_branch_ids": ["branch-choice"],
            "occurrence_ids": ["occurrence-a", "occurrence-b"],
            "repeatability": "once",
            "loop_hub_id": None,
            "boundary_id": "boundary-parent",
            "definition_only": False,
            "provenance": provenance,
        },
        {
            "id": "scene-arm-a",
            "chapter_id": "chapter-story",
            "lane_id": "lane-spine",
            "title": "Arm location one",
            "ordinal": 1,
            "atom_ids": ["atom-1"],
            "temporary_branch_ids": [],
            "occurrence_ids": [],
            "repeatability": "once",
            "loop_hub_id": None,
            "boundary_id": "boundary-arm",
            "definition_only": False,
            "provenance": provenance,
        },
        {
            "id": "scene-arm-b",
            "chapter_id": "chapter-story",
            "lane_id": "lane-spine",
            "title": "Arm location two",
            "ordinal": 2,
            "atom_ids": ["atom-2"],
            "temporary_branch_ids": [],
            "occurrence_ids": [],
            "repeatability": "once",
            "loop_hub_id": None,
            "boundary_id": "boundary-arm",
            "definition_only": False,
            "provenance": provenance,
        },
        {
            "id": "scene-repeatable",
            "chapter_id": "chapter-story",
            "lane_id": "lane-route",
            "title": "Repeatable event",
            "ordinal": 3,
            "atom_ids": [f"atom-{index}" for index in range(3, 70)],
            "temporary_branch_ids": [],
            "occurrence_ids": [],
            "repeatability": "repeatable",
            "loop_hub_id": "hub-1",
            "boundary_id": "boundary-repeatable",
            "definition_only": False,
            "provenance": provenance,
        },
    ]
    model: dict[str, object] = {
        "schema": "m11-scene-model-v1",
        "schema_version": 1,
        "binding": binding,
        "atom_rule_version": "v1",
        "boundary_rule_version": "v1",
        "atoms": atoms,
        "boundaries": [
            {
                "id": "boundary-parent",
                "strength": "strong",
                "status": "accepted",
                "provenance": provenance,
            },
            {
                "id": "boundary-arm",
                "strength": "hard",
                "status": "accepted",
                "provenance": provenance,
            },
            {
                "id": "boundary-repeatable",
                "strength": "weak",
                "status": "rejected",
                "provenance": provenance,
            },
        ],
        "scenes": scenes,
        "temporary_branches": [
            {
                "id": "branch-choice",
                "canonical_region_id": "region-choice",
                "split_atom_id": "atom-0",
                "arms": [
                    {
                        "id": "arm-0",
                        "ordinal": 0,
                        "atom_ids": ["atom-1", "atom-2"],
                        "scene_ids": ["scene-arm-a", "scene-arm-b"],
                        "nested_branch_ids": ["branch-nested"],
                        "occurrence_ids": ["occurrence-a"],
                    }
                ],
                "merge_node_id": "node-split",
                "continuation_atom_id": "atom-3",
                "parent_scene_id": "scene-parent",
                "parent_branch_id": None,
                "provenance": provenance,
            },
            {
                "id": "branch-nested",
                "canonical_region_id": "region-choice",
                "split_atom_id": "atom-1",
                "arms": [],
                "merge_node_id": "node-split",
                "continuation_atom_id": "atom-2",
                "parent_scene_id": "scene-arm-a",
                "parent_branch_id": "branch-choice",
                "provenance": provenance,
            },
        ],
        "occurrences": [
            {
                "id": occurrence,
                "call_atom_id": "atom-0",
                "callee_entry_node_id": "node-split",
                "kind": "narrative",
                "scene_id": "scene-parent",
                "lane_id": "lane-spine",
                "referenced_atom_ids": ["atom-1", "atom-2"],
                "guard_fact_ids": [],
                "collapsed": False,
                "repeatable": False,
                "provenance": provenance,
            }
            for occurrence in ("occurrence-a", "occurrence-b")
        ],
        "lanes": [
            {
                "id": "lane-spine",
                "kind": "spine",
                "parent_lane_id": None,
                "scene_ids": ["scene-parent", "scene-arm-a", "scene-arm-b"],
                "provenance": provenance,
            },
            {
                "id": "lane-route",
                "kind": "persistent_route",
                "parent_lane_id": "lane-spine",
                "scene_ids": ["scene-repeatable"],
                "provenance": provenance,
            },
        ],
        "chapters": [
            {
                "id": "chapter-story",
                "label": "Story",
                "ordinal": 0,
                "lane_ids": ["lane-spine", "lane-route"],
                "scene_ids": [item["id"] for item in scenes],
                "provenance": provenance,
            }
        ],
        "loop_hubs": [
            {
                "id": "hub-1",
                "canonical_region_id": "region-loop",
                "hub_atom_id": "atom-3",
                "scene_ids": ["scene-repeatable"],
                "occurrence_ids": [],
                "return_relationships": [
                    {"id": "return-1", "scene_id": "scene-repeatable", "hub_atom_id": "atom-3"}
                ],
                "partial_order": [
                    {
                        "id": "partial-1",
                        "before_scene_id": "scene-parent",
                        "after_scene_id": "scene-repeatable",
                    }
                ],
                "provenance": provenance,
            }
        ],
        "coverage": {},
        "correction_overlay": None,
    }
    presentation: dict[str, object] = {
        "schema": "m11-scene-presentation-v1",
        "binding": binding,
        "scene_model_hash": _hash(model),
        "nodes": [
            {
                "id": scene["id"],
                "kind": "scene",
                "scene_id": scene["id"],
                "title": scene["title"],
            }
            for scene in scenes
        ]
        + [
            {
                "id": "branch-choice",
                "kind": "temporary_branch",
                "temporary_branch_id": "branch-choice",
                "title": "Temporary choice",
            },
            {"id": "occurrence-a", "kind": "call_occurrence"},
            {"id": "hub-1", "kind": "loop_hub"},
        ],
        "relationships": [
            {
                "id": f"relationship-{index}",
                "kind": "scene_branch",
                "source_id": "scene-parent",
                "target_id": "branch-choice",
            }
            for index in range(200)
        ],
        "chapter_bands": [
            {
                "id": "chapter-story",
                "label": "Story",
                "ordinal": 0,
                "lane_ids": ["lane-spine", "lane-route"],
                "scene_ids": [item["id"] for item in scenes],
            }
        ],
        "lanes": model["lanes"],
        "page_order": [item["id"] for item in scenes] + ["branch-choice"],
        "layout_columns": [
            {"lane_id": "lane-spine", "column": 0},
            {"lane_id": "lane-route", "column": 2},
        ],
    }
    return model, presentation, canonical


def _kwargs(model: Mapping[str, object]) -> dict[str, str]:
    binding = model["binding"]
    assert isinstance(binding, Mapping)
    return {
        "current_source_generation": str(binding["source_generation"]),
        "current_canonical_hash": str(binding["canonical_hash"]),
    }


def _membership_reference_count(value: object) -> int:
    if isinstance(value, Mapping):
        return sum(
            len(item)
            if key.endswith("_ids")
            and isinstance(item, list)
            and all(isinstance(reference, str) for reference in item)
            else _membership_reference_count(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return sum(_membership_reference_count(item) for item in value)
    return 0


def test_scene_map_is_strictly_bounded_reference_only_and_generation_gated() -> None:
    model, presentation, _ = _fixture()
    page = scene_page(model, presentation, relationship_limit=180, **_kwargs(model))
    assert len(page["nodes"]) == 6
    assert len(page["relationships"]) == 180
    assert page["relationship_next_offset"] == 180
    assert {item["kind"] for item in page["nodes"]} == {
        "scene_occurrence",
        "temporary_branch",
    }
    repeatable = next(item for item in page["nodes"] if item["id"] == "scene-repeatable")
    assert repeatable["page_order"] == 3
    assert repeatable["layout_column"] == 2
    assert repeatable["lane_ancestry"] == ["lane-spine", "lane-route"]
    assert repeatable["repeatable"] is True
    assert repeatable["boundary_strength"] == "weak"
    assert "literal source" not in str(page)
    membership_roots = [page["nodes"], page["chapter_bands"], page["lanes"]]
    assert _membership_reference_count(membership_roots) == page["membership_reference_count"]
    assert page["membership_reference_count"] <= page["membership_reference_limit"] == 240
    visible_scene_ids = {
        item["scene_id"] for item in page["nodes"] if isinstance(item.get("scene_id"), str)
    }
    assert all(
        set(chapter["scene_ids"]) <= visible_scene_ids for chapter in page["chapter_bands"]
    )
    assert all(set(lane["scene_ids"]) <= visible_scene_ids for lane in page["lanes"])

    unavailable = scene_page(
        model,
        presentation,
        current_source_generation="generation-2",
        current_canonical_hash=_kwargs(model)["current_canonical_hash"],
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["reason"] == "scene_model_canonical_mismatch"
    with pytest.raises(ValueError, match="node limit"):
        scene_page(model, presentation, limit=31, **_kwargs(model))


def test_detail_exposes_multi_scene_arm_shared_occurrences_loop_and_escape() -> None:
    model, presentation, canonical = _fixture()
    branch = scene_detail(
        model,
        presentation,
        canonical,
        element_id="branch-choice",
        **_kwargs(model),
    )
    assert branch["arm_local_scenes"][0]["scene_ids"] == ["scene-arm-a", "scene-arm-b"]
    assert branch["arm_local_scenes"][0]["nested_branch_ids"] == ["branch-nested"]
    assert branch["call_occurrences"][0]["id"] == "occurrence-a"
    assert branch["canonical_escape_ids"] == [
        "evidence-1",
        "node-split",
        "region-choice",
    ]
    assert branch["evidence"][0]["id"] == "evidence-1"

    occurrence = scene_detail(
        model,
        presentation,
        canonical,
        element_id="occurrence-a",
        **_kwargs(model),
    )
    assert occurrence["selected_occurrence_id"] == "occurrence-a"
    assert occurrence["caller_scene"]["id"] == "scene-parent"
    assert [item["id"] for item in occurrence["atoms"]] == ["atom-1", "atom-2"]

    scene = scene_detail(
        model,
        presentation,
        canonical,
        element_id="scene-parent",
        **_kwargs(model),
    )
    assert [item["id"] for item in scene["call_occurrences"]] == [
        "occurrence-a",
        "occurrence-b",
    ]
    assert scene["boundary"]["id"] == "boundary-parent"
    assert scene["boundary"]["provenance"]["node_ids"] == ["node-split"]

    for element_id, field in (
        ("lane-spine", "lane"),
        ("chapter-story", "chapter"),
        ("boundary-parent", "boundary"),
    ):
        hierarchy = scene_detail(
            model,
            presentation,
            canonical,
            element_id=element_id,
            **_kwargs(model),
        )
        assert hierarchy[field]["id"] == element_id
        assert hierarchy["canonical_escape_ids"]
        assert hierarchy["evidence"][0]["id"] == "evidence-1"
    repeatable = scene_detail(
        model,
        presentation,
        canonical,
        element_id="scene-repeatable",
        **_kwargs(model),
    )
    assert repeatable["loop_hubs"][0]["id"] == "hub-1"
    assert repeatable["return_relationships"][0]["id"] == "return-1"
    assert repeatable["partial_order"][0]["id"] == "partial-1"
    assert len(repeatable["atoms"]) == 60
    assert len(repeatable["scene"]["atom_ids"]) == 60
    assert repeatable["scene"]["atom_ids_total"] == 67
    detail_roots = [
        repeatable.get("scene"),
        repeatable.get("temporary_branch"),
        repeatable.get("selected_occurrence"),
        repeatable.get("lane"),
        repeatable.get("chapter"),
        repeatable.get("boundary"),
        repeatable["atoms"],
        repeatable["temporary_branches"],
        repeatable["arm_local_scenes"],
        repeatable["call_occurrences"],
        repeatable["loop_hubs"],
        repeatable["related_scenes"],
    ]
    assert _membership_reference_count(detail_roots) == repeatable[
        "membership_reference_count"
    ]
    assert repeatable["membership_reference_count"] <= 60
    assert _membership_reference_count(
        [repeatable["canonical_records"], repeatable["evidence"]]
    ) == repeatable["canonical_record_reference_count"]
    assert repeatable["canonical_record_reference_count"] <= 60
    assert len(canonical_json(repeatable)) < 96_000

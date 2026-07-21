from __future__ import annotations

import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_track_a_fine_units_and_exhaustive_gap_builder_exist() -> None:
    module = importlib.import_module("renpy_story_mapper.narrative_map.corridors")
    assert callable(getattr(module, "build_fine_narrative_units", None))
    assert callable(getattr(module, "build_all_eligible_gap_candidates", None))


def test_track_a_hierarchical_assembler_consumes_four_state_decisions() -> None:
    module = importlib.import_module("renpy_story_mapper.narrative_map.assembly")
    assert callable(getattr(module, "assemble_semantic_outline", None))
    fixture = json.loads((ROOT / "tests/fixtures/m15_1/semantic_outline_v2.json").read_text())
    result = module.assemble_semantic_outline(fixture)
    assert result["ordered_cluster_ids"] == fixture["expected"]["ordered_cluster_ids"]
    assert result["ordered_beat_ids"] == fixture["expected"]["ordered_beat_ids"]
    assert result["post_rejoin_continuation_count"] == 1

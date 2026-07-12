from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from renpy_story_mapper.presentation import (
    PresentationLevel,
    PresentationRequest,
    PresentationService,
)
from renpy_story_mapper.project import create_project

FIXTURE = Path(__file__).parent / "fixtures" / "m05" / "complex_branching"


def _mapping(value: object) -> Mapping[str, Any]:
    assert isinstance(value, Mapping)
    return value


def _sequence(value: object) -> Sequence[Any]:
    assert isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    return value


def test_complex_branching_manifest_matches_deterministic_pipeline(tmp_path: Path) -> None:
    source = FIXTURE / "complex_story.rpy"
    manifest = _mapping(json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8")))
    fixture_contract = _mapping(manifest["fixture"])
    observed = _mapping(manifest["observed_pipeline_counts"])

    # The manifest fingerprints canonical UTF-8/LF content so Git's Windows checkout
    # conversion cannot make the fixture contract machine-dependent.
    source_text = source.read_text(encoding="utf-8")
    assert hashlib.sha256(source_text.encode("utf-8")).hexdigest() == fixture_contract["sha256"]
    assert len(source_text.splitlines()) == fixture_contract[
        "physical_line_count"
    ]

    project_path = tmp_path / "complex-story.rsmproj"
    with create_project(project_path, FIXTURE) as project:
        snapshot = project.snapshot()
        graph = _mapping(snapshot["graph"])
        graph_counts = _mapping(graph["counts"])
        semantic = _mapping(snapshot["semantic"])

        assert graph_counts["nodes"] == observed["graph_nodes"]
        assert graph_counts["edges"] == observed["graph_edges"]
        assert graph_counts["nodes_reachable_from_entry"] == observed["graph_reachable_nodes"]
        assert graph_counts["reachable_labels"] == observed["reachable_labels"]
        assert len(_sequence(semantic["scenes"])) == observed["semantic_scenes"]
        assert len(_sequence(semantic["beats"])) == observed["semantic_beats"]
        assert len(_sequence(semantic["transitions"])) == observed["semantic_transitions"]
        assert len(_sequence(semantic["unresolved"])) == observed["semantic_unresolved"]
        assert len(_sequence(snapshot["requirements"])) == observed["requirements"]
        assert len(_sequence(snapshot["effects"])) == observed["effects"]
        assert len(_sequence(snapshot["state_variables"])) == observed["state_variables"]

        unresolved = _mapping(_sequence(snapshot["unresolved"])[0])
        assert unresolved["kind"] == "dynamic_jump_target"
        assert unresolved["expression"] == "emergency_route"
        evidence = _mapping(unresolved["evidence"])
        assert evidence["start_line"] == 298

    with PresentationService.open(project_path) as service:
        overview = service.view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=1000, edge_limit=1000)
        )
        assert len(overview.nodes) == observed["presentation_level_1_nodes"]

    with sqlite3.connect(project_path) as connection:
        for table, expected_key in (
            ("presentation_nodes", "presentation_nodes"),
            ("presentation_edges", "presentation_edges"),
            ("presentation_evidence", "presentation_evidence"),
            ("presentation_facts", "presentation_facts"),
        ):
            count = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            assert count == observed[expected_key]


def test_complex_branching_manifest_retains_ai_acceptance_features() -> None:
    manifest = _mapping(
        json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))
    )
    labels = _sequence(manifest["labels"])
    choices = _sequence(manifest["choices"])
    gates = _sequence(manifest["gates"])
    effects = _sequence(manifest["effects"])
    endings = _sequence(manifest["endings"])

    assert len(labels) == 11
    assert len(choices) == 27
    assert len(gates) == 26
    assert len(effects) == 88
    assert {_mapping(ending)["type"] for ending in endings} == {
        "good",
        "bad",
        "neutral",
        "secret",
    }
    assert _mapping(manifest["loop"])["back_edge"] == ["market_rounds", "market_rounds"]
    assert len(_sequence(manifest["calls"])) == 2
    assert len(_sequence(manifest["unresolved"])) == 1

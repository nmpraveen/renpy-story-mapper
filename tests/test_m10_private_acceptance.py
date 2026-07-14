from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from renpy_story_mapper.project import PayloadRecord, Project
from renpy_story_mapper.storage import canonical_json


def _harness() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "m10_private_acceptance.py"
    spec = importlib.util.spec_from_file_location("m10_private_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_fingerprints_stream_stored_payload_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness()
    project_path = tmp_path / "private.rsmproj"
    canonical = {"schema_version": 1, "nodes": [{"id": "node-a"}], "edges": []}
    projection = {"schema_version": 1, "nodes": [], "edges": []}
    with Project.create(project_path) as project:
        project.write_payloads(
            (
                PayloadRecord("m10_canonical_graph", "authoritative", canonical),
                PayloadRecord("m10_inspection_projection", "authoritative", projection),
            )
        )

    def fail_payload(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("fingerprinting must not materialize JSON payloads")

    monkeypatch.setattr(Project, "payload", fail_payload)
    result = harness._payload_fingerprints(project_path)

    assert result == {
        "canonical": {
            "sha256": hashlib.sha256(canonical_json(canonical)).hexdigest(),
            "size_bytes": len(canonical_json(canonical)),
        },
        "projection": {
            "sha256": hashlib.sha256(canonical_json(projection)).hexdigest(),
            "size_bytes": len(canonical_json(projection)),
        },
    }


def test_private_boundary_fails_on_provider_construction() -> None:
    harness = _harness()

    with (
        harness._offline_acceptance_boundary() as counts,
        pytest.raises(AssertionError, match="construct an organization provider"),
    ):
        harness.CodexCliProvider()

    assert counts == {"provider_constructions": 1, "remote_requests": 0}


def test_private_boundary_fails_on_network_attempt() -> None:
    harness = _harness()

    with (
        harness._offline_acceptance_boundary() as counts,
        pytest.raises(AssertionError, match="network request"),
    ):
        harness.socket.create_connection(("example.invalid", 443))

    assert counts == {"provider_constructions": 0, "remote_requests": 1}


def test_private_rejoin_proof_follows_only_resolved_merge_successors() -> None:
    harness = _harness()
    evidence = {
        "evidence-rejoin": {
            "id": "evidence-rejoin",
            "source": {
                "path": "game/day1.rpy",
                "start": {"line": 165, "column": 5},
                "end": {"line": 165, "column": 40},
            },
            "source_text": "scene Day1_Rejoin",
        }
    }
    nodes = {
        "merge-inner": {"id": "merge-inner", "kind": "merge", "evidence_ids": []},
        "merge-outer": {"id": "merge-outer", "kind": "merge", "evidence_ids": []},
        "rejoin": {
            "id": "rejoin",
            "kind": "script_unit",
            "evidence_ids": ["evidence-rejoin"],
        },
        "unresolved-decoy": {
            "id": "unresolved-decoy",
            "kind": "script_unit",
            "evidence_ids": ["evidence-rejoin"],
        },
    }

    result = harness._resolve_rejoin_evidence(
        {"projected-merge": {"id": "projected-merge", "canonical_node_ids": ["merge-inner"]}},
        {"merge_node_id": "merge-inner"},
        nodes,
        (
            {
                "id": "edge-inner-outer",
                "source_id": "merge-inner",
                "target_id": "merge-outer",
                "resolved": True,
            },
            {
                "id": "edge-outer-rejoin",
                "source_id": "merge-outer",
                "target_id": "rejoin",
                "resolved": True,
            },
            {
                "id": "edge-unresolved-decoy",
                "source_id": "merge-inner",
                "target_id": "unresolved-decoy",
                "resolved": False,
            },
        ),
        evidence,
        {},
        projected_merge_id="projected-merge",
        expected_path="game/day1.rpy",
        expected_line=165,
        expected_text="scene Day1_Rejoin",
    )

    assert result["kind"] == "resolved_merge_successor"
    assert result["canonical_merge_node_id"] == "merge-inner"
    assert result["canonical_rejoin_node_id"] == "rejoin"
    assert result["canonical_edge_ids"] == ["edge-inner-outer", "edge-outer-rejoin"]


def test_private_compactness_scopes_manifest_bound_and_reports_whole_input() -> None:
    harness = _harness()
    evidence = {
        "target": {
            "source": {"path": "game/day1.rpy", "start": {"line": 1, "column": 1}}
        },
        "other": {
            "source": {"path": "game/day2.rpy", "start": {"line": 1, "column": 1}}
        },
    }
    projected = (
        {"id": "target", "evidence_ids": ["target"], "canonical_node_ids": []},
        {"id": "other-a", "evidence_ids": ["other"], "canonical_node_ids": []},
        {"id": "other-b", "evidence_ids": ["other"], "canonical_node_ids": []},
    )
    canonical = tuple({"id": f"canonical-{index}"} for index in range(10))

    result = harness._projection_compactness(
        projected,
        canonical,
        {},
        evidence,
        expected_source_path="game/day1.rpy",
        maximum_manifest_source_nodes=1,
    )

    assert result == {
        "manifest_source_simplified_nodes": 1,
        "maximum_manifest_source_projection_nodes": 1,
        "whole_input_projection_ratio": 0.3,
        "whole_input_projection_percent": 30.0,
    }
    with pytest.raises(AssertionError, match="manifest-source"):
        harness._projection_compactness(
            projected,
            canonical,
            {},
            evidence,
            expected_source_path="game/day1.rpy",
            maximum_manifest_source_nodes=0,
        )

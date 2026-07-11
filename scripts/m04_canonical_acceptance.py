"""Run bounded M04 acceptance checks against a copied canonical project."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import tracemalloc
from pathlib import Path
from typing import NoReturn

from renpy_story_mapper.presentation import (
    FactRecord,
    PresentationLevel,
    PresentationRequest,
    PresentationService,
    SearchHit,
)
from renpy_story_mapper.project import Project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    project_path = args.project.resolve()
    if not project_path.is_file():
        parser.error(f"project does not exist: {project_path}")

    original_payload = Project.payload

    def reject_payload(_project: Project, _collection: str, _key: str) -> NoReturn:
        raise AssertionError("bounded presentation open/query deserialized a canonical payload")

    Project.payload = reject_payload
    tracemalloc.start()
    started = time.perf_counter()
    try:
        service = PresentationService.open(project_path)
    finally:
        Project.payload = original_payload
    open_seconds = time.perf_counter() - started

    try:
        query_started = time.perf_counter()
        overview = service.view(
            PresentationRequest(
                PresentationLevel.OVERVIEW,
                node_limit=80,
                edge_limit=120,
            )
        )
        overview_seconds = time.perf_counter() - query_started
        assert 0 < len(overview.nodes) <= 80
        assert len(overview.edges) <= 120

        label_hits = tuple(
            item
            for item in service.search("new_prologue", fields=("label",), limit=10).items
            if isinstance(item, SearchHit)
        )
        assert label_hits
        lineage = service.lineage(label_hits[0].node_id)
        assert lineage and lineage[0].name == "new_prologue"
        prologue = lineage[0]
        assert prologue.expandable

        events = service.view(
            PresentationRequest(
                PresentationLevel.EVENT,
                parent_ids=(prologue.id,),
                node_limit=250,
                edge_limit=500,
            )
        )
        assert 1 < len(events.nodes) < 196
        assert not events.node_continuation.has_more
        evidence = service.view(
            PresentationRequest(
                PresentationLevel.EVIDENCE,
                parent_ids=(events.nodes[0].id,),
                node_limit=20,
                edge_limit=40,
                include_technical=True,
            )
        )
        assert 1 <= len(evidence.nodes) <= 4

        expected = (
            ("gate", "ian_wits", "script.rpy", 244),
            ("gate", "ian_charisma", "script.rpy", 246),
            ("effect", "ian_lena_mmf_points", "master_script.rpy", 2256),
            ("effect", "ian_lena_dating", "gallery_scene_setups.rpy", 1103),
            ("effect", "chapter", "master_script.rpy", 1994),
        )
        verified_facts: list[dict[str, object]] = []
        for kind, variable, source_name, line in expected:
            facts = tuple(
                item
                for item in service.facts(kind=kind, variable=variable, limit=100).items
                if isinstance(item, FactRecord)
            )
            fact = next(
                item
                for item in facts
                if Path(item.source_path).name == source_name and item.start_line == line
            )
            verified_facts.append(
                {
                    "kind": fact.kind,
                    "variable": fact.variable,
                    "expression": fact.expression,
                    "status": fact.status,
                    "source_path": fact.source_path,
                    "start_line": fact.start_line,
                }
            )

        deterministic = {
            "overview_node_ids": [node.id for node in overview.nodes],
            "overview_edge_ids": [edge.id for edge in overview.edges],
            "new_prologue_id": prologue.id,
            "event_ids": [node.id for node in events.nodes],
            "evidence_ids": [node.id for node in evidence.nodes],
            "facts": verified_facts,
        }
        deterministic_bytes = json.dumps(
            deterministic, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    finally:
        service.close()

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    second_started = time.perf_counter()
    with PresentationService.open(project_path) as reopened:
        second = reopened.view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=80, edge_limit=120)
        )
        assert [node.id for node in second.nodes] == [node.id for node in overview.nodes]
    second_open_seconds = time.perf_counter() - second_started

    connection = sqlite3.connect(project_path)
    try:
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        table_counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "presentation_nodes",
                "presentation_edges",
                "presentation_evidence",
                "presentation_facts",
                "presentation_search",
            )
        }
    finally:
        connection.close()

    result = {
        "project_path": str(project_path),
        "project_size_bytes": project_path.stat().st_size,
        "schema_version": schema_version,
        "first_open_and_index_seconds": round(open_seconds, 3),
        "overview_query_seconds": round(overview_seconds, 3),
        "second_open_and_overview_seconds": round(second_open_seconds, 3),
        "python_tracemalloc_peak_bytes": peak_bytes,
        "overview_nodes_returned": len(overview.nodes),
        "overview_edges_returned": len(overview.edges),
        "overview_has_more": overview.node_continuation.has_more,
        "new_prologue_child_count": prologue.child_count,
        "new_prologue_event_nodes": len(events.nodes),
        "first_event_evidence_nodes": len(evidence.nodes),
        "table_counts": table_counts,
        "verified_facts": verified_facts,
        "deterministic_output_sha256": hashlib.sha256(deterministic_bytes).hexdigest(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

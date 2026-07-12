from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.presentation import (
    PresentationLevel,
    PresentationRequest,
    PresentationService,
)
from renpy_story_mapper.project import PayloadRecord, Project, create_project, refresh_project

FIXTURE = Path(__file__).parent / "fixtures" / "m04" / "presentation"


def _create(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "game"
    shutil.copytree(FIXTURE, source)
    project_path = tmp_path / "story.rsmproj"
    create_project(project_path, source).close()
    return project_path, source


def test_overview_is_bounded_and_does_not_load_authoritative_payload(
    tmp_path: Path, monkeypatch: object
) -> None:
    project_path, _ = _create(tmp_path)
    with PresentationService.open(project_path) as service:
        monkeypatch.setattr(service._project, "payload", lambda *_args: (_ for _ in ()).throw(
            AssertionError("bounded query loaded an authoritative payload")
        ))
        page = service.view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=2, edge_limit=1)
        )
        assert len(page.nodes) == 2
        assert page.node_continuation.has_more
        assert len(page.edges) <= 1
        assert {edge.source_id for edge in page.edges} <= {node.id for node in page.nodes}


def test_deterministic_expandable_three_level_projection(tmp_path: Path) -> None:
    first_path, _ = _create(tmp_path / "first")
    second_path, _ = _create(tmp_path / "second")
    with (
        PresentationService.open(first_path) as first,
        PresentationService.open(second_path) as second,
    ):
        left = first.view(PresentationRequest(PresentationLevel.OVERVIEW))
        right = second.view(PresentationRequest(PresentationLevel.OVERVIEW))
        assert asdict(left) == asdict(right)
        prologue = next(node for node in left.nodes if node.name == "new_prologue")
        assert prologue.expandable and prologue.child_count > 1
        events = first.view(
            PresentationRequest(PresentationLevel.EVENT, expanded_ids=(prologue.id,), node_limit=2)
        )
        assert events.nodes
        assert all(node.parent_id == prologue.id for node in events.nodes)
        assert all(node.level is PresentationLevel.EVENT for node in events.nodes)
        beats = first.view(
            PresentationRequest(
                PresentationLevel.EVIDENCE, expanded_ids=(events.nodes[0].id,), node_limit=3
            )
        )
        assert beats.nodes
        assert all(node.level is PresentationLevel.EVIDENCE for node in beats.nodes)


def test_search_facts_exact_evidence_and_overrides_survive_refresh(tmp_path: Path) -> None:
    project_path, source = _create(tmp_path)
    with PresentationService.open(project_path) as service:
        for query, field in (
            ("new_prologue", "label"),
            ("I can help", "dialogue"),
            ("Rain covered", "narration"),
            ("Offer help", "choice"),
            ("ian_charisma", "condition"),
            ("ian_wits", "variable"),
        ):
            assert service.search(query, fields=(field,)).items
        gate = service.facts(kind="gate", variable="ian_wits").items[0]
        assert gate.source_path == "story.rpy" and gate.start_line == 8
        effect = service.facts(kind="effect", variable="love").items[0]
        assert effect.expression == "love += 1" and effect.start_line == 12
        assert effect.node_id is not None
        evidence = service.evidence(effect.node_id).items
        assert evidence and evidence[0].source_path == "story.rpy"
        prologue = next(
            node
            for node in service.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
            if node.name == "new_prologue"
        )
        service.rename_node(prologue.id, "Custom Prologue")
        service.set_hidden(prologue.id, True)

    refresh_project(project_path, source)
    with PresentationService.open(project_path) as reopened:
        visible = reopened.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
        assert all(node.id != prologue.id for node in visible)
        reopened.set_hidden(prologue.id, False)
        renamed = reopened.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
        assert next(node for node in renamed if node.id == prologue.id).name == "Custom Prologue"


def test_generation_mismatch_rebuilds_stale_facts_and_search(tmp_path: Path) -> None:
    project_path, _ = _create(tmp_path)
    with Project.open(project_path) as project:
        connection = project._require_open()
        stale_generation = str(
            connection.execute("SELECT generation FROM presentation_index_state").fetchone()[0]
        )
        raw = project.payload("effects", "story.rpy")
        assert isinstance(raw, list)
        changed = [
            *raw,
            {
                "id": "effect_injected_generation_test",
                "original_expression": "fresh_generation_flag = True",
                "operation": "assignment",
                "variable": "fresh_generation_flag",
                "value": True,
                "status": "proven",
                "evidence": {
                    "source_path": "story.rpy",
                    "start_line": 12,
                    "end_line": 12,
                },
            },
        ]
        project.write_payloads(
            [PayloadRecord("effects", "story.rpy", changed, ("story.rpy",))]
        )
        assert (
            str(connection.execute("SELECT generation FROM presentation_index_state").fetchone()[0])
            == stale_generation
        )

    with PresentationService.open(project_path) as service:
        facts = service.facts(variable="fresh_generation_flag").items
        assert len(facts) == 1
        assert facts[0].expression == "fresh_generation_flag = True"
        hits = service.search("fresh_generation_flag", fields=("variable",)).items
        assert hits and hits[0].node_id == facts[0].node_id
        current_generation = str(
            service._project._require_open()
            .execute("SELECT generation FROM presentation_index_state")
            .fetchone()[0]
        )
        assert current_generation != stale_generation


def test_event_title_search_rename_reset_and_refresh_persistence(tmp_path: Path) -> None:
    project_path, source = _create(tmp_path)
    with PresentationService.open(project_path) as service:
        prologue = next(
            node
            for node in service.view(PresentationRequest(PresentationLevel.OVERVIEW)).nodes
            if node.name == "new_prologue"
        )
        event = service.view(
            PresentationRequest(PresentationLevel.EVENT, expanded_ids=(prologue.id,))
        ).nodes[0]
        default_title = event.name
        assert any(
            hit.node_id == event.id
            for hit in service.search(default_title, fields=("event_title",)).items
        )

        service.rename_node(event.id, "Opening Decision")
        assert any(
            hit.node_id == event.id
            for hit in service.search("Opening Decision", fields=("event_title",)).items
        )
        assert all(
            hit.node_id != event.id
            for hit in service.search(default_title, fields=("event_title",)).items
        )

        service.rename_node(event.id, None)
        assert any(
            hit.node_id == event.id
            for hit in service.search(default_title, fields=("event_title",)).items
        )
        assert not service.search("Opening Decision", fields=("event_title",)).items
        service.rename_node(event.id, "Persistent Event Name")

    refresh_project(project_path, source)
    with PresentationService.open(project_path) as reopened:
        assert any(
            hit.node_id == event.id
            for hit in reopened.search("Persistent Event Name", fields=("event_title",)).items
        )
        assert all(
            hit.node_id != event.id
            for hit in reopened.search(default_title, fields=("event_title",)).items
        )


def test_real_schema_v2_migration_is_queryable(tmp_path: Path) -> None:
    project_path, _ = _create(tmp_path)
    connection = storage.connect(project_path)
    for table in (
        "presentation_search",
        "presentation_evidence",
        "presentation_facts",
        "presentation_edges",
        "presentation_nodes",
        "presentation_overrides",
        "presentation_index_state",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM schema_migrations WHERE version = 3")
    connection.execute("PRAGMA user_version = 2")
    connection.close()

    with Project.open(project_path) as project:
        assert project.schema_version == storage.SCHEMA_VERSION
        page = project.presentation_service().view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=1)
        )
        assert len(page.nodes) == 1
    assert project_path.with_name(f"{project_path.name}.pre-migrate-v2.bak").is_file()


def test_organization_connectivity_is_unpaged_chunked_and_keeps_cross_scope_edges(
    tmp_path: Path,
) -> None:
    project_path, _ = _create(tmp_path)
    with PresentationService.open(project_path) as service:
        connection = service._project._require_open()
        containers = []
        for scope in range(3):
            containers.extend(
                [
                    (
                        f"synthetic-scope-{scope}", 1, None, f"8{scope:011d}", "label",
                        f"Scope {scope}", "synthetic.rpy", 1, 1200, 0,
                        storage.canonical_json({"synthetic": True}),
                    ),
                    (
                        f"event:synthetic-scope-{scope}:00000000", 2,
                        f"synthetic-scope-{scope}", f"8{scope + 3:011d}", "structural_group",
                        f"Event {scope}", "synthetic.rpy", 1, 1200, 0,
                        storage.canonical_json({"synthetic": True}),
                    ),
                ]
            )
        nodes = [
            (
                f"synthetic-beat-{index:04d}",
                3,
                f"event:synthetic-scope-{index % 3}:00000000",
                f"9{index:011d}",
                "dialogue",
                f"Beat {index}",
                "synthetic.rpy",
                index + 1,
                index + 1,
                0,
                storage.canonical_json({"synthetic": True}),
            )
            for index in range(1200)
        ]
        edges = [
            (
                f"synthetic-edge-{index:04d}",
                3,
                f"synthetic-beat-{index % 1200:04d}",
                f"synthetic-beat-{(index * 17 + 1) % 1200:04d}",
                f"9{index:011d}",
                "flow",
                storage.canonical_json({"synthetic": True}),
            )
            for index in range(1100)
        ]
        edges.append(
            (
                "synthetic-edge-cross-page",
                3,
                "synthetic-beat-0000",
                "synthetic-beat-1199",
                "999999999999",
                "flow",
                storage.canonical_json({"synthetic": True}),
            )
        )
        with storage.transaction(connection):
            connection.executemany(
                "INSERT INTO presentation_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)", containers
            )
            connection.executemany(
                "INSERT INTO presentation_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)", nodes
            )
            connection.executemany("INSERT INTO presentation_edges VALUES (?,?,?,?,?,?,?)", edges)

        selected = tuple(node[0] for node in nodes)
        result = service.organization_connectivity(selected)
        assert result.beat_ids == selected
        assert result.required_beat_ids == selected
        assert len(result.edges) == 1101
        assert any(
            int(edge.source_id.rsplit("-", 1)[1]) % 3
            != int(edge.target_id.rsplit("-", 1)[1]) % 3
            for edge in result.edges
        )
        assert [edge.id for edge in result.edges] == [edge[0] for edge in edges]
        induced = service.edges_for_nodes(PresentationLevel.EVIDENCE, selected)
        assert len(induced) == 1101
        assert induced[-1].id == "synthetic-edge-cross-page"
        assert (
            service.edges_for_nodes(PresentationLevel.EVIDENCE, (*selected, *selected[:5]))
            == induced
        )
        connection.execute(
            "CREATE TEMP TABLE edge_plan_nodes(node_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        connection.executemany(
            "INSERT INTO edge_plan_nodes VALUES (?)", ((value,) for value in selected[:3])
        )
        plan = connection.execute(
            """EXPLAIN QUERY PLAN SELECT edge.* FROM edge_plan_nodes source
               CROSS JOIN presentation_edges edge INDEXED BY presentation_edges_source_idx
               JOIN edge_plan_nodes target ON target.node_id=edge.target_id
               WHERE edge.source_id=source.node_id AND edge.level=3
               ORDER BY edge.sort_key,edge.edge_id"""
        ).fetchall()
        assert any("presentation_edges_source_idx" in str(row[3]) for row in plan)
        connection.execute("DROP TABLE edge_plan_nodes")

        with pytest.raises(ValueError, match="unknown Level-3"):
            service.organization_connectivity((*selected, "unknown-beat"))
        with pytest.raises(ValueError, match="unknown presentation node"):
            service.edges_for_nodes(PresentationLevel.EVIDENCE, (*selected, "unknown-beat"))
        assert connection.execute(
            "SELECT 1 FROM sqlite_temp_schema WHERE name='selected_presentation_nodes'"
        ).fetchone() is None
        with pytest.raises(ValueError, match="non-empty strings"):
            service.edges_for_nodes(
                PresentationLevel.EVIDENCE,
                (selected[0], 7),  # type: ignore[arg-type]
            )
        cancellation_checks = 0

        def cancel_during_decode() -> bool:
            nonlocal cancellation_checks
            cancellation_checks += 1
            return cancellation_checks >= 5

        service._cancelled = cancel_during_decode
        with pytest.raises(storage.ProjectOperationCancelled):
            service.edges_for_nodes(PresentationLevel.EVIDENCE, selected)
        service._cancelled = None
        assert connection.execute(
            "SELECT 1 FROM sqlite_temp_schema WHERE name='selected_presentation_nodes'"
        ).fetchone() is None

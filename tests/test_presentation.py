from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path

from renpy_story_mapper import storage
from renpy_story_mapper.presentation import (
    PresentationLevel,
    PresentationRequest,
    PresentationService,
)
from renpy_story_mapper.project import Project, create_project, refresh_project

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
        assert project.schema_version == 3
        page = project.presentation_service().view(
            PresentationRequest(PresentationLevel.OVERVIEW, node_limit=1)
        )
        assert len(page.nodes) == 1
    assert project_path.with_name(f"{project_path.name}.pre-migrate-v2.bak").is_file()

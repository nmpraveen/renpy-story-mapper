from __future__ import annotations

from pathlib import Path

import pytest

from ingestion_fixtures import make_rpa
from renpy_story_mapper import storage
from renpy_story_mapper.control_flow import analyze_control_flow
from renpy_story_mapper.ingestion import IngestionOptions, inspect_input
from renpy_story_mapper.ingestion.errors import IngestionError
from renpy_story_mapper.ingestion.helper import _audit
from renpy_story_mapper.project import Project
from renpy_story_mapper.ui.organization_workflow import (
    OrganizationOptions,
    OrganizationWorkflow,
)
from renpy_story_mapper.ui.project_controller import validate_create_paths


def test_desktop_project_creation_accepts_direct_compiled_source(tmp_path: Path) -> None:
    compiled = tmp_path / "story.rpyc"
    compiled.write_bytes(b"RENPY RPC2")
    projects = tmp_path / "projects"
    projects.mkdir()

    source, destination = validate_create_paths(compiled, projects / "story.rsmproj")

    assert source == compiled
    assert destination == projects / "story.rsmproj"


def test_incomplete_source_coverage_blocks_provider_construction(tmp_path: Path) -> None:
    project_path = tmp_path / "partial.rsmproj"
    with Project.create(project_path) as project:
        connection = storage.connect(project_path)
        try:
            with storage.transaction(connection):
                connection.execute(
                    """
                    INSERT INTO source_coverage(
                        singleton, complete, partial_allowed, ai_transmission_blocked,
                        acknowledged, warning, updated_utc
                    ) VALUES (1, 0, 1, 1, 0, 'Incomplete recovery.', ?)
                    """,
                    (storage.utc_now(),),
                )
        finally:
            connection.close()

        def provider_must_not_be_constructed(_mode: object) -> object:
            raise AssertionError("provider boundary reached for blocked source coverage")

        workflow = OrganizationWorkflow(project, provider_must_not_be_constructed)  # type: ignore[arg-type]
        with pytest.raises(Exception, match="incomplete source coverage"):
            workflow.organize(
                (),
                OrganizationOptions(),
                progress=lambda _percent, _status: None,
                cancelled=lambda: False,
                confirm_cloud=lambda _run_id: True,
            )


def test_v3_to_v5_migration_rolls_back_as_one_atomic_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_path = tmp_path / "legacy-v3.rsmproj"
    connection = storage.connect(project_path)
    storage.initialize_database(connection, target_version=3)

    def fail_v5(_connection: object) -> None:
        raise RuntimeError("injected v5 migration failure")

    monkeypatch.setattr(storage, "_migrate_to_v5", fail_v5)
    with pytest.raises(RuntimeError, match="injected"):
        storage.initialize_database(connection)

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    connection.close()
    assert version == 3


def test_folder_discovery_rejects_symlinked_archive_escape(tmp_path: Path) -> None:
    game = tmp_path / "release" / "game"
    game.mkdir(parents=True)
    outside = make_rpa(
        tmp_path / "outside.rpa",
        {"game/escaped.rpy": b"label escaped:\n    return\n"},
    )
    linked = game / "linked.rpa"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable on this Windows host: {exc}")

    with pytest.raises(IngestionError, match="escapes selected game folder"):
        inspect_input(game, IngestionOptions(cache_root=tmp_path / "cache"))


def test_recovery_helper_audit_denies_arbitrary_file_write(tmp_path: Path) -> None:
    outside = tmp_path / "outside-game" / "modified.rpy"

    with pytest.raises(PermissionError, match="disabled"):
        _audit("open", (str(outside), "w", 0o666))


@pytest.mark.xfail(
    strict=True,
    reason="persistent split arm discovery retains quadratic whole-graph traversals",
)
def test_persistent_region_analysis_has_bounded_total_arm_membership() -> None:
    split_count = 200
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    for index in range(split_count):
        nodes.extend(
            [
                {
                    "id": f"split-{index}",
                    "kind": "if",
                    "label": "start",
                    "metadata": {"name": "start"} if index == 0 else {},
                },
                {
                    "id": f"terminal-{index}",
                    "kind": "module_end",
                    "label": "start",
                },
            ]
        )
        edges.append(
            {
                "source": f"split-{index}",
                "target": f"terminal-{index}",
                "kind": "condition",
            }
        )
        if index + 1 < split_count:
            edges.append(
                {
                    "source": f"split-{index}",
                    "target": f"split-{index + 1}",
                    "kind": "condition_false",
                }
            )

    analysis = analyze_control_flow(
        {"schema_version": 1, "nodes": nodes, "edges": edges},
        {"schema_version": 1, "transitions": []},
    )
    total_arm_membership = sum(len(arm.node_ids) for arm in analysis.arms)

    assert total_arm_membership <= len(nodes) * 8

from __future__ import annotations

from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.m07_model import (
    AttemptAccounting,
    CheckpointStatus,
    normalized_cache_key,
)
from renpy_story_mapper.project import Project
from renpy_story_mapper.route_map import RouteScope


def _scope(ordinal: int) -> RouteScope:
    digest = f"{ordinal:064x}"
    return RouteScope(
        f"scope_{ordinal}", ordinal, "lane_spine", (f"node_{ordinal}",), (), (), digest
    )


def test_v5_to_v6_migration_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "migration.rsmproj"
    connection = storage.connect(path)
    storage.initialize_database(connection, target_version=5)
    connection.close()

    with Project.open(path) as project:
        assert project.schema_version == 6
        project.m07_model_service().register_scopes((_scope(0),), generation="g1")
    with Project.open(path) as reopened:
        checkpoints = reopened.m07_model_service().checkpoints()
        assert checkpoints[0].status is CheckpointStatus.PENDING


def test_migration_rolls_back_transactionally(tmp_path: Path) -> None:
    path = tmp_path / "rollback.rsmproj"
    connection = storage.connect(path)
    storage.initialize_database(connection, target_version=5)
    connection.execute("CREATE TABLE m07_provider_attempts(wrong TEXT) STRICT")
    with pytest.raises(Exception, match="scope_id"):
        storage.initialize_database(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema")}
    assert "m07_scope_checkpoints" not in tables
    connection.close()


def test_status_accounting_coverage_and_validated_resume(tmp_path: Path) -> None:
    with Project.create(tmp_path / "model.rsmproj") as project:
        service = project.m07_model_service()
        scopes = (_scope(0), _scope(1), _scope(2))
        service.register_scopes(scopes, generation="g1")
        service.transition("scope_0", CheckpointStatus.IN_FLIGHT)
        service.record_attempt(AttemptAccounting("attempt_0", "scope_0", 0, "ok", 1, 100, 20, 50))
        service.transition("scope_0", CheckpointStatus.VALIDATED, result={"title": "A"})
        service.transition("scope_1", CheckpointStatus.CACHED)
        service.transition("scope_1", CheckpointStatus.VALIDATED, result={"title": "B"})
        service.transition("scope_2", CheckpointStatus.CANCELLED)

        coverage = service.coverage()
        assert coverage.validated == 2
        assert coverage.cancelled == 1
        assert coverage.calls == 1
        assert coverage.input_tokens == 100
        assert coverage.output_tokens == 20
        assert coverage.ratio == pytest.approx(2 / 3)

        service.register_scopes(scopes, generation="g2")
        statuses = {item.scope_id: item.status for item in service.checkpoints()}
        assert statuses == {
            "scope_0": CheckpointStatus.VALIDATED,
            "scope_1": CheckpointStatus.VALIDATED,
            "scope_2": CheckpointStatus.PENDING,
        }


def test_completion_order_equivalence_partial_assembly_corrections_and_pins(
    tmp_path: Path,
) -> None:
    hashes: list[str] = []
    payloads: list[object] = []
    for run, completion_order in enumerate(((2, 0, 1), (0, 1, 2))):
        with Project.create(tmp_path / f"order-{run}.rsmproj") as project:
            service = project.m07_model_service()
            service.register_scopes(tuple(_scope(i) for i in range(3)), generation="same")
            for ordinal in completion_order:
                scope_id = f"scope_{ordinal}"
                service.transition(scope_id, CheckpointStatus.IN_FLIGHT)
                service.transition(
                    scope_id,
                    CheckpointStatus.VALIDATED,
                    result={"ordinal": ordinal, "title": chr(65 + ordinal)},
                )
            service.set_override(
                "scope_1", generation="same", correction={"title": "Corrected"}, pinned=True
            )
            assembly = service.assemble(generation="same")
            applied = service.apply(assembly.assembly_id, generation="same")
            hashes.append(applied.payload_hash)
            payloads.append(applied.payload)
    assert hashes[0] == hashes[1]
    assert payloads[0] == payloads[1]

    with Project.create(tmp_path / "partial.rsmproj") as project:
        service = project.m07_model_service()
        service.register_scopes((_scope(0), _scope(1)), generation="partial")
        service.transition("scope_0", CheckpointStatus.IN_FLIGHT)
        service.transition("scope_0", CheckpointStatus.VALIDATED, result={"title": "Ready"})
        partial = service.assemble(generation="partial")
        assert partial.payload["partial"] is True
        assert partial.coverage.validated == 1
        with pytest.raises(ValueError, match="incomplete"):
            service.assemble(generation="partial", allow_partial=False)


def test_invalid_transition_and_attempt_are_rolled_back(tmp_path: Path) -> None:
    with Project.create(tmp_path / "invalid.rsmproj") as project:
        service = project.m07_model_service()
        service.register_scopes((_scope(0),), generation="g")
        with pytest.raises(ValueError, match="invalid checkpoint transition"):
            service.transition("scope_0", CheckpointStatus.VALIDATED, result={"x": 1})
        with pytest.raises(ValueError, match="negative"):
            service.record_attempt(AttemptAccounting("bad", "scope_0", 0, "bad", 1, -1, 0, 0))
        checkpoint = service.checkpoints()[0]
        assert checkpoint.status is CheckpointStatus.PENDING
        assert checkpoint.attempts == 0


def test_cache_identity_is_scope_agnostic() -> None:
    values = {
        "input_hash": "a" * 64,
        "model_profile": "gpt-5.6-luna/high/no-fast",
        "prompt_version": "m07-p1",
        "output_schema_version": "m07-s1",
    }
    global_key = normalized_cache_key(**values)
    scoped_key = normalized_cache_key(**values)
    assert global_key == scoped_key
    assert len(global_key) == 64

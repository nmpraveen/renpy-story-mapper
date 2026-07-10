"""Independent black-box contracts for the M03 public project boundary.

The implementation is intentionally absent at the assigned base commit. These tests define the
expected public API without importing implementation-private SQLite or analyzer helpers:

* ``create_project(database_path, source_root, *, cancel_check=None) -> Project``
* ``open_project(database_path) -> Project``
* ``refresh_project(database_path, source_root, *, cancel_check=None) -> RefreshReport``
* ``delete_project(database_path) -> None``
* ``Project.authoritative_bytes() -> bytes`` and ``Project.snapshot() -> Mapping``
* ``RefreshReport.parsed_sources``, ``reused_sources``, and ``invalidated_sources``

The module also exposes ``PROJECT_SCHEMA_VERSION`` and the three safe-failure exception types used
below. Source paths in snapshots and refresh reports are normalized project-relative POSIX paths.
"""

from __future__ import annotations

import importlib
import shutil
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "m03"


@pytest.fixture
def project_api() -> ModuleType:
    try:
        return importlib.import_module("renpy_story_mapper.project")
    except ModuleNotFoundError:
        pytest.fail(
            "M03 contract requires the public renpy_story_mapper.project module described in "
            "this test module's docstring"
        )


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    destination = tmp_path / "game"
    shutil.copytree(FIXTURES, destination)
    return destination


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    return tmp_path / "story.rsmproj"


def _snapshot(project: Any) -> Mapping[str, Any]:
    snapshot = project.snapshot()
    assert isinstance(snapshot, Mapping)
    return snapshot


def _records(snapshot: Mapping[str, Any], name: str) -> Sequence[Mapping[str, Any]]:
    records = snapshot[name]
    assert isinstance(records, Sequence) and not isinstance(records, (str, bytes))
    assert all(isinstance(record, Mapping) for record in records)
    return records


def _record_containing(records: Sequence[Mapping[str, Any]], text: str) -> Mapping[str, Any]:
    for record in records:
        if _value_contains(record, text, exact=True):
            return record
    for record in records:
        if _value_contains(record, text, exact=False):
            return record
    pytest.fail(f"No public record contains {text!r}")


def _value_contains(value: Any, text: str, *, exact: bool) -> bool:
    if isinstance(value, str):
        return value == text if exact else text in value
    if isinstance(value, Mapping):
        return any(_value_contains(item, text, exact=exact) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_value_contains(item, text, exact=exact) for item in value)
    return False


def _source_paths(value: Any) -> set[str]:
    assert isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    return {str(item).replace("\\", "/") for item in value}


def _close(project: Any) -> None:
    close = getattr(project, "close", None)
    if close is not None:
        close()


def test_create_open_and_delete_project_lifecycle(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    created = project_api.create_project(project_path, source_tree)
    assert project_path.is_file()
    created_bytes = created.authoritative_bytes()
    assert created_bytes
    _close(created)

    reopened = project_api.open_project(project_path)
    assert reopened.authoritative_bytes() == created_bytes
    _close(reopened)

    project_api.delete_project(project_path)
    assert not project_path.exists()


def test_authoritative_reopen_is_byte_equivalent(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    first = project_api.create_project(project_path, source_tree)
    before = first.authoritative_bytes()
    _close(first)

    second = project_api.open_project(project_path)
    after = second.authoritative_bytes()
    _close(second)

    assert after == before


def test_state_fixture_covers_literal_assignments_deltas_and_literal_calls(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    snapshot = _snapshot(project)
    effects = _records(snapshot, "effects")
    variables = _records(snapshot, "state_variables")

    for expression in (
        "love += 1",
        "lust_points -= 2",
        "dating = True",
        "cheating = False",
        "wits = 3",
        "money -= 10",
        'job = "Company Z"',
        "chapter = 3",
    ):
        assert _record_containing(effects, expression)["status"] == "proven"

    for call in ('xp_up("lust")', 'set_relationship("alex", "dating", True)'):
        assert _record_containing(effects, call)["status"] == "possible"

    expected_categories = {
        "love": "relationship",
        "lust_points": "relationship",
        "dating": "relationship",
        "wits": "skill",
        "money": "resource",
        "job": "job",
        "chapter": "progression",
    }
    for variable_name, category in expected_categories.items():
        record = _record_containing(variables, variable_name)
        assert record["original_name"] == variable_name
        assert record["category"] == category
        assert record["display_name"]
    _close(project)


def test_boolean_chained_branch_and_choice_requirements_are_proven(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    requirements = _records(_snapshot(project), "requirements")

    for expression in (
        "wits > 0 and chapter >= 2",
        "0 < charisma <= 5",
        "money >= 10 and (dating or love > 2)",
        "not cheating and dating",
    ):
        record = _record_containing(requirements, expression)
        assert record["status"] == "proven"
        assert record["evidence"]["source_path"] == "requirements.rpy"
    _close(project)


def test_exact_physical_line_evidence_is_preserved(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    snapshot = _snapshot(project)

    love = _record_containing(_records(snapshot, "effects"), "love += 1")
    assert love["evidence"] == {
        "source_path": "state_basics.rpy",
        "start_line": 3,
        "end_line": 3,
    }
    gate = _record_containing(_records(snapshot, "requirements"), "wits > 0 and chapter >= 2")
    assert gate["evidence"] == {
        "source_path": "requirements.rpy",
        "start_line": 2,
        "end_line": 2,
    }
    _close(project)


def test_dynamic_and_computed_cases_are_never_proven(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    snapshot = _snapshot(project)
    effects = _records(snapshot, "effects")
    unresolved = _records(snapshot, "unresolved")

    safe = _record_containing(effects, "safe_literal = 7")
    assert safe["status"] == "proven"

    for expression in (
        "current_love + bonus",
        "points[hero_name] += amount",
        "choose_job()",
        "setattr(store, variable_name, 1)",
        "award_points(stat_name, calculate_amount())",
        "getattr(store, gate_name)",
    ):
        record = _record_containing(unresolved, expression)
        assert record["status"] == "unresolved"
        assert record["evidence"]["source_path"] == "dynamic_unsupported.rpy"
    _close(project)


def test_proven_possible_and_unresolved_are_disjoint_public_sets(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    snapshot = _snapshot(project)
    effect_ids = {
        status: {
            str(record["id"])
            for record in _records(snapshot, "effects")
            if record["status"] == status
        }
        for status in ("proven", "possible")
    }
    unresolved_ids = {str(record["id"]) for record in _records(snapshot, "unresolved")}

    assert effect_ids["proven"]
    assert effect_ids["possible"]
    assert unresolved_ids
    assert effect_ids["proven"].isdisjoint(effect_ids["possible"])
    assert effect_ids["proven"].isdisjoint(unresolved_ids)
    assert effect_ids["possible"].isdisjoint(unresolved_ids)
    _close(project)


def test_unchanged_refresh_reuses_every_source_without_reparse(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    created = project_api.create_project(project_path, source_tree)
    before = created.authoritative_bytes()
    source_count = len(_records(_snapshot(created), "sources"))
    _close(created)

    report = project_api.refresh_project(project_path, source_tree)
    assert _source_paths(report.parsed_sources) == set()
    assert len(_source_paths(report.reused_sources)) == source_count
    assert _source_paths(report.invalidated_sources) == set()

    reopened = project_api.open_project(project_path)
    assert reopened.authoritative_bytes() == before
    _close(reopened)


def test_changed_source_reparses_once_and_invalidates_only_dependents(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    before = _snapshot(project)
    unrelated_before = _record_containing(_records(before, "effects"), "unrelated_flag = True")
    _close(project)

    shared = source_tree / "dependencies" / "shared.rpy"
    shared.write_text(shared.read_text(encoding="utf-8").replace("+= 1", "+= 2"), encoding="utf-8")
    report = project_api.refresh_project(project_path, source_tree)

    assert _source_paths(report.parsed_sources) == {"dependencies/shared.rpy"}
    assert _source_paths(report.invalidated_sources) == {
        "dependencies/entry.rpy",
        "dependencies/shared.rpy",
    }
    assert "dependencies/unrelated.rpy" in _source_paths(report.reused_sources)

    reopened = project_api.open_project(project_path)
    after = _snapshot(reopened)
    unrelated_after = _record_containing(_records(after, "effects"), "unrelated_flag = True")
    assert unrelated_after == unrelated_before
    assert _record_containing(_records(after, "effects"), "shared_points += 2")
    _close(reopened)


def test_two_fresh_projects_have_deterministic_authoritative_output(
    project_api: ModuleType, source_tree: Path, tmp_path: Path
) -> None:
    first = project_api.create_project(tmp_path / "first.rsmproj", source_tree)
    second = project_api.create_project(tmp_path / "second.rsmproj", source_tree)
    assert first.authoritative_bytes() == second.authoritative_bytes()
    _close(first)
    _close(second)


def test_user_state_metadata_survives_unchanged_refresh(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    project.update_state_variable(
        "love", display_name="Custom Affection", category="custom_relationship"
    )
    _close(project)

    report = project_api.refresh_project(project_path, source_tree)
    assert _source_paths(report.parsed_sources) == set()
    reopened = project_api.open_project(project_path)
    love = _record_containing(_records(_snapshot(reopened), "state_variables"), "love")
    assert love["display_name"] == "Custom Affection"
    assert love["category"] == "custom_relationship"
    assert love["user_override"] is True
    _close(reopened)


class _CancelOnCheck:
    def __init__(self) -> None:
        self.checks = 0

    def __call__(self) -> bool:
        self.checks += 1
        return True


def test_cancelled_create_rolls_back_without_partial_project(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    cancel = _CancelOnCheck()
    with pytest.raises(project_api.ProjectCancelledError):
        project_api.create_project(project_path, source_tree, cancel_check=cancel)
    assert cancel.checks > 0
    assert not project_path.exists()
    assert not list(project_path.parent.glob(f"{project_path.name}*.tmp"))


def test_cancelled_refresh_preserves_last_committed_authoritative_data(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    project = project_api.create_project(project_path, source_tree)
    before = project.authoritative_bytes()
    _close(project)
    target = source_tree / "state_basics.rpy"
    target.write_text(target.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    cancel = _CancelOnCheck()
    with pytest.raises(project_api.ProjectCancelledError):
        project_api.refresh_project(project_path, source_tree, cancel_check=cancel)
    assert cancel.checks > 0

    reopened = project_api.open_project(project_path)
    assert reopened.authoritative_bytes() == before
    _close(reopened)


def test_corrupt_project_fails_safely_without_rewriting_input(
    project_api: ModuleType, project_path: Path
) -> None:
    corrupt_bytes = b"not a sqlite project\x00synthetic"
    project_path.write_bytes(corrupt_bytes)
    with pytest.raises(project_api.ProjectCorruptionError):
        project_api.open_project(project_path)
    assert project_path.read_bytes() == corrupt_bytes


def test_incompatible_future_schema_fails_safely(
    project_api: ModuleType, project_path: Path
) -> None:
    future_version = int(project_api.PROJECT_SCHEMA_VERSION) + 1
    with sqlite3.connect(project_path) as connection:
        connection.execute(f"PRAGMA user_version = {future_version}")

    before = project_path.read_bytes()
    with pytest.raises(project_api.IncompatibleProjectVersionError):
        project_api.open_project(project_path)
    assert project_path.read_bytes() == before


def test_supported_previous_schema_is_migrated_transactionally(
    project_api: ModuleType, source_tree: Path, project_path: Path
) -> None:
    current_version = int(project_api.PROJECT_SCHEMA_VERSION)
    assert current_version >= 2, "M03 must retain at least one executable migration path"
    project = project_api.create_project(project_path, source_tree)
    authoritative_before = project.authoritative_bytes()
    _close(project)

    with sqlite3.connect(project_path) as connection:
        connection.execute(f"PRAGMA user_version = {current_version - 1}")

    migrated = project_api.open_project(project_path)
    assert migrated.authoritative_bytes() == authoritative_before
    _close(migrated)
    with sqlite3.connect(project_path) as connection:
        migrated_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert migrated_version == current_version


@pytest.mark.parametrize(
    ("operation", "expected_exception"),
    [
        (lambda api, path, source: api.create_project(path, source), FileExistsError),
        (
            lambda api, path, source: api.open_project(path.with_name("missing.rsmproj")),
            FileNotFoundError,
        ),
    ],
)
def test_lifecycle_refuses_overwrite_and_missing_open(
    project_api: ModuleType,
    source_tree: Path,
    project_path: Path,
    operation: Callable[[ModuleType, Path, Path], Any],
    expected_exception: type[Exception],
) -> None:
    existing = project_api.create_project(project_path, source_tree)
    _close(existing)
    with pytest.raises(expected_exception):
        operation(project_api, project_path, source_tree)

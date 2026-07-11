from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.project import Project, create_project, refresh_project
from renpy_story_mapper.story_organization import StoryOrganizationService

FIXTURE = Path(__file__).parent / "fixtures" / "m05" / "organization"


def _create(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    shutil.copytree(FIXTURE, source)
    path = tmp_path / "story.rsmproj"
    create_project(path, source).close()
    return Project.open(path)


def _candidate(project: Project, *, suffix: str = "") -> dict[str, object]:
    connection = project._require_open()
    beats = [
        str(row[0])
        for row in connection.execute(
            "SELECT node_id FROM presentation_nodes WHERE level=3 ORDER BY sort_key,node_id"
        )
    ]
    assert len(beats) >= 7
    first = beats[:3]
    second = beats[3:6]
    third = beats[6:]
    evidence = str(
        connection.execute(
            "SELECT evidence_id FROM presentation_evidence WHERE node_id=?", (first[0],)
        ).fetchone()[0]
    )
    return {
        "events": [
            {
                "id": f"event-a{suffix}",
                "title": "Storm",
                "summary": "The storm begins.",
                "beat_ids": first,
            },
            {
                "id": f"event-b{suffix}",
                "title": "Choice",
                "summary": "A route is chosen.",
                "beat_ids": second,
            },
            {
                "id": f"event-c{suffix}",
                "title": "Ending",
                "summary": "The routes meet.",
                "beat_ids": third,
            },
        ],
        "arcs": [
            {
                "id": f"arc-a{suffix}",
                "title": "Opening",
                "summary": "The opening arc.",
                "event_ids": [f"event-a{suffix}", f"event-b{suffix}"],
            },
            {
                "id": f"arc-b{suffix}",
                "title": "Outcome",
                "summary": "The outcome arc.",
                "event_ids": [f"event-c{suffix}"],
            },
        ],
        "claims": [
            {
                "id": f"claim-a{suffix}",
                "event_id": f"event-a{suffix}",
                "text": "The storm creates tension.",
                "kind": "interpretation",
                "evidence_ids": [evidence],
            }
        ],
    }


def _run_and_draft(service: StoryOrganizationService, candidate: dict[str, object]) -> str:
    run_id = service.create_run(
        provider_mode="local",
        model_profile="balanced",
        model_fingerprint="synthetic-model",
        prompt_version="p1",
        output_schema_version="s1",
        generation="generation-1",
    )
    service.finish_run(run_id, "completed", elapsed_ms=5, usage={"input": 10})
    return service.create_draft(run_id, "generation-1", candidate)


def test_v3_migrates_transactionally_and_failed_v4_migration_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "legacy.rsmp"
    connection = storage.connect(legacy)
    storage.initialize_database(connection, target_version=3)
    connection.close()

    with Project.open(legacy) as project:
        assert project.schema_version == 4
        assert (
            project._require_open()
            .execute("SELECT 1 FROM sqlite_schema WHERE name='story_events'")
            .fetchone()
        )
    backup = legacy.with_name("legacy.rsmp.pre-migrate-v3.bak")
    backup_connection = storage.connect(backup)
    try:
        assert storage.validate_database(backup_connection) == 3
    finally:
        backup_connection.close()

    failed = tmp_path / "failed.rsmp"
    connection = storage.connect(failed)
    storage.initialize_database(connection, target_version=3)

    def fail_migration(target: sqlite3.Connection) -> None:
        target.execute("CREATE TABLE partial(value TEXT) STRICT")
        raise storage.ProjectOperationCancelled("cancelled")

    monkeypatch.setattr(storage, "_migrate_to_v4", fail_migration)
    with pytest.raises(storage.ProjectOperationCancelled):
        storage.initialize_database(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='partial'").fetchone() is None
    connection.close()


def test_v4_structural_corruption_is_rejected(tmp_path: Path) -> None:
    project = _create(tmp_path)
    path = project.path
    project.close()
    connection = sqlite3.connect(path)
    connection.execute("DROP INDEX story_event_edges_source_idx")
    connection.close()
    with pytest.raises(storage.ProjectCorruptError, match="organization indexes"):
        Project.open(path)


def test_atomic_apply_discard_and_authoritative_data_is_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        authoritative = project.authoritative_bytes()
        first = _run_and_draft(service, _candidate(project))
        assert service.drafts(status="pending")[0].id == first
        service.discard_draft(first)
        assert service.arcs() == ()

        applied = _run_and_draft(service, _candidate(project))
        service.apply_draft(applied)
        accepted = service.arcs(include_hidden=True)
        assert [arc.id for arc in accepted] == ["arc-a", "arc-b"]
        assert service.claims(event_id="event-a")[0].kind == "interpretation"
        assert project.authoritative_bytes() == authoritative

        replacement = _run_and_draft(service, _candidate(project, suffix="-next"))

        def fail_edges() -> None:
            raise RuntimeError("synthetic failure")

        monkeypatch.setattr(service, "_derive_event_edges", fail_edges)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            service.apply_draft(replacement)
        assert service.arcs(include_hidden=True) == accepted


def test_candidate_validation_rejects_unknown_duplicate_and_unsupported_claims(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        candidate = _candidate(project)
        events = candidate["events"]
        assert isinstance(events, list) and isinstance(events[0], dict)
        events[0]["beat_ids"] = ["invented-beat"]
        run = service.create_run(
            provider_mode="local",
            model_profile="balanced",
            model_fingerprint=None,
            prompt_version="p1",
            output_schema_version="s1",
            generation="g1",
        )
        with pytest.raises(ValueError, match="unknown beat"):
            service.create_draft(run, "g1", candidate)
        candidate = _candidate(project)
        candidate["edges"] = [{"source": "event-a", "target": "event-b"}]
        with pytest.raises(ValueError, match="unsupported fields"):
            service.create_draft(run, "g1", candidate)
        assert service.arcs() == ()


def test_quotient_edges_and_m03_facts_are_derived_locally(tmp_path: Path) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        draft = _run_and_draft(service, _candidate(project))
        service.apply_draft(draft)
        edges = service.event_edges()
        assert edges
        assert all(edge.source_id != edge.target_id for edge in edges)
        assert all(value.startswith("l3:") for edge in edges for value in edge.transition_ids)
        assert service.arc_edges()
        facts = service.attached_facts()
        assert {fact.fact_kind for fact in facts} == {"gate", "effect"}
        assert all(fact.evidence_id.startswith("fact:") for fact in facts)


def test_durable_corrections_enforce_boundaries_contiguity_and_preserve_edges(
    tmp_path: Path,
) -> None:
    path: Path
    with _create(tmp_path) as project:
        path = project.path
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        first = service.events(arc_id="arc-a")[0]
        with pytest.raises(ValueError, match="boundary"):
            service.split_event(first.id, "unknown", new_title="Invalid")
        split = service.split_event(first.id, first.beat_ids[1], new_title="After the storm")
        assert service.events(arc_id="arc-a")[1].id == split
        with pytest.raises(ValueError, match="same arc"):
            service.merge_events(split, "event-c", title="Invalid")
        merged = service.merge_events(split, "event-b", title="Decision")
        after_merge = service.event_edges()
        assert after_merge
        service.move_event(merged, "arc-b", 0)
        assert service.event_edges() == after_merge
        service.rename("event", merged, "A durable decision")
        service.set_hidden("event", merged, True)
        service.set_hidden("event", merged, False)
        service.set_pinned("event", merged, True)
        service.set_approval("event", merged, "approved")
        assert {edit.operation for edit in service.edits(merged)} >= {
            "merge",
            "move",
            "rename",
            "hide",
            "pin",
            "approve",
        }
        assert project.authoritative_bytes()

    with Project.open(path) as reopened:
        restored = reopened.organization_service().events(arc_id="arc-b", include_hidden=True)
        assert restored[0].title == "A durable decision"
        assert restored[0].pinned and restored[0].approval_state == "approved"


def test_pinned_groups_override_reruns_and_missing_beats_become_needs_review(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_pinned("event", "event-a", True)
        pinned_beats = service.events(arc_id="arc-a")[0].beat_ids
        service.apply_draft(_run_and_draft(service, _candidate(project, suffix="-next")))
        pinned = next(
            event for event in service.events(include_hidden=True) if event.id == "event-a"
        )
        assert pinned.beat_ids == pinned_beats
        path = project.path
        project.close()

        unchanged = refresh_project(path, tmp_path / "game")
        assert unchanged.parsed_sources == ()
        with Project.open(path) as reopened:
            assert next(
                event
                for event in reopened.organization_service().events(include_hidden=True)
                if event.id == "event-a"
            ).beat_ids == pinned_beats

        (tmp_path / "game" / "story.rpy").write_text(
            "label start:\n    return\n", encoding="utf-8"
        )
        changed = refresh_project(path, tmp_path / "game")
        assert changed.parsed_sources == ("story.rpy",)
        with Project.open(path) as refreshed:
            reviewed_service = refreshed.organization_service()
            reviewed = next(
                event
                for event in reviewed_service.events(include_hidden=True)
                if event.id == "event-a"
            )
            assert reviewed.needs_review
            assert next(
                arc
                for arc in reviewed_service.arcs(include_hidden=True)
                if arc.id == "arc-a"
            ).needs_review


def test_cache_key_exactness_run_chunk_status_and_no_dialogue_duplication(tmp_path: Path) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        digest = hashlib.sha256(b"input").hexdigest()
        identity = service.cache_identity(
            provider_mode="local",
            model_fingerprint="model-a",
            prompt_version="p1",
            output_schema_version="s1",
            input_hash=digest,
            ordered_ids=["beat-a", "beat-b"],
        )
        assert service.cache_result(identity) is None
        service.store_cache_result(identity, {"events": [{"id": "event-a"}]})
        assert service.cache_result(identity) == {"events": [{"id": "event-a"}]}
        changed = service.cache_identity(
            provider_mode="local",
            model_fingerprint="model-a",
            prompt_version="p2",
            output_schema_version="s1",
            input_hash=digest,
            ordered_ids=["beat-a", "beat-b"],
        )
        assert service.cache_result(changed) is None
        with pytest.raises(ValueError, match="raw fields"):
            service.store_cache_result(identity, {"dialogue": "A storm begins."})

        run = service.create_run(
            provider_mode="local",
            model_profile="balanced",
            model_fingerprint="model-a",
            prompt_version="p1",
            output_schema_version="s1",
            generation="g1",
        )
        service.record_chunk(
            run_id=run,
            scope_id="scene:start",
            reconciliation_scope="scene:start",
            ordinal=0,
            identity=identity,
            cache_state="hit",
            status="validated",
            result={"events": [{"id": "event-a"}]},
        )
        service.finish_run(run, "cancelled", elapsed_ms=1)
        assert service.runs()[-1].status == "cancelled"
        assert service.runs()[-1].sanitized_failure == "Organization did not complete."
        assert service.chunks(run)[0].result == {"events": [{"id": "event-a"}]}
        assert service.cache_entry_count() == 1

        organization_tables = [
            str(row[0])
            for row in project._require_open().execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND "
                "(name LIKE 'organization_%' OR name LIKE 'story_%')"
            )
        ]
        for table in organization_tables:
            values = project._require_open().execute(f'SELECT * FROM "{table}"').fetchall()
            assert "A storm begins." not in repr([tuple(row) for row in values])


def test_synthetic_query_plans_use_bounded_indexes(tmp_path: Path) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        connection = project._require_open()
        now = storage.utc_now()
        row_count = 10_000
        with storage.transaction(connection):
            connection.executemany(
                "INSERT INTO story_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (
                        f"synthetic-event-{index:05d}",
                        "Synthetic",
                        "",
                        index + 100,
                        "deterministic",
                        0,
                        0,
                        "approved",
                        0,
                        "synthetic-generation",
                        now,
                    )
                    for index in range(row_count)
                ),
            )
            connection.executemany(
                "INSERT INTO story_event_members VALUES (?,?,0)",
                (
                    (f"synthetic-event-{index:05d}", f"synthetic-beat-{index:05d}")
                    for index in range(row_count)
                ),
            )
        started = time.perf_counter()
        member_plan = service.query_plan(
            "SELECT event_id FROM story_event_members WHERE beat_id=?", ("missing",)
        )
        edge_plan = service.query_plan(
            "SELECT target_event_id FROM story_event_edges WHERE source_event_id=? AND kind=?",
            ("event-a", "flow"),
        )
        for index in range(200):
            row = connection.execute(
                "SELECT event_id FROM story_event_members WHERE beat_id=?",
                (f"synthetic-beat-{index * 49:05d}",),
            ).fetchone()
            assert row is not None
        elapsed = time.perf_counter() - started
        assert all(
            any("SEARCH" in detail and "INDEX" in detail for detail in plan)
            for plan in (member_plan, edge_plan)
        )
        assert elapsed < 1.0

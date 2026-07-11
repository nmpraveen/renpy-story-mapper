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


def _review_all(
    service: StoryOrganizationService,
    draft_id: str,
    candidate: dict[str, object],
) -> None:
    for kind, collection in (("arc", "arcs"), ("event", "events")):
        values = candidate[collection]
        assert isinstance(values, list)
        for value in values:
            assert isinstance(value, dict) and isinstance(value["id"], str)
            service.review_draft_group(draft_id, kind, value["id"], "approved")  # type: ignore[arg-type]


def _run_and_draft(
    service: StoryOrganizationService,
    candidate: dict[str, object],
    *,
    review: bool = True,
) -> str:
    run_id = service.create_run(
        provider_mode="local",
        model_profile="balanced",
        model_fingerprint="synthetic-model",
        prompt_version="p1",
        output_schema_version="s1",
        generation="generation-1",
    )
    service.finish_run(run_id, "completed", elapsed_ms=5, usage={"input": 10})
    draft_id = service.create_draft(run_id, "generation-1", candidate)
    if review:
        _review_all(service, draft_id, candidate)
    return draft_id


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
        cache_columns = {
            str(row[1])
            for row in project._require_open().execute("PRAGMA table_info(organization_cache)")
        }
        assert "model_profile" in cache_columns
        assert (
            project._require_open()
            .execute("SELECT 1 FROM sqlite_schema WHERE name='organization_draft_reviews'")
            .fetchone()
        )
        cache_index = tuple(
            str(row[2])
            for row in project._require_open().execute(
                'PRAGMA index_info("organization_cache_lookup_idx")'
            )
        )
        assert cache_index[:3] == ("provider_mode", "model_profile", "model_fingerprint")
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

    constrained = _create(tmp_path / "constraint")
    constrained_path = constrained.path
    constrained.close()
    connection = sqlite3.connect(constrained_path)
    connection.execute("PRAGMA writable_schema=ON")
    connection.execute(
        """UPDATE sqlite_schema SET sql=replace(
            sql,
            'origin TEXT NOT NULL CHECK (origin IN (''ai'',''deterministic'',''user''))',
            'origin TEXT NOT NULL'
        ) WHERE type='table' AND name='story_events'"""
    )
    schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
    connection.execute(f"PRAGMA schema_version={schema_version + 1}")
    connection.execute("PRAGMA writable_schema=OFF")
    connection.commit()
    connection.close()
    with pytest.raises(storage.ProjectCorruptError, match="invalid constraints"):
        Project.open(constrained_path)


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
        organization_rows = project._require_open().execute(
            """SELECT name FROM sqlite_schema WHERE type='table'
               AND (name LIKE 'organization_%' OR name LIKE 'story_%')"""
        )
        for table_row in organization_rows:
            table = str(table_row[0])
            rows = project._require_open().execute(f'SELECT * FROM "{table}"').fetchall()
            assert "A storm begins." not in repr([tuple(row) for row in rows])

        replacement = _run_and_draft(service, _candidate(project, suffix="-next"))

        def fail_edges() -> None:
            raise RuntimeError("synthetic failure")

        monkeypatch.setattr(service, "_derive_event_edges", fail_edges)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            service.apply_draft(replacement)
        assert service.arcs(include_hidden=True) == accepted


def test_draft_group_review_reject_fallback_apply_and_reopen(tmp_path: Path) -> None:
    path: Path
    with _create(tmp_path) as project:
        path = project.path
        service = project.organization_service()
        candidate = _candidate(project)
        draft = _run_and_draft(service, candidate, review=False)
        with pytest.raises(ValueError, match="must be reviewed"):
            service.apply_draft(draft)

        service.review_draft_group(draft, "arc", "arc-a", "approved")
        service.review_draft_group(draft, "arc", "arc-b", "approved")
        service.review_draft_group(draft, "event", "event-a", "approved")
        service.review_draft_group(draft, "event", "event-b", "rejected")
        service.review_draft_group(draft, "event", "event-c", "approved")
        assert len(service.draft_reviews(draft)) == 5
        rejected_beats = tuple(
            next(
                value["beat_ids"]
                for value in candidate["events"]  # type: ignore[union-attr]
                if value["id"] == "event-b"
            )
        )
        service.apply_draft(draft)
        events = service.events(include_hidden=True)
        assert "event-b" not in {event.id for event in events}
        fallback = next(event for event in events if event.beat_ids == rejected_beats)
        assert fallback.origin == "deterministic"
        assert fallback.approval_state == "approved"
        assert all(event.approval_state == "approved" for event in events)
        assert all(arc.approval_state == "approved" for arc in service.arcs(include_hidden=True))
        assert project.authoritative_bytes()

        discarded = _run_and_draft(service, _candidate(project, suffix="-discard"), review=False)
        service.review_draft_group(discarded, "arc", "arc-a-discard", "rejected")
        service.discard_draft(discarded)

    with Project.open(path) as reopened:
        restored = reopened.organization_service()
        assert len(restored.draft_reviews(draft)) == 5
        assert restored.drafts()[-1].status == "discarded"
        assert any(
            event.origin == "deterministic" for event in restored.events(include_hidden=True)
        )


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


def test_candidate_requires_complete_non_crossing_chronological_coverage(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        required_beat = str(
            project._require_open()
            .execute(
                """SELECT node_id FROM presentation_nodes WHERE level=3
                   AND kind IN ('narrative','dialogue','narration','choice','condition')
                   ORDER BY sort_key,node_id LIMIT 1"""
            )
            .fetchone()[0]
        )

        def remove_required(candidate: dict[str, object]) -> None:
            events = candidate["events"]
            assert isinstance(events, list)
            for event in events:
                assert isinstance(event, dict) and isinstance(event["beat_ids"], list)
                if required_beat in event["beat_ids"]:
                    event["beat_ids"].remove(required_beat)
                    return
            raise AssertionError("required beat not found")

        omitted = _candidate(project)
        remove_required(omitted)
        with pytest.raises(ValueError, match="required story beats"):
            _run_and_draft(service, omitted, review=False)

        duplicate_ungrouped = _candidate(project)
        remove_required(duplicate_ungrouped)
        duplicate_ungrouped["ungrouped_beat_ids"] = [required_beat, required_beat]
        with pytest.raises(ValueError, match="cannot contain duplicates"):
            _run_and_draft(service, duplicate_ungrouped, review=False)

        reordered_events = _candidate(project)
        assert isinstance(reordered_events["events"], list)
        reordered_events["events"].reverse()
        with pytest.raises(ValueError, match="globally ordered"):
            _run_and_draft(service, reordered_events, review=False)

        reordered_within_arc = _candidate(project)
        arcs = reordered_within_arc["arcs"]
        assert isinstance(arcs, list) and isinstance(arcs[0], dict)
        assert isinstance(arcs[0]["event_ids"], list)
        arcs[0]["event_ids"].reverse()
        with pytest.raises(ValueError, match="within an arc"):
            _run_and_draft(service, reordered_within_arc, review=False)

        reordered_arcs = _candidate(project)
        assert isinstance(reordered_arcs["arcs"], list)
        reordered_arcs["arcs"].reverse()
        with pytest.raises(ValueError, match="candidate arcs"):
            _run_and_draft(service, reordered_arcs, review=False)

        empty_summary = _candidate(project)
        empty_events = empty_summary["events"]
        assert isinstance(empty_events, list) and isinstance(empty_events[0], dict)
        empty_events[0]["summary"] = ""
        with pytest.raises(ValueError, match="summary"):
            _run_and_draft(service, empty_summary, review=False)

        empty_arc_title = _candidate(project)
        empty_arcs = empty_arc_title["arcs"]
        assert isinstance(empty_arcs, list) and isinstance(empty_arcs[0], dict)
        empty_arcs[0]["title"] = " "
        with pytest.raises(ValueError, match="title"):
            _run_and_draft(service, empty_arc_title, review=False)

        invalid_origin = _candidate(project)
        invalid_events = invalid_origin["events"]
        assert isinstance(invalid_events, list) and isinstance(invalid_events[0], dict)
        invalid_events[0]["origin"] = {"not": "a string"}
        with pytest.raises(ValueError, match="origin"):
            _run_and_draft(service, invalid_origin, review=False)

        explicit_fallback = _candidate(project, suffix="-ungrouped")
        remove_required(explicit_fallback)
        explicit_fallback["ungrouped_beat_ids"] = [required_beat]
        draft = _run_and_draft(service, explicit_fallback)
        service.apply_draft(draft)
        assert any(
            event.beat_ids == (required_beat,) and event.origin == "deterministic"
            for event in service.events(include_hidden=True)
        )


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
        assert all(fact.source_path == "story.rpy" for fact in facts)
        assert all(fact.start_line > 0 and fact.end_line >= fact.start_line for fact in facts)
        expressions = {fact.expression: fact for fact in facts}
        assert expressions["courage > 0"].start_line == 3
        assert expressions["trust += 1"].start_line == 7


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
        service.rename("arc", "arc-a", "Pinned opening")
        pinned_beats = service.events(arc_id="arc-a")[0].beat_ids
        preserved_claim = service.claims(event_id="event-a")[0]
        service.apply_draft(_run_and_draft(service, _candidate(project, suffix="-next")))
        pinned = next(
            event for event in service.events(include_hidden=True) if event.id == "event-a"
        )
        assert pinned.beat_ids == pinned_beats
        assert service.claims(event_id="event-a")[0] == preserved_claim
        assert any(event.id == "event-c-next" for event in service.events(include_hidden=True))
        assert all(arc.event_ids for arc in service.arcs(include_hidden=True))
        assert all(event.beat_ids for event in service.events(include_hidden=True))
        assert any(edit.operation == "rename" for edit in service.edits("arc-a"))
        path = project.path
        project.close()

        unchanged = refresh_project(path, tmp_path / "game")
        assert unchanged.parsed_sources == ()
        with Project.open(path) as reopened:
            assert (
                next(
                    event
                    for event in reopened.organization_service().events(include_hidden=True)
                    if event.id == "event-a"
                ).beat_ids
                == pinned_beats
            )

        (tmp_path / "game" / "story.rpy").write_text("label start:\n    return\n", encoding="utf-8")
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
                arc for arc in reviewed_service.arcs(include_hidden=True) if arc.id == "arc-a"
            ).needs_review
            assert reviewed_service.claims(event_id="event-a")[0].status == "needs_review"
            assert all(edit.status == "needs_review" for edit in reviewed_service.edits("arc-a"))


def test_cache_key_exactness_run_chunk_status_and_no_dialogue_duplication(tmp_path: Path) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        digest = hashlib.sha256(b"input").hexdigest()
        identity = service.cache_identity(
            provider_mode="local",
            model_profile="balanced",
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
            model_profile="balanced",
            model_fingerprint="model-a",
            prompt_version="p2",
            output_schema_version="s1",
            input_hash=digest,
            ordered_ids=["beat-a", "beat-b"],
        )
        assert service.cache_result(changed) is None
        changed_profile = service.cache_identity(
            provider_mode="local",
            model_profile="quality",
            model_fingerprint="model-a",
            prompt_version="p1",
            output_schema_version="s1",
            input_hash=digest,
            ordered_ids=["beat-a", "beat-b"],
        )
        assert changed_profile.key != identity.key
        assert service.cache_result(changed_profile) is None
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
                        "Synthetic benchmark event.",
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

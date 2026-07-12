from __future__ import annotations

import hashlib
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.project import Project, create_project, refresh_project
from renpy_story_mapper.story_organization import (
    StoryArc,
    StoryEvent,
    StoryOrganizationService,
)

FIXTURE = Path(__file__).parent / "fixtures" / "m05" / "organization"


def _create(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    shutil.copytree(FIXTURE, source)
    path = tmp_path / "story.rsmproj"
    create_project(path, source).close()
    return Project.open(path)


def _rows(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> tuple[tuple[object, ...], ...]:
    return tuple(tuple(row) for row in connection.execute(sql, parameters))


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


def _scoped_candidate(
    project: Project, event_indexes: tuple[int, ...], *, suffix: str
) -> dict[str, object]:
    connection = project._require_open()
    containers = connection.execute(
        "SELECT node_id FROM presentation_nodes WHERE level=2 ORDER BY sort_key,node_id"
    ).fetchall()
    selected_events: list[dict[str, object]] = []
    selected_arcs: list[dict[str, object]] = []
    selected_beats: list[str] = []
    for index in event_indexes:
        container_id = str(containers[index][0])
        beats = [
            str(row[0])
            for row in connection.execute(
                """SELECT node_id FROM presentation_nodes
                   WHERE level=3 AND parent_id=? ORDER BY sort_key,node_id""",
                (container_id,),
            )
        ]
        letter = chr(ord("a") + index)
        event_id = f"event-{letter}{suffix}"
        selected_events.append(
            {
                "id": event_id,
                "title": f"Scoped {letter.upper()}",
                "summary": f"Exact container {letter.upper()} organization.",
                "beat_ids": beats,
            }
        )
        selected_arcs.append(
            {
                "id": f"arc-{letter}{suffix}",
                "title": f"Scoped arc {letter.upper()}",
                "summary": f"Exact container {letter.upper()} arc.",
                "event_ids": [event_id],
            }
        )
        selected_beats.extend(beats)
    return {
        "events": selected_events,
        "arcs": selected_arcs,
        "claims": [],
        "selected_beat_ids": selected_beats,
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
    selected = candidate.get("selected_beat_ids")
    if isinstance(selected, list):
        body = {key: value for key, value in candidate.items() if key != "selected_beat_ids"}
        placeholders = ",".join("?" for _ in selected)
        scope_ids = [
            str(row[0])
            for row in service._connection.execute(
                f"""SELECT DISTINCT event.node_id FROM presentation_nodes beat
                JOIN presentation_nodes event ON event.node_id=beat.parent_id
                WHERE beat.node_id IN ({placeholders}) ORDER BY event.sort_key,event.node_id""",
                selected,
            )
        ]
        draft_id = service.create_scoped_draft(
            run_id,
            "generation-1",
            body,
            scope_ids=scope_ids,
            covered_beat_ids=selected,
        )
    else:
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

    legacy_v4 = _create(tmp_path / "legacy-v4")
    legacy_v4_path = legacy_v4.path
    legacy_v4.close()
    connection = storage.connect(legacy_v4_path)
    connection.execute("DROP TABLE story_group_enrichment")
    connection.close()
    with pytest.raises(storage.IncompatibleProjectVersionError):
        Project.open(legacy_v4_path, migrate=False)
    with Project.open(legacy_v4_path) as upgraded:
        assert not storage.needs_v4_enrichment_extension(upgraded._require_open())
        assert storage.validate_database(upgraded._require_open()) == 4
    assert legacy_v4_path.with_name(f"{legacy_v4_path.name}.pre-migrate-v4.bak").is_file()

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
        assert (
            project._require_open()
            .execute("SELECT 1 FROM sqlite_schema WHERE name='story_group_enrichment'")
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


def test_run_model_fingerprint_lifecycle_preserves_cache_chunks_and_reopens(tmp_path: Path) -> None:
    path: Path
    with _create(tmp_path) as project:
        path = project.path
        service = project.organization_service()
        run = service.create_run(
            provider_mode="local",
            model_profile="balanced",
            model_fingerprint=None,
            prompt_version="p1",
            output_schema_version="s1",
            generation="g-model",
        )
        identity = service.cache_identity(
            provider_mode="local",
            model_profile="balanced",
            model_fingerprint="model-before-metadata",
            prompt_version="p1",
            output_schema_version="s1",
            input_hash=hashlib.sha256(b"input").hexdigest(),
            ordered_ids=("beat-a",),
        )
        cache_key = service.store_cache_result(identity, {"groups": []})
        chunk_id = service.record_chunk(
            run_id=run,
            scope_id="scope-a",
            reconciliation_scope="scope-a",
            ordinal=0,
            identity=identity,
            cache_state="stored",
            status="validated",
            result={"groups": []},
        )
        with pytest.raises(ValueError, match="effective model"):
            service.set_run_model_fingerprint(run, "balanced")
        service.set_run_model_fingerprint(run, "  local/model-3.2  ")
        service.set_run_model_fingerprint(run, "local/model-3.2")
        with pytest.raises(ValueError, match="different model"):
            service.set_run_model_fingerprint(run, "local/model-4")
        assert service.chunks(run)[0].id == chunk_id
        assert service.chunks(run)[0].cache_key == cache_key
        service.finish_run(run, "completed", elapsed_ms=1)
        with pytest.raises(KeyError, match="running organization run"):
            service.set_run_model_fingerprint(run, "local/model-3.2")

    with Project.open(path) as reopened:
        restored = reopened.organization_service()
        assert restored.runs()[0].model_fingerprint == "local/model-3.2"
        assert restored.chunks(run)[0].id == chunk_id


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


def test_global_draft_rejects_scope_fields_and_fully_replaces_unpinned_state(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        before = service.events(include_hidden=True)
        partial = _scoped_candidate(project, (0,), suffix="-global-bypass")
        run = service.create_run(
            provider_mode="local",
            model_profile="balanced",
            model_fingerprint=None,
            prompt_version="p1",
            output_schema_version="s1",
            generation="g-global-bypass",
        )
        with pytest.raises(ValueError, match="managed exclusively"):
            service.create_draft(run, "g-global-bypass", partial)
        assert service.events(include_hidden=True) == before

        service.set_hidden("event", "event-b", True)
        replacement = _candidate(project, suffix="-global-replacement")
        service.apply_draft(_run_and_draft(service, replacement))
        events = service.events(include_hidden=True)
        assert {event.id for event in events} == {
            "event-a-global-replacement",
            "event-b-global-replacement",
            "event-c-global-replacement",
        }
        assert all(
            service._connection.execute(
                "SELECT 1 FROM story_arc_members WHERE event_id=?", (event.id,)
            ).fetchone()
            for event in events
        )
        assert {edit.status for edit in service.edits("event-b")} == {"needs_review"}


def test_global_apply_removes_stale_and_mixed_unpinned_groups_after_refresh(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_pinned("event", "event-c", True)
        pinned_event = next(event for event in service.events() if event.id == "event-c")
        pinned_arc = next(arc for arc in service.arcs() if arc.id == "arc-b")
        connection = service._connection
        event_a_members = service._member_ids("event-a")
        event_b_members = service._member_ids("event-b")
        with storage.transaction(connection):
            for ordinal, beat_id in enumerate(event_a_members):
                connection.execute(
                    """UPDATE story_event_members SET beat_id=?
                       WHERE event_id='event-a' AND beat_id=?""",
                    (f"stale-only-{ordinal}", beat_id),
                )
            connection.execute(
                """UPDATE story_event_members SET beat_id='stale-mixed'
                   WHERE event_id='event-b' AND beat_id=?""",
                (event_b_members[0],),
            )
        assert set(service.reconcile_after_refresh()) == {"event-a", "event-b"}

        service.apply_draft(_run_and_draft(service, _candidate(project, suffix="-after-refresh")))
        event_ids = {event.id for event in service.events(include_hidden=True)}
        arc_ids = {arc.id for arc in service.arcs(include_hidden=True)}
        assert {"event-a", "event-b"}.isdisjoint(event_ids)
        assert "arc-a" not in arc_ids
        assert next(event for event in service.events() if event.id == "event-c") == pinned_event
        assert next(arc for arc in service.arcs() if arc.id == "arc-b") == pinned_arc
        assert (
            connection.execute(
                """SELECT 1 FROM story_event_members
               WHERE event_id IN ('event-a','event-b') OR beat_id LIKE 'stale-%'"""
            ).fetchone()
            is None
        )
        assert all(claim.id != "claim-a" for claim in service.claims())
        stale_enrichment = connection.execute(
            """SELECT 1 FROM story_group_enrichment
               WHERE (target_kind='event' AND target_id IN ('event-a','event-b'))
                  OR (target_kind='arc' AND target_id='arc-a')"""
        ).fetchone()
        assert stale_enrichment is None


def test_global_rerun_replays_scalar_edits_for_stable_ids_and_reopens(tmp_path: Path) -> None:
    path: Path
    with _create(tmp_path) as project:
        path = project.path
        service = project.organization_service()
        candidate = _candidate(project)
        service.apply_draft(_run_and_draft(service, candidate))
        service.rename("event", "event-a", "Remembered storm")
        service.set_pinned("event", "event-a", False)
        service.set_hidden("event", "event-a", True)
        service.set_approval("event", "event-a", "approved")
        service.set_approval("event", "event-a", "rejected")
        service.set_hidden("arc", "arc-a", True)
        service.set_approval("arc", "arc-a", "approved")
        service.set_approval("arc", "arc-a", "rejected")

        service.apply_draft(_run_and_draft(service, candidate))
        event = next(
            value for value in service.events(include_hidden=True) if value.id == "event-a"
        )
        arc = next(value for value in service.arcs(include_hidden=True) if value.id == "arc-a")
        assert event.title == "Remembered storm"
        assert event.hidden and not event.pinned and event.approval_state == "rejected"
        assert arc.hidden and arc.approval_state == "rejected"
        assert {edit.status for edit in service.edits("event-a")} == {"applied"}
        assert {edit.status for edit in service.edits("arc-a")} == {"applied"}

    with Project.open(path) as reopened:
        restored = reopened.organization_service()
        event = next(
            value for value in restored.events(include_hidden=True) if value.id == "event-a"
        )
        arc = next(value for value in restored.arcs(include_hidden=True) if value.id == "arc-a")
        assert event.title == "Remembered storm"
        assert event.hidden and not event.pinned and event.approval_state == "rejected"
        assert arc.hidden and arc.approval_state == "rejected"


def test_global_pinned_id_collisions_remap_without_lost_beats_or_orphans(
    tmp_path: Path,
) -> None:
    with _create(tmp_path / "event-collision") as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_pinned("event", "event-a", True)
        pinned = next(event for event in service.events() if event.id == "event-a")
        pinned_claims = service.claims(event_id="event-a")
        pinned_edits = service.edits("event-a")
        pinned_state = (
            _rows(service._connection, "SELECT * FROM story_events WHERE event_id='event-a'"),
            _rows(
                service._connection,
                "SELECT * FROM story_event_members WHERE event_id='event-a' ORDER BY ordinal",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_arc_members WHERE event_id='event-a'",
            ),
            _rows(service._connection, "SELECT * FROM story_claims WHERE event_id='event-a'"),
            _rows(
                service._connection,
                "SELECT * FROM story_claim_evidence WHERE claim_id IN "
                "(SELECT claim_id FROM story_claims WHERE event_id='event-a')",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_group_enrichment "
                "WHERE target_kind='event' AND target_id='event-a'",
            ),
            _rows(service._connection, "SELECT * FROM story_edits WHERE target_id='event-a'"),
        )
        pinned_beats = set(pinned.beat_ids)
        candidate = _candidate(project, suffix="-event-collision")
        events = candidate["events"]
        arcs = candidate["arcs"]
        claims = candidate["claims"]
        assert isinstance(events, list) and isinstance(arcs, list) and isinstance(claims, list)
        assert all(isinstance(value, dict) for value in (*events, *arcs, *claims))
        events[0]["id"] = "pinned-shadow-event"
        events[1]["id"] = "event-a"
        arcs[0]["event_ids"] = ["pinned-shadow-event", "event-a"]
        claims[0]["id"] = "claim-a"
        claims[0]["event_id"] = "event-a"
        replacement_beat = events[1]["beat_ids"][0]
        assert isinstance(replacement_beat, str)
        replacement_evidence = str(
            service._connection.execute(
                "SELECT evidence_id FROM presentation_evidence WHERE node_id=?",
                (replacement_beat,),
            ).fetchone()[0]
        )
        claims[0]["evidence_ids"] = [replacement_evidence]
        service.apply_draft(_run_and_draft(service, candidate))
        assert next(event for event in service.events() if event.id == "event-a") == pinned
        assert service.claims(event_id="event-a") == pinned_claims
        assert service.edits("event-a") == pinned_edits
        assert pinned_state == (
            _rows(service._connection, "SELECT * FROM story_events WHERE event_id='event-a'"),
            _rows(
                service._connection,
                "SELECT * FROM story_event_members WHERE event_id='event-a' ORDER BY ordinal",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_arc_members WHERE event_id='event-a'",
            ),
            _rows(service._connection, "SELECT * FROM story_claims WHERE event_id='event-a'"),
            _rows(
                service._connection,
                "SELECT * FROM story_claim_evidence WHERE claim_id IN "
                "(SELECT claim_id FROM story_claims WHERE event_id='event-a')",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_group_enrichment "
                "WHERE target_kind='event' AND target_id='event-a'",
            ),
            _rows(service._connection, "SELECT * FROM story_edits WHERE target_id='event-a'"),
        )
        current_beats = {
            str(row[0])
            for row in service._connection.execute(
                "SELECT node_id FROM presentation_nodes WHERE level=3"
            )
        }
        expected_unpinned = current_beats - pinned_beats
        memberships = [
            str(row[0])
            for row in service._connection.execute(
                """SELECT member.beat_id FROM story_event_members member
                       JOIN story_events event ON event.event_id=member.event_id
                       LEFT JOIN story_arc_members arc_member
                         ON arc_member.event_id=event.event_id
                       LEFT JOIN story_arcs arc ON arc.arc_id=arc_member.arc_id
                       WHERE event.pinned=0 AND COALESCE(arc.pinned,0)=0"""
            )
        ]
        assert set(memberships) == expected_unpinned
        assert len(memberships) == len(expected_unpinned)
        assert (
            service._connection.execute(
                """SELECT event.event_id FROM story_events event
               LEFT JOIN story_arc_members member ON member.event_id=event.event_id
               WHERE event.pinned=0 AND member.event_id IS NULL"""
            ).fetchone()
            is None
        )
        remapped = next(
            event
            for event in service.events()
            if event.id != "event-a" and set(event.beat_ids) == set(events[1]["beat_ids"])
        )
        remapped_claim = next(claim for claim in service.claims() if claim.event_id == remapped.id)
        assert remapped_claim.id != "claim-a"
        remapped_ids = (
            {event.id for event in service.events(include_hidden=True) if not event.pinned},
            {arc.id for arc in service.arcs(include_hidden=True) if not arc.pinned},
            {claim.id for claim in service.claims() if claim.id != "claim-a"},
        )
        service.apply_draft(_run_and_draft(service, candidate))
        assert remapped_ids == (
            {event.id for event in service.events(include_hidden=True) if not event.pinned},
            {arc.id for arc in service.arcs(include_hidden=True) if not arc.pinned},
            {claim.id for claim in service.claims() if claim.id != "claim-a"},
        )

    with _create(tmp_path / "arc-collision") as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_pinned("arc", "arc-a", True)
        pinned = next(arc for arc in service.arcs() if arc.id == "arc-a")
        pinned_events = service.events(arc_id="arc-a")
        pinned_claims = tuple(
            claim for event in pinned_events for claim in service.claims(event_id=event.id)
        )
        pinned_edits = service.edits("arc-a")
        pinned_state = (
            _rows(service._connection, "SELECT * FROM story_arcs WHERE arc_id='arc-a'"),
            _rows(
                service._connection,
                "SELECT * FROM story_arc_members WHERE arc_id='arc-a' ORDER BY ordinal",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_events WHERE event_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY event_id",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_event_members WHERE event_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY event_id,ordinal",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_claims WHERE arc_id='arc-a' OR event_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY claim_id",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_group_enrichment WHERE "
                "(target_kind='arc' AND target_id='arc-a') OR "
                "(target_kind='event' AND target_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a')) "
                "ORDER BY target_kind,target_id",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_edits WHERE target_id='arc-a' OR target_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY edit_id",
            ),
        )
        pinned_event_ids = set(pinned.event_ids)
        pinned_beats = {beat for event in service.events(arc_id="arc-a") for beat in event.beat_ids}
        candidate = _candidate(project, suffix="-arc-collision")
        arcs = candidate["arcs"]
        claims = candidate["claims"]
        assert isinstance(arcs, list) and isinstance(claims, list)
        assert isinstance(arcs[0], dict) and isinstance(arcs[1], dict)
        assert isinstance(claims[0], dict)
        events = candidate["events"]
        assert isinstance(events, list) and isinstance(events[2], dict)
        target_beat_ids = events[2]["beat_ids"]
        assert isinstance(target_beat_ids, list)
        target_evidence = str(
            service._connection.execute(
                "SELECT evidence_id FROM presentation_evidence WHERE node_id=?",
                (target_beat_ids[0],),
            ).fetchone()[0]
        )
        arcs[0]["id"] = "pinned-shadow-arc"
        arcs[1]["id"] = "arc-a"
        claims[0]["id"] = "claim-a"
        claims[0].pop("event_id")
        claims[0]["arc_id"] = "arc-a"
        claims[0]["evidence_ids"] = [target_evidence]
        service.apply_draft(_run_and_draft(service, candidate))
        assert next(arc for arc in service.arcs() if arc.id == "arc-a") == pinned
        assert service.events(arc_id="arc-a") == pinned_events
        assert (
            tuple(claim for event in pinned_events for claim in service.claims(event_id=event.id))
            == pinned_claims
        )
        assert service.edits("arc-a") == pinned_edits
        assert pinned_state == (
            _rows(service._connection, "SELECT * FROM story_arcs WHERE arc_id='arc-a'"),
            _rows(
                service._connection,
                "SELECT * FROM story_arc_members WHERE arc_id='arc-a' ORDER BY ordinal",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_events WHERE event_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY event_id",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_event_members WHERE event_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY event_id,ordinal",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_claims WHERE arc_id='arc-a' OR event_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY claim_id",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_group_enrichment WHERE "
                "(target_kind='arc' AND target_id='arc-a') OR "
                "(target_kind='event' AND target_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a')) "
                "ORDER BY target_kind,target_id",
            ),
            _rows(
                service._connection,
                "SELECT * FROM story_edits WHERE target_id='arc-a' OR target_id IN "
                "(SELECT event_id FROM story_arc_members WHERE arc_id='arc-a') "
                "ORDER BY edit_id",
            ),
        )
        restored_pinned = next(arc for arc in service.arcs() if arc.id == "arc-a")
        assert set(restored_pinned.event_ids) == pinned_event_ids
        current_beats = {
            str(row[0])
            for row in service._connection.execute(
                "SELECT node_id FROM presentation_nodes WHERE level=3"
            )
        }
        expected_unpinned = current_beats - pinned_beats
        memberships = [
            str(row[0])
            for row in service._connection.execute(
                """SELECT member.beat_id FROM story_event_members member
                       JOIN story_events event ON event.event_id=member.event_id
                       LEFT JOIN story_arc_members arc_member
                         ON arc_member.event_id=event.event_id
                       LEFT JOIN story_arcs arc ON arc.arc_id=arc_member.arc_id
                       WHERE event.pinned=0 AND COALESCE(arc.pinned,0)=0"""
            )
        ]
        assert set(memberships) == expected_unpinned
        assert len(memberships) == len(expected_unpinned)
        remapped_arc = next(
            arc for arc in service.arcs() if arc.id != "arc-a" and arc.title == "Outcome"
        )
        assert remapped_arc.event_ids
        assert all(
            claim.id != "claim-a" for claim in service.claims() if claim.arc_id == remapped_arc.id
        )
        replacement_ids = (
            {event.id for event in service.events(include_hidden=True) if not event.pinned},
            {arc.id for arc in service.arcs(include_hidden=True) if not arc.pinned},
            {claim.id for claim in service.claims() if claim.id != "claim-a"},
        )
        service.apply_draft(_run_and_draft(service, candidate))
        assert replacement_ids == (
            {event.id for event in service.events(include_hidden=True) if not event.pinned},
            {arc.id for arc in service.arcs(include_hidden=True) if not arc.pinned},
            {claim.id for claim in service.claims() if claim.id != "claim-a"},
        )


def test_ungrouped_fallback_requires_authoritative_order_and_reopens(tmp_path: Path) -> None:
    path: Path
    with _create(tmp_path) as project:
        path = project.path
        beats = [
            str(row[0])
            for row in project._require_open().execute(
                "SELECT node_id FROM presentation_nodes WHERE level=3 ORDER BY sort_key,node_id"
            )
        ]
        reversed_candidate: dict[str, object] = {
            "events": [],
            "arcs": [],
            "claims": [],
            "ungrouped_beat_ids": list(reversed(beats)),
        }
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, reversed_candidate))
        global_events = service.events(include_hidden=True)
        global_arcs = service.arcs(include_hidden=True)
        assert [event.beat_ids[0] for event in global_events] == beats
        assert [event.order for event in global_events] == list(range(len(global_events)))
        assert len(global_arcs) == 1 and global_arcs[0].order == 0
        assert global_arcs[0].event_ids == tuple(event.id for event in global_events)

        scoped = _scoped_candidate(project, (0,), suffix="-ungrouped-order")
        scoped_beats = scoped["selected_beat_ids"]
        assert isinstance(scoped_beats, list)
        scoped["events"] = []
        scoped["arcs"] = []
        scoped["claims"] = []
        scoped["ungrouped_beat_ids"] = list(reversed(scoped_beats))
        service.apply_draft(_run_and_draft(service, scoped))
        accepted = service.events(include_hidden=True)
        accepted_arcs = service.arcs(include_hidden=True)
        assert [event.beat_ids[0] for event in accepted] == beats
        assert tuple(event_id for arc in accepted_arcs for event_id in arc.event_ids) == tuple(
            event.id for event in accepted
        )

    with Project.open(path) as reopened:
        restored = reopened.organization_service()
        assert restored.events(include_hidden=True) == accepted
        assert restored.arcs(include_hidden=True) == accepted_arcs


def test_global_changed_ids_mark_unreplayable_scalar_edits_for_review(tmp_path: Path) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_hidden("event", "event-a", True)

        service.apply_draft(_run_and_draft(service, _candidate(project, suffix="-changed")))

        assert {edit.status for edit in service.edits("event-a")} == {"needs_review"}
        assert all(event.id != "event-a" for event in service.events(include_hidden=True))


def test_mixed_ungrouped_fallbacks_are_gap_safe_and_non_interleaving_after_reopen(
    tmp_path: Path,
) -> None:
    path: Path
    accepted_events: tuple[StoryEvent, ...]
    accepted_arcs: tuple[StoryArc, ...]
    with _create(tmp_path) as project:
        path = project.path
        service = project.organization_service()
        candidate = _candidate(project)
        events = candidate["events"]
        assert isinstance(events, list) and isinstance(events[1], dict)
        second_beats = events[1]["beat_ids"]
        assert isinstance(second_beats, list) and len(second_beats) >= 2
        ungrouped = second_beats.pop(0)
        candidate["ungrouped_beat_ids"] = [ungrouped]

        service.apply_draft(_run_and_draft(service, candidate))

        positions = {
            str(row["node_id"]): index
            for index, row in enumerate(
                service._connection.execute(
                    "SELECT node_id FROM presentation_nodes WHERE level=3 ORDER BY sort_key,node_id"
                )
            )
        }
        accepted_events = service.events(include_hidden=True)
        accepted_arcs = service.arcs(include_hidden=True)
        event_bounds = {
            event.id: (
                min(positions[beat] for beat in event.beat_ids),
                max(positions[beat] for beat in event.beat_ids),
            )
            for event in accepted_events
        }
        assert [event_bounds[event.id][0] for event in accepted_events] == sorted(
            event_bounds[event.id][0] for event in accepted_events
        )
        fallback = next(event for event in accepted_events if event.beat_ids == (ungrouped,))
        opening = next(arc for arc in accepted_arcs if arc.id == "arc-a")
        assert fallback.id in opening.event_ids
        assert [event_bounds[event_id][0] for event_id in opening.event_ids] == sorted(
            event_bounds[event_id][0] for event_id in opening.event_ids
        )
        previous_end = -1
        for arc in accepted_arcs:
            start = min(event_bounds[event_id][0] for event_id in arc.event_ids)
            end = max(event_bounds[event_id][1] for event_id in arc.event_ids)
            assert start > previous_end
            previous_end = end

    with Project.open(path) as reopened:
        service = reopened.organization_service()
        assert service.events(include_hidden=True) == accepted_events
        assert service.arcs(include_hidden=True) == accepted_arcs


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
        explicit_fallback["claims"] = []
        draft = _run_and_draft(service, explicit_fallback)
        service.apply_draft(draft)
        assert any(
            event.beat_ids == (required_beat,) and event.origin == "deterministic"
            for event in service.events(include_hidden=True)
        )


def test_partial_scope_apply_preserves_outside_groups_claims_edits_and_is_idempotent(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_approval("event", "event-a", "approved")
        preserved_event = next(event for event in service.events() if event.id == "event-a")
        preserved_claim = service.claims(event_id="event-a")[0]
        preserved_edit = service.edits("event-a")[0]

        replacement = _scoped_candidate(project, (1,), suffix="-scope-b")
        service.apply_draft(_run_and_draft(service, replacement))
        ids = {event.id for event in service.events(include_hidden=True)}
        assert ids == {"event-a", "event-b", "event-b-scope-b", "event-c"}
        boundary = next(event for event in service.events() if event.id == "event-b")
        assert boundary.origin == "deterministic" and boundary.needs_review
        assert next(event for event in service.events() if event.id == "event-a") == preserved_event
        assert service.claims(event_id="event-a")[0] == preserved_claim
        assert service.edits("event-a")[0] == preserved_edit

        service.apply_draft(_run_and_draft(service, replacement))
        assert {event.id for event in service.events(include_hidden=True)} == ids
        assert len([event for event in service.events() if event.id == "event-b-scope-b"]) == 1


def test_sequential_partial_scopes_retain_prior_scope_and_do_not_create_global_fallbacks(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        scope_a = _scoped_candidate(project, (0,), suffix="-scope-a")
        scope_b = _scoped_candidate(project, (1,), suffix="-scope-b")
        service.apply_draft(_run_and_draft(service, scope_a))
        assert {event.id for event in service.events()} == {"event-a-scope-a"}
        service.set_hidden("event", "event-a-scope-a", True)
        service.set_approval("event", "event-a-scope-a", "approved")
        service.set_approval("event", "event-a-scope-a", "rejected")
        service.apply_draft(_run_and_draft(service, scope_b))
        assert {event.id for event in service.events(include_hidden=True)} == {
            "event-a-scope-a",
            "event-b-scope-b",
        }
        service.apply_draft(_run_and_draft(service, scope_a))
        events = service.events(include_hidden=True)
        assert {event.id for event in events} == {"event-a-scope-a", "event-b-scope-b"}
        reapplied = next(event for event in events if event.id == "event-a-scope-a")
        assert reapplied.hidden and reapplied.approval_state == "rejected"
        assert {edit.status for edit in service.edits(reapplied.id)} == {"applied"}
        assert all(event.origin != "deterministic" for event in events)


def test_scoped_apply_recomputes_global_chronology_after_reopen_and_rerun(
    tmp_path: Path,
) -> None:
    path: Path
    with _create(tmp_path) as project:
        path = project.path
        service = project.organization_service()
        early = _scoped_candidate(project, (0,), suffix="-chronology")
        late = _scoped_candidate(project, (1,), suffix="-chronology")

        def rename(candidate: dict[str, object], event_id: str, arc_id: str) -> None:
            events = candidate["events"]
            arcs = candidate["arcs"]
            assert isinstance(events, list) and isinstance(events[0], dict)
            assert isinstance(arcs, list) and isinstance(arcs[0], dict)
            events[0]["id"] = event_id
            arcs[0]["id"] = arc_id
            arcs[0]["event_ids"] = [event_id]

        rename(early, "z-early-event", "z-early-arc")
        rename(late, "a-late-event", "a-late-arc")
        service.apply_draft(_run_and_draft(service, early))
        service.apply_draft(_run_and_draft(service, late))
        assert [event.id for event in service.events()] == ["z-early-event", "a-late-event"]
        assert [arc.id for arc in service.arcs()] == ["z-early-arc", "a-late-arc"]
        service.apply_draft(_run_and_draft(service, early))
        assert [event.id for event in service.events()] == ["z-early-event", "a-late-event"]
        assert [arc.id for arc in service.arcs()] == ["z-early-arc", "a-late-arc"]

    with Project.open(path) as reopened:
        restored = reopened.organization_service()
        assert [event.id for event in restored.events()] == [
            "z-early-event",
            "a-late-event",
        ]
        assert [arc.id for arc in restored.arcs()] == ["z-early-arc", "a-late-arc"]


def test_partial_scope_requires_declared_coverage_and_preserves_pinned_intersection(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        bypass = _scoped_candidate(project, (0,), suffix="-global-bypass")
        bypass_run = service.create_run(
            provider_mode="local",
            model_profile="balanced",
            model_fingerprint=None,
            prompt_version="p1",
            output_schema_version="s1",
            generation="g-bypass",
        )
        with pytest.raises(ValueError, match="managed exclusively"):
            service.create_draft(bypass_run, "g-bypass", bypass)

        exact = _scoped_candidate(project, (0,), suffix="-outside")
        exact_covered = exact.pop("selected_beat_ids")
        assert isinstance(exact_covered, list)
        exact_events = exact["events"]
        assert isinstance(exact_events, list) and isinstance(exact_events[0], dict)
        assert isinstance(exact_events[0]["beat_ids"], list)
        scope_id = str(
            service._connection.execute(
                "SELECT parent_id FROM presentation_nodes WHERE node_id=?",
                (exact_covered[0],),
            ).fetchone()[0]
        )
        outside_beat = str(
            service._connection.execute(
                """SELECT beat.node_id FROM presentation_nodes beat
                   WHERE beat.level=3 AND beat.parent_id<>? ORDER BY beat.sort_key LIMIT 1""",
                (scope_id,),
            ).fetchone()[0]
        )
        exact_events[0]["beat_ids"].append(outside_beat)
        with pytest.raises(ValueError, match="outside selected scope"):
            service.create_scoped_draft(
                bypass_run,
                "g-bypass",
                exact,
                scope_ids=(scope_id,),
                covered_beat_ids=exact_covered,
            )
        with pytest.raises(ValueError, match="outside the selected scopes"):
            service.create_scoped_draft(
                bypass_run,
                "g-bypass",
                {**exact, "events": []},
                scope_ids=(scope_id,),
                covered_beat_ids=(*exact_covered, outside_beat),
            )

        incomplete = _scoped_candidate(project, (0,), suffix="-incomplete")
        selected = incomplete["selected_beat_ids"]
        events = incomplete["events"]
        assert isinstance(selected, list) and isinstance(events, list)
        assert isinstance(events[0], dict) and isinstance(events[0]["beat_ids"], list)
        missing = events[0]["beat_ids"].pop()
        assert missing in selected
        with pytest.raises(ValueError, match="required story beats"):
            _run_and_draft(service, incomplete, review=False)

        missing_scope = _scoped_candidate(project, (0,), suffix="-missing-scope")
        missing_selected = missing_scope["selected_beat_ids"]
        missing_events = missing_scope["events"]
        assert isinstance(missing_selected, list) and isinstance(missing_events, list)
        assert isinstance(missing_events[0], dict) and isinstance(
            missing_events[0]["beat_ids"], list
        )
        omitted = missing_selected.pop()
        missing_events[0]["beat_ids"].remove(omitted)
        with pytest.raises(ValueError, match="omit a scoped Level-3 beat"):
            _run_and_draft(service, missing_scope, review=False)

        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_pinned("event", "event-a", True)
        pinned = next(event for event in service.events() if event.id == "event-a")
        scoped = _scoped_candidate(project, (0, 1), suffix="-overlap")
        service.apply_draft(_run_and_draft(service, scoped))
        assert next(event for event in service.events() if event.id == "event-a") == pinned
        overlap = next(event for event in service.events() if event.id == "event-b-overlap")
        assert set(overlap.beat_ids).isdisjoint(pinned.beat_ids)


def test_scoped_exactness_excludes_durable_hidden_descendant(tmp_path: Path) -> None:
    with _create(tmp_path) as project:
        candidate = _scoped_candidate(project, (0,), suffix="-visible-only")
        events = candidate["events"]
        selected = candidate["selected_beat_ids"]
        assert isinstance(events, list) and isinstance(events[0], dict)
        assert isinstance(events[0]["beat_ids"], list) and isinstance(selected, list)
        hidden = str(events[0]["beat_ids"].pop())
        selected.remove(hidden)
        project.presentation_service().set_hidden(hidden, True)
        service = project.organization_service()
        draft = _run_and_draft(service, candidate)
        service.apply_draft(draft)
        events_after = service.events(include_hidden=True)
        assert len(events_after) == 1
        assert hidden not in events_after[0].beat_ids
        assert all(hidden not in event.beat_ids for event in events_after)

    with _create(tmp_path / "hidden-parent") as project:
        connection = project._require_open()
        parent_rows = connection.execute(
            "SELECT node_id,parent_id FROM presentation_nodes WHERE level=2 "
            "ORDER BY sort_key,node_id"
        ).fetchall()
        hidden_parent = str(parent_rows[0]["node_id"])
        scene_id = str(parent_rows[0]["parent_id"])
        visible_index = next(
            index
            for index, row in enumerate(parent_rows)
            if str(row["parent_id"]) == scene_id and str(row["node_id"]) != hidden_parent
        )
        hidden_children = {
            str(row[0])
            for row in connection.execute(
                "SELECT node_id FROM presentation_nodes WHERE parent_id=?", (hidden_parent,)
            )
        }
        project.presentation_service().set_hidden(hidden_parent, True)
        candidate = _scoped_candidate(project, (visible_index,), suffix="-hidden-parent")
        covered = candidate.pop("selected_beat_ids")
        assert isinstance(covered, list)
        service = project.organization_service()
        run = service.create_run(
            provider_mode="local",
            model_profile="balanced",
            model_fingerprint=None,
            prompt_version="p1",
            output_schema_version="s1",
            generation="g-hidden-parent",
        )
        with pytest.raises(ValueError, match="unknown covered Level-3 beat"):
            service.create_scoped_draft(
                run,
                "g-hidden-parent",
                candidate,
                scope_ids=(scene_id,),
                covered_beat_ids=(*covered, next(iter(hidden_children))),
            )
        draft = service.create_scoped_draft(
            run,
            "g-hidden-parent",
            candidate,
            scope_ids=(scene_id,),
            covered_beat_ids=covered,
        )
        _review_all(service, draft, candidate)
        service.apply_draft(draft)
        accepted = service.events(include_hidden=True)
        assert len(accepted) == 1
        assert hidden_children.isdisjoint(accepted[0].beat_ids)


def test_scoped_candidate_id_collisions_preserve_pinned_groups_without_orphans(
    tmp_path: Path,
) -> None:
    with _create(tmp_path / "event-collision") as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_pinned("event", "event-a", True)
        pinned = next(event for event in service.events() if event.id == "event-a")
        candidate = _scoped_candidate(project, (1,), suffix="-event-collision")
        covered = candidate["selected_beat_ids"]
        events = candidate["events"]
        arcs = candidate["arcs"]
        assert isinstance(covered, list) and isinstance(events, list) and isinstance(arcs, list)
        assert isinstance(events[0], dict) and isinstance(arcs[0], dict)
        events[0]["id"] = "event-a"
        arcs[0]["event_ids"] = ["event-a"]
        service.apply_draft(_run_and_draft(service, candidate))
        assert next(event for event in service.events() if event.id == "event-a") == pinned
        replacement = next(
            event
            for event in service.events(include_hidden=True)
            if event.id != "event-a" and set(event.beat_ids) == set(covered)
        )
        assert service._connection.execute(
            "SELECT 1 FROM story_arc_members WHERE event_id=?", (replacement.id,)
        ).fetchone()

    with _create(tmp_path / "arc-collision") as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        service.set_pinned("arc", "arc-a", True)
        pinned = next(arc for arc in service.arcs() if arc.id == "arc-a")
        candidate = _scoped_candidate(project, (2,), suffix="-arc-collision")
        covered = candidate["selected_beat_ids"]
        arcs = candidate["arcs"]
        assert isinstance(covered, list) and isinstance(arcs, list) and isinstance(arcs[0], dict)
        arcs[0]["id"] = "arc-a"
        service.apply_draft(_run_and_draft(service, candidate))
        assert next(arc for arc in service.arcs() if arc.id == "arc-a") == pinned
        replacement = next(
            event
            for event in service.events(include_hidden=True)
            if set(event.beat_ids) == set(covered)
        )
        attached = service._connection.execute(
            "SELECT arc_id FROM story_arc_members WHERE event_id=?", (replacement.id,)
        ).fetchone()
        assert attached is not None and str(attached[0]) != "arc-a"


def test_rejected_scoped_group_creates_only_selected_fallback(tmp_path: Path) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        candidate = _scoped_candidate(project, (0,), suffix="-rejected")
        covered = candidate["selected_beat_ids"]
        assert isinstance(covered, list)
        draft = _run_and_draft(service, candidate, review=False)
        service.review_draft_group(draft, "arc", "arc-a-rejected", "approved")
        service.review_draft_group(draft, "event", "event-a-rejected", "rejected")
        service.apply_draft(draft)
        events = service.events(include_hidden=True)
        assert len(events) == 1
        assert events[0].origin == "deterministic"
        assert set(events[0].beat_ids) == set(covered)
        total_beats = int(
            service._connection.execute(
                "SELECT COUNT(*) FROM presentation_nodes WHERE level=3"
            ).fetchone()[0]
        )
        assert len(events[0].beat_ids) < total_beats


def test_partial_boundary_intersection_trims_unpinned_group_without_losing_outside_edits(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        initial = _candidate(project)
        initial_arcs = initial["arcs"]
        initial_claims = initial["claims"]
        assert isinstance(initial_arcs, list) and isinstance(initial_arcs[0], dict)
        assert isinstance(initial_claims, list) and isinstance(initial_claims[0], dict)
        initial_arcs[0].update(
            {
                "importance": "major",
                "outcomes": ["The old arc interpretation changes."],
                "warnings": ["Old arc warning."],
            }
        )
        initial_claims.append(
            {
                "id": "claim-arc-boundary",
                "arc_id": "arc-a",
                "text": "The original arc spans the selected boundary.",
                "kind": "interpretation",
                "evidence_ids": initial_claims[0]["evidence_ids"],
            }
        )
        service.apply_draft(_run_and_draft(service, initial))
        service.set_hidden("arc", "arc-a", False)
        original = next(event for event in service.events() if event.id == "event-b")
        service.rename("event", original.id, "Old selected interpretation")
        service._connection.execute(
            "UPDATE story_events SET pinned=0 WHERE event_id=?", (original.id,)
        )
        container = str(
            service._connection.execute(
                "SELECT parent_id FROM presentation_nodes WHERE node_id=?",
                (original.beat_ids[0],),
            ).fetchone()[0]
        )
        selected = [
            str(row[0])
            for row in service._connection.execute(
                """SELECT node_id FROM presentation_nodes WHERE level=3 AND parent_id=?
                   ORDER BY sort_key,node_id""",
                (container,),
            )
        ]
        candidate = {
            "events": [
                {
                    "id": "event-middle",
                    "title": "Middle",
                    "summary": "The selected exact container.",
                    "beat_ids": selected,
                }
            ],
            "arcs": [
                {
                    "id": "arc-middle",
                    "title": "Middle",
                    "summary": "The selected middle arc.",
                    "event_ids": ["event-middle"],
                }
            ],
            "claims": [],
            "selected_beat_ids": selected,
        }
        service.apply_draft(_run_and_draft(service, candidate))
        trimmed = next(event for event in service.events() if event.id == original.id)
        assert trimmed.beat_ids == original.beat_ids[1:]
        assert trimmed.origin == "deterministic"
        assert trimmed.needs_review
        assert trimmed.title == "Technical boundary event"
        assert {edit.status for edit in service.edits(original.id)} == {"needs_review"}
        inserted = next(event for event in service.events() if event.id == "event-middle")
        assert inserted.beat_ids == tuple(selected)
        boundary_arc = next(arc for arc in service.arcs() if arc.id == "arc-a")
        assert boundary_arc.origin == "deterministic"
        assert boundary_arc.needs_review
        assert boundary_arc.title == "Technical boundary arc"
        assert {edit.status for edit in service.edits("arc-a")} == {"needs_review"}
        arc_claim = next(claim for claim in service.claims() if claim.id == "claim-arc-boundary")
        assert arc_claim.status == "needs_review"
        assert service.enrichments(target_kind="arc", target_id="arc-a") == ()
        ordinals = [
            int(row[0])
            for row in service._connection.execute(
                "SELECT ordinal FROM story_arc_members WHERE arc_id='arc-a' ORDER BY ordinal"
            )
        ]
        assert ordinals == list(range(len(ordinals)))


def test_enrichment_survives_draft_review_scoped_apply_and_reopen(tmp_path: Path) -> None:
    path: Path
    with _create(tmp_path) as project:
        path = project.path
        connection = project._require_open()
        candidate = _scoped_candidate(project, (0,), suffix="-enriched")
        event = candidate["events"][0]  # type: ignore[index]
        arc = candidate["arcs"][0]  # type: ignore[index]
        assert isinstance(event, dict) and isinstance(arc, dict)
        beats = event["beat_ids"]
        assert isinstance(beats, list)
        first = beats[0]
        payload = storage.decode_json(
            connection.execute(
                "SELECT payload_json FROM presentation_nodes WHERE node_id=?", (first,)
            ).fetchone()[0]
        )
        assert isinstance(payload, dict)
        payload["speaker"] = "Ava"
        connection.execute(
            "UPDATE presentation_nodes SET payload_json=? WHERE node_id=?",
            (storage.canonical_json(payload), first),
        )
        fact_id = str(
            connection.execute(
                "SELECT fact_id FROM presentation_facts WHERE node_id IN ("
                + ",".join("?" for _ in beats)
                + ") ORDER BY fact_id LIMIT 1",
                beats,
            ).fetchone()[0]
        )
        enrichment = {
            "characters": ["Ava"],
            "importance": "turning point",
            "outcomes": ["The route remains open."],
            "promoted_fact_ids": [fact_id],
            "warnings": ["Interpretation depends on the selected route."],
        }
        event.update(enrichment)
        arc.update(enrichment)
        service = project.organization_service()
        draft = _run_and_draft(service, candidate, review=False)
        assert {value.importance for value in service.draft_enrichments(draft)} == {"turning point"}
        _review_all(service, draft, candidate)
        service.apply_draft(draft)
        accepted = service.enrichments()
        assert len(accepted) == 2
        assert all(value.characters == ("Ava",) for value in accepted)
        assert all(value.promoted_fact_ids == (fact_id,) for value in accepted)
        assert project.authoritative_bytes()

        invented = _scoped_candidate(project, (0,), suffix="-invented-fact")
        invented_event = invented["events"][0]  # type: ignore[index]
        assert isinstance(invented_event, dict)
        invented_event["promoted_fact_ids"] = ["invented-fact"]
        with pytest.raises(ValueError, match="existing facts"):
            _run_and_draft(service, invented, review=False)

    with Project.open(path) as reopened:
        values = reopened.organization_service().enrichments()
        assert len(values) == 2
        assert {value.importance for value in values} == {"turning point"}


def test_enrichment_validation_uses_member_indexes_with_ten_thousand_noise_rows(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        connection = project._require_open()
        candidate = _scoped_candidate(project, (0,), suffix="-indexed-enrichment")
        event = candidate["events"][0]  # type: ignore[index]
        arc = candidate["arcs"][0]  # type: ignore[index]
        assert isinstance(event, dict) and isinstance(arc, dict)
        beats = event["beat_ids"]
        assert isinstance(beats, list)
        payload = storage.decode_json(
            connection.execute(
                "SELECT payload_json FROM presentation_nodes WHERE node_id=?", (beats[0],)
            ).fetchone()[0]
        )
        assert isinstance(payload, dict)
        payload["speaker"] = "Ava"
        connection.execute(
            "UPDATE presentation_nodes SET payload_json=? WHERE node_id=?",
            (storage.canonical_json(payload), beats[0]),
        )
        fact_id = str(
            connection.execute(
                "SELECT fact_id FROM presentation_facts WHERE node_id IN ("
                + ",".join("?" for _ in beats)
                + ") ORDER BY fact_id LIMIT 1",
                beats,
            ).fetchone()[0]
        )
        enrichment = {
            "characters": ["Ava"],
            "importance": "major",
            "outcomes": [],
            "promoted_fact_ids": [fact_id],
            "warnings": [],
        }
        event.update(enrichment)
        arc.update(enrichment)
        noise_count = 10_500
        with storage.transaction(connection):
            connection.executemany(
                "INSERT INTO presentation_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (
                        f"noise-beat-{index:05d}",
                        3,
                        None,
                        f"z{index:011d}",
                        "dialogue",
                        "Noise",
                        "noise.rpy",
                        index + 1,
                        index + 1,
                        0,
                        b"not-json-and-must-not-be-decoded",
                    )
                    for index in range(noise_count)
                ),
            )
            connection.executemany(
                "INSERT INTO presentation_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (
                        f"noise-fact-{index:05d}",
                        f"noise-beat-{index:05d}",
                        "gate",
                        "noise",
                        None,
                        "resolved",
                        "noise > 0",
                        "noise.rpy",
                        index + 1,
                        index + 1,
                        f"z{index:011d}",
                        b"not-json-and-must-not-be-decoded",
                    )
                    for index in range(noise_count)
                ),
            )
        started = time.perf_counter()
        draft = _run_and_draft(project.organization_service(), candidate, review=False)
        elapsed = time.perf_counter() - started
        assert draft
        assert elapsed < 2.0
        plan = connection.execute(
            """EXPLAIN QUERY PLAN SELECT fact_id FROM presentation_facts
               INDEXED BY presentation_facts_node_idx WHERE node_id IN (?,?)""",
            beats[:2],
        ).fetchall()
        assert any("presentation_facts_node_idx" in str(row[3]) for row in plan)


def test_partial_apply_failure_rolls_back_scope_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _create(tmp_path) as project:
        service = project.organization_service()
        service.apply_draft(_run_and_draft(service, _candidate(project)))
        before_arcs = service.arcs(include_hidden=True)
        before_events = service.events(include_hidden=True)
        draft = _run_and_draft(service, _scoped_candidate(project, (1,), suffix="-atomic-failure"))

        def fail_edges() -> None:
            raise RuntimeError("scoped edge derivation failed")

        monkeypatch.setattr(service, "_derive_event_edges", fail_edges)
        with pytest.raises(RuntimeError, match="scoped edge derivation failed"):
            service.apply_draft(draft)
        assert service.arcs(include_hidden=True) == before_arcs
        assert service.events(include_hidden=True) == before_events
        assert service.drafts(status="pending")[-1].id == draft


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


def test_quotient_edges_cross_ungrouped_chains_without_losing_semantics(
    tmp_path: Path,
) -> None:
    with _create(tmp_path) as project:
        connection = project._require_open()
        service = project.organization_service()
        beat_ids = [
            str(row[0])
            for row in connection.execute(
                """SELECT node_id FROM presentation_nodes WHERE level=3
                   ORDER BY sort_key,node_id LIMIT 9"""
            )
        ]
        assert len(beat_ids) == 9
        now = storage.utc_now()
        with storage.transaction(connection):
            connection.execute("DELETE FROM story_event_members")
            connection.execute("DELETE FROM story_events")
            connection.executemany(
                "INSERT INTO story_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (event_id, event_id, event_id, ordinal, "ai", 0, 0, "approved", 0, "g", now)
                    for ordinal, event_id in enumerate(("event-a", "event-b", "event-c", "event-d"))
                ),
            )
            connection.executemany(
                "INSERT INTO story_event_members VALUES (?,?,?)",
                (
                    ("event-a", beat_ids[0], 0),
                    ("event-a", beat_ids[1], 1),
                    ("event-b", beat_ids[5], 0),
                    ("event-c", beat_ids[6], 0),
                    ("event-d", beat_ids[7], 0),
                ),
            )
            connection.execute(
                "UPDATE presentation_nodes SET kind='ending' WHERE node_id=?", (beat_ids[7],)
            )
            connection.execute("DELETE FROM presentation_edges WHERE level=3")
            edges = (
                ("same-event", beat_ids[0], beat_ids[1], "fallthrough"),
                ("to-chain", beat_ids[1], beat_ids[2], "fallthrough"),
                ("condition", beat_ids[2], beat_ids[3], "condition"),
                ("to-b", beat_ids[3], beat_ids[5], "jump"),
                ("choice", beat_ids[2], beat_ids[4], "choice"),
                ("to-c", beat_ids[4], beat_ids[6], "fallthrough"),
                ("cycle", beat_ids[3], beat_ids[2], "fallthrough"),
                ("return", beat_ids[5], beat_ids[4], "return"),
                ("ending-chain", beat_ids[6], beat_ids[8], "fallthrough"),
                ("ending-target", beat_ids[8], beat_ids[7], "jump"),
            )
            connection.executemany(
                "INSERT INTO presentation_edges VALUES (?,3,?,?,?,?,?)",
                (
                    (
                        edge_id,
                        source_id,
                        target_id,
                        f"{ordinal:012d}",
                        kind,
                        storage.canonical_json({}),
                    )
                    for ordinal, (edge_id, source_id, target_id, kind) in enumerate(edges)
                ),
            )
            service._derive_event_edges()

        derived = {
            (edge.source_id, edge.target_id, edge.kind): set(edge.transition_ids)
            for edge in service.event_edges()
        }
        assert ("event-a", "event-a", "fallthrough") not in derived
        assert {"same-event", "to-chain", "condition", "to-b"} <= derived[
            ("event-a", "event-b", "condition")
        ]
        assert {"same-event", "to-chain", "choice", "to-c"} <= derived[
            ("event-a", "event-c", "choice")
        ]
        assert {"return", "to-c"} <= derived[("event-b", "event-c", "return")]
        assert {"ending-chain", "ending-target"} <= derived[
            ("event-c", "event-d", "ending")
        ]
        assert all(source != target for source, target, _kind in derived)


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

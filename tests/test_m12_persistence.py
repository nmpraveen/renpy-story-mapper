from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.m12_persistence import (
    REQUIRED_LIMIT_FIELDS,
    ROUTE_RESULTS_COLLECTION,
    AttemptStatus,
    RouteCacheIdentity,
    RouteCacheState,
    normalized_result_bytes,
    route_cache_identity,
)
from renpy_story_mapper.project import PayloadRecord, Project


def _hash(marker: str) -> str:
    return hashlib.sha256(marker.encode("utf-8")).hexdigest()


def _limits(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "version": "m12-deterministic-limits-v1",
        "expanded_states": 10_000,
        "retained_states": 5_000,
        "frontier_states": 2_000,
        "prefix_records": 8_000,
        "call_depth": 32,
        "repetition_per_transition": 64,
        "alternatives": 3,
        "accounting_units": 100_000,
    }
    value.update(changes)
    return value


def _request(target: str = "scene:ending") -> dict[str, object]:
    return {
        "schema": "m12-route-request-v1",
        "start": {"kind": "configured_entry", "node_id": "node:start"},
        "destination": {"kind": "human_scene", "id": target},
        "options": {"alternatives": 2},
    }


def _m10(marker: str = "one") -> dict[str, object]:
    return {
        "source_generation": f"generation-{marker}",
        "schema": "m10-canonical-graph-v1",
        "schema_version": 1,
        "canonical_hash": _hash(f"m10:{marker}"),
    }


def _m11(marker: str = "one") -> dict[str, object]:
    return {
        "schema": "m11-scene-model-v1",
        "schema_version": 1,
        "model_hash": _hash(f"m11:{marker}"),
    }


def _identity(
    *,
    target: str = "scene:ending",
    limit_changes: Mapping[str, object] | None = None,
    m10_marker: str = "one",
    m11_marker: str = "one",
    solver_version: str = "m12-solver-v1",
) -> RouteCacheIdentity:
    limits = _limits()
    if limit_changes is not None:
        limits.update(limit_changes)
    return route_cache_identity(
        _request(target),
        limits,
        m10_provenance=_m10(m10_marker),
        m11_provenance=_m11(m11_marker),
        solver_version=solver_version,
    )


def _result(marker: str = "one") -> dict[str, object]:
    return {
        "schema": "m12-route-result-v1",
        "semantic_status": "confirmed_route",
        "complete": True,
        "termination_reason": "target_reached",
        "route": {
            "scenes": ["scene:start", f"scene:{marker}"],
            "choices": [{"caption": "Take the path", "evidence_id": "evidence:1"}],
        },
    }


def test_m12_uses_scoped_schema_v6_generic_payload_storage() -> None:
    assert storage.SCHEMA_VERSION == 6
    assert ROUTE_RESULTS_COLLECTION in storage.PAYLOAD_COLLECTIONS


def test_identity_binds_request_all_deterministic_limits_versions_and_authority() -> None:
    baseline = _identity()
    assert baseline.cache_key == f"route:{baseline.identity_hash}"
    assert hashlib.sha256(baseline.normalized_bytes).hexdigest() == baseline.identity_hash
    assert set(REQUIRED_LIMIT_FIELDS) <= set(
        baseline.document["deterministic_limits"]  # type: ignore[arg-type]
    )

    changed = {
        _identity(target="scene:other").identity_hash,
        _identity(limit_changes={"version": "m12-deterministic-limits-v2"}).identity_hash,
        _identity(m10_marker="two").identity_hash,
        _identity(m11_marker="two").identity_hash,
        _identity(solver_version="m12-solver-v2").identity_hash,
    }
    changed.update(
        _identity(limit_changes={field: int(_limits()[field]) + 1}).identity_hash
        for field in REQUIRED_LIMIT_FIELDS
    )
    assert baseline.identity_hash not in changed
    assert len(changed) == len(REQUIRED_LIMIT_FIELDS) + 5


def test_incomplete_or_unversioned_limit_profiles_are_rejected() -> None:
    for field in REQUIRED_LIMIT_FIELDS:
        limits = _limits()
        del limits[field]
        with pytest.raises(ValueError, match="incomplete"):
            route_cache_identity(
                _request(),
                limits,
                m10_provenance=_m10(),
                m11_provenance=_m11(),
                solver_version="m12-solver-v1",
            )
    with pytest.raises(ValueError, match="version"):
        route_cache_identity(
            _request(),
            {**_limits(), "version": ""},
            m10_provenance=_m10(),
            m11_provenance=_m11(),
            solver_version="m12-solver-v1",
        )


def test_atomic_publication_reopens_as_byte_identical_exact_hit(tmp_path: Path) -> None:
    path = tmp_path / "route.rsmproj"
    identity = _identity()
    with Project.create(path) as project:
        publication = project.m12_persistence().publish_result(identity, _result())
        lookup = project.m12_persistence().lookup(identity)
        dependencies = project._require_open().execute(
            "SELECT COUNT(*) FROM payload_dependencies WHERE collection=?",
            (ROUTE_RESULTS_COLLECTION,),
        ).fetchone()

    assert publication.reused is False
    assert lookup.state is RouteCacheState.HIT
    assert lookup.normalized_bytes == publication.normalized_bytes
    assert lookup.result_hash == publication.result_hash
    assert dependencies is not None and int(dependencies[0]) == 0

    with Project.open(path) as reopened:
        replay = reopened.m12_persistence().lookup(identity)
        assert replay.state is RouteCacheState.HIT
        assert replay.normalized_bytes == publication.normalized_bytes


def test_exact_replay_reuses_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    with Project.create(tmp_path / "replay.rsmproj") as project:
        first = project.m12_persistence().publish_result(identity, _result())

        def unexpected_write(
            _records: Sequence[PayloadRecord],
            *,
            cancelled: object = None,
        ) -> None:
            del cancelled
            raise AssertionError("exact M12 replay attempted a write")

        monkeypatch.setattr(project, "_write_payloads_in_transaction", unexpected_write)
        second = project.m12_persistence().publish_result(identity, _result())

    assert second.reused is True
    assert second.result_hash == first.result_hash
    assert second.normalized_bytes == first.normalized_bytes


def test_same_identity_can_never_be_replaced_by_different_result_bytes(tmp_path: Path) -> None:
    identity = _identity()
    with Project.create(tmp_path / "conflict.rsmproj") as project:
        first = project.m12_persistence().publish_result(identity, _result("first"))
        with pytest.raises(storage.ProjectCorruptError, match="different normalized result"):
            project.m12_persistence().publish_result(identity, _result("second"))
        lookup = project.m12_persistence().lookup(identity)

    assert lookup.normalized_bytes == first.normalized_bytes


def test_forged_or_mutated_identity_is_rejected_before_cache_access(tmp_path: Path) -> None:
    identity = _identity()
    forged = RouteCacheIdentity(
        cache_key=identity.cache_key,
        identity_hash=_hash("forged"),
        normalized_bytes=identity.normalized_bytes,
        document=identity.document,
    )
    with (
        Project.create(tmp_path / "forged.rsmproj") as project,
        pytest.raises(ValueError, match="internally inconsistent"),
    ):
        project.m12_persistence().lookup(forged)


def test_stale_authority_and_provenance_miss_without_removing_valid_entry(tmp_path: Path) -> None:
    current = _identity()
    stale_m10 = _identity(m10_marker="two")
    stale_m11 = _identity(m11_marker="two")
    with Project.create(tmp_path / "stale.rsmproj") as project:
        project.m12_persistence().publish_result(current, _result())

        assert project.m12_persistence().lookup(stale_m10).state is RouteCacheState.MISS
        assert project.m12_persistence().lookup(stale_m11).state is RouteCacheState.MISS
        assert project.m12_persistence().lookup(current).state is RouteCacheState.HIT
        assert project.payload_keys(ROUTE_RESULTS_COLLECTION) == (current.cache_key,)


def test_projects_are_isolated_even_for_identical_cache_identity(tmp_path: Path) -> None:
    identity = _identity()
    with Project.create(tmp_path / "one.rsmproj") as first:
        first.m12_persistence().publish_result(identity, _result())
        assert first.m12_persistence().lookup(identity).state is RouteCacheState.HIT
    with Project.create(tmp_path / "two.rsmproj") as second:
        assert second.m12_persistence().lookup(identity).state is RouteCacheState.MISS


def test_prewrite_and_midwrite_cancellation_roll_back(tmp_path: Path) -> None:
    identity = _identity()
    with Project.create(tmp_path / "cancel.rsmproj") as project:
        with pytest.raises(storage.ProjectOperationCancelled):
            project.m12_persistence().publish_result(identity, _result(), cancelled=lambda: True)
        assert project.m12_persistence().lookup(identity).state is RouteCacheState.MISS

        calls = 0

        def cancel_after_insert() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        with pytest.raises(storage.ProjectOperationCancelled):
            project.m12_persistence().publish_result(
                identity,
                _result(),
                cancelled=cancel_after_insert,
            )
        assert calls == 3
        assert project.m12_persistence().lookup(identity).state is RouteCacheState.MISS


def test_cancelled_and_emergency_attempts_are_uncached_and_preserve_previous_result(
    tmp_path: Path,
) -> None:
    identity = _identity()
    with Project.create(tmp_path / "abort.rsmproj") as project:
        published = project.m12_persistence().publish_result(identity, _result())
        before = project.m12_persistence().lookup(identity)
        cancelled = project.m12_persistence().attempt_diagnostic(
            identity,
            AttemptStatus.CANCELLED,
            "user_cancelled",
            volatile_metrics={"elapsed_ms": 12},
        )
        emergency = project.m12_persistence().attempt_diagnostic(
            identity,
            AttemptStatus.EMERGENCY_ABORT,
            "wall_clock_guard",
            volatile_metrics={"duration_ms": 5000, "peak_memory_bytes": 999},
        )
        after = project.m12_persistence().lookup(identity)

    assert cancelled.cached is False
    assert emergency.cached is False
    assert emergency.to_dict()["volatile_metrics"] == {
        "duration_ms": 5000,
        "peak_memory_bytes": 999,
    }
    assert before.normalized_bytes == published.normalized_bytes == after.normalized_bytes


def test_normalized_result_bytes_exclude_all_volatile_observations() -> None:
    first = _result()
    first.update(
        {
            "elapsed_ms": 10,
            "finished_utc": "2026-07-15T10:00:00Z",
            "volatile_metrics": {"duration_ms": 10},
            "diagnostic": {
                "peak_memory_bytes": 100,
                "machine_memory_bytes": 200,
                "stable_counter": 3,
            },
        }
    )
    second = _result()
    second.update(
        {
            "elapsed_ms": 999,
            "finished_utc": "2099-01-01T00:00:00Z",
            "volatile_metrics": {"duration_ms": 999},
            "diagnostic": {
                "peak_memory_bytes": 999,
                "machine_memory_bytes": 999,
                "stable_counter": 3,
            },
        }
    )

    normalized = normalized_result_bytes(first)
    assert normalized == normalized_result_bytes(second)
    assert b"elapsed" not in normalized
    assert b"finished_utc" not in normalized
    assert b"peak_memory" not in normalized
    assert b"stable_counter" in normalized


def test_budget_incomplete_result_is_cacheable_but_cannot_be_a_negative_conclusion(
    tmp_path: Path,
) -> None:
    identity = _identity()
    incomplete = {
        "schema": "m12-route-result-v1",
        "semantic_status": "best_known_route",
        "complete": False,
        "termination_reason": "expanded_states",
        "route": {"scenes": ["scene:start"]},
    }
    with Project.create(tmp_path / "budget.rsmproj") as project:
        publication = project.m12_persistence().publish_result(identity, incomplete)
        assert project.m12_persistence().lookup(identity).normalized_bytes == (
            publication.normalized_bytes
        )

    with pytest.raises(ValueError, match="negative route conclusions"):
        normalized_result_bytes(
            {
                **incomplete,
                "semantic_status": "state_infeasible",
            }
        )
    with pytest.raises(ValueError, match="not cacheable"):
        normalized_result_bytes(
            {
                **incomplete,
                "semantic_status": "emergency_wall_clock_abort",
            }
        )


def test_core_route_result_shape_is_accepted_with_conservative_status_invariants(
    tmp_path: Path,
) -> None:
    confirmed = {
        "schema": "m12-route-result-v1",
        "status": "confirmed_route",
        "exhaustive": False,
        "closed_world": False,
        "budget_usage": {
            "expanded_states": 8,
            "limiting_dimension": None,
        },
        "route": {"scenes": ["scene:start", "scene:ending"]},
    }
    incomplete = {
        **confirmed,
        "status": "incomplete",
        "budget_usage": {
            "expanded_states": 10_000,
            "limiting_dimension": "expanded_states",
        },
    }
    negative = {
        **confirmed,
        "status": "no_route_in_resolved_static_graph",
        "exhaustive": True,
        "closed_world": True,
    }
    with Project.create(tmp_path / "core-shape.rsmproj") as project:
        confirmed_identity = _identity(target="scene:confirmed")
        incomplete_identity = _identity(target="scene:incomplete")
        negative_identity = _identity(target="scene:negative")
        project.m12_persistence().publish_result(confirmed_identity, confirmed)
        project.m12_persistence().publish_result(incomplete_identity, incomplete)
        project.m12_persistence().publish_result(negative_identity, negative)
        assert project.m12_persistence().lookup(confirmed_identity).state is RouteCacheState.HIT
        assert project.m12_persistence().lookup(incomplete_identity).state is RouteCacheState.HIT
        assert project.m12_persistence().lookup(negative_identity).state is RouteCacheState.HIT

    with pytest.raises(ValueError, match="exhaustive evidence"):
        normalized_result_bytes({**negative, "exhaustive": False})
    with pytest.raises(ValueError, match="closed-world evidence"):
        normalized_result_bytes({**negative, "closed_world": False})
    with pytest.raises(ValueError, match="operational abort"):
        normalized_result_bytes(
            {
                **incomplete,
                "budget_usage": {"limiting_dimension": "wall_clock_timeout"},
            }
        )


def test_injected_write_failure_rolls_back_whole_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    with Project.create(tmp_path / "rollback.rsmproj") as project:
        original = project._write_payloads_in_transaction

        def fail_after_write(
            records: Sequence[PayloadRecord],
            *,
            cancelled: object = None,
        ) -> None:
            original(records, cancelled=cancelled)  # type: ignore[arg-type]
            raise RuntimeError("injected publication failure")

        monkeypatch.setattr(project, "_write_payloads_in_transaction", fail_after_write)
        with pytest.raises(RuntimeError, match="injected publication failure"):
            project.m12_persistence().publish_result(identity, _result())
        assert project.m12_persistence().lookup(identity).state is RouteCacheState.MISS


def test_corrupt_payload_is_unavailable_and_never_silently_replaced(tmp_path: Path) -> None:
    identity = _identity()
    with Project.create(tmp_path / "corrupt.rsmproj") as project:
        project.m12_persistence().publish_result(identity, _result())
        project._require_open().execute(
            """UPDATE payloads SET payload_json=?
               WHERE collection=? AND record_key=?""",
            (b"{}", ROUTE_RESULTS_COLLECTION, identity.cache_key),
        )
        lookup = project.m12_persistence().lookup(identity)
        assert lookup.state is RouteCacheState.UNAVAILABLE
        assert lookup.reason == "corrupt_cache_entry"
        with pytest.raises(storage.ProjectCorruptError):
            project.m12_persistence().publish_result(identity, _result())
        row = project._require_open().execute(
            """SELECT payload_json FROM payloads
               WHERE collection=? AND record_key=?""",
            (ROUTE_RESULTS_COLLECTION, identity.cache_key),
        ).fetchone()
        assert row is not None and bytes(row[0]) == b"{}"


def test_well_formed_stale_envelope_is_a_safe_miss_and_cannot_be_overwritten(
    tmp_path: Path,
) -> None:
    identity = _identity()
    with Project.create(tmp_path / "stale-envelope.rsmproj") as project:
        project.m12_persistence().publish_result(identity, _result())
        raw = project.payload(ROUTE_RESULTS_COLLECTION, identity.cache_key)
        assert isinstance(raw, dict)
        raw["identity_hash"] = _hash("different-identity")
        payload = storage.canonical_json(raw)
        project._require_open().execute(
            """UPDATE payloads SET payload_json=?,payload_hash=?
               WHERE collection=? AND record_key=?""",
            (
                payload,
                storage.payload_digest(payload),
                ROUTE_RESULTS_COLLECTION,
                identity.cache_key,
            ),
        )

        lookup = project.m12_persistence().lookup(identity)
        assert lookup.state is RouteCacheState.MISS
        assert lookup.reason == "authority_or_request_mismatch"
        with pytest.raises(storage.ProjectCorruptError, match="different request identity"):
            project.m12_persistence().publish_result(identity, _result())

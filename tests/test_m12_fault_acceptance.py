from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.m12_model import (
    BudgetUsage,
    RouteBadge,
    RouteResult,
    TechnicalStatus,
)
from renpy_story_mapper.m12_persistence import (
    ROUTE_RESULTS_COLLECTION,
    RouteCacheState,
    normalized_result_bytes,
    route_cache_identity,
)
from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.project import PayloadRecord, Project, create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _identity(target: str = "scene:one"):
    return route_cache_identity(
        {"destination": target},
        {
            "version": "m12-limits-v1",
            "expanded_states": 100,
            "retained_states": 100,
            "frontier_states": 100,
            "prefix_records": 100,
            "call_depth": 10,
            "repetition_per_transition": 10,
            "alternatives": 3,
            "accounting_units": 1_000,
        },
        m10_provenance={
            "source_generation": "generation",
            "schema": "m10-canonical-graph-v1",
            "schema_version": 1,
            "canonical_hash": _hash("m10"),
        },
        m11_provenance={
            "schema": "m11-scene-model-v1",
            "schema_version": 1,
            "model_hash": _hash("m11"),
        },
        solver_version="m12-static-solver-v1",
    )


def _result(marker: str = "one") -> dict[str, object]:
    return {
        "schema": "m12-route-result-v1",
        "status": "confirmed",
        "complete": True,
        "exhaustive": True,
        "closed_world": True,
        "termination_reason": "exhaustive",
        "recommended": {"scene_ids": [f"scene:{marker}"]},
        "budget_usage": {"expanded_states": 1, "limiting_dimension": None},
    }


def _project(tmp_path: Path):
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "routes.rsmproj", source)


def test_prepublication_and_midpublication_cancellation_leave_no_cache(tmp_path: Path) -> None:
    first = _identity("scene:before")
    second = _identity("scene:mid")
    with Project.create(tmp_path / "cancel.rsmproj") as project:
        with pytest.raises(storage.ProjectOperationCancelled):
            project.m12_persistence().publish_result(first, _result(), cancelled=lambda: True)

        calls = 0

        def cancel_during_publication() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 2

        with pytest.raises(storage.ProjectOperationCancelled):
            project.m12_persistence().publish_result(
                second,
                _result("mid"),
                cancelled=cancel_during_publication,
            )
        assert project.m12_persistence().lookup(first).state is RouteCacheState.MISS
        assert project.m12_persistence().lookup(second).state is RouteCacheState.MISS


def test_injected_write_failure_rolls_back_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = _identity()
    with Project.create(tmp_path / "failure.rsmproj") as project:
        original = project._write_payloads_in_transaction

        def fail_after_write(records: Sequence[PayloadRecord], *, cancelled: object = None) -> None:
            original(records, cancelled=cancelled)  # type: ignore[arg-type]
            raise RuntimeError("injected M12 write fault")

        monkeypatch.setattr(project, "_write_payloads_in_transaction", fail_after_write)
        with pytest.raises(RuntimeError, match="injected M12 write fault"):
            project.m12_persistence().publish_result(identity, _result())
        assert project.m12_persistence().lookup(identity).state is RouteCacheState.MISS


def test_emergency_abort_is_uncached_and_preserves_prior_valid_cache(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with project:
        service = M12RouteService(project)
        nodes = [
            item
            for item in service.destinations(limit=50)["nodes"]
            if item["kind"] == "generic_scene"
        ]
        assert len(nodes) >= 2
        valid = service.prepare(str(nodes[0]["kind"]), str(nodes[0]["target_id"]))
        aborted = service.prepare(str(nodes[1]["kind"]), str(nodes[1]["target_id"]))
        first = service.solve(valid)
        prior = service.lookup(valid)
        outcome = service.solve(aborted, emergency_seconds=1e-12)

        assert first.result is not None
        assert outcome.result is None and outcome.diagnostic is not None
        assert outcome.diagnostic.status.value == "emergency_abort"
        assert service.lookup(aborted).state is RouteCacheState.MISS
        after = service.lookup(valid)
        assert after.state is RouteCacheState.HIT
        assert after.normalized_bytes == prior.normalized_bytes


def test_corrupt_cache_is_isolated_from_other_exact_key(tmp_path: Path) -> None:
    corrupt = _identity("scene:corrupt")
    healthy = _identity("scene:healthy")
    with Project.create(tmp_path / "isolation.rsmproj") as project:
        project.m12_persistence().publish_result(corrupt, _result("corrupt"))
        project.m12_persistence().publish_result(healthy, _result("healthy"))
        project._require_open().execute(
            "UPDATE payloads SET payload_json=? WHERE collection=? AND record_key=?",
            (b"{}", ROUTE_RESULTS_COLLECTION, corrupt.cache_key),
        )
        assert project.m12_persistence().lookup(corrupt).state is RouteCacheState.UNAVAILABLE
        healthy_lookup = project.m12_persistence().lookup(healthy)
        assert healthy_lookup.state is RouteCacheState.HIT
        assert healthy_lookup.result == _result("healthy")


def test_stale_cache_is_safe_miss_and_does_not_remove_other_entry(tmp_path: Path) -> None:
    stale = _identity("scene:stale")
    healthy = _identity("scene:healthy")
    with Project.create(tmp_path / "stale.rsmproj") as project:
        project.m12_persistence().publish_result(stale, _result("stale"))
        project.m12_persistence().publish_result(healthy, _result("healthy"))
        raw = project.payload(ROUTE_RESULTS_COLLECTION, stale.cache_key)
        assert isinstance(raw, dict)
        raw["identity_hash"] = _hash("different")
        payload = storage.canonical_json(raw)
        project._require_open().execute(
            "UPDATE payloads SET payload_json=?, payload_hash=? "
            "WHERE collection=? AND record_key=?",
            (
                payload,
                storage.payload_digest(payload),
                ROUTE_RESULTS_COLLECTION,
                stale.cache_key,
            ),
        )
        lookup = project.m12_persistence().lookup(stale)
        assert lookup.state is RouteCacheState.MISS
        assert lookup.reason == "authority_or_request_mismatch"
        assert project.m12_persistence().lookup(healthy).state is RouteCacheState.HIT


def test_deterministic_bound_can_never_construct_negative_conclusion() -> None:
    usage = BudgetUsage(10, 10, 10, 10, 10, "expanded_states")
    with pytest.raises(ValueError, match="negative conclusions"):
        RouteResult(
            "request",
            TechnicalStatus.NO_STATIC_ROUTE,
            RouteBadge.NO_PROVEN,
            None,
            (),
            False,
            "limit:expanded_states",
            False,
            True,
            usage,
            None,
            (),
        )
    incomplete = RouteResult(
        "request",
        TechnicalStatus.INCOMPLETE,
        RouteBadge.NO_PROVEN,
        None,
        (),
        False,
        "limit:expanded_states",
        False,
        False,
        usage,
        None,
        (),
    )
    assert incomplete.status is TechnicalStatus.INCOMPLETE


def test_dynamic_transfer_withholds_no_route_on_real_static_fixture(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with project:
        service = M12RouteService(project)
        destination = next(
            item
            for item in service.destinations(query="Sealed Room", limit=50)["nodes"]
            if item["kind"] == "generic_scene"
        )
        outcome = service.solve(
            service.prepare(str(destination["kind"]), str(destination["target_id"]))
        )
        assert outcome.result is not None
        assert outcome.result["status"] not in {
            "state_infeasible",
            "no_route_in_resolved_static_graph",
        }
        assert outcome.result["closed_world"] is False


def test_normalized_bytes_strip_nested_volatile_machine_observations() -> None:
    baseline = _result()
    noisy: dict[str, object] = {
        **baseline,
        "timestamp": "volatile",
        "duration_ms": 99,
        "diagnostics": {
            "machine_memory_bytes": 1_000,
            "nested": [{"elapsed_seconds": 2}, {"stable": "kept"}],
        },
    }
    expected: dict[str, object] = {
        **baseline,
        "diagnostics": {"nested": [{}, {"stable": "kept"}]},
    }
    assert normalized_result_bytes(noisy) == normalized_result_bytes(expected)

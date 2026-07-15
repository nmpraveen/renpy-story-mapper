from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.canonical_graph_contract import CANONICAL_GRAPH_SCHEMA
from renpy_story_mapper.m11_persistence import (
    ANALYSIS_STATE_COLLECTION,
    ANALYSIS_STATE_KEY,
    CORRECTIONS_COLLECTION,
    M11_PHASES,
    PHASE_RESULTS_COLLECTION,
    CanonicalBinding,
    M11Availability,
    M11Persistence,
    M11PreconditionError,
    Publication,
    phase_input_hash,
    phase_result_key,
)
from renpy_story_mapper.project import PayloadRecord, Project


def _canonical(generation: str, marker: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "schema": CANONICAL_GRAPH_SCHEMA,
        "source_generation": generation,
        "origin_generations": {"m10": generation},
        "nodes": [{"id": f"node-{marker}"}],
        "edges": [],
        "regions": [],
        "facts": [],
        "evidence": [],
        "proofs": [],
    }


def _input_hash(canonical: Mapping[str, object], phase: str) -> str:
    return phase_input_hash(
        {
            "phase": phase,
            "source_generation": canonical["source_generation"],
            "node_id": canonical["nodes"],
            "rule_version": "m11-test-v1",
        }
    )


def _result(canonical: Mapping[str, object], phase: str) -> dict[str, object]:
    node_marker = phase_input_hash({"nodes": canonical["nodes"]})[:12]
    return {
        "schema": f"m11-{phase}-test-v1",
        "member_ids": [f"{canonical['source_generation']}:{node_marker}:{phase}"],
    }


def _checkpoint_all(
    persistence: M11Persistence,
    canonical: Mapping[str, object],
) -> tuple[str, dict[str, str]]:
    working_hash: str | None = None
    phase_hashes: dict[str, str] = {}
    for phase in M11_PHASES:
        checkpoint = persistence.checkpoint_phase(
            canonical,
            phase,
            _input_hash(canonical, phase),
            _result(canonical, phase),
            expected_working_hash=working_hash,
        )
        working_hash = checkpoint.working_hash
        phase_hashes[phase] = checkpoint.result_hash
    assert working_hash is not None
    return working_hash, phase_hashes


def _publish_all(
    persistence: M11Persistence,
    canonical: Mapping[str, object],
) -> Publication:
    working_hash, phase_hashes = _checkpoint_all(persistence, canonical)
    return persistence.publish(
        canonical,
        expected_working_hash=working_hash,
        expected_phase_hashes=phase_hashes,
    )


def test_collections_use_schema_v6_generic_payload_storage() -> None:
    assert storage.SCHEMA_VERSION == 6
    assert M11_PHASES == (
        "story_atoms",
        "scene_boundaries",
        "scene_assembly",
        "scene_presentation",
    )
    assert {
        PHASE_RESULTS_COLLECTION,
        ANALYSIS_STATE_COLLECTION,
        CORRECTIONS_COLLECTION,
    } <= storage.PAYLOAD_COLLECTIONS


def test_phase_checkpoint_and_working_state_are_one_provenance_bound_transaction(
    tmp_path: Path,
) -> None:
    canonical = _canonical("generation-1", "one")
    input_hash = _input_hash(canonical, M11_PHASES[0])
    with Project.create(tmp_path / "checkpoint.rsmproj") as project:
        checkpoint = project.m11_persistence().checkpoint_phase(
            canonical,
            M11_PHASES[0],
            input_hash,
            _result(canonical, M11_PHASES[0]),
        )
        envelope = project.payload(PHASE_RESULTS_COLLECTION, checkpoint.record_key)
        state = project.payload(ANALYSIS_STATE_COLLECTION, ANALYSIS_STATE_KEY)
        dependencies = project._require_open().execute(
            """SELECT COUNT(*) FROM payload_dependencies
               WHERE collection IN (?,?,?)""",
            (PHASE_RESULTS_COLLECTION, ANALYSIS_STATE_COLLECTION, CORRECTIONS_COLLECTION),
        ).fetchone()

    assert checkpoint.record_key == phase_result_key(M11_PHASES[0], input_hash)
    assert isinstance(envelope, dict)
    assert set(envelope) == {
        "schema",
        "phase",
        "input_hash",
        "source_generation",
        "canonical_schema",
        "canonical_hash",
        "result_hash",
        "result",
    }
    assert "canonical_graph" not in envelope
    assert isinstance(state, dict)
    assert state["published"] is None
    assert state["working"]["phases"][0]["record_key"] == checkpoint.record_key
    assert dependencies is not None and int(dependencies[0]) == 0


def test_phase_checkpoint_rolls_back_result_when_state_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _canonical("generation-1", "rollback")
    with Project.create(tmp_path / "checkpoint-rollback.rsmproj") as project:
        persistence = project.m11_persistence()
        original = project._write_payloads_in_transaction

        def fail_after_first(
            records: Sequence[PayloadRecord],
            *,
            cancelled: Callable[[], bool] | None = None,
        ) -> None:
            original(records[:1], cancelled=cancelled)
            raise RuntimeError("injected state failure")

        monkeypatch.setattr(project, "_write_payloads_in_transaction", fail_after_first)
        with pytest.raises(RuntimeError, match="injected state failure"):
            persistence.checkpoint_phase(
                canonical,
                M11_PHASES[0],
                _input_hash(canonical, M11_PHASES[0]),
                _result(canonical, M11_PHASES[0]),
            )

        assert project.payload_keys(PHASE_RESULTS_COLLECTION) == ()
        assert project.payload(ANALYSIS_STATE_COLLECTION, ANALYSIS_STATE_KEY) is None


def test_publication_checks_hashes_preserves_stale_then_prunes_atomically(
    tmp_path: Path,
) -> None:
    old = _canonical("generation-1", "old")
    current = _canonical("generation-2", "current")
    with Project.create(tmp_path / "publish.rsmproj") as project:
        persistence = project.m11_persistence()
        old_publication = _publish_all(persistence, old)
        working_hash, phase_hashes = _checkpoint_all(persistence, current)

        stale = persistence.select(current)
        assert stale.availability is M11Availability.UNAVAILABLE
        assert stale.model_hash == old_publication.model_hash
        assert stale.phase_results is None

        wrong_hashes = dict(phase_hashes)
        wrong_hashes[M11_PHASES[-1]] = "0" * 64
        with pytest.raises(M11PreconditionError, match="phase hash"):
            persistence.publish(
                current,
                expected_working_hash=working_hash,
                expected_phase_hashes=wrong_hashes,
            )
        assert persistence.select(current).availability is M11Availability.UNAVAILABLE

        publication = persistence.publish(
            current,
            expected_working_hash=working_hash,
            expected_phase_hashes=phase_hashes,
        )
        selected = persistence.select(current)

        assert publication.pruned_results == len(M11_PHASES)
        assert selected.availability is M11Availability.CURRENT_COMPLETE
        assert selected.model_hash == publication.model_hash
        assert tuple(selected.phase_results or {}) == M11_PHASES
        assert len(project.payload_keys(PHASE_RESULTS_COLLECTION)) == len(M11_PHASES)


def test_final_pointer_and_pruning_rollback_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _canonical("generation-1", "old")
    current = _canonical("generation-2", "new")
    with Project.create(tmp_path / "publish-rollback.rsmproj") as project:
        persistence = project.m11_persistence()
        old_publication = _publish_all(persistence, old)
        working_hash, phase_hashes = _checkpoint_all(persistence, current)

        def fail_prune(_binding: object) -> int:
            raise RuntimeError("injected prune failure")

        monkeypatch.setattr(persistence, "_prune_phase_results", fail_prune)
        with pytest.raises(RuntimeError, match="injected prune failure"):
            persistence.publish(
                current,
                expected_working_hash=working_hash,
                expected_phase_hashes=phase_hashes,
            )

        selected = persistence.select(current)
        assert selected.availability is M11Availability.UNAVAILABLE
        assert selected.model_hash == old_publication.model_hash
        assert selected.phase_results is None
        assert len(project.payload_keys(PHASE_RESULTS_COLLECTION)) == 2 * len(M11_PHASES)


def test_unchanged_complete_input_reuses_all_phases_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _canonical("generation-1", "unchanged")
    with Project.create(tmp_path / "unchanged.rsmproj") as project:
        persistence = project.m11_persistence()
        first = _publish_all(persistence, canonical)
        before = project._require_open().execute(
            """SELECT collection,record_key,payload_hash,updated_utc FROM payloads
               WHERE collection IN (?,?) ORDER BY collection,record_key""",
            (PHASE_RESULTS_COLLECTION, ANALYSIS_STATE_COLLECTION),
        ).fetchall()
        before_values = [tuple(row) for row in before]

        def unexpected_write(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("unchanged M11 input attempted a payload write")

        monkeypatch.setattr(project, "_write_payloads_in_transaction", unexpected_write)
        working_hash, phase_hashes = _checkpoint_all(persistence, canonical)
        second = persistence.publish(
            canonical,
            expected_working_hash=working_hash,
            expected_phase_hashes=phase_hashes,
        )
        after = project._require_open().execute(
            """SELECT collection,record_key,payload_hash,updated_utc FROM payloads
               WHERE collection IN (?,?) ORDER BY collection,record_key""",
            (PHASE_RESULTS_COLLECTION, ANALYSIS_STATE_COLLECTION),
        ).fetchall()

        assert all(
            persistence.checkpoint_phase(
                canonical,
                phase,
                _input_hash(canonical, phase),
                _result(canonical, phase),
            ).reused
            for phase in M11_PHASES
        )
        assert second.reused is True
        assert second.model_hash == first.model_hash
        assert [tuple(row) for row in after] == before_values


def test_tampered_phase_is_gated_unavailable_even_with_valid_outer_checksum(
    tmp_path: Path,
) -> None:
    canonical = _canonical("generation-1", "tamper")
    with Project.create(tmp_path / "tamper.rsmproj") as project:
        persistence = project.m11_persistence()
        _publish_all(persistence, canonical)
        record_key = phase_result_key(M11_PHASES[0], _input_hash(canonical, M11_PHASES[0]))
        row = project._require_open().execute(
            """SELECT payload_json FROM payloads
               WHERE collection=? AND record_key=?""",
            (PHASE_RESULTS_COLLECTION, record_key),
        ).fetchone()
        assert row is not None
        envelope = storage.decode_json(row[0])
        assert isinstance(envelope, dict)
        assert isinstance(envelope["result"], dict)
        envelope["result"]["member_ids"] = ["tampered"]
        payload = storage.canonical_json(envelope)
        project._require_open().execute(
            """UPDATE payloads SET payload_json=?,payload_hash=?
               WHERE collection=? AND record_key=?""",
            (
                payload,
                storage.payload_digest(payload),
                PHASE_RESULTS_COLLECTION,
                record_key,
            ),
        )

        selection = persistence.select(canonical)
        assert selection.availability is M11Availability.UNAVAILABLE
        assert selection.reason == "m11_published_result_invalid"


def test_small_current_publication_check_does_not_decode_phase_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _canonical("generation-1", "small-check")
    binding = CanonicalBinding.from_payload(canonical)
    with Project.create(tmp_path / "small-check.rsmproj") as project:
        persistence = project.m11_persistence()
        _publish_all(persistence, canonical)
        original_payload = project.payload

        def guarded_payload(collection: str, key: str) -> object | None:
            if collection == PHASE_RESULTS_COLLECTION:
                raise AssertionError("phase payload was decoded")
            return original_payload(collection, key)

        monkeypatch.setattr(project, "payload", guarded_payload)
        assert persistence.has_current_publication(
            source_generation=binding.source_generation,
            canonical_schema=binding.canonical_schema,
            canonical_hash=binding.canonical_hash,
        )


def test_small_current_publication_check_rejects_mismatched_binding(tmp_path: Path) -> None:
    canonical = _canonical("generation-1", "mismatch")
    binding = CanonicalBinding.from_payload(canonical)
    with Project.create(tmp_path / "small-mismatch.rsmproj") as project:
        persistence = project.m11_persistence()
        _publish_all(persistence, canonical)

        assert not persistence.has_current_publication(
            source_generation="generation-2",
            canonical_schema=binding.canonical_schema,
            canonical_hash=binding.canonical_hash,
        )


def test_stale_current_pairing_never_selects_working_or_mixes_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _canonical("same-generation", "first")
    changed = _canonical("same-generation", "changed")
    with Project.create(tmp_path / "stale.rsmproj") as project:
        persistence = project.m11_persistence()
        old_publication = _publish_all(persistence, first)
        _checkpoint_all(persistence, changed)

        def unexpected_load(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("stale phase results were decoded")

        monkeypatch.setattr(M11Persistence, "_load_complete_results", unexpected_load)

        selection = persistence.select(changed)
        assert selection.availability is M11Availability.UNAVAILABLE
        assert selection.model_hash == old_publication.model_hash
        assert selection.phase_results is None
        assert selection.canonical is not None
        assert selection.canonical.canonical_hash == CanonicalBinding.from_payload(
            first
        ).canonical_hash
        assert selection.canonical.canonical_hash != CanonicalBinding.from_payload(
            changed
        ).canonical_hash
        current = CanonicalBinding.from_payload(changed)
        assert (
            persistence.select_current(
                source_generation=current.source_generation,
                canonical_schema=current.canonical_schema,
                canonical_hash=current.canonical_hash,
            ).reason
            == "canonical_binding_mismatch"
        )
        first_marker = phase_input_hash({"nodes": first["nodes"]})[:12]
        assert all(
            payload["member_ids"][0].startswith(f"same-generation:{first_marker}:")
            for payload in (selection.phase_results or {}).values()
        )

    with Project.create(tmp_path / "unpublished.rsmproj") as project:
        persistence = project.m11_persistence()
        _checkpoint_all(persistence, changed)
        selection = persistence.select(changed)
        assert selection.availability is M11Availability.UNAVAILABLE
        assert selection.phase_results is None


def test_corrections_are_model_bound_hash_checked_and_dependency_free(tmp_path: Path) -> None:
    canonical = _canonical("generation-1", "corrections")
    changed = _canonical("generation-2", "changed")
    with Project.create(tmp_path / "corrections.rsmproj") as project:
        persistence = project.m11_persistence()
        publication = _publish_all(persistence, canonical)
        first = persistence.save_corrections(
            canonical,
            {"operations": [{"kind": "split", "before_atom_id": "atom-2"}]},
        )
        assert first.record_key == publication.model_hash
        assert persistence.save_corrections(
            canonical,
            {"operations": [{"kind": "split", "before_atom_id": "atom-2"}]},
        ).reused
        replacement = {"operations": [{"kind": "merge", "boundary_id": "boundary-1"}]}
        persistence.save_corrections(
            canonical,
            replacement,
            expected_corrections_hash=first.corrections_hash,
        )

        assert persistence.corrections(canonical) == replacement
        assert persistence.corrections(changed) is None
        row = project._require_open().execute(
            """SELECT COUNT(*) FROM payload_dependencies
               WHERE collection=?""",
            (CORRECTIONS_COLLECTION,),
        ).fetchone()
        assert row is not None and int(row[0]) == 0


def test_phase_lookup_rejects_same_input_hash_under_different_canonical_pair(
    tmp_path: Path,
) -> None:
    canonical = _canonical("generation-1", "one")
    mismatched = _canonical("generation-1", "two")
    phase = M11_PHASES[0]
    input_hash = _input_hash(canonical, phase)
    with Project.create(tmp_path / "pairing.rsmproj") as project:
        persistence = project.m11_persistence()
        persistence.checkpoint_phase(canonical, phase, input_hash, _result(canonical, phase))
        with pytest.raises(storage.ProjectCorruptError, match="envelope"):
            persistence.phase_result(mismatched, phase, input_hash)

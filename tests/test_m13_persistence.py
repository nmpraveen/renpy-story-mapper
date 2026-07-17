from __future__ import annotations

from pathlib import Path

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.narrative.persistence import (
    ARTIFACTS_COLLECTION,
    ATTEMPTS_COLLECTION,
    BATCHES_COLLECTION,
    CACHE_COLLECTION,
    CLAIM_EDGES_COLLECTION,
    CLAIMS_COLLECTION,
    CONSENTS_COLLECTION,
    JOBS_COLLECTION,
    M13_PAYLOAD_COLLECTIONS,
    RECORD_COLLECTIONS,
    RUNS_COLLECTION,
    DebugRetention,
    LookupState,
    M13Persistence,
    RecordKind,
    cache_record_key,
    sanitized_error,
)
from renpy_story_mapper.project import Project


def _authority(seed: str = "a") -> dict[str, object]:
    return {
        "m10": {"graph_hash": seed * 64, "generation": 7, "schema": "m10-v1"},
        "m11": {"model_hash": seed * 64, "correction_hash": seed * 64},
        "m12": {"result_hashes": [seed * 64]},
    }


def _cache_identity(seed: str = "1") -> dict[str, object]:
    return {
        "schema": "m13-cache-identity-v1",
        "normalized_input_hash": seed * 64,
        "prompt_version": "scene-summary-v1",
        "output_schema_version": "scene-artifact-v1",
        "provider": {
            "adapter": "test-adapter",
            "adapter_version": "1",
            "requested_model": "runtime-request",
            "resolved_model": "runtime-resolution",
            "settings_hash": seed * 64,
        },
    }


def _publish(
    persistence: M13Persistence,
    *,
    suffix: str = "one",
    authority: dict[str, object] | None = None,
    cancelled: object | None = None,
) -> object:
    callback = cancelled if callable(cancelled) else None
    return persistence.publish_validated(
        job_id=f"scene-job:{suffix}",
        job={"status": "published", "input_revision": suffix},
        claims={
            f"claim:{suffix}:1": {
                "claim_class": "factual",
                "text": "A bounded fact.",
                "direct_support": ["evidence:1"],
            },
            f"claim:{suffix}:2": {
                "claim_class": "interpretive",
                "text": "A bounded interpretation.",
                "child_claim_ids": [f"claim:{suffix}:1"],
            },
        },
        claim_edges={
            f"edge:{suffix}:1": {
                "parent_claim_id": f"claim:{suffix}:2",
                "child_claim_id": f"claim:{suffix}:1",
            }
        },
        artifact_id=f"artifact:{suffix}",
        artifact={
            "title": "A deterministic artifact",
            "claim_ids": [f"claim:{suffix}:1", f"claim:{suffix}:2"],
            "rendering": {"summary": "A bounded summary."},
        },
        cache_identity=_cache_identity("1" if suffix == "one" else "2"),
        cache_metadata={"metrics": {"input_tokens": 12, "output_tokens": 8}},
        authority_binding=_authority() if authority is None else authority,
        cancelled=callback,
    )


def test_collections_reuse_schema_v6_and_records_reopen_independently(tmp_path: Path) -> None:
    expected = {
        RUNS_COLLECTION,
        CONSENTS_COLLECTION,
        JOBS_COLLECTION,
        ATTEMPTS_COLLECTION,
        BATCHES_COLLECTION,
        CLAIMS_COLLECTION,
        CLAIM_EDGES_COLLECTION,
        ARTIFACTS_COLLECTION,
        CACHE_COLLECTION,
    }
    assert storage.SCHEMA_VERSION == 6
    assert expected == M13_PAYLOAD_COLLECTIONS
    assert expected <= storage.PAYLOAD_COLLECTIONS

    path = tmp_path / "records.rsmproj"
    authority = _authority()
    with Project.create(path) as project:
        persistence = project.m13_persistence()
        assert isinstance(persistence, M13Persistence)
        persistence.put_run("run:1", {"status": "running"}, authority_binding=authority)
        persistence.put_consent(
            "consent:1",
            {"scope_hash": "c" * 64, "approved": True},
            authority_binding=authority,
        )
        persistence.put_job("job:2", {"status": "queued"}, authority_binding=authority)
        persistence.put_attempt(
            "attempt:1",
            {"status": "running", "job_id": "job:2"},
            authority_binding=authority,
        )
        persistence.put_batch(
            "batch:1",
            {"status": "packed", "logical_job_ids": ["job:2"]},
            authority_binding=authority,
        )
        persistence.put_claim(
            "claim:standalone",
            {"claim_class": "factual", "direct_support": ["evidence:1"]},
            authority_binding=authority,
        )
        persistence.put_claim_edge(
            "edge:standalone",
            {"parent_claim_id": "claim:p", "child_claim_id": "claim:c"},
            authority_binding=authority,
        )
        persistence.put_artifact(
            "artifact:standalone",
            {"title": "Independent"},
            authority_binding=authority,
        )
        persistence.put(
            RecordKind.CACHE,
            "cache:standalone",
            {"status": "independent"},
            authority_binding=authority,
        )

    with Project.open(path) as reopened:
        persistence = reopened.m13_persistence()
        expected_ids = {
            RecordKind.RUN: "run:1",
            RecordKind.CONSENT: "consent:1",
            RecordKind.JOB: "job:2",
            RecordKind.ATTEMPT: "attempt:1",
            RecordKind.BATCH: "batch:1",
            RecordKind.CLAIM: "claim:standalone",
            RecordKind.CLAIM_EDGE: "edge:standalone",
            RecordKind.ARTIFACT: "artifact:standalone",
            RecordKind.CACHE: "cache:standalone",
        }
        for kind, record_id in expected_ids.items():
            records = persistence.list_records(kind, authority_binding=authority)
            assert len(records) == 1
            assert records[0].record_id == record_id
            assert records[0].state is LookupState.HIT


def test_atomic_publication_exact_cache_replay_makes_zero_provider_calls(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.rsmproj"
    identity = _cache_identity()
    authority = _authority()
    with Project.create(path) as project:
        publication = _publish(project.m13_persistence())
        assert publication.cache_key == cache_record_key(identity)
        assert publication.reused_cache is False

    provider_calls = 0
    with Project.open(path) as reopened:
        persistence = reopened.m13_persistence()
        replay = persistence.lookup_cache(identity, authority_binding=authority)
        if replay.state is not LookupState.HIT:
            provider_calls += 1
        assert provider_calls == 0
        assert replay.reason == "exact_cache_hit"
        assert replay.entry is not None
        assert replay.artifact == {
            "claim_ids": ["claim:one:1", "claim:one:2"],
            "rendering": {"summary": "A bounded summary."},
            "title": "A deterministic artifact",
        }
        assert replay.entry["job_id"] == "scene-job:one"
        assert replay.entry["claim_ids"] == ["claim:one:1", "claim:one:2"]
        assert tuple(
            record.record_id
            for record in persistence.list_records(
                RecordKind.CLAIM,
                authority_binding=authority,
            )
        ) == ("claim:one:1", "claim:one:2")


def test_stale_binding_and_cache_identity_are_misses_without_deleting_last_good(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "stale.rsmproj") as project:
        persistence = project.m13_persistence()
        publication = _publish(persistence)

        stale_authority = persistence.lookup_cache(
            _cache_identity(),
            authority_binding=_authority("b"),
        )
        assert stale_authority.state is LookupState.STALE
        assert stale_authority.reason == "authority_binding_mismatch"

        changed_identity = persistence.lookup_cache(
            _cache_identity("9"),
            authority_binding=_authority(),
        )
        assert changed_identity.state is LookupState.MISS
        assert changed_identity.reason == "not_found"
        assert project.payload_keys(CACHE_COLLECTION) == (publication.cache_key,)


def test_cancellation_rolls_back_whole_publication_and_keeps_prior_cache(
    tmp_path: Path,
) -> None:
    class CancelDuringWrite:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> bool:
            self.calls += 1
            return self.calls >= 4

    with Project.create(tmp_path / "cancel.rsmproj") as project:
        persistence = project.m13_persistence()
        _publish(persistence)
        before_cache = project.payload(CACHE_COLLECTION, cache_record_key(_cache_identity()))
        before_artifact = project.payload(ARTIFACTS_COLLECTION, "artifact:one")

        with pytest.raises(storage.ProjectOperationCancelled):
            _publish(persistence, suffix="two", cancelled=CancelDuringWrite())

        assert (
            project.payload(CACHE_COLLECTION, cache_record_key(_cache_identity())) == before_cache
        )
        assert project.payload(ARTIFACTS_COLLECTION, "artifact:one") == before_artifact
        assert project.payload(ARTIFACTS_COLLECTION, "artifact:two") is None
        assert project.payload(CLAIMS_COLLECTION, "claim:two:1") is None
        assert project.payload(JOBS_COLLECTION, "scene-job:two") is None


def test_job_local_failure_preserves_last_good_and_immutable_conflicts_fail_closed(
    tmp_path: Path,
) -> None:
    with Project.create(tmp_path / "last-good.rsmproj") as project:
        persistence = project.m13_persistence()
        _publish(persistence)
        prior_artifact = project.payload(ARTIFACTS_COLLECTION, "artifact:one")

        persistence.record_unsuccessful_attempt(
            job_id="scene-job:one",
            attempt_id="attempt:cancelled",
            status="cancelled",
            error_code="cancelled",
            authority_binding=_authority(),
            metrics={"input_tokens": 4, "calls": 1},
        )
        job = persistence.lookup(
            RecordKind.JOB,
            "scene-job:one",
            authority_binding=_authority(),
        )
        assert job.payload is not None
        assert job.payload["status"] == "published"
        assert job.payload["latest_attempt_status"] == "cancelled"
        attempt = persistence.lookup(
            RecordKind.ATTEMPT,
            "attempt:cancelled",
            authority_binding=_authority(),
        )
        assert attempt.payload is not None
        assert attempt.payload["error"] == sanitized_error("cancelled")
        assert project.payload(ARTIFACTS_COLLECTION, "artifact:one") == prior_artifact
        assert persistence.lookup_cache(
            _cache_identity(), authority_binding=_authority()
        ).state is LookupState.HIT

        with pytest.raises(storage.ProjectCorruptError, match="different canonical bytes"):
            persistence.put_artifact(
                "artifact:one",
                {"title": "Conflicting bytes"},
                authority_binding=_authority(),
            )
        assert project.payload(ARTIFACTS_COLLECTION, "artifact:one") == prior_artifact


def test_corrupt_envelopes_are_unavailable_and_never_overwritten(tmp_path: Path) -> None:
    with Project.create(tmp_path / "corrupt.rsmproj") as project:
        persistence = project.m13_persistence()
        persistence.put_claim(
            "claim:corrupt",
            {"claim_class": "factual", "direct_support": ["evidence:1"]},
            authority_binding=_authority(),
        )
        raw = project.payload(CLAIMS_COLLECTION, "claim:corrupt")
        assert isinstance(raw, dict)
        damaged = dict(raw)
        damaged["payload_hash"] = "0" * 64
        encoded = storage.canonical_json(damaged)
        project._require_open().execute(
            """UPDATE payloads SET payload_json = ?, payload_hash = ?
               WHERE collection = ? AND record_key = ?""",
            (
                encoded,
                storage.payload_digest(encoded),
                CLAIMS_COLLECTION,
                "claim:corrupt",
            ),
        )

        lookup = persistence.lookup(
            RecordKind.CLAIM,
            "claim:corrupt",
            authority_binding=_authority(),
        )
        assert lookup.state is LookupState.UNAVAILABLE
        assert lookup.payload is None
        with pytest.raises(storage.ProjectCorruptError):
            persistence.put_claim(
                "claim:corrupt",
                {"claim_class": "factual", "direct_support": ["evidence:1"]},
                authority_binding=_authority(),
            )


def test_privacy_defaults_sanitize_errors_and_debug_is_explicit_and_bounded(
    tmp_path: Path,
) -> None:
    path = tmp_path / "privacy.rsmproj"
    with Project.create(path) as project:
        persistence = project.m13_persistence()
        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.put_attempt(
                "attempt:raw-prompt",
                {"raw_prompt": "private prompt body"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.put_attempt(
                "attempt:raw-response",
                {"raw_provider_response": "private provider output"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.put_attempt(
                "attempt:source-text",
                {"source_text": "complete private source text"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.put_attempt(
                "attempt:prompt",
                {"prompt": "complete rendered prompt"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.put_attempt(
                "attempt:provider-response",
                {"provider_response": "complete provider response"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="disabled"):
            persistence.put_attempt(
                "attempt:debug-disabled",
                {"status": "failed"},
                authority_binding=_authority(),
                debug_payload={"raw_prompt": "debug only"},
            )
        with pytest.raises(ValueError, match="absolute filesystem paths"):
            persistence.put_attempt(
                "attempt:path",
                {"status": "failed", "detail": "C:\\private\\story.rpy"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.put_attempt(
                "attempt:secret",
                {"status": "failed", "api_key": "do-not-store"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="sanitized error shape"):
            persistence.put_attempt(
                "attempt:error",
                {"status": "failed", "error": "provider said a private thing"},
                authority_binding=_authority(),
            )
        with pytest.raises(ValueError, match="byte limit"):
            persistence.put_attempt(
                "attempt:debug-large",
                {"status": "failed"},
                authority_binding=_authority(),
                debug_payload={"raw_prompt": "x" * 100},
                debug_retention=DebugRetention(development_enabled=True, max_bytes=32),
            )

        persistence.put_attempt(
            "attempt:safe",
            {
                "status": "failed",
                "error": sanitized_error("provider_timeout"),
                "sanitized_error_code": "provider_timeout",
            },
            authority_binding=_authority(),
        )
        persistence.put_attempt(
            "attempt:accepted",
            {"status": "accepted", "sanitized_error_code": None},
            authority_binding=_authority(),
        )
        with pytest.raises(ValueError, match="allowlisted"):
            persistence.put_attempt(
                "attempt:unsafe-code",
                {"status": "failed", "sanitized_error_code": "provider_stderr_dump"},
                authority_binding=_authority(),
            )
        persistence.put_attempt(
            "attempt:debug",
            {"status": "failed", "error": sanitized_error("invalid_output")},
            authority_binding=_authority(),
            debug_payload={"raw_prompt": "explicit bounded debug"},
            debug_retention=DebugRetention(development_enabled=True, max_bytes=128),
        )
        debug_raw = project.payload(ATTEMPTS_COLLECTION, "attempt:debug")
        assert isinstance(debug_raw, dict)
        assert debug_raw["debug"]

    database_bytes = path.read_bytes()
    assert b"private prompt body" not in database_bytes
    assert b"private provider output" not in database_bytes
    assert b"provider said a private thing" not in database_bytes
    assert b"complete private source text" not in database_bytes
    assert b"complete rendered prompt" not in database_bytes
    assert b"complete provider response" not in database_bytes


@pytest.mark.parametrize(
    "sensitive_key",
    (
        "openai_api_key",
        "providerAccessToken",
        "authorization-header",
        "complete_prompt_payload",
        "promptPayload",
        "raw_provider_response_blob",
        "source_text_packet",
    ),
)
def test_every_m13_record_write_rejects_compound_sensitive_keys_before_persisting(
    tmp_path: Path,
    sensitive_key: str,
) -> None:
    authority = _authority()
    with Project.create(tmp_path / f"privacy-{sensitive_key}.rsmproj") as project:
        persistence = project.m13_persistence()
        for kind in RecordKind:
            with pytest.raises(ValueError, match="sensitive or raw-content"):
                persistence.put(
                    kind,
                    f"record:{kind.value}",
                    {"nested": {sensitive_key: "must never be written"}},
                    authority_binding=authority,
                )
            assert project.payload_keys(RECORD_COLLECTIONS[kind]) == ()


def test_atomic_publication_and_debug_exception_share_privacy_validation(
    tmp_path: Path,
) -> None:
    authority = _authority()
    with Project.create(tmp_path / "privacy-publication.rsmproj") as project:
        persistence = project.m13_persistence()
        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.publish_validated(
                job_id="scene-job:private",
                job={"status": "published"},
                claims={},
                claim_edges={},
                artifact_id="artifact:private",
                artifact={"raw_provider_response_blob": "private provider output"},
                cache_identity=_cache_identity(),
                cache_metadata={},
                authority_binding=authority,
            )
        assert all(
            project.payload_keys(collection) == ()
            for collection in M13_PAYLOAD_COLLECTIONS
        )

        with pytest.raises(ValueError, match="sensitive or raw-content"):
            persistence.put_attempt(
                "attempt:credential-debug",
                {"status": "failed"},
                authority_binding=authority,
                debug_payload={"providerAccessToken": "credential"},
                debug_retention=DebugRetention(development_enabled=True),
            )
        assert project.payload_keys(ATTEMPTS_COLLECTION) == ()

        persistence.put_attempt(
            "attempt:safe-near-misses",
            {
                "secret_scene_id": "scene:1",
                "route_token_count": 2,
                "token_budget": 10,
                "prompt_version": "v1",
                "source_text_omitted_count": 3,
            },
            authority_binding=authority,
        )
def test_sanitized_error_rejects_unknown_codes() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        sanitized_error("provider_dumped_private_stderr")

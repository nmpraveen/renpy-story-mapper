"""Persistent schema-v6 adapter contracts for parallel M07 organization."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from renpy_story_mapper import storage
from renpy_story_mapper.m07_model import CheckpointStatus
from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    CodexMode,
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationConstraints,
    OrganizationGroup,
    OrganizationRequest,
    OrganizationStage,
    ProviderAttemptUsage,
    ProviderExecutionMetadata,
    ProviderState,
    ProviderStatus,
)
from renpy_story_mapper.organization.parallel import (
    CheckpointState,
    ParallelOrganizationScheduler,
    RouteScope,
    SchedulerConfig,
    ScopeEnvelope,
)
from renpy_story_mapper.organization.persistence import (
    PersistentCheckpointSink,
    decode_organization_result,
    encode_organization_result,
)
from renpy_story_mapper.project import Project
from renpy_story_mapper.route_map import RouteScope as DeterministicRouteScope


def _request(scope_id: str, *, run_id: str = "run-1") -> OrganizationRequest:
    return OrganizationRequest(
        run_id=run_id,
        chunk_id=f"chunk-{scope_id}",
        scope_id=scope_id,
        stage=OrganizationStage.EVENTS,
        payload={"beats": [{"id": "beat-1", "text": "A safe synthetic line."}]},
        constraints=OrganizationConstraints(
            ordered_member_ids=("beat-1",),
            required_member_ids=frozenset({"beat-1"}),
            evidence_ids=frozenset({"evidence-1"}),
            character_names=frozenset({"Ava"}),
        ),
        cloud_consent_run_id=run_id,
        model=M05_CLOUD_MODEL,
    )


def _result() -> OrganizationChunkResult:
    raw = {
        "stage": "events",
        "groups": [
            {
                "id": "group-1",
                "title": "Arrival",
                "summary": "A synthetic arrival.",
                "member_ids": ["beat-1"],
                "characters": ["Ava"],
                "importance": "major",
                "outcomes": ["Ava arrives."],
                "promoted_fact_ids": [],
                "claims": [{"text": "Ava arrives.", "evidence_ids": ["evidence-1"]}],
                "warnings": [],
            }
        ],
        "ungrouped_ids": [],
    }
    return OrganizationChunkResult(
        stage=OrganizationStage.EVENTS,
        groups=(
            OrganizationGroup(
                id="group-1",
                title="Arrival",
                summary="A synthetic arrival.",
                member_ids=("beat-1",),
                characters=("Ava",),
                importance="major",
                outcomes=("Ava arrives.",),
                promoted_fact_ids=(),
                claims=(InterpretationClaim("Ava arrives.", ("evidence-1",)),),
                warnings=(),
            ),
        ),
        ungrouped_ids=(),
        raw_normalized=raw,
        metadata=ProviderExecutionMetadata(
            provider_mode=CodexMode.CODEX_CHATGPT,
            model_identifier=M05_CLOUD_MODEL,
            cli_version="mock-1",
            elapsed_ms=12,
            input_hash="a" * 64,
            output_hash="b" * 64,
            input_tokens=101,
            output_tokens=23,
            context_window_tokens=200_000,
        ),
    )


def _topology(scope_id: str, ordinal: int = 0) -> DeterministicRouteScope:
    return DeterministicRouteScope(
        id=scope_id,
        ordinal=ordinal,
        lane_id="lane-spine",
        node_ids=(f"node-{ordinal}",),
        edge_ids=(),
        evidence_ids=("evidence-1",),
        input_hash=f"{ordinal + 1:064x}",
    )


class MockProvider:
    def __init__(self, result: OrganizationChunkResult) -> None:
        self.result = result

    def status(self) -> ProviderStatus:
        return ProviderStatus(ProviderState.READY, "mock", model_identifier=M05_CLOUD_MODEL)

    def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
        del request, progress
        assert not cancelled()
        return self.result

    def cancel(self) -> None:
        return


def _sink(
    project: Project,
    scope: RouteScope,
    topology: DeterministicRouteScope,
    *,
    generation: str = "generation-1",
) -> PersistentCheckpointSink:
    return PersistentCheckpointSink(
        project,
        generation=generation,
        deterministic_scopes=(topology,),
        organization_scopes=(scope,),
        config=SchedulerConfig(),
    )


def test_full_result_codec_is_deterministic_and_lossless() -> None:
    result = _result()
    encoded = encode_organization_result(result)
    decoded = decode_organization_result(encoded)
    assert decoded == result
    assert storage.canonical_json(encoded) == storage.canonical_json(
        encode_organization_result(decoded)
    )


def test_close_reopen_resume_and_scope_agnostic_cache_replay(tmp_path: Path) -> None:
    project_path = tmp_path / "parallel.rsmproj"
    result = _result()
    request = _request("scope-global")
    scope = RouteScope(0, request)
    calls = 0

    def factory(_scope: RouteScope) -> MockProvider:
        nonlocal calls
        calls += 1
        return MockProvider(result)

    with Project.create(project_path) as project:
        sink = _sink(project, scope, _topology("scope-global"))
        completed = ParallelOrganizationScheduler(factory, sink).run(
            (scope,), consent_run_id="run-1"
        )
        assert completed.progress.validated == 1
        assert sink.last_assembly is not None
        assert sink.last_assembly.generation == "generation-1"
        row = project._require_open().execute(
            "SELECT attempt_id,calls,input_tokens,output_tokens FROM m07_provider_attempts"
        ).fetchone()
        assert row is not None
        attempt_id = str(row["attempt_id"])
        assert re.fullmatch(r"attempt_[0-9a-f]{24}", attempt_id)
        assert tuple(row[key] for key in ("calls", "input_tokens", "output_tokens")) == (
            1,
            101,
            23,
        )
    assert calls == 1

    with Project.open(project_path) as project:
        resumed_request = replace(request, cloud_consent_run_id=None)
        resumed_scope = RouteScope(0, resumed_request)
        sink = _sink(project, resumed_scope, _topology("scope-global"))
        resumed = ParallelOrganizationScheduler(
            lambda _scope: (_ for _ in ()).throw(AssertionError("provider constructed")),
            sink,
        ).run((resumed_scope,), consent_run_id="")
        assert resumed.progress.calls == 0
        assert resumed.envelopes[0].result == result
        row = project._require_open().execute(
            "SELECT attempt_id FROM m07_provider_attempts"
        ).fetchone()
        assert row is not None and str(row["attempt_id"]) == attempt_id

    with Project.open(project_path) as project:
        scoped_request = replace(
            _request("scope-route"),
            run_id="run-2",
            chunk_id="chunk-route",
            cloud_consent_run_id=None,
        )
        scoped_scope = RouteScope(0, scoped_request)
        sink = _sink(project, scoped_scope, _topology("scope-route"), generation="generation-2")
        replay = ParallelOrganizationScheduler(
            lambda _scope: (_ for _ in ()).throw(AssertionError("provider constructed")),
            sink,
        ).run((scoped_scope,), consent_run_id="")
        assert replay.progress.calls == 0
        assert replay.envelopes[0].result == result
        checkpoint = project.m07_model_service().checkpoints()[0]
        assert checkpoint.status is CheckpointStatus.VALIDATED
        assert sink.last_assembly is not None
        assert sink.last_assembly.generation == "generation-2"


def test_terminal_transitions_and_partial_assembly_are_durable(tmp_path: Path) -> None:
    project_path = tmp_path / "states.rsmproj"
    result = _result()
    requests = tuple(_request(f"scope-{index}") for index in range(3))
    scopes = tuple(RouteScope(index, request) for index, request in enumerate(requests))
    topologies = tuple(_topology(scope.request.scope_id, scope.ordinal) for scope in scopes)

    with Project.create(project_path) as project:
        sink = PersistentCheckpointSink(
            project,
            generation="states",
            deterministic_scopes=topologies,
            organization_scopes=scopes,
            config=SchedulerConfig(),
        )
        terminal = (
            (CheckpointState.FALLBACK, result, "rate_limited"),
            (CheckpointState.FAILED, None, "provider_error"),
            (CheckpointState.CANCELLED, None, "cancelled"),
        )
        envelopes: list[ScopeEnvelope] = []
        for scope, (state, scope_result, error) in zip(scopes, terminal, strict=True):
            identity = project.m07_model_service().checkpoints()[scope.ordinal].input_hash
            sink.event(scope, CheckpointState.PENDING, identity)
            if state is not CheckpointState.CANCELLED:
                sink.event(scope, CheckpointState.CACHED_OR_IN_FLIGHT, identity)
                assert (
                    project.m07_model_service().checkpoints()[scope.ordinal].status
                    is CheckpointStatus.IN_FLIGHT
                )
            sink.event(scope, state, identity, error_code=error)
            envelope = ScopeEnvelope(
                scope.ordinal, scope.request.scope_id, state, identity, scope_result
            )
            sink.publish(envelope)
            envelopes.append(envelope)
        sink.assemble(envelopes)
        assert sink.last_assembly is not None
        assert sink.last_assembly.payload["partial"] is True

    with Project.open(project_path) as project:
        checkpoints = project.m07_model_service().checkpoints()
        assert tuple(item.status for item in checkpoints) == (
            CheckpointStatus.FALLBACK,
            CheckpointStatus.FAILED,
            CheckpointStatus.CANCELLED,
        )
        assert tuple(item.error_code for item in checkpoints) == (
            "rate_limited",
            "provider_error",
            "cancelled",
        )


def test_retry_continues_stable_attempt_ordinals_after_reopen(tmp_path: Path) -> None:
    project_path = tmp_path / "attempt-resume.rsmproj"
    request = _request("scope-retry")
    scope = RouteScope(0, request)
    topology = _topology("scope-retry")
    with Project.create(project_path) as project:
        sink = _sink(project, scope, topology, generation="attempt-generation")
        identity = project.m07_model_service().checkpoints()[0].input_hash
        sink.event(scope, CheckpointState.CACHED_OR_IN_FLIGHT, identity)
        sink.attempt(
            "scope-retry",
            ProviderAttemptUsage(1, 4, "cancelled", input_tokens=3, output_tokens=1),
        )
        sink.event(scope, CheckpointState.CANCELLED, identity, error_code="cancelled")
        sink.publish(ScopeEnvelope(0, "scope-retry", CheckpointState.CANCELLED, identity, None))

    with Project.open(project_path) as project:
        sink = _sink(project, scope, topology, generation="attempt-generation")
        identity = project.m07_model_service().checkpoints()[0].input_hash
        sink.event(scope, CheckpointState.CACHED_OR_IN_FLIGHT, identity)
        sink.attempt(
            "scope-retry",
            ProviderAttemptUsage(1, 5, "validated", input_tokens=5, output_tokens=2),
        )
        sink.event(scope, CheckpointState.FAILED, identity, error_code="provider_error")
        sink.publish(ScopeEnvelope(0, "scope-retry", CheckpointState.FAILED, identity, None))
        rows = project._require_open().execute(
            "SELECT attempt_id,ordinal FROM m07_provider_attempts ORDER BY ordinal"
        ).fetchall()
        assert [int(row["ordinal"]) for row in rows] == [0, 1]
        assert len({str(row["attempt_id"]) for row in rows}) == 2


def test_attempt_is_durable_before_any_terminal_event(tmp_path: Path) -> None:
    project_path = tmp_path / "attempt-immediate.rsmproj"
    request = _request("scope-incremental")
    scope = RouteScope(0, request)
    with Project.create(project_path) as project:
        sink = _sink(project, scope, _topology("scope-incremental"))
        sink.attempt(
            "scope-incremental",
            ProviderAttemptUsage(1, 7, "invalid", input_tokens=11, output_tokens=3),
        )
        row = project._require_open().execute(
            "SELECT outcome,calls,input_tokens,output_tokens FROM m07_provider_attempts"
        ).fetchone()
        assert row is not None
        assert tuple(row[key] for key in ("outcome", "calls", "input_tokens", "output_tokens")) == (
            "invalid",
            1,
            11,
            3,
        )

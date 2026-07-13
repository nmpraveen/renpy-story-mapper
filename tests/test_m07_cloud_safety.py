"""Adversarial contracts for M07 prompt partitioning and aggregate boundaries."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper.organization.chunking import partition_organization_request
from renpy_story_mapper.organization.contracts import (
    M05_CLOUD_MODEL,
    MAX_PROMPT_CHARS,
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationConstraints,
    OrganizationGroup,
    OrganizationRequest,
    OrganizationStage,
    ProviderAttemptUsage,
    organization_prompts_fit,
    serialize_organization_prompt,
    serialized_prompt_chars,
)
from renpy_story_mapper.organization.errors import OrganizationCancelledError
from renpy_story_mapper.organization.parallel import (
    BudgetPolicy,
    CheckpointState,
    InMemoryCheckpointSink,
    ParallelOrganizationScheduler,
    RouteScope,
    SchedulerConfig,
)
from renpy_story_mapper.organization.provider import CodexCliProvider


def _request_with_text(text: str) -> OrganizationRequest:
    return OrganizationRequest(
        run_id="run-1",
        chunk_id="chunk-1",
        scope_id="scope-1",
        stage=OrganizationStage.EVENTS,
        payload={"beats": [{"id": "node-1", "text": text}]},
        constraints=OrganizationConstraints(
            ordered_member_ids=("node-1",),
            required_member_ids=frozenset({"node-1"}),
        ),
        cloud_consent_run_id="run-1",
        model=M05_CLOUD_MODEL,
    )


@pytest.mark.parametrize("repair", [False, True])
def test_exactly_48000_serialized_characters_is_rejected(repair: bool) -> None:
    base = serialized_prompt_chars(_request_with_text(""), repair=repair)
    request = _request_with_text("x" * (MAX_PROMPT_CHARS - base))
    assert serialized_prompt_chars(request, repair=repair) == MAX_PROMPT_CHARS
    assert not organization_prompts_fit(request)
    with pytest.raises(ValueError, match="48,000"):
        CodexCliProvider._validate_prompt_limits(request)


def _fixture_route_request(*, repetitions: int = 1) -> OrganizationRequest:
    manifest = json.loads(
        Path("tests/fixtures/m07/manifest.json").read_text(encoding="utf-8")
    )
    source_evidence = manifest["evidence"]
    nodes: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    for index, item in enumerate(source_evidence * repetitions):
        node_id = f"node-{index:03d}"
        evidence_id = f"evidence-{index:03d}"
        nodes.append(
            {
                "id": node_id,
                "kind": "story",
                "text": item["text"] + (" quoted\\line\n雪" * 120),
                "evidence_ids": [evidence_id],
            }
        )
        evidence.append({"id": evidence_id, "path": item["path"], "text": item["text"]})
        if index:
            edges.append(
                {
                    "id": f"edge-{index:03d}",
                    "source": f"node-{index - 1:03d}",
                    "target": node_id,
                    "evidence_ids": [evidence_id],
                }
            )
    node_ids = tuple(str(item["id"]) for item in nodes)
    evidence_ids = frozenset(str(item["id"]) for item in evidence)
    return OrganizationRequest(
        run_id="run-1",
        chunk_id="chunk-route",
        scope_id="route-fixture",
        stage=OrganizationStage.EVENTS,
        payload={
            "route_scope_id": "route-fixture",
            "node_ids": list(node_ids),
            "edge_ids": [item["id"] for item in edges],
            "evidence_ids": sorted(evidence_ids),
            "fact_ids": [],
            "facts": [],
            "nodes": nodes,
            "edges": edges,
            "evidence": evidence,
        },
        constraints=OrganizationConstraints(
            ordered_member_ids=node_ids,
            required_member_ids=frozenset(node_ids),
            evidence_ids=evidence_ids,
            member_evidence_ids=tuple(
                (str(node["id"]), tuple(str(item) for item in node["evidence_ids"]))
                for node in nodes
            ),
        ),
        cloud_consent_run_id="run-1",
        model=M05_CLOUD_MODEL,
    )


def test_current_m07_fixture_route_is_partitioned_by_exact_normal_and_repair_sizes() -> None:
    request = _fixture_route_request(repetitions=2)
    assert not organization_prompts_fit(request)
    partitions = partition_organization_request(request)
    assert len(partitions) > 1
    assert all(organization_prompts_fit(part) for part in partitions)
    assert all(
        len(serialize_organization_prompt(part, repair=repair)) < MAX_PROMPT_CHARS
        for part in partitions
        for repair in (False, True)
    )
    assigned = tuple(
        member for part in partitions for member in part.constraints.ordered_member_ids
    )
    required = [
        member for part in partitions for member in part.constraints.required_member_ids
    ]
    assert assigned == request.constraints.ordered_member_ids
    assert len(required) == len(set(required)) == len(assigned)


def _result_for(request: OrganizationRequest) -> OrganizationChunkResult:
    cited_evidence = tuple(
        evidence_id
        for member_id, evidence_ids in request.constraints.member_evidence_ids
        if member_id in request.constraints.ordered_member_ids
        for evidence_id in evidence_ids
    )
    claims = (InterpretationClaim("Grounded partition.", cited_evidence),)
    group = OrganizationGroup(
        id="group",
        title="Partition",
        summary="Validated synthetic route partition.",
        member_ids=request.constraints.ordered_member_ids,
        characters=(),
        importance="supporting",
        outcomes=(),
        promoted_fact_ids=(),
        claims=claims,
        warnings=(),
    )
    raw = {
        "stage": "events",
        "groups": [
            {
                "id": group.id,
                "title": group.title,
                "summary": group.summary,
                "member_ids": list(group.member_ids),
                "characters": [],
                "importance": group.importance,
                "outcomes": [],
                "promoted_fact_ids": [],
                "claims": [
                    {"text": claims[0].text, "evidence_ids": list(cited_evidence)}
                ],
                "warnings": [],
            }
        ],
        "ungrouped_ids": [],
    }
    return OrganizationChunkResult(OrganizationStage.EVENTS, (group,), (), raw)


class GatedProvider:
    def __init__(self, scope: RouteScope) -> None:
        self.scope = scope
        self.gate: Callable[[bytes], bool] | None = None
        self.observer: Callable[[ProviderAttemptUsage], None] | None = None
        self.prompts: list[bytes] = []

    def set_attempt_gate(self, gate: Callable[[bytes], bool] | None) -> None:
        self.gate = gate

    def set_attempt_observer(
        self, observer: Callable[[ProviderAttemptUsage], None] | None
    ) -> None:
        self.observer = observer

    def set_maximum_output_bytes(self, maximum: int) -> None:
        assert maximum > 0

    def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
        del progress
        prompt = serialize_organization_prompt(request, repair=False).encode("utf-8")
        assert self.gate is not None
        if not self.gate(prompt):
            raise OrganizationCancelledError("budget")
        self.prompts.append(prompt)
        assert not cancelled()
        if self.observer is not None:
            self.observer(ProviderAttemptUsage(1, 1, "validated", 10, 2))
        return _result_for(request)

    def status(self) -> Any:
        raise AssertionError("not used")

    def cancel(self) -> None:
        return


def test_scheduler_partitions_oversized_scope_but_preserves_one_outer_checkpoint() -> None:
    request = _fixture_route_request(repetitions=2)
    providers: list[GatedProvider] = []

    def factory(scope: RouteScope) -> GatedProvider:
        provider = GatedProvider(scope)
        providers.append(provider)
        return provider

    sink = InMemoryCheckpointSink()
    result = ParallelOrganizationScheduler(factory, sink).run(
        (RouteScope(0, request),), consent_run_id="run-1"
    )
    assert result.progress.validated == 1
    assert len(result.envelopes) == 1
    merged = result.envelopes[0].result
    assert merged is not None
    assert tuple(member for group in merged.groups for member in group.member_ids) == (
        request.constraints.ordered_member_ids
    )
    assert all(len(prompt.decode("utf-8")) < MAX_PROMPT_CHARS for prompt in providers[0].prompts)


class RepairingProvider(GatedProvider):
    def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
        del progress, cancelled
        assert self.gate is not None
        for attempt, repair in ((1, False), (2, True)):
            prompt = serialize_organization_prompt(request, repair=repair).encode("utf-8")
            if not self.gate(prompt):
                raise OrganizationCancelledError("budget")
            self.prompts.append(prompt)
            if self.observer is not None:
                self.observer(ProviderAttemptUsage(attempt, 1, "invalid", 3, 1))
        return _result_for(request)


def test_hard_call_reservation_cannot_overshoot_on_repair() -> None:
    request = _request_with_text("safe")
    sink = InMemoryCheckpointSink()
    providers: list[RepairingProvider] = []

    def factory(scope: RouteScope) -> RepairingProvider:
        provider = RepairingProvider(scope)
        providers.append(provider)
        return provider

    result = ParallelOrganizationScheduler(
        factory,
        sink,
        SchedulerConfig(
            initial_workers=1,
            budget=BudgetPolicy(hard_calls=1, hard_tokens=1_000_000, hard_seconds=30),
        ),
    ).run((RouteScope(0, request, _result_for(request)),), consent_run_id="run-1")
    assert result.progress.calls == 1
    assert len(sink.attempts) == 1
    assert len(providers[0].prompts) == 1
    assert result.envelopes[0].state is CheckpointState.FALLBACK


def test_concurrent_attempt_reservations_never_overshoot_hard_calls() -> None:
    release = threading.Event()
    accepted = 0
    lock = threading.Lock()

    class BlockingProvider(GatedProvider):
        def organize(self, request: Any, progress: Any, cancelled: Any) -> OrganizationChunkResult:
            nonlocal accepted
            del progress, cancelled
            assert self.gate is not None
            prompt = serialize_organization_prompt(request, repair=False).encode("utf-8")
            if not self.gate(prompt):
                raise OrganizationCancelledError("budget")
            with lock:
                accepted += 1
            release.wait(1)
            if self.observer is not None:
                self.observer(ProviderAttemptUsage(1, 1, "validated", 2, 1))
            return _result_for(request)

    scopes = tuple(
        RouteScope(
            index,
            replace(
                _request_with_text("safe"),
                chunk_id=f"c-{index}",
                scope_id=f"s-{index}",
            ),
        )
        for index in range(12)
    )
    threading.Timer(0.05, release.set).start()
    result = ParallelOrganizationScheduler(
        lambda scope: BlockingProvider(scope),
        InMemoryCheckpointSink(),
        SchedulerConfig(
            initial_workers=8,
            budget=BudgetPolicy(hard_calls=3, hard_tokens=2_000_000, hard_seconds=30),
        ),
    ).run(scopes, consent_run_id="run-1")
    assert accepted == result.progress.calls == 3


def test_actual_usage_releases_conservative_token_reservations() -> None:
    scopes = tuple(
        RouteScope(
            index,
            replace(
                _request_with_text("safe"),
                chunk_id=f"release-{index}",
                scope_id=f"release-{index}",
            ),
        )
        for index in range(10)
    )
    result = ParallelOrganizationScheduler(
        lambda scope: GatedProvider(scope),
        InMemoryCheckpointSink(),
        SchedulerConfig(
            initial_workers=1,
            maximum_output_bytes_per_attempt=10_000,
            budget=BudgetPolicy(hard_calls=10, hard_tokens=50_000, hard_seconds=30),
        ),
    ).run(scopes, consent_run_id="run-1")
    assert result.progress.validated == 10
    assert result.progress.calls == 10
    assert result.progress.input_tokens + result.progress.output_tokens == 120


def test_provider_usage_above_admitted_ceiling_is_persisted_and_fails_closed() -> None:
    class ViolatingProvider(GatedProvider):
        def organize(
            self, request: Any, progress: Any, cancelled: Any
        ) -> OrganizationChunkResult:
            del progress, cancelled
            assert self.gate is not None
            prompt = serialize_organization_prompt(request, repair=False).encode("utf-8")
            assert self.gate(prompt)
            assert self.observer is not None
            self.observer(ProviderAttemptUsage(1, 1, "validated", 50_000, 1))
            return _result_for(request)

    request = _request_with_text("safe")
    sink = InMemoryCheckpointSink()
    result = ParallelOrganizationScheduler(
        lambda scope: ViolatingProvider(scope),
        sink,
        SchedulerConfig(
            initial_workers=1,
            maximum_output_bytes_per_attempt=1_000,
            budget=BudgetPolicy(hard_calls=1, hard_tokens=1_000_000, hard_seconds=30),
        ),
    ).run((RouteScope(0, request),), consent_run_id="run-1")

    assert result.envelopes[0].state is CheckpointState.FAILED
    assert result.progress.input_tokens == 50_000
    assert result.progress.output_tokens == 1
    assert sink.attempts == [
        ("scope-1", ProviderAttemptUsage(1, 1, "validated", 50_000, 1))
    ]
    assert any(event.error_code == "provider_error" for event in sink.events)


def test_budget_policy_requires_finite_positive_hard_boundaries() -> None:
    defaults = BudgetPolicy(hard_seconds=None, hard_tokens=None, hard_calls=None)
    assert defaults.hard_seconds == 900
    assert defaults.soft_seconds == 600
    assert defaults.hard_tokens == 2_000_000
    assert defaults.soft_tokens == 1_500_000
    assert defaults.hard_calls == 32
    with pytest.raises(ValueError, match="positive"):
        BudgetPolicy(hard_tokens=0)
    with pytest.raises(ValueError, match="cannot exceed"):
        BudgetPolicy(soft_seconds=31, hard_seconds=30)


def test_route_partition_single_indivisible_record_fails_before_provider() -> None:
    request = _fixture_route_request()
    first = request.payload["nodes"][0]  # type: ignore[index]
    assert isinstance(first, dict)
    first["text"] = "x" * MAX_PROMPT_CHARS
    request = replace(
        request,
        payload={
            **request.payload,
            "node_ids": [request.constraints.ordered_member_ids[0]],
            "nodes": [first],
            "edges": [],
            "edge_ids": [],
        },
        constraints=replace(
            request.constraints,
            ordered_member_ids=(request.constraints.ordered_member_ids[0],),
            required_member_ids=frozenset({request.constraints.ordered_member_ids[0]}),
        ),
    )
    with pytest.raises(ValueError, match="single complete route-node"):
        partition_organization_request(request)

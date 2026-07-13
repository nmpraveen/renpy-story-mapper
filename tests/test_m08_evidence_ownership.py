"""Adversarial subject-scoped evidence validation for M08 organization."""

from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.organization.cache import build_cache_key
from renpy_story_mapper.organization.contracts import (
    CodexMode,
    EdgeEvidenceOwnership,
    OrganizationConstraints,
    OrganizationRequest,
    OrganizationStage,
)
from renpy_story_mapper.organization.errors import InvalidProviderOutputError
from renpy_story_mapper.organization.parallel import (
    SchedulerConfig,
    normalized_cache_identity,
)
from renpy_story_mapper.organization.validation import validate_result


def _request(
    *,
    member_evidence: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("member-a", ("evidence-a",)),
        ("member-b", ("evidence-b",)),
    ),
    member_facts: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("member-a", ("fact-a",)),
        ("member-b", ("fact-b",)),
    ),
    fact_evidence: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("fact-a", ("evidence-fact-a",)),
        ("fact-b", ("evidence-fact-b",)),
    ),
    edges: tuple[EdgeEvidenceOwnership, ...] = (),
    context: frozenset[str] = frozenset(),
) -> OrganizationRequest:
    return OrganizationRequest(
        run_id="run",
        chunk_id="chunk",
        scope_id="scope",
        stage=OrganizationStage.EVENTS,
        payload={"nodes": [{"id": "member-a"}, {"id": "member-b"}]},
        constraints=OrganizationConstraints(
            ordered_member_ids=("member-a", "member-b"),
            required_member_ids=frozenset({"member-a", "member-b"}),
            context_member_ids=context,
            fact_ids=frozenset({"fact-a", "fact-b"}),
            evidence_ids=frozenset(
                {
                    "evidence-a",
                    "evidence-b",
                    "evidence-fact-a",
                    "evidence-fact-b",
                    "evidence-edge",
                    "evidence-boundary",
                    "evidence-context",
                }
            ),
            character_names=frozenset({"Ava", "Bea"}),
            member_evidence_ids=member_evidence,
            member_fact_ids=member_facts,
            fact_evidence_ids=fact_evidence,
            member_character_names=(
                ("member-a", ("Ava",)),
                ("member-b", ("Bea",)),
            ),
            edge_ownership=edges,
        ),
    )


def _group(
    group_id: str,
    members: list[str],
    evidence_ids: list[str],
    *,
    facts: list[str] | None = None,
    characters: list[str] | None = None,
    claims: bool = True,
) -> dict[str, object]:
    return {
        "id": group_id,
        "title": f"Group {group_id}",
        "summary": "Evidence-backed group.",
        "member_ids": members,
        "characters": [] if characters is None else characters,
        "importance": "major",
        "outcomes": ["A bounded outcome."],
        "promoted_fact_ids": [] if facts is None else facts,
        "claims": (
            [{"text": "Grounded interpretation.", "evidence_ids": evidence_ids}]
            if claims
            else []
        ),
        "warnings": [],
    }


def _payload(*groups: dict[str, object]) -> dict[str, object]:
    return {"stage": "events", "groups": list(groups), "ungrouped_ids": []}


def test_two_valid_groups_cannot_swap_request_wide_evidence() -> None:
    payload = _payload(
        _group("a", ["member-a"], ["evidence-b"]),
        _group("b", ["member-b"], ["evidence-a"]),
    )

    with pytest.raises(InvalidProviderOutputError, match="outside its group"):
        validate_result(payload, _request())


def test_group_cannot_promote_fact_owned_by_another_group() -> None:
    payload = _payload(
        _group("a", ["member-a"], ["evidence-a"], facts=["fact-b"]),
        _group("b", ["member-b"], ["evidence-b"]),
    )

    with pytest.raises(InvalidProviderOutputError, match="not attributable"):
        validate_result(payload, _request())


def test_boundary_and_context_evidence_do_not_support_a_member() -> None:
    request = _request(
        edges=(
            EdgeEvidenceOwnership(
                "member-a", "context-node", ("evidence-boundary",), ()
            ),
        ),
        context=frozenset({"context-node"}),
    )
    payload = _payload(
        _group("a", ["member-a"], ["evidence-boundary"]),
        _group("b", ["member-b"], ["evidence-b"]),
    )

    with pytest.raises(InvalidProviderOutputError, match="outside its group"):
        validate_result(payload, request)


def test_internal_edge_evidence_supports_both_members_and_its_fact() -> None:
    request = _request(
        member_evidence=(("member-a", ()), ("member-b", ())),
        member_facts=(("member-a", ()), ("member-b", ())),
        fact_evidence=(("fact-a", ()), ("fact-b", ())),
        edges=(
            EdgeEvidenceOwnership(
                "member-a", "member-b", ("evidence-edge",), ("fact-a",)
            ),
        ),
    )
    payload = _payload(
        _group(
            "ab",
            ["member-a", "member-b"],
            ["evidence-edge"],
            facts=["fact-a"],
            characters=["Ava", "Bea"],
        )
    )

    result = validate_result(payload, request)

    assert result.groups[0].member_ids == ("member-a", "member-b")
    assert result.groups[0].promoted_fact_ids == ("fact-a",)


def test_empty_claims_and_collectively_uncovered_members_fail_closed() -> None:
    with pytest.raises(InvalidProviderOutputError, match="evidence-backed claims"):
        validate_result(
            _payload(_group("ab", ["member-a", "member-b"], [], claims=False)),
            _request(),
        )

    with pytest.raises(InvalidProviderOutputError, match="collectively support every member"):
        validate_result(
            _payload(_group("ab", ["member-a", "member-b"], ["evidence-a"])),
            _request(),
        )


def test_ownership_changes_both_cache_identities() -> None:
    original = _request()
    changed = replace(
        original,
        constraints=replace(
            original.constraints,
            member_evidence_ids=(
                ("member-a", ("evidence-b",)),
                ("member-b", ("evidence-a",)),
            ),
        ),
    )
    parameters = {
        "provider_mode": CodexMode.CODEX_CHATGPT,
        "model_profile": "high",
        "model_fingerprint": "gpt-5.6-luna",
        "prompt_version": "m08",
        "schema_version": "events-v1",
    }

    assert build_cache_key(original, **parameters).input_hash != build_cache_key(
        changed, **parameters
    ).input_hash
    config = SchedulerConfig()
    assert normalized_cache_identity(original, config) != normalized_cache_identity(
        changed, config
    )

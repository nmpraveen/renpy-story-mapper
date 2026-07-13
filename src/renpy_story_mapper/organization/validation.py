"""Strict semantic validation beyond the packaged JSON Schemas."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from renpy_story_mapper.organization.contracts import (
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationGroup,
    OrganizationRequest,
)
from renpy_story_mapper.organization.errors import InvalidProviderOutputError

_ROOT_KEYS = {"stage", "groups", "ungrouped_ids"}
_GROUP_KEYS = {
    "id",
    "title",
    "summary",
    "member_ids",
    "characters",
    "importance",
    "outcomes",
    "promoted_fact_ids",
    "claims",
    "warnings",
}
_CLAIM_KEYS = {"text", "evidence_ids"}
_IMPORTANCE = {"supporting", "major", "turning point"}


def _reject(reason: str) -> InvalidProviderOutputError:
    return InvalidProviderOutputError(
        f"The organizer returned invalid structured output: {reason}."
    )


def _strings(
    value: object,
    name: str,
    *,
    maximum: int | None = None,
    unique: bool = False,
) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _reject(f"{name} must be a string array")
    strings = cast(list[str], value)
    if maximum is not None and any(len(item) > maximum for item in strings):
        raise _reject(f"{name} contains text exceeding {maximum} characters")
    if unique and len(set(strings)) != len(strings):
        raise _reject(f"{name} contains duplicates")
    return strings


def _text(value: object, name: str, maximum: int | None = None) -> str:
    if not isinstance(value, str):
        raise _reject(f"{name} must be text")
    if not value.strip():
        raise _reject(f"{name} must not be empty")
    if maximum is not None and len(value) > maximum:
        raise _reject(f"{name} exceeds {maximum} characters")
    return value


def _ownership_map(
    entries: object,
    name: str,
    *,
    allowed_keys: set[str],
    allowed_values: frozenset[str],
) -> dict[str, frozenset[str]]:
    if not isinstance(entries, tuple):
        raise _reject(f"{name} ownership is malformed")
    result: dict[str, frozenset[str]] = {}
    for entry in entries:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not entry[0]
            or not isinstance(entry[1], tuple)
            or any(not isinstance(value, str) or not value for value in entry[1])
        ):
            raise _reject(f"{name} ownership is malformed")
        key, values = entry
        if key in result or key not in allowed_keys:
            raise _reject(f"{name} ownership has an unknown or duplicate subject")
        if len(set(values)) != len(values) or set(values) - allowed_values:
            raise _reject(f"{name} ownership references unknown or duplicate authority")
        result[key] = frozenset(values)
    return result


def _ownership_constraints(
    request: OrganizationRequest,
) -> tuple[
    Mapping[str, frozenset[str]],
    Mapping[str, frozenset[str]],
    Mapping[str, frozenset[str]],
    Mapping[str, frozenset[str]],
]:
    constraints = request.constraints
    members = set(constraints.ordered_member_ids)
    member_evidence = _ownership_map(
        constraints.member_evidence_ids,
        "member evidence",
        allowed_keys=members,
        allowed_values=constraints.evidence_ids,
    )
    member_facts = _ownership_map(
        constraints.member_fact_ids,
        "member fact",
        allowed_keys=members,
        allowed_values=constraints.fact_ids,
    )
    fact_evidence = _ownership_map(
        constraints.fact_evidence_ids,
        "fact evidence",
        allowed_keys=set(constraints.fact_ids),
        allowed_values=constraints.evidence_ids,
    )
    member_characters = _ownership_map(
        constraints.member_character_names,
        "member character",
        allowed_keys=members,
        allowed_values=constraints.character_names,
    )
    for edge in constraints.edge_ownership:
        if (
            not edge.source_id
            or not edge.target_id
            or len(set(edge.evidence_ids)) != len(edge.evidence_ids)
            or len(set(edge.fact_ids)) != len(edge.fact_ids)
            or set(edge.evidence_ids) - constraints.evidence_ids
            or set(edge.fact_ids) - constraints.fact_ids
        ):
            raise _reject("edge ownership references unknown or duplicate authority")
    return member_evidence, member_facts, fact_evidence, member_characters


def validate_result(payload: object, request: OrganizationRequest) -> OrganizationChunkResult:
    """Reject unknown authority, invented IDs/facts, gaps, duplicates, and order crossings."""
    if not isinstance(payload, dict) or set(payload) != _ROOT_KEYS:
        raise _reject("the root fields do not match the strict contract")
    if payload["stage"] != request.stage.value:
        raise _reject("the stage does not match the request")
    groups_value = payload["groups"]
    if not isinstance(groups_value, list):
        raise _reject("groups must be an array")
    ungrouped = _strings(payload["ungrouped_ids"], "ungrouped_ids")
    if len(set(ungrouped)) != len(ungrouped):
        raise _reject("ungrouped IDs are duplicated")

    constraints = request.constraints
    allowed = set(constraints.ordered_member_ids)
    member_evidence, member_facts, fact_evidence, member_characters = (
        _ownership_constraints(request)
    )
    if set(ungrouped) - allowed:
        raise _reject("ungrouped IDs include an unknown ID")
    order = {member_id: index for index, member_id in enumerate(constraints.ordered_member_ids)}
    seen: set[str] = set()
    prior_group_max = -1
    parsed_groups: list[OrganizationGroup] = []
    group_ids: set[str] = set()
    for raw_group in groups_value:
        if not isinstance(raw_group, dict) or set(raw_group) != _GROUP_KEYS:
            raise _reject("a group contains missing or forbidden authority fields")
        group_id = _text(raw_group["id"], "group.id", 80)
        if not group_id or group_id in group_ids:
            raise _reject("group IDs must be unique and non-empty")
        group_ids.add(group_id)
        members = _strings(raw_group["member_ids"], "group.member_ids")
        if not members:
            raise _reject("groups may not be empty")
        if set(members) - allowed:
            raise _reject("a group references an unknown member ID")
        if set(members) & constraints.context_member_ids:
            raise _reject("context-only beats cannot become event members")
        if len(set(members)) != len(members) or seen.intersection(members):
            raise _reject("member IDs have duplicate membership")
        positions = [order[member] for member in members]
        if positions != sorted(positions) or positions[0] <= prior_group_max:
            raise _reject("event membership crosses deterministic order")
        prior_group_max = positions[-1]
        seen.update(members)

        characters = _strings(raw_group["characters"], "group.characters", unique=True)
        if set(characters) - constraints.character_names:
            raise _reject("a character name lacks request evidence")
        facts = _strings(
            raw_group["promoted_fact_ids"], "group.promoted_fact_ids", unique=True
        )
        if set(facts) - constraints.fact_ids:
            raise _reject("a promoted fact ID was invented")
        group_members = set(members)
        support_by_member = {
            member: set(member_evidence.get(member, ())) for member in members
        }
        fact_members: dict[str, set[str]] = {}
        fact_support: dict[str, set[str]] = {}
        for member in members:
            direct_evidence = set(member_evidence.get(member, ()))
            for fact_id in member_facts.get(member, ()):
                fact_members.setdefault(fact_id, set()).add(member)
                fact_support.setdefault(fact_id, set()).update(direct_evidence)
        for edge in constraints.edge_ownership:
            if edge.source_id not in group_members or edge.target_id not in group_members:
                continue
            edge_evidence = set(edge.evidence_ids)
            support_by_member[edge.source_id].update(edge_evidence)
            support_by_member[edge.target_id].update(edge_evidence)
            for fact_id in edge.fact_ids:
                fact_members.setdefault(fact_id, set()).update(
                    {edge.source_id, edge.target_id}
                )
                fact_support.setdefault(fact_id, set()).update(edge_evidence)
        if set(facts) - set(fact_members):
            raise _reject("a promoted fact is not attributable to this group's members")
        for fact_id in facts:
            fact_evidence_values = set(fact_evidence.get(fact_id, ()))
            fact_support.setdefault(fact_id, set()).update(fact_evidence_values)
            for member in fact_members[fact_id]:
                support_by_member[member].update(fact_evidence_values)
        group_characters = {
            character
            for member in members
            for character in member_characters.get(member, ())
        }
        if set(characters) - group_characters:
            raise _reject("a character name is not attributable to this group's members")
        importance = _text(raw_group["importance"], "group.importance")
        if importance not in _IMPORTANCE:
            raise _reject("importance is not an allowed value")
        claims_value = raw_group["claims"]
        if not isinstance(claims_value, list):
            raise _reject("claims must be an array")
        if not claims_value:
            raise _reject("every group must include evidence-backed claims")
        claims: list[InterpretationClaim] = []
        cited_evidence: set[str] = set()
        group_evidence = set().union(*support_by_member.values())
        for claim in claims_value:
            if not isinstance(claim, dict) or set(claim) != _CLAIM_KEYS:
                raise _reject("a claim contains invalid fields")
            evidence = _strings(claim["evidence_ids"], "claim.evidence_ids", unique=True)
            if not evidence:
                raise _reject("every interpretation must include evidence IDs")
            if set(evidence) - constraints.evidence_ids:
                raise _reject("an interpretation references invented evidence")
            if set(evidence) - group_evidence:
                raise _reject("an interpretation cites evidence outside its group members")
            cited_evidence.update(evidence)
            claims.append(
                InterpretationClaim(
                    text=_text(claim["text"], "claim.text", 320),
                    evidence_ids=tuple(evidence),
                )
            )
        if any(not cited_evidence.intersection(support_by_member[member]) for member in members):
            raise _reject("group claims do not collectively support every member")
        if any(not cited_evidence.intersection(fact_support[fact_id]) for fact_id in facts):
            raise _reject("a promoted fact lacks member-linked cited evidence")
        parsed_groups.append(
            OrganizationGroup(
                id=group_id,
                title=_text(raw_group["title"], "group.title", 80),
                summary=_text(raw_group["summary"], "group.summary", 320),
                member_ids=tuple(members),
                characters=tuple(characters),
                importance=importance,
                outcomes=tuple(
                    _strings(raw_group["outcomes"], "group.outcomes", maximum=320)
                ),
                promoted_fact_ids=tuple(facts),
                claims=tuple(claims),
                warnings=tuple(
                    _strings(raw_group["warnings"], "group.warnings", maximum=320)
                ),
            )
        )

    if seen.intersection(ungrouped):
        raise _reject("an ID is both grouped and ungrouped")
    covered = seen.union(ungrouped)
    if not constraints.required_member_ids.issubset(covered):
        raise _reject("required narrative, choice, or condition coverage is missing")
    if covered - allowed:
        raise _reject("the response contains an ID outside this request")
    normalized = cast(dict[str, object], payload)
    return OrganizationChunkResult(
        stage=request.stage,
        groups=tuple(parsed_groups),
        ungrouped_ids=tuple(ungrouped),
        raw_normalized=normalized,
    )

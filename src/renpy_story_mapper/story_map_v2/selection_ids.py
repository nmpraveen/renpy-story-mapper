"""Server-owned public selection IDs shared by presentation and navigation."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Final, Literal

from renpy_story_mapper.storage import canonical_json
from renpy_story_mapper.story_map_v2.contracts import CoreBranchOutcome, StoryMapCore

PUBLIC_SELECTION_SCHEMA: Final = "story_map_v2_public_selection_v1"
CONTINUATION_SELECTION_SCHEMA: Final = "story_map_v2_continuation_v1"

type SelectionRole = Literal["event", "arm", "boundary"]
VISIBLE_SELECTION_ROLES: Final[tuple[SelectionRole, ...]] = ("event", "arm")


@dataclass(frozen=True)
class PublicSelectionIds:
    """Exact role/original-ID to browser-opaque public-ID projection."""

    values: dict[tuple[SelectionRole, str], str]

    def public_id(self, role: SelectionRole, original_id: str) -> str:
        try:
            return self.values[(role, original_id)]
        except KeyError as exc:
            raise ValueError("Story Map V2 selection ownership is unavailable") from exc

    def contains(self, selection_id: str) -> bool:
        return selection_id in self.values.values()


def continuation_selection_id(path: str, node_id: str, line: int) -> str:
    """Return the frozen server-owned continuation identity."""

    payload = [CONTINUATION_SELECTION_SCHEMA, path, node_id, line]
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    return f"story-map-v2-continuation:{digest}"


def _qualified_selection_id(role: SelectionRole, original_id: str) -> str:
    payload = [PUBLIC_SELECTION_SCHEMA, role, original_id]
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    return f"story-map-v2-selection:{role}:{digest}"


def _legacy_id_is_safe(original_id: str) -> bool:
    return bool(original_id) and len(original_id) <= 512 and not any(
        marker in original_id for marker in ("/", "\\", "\r", "\n")
    )


def _outcomes(core: StoryMapCore) -> dict[tuple[str, int], CoreBranchOutcome]:
    outcomes: dict[tuple[str, int], CoreBranchOutcome] = {}
    for chunk in core.chunks:
        for outcome in chunk.branch_outcomes:
            key = (outcome.choice_key, outcome.arm_order)
            if key in outcomes:
                raise ValueError("Story Map V2 branch outcomes are not uniquely keyed")
            outcomes[key] = outcome
    return outcomes


def project_selection_ids(core: StoryMapCore) -> PublicSelectionIds:
    """Project stable public IDs without changing exact stored authority IDs."""

    outcomes = _outcomes(core)
    originals: dict[SelectionRole, set[str]] = {
        "event": set(),
        "arm": set(),
        "boundary": set(),
    }
    boundary_authority: dict[str, tuple[str, str, int]] = {}

    for chunk in core.chunks:
        for event in chunk.events:
            original_id = event.anchor.id
            if original_id in originals["event"]:
                raise ValueError("Story Map V2 same-role event selection IDs collide")
            originals["event"].add(original_id)
        for choice in chunk.choices:
            for arm in choice.arms:
                outcome = outcomes.get((choice.key, arm.order))
                if outcome is None:
                    raise ValueError("every visible choice arm requires one accepted outcome")
                original_id = outcome.anchor.id
                if original_id in originals["arm"]:
                    raise ValueError("Story Map V2 same-role arm selection IDs collide")
                originals["arm"].add(original_id)
                if arm.rejoin_node_id is None or arm.rejoin_line is None:
                    continue
                boundary_id = continuation_selection_id(
                    choice.relative_path,
                    arm.rejoin_node_id,
                    arm.rejoin_line,
                )
                authority = (choice.relative_path, arm.rejoin_node_id, arm.rejoin_line)
                previous = boundary_authority.get(boundary_id)
                if previous is not None and previous != authority:
                    raise ValueError("Story Map V2 continuation ownership is ambiguous")
                boundary_authority[boundary_id] = authority
                originals["boundary"].add(boundary_id)

    event_or_arm = originals["event"] | originals["arm"]
    if event_or_arm.intersection(originals["boundary"]):
        raise ValueError("Story Map V2 continuation ownership collides with visible authority")

    roles_by_original: dict[str, set[SelectionRole]] = defaultdict(set)
    for role in VISIBLE_SELECTION_ROLES:
        for original_id in originals[role]:
            roles_by_original[original_id].add(role)
    qualified = {
        (role, original_id)
        for original_id, roles in roles_by_original.items()
        if len(roles) > 1 or not _legacy_id_is_safe(original_id)
        for role in roles
    }

    while True:
        values: dict[tuple[SelectionRole, str], str] = {}
        for role in VISIBLE_SELECTION_ROLES:
            for original_id in originals[role]:
                key = (role, original_id)
                values[key] = (
                    _qualified_selection_id(role, original_id)
                    if key in qualified
                    else original_id
                )
        for boundary_id in originals["boundary"]:
            values[("boundary", boundary_id)] = boundary_id

        public_owners: dict[str, list[tuple[SelectionRole, str]]] = defaultdict(list)
        for key in sorted(values):
            public_owners[values[key]].append(key)
        collisions = tuple(owners for owners in public_owners.values() if len(owners) > 1)
        if not collisions:
            return PublicSelectionIds(values)
        newly_qualified = {
            key
            for owners in collisions
            for key in owners
            if key[0] != "boundary" and key not in qualified
        }
        if not newly_qualified:
            raise ValueError("Story Map V2 public selection IDs collide")
        qualified.update(newly_qualified)

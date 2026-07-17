"""Provider-free, bounded projection of exact M10/M11/M12 authority for M13.

The records produced here are transient provider inputs. They are never deterministic authority,
never execute source code, and must not be persisted as raw source packets. Every scene packet is
owned by exactly one M11 scene and carries only references already owned by that scene's M11
provenance or by its referenced M10 facts.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from renpy_story_mapper.canonical_graph_contract import CANONICAL_GRAPH_SCHEMA
from renpy_story_mapper.m11_scene_model import M11_SCENE_MODEL_SCHEMA
from renpy_story_mapper.narrative.contracts import AuthorityBinding, InputRevision
from renpy_story_mapper.storage import canonical_json

M13_SCENE_PACKET_SCHEMA: Final = "m13-scene-input-v1"
DEFAULT_SCENE_TEXT_CHARS: Final = 24_000
MAX_SCENE_TEXT_CHARS: Final = 48_000
MAX_SCENE_RECORDS: Final = 2_000
MAX_M12_RESULTS_PER_SCENE: Final = 16
MAX_M12_ALTERNATIVES_PER_RESULT: Final = 8
MAX_M12_ROUTE_MEMBERS: Final = 64
M13_CHARACTER_PARTICIPATION_VERSION: Final = "m13-character-participation-v1"

_DIALOGUE_SPEAKER = re.compile(
    r"^(?P<speaker>[A-Za-z_]\w*)(?:\s+[A-Za-z_]\w*)*\s+"
    r"(?:[rRuU]{0,2})(?P<quote>\"\"\"|'''|\"|')(?P<text>.*)(?P=quote)(?:\s+.*)?$",
    re.DOTALL,
)
_NON_CHARACTER_SPEAKERS = frozenset({"centered", "extend", "narrator"})

class NarrativeInputMode(StrEnum):
    """The exact privacy scope selected for one consented run."""

    FACT_ONLY = "fact_only"
    STORY_TEXT = "story_text"


@dataclass(frozen=True)
class SceneEvidence:
    """One direct M10 evidence leaf owned by a scene packet."""

    evidence_id: str
    source_text: str | None
    character_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.character_ids != tuple(sorted(set(self.character_ids))):
            raise ValueError("evidence character IDs must be unique and sorted")
        if any(not item.strip() or len(item) > 200 for item in self.character_ids):
            raise ValueError("evidence character IDs must be bounded non-empty text")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {"evidence_id": self.evidence_id}
        if self.source_text is not None:
            value["source_text"] = self.source_text
        if self.character_ids:
            value["character_ids"] = list(self.character_ids)
        return value


@dataclass(frozen=True)
class SceneInputPacket:
    """One independently hashable scene input with no provider or batch identity."""

    authority: AuthorityBinding
    scene_id: str
    deterministic_title: str
    structural_context: Mapping[str, object]
    atom_records: tuple[Mapping[str, object], ...]
    fact_records: tuple[Mapping[str, object], ...]
    evidence: tuple[SceneEvidence, ...]
    m12_records: tuple[Mapping[str, object], ...]
    mode: NarrativeInputMode
    omitted_evidence_ids: tuple[str, ...] = ()
    schema: str = M13_SCENE_PACKET_SCHEMA

    def __post_init__(self) -> None:
        if not self.scene_id or not self.deterministic_title.strip():
            raise ValueError("scene packets require an owned scene and deterministic title")
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if evidence_ids != tuple(sorted(set(evidence_ids))):
            raise ValueError("scene evidence must be unique and sorted")
        if set(evidence_ids) & set(self.omitted_evidence_ids):
            raise ValueError("included and omitted evidence IDs cannot overlap")
        if len(self.atom_records) + len(self.fact_records) + len(self.evidence) > MAX_SCENE_RECORDS:
            raise ValueError("scene packet record count exceeds the deterministic bound")
        if self.mode is NarrativeInputMode.FACT_ONLY and any(
            item.source_text is not None for item in self.evidence
        ):
            raise ValueError("fact-only packets cannot contain story text")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "authority": self.authority.to_dict(),
            "scene_id": self.scene_id,
            "deterministic_title": self.deterministic_title,
            "structural_context": dict(self.structural_context),
            "atom_records": [dict(item) for item in self.atom_records],
            "fact_records": [dict(item) for item in self.fact_records],
            "evidence": [item.to_dict() for item in self.evidence],
            "m12_records": [dict(item) for item in self.m12_records],
            "mode": self.mode.value,
            "omitted_evidence_ids": list(self.omitted_evidence_ids),
        }

    @property
    def input_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict())).hexdigest()

    @property
    def input_revision(self) -> InputRevision:
        return InputRevision(self.authority, self.schema, self.input_hash)


def bind_authority(
    canonical: Mapping[str, object],
    scene_model: Mapping[str, object],
    m12_results: Sequence[Mapping[str, object]] = (),
    *,
    source_archive_hash: str,
    correction_hash: str,
) -> AuthorityBinding:
    """Validate and bind exact inert payloads without changing or executing them."""

    if canonical.get("schema") != CANONICAL_GRAPH_SCHEMA:
        raise ValueError("M13 requires a supported M10 canonical payload")
    source_generation = _text(canonical, "source_generation")
    if scene_model.get("schema") != M11_SCENE_MODEL_SCHEMA:
        raise ValueError("M13 requires a supported M11 scene payload")
    binding = _mapping(scene_model.get("binding"), "M11 binding")
    canonical_hash = hashlib.sha256(canonical_json(dict(canonical))).hexdigest()
    if (
        binding.get("source_generation") != source_generation
        or binding.get("canonical_schema") != CANONICAL_GRAPH_SCHEMA
        or binding.get("canonical_hash") != canonical_hash
    ):
        raise ValueError("M11 is not exactly bound to the supplied M10 authority")
    result_identities = tuple(sorted(_m12_result_identity(item) for item in m12_results))
    if len(result_identities) != len(set(result_identities)):
        raise ValueError("selected M12 results must be unique")
    return AuthorityBinding(
        source_generation=source_generation,
        source_archive_hash=source_archive_hash,
        canonical_schema=CANONICAL_GRAPH_SCHEMA,
        canonical_hash=canonical_hash,
        scene_schema=M11_SCENE_MODEL_SCHEMA,
        scene_hash=hashlib.sha256(canonical_json(dict(scene_model))).hexdigest(),
        correction_hash=correction_hash,
        m12_result_identities=result_identities,
    )


def project_scene_inputs(
    canonical: Mapping[str, object],
    scene_model: Mapping[str, object],
    *,
    m12_results: Sequence[Mapping[str, object]] = (),
    mode: NarrativeInputMode = NarrativeInputMode.FACT_ONLY,
    max_story_text_chars: int = DEFAULT_SCENE_TEXT_CHARS,
    source_archive_hash: str,
    correction_hash: str,
) -> tuple[SceneInputPacket, ...]:
    """Build one bounded independent packet for each M11 scene."""

    if not 0 <= max_story_text_chars <= MAX_SCENE_TEXT_CHARS:
        raise ValueError("scene story-text budget is outside the supported bound")
    authority = bind_authority(
        canonical,
        scene_model,
        m12_results,
        source_archive_hash=source_archive_hash,
        correction_hash=correction_hash,
    )
    atoms = _index(_records(scene_model, "atoms"), "M11 atom")
    scenes = _records(scene_model, "scenes")
    lanes = _index(_records(scene_model, "lanes"), "M11 lane")
    chapters = _index(_records(scene_model, "chapters"), "M11 chapter")
    branches = _records(scene_model, "temporary_branches")
    occurrences = _index(_records(scene_model, "occurrences"), "M11 occurrence")
    facts = _index(_records(canonical, "facts"), "M10 fact")
    evidence = _index(_records(canonical, "evidence"), "M10 evidence")
    nodes = _index(_records(canonical, "nodes"), "M10 node")
    edges = _index(_records(canonical, "edges"), "M10 edge")
    branch_memberships = _branch_memberships(branches)

    packets: list[SceneInputPacket] = []
    ordered_scenes = sorted(
        scenes,
        key=lambda item: (
            _integer(
                _known(chapters, _text(item, "chapter_id"), "scene chapter"),
                "ordinal",
            ),
            _integer(item, "ordinal"),
            str(item.get("lane_id", "")),
            _text(item, "id"),
        ),
    )
    for scene in ordered_scenes:
        scene_id = _text(scene, "id")
        lane_id = _text(scene, "lane_id")
        chapter_id = _text(scene, "chapter_id")
        lane = _known(lanes, lane_id, f"scene {scene_id} lane")
        _known(chapters, chapter_id, f"scene {scene_id} chapter")
        scene_atoms = tuple(
            _known(atoms, atom_id, f"scene {scene_id} atom")
            for atom_id in _string_tuple(scene.get("atom_ids"), "scene atom_ids")
        )
        provenance_records = (scene, *scene_atoms)
        fact_ids = _owned_ids(provenance_records, "fact_ids")
        node_ids = _owned_ids(provenance_records, "node_ids")
        edge_ids = _owned_ids(provenance_records, "edge_ids")
        fact_records = tuple(_provider_fact(_known(facts, item, "M10 fact")) for item in fact_ids)
        direct_evidence_ids = set(_owned_ids(provenance_records, "evidence_ids"))
        for item in fact_records:
            direct_evidence_ids.update(_string_tuple(item.get("evidence_ids"), "fact evidence"))
        for item_id in node_ids:
            direct_evidence_ids.update(
                _string_tuple(
                    _known(nodes, item_id, "M10 node").get("evidence_ids"),
                    "node evidence",
                )
            )
        for item_id in edge_ids:
            direct_evidence_ids.update(
                _string_tuple(
                    _known(edges, item_id, "M10 edge").get("evidence_ids"),
                    "edge evidence",
                )
            )
        scene_evidence, omitted = _bounded_evidence(
            tuple(sorted(direct_evidence_ids)),
            evidence,
            evidence_characters=_scene_evidence_characters(scene_atoms, nodes),
            mode=mode,
            max_story_text_chars=max_story_text_chars,
        )
        character_ids = tuple(
            sorted({character for item in scene_evidence for character in item.character_ids})
        )
        packets.append(
            SceneInputPacket(
                authority=authority,
                scene_id=scene_id,
                deterministic_title=_text(scene, "title"),
                structural_context={
                    "chapter_id": chapter_id,
                    "lane_id": lane_id,
                    "lane_kind": lane.get("kind"),
                    "lane_ancestry": list(_lane_ancestry(lane_id, lanes)),
                    "ordinal": _integer(scene, "ordinal"),
                    "temporary_contexts": [
                        dict(item) for item in branch_memberships.get(scene_id, ())
                    ],
                    "occurrence_ids": list(
                        _string_tuple(scene.get("occurrence_ids"), "scene occurrence_ids")
                    ),
                    "loop_hub_id": scene.get("loop_hub_id"),
                    "repeatability": scene.get("repeatability"),
                    "definition_only": bool(scene.get("definition_only", False)),
                    "m13_character_participation": {
                        "version": M13_CHARACTER_PARTICIPATION_VERSION,
                        "character_ids": list(character_ids),
                    },
                },
                atom_records=tuple(_provider_atom(item, occurrences) for item in scene_atoms),
                fact_records=fact_records,
                evidence=scene_evidence,
                m12_records=_relevant_m12_records(scene_id, m12_results),
                mode=mode,
                omitted_evidence_ids=omitted,
            )
        )
    return tuple(packets)


def _provider_atom(
    atom: Mapping[str, object], occurrences: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    value: dict[str, object] = {
        key: atom[key]
        for key in ("id", "kind", "label", "story_facing", "speaker", "source_kind")
        if key in atom
    }
    occurrence_ids = [
        item_id
        for item_id, item in occurrences.items()
        if item.get("call_atom_id") == atom.get("id")
    ]
    if occurrence_ids:
        value["occurrence_ids"] = sorted(occurrence_ids)
    return value


def _provider_fact(fact: Mapping[str, object]) -> dict[str, object]:
    return {
        key: fact[key]
        for key in ("id", "kind", "status", "attributes", "evidence_ids")
        if key in fact
    }


def _bounded_evidence(
    evidence_ids: tuple[str, ...],
    evidence: Mapping[str, Mapping[str, object]],
    *,
    evidence_characters: Mapping[str, tuple[str, ...]],
    mode: NarrativeInputMode,
    max_story_text_chars: int,
) -> tuple[tuple[SceneEvidence, ...], tuple[str, ...]]:
    included: list[SceneEvidence] = []
    omitted: list[str] = []
    remaining = max_story_text_chars
    for evidence_id in evidence_ids:
        record = _known(evidence, evidence_id, "M10 evidence")
        character_ids = evidence_characters.get(evidence_id, ())
        if mode is NarrativeInputMode.FACT_ONLY:
            included.append(SceneEvidence(evidence_id, None, character_ids))
            continue
        text = _text(record, "source_text")
        if len(text) > remaining:
            omitted.append(evidence_id)
            continue
        included.append(SceneEvidence(evidence_id, text, character_ids))
        remaining -= len(text)
    return tuple(included), tuple(omitted)


def _scene_evidence_characters(
    atoms: Sequence[Mapping[str, object]],
    nodes: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[str, ...]]:
    """Derive inert speaker participation from exact M11 ownership and M10 node evidence."""

    result: dict[str, set[str]] = {}
    for atom in atoms:
        node = _known(nodes, _text(atom, "primary_node_id"), "M10 node")
        speaker = atom.get("speaker")
        if not isinstance(speaker, str) or not speaker.strip():
            attributes = _mapping(node.get("attributes", {}), "M10 node attributes")
            source_kind = attributes.get("source_kind", atom.get("source_kind"))
            source_text = attributes.get("source_text")
            match = (
                _DIALOGUE_SPEAKER.match(source_text.strip())
                if source_kind == "statement"
                and isinstance(source_text, str)
                and 0 < len(source_text) <= MAX_SCENE_TEXT_CHARS
                else None
            )
            speaker = None if match is None else match.group("speaker")
        if (
            not isinstance(speaker, str)
            or not speaker.strip()
            or speaker.casefold() in _NON_CHARACTER_SPEAKERS
        ):
            continue
        provenance = _mapping(atom.get("provenance", {}), "M11 atom provenance")
        evidence_ids = {
            *_string_tuple(provenance.get("evidence_ids", ()), "M11 atom evidence IDs"),
            *_string_tuple(node.get("evidence_ids", ()), "M10 node evidence IDs"),
        }
        for evidence_id in evidence_ids:
            result.setdefault(evidence_id, set()).add(speaker)
    return {key: tuple(sorted(value)) for key, value in sorted(result.items())}


def _branch_memberships(
    branches: Sequence[Mapping[str, object]],
) -> dict[str, tuple[Mapping[str, object], ...]]:
    result: dict[str, list[Mapping[str, object]]] = {}
    for branch in branches:
        branch_id = _text(branch, "id")
        for arm in _mapping_records(branch, "arms"):
            context = {
                "container_id": branch_id,
                "arm_id": _text(arm, "id"),
                "arm_ordinal": _integer(arm, "ordinal"),
            }
            for scene_id in _string_tuple(arm.get("scene_ids"), "branch arm scene_ids"):
                result.setdefault(scene_id, []).append(context)
    return {
        key: tuple(
            sorted(
                values,
                key=lambda item: (
                    str(item["container_id"]),
                    _integer(item, "arm_ordinal"),
                    str(item["arm_id"]),
                ),
            )
        )
        for key, values in result.items()
    }


def _lane_ancestry(
    lane_id: str, lanes: Mapping[str, Mapping[str, object]]
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    current: str | None = lane_id
    while current is not None:
        if current in seen:
            raise ValueError("M11 lane ancestry contains a cycle")
        seen.add(current)
        lane = _known(lanes, current, "M11 lane")
        result.append(current)
        parent = lane.get("parent_lane_id")
        if parent is not None and not isinstance(parent, str):
            raise ValueError("M11 lane parent ID is malformed")
        current = parent
    result.reverse()
    return tuple(result)


def _relevant_m12_records(
    scene_id: str, results: Sequence[Mapping[str, object]]
) -> tuple[Mapping[str, object], ...]:
    selected: list[Mapping[str, object]] = []
    for result in results:
        if _result_mentions_scene(result, scene_id):
            selected.append(_bounded_m12_record(scene_id, result))
    ordered = sorted(selected, key=lambda item: str(item.get("request_identity", "")))
    if len(ordered) > MAX_M12_RESULTS_PER_SCENE:
        raise ValueError("scene references more M12 results than the deterministic bound")
    return tuple(ordered)


def _bounded_m12_record(
    scene_id: str, result: Mapping[str, object]
) -> Mapping[str, object]:
    routes: list[Mapping[str, object]] = []
    all_paths: list[tuple[str, int, Mapping[str, object]]] = []
    recommended = result.get("recommended")
    if isinstance(recommended, Mapping):
        all_paths.append(("recommended", 0, recommended))
    alternatives = result.get("alternatives", ())
    if not isinstance(alternatives, list | tuple):
        raise ValueError("M12 alternatives must be an array")
    if any(not isinstance(item, Mapping) for item in alternatives):
        raise ValueError("M12 alternatives contain a malformed path")
    all_paths.extend(
        ("alternative", ordinal, item)
        for ordinal, item in enumerate(alternatives, start=1)
        if isinstance(item, Mapping)
    )
    matching = [item for item in all_paths if _result_mentions_scene(item[2], scene_id)]
    for role, ordinal, item in matching[: MAX_M12_ALTERNATIVES_PER_RESULT + 1]:
        routes.append(_bounded_route_alternative(item, role, ordinal))
    diagnostics = result.get("diagnostics", ())
    if not isinstance(diagnostics, list | tuple) or any(
        not isinstance(item, str) for item in diagnostics
    ):
        raise ValueError("M12 diagnostics must be an array of strings")
    result_authority: dict[str, object] = {
        key: result[key]
        for key in (
            "schema",
            "schema_version",
            "request_identity",
            "status",
            "badge",
            "complete",
            "termination_reason",
            "exhaustive",
            "closed_world",
        )
        if key in result
    }
    result_authority["diagnostics"] = list(diagnostics)
    result_authority["prerequisites"] = list(
        _common_m12_prerequisites(tuple(item[2] for item in all_paths))
    )
    value: dict[str, object] = {
        key: result[key]
        for key in (
            "schema",
            "request_identity",
            "status",
            "badge",
            "complete",
            "termination_reason",
            "exhaustive",
            "closed_world",
        )
        if key in result
    }
    value["result_authority"] = result_authority
    value["path_authority"] = routes
    value["routes"] = routes
    value["matching_route_total"] = len(routes)
    value["matching_routes_truncated"] = len(matching) > len(routes)
    return value


def _bounded_route_alternative(
    route: Mapping[str, object], role: str, ordinal: int
) -> Mapping[str, object]:
    value: dict[str, object] = {"kind": role, "role": role, "ordinal": ordinal}
    for key in (
        "scene_ids",
        "scene_titles",
        "visible_choices",
        "requirements",
        "persistent_lane_ids",
        "uncertainty_warnings",
        "instructions",
        "call_contexts",
        "persistent_commitment_claims",
    ):
        items = route.get(key, ())
        if not isinstance(items, list | tuple):
            raise ValueError(f"M12 route {key} must be an array")
        value[key] = [item for item in items[:MAX_M12_ROUTE_MEMBERS]]
        value[f"{key}_total"] = len(items)
        value[f"{key}_truncated"] = len(items) > MAX_M12_ROUTE_MEMBERS
    for key in ("selected_occurrence_id", "loop_count"):
        if key in route:
            value[key] = route[key]
    provenance = route.get("provenance", {})
    if not isinstance(provenance, Mapping):
        raise ValueError("M12 route provenance must be an object")
    value["provenance"] = dict(provenance)
    return value


def _common_m12_prerequisites(
    paths: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    if not paths:
        return ()
    ordered = tuple(_m12_requirement_texts(path) for path in paths)
    common = set(ordered[0])
    for values in ordered[1:]:
        common.intersection_update(values)
    return tuple(value for value in ordered[0] if value in common)


def _m12_requirement_texts(path: Mapping[str, object]) -> tuple[str, ...]:
    requirements = path.get("requirements", ())
    if not isinstance(requirements, list | tuple):
        raise ValueError("M12 route requirements must be an array")
    result: list[str] = []
    for item in requirements:
        if isinstance(item, str):
            text = item
        elif isinstance(item, Mapping):
            expression = item.get("expression")
            text = expression if isinstance(expression, str) else ""
        else:
            raise ValueError("M12 route requirement is malformed")
        if text.strip() and text not in result:
            result.append(text)
    return tuple(result)


def _result_mentions_scene(value: object, scene_id: str) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "scene_id" and item == scene_id:
                return True
            if key == "scene_ids" and isinstance(item, list | tuple) and scene_id in item:
                return True
            if _result_mentions_scene(item, scene_id):
                return True
        return False
    if isinstance(value, list | tuple):
        return any(_result_mentions_scene(item, scene_id) for item in value)
    return False


def _m12_result_identity(result: Mapping[str, object]) -> str:
    result_hash = hashlib.sha256(canonical_json(dict(result))).hexdigest()
    request_identity = result.get("request_identity")
    if request_identity is None:
        return result_hash
    if not isinstance(request_identity, str) or not request_identity.strip():
        raise ValueError("M12 request identity must be a non-empty string")
    return f"{request_identity}:{result_hash}"


def _owned_ids(records: Sequence[Mapping[str, object]], key: str) -> tuple[str, ...]:
    result: set[str] = set()
    for record in records:
        provenance = _mapping(record.get("provenance", {}), "M11 provenance")
        result.update(_string_tuple(provenance.get(key, ()), f"M11 provenance {key}"))
    return tuple(sorted(result))


def _records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    value = owner.get(key)
    if not isinstance(value, list | tuple):
        raise ValueError(f"{key} must be an array")
    result: list[Mapping[str, object]] = []
    for item in value:
        result.append(_mapping(item, key))
    return tuple(result)


def _mapping_records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    return _records(owner, key)


def _index(
    records: Sequence[Mapping[str, object]], label: str
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for record in records:
        record_id = _text(record, "id")
        if record_id in result:
            raise ValueError(f"duplicate {label} ID")
        result[record_id] = record
    return result


def _known(
    records: Mapping[str, Mapping[str, object]], record_id: str, label: str
) -> Mapping[str, object]:
    try:
        return records[record_id]
    except KeyError as exc:
        raise ValueError(f"unknown {label} ID") from exc


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _text(owner: Mapping[str, object], key: str) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _integer(owner: Mapping[str, object], key: str) -> int:
    value = owner.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"{label} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must contain non-empty string IDs")
    result = tuple(value)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must contain unique IDs")
    return result

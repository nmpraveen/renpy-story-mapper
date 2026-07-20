"""Atomic project persistence for the explicit M15 leading-coverage correction."""

from __future__ import annotations

import heapq
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast
from uuid import uuid4

from renpy_story_mapper import storage
from renpy_story_mapper.m11_scene_model import M11_SCENE_MODEL_SCHEMA
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    LeadingTechnicalCoverageCorrection,
    SourceLocator,
)
from renpy_story_mapper.project import PayloadRecord, Project

M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION: Final = "m15_leading_technical_corrections"
M15_LEADING_TECHNICAL_CORRECTION_KEY: Final = "authoritative"
_ENVELOPE_SCHEMA: Final = "m15-leading-technical-correction-envelope-v1"
M15_TECHNICAL_CORRECTION_SAFE_REASON: Final = "User-approved exact leading technical coverage."


class M15CorrectionPreconditionError(RuntimeError):
    """The persisted correction changed since the caller last observed it."""


@dataclass(frozen=True)
class CorrectionWrite:
    correction_id: str
    normalized_hash: str
    reused: bool


@dataclass(frozen=True)
class _StructuralAtom:
    atom_id: str
    node_id: str
    kind: str
    source_order: tuple[str, int, int, str]
    evidence_ids: tuple[str, ...]


class LeadingTechnicalCorrectionRepository:
    """Compare-and-set storage for the one authoritative M15 correction."""

    def __init__(self, project: Project) -> None:
        self._project = project

    def load(self, authority: AuthorityBinding) -> LeadingTechnicalCoverageCorrection | None:
        raw = self._project.payload(
            M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
            M15_LEADING_TECHNICAL_CORRECTION_KEY,
        )
        if raw is None:
            return None
        correction = _decode_envelope(raw)
        return correction if correction.authority == authority else None

    def save(
        self,
        correction: LeadingTechnicalCoverageCorrection,
        *,
        expected_correction_hash: str | None,
    ) -> CorrectionWrite:
        connection = self._project._require_open()
        with storage.transaction(connection):
            raw = self._project.payload(
                M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
                M15_LEADING_TECHNICAL_CORRECTION_KEY,
            )
            current = None if raw is None else _decode_envelope(raw)
            current_hash = None if current is None else current.normalized_hash
            if current_hash != expected_correction_hash:
                raise M15CorrectionPreconditionError(
                    "the authoritative M15 technical correction changed"
                )
            reused = current == correction
            if not reused:
                self._project._write_payloads_in_transaction(
                    (
                        PayloadRecord(
                            M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
                            M15_LEADING_TECHNICAL_CORRECTION_KEY,
                            _envelope(correction),
                            source_paths=tuple(
                                item.relative_path for item in correction.qualified_locators
                            ),
                        ),
                    )
                )
        return CorrectionWrite(
            correction_id=correction.correction_id,
            normalized_hash=correction.normalized_hash,
            reused=reused,
        )


def seed_leading_technical_correction_working_copy(
    source_project: Path,
    output_project: Path,
    qualified_locators: tuple[SourceLocator, ...],
) -> CorrectionWrite:
    """Atomically copy a project and persist one exact locator-proven correction.

    This routine reads only stored structural authority and never reads a creator source file.
    """

    source = source_project.resolve()
    output = output_project.resolve()
    if source == output:
        raise ValueError("the working project must differ from the source project")
    if not source.is_file():
        raise FileNotFoundError(f"source project does not exist: {source}")
    if output.exists():
        raise FileExistsError(f"working project already exists: {output}")
    if not qualified_locators:
        raise ValueError("at least one qualified source locator is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    try:
        with Project.open(source) as original:
            original.backup(temporary)
        with Project.open(temporary) as working:
            correction = _correction_from_structural_storage(working, qualified_locators)
            write = LeadingTechnicalCorrectionRepository(working).save(
                correction,
                expected_correction_hash=None,
            )
        temporary.replace(output)
        return write
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise


def _correction_from_structural_storage(
    project: Project,
    qualified_locators: tuple[SourceLocator, ...],
) -> LeadingTechnicalCoverageCorrection:
    """Resolve only structural JSON fields; source text and atom labels are never selected."""

    state = project.payload("m11_analysis_state", "authoritative")
    if not isinstance(state, dict) or not isinstance(state.get("published"), dict):
        raise ValueError("working project lacks a current complete M11 publication")
    published = cast(dict[str, object], state["published"])
    phases = published.get("phases")
    if not isinstance(phases, list):
        raise ValueError("working project has invalid M11 phase pointers")
    phase_keys: dict[str, str] = {}
    for item in phases:
        if not isinstance(item, dict):
            raise ValueError("working project has invalid M11 phase pointers")
        phase = item.get("phase")
        record_key = item.get("record_key")
        if not isinstance(phase, str) or not isinstance(record_key, str):
            raise ValueError("working project has invalid M11 phase pointers")
        phase_keys[phase] = record_key
    if set(phase_keys) != {
        "story_atoms",
        "scene_boundaries",
        "scene_assembly",
        "scene_presentation",
    }:
        raise ValueError("working project lacks a complete M11 publication")
    for field in (
        "source_generation",
        "canonical_schema",
        "canonical_hash",
    ):
        if not isinstance(published.get(field), str):
            raise ValueError("working project has an invalid M11 authority binding")

    connection = project._require_open()
    _verify_payload(connection, "m11_phase_results", phase_keys["scene_assembly"])
    atom_hash_row = connection.execute(
        """SELECT json_extract(payload_json, '$.result.scene_model_hash')
           FROM payloads WHERE collection='m11_phase_results' AND record_key=?""",
        (phase_keys["scene_assembly"],),
    ).fetchone()
    if atom_hash_row is None or not isinstance(atom_hash_row[0], str):
        raise ValueError("working project lacks the M11 structural model hash")
    authority = AuthorityBinding(
        source_generation=cast(str, published["source_generation"]),
        canonical_schema=cast(str, published["canonical_schema"]),
        canonical_hash=cast(str, published["canonical_hash"]),
        atom_schema=M11_SCENE_MODEL_SCHEMA,
        atom_hash=str(atom_hash_row[0]),
    )
    atoms = _stored_atoms(connection, phase_keys["story_atoms"])
    edges = _stored_edges(connection)
    locators_by_evidence = _stored_evidence_locators(connection)
    ordered_atoms = _structural_control_order(atoms, edges)

    resolved: list[str] = []
    used_locators: set[int] = set()
    for atom in ordered_atoms:
        atom_locators = tuple(
            locators_by_evidence[evidence_id]
            for evidence_id in atom.evidence_ids
            if evidence_id in locators_by_evidence
        )
        if not atom_locators:
            atom_locators = (
                SourceLocator(
                    atom.source_order[0],
                    atom.source_order[1],
                    atom.source_order[1],
                    "source",
                ),
            )
        hits = tuple(
            index
            for index, locator in enumerate(qualified_locators)
            if any(_locator_contains(locator, item) for item in atom_locators)
        )
        if not hits:
            break
        if len(hits) != 1:
            raise ValueError("technical correction locator resolution is ambiguous")
        used_locators.add(hits[0])
        resolved.append(atom.atom_id)
    if used_locators != set(range(len(qualified_locators))):
        raise ValueError("technical correction locator does not resolve the leading prefix")
    if not resolved or len(resolved) >= len(ordered_atoms):
        raise ValueError("technical correction must identify a strict prefix")
    return LeadingTechnicalCoverageCorrection(
        authority=authority,
        reason=M15_TECHNICAL_CORRECTION_SAFE_REASON,
        qualified_locators=qualified_locators,
        ordered_atom_ids=tuple(resolved),
    )


def _stored_atoms(
    connection: sqlite3.Connection,
    record_key: str,
) -> tuple[_StructuralAtom, ...]:
    _verify_payload(connection, "m11_phase_results", record_key)
    rows = connection.execute(
        """SELECT
               json_extract(atom.value, '$.id'),
               json_extract(atom.value, '$.primary_node_id'),
               json_extract(atom.value, '$.kind'),
               json_extract(atom.value, '$.source_order[0]'),
               json_extract(atom.value, '$.source_order[1]'),
               json_extract(atom.value, '$.source_order[2]'),
               json_extract(atom.value, '$.source_order[3]'),
               evidence.value
           FROM payloads AS payload,
                json_each(payload.payload_json, '$.result.atoms') AS atom
           LEFT JOIN json_each(atom.value, '$.provenance.evidence_ids') AS evidence
           WHERE payload.collection='m11_phase_results' AND payload.record_key=?
           ORDER BY CAST(atom.key AS INTEGER), CAST(evidence.key AS INTEGER)""",
        (record_key,),
    ).fetchall()
    grouped: dict[str, tuple[str, str, tuple[str, int, int, str], list[str]]] = {}
    order: list[str] = []
    for row in rows:
        if (
            not isinstance(row[0], str)
            or not isinstance(row[1], str)
            or not isinstance(row[2], str)
            or not isinstance(row[3], str)
            or isinstance(row[4], bool)
            or not isinstance(row[4], int)
            or isinstance(row[5], bool)
            or not isinstance(row[5], int)
            or not isinstance(row[6], str)
        ):
            raise ValueError("stored M11 structural atom data is invalid")
        atom_id = row[0]
        if atom_id not in grouped:
            order.append(atom_id)
            grouped[atom_id] = (row[1], row[2], (row[3], row[4], row[5], row[6]), [])
        if row[7] is not None:
            if not isinstance(row[7], str):
                raise ValueError("stored M11 atom evidence identity is invalid")
            grouped[atom_id][3].append(row[7])
    if not order:
        raise ValueError("working project has no stored M11 atoms")
    return tuple(
        _StructuralAtom(
            atom_id,
            grouped[atom_id][0],
            grouped[atom_id][1],
            grouped[atom_id][2],
            tuple(grouped[atom_id][3]),
        )
        for atom_id in order
    )


def _stored_edges(connection: sqlite3.Connection) -> tuple[tuple[str, str], ...]:
    _verify_payload(connection, "m10_canonical_graph", "authoritative")
    rows = connection.execute(
        """SELECT json_extract(edge.value, '$.source_id'),
                  json_extract(edge.value, '$.target_id')
           FROM payloads AS payload,
                json_each(payload.payload_json, '$.edges') AS edge
           WHERE payload.collection='m10_canonical_graph'
             AND payload.record_key='authoritative'
           ORDER BY CAST(edge.key AS INTEGER)"""
    ).fetchall()
    if any(not isinstance(row[0], str) or not isinstance(row[1], str) for row in rows):
        raise ValueError("stored M10 structural edge data is invalid")
    return tuple((str(row[0]), str(row[1])) for row in rows)


def _stored_evidence_locators(
    connection: sqlite3.Connection,
) -> dict[str, SourceLocator]:
    rows = connection.execute(
        """SELECT json_extract(evidence.value, '$.id'),
                  json_extract(evidence.value, '$.source.path'),
                  json_extract(evidence.value, '$.source.start.line'),
                  json_extract(evidence.value, '$.source.end.line'),
                  json_extract(evidence.value, '$.line_basis')
           FROM payloads AS payload,
                json_each(payload.payload_json, '$.evidence') AS evidence
           WHERE payload.collection='m10_canonical_graph'
             AND payload.record_key='authoritative'
           ORDER BY CAST(evidence.key AS INTEGER)"""
    ).fetchall()
    result: dict[str, SourceLocator] = {}
    for evidence_id, path, start, end, basis in rows:
        if not isinstance(evidence_id, str):
            raise ValueError("stored M10 evidence identity is invalid")
        if (
            isinstance(path, str)
            and isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
        ):
            result[evidence_id] = SourceLocator(
                path,
                start,
                end,
                basis if isinstance(basis, str) and basis else "source",
            )
    return result


def _structural_control_order(
    atoms: tuple[_StructuralAtom, ...],
    edges: tuple[tuple[str, str], ...],
) -> tuple[_StructuralAtom, ...]:
    atom_by_node = {item.node_id: item for item in atoms}
    by_id = {item.atom_id: item for item in atoms}
    if len(atom_by_node) != len(atoms) or len(by_id) != len(atoms):
        raise ValueError("stored M11 structural atom identities are duplicate")
    adjacency: dict[str, list[str]] = {item.atom_id: [] for item in atoms}
    indegree = {item.atom_id: 0 for item in atoms}
    for source_node, target_node in edges:
        source = atom_by_node.get(source_node)
        target = atom_by_node.get(target_node)
        if source is None or target is None or source.atom_id == target.atom_id:
            continue
        if target.atom_id not in adjacency[source.atom_id]:
            adjacency[source.atom_id].append(target.atom_id)
            indegree[target.atom_id] += 1
    keys = {item.atom_id: _structural_source_key(item) for item in atoms}
    heap = [(keys[atom_id], atom_id) for atom_id, degree in indegree.items() if degree == 0]
    heapq.heapify(heap)
    remaining = set(indegree)
    result: list[_StructuralAtom] = []
    while remaining:
        if not heap:
            atom_id = min(remaining, key=lambda item: (keys[item], item))
            heapq.heappush(heap, (keys[atom_id], atom_id))
        _key, atom_id = heapq.heappop(heap)
        if atom_id not in remaining:
            continue
        remaining.remove(atom_id)
        result.append(by_id[atom_id])
        for target_id in adjacency[atom_id]:
            indegree[target_id] -= 1
            if indegree[target_id] <= 0 and target_id in remaining:
                heapq.heappush(heap, (keys[target_id], target_id))
    return tuple(result)


def _structural_source_key(atom: _StructuralAtom) -> tuple[object, ...]:
    path, line, column, node_id = atom.source_order
    kind_rank = 0 if atom.kind in {"choice", "condition"} else 1
    return (path.replace("\\", "/"), line, column, kind_rank, node_id)


def _locator_contains(qualified: SourceLocator, atom: SourceLocator) -> bool:
    return (
        qualified.relative_path.replace("\\", "/") == atom.relative_path.replace("\\", "/")
        and qualified.line_basis == atom.line_basis
        and qualified.start_line <= atom.start_line
        and qualified.end_line >= atom.end_line
    )


def _verify_payload(connection: sqlite3.Connection, collection: str, key: str) -> None:
    row = connection.execute(
        "SELECT payload_json,payload_hash FROM payloads WHERE collection=? AND record_key=?",
        (collection, key),
    ).fetchone()
    if row is None or not isinstance(row[0], bytes | str) or not isinstance(row[1], str):
        raise storage.ProjectCorruptError("required structural project payload is missing")
    payload = row[0].encode("utf-8") if isinstance(row[0], str) else bytes(row[0])
    if storage.payload_digest(payload) != row[1]:
        raise storage.ProjectCorruptError("structural project payload checksum does not match")


def _envelope(correction: LeadingTechnicalCoverageCorrection) -> dict[str, object]:
    return {
        "schema": _ENVELOPE_SCHEMA,
        "correction_hash": correction.normalized_hash,
        "correction": correction.to_dict(),
    }


def _decode_envelope(value: object) -> LeadingTechnicalCoverageCorrection:
    try:
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "correction_hash",
            "correction",
        }:
            raise ValueError("envelope shape")
        envelope = cast(dict[str, object], value)
        if envelope["schema"] != _ENVELOPE_SCHEMA:
            raise ValueError("envelope schema")
        correction = LeadingTechnicalCoverageCorrection.from_dict(envelope["correction"])
        if envelope["correction_hash"] != correction.normalized_hash:
            raise ValueError("envelope hash")
        return correction
    except (TypeError, ValueError) as exc:
        raise storage.ProjectCorruptError("stored M15 technical correction is corrupt") from exc


def decode_leading_technical_correction_envelope(
    value: object,
) -> LeadingTechnicalCoverageCorrection:
    """Strictly decode a stored envelope for immutable read-only consumers."""

    return _decode_envelope(value)

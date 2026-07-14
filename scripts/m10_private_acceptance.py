"""Validate M10 against independently authored private MsDenvers Day 1 facts."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib
import json
import socket
import sys
import time
import urllib.request
from collections import deque
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest import mock

from renpy_story_mapper.project import (
    Project,
    create_ingested_project,
    refresh_ingested_project,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests" / "private" / "m10_msdenvers_day1_ground_truth.json"
DEFAULT_SOURCE = Path(
    r"C:\Users\prave\AppData\Local\RenPyStoryMapper\recovery-cache-v1\d8"
    r"\d8a8c2470ee58d5d55f0ab04d6a71fa19c5a68ce86d880c83e0f72107cf91f4c"
    r"\source.rpy"
)
DEFAULT_ARCHIVE = Path(
    r"C:\Users\prave\Downloads\JD\MsDenvers-0 1 2 7-p"
    r"\MsDenvers-0.1.2.7-pc\game\scripts.rpa"
)
DEFAULT_GAME_FOLDER = DEFAULT_ARCHIVE.parent
EXPECTED_REUSED_PHASES = (
    "source_inventory",
    "parse",
    "graph",
    "semantic_state",
    "control_flow",
    "route_map",
    "canonical_graph",
    "simplified_projection",
    "inspection_projection",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--game-folder", type=Path, default=DEFAULT_GAME_FOLDER)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    report = run(
        manifest_path=args.manifest,
        source_path=args.source,
        archive_path=args.archive,
        game_folder_path=args.game_folder,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run(
    *,
    manifest_path: Path,
    source_path: Path,
    archive_path: Path,
    game_folder_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    manifest_path = manifest_path.resolve(strict=True)
    source_path = source_path.resolve(strict=True)
    archive_path = archive_path.resolve(strict=True)
    game_folder_path = game_folder_path.resolve(strict=True)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = _mapping(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    source_before = _fingerprint(source_path)
    archive_before = _fingerprint(archive_path)
    started = time.perf_counter()

    direct = _verify_manifest_against_source(manifest, source_path)
    first_path = output_dir / "msdenvers-day1-folder.rsmproj"
    second_path = output_dir / "msdenvers-day1-fresh-replay.rsmproj"
    with _offline_acceptance_boundary() as safety_counts:
        first_started = time.perf_counter()
        create_ingested_project(first_path, game_folder_path).close()
        first_seconds = time.perf_counter() - first_started
        initial = _payload_fingerprints(first_path)
        initial_database_size = first_path.stat().st_size

        refresh_started = time.perf_counter()
        with _unchanged_refresh_phase_bombs():
            refresh = refresh_ingested_project(first_path, game_folder_path)
        refresh_seconds = time.perf_counter() - refresh_started
        refreshed = _payload_fingerprints(first_path)
        refreshed_database_size = first_path.stat().st_size

        second_started = time.perf_counter()
        create_ingested_project(second_path, game_folder_path).close()
        second_seconds = time.perf_counter() - second_started
        second = _payload_fingerprints(second_path)

    ingestion_metadata = _project_metadata(first_path)
    if ingestion_metadata.get("source_kind") != "game_folder" or Path(
        str(ingestion_metadata.get("source_path", ""))
    ) != game_folder_path:
        raise AssertionError("private acceptance did not use the normal game-folder ingestion path")
    manifest_source = _mapping(manifest.get("source"), "manifest.source")
    project_source_path = _project_source_for_hash(first_path, str(manifest_source["sha256"]))
    refresh_canonical_stable = initial["canonical"] == refreshed["canonical"]
    refresh_projection_stable = initial["projection"] == refreshed["projection"]
    canonical_stable = refreshed["canonical"] == second["canonical"]
    projection_stable = refreshed["projection"] == second["projection"]
    if not all(
        (
            refresh_canonical_stable,
            refresh_projection_stable,
            canonical_stable,
            projection_stable,
        )
    ):
        raise AssertionError("unchanged private input did not produce stable structural output")
    if refresh.parsed_sources or not refresh.reused_sources:
        raise AssertionError("unchanged same-project refresh did not reuse parsed sources")
    if refresh.reused_phases != EXPECTED_REUSED_PHASES:
        raise AssertionError("unchanged same-project refresh did not reuse every analysis phase")
    if initial_database_size != refreshed_database_size:
        raise AssertionError("unchanged same-project refresh changed the SQLite project size")
    if any(safety_counts.values()):
        raise AssertionError("private acceptance crossed a provider or network boundary")

    projection, analysis_state = _supporting_payloads(first_path)
    canonical = _canonical_payload(first_path)
    graph_result = _validate_graph(
        manifest,
        canonical,
        projection,
        analysis_state,
        canonical_hash=str(refreshed["canonical"]["sha256"]),
        expected_source_path=project_source_path,
    )
    del canonical
    gc.collect()
    source_after = _fingerprint(source_path)
    archive_after = _fingerprint(archive_path)
    if source_before != source_after or archive_before != archive_after:
        raise AssertionError("private acceptance changed a read-only source")
    hardcoded = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src" / "renpy_story_mapper").rglob("*.py")
        if "msdenvers" in path.read_text(encoding="utf-8").casefold()
    ]
    if hardcoded:
        raise AssertionError(f"production code contains game-specific names: {hardcoded}")

    report: dict[str, object] = {
        "schema_version": 1,
        "status": "passed",
        "manifest": str(manifest_path),
        "ground_truth_authorship": manifest.get("authorship"),
        "safety": {
            "game_or_creator_python_executed": False,
            "provider_constructions": safety_counts["provider_constructions"],
            "remote_requests": safety_counts["remote_requests"],
            "source_unchanged": source_before == source_after,
            "archive_unchanged": archive_before == archive_after,
            "production_game_hardcodes": hardcoded,
        },
        "direct_source_verification": direct,
        "graph_validation": graph_result,
        "determinism": {
            "same_project_refresh_canonical_equal": refresh_canonical_stable,
            "same_project_refresh_projection_equal": refresh_projection_stable,
            "canonical_structural_bytes_equal": canonical_stable,
            "projection_structural_bytes_equal": projection_stable,
            "canonical_hash": refreshed["canonical"]["sha256"],
            "projection_hash": refreshed["projection"]["sha256"],
        },
        "timings": {
            "first_analysis_seconds": round(first_seconds, 3),
            "unchanged_refresh_seconds": round(refresh_seconds, 3),
            "replay_analysis_seconds": round(second_seconds, 3),
            "phase_seconds": {
                str(item["phase"]): item["duration_seconds"]
                for item in _records(analysis_state.get("phases"), "analysis_state.phases")
            },
            "total_seconds": round(time.perf_counter() - started, 3),
        },
        "sizes": {
            "canonical_payload_bytes": refreshed["canonical"]["size_bytes"],
            "simplified_payload_bytes": refreshed["projection"]["size_bytes"],
            "sqlite_project_bytes": refreshed_database_size,
        },
        "artifacts": {
            "first_project": str(first_path),
            "replay_project": str(second_path),
        },
        "ingestion": {
            "input_kind": ingestion_metadata.get("source_kind"),
            "game_folder": str(game_folder_path),
            "archive": str(archive_path),
            "manifest_source_path": project_source_path,
            "parsed_sources": list(refresh.parsed_sources),
            "reused_sources": list(refresh.reused_sources),
            "invalidated_sources": list(refresh.invalidated_sources),
            "removed_sources": list(refresh.removed_sources),
            "reused_phases": list(refresh.reused_phases),
        },
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (output_dir / "ACCEPTANCE_REPORT.md").write_text(
        _markdown(report), encoding="utf-8", newline="\n"
    )
    return report


def _verify_manifest_against_source(
    manifest: Mapping[str, object], source_path: Path
) -> dict[str, object]:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    source = _mapping(manifest.get("source"), "manifest.source")
    actual_hash = _sha256(source_path.read_bytes())
    if actual_hash != str(source.get("sha256")):
        raise AssertionError("private source does not match the independently authored manifest")
    checked_lines: set[int] = set()
    choices = _records(manifest.get("choices"), "manifest.choices")
    for choice in choices:
        _expect_line(lines, _integer(choice, "menu_line"), "menu:")
        checked_lines.add(_integer(choice, "menu_line"))
        for arm in _records(choice.get("ordered_arms"), "choice.ordered_arms"):
            caption = str(arm["caption"])
            caption_line = _integer(arm, "caption_line")
            _expect_line(lines, caption_line, f'"{caption}":')
            target_line = _integer(arm, "target_line")
            _expect_line(lines, target_line, str(arm["target_text"]))
            checked_lines.update((caption_line, target_line))
        rejoin_line = _integer(choice, "rejoin_line")
        _expect_line(lines, rejoin_line, str(choice["rejoin_text"]))
        checked_lines.add(rejoin_line)
    for key in ("conditions", "effects"):
        for item in _records(manifest.get(key), f"manifest.{key}"):
            line = _integer(item, "line")
            _expect_line(lines, line, str(item["expression"]))
            checked_lines.add(line)
    for item in _records(manifest.get("visibility_cases"), "manifest.visibility_cases"):
        line = _integer(item, "line")
        _expect_line(lines, line, str(item["source_text"]))
        checked_lines.add(line)
    return {
        "source_sha256": actual_hash,
        "choice_count": len(choices),
        "arm_count": sum(
            len(_records(item.get("ordered_arms"), "choice.ordered_arms")) for item in choices
        ),
        "independently_checked_source_lines": len(checked_lines),
    }


def _validate_graph(
    manifest: Mapping[str, object],
    canonical: Mapping[str, object],
    projection: Mapping[str, object],
    analysis_state: Mapping[str, object],
    *,
    canonical_hash: str,
    expected_source_path: str,
) -> dict[str, object]:
    canonical_nodes = _records(canonical.get("nodes"), "canonical.nodes")
    canonical_edges = _records(canonical.get("edges"), "canonical.edges")
    canonical_regions = _records(canonical.get("regions"), "canonical.regions")
    evidence = _records(canonical.get("evidence"), "canonical.evidence")
    facts = _records(canonical.get("facts"), "canonical.facts")
    proofs = _records(canonical.get("proofs"), "canonical.proofs")
    projected_nodes = _records(projection.get("nodes"), "projection.nodes")
    projected_edges = _records(projection.get("edges"), "projection.edges")
    projected_regions = _records(projection.get("regions"), "projection.regions")
    node_by_id = {str(item["id"]): item for item in canonical_nodes}
    evidence_by_id = {str(item["id"]): item for item in evidence}
    proof_by_id = {str(item["id"]): item for item in proofs}
    choices = _records(manifest.get("choices"), "manifest.choices")
    bounds = _mapping(manifest.get("bounds"), "manifest.bounds")
    expected_choice_count = _integer(bounds, "expected_day1_choice_count")
    if len(choices) != expected_choice_count:
        raise AssertionError(
            f"manifest Day 1 choice count mismatch: {len(choices)} != {expected_choice_count}"
        )
    source = _mapping(manifest.get("source"), "manifest.source")
    day1_start = _integer(source, "day1_start_line")
    day2_start = _integer(source, "day2_start_line")

    day1_outcomes = [
        item
        for item in projected_nodes
        if item.get("kind") == "choice_outcome"
        and (
            (entry := _entry_location(item, node_by_id, evidence_by_id))[0]
            == expected_source_path
            and day1_start <= entry[1] < day2_start
        )
    ]
    expected_arm_count = _integer(
        _mapping(manifest.get("bounds"), "bounds"), "expected_day1_arm_count"
    )
    if len(day1_outcomes) != expected_arm_count:
        raise AssertionError(
            f"Day 1 outcome count mismatch: {len(day1_outcomes)} != {expected_arm_count}"
        )
    outcomes_by_line = {
        _entry_location(item, node_by_id, evidence_by_id)[1]: item for item in day1_outcomes
    }
    matched_regions: set[str] = set()
    rejoin_records: list[dict[str, object]] = []
    arm_bindings: list[dict[str, object]] = []
    projected_by_id = {str(item["id"]): item for item in projected_nodes}
    canonical_region_by_id = {str(item["id"]): item for item in canonical_regions}
    for choice in choices:
        arms = _records(choice.get("ordered_arms"), "choice.ordered_arms")
        outcomes = [outcomes_by_line[_integer(arm, "caption_line")] for arm in arms]
        if [str(item["title"]) for item in outcomes] != [str(item["caption"]) for item in arms]:
            raise AssertionError("Day 1 captions or arm order differ from the source manifest")
        if [
            _integer(_mapping(item.get("attributes"), "outcome.attributes"), "ordinal")
            for item in outcomes
        ] != list(range(len(arms))):
            raise AssertionError("Day 1 projected arm ordinals are incorrect")
        region_ids = {
            str(_mapping(item.get("attributes"), "outcome.attributes")["canonical_region_id"])
            for item in outcomes
        }
        if len(region_ids) != 1:
            raise AssertionError("choice arms do not share one canonical region")
        region_id = region_ids.pop()
        matched_regions.add(region_id)
        region = next(
            item for item in projected_regions if item["canonical_region_id"] == region_id
        )
        merge = region.get("merge_node_id")
        split = region.get("split_node_id")
        if not isinstance(merge, str) or not isinstance(split, str):
            raise AssertionError("a source-proven Day 1 choice lacks its split or rejoin")
        for index, (arm, outcome) in enumerate(zip(arms, outcomes, strict=True)):
            target_line = _integer(arm, "target_line")
            member_lines = _member_lines(
                outcome,
                node_by_id,
                evidence_by_id,
                expected_source_path=expected_source_path,
            )
            if target_line not in member_lines:
                raise AssertionError(
                    f"branch target line {target_line} is absent from {arm['caption']!r}"
                )
            if not _reachable(str(outcome["id"]), merge, projected_edges):
                raise AssertionError(f"choice outcome {arm['caption']!r} does not reach its rejoin")
            attributes = _mapping(outcome.get("attributes"), "outcome.attributes")
            next_line = (
                _integer(arms[index + 1], "caption_line")
                if index + 1 < len(arms)
                else _integer(choice, "rejoin_line")
            )
            arm_bindings.append(
                {
                    "start_line": target_line,
                    "end_line": next_line,
                    "canonical_region_id": region_id,
                    "canonical_arm_id": str(attributes["canonical_arm_id"]),
                }
            )
        rejoin_proof = _resolve_rejoin_evidence(
            projected_by_id,
            canonical_region_by_id[region_id],
            node_by_id,
            canonical_edges,
            evidence_by_id,
            proof_by_id,
            projected_merge_id=merge,
            expected_path=expected_source_path,
            expected_line=_integer(choice, "rejoin_line"),
            expected_text=str(choice["rejoin_text"]),
        )
        rejoin_records.append(
            {
                "manifest_line": choice["rejoin_line"],
                "manifest_text": choice["rejoin_text"],
                "canonical_region_id": region_id,
                "projected_merge_node_id": merge,
                "evidence": rejoin_proof,
            }
        )

    if len(matched_regions) != expected_choice_count:
        raise AssertionError(
            f"Day 1 choice count mismatch: {len(matched_regions)} != {expected_choice_count}"
        )
    expected_rejoin_count = _integer(bounds, "expected_choice_rejoin_count")
    if len(rejoin_records) != expected_rejoin_count:
        raise AssertionError(
            f"choice rejoin count mismatch: {len(rejoin_records)} != {expected_rejoin_count}"
        )
    fact_attachments = _verify_facts(
        manifest,
        facts,
        evidence_by_id,
        canonical_nodes,
        canonical_edges,
        canonical_region_by_id,
        arm_bindings,
        expected_source_path=expected_source_path,
    )
    visible_locations = {
        location
        for item in canonical_nodes
        for location in _evidence_locations(
            _strings(item.get("evidence_ids")), evidence_by_id
        )
    }
    for item in _records(manifest.get("visibility_cases"), "manifest.visibility_cases"):
        if (expected_source_path, _integer(item, "line")) not in visible_locations:
            raise AssertionError(f"source visibility case at line {item['line']} disappeared")
    maximum = _integer(bounds, "maximum_whole_project_projection_nodes")
    compactness = _projection_compactness(
        projected_nodes,
        canonical_nodes,
        node_by_id,
        evidence_by_id,
        expected_source_path=expected_source_path,
        maximum_manifest_source_nodes=maximum,
    )
    if analysis_state.get("status") != "current_complete":
        raise AssertionError("private analysis did not complete on one generation")
    if projection.get("source_generation") != canonical.get("source_generation"):
        raise AssertionError("private graph projections mixed source generations")
    if projection.get("canonical_graph_hash") != canonical_hash:
        raise AssertionError("private simplified projection is not bound to canonical authority")
    return {
        "canonical_nodes": len(canonical_nodes),
        "canonical_edges": len(canonical_edges),
        "simplified_nodes": len(projected_nodes),
        "simplified_edges": len(projected_edges),
        **compactness,
        "day1_choices": len(matched_regions),
        "day1_outcomes": len(day1_outcomes),
        "choice_rejoins": rejoin_records,
        "fact_attachments": fact_attachments,
        "conditions_verified": len(_records(manifest.get("conditions"), "conditions")),
        "effects_verified": len(_records(manifest.get("effects"), "effects")),
        "visibility_cases_verified": len(
            _records(manifest.get("visibility_cases"), "visibility_cases")
        ),
        "source_generation": projection.get("source_generation"),
    }


def _resolve_rejoin_evidence(
    projected_by_id: Mapping[str, Mapping[str, object]],
    canonical_region: Mapping[str, object],
    node_by_id: Mapping[str, Mapping[str, object]],
    canonical_edges: Sequence[Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
    proof_by_id: Mapping[str, Mapping[str, object]],
    *,
    projected_merge_id: str,
    expected_path: str,
    expected_line: int,
    expected_text: str,
) -> dict[str, object]:
    projected_merge = projected_by_id[projected_merge_id]
    candidates = list(_strings(projected_merge.get("canonical_node_ids")))
    canonical_merge_id = canonical_region.get("merge_node_id")
    if isinstance(canonical_merge_id, str):
        candidates.append(canonical_merge_id)
    node_by_graph_id = {str(item.get("graph_node_id")): item for item in node_by_id.values()}
    proof_chain: list[str] = []
    for candidate_id in tuple(dict.fromkeys(candidates)):
        candidate = node_by_id.get(candidate_id)
        if candidate is None:
            continue
        evidence_ids = _strings(candidate.get("evidence_ids"))
        for evidence_id in evidence_ids:
            evidence = evidence_by_id[evidence_id]
            line_matches = (expected_path, expected_line) in _evidence_locations(
                (evidence_id,), evidence_by_id
            )
            text_matches = expected_text in str(evidence.get("source_text", ""))
            if line_matches and text_matches:
                return {
                    "kind": "direct_merge_evidence",
                    "canonical_merge_node_id": candidate_id,
                    "evidence_id": evidence_id,
                    "line": expected_line,
                    "text": expected_text,
                }
        for proof_id in _strings(candidate.get("proof_ids")):
            proof = proof_by_id.get(proof_id)
            if proof is None:
                continue
            proof_chain.append(proof_id)
            for input_id in _strings(proof.get("input_ids")):
                origin_node = node_by_graph_id.get(input_id)
                if origin_node is None:
                    continue
                for evidence_id in _strings(origin_node.get("evidence_ids")):
                    evidence = evidence_by_id[evidence_id]
                    if (
                        expected_path,
                        expected_line,
                    ) in _evidence_locations(
                        (evidence_id,), evidence_by_id
                    ) and expected_text in str(evidence.get("source_text", "")):
                        return {
                            "kind": "merge_proof_chain",
                            "canonical_merge_node_id": candidate_id,
                            "proof_ids": proof_chain,
                            "evidence_id": evidence_id,
                            "line": expected_line,
                            "text": expected_text,
                        }
    outgoing: dict[str, list[Mapping[str, object]]] = {}
    for edge in canonical_edges:
        if edge.get("resolved") is True:
            outgoing.setdefault(str(edge["source_id"]), []).append(edge)
    pending: deque[tuple[str, tuple[str, ...], str]] = deque(
        (candidate_id, (), candidate_id) for candidate_id in tuple(dict.fromkeys(candidates))
    )
    visited = set(candidates)
    while pending:
        source_id, edge_path, start_id = pending.popleft()
        for edge in outgoing.get(source_id, ()):
            target_id = str(edge["target_id"])
            target = node_by_id[target_id]
            next_path = (*edge_path, str(edge["id"]))
            for evidence_id in _strings(target.get("evidence_ids")):
                evidence = evidence_by_id[evidence_id]
                if (
                    (expected_path, expected_line)
                    in _evidence_locations((evidence_id,), evidence_by_id)
                    and expected_text in str(evidence.get("source_text", ""))
                ):
                    return {
                        "kind": "resolved_merge_successor",
                        "canonical_merge_node_id": start_id,
                        "canonical_predecessor_node_id": source_id,
                        "canonical_rejoin_node_id": target_id,
                        "canonical_edge_ids": list(next_path),
                        "evidence_id": evidence_id,
                        "line": expected_line,
                        "text": expected_text,
                    }
            if target.get("kind") == "merge" and target_id not in visited:
                visited.add(target_id)
                pending.append((target_id, next_path, start_id))
    raise AssertionError(
        f"projected merge {projected_merge_id} does not prove exact rejoin line {expected_line}"
    )


def _verify_facts(
    manifest: Mapping[str, object],
    facts: Sequence[Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
    canonical_nodes: Sequence[Mapping[str, object]],
    canonical_edges: Sequence[Mapping[str, object]],
    canonical_region_by_id: Mapping[str, Mapping[str, object]],
    arm_bindings: Sequence[Mapping[str, object]],
    *,
    expected_source_path: str,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    node_by_id = {str(item["id"]): item for item in canonical_nodes}
    edge_by_id = {str(item["id"]): item for item in canonical_edges}
    for manifest_key, fact_kind in (("conditions", "requirement"), ("effects", "effect")):
        for expected in _records(manifest.get(manifest_key), manifest_key):
            line = _integer(expected, "line")
            expression = str(expected["expression"])
            matches = [
                item
                for item in facts
                if item.get("kind") == fact_kind
                and _fact_expression(item) == expression
                and (expected_source_path, line)
                in _evidence_locations(_strings(item.get("evidence_ids")), evidence_by_id)
            ]
            if not matches:
                raise AssertionError(f"missing {fact_kind} {expression!r} at source line {line}")
            fact = matches[0]
            fact_id = str(fact["id"])
            applicable = [
                item
                for item in arm_bindings
                if _integer(item, "start_line") <= line < _integer(item, "end_line")
            ]
            applicable.sort(
                key=lambda item: _integer(item, "end_line") - _integer(item, "start_line")
            )
            attachment: dict[str, object]
            if applicable:
                binding = applicable[0]
                region = canonical_region_by_id[str(binding["canonical_region_id"])]
                arm = next(
                    item
                    for item in _records(
                        _mapping(region.get("attributes"), "region.attributes").get("arms"),
                        "region.attributes.arms",
                    )
                    if str(item["id"]) == str(binding["canonical_arm_id"])
                )
                member_ids = {
                    str(arm["entry_node_id"]),
                    *_strings(arm.get("member_node_ids")),
                }
                relevant_edges = {
                    str(arm["edge_id"]),
                    *(
                        str(item["id"])
                        for item in canonical_edges
                        if item.get("source_id") in member_ids
                        or item.get("target_id") in member_ids
                    ),
                }
                attached = {
                    fact_value
                    for node_id in member_ids
                    if node_id in node_by_id
                    for fact_value in _canonical_fact_ids(node_by_id[node_id])
                } | {
                    fact_value
                    for edge_id in relevant_edges
                    if edge_id in edge_by_id
                    for fact_value in _canonical_fact_ids(edge_by_id[edge_id])
                }
                if fact_id not in attached:
                    raise AssertionError(
                        f"{fact_kind} {expression!r} is not attached to expected branch arm"
                    )
                attachment = {
                    "scope": "branch_arm",
                    "canonical_region_id": binding["canonical_region_id"],
                    "canonical_arm_id": binding["canonical_arm_id"],
                }
            else:
                owners = [
                    str(item["id"])
                    for item in (*canonical_nodes, *canonical_edges)
                    if fact_id in _canonical_fact_ids(item)
                ]
                if not owners:
                    raise AssertionError(f"{fact_kind} {expression!r} has no canonical attachment")
                attachment = {"scope": "canonical_record", "owner_ids": owners}
            results.append(
                {
                    "kind": fact_kind,
                    "line": line,
                    "expression": expression,
                    "fact_id": fact_id,
                    "attachment": attachment,
                }
            )
    return results


def _canonical_fact_ids(item: Mapping[str, object]) -> set[str]:
    attributes = _mapping(item.get("attributes"), "canonical attributes")
    return {
        *_strings(attributes.get("fact_ids")),
        *_strings(attributes.get("gate_ids")),
        *_strings(attributes.get("effect_ids")),
    }


def _projection_compactness(
    projected_nodes: Sequence[Mapping[str, object]],
    canonical_nodes: Sequence[Mapping[str, object]],
    canonical_node_by_id: Mapping[str, Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
    *,
    expected_source_path: str,
    maximum_manifest_source_nodes: int,
) -> dict[str, object]:
    manifest_source_nodes = sum(
        expected_source_path
        in _projected_source_paths(item, canonical_node_by_id, evidence_by_id)
        for item in projected_nodes
    )
    if manifest_source_nodes > maximum_manifest_source_nodes:
        raise AssertionError(
            "the manifest-source simplified graph exceeds its independently authored bound"
        )
    if len(projected_nodes) >= len(canonical_nodes):
        raise AssertionError(
            "the whole-input simplified graph is not compact relative to authority"
        )
    ratio = len(projected_nodes) / len(canonical_nodes) if canonical_nodes else 0.0
    return {
        "manifest_source_simplified_nodes": manifest_source_nodes,
        "maximum_manifest_source_projection_nodes": maximum_manifest_source_nodes,
        "whole_input_projection_ratio": round(ratio, 6),
        "whole_input_projection_percent": round(ratio * 100, 3),
    }


def _projected_source_paths(
    item: Mapping[str, object],
    canonical_node_by_id: Mapping[str, Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> set[str]:
    evidence_ids = set(_strings(item.get("evidence_ids")))
    for canonical_id in _strings(item.get("canonical_node_ids")):
        canonical = canonical_node_by_id.get(canonical_id)
        if canonical is not None:
            evidence_ids.update(_strings(canonical.get("evidence_ids")))
    return {path for path, _line in _evidence_locations(tuple(evidence_ids), evidence_by_id)}


def _payload_fingerprints(path: Path) -> dict[str, dict[str, object]]:
    collections = {
        "m10_canonical_graph": "canonical",
        "m10_inspection_projection": "projection",
    }
    with Project.open(path) as project:
        connection = project._require_open()
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        rows = connection.execute(
            """
            SELECT rowid, collection, payload_hash, length(payload_json)
            FROM payloads
            WHERE record_key = 'authoritative'
              AND collection IN ('m10_canonical_graph', 'm10_inspection_projection')
            ORDER BY collection
            """
        ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for rowid, collection, stored_hash, size_bytes in rows:
            digest = hashlib.sha256()
            with connection.blobopen("payloads", "payload_json", int(rowid), readonly=True) as blob:
                while chunk := blob.read(1024 * 1024):
                    digest.update(chunk)
            actual_hash = digest.hexdigest()
            if actual_hash != str(stored_hash):
                raise AssertionError(f"{collection} payload hash does not match its stored bytes")
            result[collections[str(collection)]] = {
                "sha256": actual_hash,
                "size_bytes": int(size_bytes),
            }
    if integrity != "ok":
        raise AssertionError(f"private project integrity check failed: {integrity}")
    if result.keys() != {"canonical", "projection"}:
        raise AssertionError("private project is missing a required M10 structural payload")
    return result


def _supporting_payloads(
    path: Path,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    with Project.open(path) as project:
        projection = project.payload("m10_inspection_projection", "authoritative")
        analysis_state = project.payload("m10_analysis_state", "authoritative")
    return _mapping(projection, "projection"), _mapping(analysis_state, "analysis_state")


def _canonical_payload(path: Path) -> Mapping[str, object]:
    with Project.open(path) as project:
        canonical = project.payload("m10_canonical_graph", "authoritative")
    return _mapping(canonical, "canonical")


def _project_metadata(path: Path) -> Mapping[str, object]:
    with Project.open(path) as project:
        return project.metadata()


def _project_source_for_hash(path: Path, content_hash: str) -> str:
    with Project.open(path) as project:
        rows = project._require_open().execute(
            "SELECT path FROM sources WHERE content_hash = ? ORDER BY path", (content_hash,)
        ).fetchall()
    if len(rows) != 1:
        raise AssertionError(
            f"manifest source hash resolved to {len(rows)} ingested sources instead of one"
        )
    return str(rows[0][0])


def _entry_location(
    outcome: Mapping[str, object],
    node_by_id: Mapping[str, Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> tuple[str, int]:
    attributes = _mapping(outcome.get("attributes"), "outcome.attributes")
    entry = node_by_id[str(attributes["canonical_entry_node_id"])]
    locations = _evidence_locations(_strings(entry.get("evidence_ids")), evidence_by_id)
    if len(locations) != 1:
        raise AssertionError("choice outcome entry does not have one exact source location")
    return next(iter(locations))


def _member_lines(
    outcome: Mapping[str, object],
    node_by_id: Mapping[str, Mapping[str, object]],
    evidence_by_id: Mapping[str, Mapping[str, object]],
    *,
    expected_source_path: str,
) -> set[int]:
    return {
        line
        for node_id in _strings(outcome.get("canonical_node_ids"))
        for path, line in _evidence_locations(
            _strings(node_by_id[node_id].get("evidence_ids")), evidence_by_id
        )
        if path == expected_source_path
    }


def _evidence_lines(
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> set[int]:
    result: set[int] = set()
    for evidence_id in evidence_ids:
        source = _mapping(evidence_by_id[evidence_id].get("source"), "evidence.source")
        start = source.get("start")
        if isinstance(start, Mapping) and isinstance(start.get("line"), int):
            result.add(cast(int, start["line"]))
        elif isinstance(source.get("start_line"), int):
            result.add(cast(int, source["start_line"]))
    return result


def _evidence_locations(
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, Mapping[str, object]],
) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for evidence_id in evidence_ids:
        source = _mapping(evidence_by_id[evidence_id].get("source"), "evidence.source")
        path = source.get("path") or source.get("source_path")
        start = source.get("start")
        if not isinstance(path, str):
            continue
        if isinstance(start, Mapping) and isinstance(start.get("line"), int):
            result.add((path, cast(int, start["line"])))
        elif isinstance(source.get("start_line"), int):
            result.add((path, cast(int, source["start_line"])))
    return result


def _fact_expression(item: Mapping[str, object]) -> str:
    attributes = _mapping(item.get("attributes"), "fact.attributes")
    return str(attributes.get("original_expression") or attributes.get("expression") or "")


def _reachable(source: str, target: str, edges: Sequence[Mapping[str, object]]) -> bool:
    outgoing: dict[str, list[str]] = {}
    for edge in edges:
        outgoing.setdefault(str(edge["source_id"]), []).append(str(edge["target_id"]))
    queue = deque([source])
    visited = {source}
    while queue:
        current = queue.popleft()
        if current == target:
            return True
        for successor in outgoing.get(current, ()):
            if successor not in visited:
                visited.add(successor)
                queue.append(successor)
    return False


def _expect_line(lines: Sequence[str], line_number: int, expected: str) -> None:
    actual = lines[line_number - 1].strip()
    if expected not in actual:
        raise AssertionError(
            f"ground truth source mismatch at line {line_number}: {actual!r} lacks {expected!r}"
        )


def _markdown(report: Mapping[str, object]) -> str:
    graph = _mapping(report["graph_validation"], "graph_validation")
    timings = _mapping(report["timings"], "timings")
    safety = _mapping(report["safety"], "safety")
    ingestion = _mapping(report["ingestion"], "ingestion")
    sizes = _mapping(report["sizes"], "sizes")
    reused_count = len(cast(list[object], ingestion["reused_sources"]))
    reused_phases = cast(list[object], ingestion["reused_phases"])
    return (
        "# M10 private MsDenvers Day 1 acceptance\n\n"
        f"Status: **{report['status']}**\n\n"
        f"- Day 1 choices: {graph['day1_choices']}\n"
        f"- Day 1 outcomes: {graph['day1_outcomes']}\n"
        f"- Canonical graph: {graph['canonical_nodes']} nodes / {graph['canonical_edges']} edges\n"
        "- Simplified graph: "
        f"{graph['simplified_nodes']} nodes / {graph['simplified_edges']} edges\n"
        "- Manifest-source simplified nodes: "
        f"{graph['manifest_source_simplified_nodes']} / "
        f"{graph['maximum_manifest_source_projection_nodes']} maximum\n"
        f"- Whole-input projection ratio: {graph['whole_input_projection_percent']}%\n"
        f"- Input workflow: {ingestion['input_kind']} ({ingestion['game_folder']})\n"
        f"- Reused sources on unchanged refresh: {reused_count}\n"
        f"- Reused phases on unchanged refresh: {', '.join(map(str, reused_phases))}\n"
        f"- Canonical payload: {sizes['canonical_payload_bytes']} bytes\n"
        f"- Simplified payload: {sizes['simplified_payload_bytes']} bytes\n"
        f"- SQLite project: {sizes['sqlite_project_bytes']} bytes\n"
        f"- Provider constructions: {safety['provider_constructions']}\n"
        f"- Remote requests: {safety['remote_requests']}\n"
        f"- First analysis: {timings['first_analysis_seconds']} s\n"
        f"- Unchanged refresh: {timings['unchanged_refresh_seconds']} s\n"
        f"- Replay analysis: {timings['replay_analysis_seconds']} s\n"
        "- Canonical and simplified structural bytes were stable on replay.\n"
        "- Source and archive fingerprints were unchanged.\n"
    )


@contextmanager
def _offline_acceptance_boundary() -> Any:
    counts = {"provider_constructions": 0, "remote_requests": 0}

    def block_provider(*_args: object, **_kwargs: object) -> None:
        counts["provider_constructions"] += 1
        raise AssertionError("M10 acceptance attempted to construct an organization provider")

    def block_network(*_args: object, **_kwargs: object) -> None:
        counts["remote_requests"] += 1
        raise AssertionError("M10 acceptance attempted a network request")

    provider_module = ModuleType("renpy_story_mapper.organization.provider")

    class ProviderBomb:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            block_provider()

    provider_module.CodexCliProvider = ProviderBomb  # type: ignore[attr-defined]

    with (
        mock.patch.dict(
            sys.modules,
            {"renpy_story_mapper.organization.provider": provider_module},
        ),
        mock.patch.object(socket.socket, "connect", block_network),
        mock.patch.object(socket, "create_connection", block_network),
        mock.patch.object(urllib.request.OpenerDirector, "open", block_network),
    ):
        yield counts


def _provider_bomb_probe() -> None:
    provider_module = importlib.import_module("renpy_story_mapper.organization.provider")
    provider_module.CodexCliProvider()  # type: ignore[attr-defined]


@contextmanager
def _unchanged_refresh_phase_bombs() -> Any:
    import renpy_story_mapper.presentation as presentation
    import renpy_story_mapper.project_analysis as project_analysis

    def block_phase(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unchanged private refresh called an expensive phase or backup")

    with (
        mock.patch.object(project_analysis, "build_graph", block_phase),
        mock.patch.object(project_analysis, "build_semantic_story", block_phase),
        mock.patch.object(project_analysis, "extract_state", block_phase),
        mock.patch.object(project_analysis, "analyze_control_flow", block_phase),
        mock.patch.object(project_analysis, "project_route_map", block_phase),
        mock.patch.object(project_analysis, "build_canonical_graph", block_phase),
        mock.patch.object(project_analysis, "project_inspection_graph", block_phase),
        mock.patch.object(presentation, "rebuild_presentation_index", block_phase),
        mock.patch.object(Project, "backup", block_phase),
    ):
        yield


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "sha256": _sha256(path.read_bytes()),
        "modified_ns": stat.st_mtime_ns,
    }


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _records(value: object, name: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain objects")
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{key} must be an integer")
    return item


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded read-only presentation of current M13 jobs, artifacts, and citations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from renpy_story_mapper.narrative.authority import (
    NarrativeAuthority,
    load_narrative_authority,
)
from renpy_story_mapper.narrative.contracts import (
    AuthorityReference,
    AuthoritySystem,
    ClaimClass,
    ClaimContextScope,
    ClaimPolarity,
    ClaimSemantics,
    ClaimSupport,
    LogicalJobKind,
    NarrativeClaim,
    SupportKind,
)
from renpy_story_mapper.narrative.evidence import (
    ResolutionLimits,
    resolve_claim_evidence,
)
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.project import Project

MAX_NARRATIVE_JOBS_PAGE = 200
MAX_NARRATIVE_CLAIMS = 256
MAX_NARRATIVE_CITATIONS = 60


def narrative_snapshot(
    project: Project,
    *,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, object]:
    """Return current M13 overlay state without requiring cloud AI."""

    if offset < 0 or not 1 <= limit <= MAX_NARRATIVE_JOBS_PAGE:
        raise ValueError("narrative job window is outside the supported bound")
    try:
        authority = load_narrative_authority(project, include_m12=True)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "schema": "m13-narrative-snapshot-v1",
            "status": "unavailable",
            "reason": _reason_code(exc),
            "cloud_enabled": False,
            "jobs": [],
            "offset": offset,
            "limit": limit,
            "total": 0,
            "next_offset": None,
        }

    store = project.m13_persistence()
    job_records = store.list_records(
        RecordKind.JOB,
        authority_binding=authority.binding.to_dict(),
    )
    current_jobs: list[dict[str, object]] = []
    stale = 0
    unavailable = 0
    for lookup in job_records:
        if lookup.state is LookupState.STALE:
            stale += 1
            continue
        if lookup.state is not LookupState.HIT or lookup.payload is None:
            unavailable += 1
            continue
        try:
            current_jobs.append(_job_summary(project, authority, lookup.payload))
        except (KeyError, TypeError, ValueError):
            unavailable += 1
    current_jobs.sort(
        key=lambda item: (
            str(item["kind"]),
            str(item["owner_id"]),
            str(item["job_id"]),
        )
    )
    total = len(current_jobs)
    page = current_jobs[offset : offset + limit]
    next_offset = offset + len(page) if offset + len(page) < total else None
    scenes = _records(authority.scene_model, "scenes")
    expected_scene_ids = {str(item.get("id", "")) for item in scenes}
    published_scene_ids = {
        str(item["owner_id"])
        for item in current_jobs
        if item["kind"] == LogicalJobKind.SCENE.value and item["artifact"] is not None
    }
    published_scene_ids &= expected_scene_ids
    coverage_basis_points = (
        10_000
        if not expected_scene_ids
        else len(published_scene_ids) * 10_000 // len(expected_scene_ids)
    )
    states: dict[str, int] = {}
    for item in current_jobs:
        state = str(item["state"])
        states[state] = states.get(state, 0) + 1
    return {
        "schema": "m13-narrative-snapshot-v1",
        "status": "available",
        "authority_hash": authority.binding.identity,
        "cloud_enabled": False,
        "jobs": page,
        "offset": offset,
        "limit": limit,
        "total": total,
        "next_offset": next_offset,
        "state_counts": dict(sorted(states.items())),
        "coverage": {
            "expected_scene_jobs": len(expected_scene_ids),
            "published_scene_jobs": len(published_scene_ids),
            "scene_coverage_basis_points": coverage_basis_points,
            "stale_jobs": stale,
            "unavailable_jobs": unavailable,
            "m12_selected_results": authority.m12_coverage.selected,
            "m12_stale_results": authority.m12_coverage.stale,
            "m12_invalid_results": authority.m12_coverage.invalid,
        },
    }


def narrative_artifact_detail(project: Project, artifact_id: str) -> dict[str, object]:
    """Return one current validated artifact and bounded claim summaries."""

    authority = load_narrative_authority(project, include_m12=True)
    lookup = project.m13_persistence().lookup(
        RecordKind.ARTIFACT,
        artifact_id,
        authority_binding=authority.binding.to_dict(),
    )
    if lookup.state is not LookupState.HIT or lookup.payload is None:
        raise KeyError("current narrative artifact not found")
    artifact = lookup.payload
    claims_raw = artifact.get("claims")
    if not isinstance(claims_raw, list) or len(claims_raw) > MAX_NARRATIVE_CLAIMS:
        raise ValueError("narrative artifact claim list is invalid or unbounded")
    claims = [_claim_summary(_mapping(item, "artifact claim")) for item in claims_raw]
    coverage = _mapping(artifact.get("coverage"), "artifact coverage")
    warnings = _strings(artifact.get("warnings"), "artifact warnings")
    hierarchy_raw = artifact.get("hierarchy")
    hierarchy = None
    if hierarchy_raw is not None:
        hierarchy = dict(_mapping(hierarchy_raw, "artifact hierarchy"))
        entries = _sequence(hierarchy.get("section_entries"), "hierarchy section entries")
        if len(entries) > 32:
            raise ValueError("narrative hierarchy section entries are unbounded")
    m12_raw = artifact.get("m12_authority", ())
    m12_authority = [
        dict(_mapping(item, "artifact M12 authority"))
        for item in _sequence(m12_raw, "artifact M12 authority")
    ]
    if len(m12_authority) > 32:
        raise ValueError("narrative M12 authority annotations are unbounded")
    used_deterministic_title = bool(artifact.get("used_deterministic_title", False))
    title_class = artifact.get("title_class")
    if title_class not in {"interpretive", "deterministic_fallback"}:
        title_class = "deterministic_fallback" if used_deterministic_title else "interpretive"
    summary_class = artifact.get("summary_class")
    if summary_class != "interpretive":
        summary_class = "interpretive"
    return {
        "schema": "m13-narrative-artifact-detail-v1",
        "status": "available",
        "authority_hash": authority.binding.identity,
        "artifact_id": artifact_id,
        "logical_job_id": _text(artifact, "logical_job_id"),
        "kind": _text(artifact, "job_kind"),
        "publication": _text(artifact, "publication"),
        "title": _text(artifact, "title"),
        "title_class": title_class,
        "summary": _text(artifact, "summary"),
        "summary_class": summary_class,
        "claims": claims,
        "coverage": dict(coverage),
        "warnings": list(warnings),
        "used_deterministic_title": used_deterministic_title,
        "hierarchy": hierarchy,
        "m12_authority": m12_authority,
    }


def narrative_claim_citations(project: Project, claim_id: str) -> dict[str, object]:
    """Resolve only the requested claim through the persisted claim DAG."""

    authority = load_narrative_authority(project, include_m12=True)
    binding = authority.binding.to_dict()
    parsed: dict[str, NarrativeClaim] = {}

    def lookup(current_id: str) -> NarrativeClaim | None:
        if current_id in parsed:
            return parsed[current_id]
        result = project.m13_persistence().lookup(
            RecordKind.CLAIM,
            current_id,
            authority_binding=binding,
        )
        if result.state is not LookupState.HIT or result.payload is None:
            return None
        claim = _claim(result.payload)
        if claim.claim_id != current_id:
            raise ValueError("persisted claim identity is corrupt")
        parsed[current_id] = claim
        return claim

    resolved = resolve_claim_evidence(
        claim_id,
        lookup,
        limits=ResolutionLimits(
            max_depth=16,
            max_claims=MAX_NARRATIVE_CLAIMS,
            max_evidence=MAX_NARRATIVE_CITATIONS,
            max_result_items=MAX_NARRATIVE_CLAIMS + MAX_NARRATIVE_CITATIONS,
        ),
    )
    owner_by_job = {
        claim.logical_job_id: _job_owner(project, authority, claim.logical_job_id)
        for claim in parsed.values()
    }
    for claim in parsed.values():
        expected_owner = owner_by_job[claim.logical_job_id]
        if any(item.owner_id != expected_owner for item in claim.support.direct_evidence):
            raise ValueError("persisted claim evidence ownership is corrupt")
    citations = [
        _citation(authority, reference, claim_path)
        for reference, claim_path in zip(
            resolved.direct_evidence,
            resolved.evidence_claim_paths,
            strict=True,
        )
    ]
    labels = list(dict.fromkeys(str(item["label"]) for item in citations))
    return {
        "schema": "m13-narrative-claim-navigation-v1",
        "status": "available",
        "authority_hash": authority.binding.identity,
        "claim_id": claim_id,
        "traversed_claim_ids": list(resolved.traversed_claim_ids),
        "claim_path": list(resolved.traversed_claim_ids),
        "maximum_depth": resolved.maximum_depth,
        "citation_count": len(citations),
        "authority_labels": labels,
        "citations": citations,
    }


def _job_summary(
    project: Project,
    authority: NarrativeAuthority,
    payload: Mapping[str, object],
) -> dict[str, object]:
    spec = _mapping(payload.get("spec"), "narrative job spec")
    job_id = _text(payload, "job_id")
    artifact_id = payload.get("artifact_id")
    artifact_summary: dict[str, object] | None = None
    if isinstance(artifact_id, str) and artifact_id:
        lookup = project.m13_persistence().lookup(
            RecordKind.ARTIFACT,
            artifact_id,
            authority_binding=authority.binding.to_dict(),
        )
        if lookup.state is LookupState.HIT and lookup.payload is not None:
            artifact_summary = {
                "artifact_id": artifact_id,
                "publication": _text(lookup.payload, "publication"),
                "title": _text(lookup.payload, "title"),
                "summary": _text(lookup.payload, "summary"),
                "coverage": dict(
                    _mapping(lookup.payload.get("coverage"), "artifact coverage")
                ),
                "warnings": list(
                    _strings(lookup.payload.get("warnings"), "artifact warnings")
                ),
            }
    state = payload.get("status", payload.get("state", "queued"))
    if not isinstance(state, str) or not state:
        raise ValueError("narrative job state is invalid")
    return {
        "job_id": job_id,
        "kind": _text(spec, "kind"),
        "owner_id": _text(spec, "owner_id"),
        "state": state,
        "artifact": artifact_summary,
        "latest_attempt_id": payload.get("latest_attempt_id"),
        "latest_error": payload.get("latest_error"),
    }


def _job_owner(
    project: Project,
    authority: NarrativeAuthority,
    job_id: str,
) -> str:
    result = project.m13_persistence().lookup(
        RecordKind.JOB,
        job_id,
        authority_binding=authority.binding.to_dict(),
    )
    if result.state is not LookupState.HIT or result.payload is None:
        raise ValueError("claim owner job is unavailable")
    spec = _mapping(result.payload.get("spec"), "claim owner job spec")
    return _text(spec, "owner_id")


def _claim(payload: Mapping[str, object]) -> NarrativeClaim:
    support_raw = _mapping(payload.get("support"), "claim support")
    support_kind = SupportKind(_text(support_raw, "kind"))
    direct = tuple(
        _authority_reference(_mapping(item, "claim evidence reference"))
        for item in _sequence(support_raw.get("direct_evidence"), "direct evidence")
    )
    children = _strings(support_raw.get("child_claim_ids"), "child claim IDs")
    support = ClaimSupport(support_kind, direct_evidence=direct, child_claim_ids=children)
    semantics_raw = payload.get("semantics")
    semantics = None
    if semantics_raw is not None:
        value = _mapping(semantics_raw, "claim semantics")
        semantics = ClaimSemantics(
            subject=_text(value, "subject"),
            predicate=_text(value, "predicate"),
            polarity=ClaimPolarity(_text(value, "polarity")),
            normalized_value=_text(value, "normalized_value"),
        )
    ordinal = payload.get("ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool):
        raise ValueError("claim ordinal is invalid")
    return NarrativeClaim(
        logical_job_id=_text(payload, "logical_job_id"),
        job_kind=LogicalJobKind(_text(payload, "job_kind")),
        ordinal=ordinal,
        claim_class=ClaimClass(_text(payload, "claim_class")),
        context_scope=ClaimContextScope(_text(payload, "context_scope")),
        text=_text(payload, "text"),
        support=support,
        semantics=semantics,
    )


def _claim_summary(payload: Mapping[str, object]) -> dict[str, object]:
    claim = _claim(payload)
    return {
        "claim_id": claim.claim_id,
        "claim_class": claim.claim_class.value,
        "context_scope": claim.context_scope.value,
        "text": claim.text,
        "semantics": None if claim.semantics is None else claim.semantics.to_dict(),
        "support_kind": claim.support.kind.value,
    }


def _authority_reference(payload: Mapping[str, object]) -> AuthorityReference:
    return AuthorityReference(
        AuthoritySystem(_text(payload, "authority")),
        _text(payload, "record_kind"),
        _text(payload, "record_id"),
        _text(payload, "owner_id"),
    )


def _citation(
    authority: NarrativeAuthority,
    reference: AuthorityReference,
    claim_path: tuple[str, ...],
) -> dict[str, object]:
    _authority_record(authority, reference)
    label = f"{reference.authority.value.upper()} {reference.record_kind.replace('_', ' ')}"
    if reference.authority is AuthoritySystem.M10:
        navigation = {
            "mode": "canonical",
            "element_id": reference.record_id,
            "focus_record_id": reference.record_id,
        }
    elif reference.authority is AuthoritySystem.M11:
        element_id = (
            reference.owner_id
            if reference.record_kind == "atom"
            else reference.record_id
        )
        navigation = {
            "mode": "scenes",
            "element_id": element_id,
            "focus_record_id": reference.record_id,
        }
    else:
        navigation = {
            "mode": "m12_result",
            "element_id": reference.record_id,
            "focus_record_id": reference.record_id,
            "request_identity": reference.record_id,
        }
    return {
        "authority": reference.authority.value,
        "record_kind": reference.record_kind,
        "record_id": reference.record_id,
        "owner_id": reference.owner_id,
        "label": label,
        "claim_path": list(claim_path),
        "navigation": navigation,
    }


def _authority_record(
    authority: NarrativeAuthority,
    reference: AuthorityReference,
) -> Mapping[str, object]:
    if reference.authority is AuthoritySystem.M10:
        collection = {
            "evidence": "evidence",
            "fact": "facts",
            "node": "nodes",
            "edge": "edges",
            "region": "regions",
            "proof": "proofs",
        }.get(reference.record_kind)
        roots: Sequence[Mapping[str, object]] = (
            () if collection is None else _records(authority.canonical, collection)
        )
    elif reference.authority is AuthoritySystem.M11:
        collection = {
            "scene": "scenes",
            "atom": "atoms",
            "chapter": "chapters",
            "lane": "lanes",
            "temporary_branch": "temporary_branches",
            "occurrence": "occurrences",
            "loop_hub": "loop_hubs",
        }.get(reference.record_kind)
        roots = () if collection is None else _records(authority.scene_model, collection)
    else:
        roots = (
            ()
            if reference.record_kind != "route_result"
            else authority.m12_results
        )
    key = "request_identity" if reference.authority is AuthoritySystem.M12 else "id"
    matches = [item for item in roots if item.get(key) == reference.record_id]
    if len(matches) != 1:
        raise ValueError("citation references unknown or ambiguous authority")
    return matches[0]


def _records(owner: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    return tuple(_mapping(item, f"{key} record") for item in _sequence(owner.get(key), key))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{label} must be an array")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    values = _sequence(value, label)
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{label} must contain non-empty strings")
    result = cast(tuple[str, ...], tuple(values))
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must contain unique values")
    return result


def _text(owner: Mapping[str, object], key: str) -> str:
    value = owner.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _reason_code(error: Exception) -> str:
    text = str(error).casefold()
    if "m10" in text:
        return "m10_authority_unavailable"
    if "m11" in text:
        return "m11_authority_unavailable"
    return "narrative_authority_unavailable"

"""Browser-facing M08 API contracts over a real temporary project."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from renpy_story_mapper import storage
from renpy_story_mapper.m07_model import CheckpointStatus
from renpy_story_mapper.organization.contracts import (
    InterpretationClaim,
    OrganizationChunkResult,
    OrganizationGroup,
    OrganizationStage,
)
from renpy_story_mapper.organization.persistence import encode_organization_result
from renpy_story_mapper.project import PayloadRecord, Project, create_ingested_project
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import M08_API_ROUTES


class _NoDialogs:
    def choose_source(self, _kind: str) -> Path | None:
        return None

    def choose_open_project(self) -> Path | None:
        return None

    def choose_save_project(self) -> Path | None:
        return None


@pytest.fixture
def m08_project(tmp_path: Path) -> Path:
    source = tmp_path / "game" / "story.rpy"
    source.parent.mkdir()
    source.write_text(
        """label start:
    $ trust = 0
    menu:
        "Confide" if trust >= 0:
            $ trust += 1
            "Avery shares the truth."
        "Wait":
            "Avery keeps the secret."
    "They meet again."
    return
""",
        encoding="utf-8",
    )
    destination = tmp_path / "story.rsmproj"
    create_ingested_project(destination, source.parent).close()
    return destination


def _api(project: Path, constructions: list[str]) -> ProjectApi:
    def forbidden_provider(_scope: object) -> object:
        constructions.append("provider")
        raise AssertionError("browser read paths must not construct a provider")

    api = ProjectApi(_NoDialogs(), m07_provider_factory=forbidden_provider)
    api._project_path = project
    return api


def _apply(project_path: Path) -> tuple[str, str]:
    with Project.open(project_path) as project:
        route = project.payload("m07_route_map", "authoritative")
        assert isinstance(route, dict)
        generation = hashlib.sha256(storage.canonical_json(route)).hexdigest()
        service = project.m07_model_service()
        for scope in route["scopes"]:
            assert isinstance(scope, dict)
            scope_id = str(scope["id"])
            members = [str(item) for item in scope["node_ids"]]
            nodes_by_id = {
                str(item["id"]): item
                for item in route["nodes"]
                if isinstance(item, dict)
            }
            evidence_ids = tuple(
                dict.fromkeys(
                    evidence_id
                    for member_id in members
                    for evidence_id in nodes_by_id[member_id]["evidence_ids"]
                    if isinstance(evidence_id, str)
                )
            )
            raw_group = {
                "id": f"story_{scope_id}",
                "title": "A Choice of Trust",
                "summary": "Avery decides whether to confide before the routes meet again.",
                "member_ids": members,
                "characters": [],
                "importance": "major",
                "outcomes": ["Trust changes or the secret remains."],
                "promoted_fact_ids": [],
                "claims": [
                    {
                        "text": "The selected route events form one evidence-backed choice.",
                        "evidence_ids": list(evidence_ids),
                    }
                ],
                "warnings": [],
            }
            result = OrganizationChunkResult(
                stage=OrganizationStage.EVENTS,
                groups=(
                    OrganizationGroup(
                        id=f"story_{scope_id}",
                        title="A Choice of Trust",
                        summary="Avery decides whether to confide before the routes meet again.",
                        member_ids=tuple(members),
                        characters=(),
                        importance="major",
                        outcomes=("Trust changes or the secret remains.",),
                        promoted_fact_ids=(),
                        claims=(
                            InterpretationClaim(
                                "The selected route events form one evidence-backed choice.",
                                evidence_ids,
                            ),
                        ),
                        warnings=(),
                    ),
                ),
                ungrouped_ids=(),
                raw_normalized={
                    "stage": "events",
                    "groups": [raw_group],
                    "ungrouped_ids": [],
                },
            )
            service.transition(scope_id, CheckpointStatus.IN_FLIGHT)
            service.transition(
                scope_id,
                CheckpointStatus.VALIDATED,
                result={"organization_result": encode_organization_result(result)},
            )
        draft = service.assemble(generation=generation)
        service.apply(draft.assembly_id, generation=generation)
        return generation, draft.assembly_id


def _page(api: ProjectApi, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "node_offset": 0,
        "node_limit": 30,
        "edge_offset": 0,
        "edge_limit": 180,
    }
    body.update(overrides)
    value = api.dispatch("POST", M08_API_ROUTES["ai_story_map"], body)
    assert isinstance(value, dict)
    return value


def test_missing_applied_map_falls_back_without_provider_or_paths(m08_project: Path) -> None:
    constructions: list[str] = []
    api = _api(m08_project, constructions)
    try:
        value = _page(api)
    finally:
        api.close()

    assert value["status"] == "unavailable"
    assert value["reason"] == "no_applied_organization"
    assert value["technical_fallback"]["available"] is True
    assert constructions == []
    encoded = json.dumps(value)
    assert str(m08_project.parent) not in encoded
    assert "provider" not in encoded.casefold()


def test_pre_fix_invalid_applied_assembly_cannot_render_ai_story_map(
    m08_project: Path,
) -> None:
    _generation, assembly_id = _apply(m08_project)
    with Project.open(m08_project) as project:
        connection = project._require_open()
        row = connection.execute(
            "SELECT payload_json FROM m07_assemblies WHERE assembly_id=?", (assembly_id,)
        ).fetchone()
        assert row is not None
        payload = storage.decode_json(row["payload_json"])
        assert isinstance(payload, dict)
        items = payload["items"]
        assert isinstance(items, list)
        for item in items:
            assert isinstance(item, dict)
            wrapper = item["result"]
            assert isinstance(wrapper, dict)
            encoded = wrapper["organization_result"]
            assert isinstance(encoded, dict)
            groups = encoded["groups"]
            raw = encoded["raw_normalized"]
            assert isinstance(groups, list) and isinstance(groups[0], dict)
            assert isinstance(raw, dict) and isinstance(raw["groups"], list)
            groups[0]["claims"] = []
            raw["groups"][0]["claims"] = []
        payload_json = storage.canonical_json(payload)
        with storage.transaction(connection):
            connection.execute(
                "UPDATE m07_assemblies SET payload_json=?,payload_hash=? WHERE assembly_id=?",
                (payload_json, hashlib.sha256(payload_json).hexdigest(), assembly_id),
            )

    constructions: list[str] = []
    api = _api(m08_project, constructions)
    try:
        value = _page(api)
    finally:
        api.close()

    assert value["status"] == "unavailable"
    assert value["reason"] == "invalid_applied_organization"
    assert constructions == []


def test_available_page_detail_and_comparison_are_exact_and_bounded(
    m08_project: Path,
) -> None:
    generation, assembly_id = _apply(m08_project)
    constructions: list[str] = []
    api = _api(m08_project, constructions)
    try:
        page = _page(api)
        assert page["status"] == "available"
        node_id = str(page["nodes"][0]["id"])
        detail = api.dispatch(
            "POST",
            M08_API_ROUTES["ai_story_detail"],
            {
                "element_id": node_id,
                "route_node_limit": 30,
                "route_edge_limit": 180,
                "evidence_limit": 60,
            },
        )
        comparison = api.dispatch(
            "POST",
            M08_API_ROUTES["comparison"],
            {"node_offset": 0, "node_limit": 30, "edge_offset": 0, "edge_limit": 180},
        )
    finally:
        api.close()

    assert page["authority_hash"] == generation
    assert page["assembly_id"] == assembly_id
    assert len(page["nodes"]) <= 30 and len(page["edges"]) <= 180
    assert isinstance(detail, dict)
    assert detail["back_target"] == "ai_story_map"
    assert len(detail["member_route_nodes"]) <= 30
    assert len(detail["member_route_edges"]) <= 180
    assert len(detail["evidence"]) <= 60
    assert all(not Path(str(item["source_path"])).is_absolute() for item in detail["evidence"])
    assert all(
        str(item["line_basis"]).startswith(("physical_", "reconstructed_"))
        for item in detail["evidence"]
    )
    assert str(m08_project.parent) not in json.dumps(detail)
    assert comparison["authority_hash"] == generation
    assert comparison["authority_unchanged"] is True
    assert comparison["ai"]["authority_hash"] == comparison["technical"]["authority_hash"]
    assert constructions == []


def test_stale_and_invalid_applied_rows_have_safe_reasons(m08_project: Path) -> None:
    _apply(m08_project)
    with Project.open(m08_project) as project:
        route = project.payload("m07_route_map", "authoritative")
        assert isinstance(route, dict)
        changed = dict(route)
        changed["coverage"] = {**dict(changed["coverage"]), "m08_test_generation": 1}
        project.write_payloads((PayloadRecord("m07_route_map", "authoritative", changed),))

    constructions: list[str] = []
    api = _api(m08_project, constructions)
    try:
        stale = _page(api)
    finally:
        api.close()
    assert stale["reason"] == "stale_authority"

    # Restore exact authority, then corrupt only the applied candidate body. The deterministic
    # route payload remains readable and must still be offered as fallback.
    with Project.open(m08_project) as project:
        project.write_payloads((PayloadRecord("m07_route_map", "authoritative", route),))
        project._require_open().execute(
            "UPDATE m07_assemblies SET payload_json=? WHERE status='applied'",
            (b"[]",),
        )
        project._require_open().commit()
    api = _api(m08_project, constructions)
    try:
        invalid = _page(api)
    finally:
        api.close()
    assert invalid["reason"] == "invalid_applied_organization"
    assert invalid["technical_fallback"]["available"] is True
    assert constructions == []


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("ai_story_map", {"node_limit": 31}),
        ("ai_story_map", {"edge_limit": 181}),
        ("ai_story_map", {"unknown": True}),
        ("ai_story_detail", {"element_id": "x", "evidence_limit": 61}),
        ("ai_story_detail", {"element_id": "x", "unknown": True}),
    ],
)
def test_unknown_fields_and_invalid_limits_fail_closed(
    m08_project: Path, route: str, body: dict[str, object]
) -> None:
    api = _api(m08_project, [])
    try:
        with pytest.raises(ValueError):
            api.dispatch("POST", M08_API_ROUTES[route], body)  # type: ignore[index]
    finally:
        api.close()


def test_ai_paging_rejects_unbound_cursor_offsets_and_comparison_keeps_technical_contract(
    m08_project: Path,
) -> None:
    _apply(m08_project)
    api = _api(m08_project, [])
    try:
        with pytest.raises(ValueError, match="edge_cursor does not match"):
            _page(api, edge_offset=1, edge_cursor="v1.1." + "0" * 64)
        with pytest.raises(ValueError, match="node_offset"):
            _page(api, node_offset=999)
        with pytest.raises(ValueError, match="unsupported fields"):
            api.dispatch(
                "POST",
                M08_API_ROUTES["comparison"],
                {
                    "node_offset": 0,
                    "node_limit": 30,
                    "edge_offset": 0,
                    "edge_limit": 180,
                    "edge_cursor": "v1.0." + "0" * 64,
                },
            )
        comparison = api.dispatch(
            "POST",
            M08_API_ROUTES["comparison"],
            {"node_offset": 0, "node_limit": 30, "edge_offset": 1, "edge_limit": 180},
        )
        assert isinstance(comparison, dict)
        assert comparison["technical"]["edge_offset"] == 1
        assert comparison["ai"]["page"]["edge_offset"] == 0
    finally:
        api.close()

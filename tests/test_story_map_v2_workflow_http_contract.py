from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "src"
    / "renpy_story_mapper"
    / "story_map_v2"
    / "schemas"
    / "story_map_workflow_http_v1.schema.json"
)
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "story_map_v2"
    / "phase04_workflow_http_v1.json"
)
DOC_PATH = (
    ROOT
    / "docs"
    / "milestones"
    / "M15_PHASE_04"
    / "TRACK_B_WORKFLOW_HTTP_CONTRACT.md"
)
CONTRACT = "story-map-v2-workflow-http-v1"
COMMANDS = ("prepare", "start", "cancel", "resume", "retry", "status")
ROUTES = {
    command: f"/api/v1/story-map-v2/workflow/{command}" for command in COMMANDS
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _objects(value: object) -> Iterator[Mapping[str, object]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _reduce_calls(count: int, fan_in: int) -> int:
    if count <= fan_in:
        return 0
    parent_count = math.ceil(count / fan_in)
    return parent_count + _reduce_calls(parent_count, fan_in)


def test_workflow_http_schema_and_fixture_are_frozen() -> None:
    schema = _load(SCHEMA_PATH)
    fixture = _load(FIXTURE_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["contract"] == {"const": CONTRACT}
    for node in _objects(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, node

    assert fixture["contract"] == CONTRACT
    assert json.loads(json.dumps(fixture, sort_keys=True)) == fixture
    advertised = fixture["routes"]
    assert set(advertised) == {"story_map_v2_workflow"}
    route_object = advertised["story_map_v2_workflow"]
    assert route_object == {"contract": CONTRACT, **ROUTES}
    assert "approve" not in route_object
    assert "/workflow/approve" not in json.dumps(fixture)


def test_requests_and_success_envelopes_have_exact_shapes() -> None:
    fixture = _load(FIXTURE_PATH)
    requests = fixture["examples"]["requests"]
    assert tuple(requests) == COMMANDS
    assert set(requests["prepare"]) == {"contract"}
    assert set(requests["status"]) == {"contract", "run_id"}
    for command in ("start", "cancel", "resume"):
        assert set(requests[command]) == {"contract", "run_id", "preview_identity"}
    assert set(requests["retry"]) == {
        "contract",
        "run_id",
        "preview_identity",
        "job_id",
        "indeterminate_attempt_id",
    }

    successes = fixture["examples"]["successes"]
    assert tuple(successes) == COMMANDS
    envelope_keys = {
        "contract",
        "command",
        "preview",
        "approval",
        "status",
        "retry_approval",
    }
    for command, response in successes.items():
        assert set(response) == envelope_keys
        assert response["contract"] == CONTRACT
        assert response["command"] == command
        assert response["retry_approval"] is not None if command == "retry" else response[
            "retry_approval"
        ] is None

    assert successes["prepare"]["approval"]["state"] == "not_approved"
    assert successes["start"]["approval"]["state"] == "approved"
    assert successes["resume"]["approval"]["state"] == "approved"
    assert successes["retry"]["approval"]["state"] == "approved"


def test_cancel_is_terminal_and_status_has_exact_retry_lineage() -> None:
    successes = _load(FIXTURE_PATH)["examples"]["successes"]
    cancelled = successes["cancel"]["status"]
    assert cancelled["cancelled"] is True
    assert cancelled["can_start"] is False
    assert cancelled["can_resume"] is False
    assert cancelled["can_cancel"] is False

    status = successes["status"]["status"]
    retries = status["indeterminate_retries"]
    assert status["indeterminate_jobs"] == len(retries) == 2
    assert [(item["job_id"], item["attempt_id"], item["call_kind"]) for item in retries] == [
        ("derived:section:prologue", "attempt:section:1", "section_synthesis"),
        ("derived:overview:root", "attempt:overview:1", "rollup_synthesis"),
    ]
    assert retries[0]["approval_state"] == "required"
    assert retries[0]["retry_approval_identity"] is None
    assert retries[1]["approval_state"] == "approved"
    assert retries[1]["can_approve_retry"] is False


def test_derived_semantic_plan_and_component_ceilings_follow_v2_formula() -> None:
    preview = _load(FIXTURE_PATH)["examples"]["successes"]["prepare"]["preview"]
    plan = preview["derived_semantic_plan"]
    ceilings = preview["ceilings"]
    assert plan["fan_in"] == 24
    assert _reduce_calls(24, 24) == 0
    assert _reduce_calls(25, 24) == 2
    assert _reduce_calls(577, 24) == 27

    corridors = plan["corridors"]
    assert [item["ordinal"] for item in corridors] == list(range(len(corridors)))
    by_id = {item["corridor_id"]: item for item in corridors}
    memberships = plan["route_memberships"]
    for membership in memberships:
        route_id = membership["route_id"]
        for corridor_id in membership["ordered_corridor_ids"]:
            assert by_id[corridor_id]["route_owner"] == route_id

    route_reductions = sum(
        _reduce_calls(
            sum(
                by_id[item]["event_slot_upper_bound"]
                for item in membership["ordered_corridor_ids"]
            ),
            plan["fan_in"],
        )
        for membership in memberships
    )
    common = sum(
        item["event_slot_upper_bound"] for item in corridors if item["route_owner"] is None
    )
    expected = {
        "section_synthesis_calls": len(corridors),
        "route_reduction_calls": route_reductions,
        "route_summary_calls": len(memberships),
        "whole_game_reduction_calls": _reduce_calls(
            common + len(memberships), plan["fan_in"]
        ),
        "final_overview_calls": int(common + len(memberships) > 0),
    }
    expected["rollup_synthesis_calls"] = sum(
        expected[field]
        for field in (
            "route_reduction_calls",
            "route_summary_calls",
            "whole_game_reduction_calls",
            "final_overview_calls",
        )
    )
    assert {field: plan[field] for field in expected} == expected
    assert {field: ceilings[field] for field in expected} == expected

    serialized = json.dumps(plan, sort_keys=True)
    for forbidden in ("child_ids", "request_bytes", "serialized_request_identity"):
        assert forbidden not in serialized


def test_contract_artifacts_are_public_and_sanitized() -> None:
    fixture = _load(FIXTURE_PATH)
    schema = _load(SCHEMA_PATH)
    documentation = DOC_PATH.read_text(encoding="utf-8")
    combined = json.dumps({"schema": schema, "fixture": fixture}, sort_keys=True)
    assert CONTRACT in documentation
    assert "db50539a8616bb29b6735b95a60ff401ce0f10d2" in documentation
    assert "story-map-v2-derived-semantic-workflow-v2" in documentation
    assert "9657c6e" not in documentation

    forbidden_keys = {
        "prompt",
        "source",
        "source_text",
        "request_bytes",
        "response",
        "response_bytes",
        "stderr",
        "credentials",
        "absolute_path",
    }
    for node in _objects(fixture):
        assert forbidden_keys.isdisjoint(node)
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", combined)
    assert "\\\\" not in combined
    for value in (item for item in _walk_strings(fixture) if item.startswith("/")):
        assert value in ROUTES.values()


def _walk_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)

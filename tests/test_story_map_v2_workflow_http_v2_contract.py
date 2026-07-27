from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from renpy_story_mapper.story_map_v2.workflow_http_contract import (
    WORKFLOW_HTTP_COHERENCE,
    WorkflowHttpContractCoherenceError,
    validate_workflow_http_contract_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "src"
    / "renpy_story_mapper"
    / "story_map_v2"
    / "schemas"
    / "story_map_workflow_http_v2.schema.json"
)
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "story_map_v2"
    / "phase04_workflow_http_v2.json"
)
DOC_PATH = (
    ROOT
    / "docs"
    / "milestones"
    / "M15_PHASE_04"
    / "TRACK_B_WORKFLOW_HTTP_V2_CONTRACT.md"
)
CONTRACT = "story-map-v2-workflow-http-v2"
COMMANDS = ("prepare", "start", "cancel", "resume", "retry", "status")
ROUTES = {
    command: f"/api/v1/story-map-v2/workflow/{command}" for command in COMMANDS
}
Mutation = Callable[[dict[str, Any]], None]


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


def test_workflow_http_v2_schema_and_fixture_are_frozen() -> None:
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

    Draft202012Validator.check_schema(schema)
    assert not tuple(Draft202012Validator(schema).iter_errors(fixture))
    validate_workflow_http_contract_bundle(fixture)


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
    documentation = DOC_PATH.read_text(encoding="utf-8")
    fixture_serialized = json.dumps(fixture, sort_keys=True)
    assert CONTRACT in documentation
    assert WORKFLOW_HTTP_COHERENCE in documentation
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
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", fixture_serialized)
    assert "\\\\" not in fixture_serialized
    for value in (item for item in _walk_strings(fixture) if item.startswith("/")):
        assert value in ROUTES.values()


def _set_path(*path: str, value: object) -> Mutation:
    def mutate(bundle: dict[str, Any]) -> None:
        target: dict[str, Any] = bundle
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _append_foreign_cloud_cache(bundle: dict[str, Any]) -> None:
    bundle["examples"]["successes"]["prepare"]["preview"]["cache_hits"][
        "cloud_job_ids"
    ].append("job:foreign")


def _duplicate_mapping_job(bundle: dict[str, Any]) -> None:
    jobs = bundle["examples"]["successes"]["prepare"]["preview"]["jobs"]
    duplicate = deepcopy(jobs[0])
    duplicate["scope_id"] = "scope:duplicate"
    duplicate["chunk_id"] = "chunk:duplicate"
    jobs.append(duplicate)


def _append_unknown_route_corridor(bundle: dict[str, Any]) -> None:
    plan = bundle["examples"]["successes"]["prepare"]["preview"][
        "derived_semantic_plan"
    ]
    plan["route_memberships"].append(
        {"route_id": "route:unknown", "ordered_corridor_ids": ["chunk:missing"]}
    )


MUTATIONS: tuple[tuple[str, Mutation], ...] = (
    (
        "cancelled_resume_success",
        _set_path(
            "examples", "successes", "resume", "status", "cancelled", value=True
        ),
    ),
    (
        "start_status_not_approved",
        _set_path(
            "examples", "successes", "start", "status", "approved", value=False
        ),
    ),
    (
        "prepare_bucket_wrong_command",
        _set_path("examples", "successes", "prepare", "command", value="start"),
    ),
    (
        "retry_wrong_job_lineage",
        _set_path(
            "examples",
            "successes",
            "retry",
            "retry_approval",
            "job_id",
            value="job:foreign",
        ),
    ),
    (
        "indeterminate_count_mismatch",
        _set_path(
            "examples", "successes", "status", "status", "indeterminate_jobs", value=1
        ),
    ),
    (
        "derived_formula_mismatch",
        _set_path(
            "examples",
            "successes",
            "prepare",
            "preview",
            "derived_semantic_plan",
            "final_overview_calls",
            value=0,
        ),
    ),
    ("unknown_route_corridor", _append_unknown_route_corridor),
    (
        "nonstale_bucket_code_mismatch",
        _set_path(
            "examples",
            "non_stale_errors",
            "invalid_workflow_request",
            "error",
            "code",
            value="workflow_unavailable",
        ),
    ),
    (
        "stale_bucket_code_mismatch",
        _set_path(
            "examples",
            "stale_errors",
            "stale_workflow_preview",
            "error",
            "code",
            value="stale_workflow_approval",
        ),
    ),
    (
        "approval_preview_mismatch",
        _set_path(
            "examples",
            "successes",
            "start",
            "approval",
            "preview_identity",
            value="f" * 64,
        ),
    ),
    (
        "status_preview_mismatch",
        _set_path(
            "examples",
            "successes",
            "start",
            "status",
            "preview_identity",
            value="f" * 64,
        ),
    ),
    (
        "loopback_privacy_false",
        _set_path(
            "examples",
            "successes",
            "prepare",
            "preview",
            "privacy",
            "loopback_story_content",
            value=False,
        ),
    ),
    ("cloud_cache_foreign_job", _append_foreign_cloud_cache),
    ("duplicate_mapping_job", _duplicate_mapping_job),
    (
        "absolute_path_error_message",
        _set_path(
            "examples",
            "non_stale_errors",
            "invalid_workflow_request",
            "error",
            "message",
            value="Request exposed /opt/private/story.rpy",
        ),
    ),
)


@pytest.mark.parametrize(("mutation_name", "mutate"), MUTATIONS)
def test_schema_and_coherence_validator_fail_closed_on_adversarial_mutations(
    mutation_name: str,
    mutate: Mutation,
) -> None:
    schema = _load(SCHEMA_PATH)
    bundle = deepcopy(_load(FIXTURE_PATH))
    mutate(bundle)

    schema_failures = tuple(Draft202012Validator(schema).iter_errors(bundle))
    coherence_failure: WorkflowHttpContractCoherenceError | None = None
    try:
        validate_workflow_http_contract_bundle(bundle)
    except WorkflowHttpContractCoherenceError as exc:
        coherence_failure = exc

    assert schema_failures or coherence_failure is not None, mutation_name


def _walk_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)

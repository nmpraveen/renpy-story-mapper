"""Provider-free coherence validation for the Story Map V2 workflow HTTP v2 seam."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Final, cast

WORKFLOW_HTTP_CONTRACT: Final = "story-map-v2-workflow-http-v2"
WORKFLOW_HTTP_COHERENCE: Final = "story-map-v2-workflow-http-coherence-v1"
DERIVED_SEMANTIC_FAN_IN: Final = 24
WORKFLOW_HTTP_ERROR_MESSAGES: Final[Mapping[str, str]] = {
    "stale_workflow_preview": "The workflow preview has changed.",
    "stale_workflow_approval": "The workflow approval is stale.",
    "invalid_workflow_request": "The workflow request is invalid.",
    "workflow_run_not_found": "The workflow run is unavailable.",
    "workflow_command_conflict": "The workflow command is not available.",
    "workflow_request_too_large": "The workflow request is too large.",
    "workflow_internal_error": "The workflow command could not be completed.",
    "workflow_unavailable": "The workflow service is unavailable.",
}

_COMMANDS: Final = frozenset({"prepare", "start", "cancel", "resume", "retry", "status"})
_CALL_KINDS: Final = frozenset(
    {
        "mapping",
        "replacement_review",
        "refusal_fallback",
        "section_synthesis",
        "rollup_synthesis",
    }
)
_ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|(?<![A-Za-z0-9._-])/(?!/)[^\s\"'<>]+)"
)
_DERIVED_FIELDS: Final = (
    "section_synthesis_calls",
    "route_reduction_calls",
    "route_summary_calls",
    "whole_game_reduction_calls",
    "final_overview_calls",
    "rollup_synthesis_calls",
)


class WorkflowHttpContractCoherenceError(ValueError):
    """A schema-valid workflow value violates a normative cross-field invariant."""


def derived_reduce_calls(count: int, *, fan_in: int = DERIVED_SEMANTIC_FAN_IN) -> int:
    """Return the frozen consecutive fan-in reduction-call upper bound."""

    if type(count) is not int or count < 0:
        raise WorkflowHttpContractCoherenceError("derived reduction count is invalid")
    if fan_in != DERIVED_SEMANTIC_FAN_IN:
        raise WorkflowHttpContractCoherenceError("derived semantic fan-in must be 24")
    total = 0
    while count > fan_in:
        count = math.ceil(count / fan_in)
        total += count
    return total


def validate_workflow_http_preview(value: object) -> None:
    """Validate membership, privacy, cache, and derived-ceiling coherence."""

    preview = _mapping(value, "workflow preview")
    jobs = _sequence(preview.get("jobs"), "workflow jobs")
    job_ids = tuple(_text(_mapping(item, "workflow job").get("job_id"), "job_id") for item in jobs)
    if len(set(job_ids)) != len(job_ids):
        raise WorkflowHttpContractCoherenceError("mapping job IDs must be unique")

    cache_hits = _mapping(preview.get("cache_hits"), "cache hits")
    cloud_hits = _text_sequence(cache_hits.get("cloud_job_ids"), "cloud cache jobs")
    loopback_hits = _text_sequence(
        cache_hits.get("loopback_job_ids"), "loopback cache jobs"
    )
    known_jobs = set(job_ids)
    if not set(cloud_hits).issubset(known_jobs) or not set(loopback_hits).issubset(
        known_jobs
    ):
        raise WorkflowHttpContractCoherenceError("cache hits must identify mapping jobs")
    if set(cloud_hits) & set(loopback_hits):
        raise WorkflowHttpContractCoherenceError("cloud and loopback cache hits overlap")

    policy = _mapping(preview.get("policy"), "workflow policy")
    privacy = _mapping(preview.get("privacy"), "workflow privacy")
    primary = _mapping(policy.get("cloud"), "primary provider")
    primary_mode = _text(primary.get("mode"), "primary provider mode")
    fallback = _boolean(policy.get("allow_refusal_fallback"), "fallback permission")
    has_loopback = policy.get("loopback") is not None
    loopback_content = _boolean(
        privacy.get("loopback_story_content"), "loopback privacy scope"
    )
    if fallback != has_loopback or loopback_content != (
        fallback or primary_mode == "loopback"
    ):
        raise WorkflowHttpContractCoherenceError(
            "loopback provider, consent, and privacy scope must agree"
        )
    cloud_content = _boolean(privacy.get("cloud_story_content"), "cloud privacy scope")
    if cloud_content != (primary_mode == "cloud"):
        raise WorkflowHttpContractCoherenceError("cloud story scope must match provider mode")
    for key in (
        "durable_raw_requests",
        "durable_raw_responses",
        "durable_provider_diagnostics",
        "durable_absolute_paths",
    ):
        if _boolean(privacy.get(key), key):
            raise WorkflowHttpContractCoherenceError("durable sensitive material is forbidden")

    derived = _mapping(preview.get("derived_semantic_plan"), "derived semantic plan")
    if _text(derived.get("authority_identity"), "derived authority identity") != _text(
        preview.get("authority_identity"), "preview authority identity"
    ):
        raise WorkflowHttpContractCoherenceError("derived authority changed from preview")
    fan_in = _integer(derived.get("fan_in"), "derived fan-in")
    if fan_in != DERIVED_SEMANTIC_FAN_IN:
        raise WorkflowHttpContractCoherenceError("derived semantic fan-in must be 24")

    corridor_values = _sequence(derived.get("corridors"), "derived corridors")
    corridors = tuple(_mapping(item, "derived corridor") for item in corridor_values)
    corridor_ids = tuple(_text(item.get("corridor_id"), "corridor_id") for item in corridors)
    if len(set(corridor_ids)) != len(corridor_ids):
        raise WorkflowHttpContractCoherenceError("corridor IDs must be unique")
    if tuple(_integer(item.get("ordinal"), "corridor ordinal") for item in corridors) != tuple(
        range(len(corridors))
    ):
        raise WorkflowHttpContractCoherenceError("corridor ordinals must be consecutive")
    corridor_by_id = dict(zip(corridor_ids, corridors, strict=True))

    membership_values = _sequence(
        derived.get("route_memberships"), "route memberships"
    )
    memberships = tuple(_mapping(item, "route membership") for item in membership_values)
    route_ids = tuple(_text(item.get("route_id"), "route_id") for item in memberships)
    if len(set(route_ids)) != len(route_ids):
        raise WorkflowHttpContractCoherenceError("persistent route IDs must be unique")
    referenced: list[str] = []
    route_upper_bounds: list[int] = []
    for membership, route_id in zip(memberships, route_ids, strict=True):
        member_ids = _text_sequence(
            membership.get("ordered_corridor_ids"), "route corridor IDs"
        )
        if not member_ids or len(set(member_ids)) != len(member_ids):
            raise WorkflowHttpContractCoherenceError(
                "route corridor membership must be nonempty and unique"
            )
        upper_bound = 0
        for corridor_id in member_ids:
            corridor = corridor_by_id.get(corridor_id)
            if corridor is None:
                raise WorkflowHttpContractCoherenceError(
                    "route membership references an unknown corridor"
                )
            if corridor.get("route_owner") != route_id:
                raise WorkflowHttpContractCoherenceError(
                    "route membership does not match the corridor owner"
                )
            referenced.append(corridor_id)
            upper_bound += _positive_integer(
                corridor.get("event_slot_upper_bound"), "event slot upper bound"
            )
        route_upper_bounds.append(upper_bound)
    owned = [
        corridor_id
        for corridor_id, corridor in corridor_by_id.items()
        if corridor.get("route_owner") is not None
    ]
    if len(set(referenced)) != len(referenced) or set(referenced) != set(owned):
        raise WorkflowHttpContractCoherenceError(
            "persistent corridors require exactly one route membership"
        )

    common = sum(
        _positive_integer(item.get("event_slot_upper_bound"), "event slot upper bound")
        for item in corridors
        if item.get("route_owner") is None
    )
    expected = {
        "section_synthesis_calls": len(corridors),
        "route_reduction_calls": sum(
            derived_reduce_calls(count, fan_in=fan_in) for count in route_upper_bounds
        ),
        "route_summary_calls": len(memberships),
        "whole_game_reduction_calls": derived_reduce_calls(
            common + len(memberships), fan_in=fan_in
        ),
        "final_overview_calls": int(common + len(memberships) > 0),
    }
    expected["rollup_synthesis_calls"] = sum(
        expected[key]
        for key in (
            "route_reduction_calls",
            "route_summary_calls",
            "whole_game_reduction_calls",
            "final_overview_calls",
        )
    )
    ceilings = _mapping(preview.get("ceilings"), "workflow ceilings")
    for key, expected_value in expected.items():
        if _integer(derived.get(key), key) != expected_value or _integer(
            ceilings.get(key), key
        ) != expected_value:
            raise WorkflowHttpContractCoherenceError(
                "derived semantic ceiling formula does not match"
            )


def validate_workflow_http_success(
    value: object,
    *,
    expected_command: str | None = None,
    request: object | None = None,
) -> None:
    """Validate one schema-valid successful response and optional originating request."""

    envelope = _mapping(value, "workflow success envelope")
    _contract(envelope)
    command = _text(envelope.get("command"), "workflow command")
    if command not in _COMMANDS or (
        expected_command is not None and command != expected_command
    ):
        raise WorkflowHttpContractCoherenceError("workflow command bucket mismatch")
    preview = _mapping(envelope.get("preview"), "workflow preview")
    validate_workflow_http_preview(preview)
    run_id = _text(preview.get("run_id"), "preview run_id")
    preview_identity = _text(preview.get("preview_identity"), "preview identity")

    status = _mapping(envelope.get("status"), "workflow status")
    if _text(status.get("run_id"), "status run_id") != run_id or _text(
        status.get("preview_identity"), "status preview identity"
    ) != preview_identity:
        raise WorkflowHttpContractCoherenceError("status lineage does not match preview")
    cancelled = _boolean(status.get("cancelled"), "cancelled status")
    if cancelled and (
        _boolean(status.get("can_start"), "can_start")
        or _boolean(status.get("can_resume"), "can_resume")
    ):
        raise WorkflowHttpContractCoherenceError("cancelled workflow actions are terminal")

    retries = tuple(
        _mapping(item, "indeterminate retry")
        for item in _sequence(status.get("indeterminate_retries"), "indeterminate retries")
    )
    if _integer(status.get("indeterminate_jobs"), "indeterminate job count") != len(
        retries
    ):
        raise WorkflowHttpContractCoherenceError("indeterminate job count is inconsistent")
    retry_pairs: set[tuple[str, str]] = set()
    for retry in retries:
        pair = (
            _text(retry.get("job_id"), "retry job_id"),
            _text(retry.get("attempt_id"), "retry attempt_id"),
        )
        if pair in retry_pairs:
            raise WorkflowHttpContractCoherenceError("indeterminate retry lineage is duplicated")
        retry_pairs.add(pair)
        if _text(retry.get("call_kind"), "retry call kind") not in _CALL_KINDS:
            raise WorkflowHttpContractCoherenceError("indeterminate call kind is invalid")

    approval = _mapping(envelope.get("approval"), "workflow approval")
    approval_state = _text(approval.get("state"), "approval state")
    approved = _boolean(status.get("approved"), "approved status")
    if approval_state == "not_approved":
        if approved or any(
            approval.get(key) is not None
            for key in (
                "approval_identity",
                "preview_identity",
                "plan_id",
                "authority_identity",
            )
        ):
            raise WorkflowHttpContractCoherenceError("unapproved lineage is inconsistent")
    elif approval_state == "approved":
        if not approved or (
            approval.get("preview_identity") != preview_identity
            or approval.get("plan_id") != preview.get("plan_id")
            or approval.get("authority_identity") != preview.get("authority_identity")
        ):
            raise WorkflowHttpContractCoherenceError("approval lineage does not match preview")
    else:
        raise WorkflowHttpContractCoherenceError("approval state is invalid")

    if command == "prepare" and approval_state != "not_approved":
        raise WorkflowHttpContractCoherenceError("prepare cannot carry approval")
    if command in {"start", "resume", "retry"} and approval_state != "approved":
        raise WorkflowHttpContractCoherenceError("command requires exact preview approval")
    if command == "resume" and cancelled:
        raise WorkflowHttpContractCoherenceError("cancelled runs cannot resume")
    if command == "cancel" and not cancelled:
        raise WorkflowHttpContractCoherenceError("cancel response must be terminal")

    retry_approval = envelope.get("retry_approval")
    if command != "retry":
        if retry_approval is not None:
            raise WorkflowHttpContractCoherenceError("foreign retry approval is inapplicable")
        return
    retry_value = _mapping(retry_approval, "retry approval")
    if retry_value.get("preview_identity") != preview_identity:
        raise WorkflowHttpContractCoherenceError("retry approval changed preview identity")
    if request is not None:
        request_value = _mapping(request, "retry request")
        if (
            retry_value.get("job_id") != request_value.get("job_id")
            or retry_value.get("indeterminate_attempt_id")
            != request_value.get("indeterminate_attempt_id")
            or retry_value.get("preview_identity") != request_value.get("preview_identity")
            or run_id != request_value.get("run_id")
        ):
            raise WorkflowHttpContractCoherenceError("retry approval lineage changed")


def validate_workflow_http_error(value: object, *, expected_code: str) -> None:
    """Validate one schema-valid sanitized error bucket."""

    envelope = _mapping(value, "workflow error envelope")
    _contract(envelope)
    error = _mapping(envelope.get("error"), "workflow error")
    code = _text(error.get("code"), "error code")
    if code != expected_code:
        raise WorkflowHttpContractCoherenceError("workflow error bucket mismatch")
    expected_message = WORKFLOW_HTTP_ERROR_MESSAGES.get(code)
    if expected_message is None or error.get("message") != expected_message:
        raise WorkflowHttpContractCoherenceError(
            "workflow error message is not the fixed safe value"
        )
    for item in _strings(error):
        if _ABSOLUTE_PATH.search(item) is not None:
            raise WorkflowHttpContractCoherenceError("workflow error contains an absolute path")


def validate_workflow_http_contract_bundle(value: object) -> None:
    """Validate the public schema bundle with all normative coherence rules."""

    bundle = _mapping(value, "workflow contract bundle")
    _contract(bundle)
    examples = _mapping(bundle.get("examples"), "workflow examples")
    requests = _mapping(examples.get("requests"), "workflow requests")
    successes = _mapping(examples.get("successes"), "workflow successes")
    for command in ("prepare", "start", "cancel", "resume", "retry", "status"):
        validate_workflow_http_success(
            successes.get(command),
            expected_command=command,
            request=requests.get(command),
        )
    for bucket_name, envelope in _mapping(
        examples.get("stale_errors"), "stale errors"
    ).items():
        validate_workflow_http_error(envelope, expected_code=bucket_name)
    for bucket_name, envelope in _mapping(
        examples.get("non_stale_errors"), "non-stale errors"
    ).items():
        validate_workflow_http_error(envelope, expected_code=bucket_name)


def _contract(value: Mapping[str, object]) -> None:
    if value.get("contract") != WORKFLOW_HTTP_CONTRACT:
        raise WorkflowHttpContractCoherenceError("workflow HTTP contract version mismatch")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise WorkflowHttpContractCoherenceError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise WorkflowHttpContractCoherenceError(f"{label} must be a list")
    return value


def _text_sequence(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(item, label) for item in _sequence(value, label))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WorkflowHttpContractCoherenceError(f"{label} must be nonempty text")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise WorkflowHttpContractCoherenceError(f"{label} must be nonnegative")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _integer(value, label)
    if result < 1:
        raise WorkflowHttpContractCoherenceError(f"{label} must be positive")
    return result


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise WorkflowHttpContractCoherenceError(f"{label} must be a boolean")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(item for child in value.values() for item in _strings(child))
    if isinstance(value, list):
        return tuple(item for child in value for item in _strings(child))
    return ()


__all__ = [
    "DERIVED_SEMANTIC_FAN_IN",
    "WORKFLOW_HTTP_COHERENCE",
    "WORKFLOW_HTTP_CONTRACT",
    "WorkflowHttpContractCoherenceError",
    "derived_reduce_calls",
    "validate_workflow_http_contract_bundle",
    "validate_workflow_http_error",
    "validate_workflow_http_preview",
    "validate_workflow_http_success",
]

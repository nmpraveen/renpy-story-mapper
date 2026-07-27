"""Privacy-safe HTTP projections for the frozen Phase 04 workflow contract."""

from __future__ import annotations

from dataclasses import asdict

from renpy_story_mapper.story_map_v2.phase04_sections import (
    DERIVED_FAST_MODE,
    DERIVED_MODEL,
    DERIVED_PROVIDER,
    DERIVED_REASONING,
    ROLLUP_SYNTHESIS_ADAPTER_VERSION,
    ROLLUP_SYNTHESIS_PROMPT_VERSION,
    ROLLUP_SYNTHESIS_SCHEMA_VERSION,
    SECTION_SYNTHESIS_ADAPTER_VERSION,
    SECTION_SYNTHESIS_PROMPT_VERSION,
    SECTION_SYNTHESIS_SCHEMA_VERSION,
)
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    JobRetryApproval,
    ProviderSettings,
    WorkflowApproval,
    WorkflowDerivedSemanticPlanDescriptor,
    WorkflowPreview,
    WorkflowStatus,
)
from renpy_story_mapper.story_map_v2.workflow_http_contract import (
    validate_workflow_http_success,
)

WORKFLOW_HTTP_CONTRACT = "story-map-v2-workflow-http-v2"
WORKFLOW_HTTP_ROUTES = {
    "contract": WORKFLOW_HTTP_CONTRACT,
    "prepare": "/api/v1/story-map-v2/workflow/prepare",
    "start": "/api/v1/story-map-v2/workflow/start",
    "cancel": "/api/v1/story-map-v2/workflow/cancel",
    "resume": "/api/v1/story-map-v2/workflow/resume",
    "retry": "/api/v1/story-map-v2/workflow/retry",
    "status": "/api/v1/story-map-v2/workflow/status",
}


def workflow_success_envelope(
    command: str,
    preview: WorkflowPreview,
    status: WorkflowStatus,
    approval: WorkflowApproval | None,
    *,
    retry_approval: JobRetryApproval | None = None,
) -> dict[str, object]:
    """Project and self-check one exact successful browser response."""

    value: dict[str, object] = {
        "contract": WORKFLOW_HTTP_CONTRACT,
        "command": command,
        "preview": workflow_preview_object(preview),
        "approval": workflow_approval_object(approval),
        "status": workflow_status_object(status),
        "retry_approval": (
            None
            if retry_approval is None
            else {
                "retry_approval_identity": retry_approval.identity,
                "preview_identity": retry_approval.preview_identity,
                "job_id": retry_approval.job_id,
                "indeterminate_attempt_id": retry_approval.indeterminate_attempt_id,
            }
        ),
    }
    validate_workflow_http_success(value, expected_command=command)
    return value


def workflow_preview_object(preview: WorkflowPreview) -> dict[str, object]:
    derived = preview.plan.derived_semantic_plan
    if derived is None:
        raise ValueError("Phase 04 browser preview requires a derived semantic plan")
    return {
        "run_id": preview.run_id,
        "preview_identity": preview.identity,
        "plan_id": preview.plan.plan_id,
        "authority_identity": preview.plan.authority_identity.value,
        "jobs": [
            {
                "job_id": item.job_id,
                "scope_id": item.scope_id,
                "chunk_id": item.chunk_id,
                "critical": item.critical,
            }
            for item in preview.plan.jobs
        ],
        "derived_semantic_plan": _derived_plan_object(derived),
        "cache_hits": {
            "cloud_job_ids": list(preview.cache_hit_job_ids),
            "loopback_job_ids": list(preview.loopback_cache_hit_job_ids),
        },
        "policy": {
            "policy_version": preview.policy.policy_version,
            "prompt_version": preview.policy.prompt_version,
            "schema_version": preview.policy.schema_version,
            "cloud": _provider_object(preview.policy.cloud),
            "loopback": (
                None
                if preview.policy.loopback is None
                else _provider_object(preview.policy.loopback)
            ),
            "allow_refusal_fallback": preview.policy.allow_refusal_fallback,
            "section_synthesis": _derived_provider_object(
                SECTION_SYNTHESIS_PROMPT_VERSION,
                SECTION_SYNTHESIS_SCHEMA_VERSION,
                SECTION_SYNTHESIS_ADAPTER_VERSION,
            ),
            "rollup_synthesis": _derived_provider_object(
                ROLLUP_SYNTHESIS_PROMPT_VERSION,
                ROLLUP_SYNTHESIS_SCHEMA_VERSION,
                ROLLUP_SYNTHESIS_ADAPTER_VERSION,
            ),
        },
        "ceilings": asdict(preview.ceilings),
        "privacy": asdict(preview.privacy),
    }


def workflow_approval_object(approval: WorkflowApproval | None) -> dict[str, object]:
    if approval is None:
        return {
            "state": "not_approved",
            "approval_identity": None,
            "preview_identity": None,
            "plan_id": None,
            "authority_identity": None,
        }
    return {
        "state": "approved",
        "approval_identity": approval.identity,
        "preview_identity": approval.preview_identity,
        "plan_id": approval.plan_id,
        "authority_identity": approval.authority_identity.value,
    }


def workflow_status_object(status: WorkflowStatus) -> dict[str, object]:
    unfinished = (
        status.pending_jobs
        + status.active_jobs
        + status.resumable_jobs
        + status.indeterminate_jobs
    )
    return {
        "run_id": status.run_id,
        "preview_identity": status.preview_identity,
        "approved": status.approved,
        "cancelled": status.cancelled,
        "pending_jobs": status.pending_jobs,
        "active_jobs": status.active_jobs,
        "accepted_jobs": status.accepted_jobs,
        "structural_fallback_jobs": status.structural_fallback_jobs,
        "resumable_jobs": status.resumable_jobs,
        "indeterminate_jobs": status.indeterminate_jobs,
        "accounting": asdict(status.accounting),
        "can_approve": not status.approved and not status.cancelled,
        "can_start": not status.approved and not status.cancelled,
        "can_cancel": not status.cancelled and unfinished > 0,
        "can_resume": (
            status.approved
            and not status.cancelled
            and status.active_jobs == 0
            and status.resumable_jobs > 0
        ),
        "indeterminate_retries": [
            {
                "job_id": item.job_id,
                "attempt_id": item.attempt_id,
                "call_kind": item.call_kind.value,
                "approval_state": (
                    "required" if item.retry_approval_identity is None else "approved"
                ),
                "retry_approval_identity": item.retry_approval_identity,
                "can_approve_retry": item.can_approve_retry,
            }
            for item in status.indeterminate_retries
        ],
    }


def _provider_object(settings: ProviderSettings) -> dict[str, object]:
    return {
        "provider": settings.provider,
        "model": settings.model,
        "reasoning": settings.reasoning,
        "fast_mode": settings.fast_mode,
        "mode": settings.mode.value,
        "adapter_version": settings.adapter_version,
    }


def _derived_provider_object(
    prompt_version: str,
    schema_version: str,
    adapter_version: str,
) -> dict[str, object]:
    return {
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "provider": DERIVED_PROVIDER,
        "model": DERIVED_MODEL,
        "reasoning": DERIVED_REASONING,
        "fast_mode": DERIVED_FAST_MODE,
        "mode": "cloud",
        "adapter_version": adapter_version,
    }


def _derived_plan_object(
    plan: WorkflowDerivedSemanticPlanDescriptor,
) -> dict[str, object]:
    return {
        "semantic_plan_identity": plan.semantic_plan_identity,
        "story_chunk_plan_identity": plan.story_chunk_plan_identity,
        "authority_identity": plan.authority_identity.value,
        "corridors": [
            {
                "corridor_id": item.corridor_id,
                "route_owner": item.route_owner,
                "event_slot_upper_bound": item.event_slot_upper_bound,
                "ordinal": item.ordinal,
            }
            for item in plan.corridors
        ],
        "route_memberships": [
            {
                "route_id": item.route_id,
                "ordered_corridor_ids": list(item.ordered_corridor_ids),
            }
            for item in plan.route_memberships
        ],
        "fan_in": plan.fan_in,
        "section_synthesis_calls": plan.section_synthesis_calls,
        "route_reduction_calls": plan.route_reduction_calls,
        "route_summary_calls": plan.route_summary_calls,
        "whole_game_reduction_calls": plan.whole_game_reduction_calls,
        "final_overview_calls": plan.final_overview_calls,
        "rollup_synthesis_calls": plan.rollup_synthesis_calls,
    }

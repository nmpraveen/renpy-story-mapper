from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    ProviderCancelledError,
    ProviderOutputItem,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderUsage,
)
from renpy_story_mapper.project import create_ingested_project
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.state import UserStateStore

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


@dataclass
class _Provider:
    requests: list[ProviderRequest] = field(default_factory=list)

    def status(self) -> ProviderStatus:
        return ProviderStatus(True, "test-cloud", "test-adapter", "test-adapter-v1")

    def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
        del cancelled
        self.requests.append(request)
        identity = ProviderIdentity(
            "test-cloud",
            "test-adapter",
            "test-adapter-v1",
            request.requested_model,
            request.requested_model,
            ProviderSettings(),
        )
        return ProviderResponse(
            request.request_id,
            identity,
            tuple(
                ProviderOutputItem(
                    item.logical_job_id,
                    index,
                    {
                        "logical_job_id": item.logical_job_id,
                        "title": f"Narrative {index + 1}",
                        "summary": "A bounded validated narrative summary.",
                        "claims": [
                            {
                                "claim_class": "factual",
                                "context_scope": "atomic",
                                "text": "A directly supported narrative fact.",
                                "evidence_handles": (
                                    ["E1"] if item.payload["job_kind"] == "scene" else []
                                ),
                                "child_claim_handles": (
                                    [] if item.payload["job_kind"] == "scene" else ["C1"]
                                ),
                                "subject": "story",
                                "predicate": "contains",
                                "polarity": "positive",
                                "normalized_value": "supported",
                            }
                        ],
                    },
                )
                for index, item in enumerate(request.items)
            ),
            ProviderUsage(10, 5, 1),
            PROMPT_TEMPLATE_VERSION,
            RESPONSE_SCHEMA_VERSION,
        )

    def cancel(self) -> None:
        return


@dataclass
class _BlockingAfterFirstProvider(_Provider):
    first_completed: Event = field(default_factory=Event)
    second_started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    cancel_calls: int = 0

    def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
        if not self.requests:
            response = super().submit(request, cancelled)
            self.first_completed.set()
            return response
        self.requests.append(request)
        self.second_started.set()
        while not self.release.wait(0.01):
            if callable(cancelled) and cancelled():
                raise ProviderCancelledError("cancelled", "M13 provider call cancelled")
        raise ProviderCancelledError("cancelled", "M13 provider call cancelled")

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.release.set()


def _api(tmp_path: Path, provider: _Provider | None = None) -> ProjectApi:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m13_provider_factory=(None if provider is None else lambda: provider),
    )
    api._retain_project_path(project_path, source)
    return api


def test_m13_api_advertises_bounded_provider_free_snapshot(tmp_path: Path) -> None:
    api = _api(tmp_path)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert bootstrap["routes"]["m13"] == {
            "snapshot": "/api/v1/m13/snapshot",
            "artifact": "/api/v1/m13/artifact",
            "citations": "/api/v1/m13/citations",
            "prepare": "/api/v1/m13/prepare",
            "start": "/api/v1/m13/start",
            "status": "/api/v1/m13/status",
            "cancel": "/api/v1/m13/cancel",
        }
        snapshot = api.dispatch(
            "POST",
            "/api/v1/m13/snapshot",
            {"offset": 0, "limit": 25},
        )
        assert snapshot["status"] == "available"
        assert snapshot["cloud_enabled"] is False
        assert snapshot["total"] == 0
        assert snapshot["coverage"]["expected_scene_jobs"] > 0

        with pytest.raises(ValueError, match="unsupported fields"):
            api.dispatch(
                "POST",
                "/api/v1/m13/snapshot",
                {"offset": 0, "limit": 25, "raw_prompt": True},
            )
    finally:
        api.close()


def test_m13_api_fails_closed_for_unknown_artifact_and_claim(tmp_path: Path) -> None:
    api = _api(tmp_path)
    try:
        with pytest.raises(ApiProblem) as artifact_error:
            api.dispatch(
                "POST",
                "/api/v1/m13/artifact",
                {"artifact_id": "m13_artifact_unknown"},
            )
        assert artifact_error.value.status == 404
        assert artifact_error.value.code == "m13_artifact_not_found"

        with pytest.raises(ApiProblem) as claim_error:
            api.dispatch(
                "POST",
                "/api/v1/m13/citations",
                {"claim_id": "m13_claim_unknown"},
            )
        assert claim_error.value.status == 404
        assert claim_error.value.code == "m13_claim_not_found"
    finally:
        api.close()


def test_m13_api_prepares_without_transmission_then_runs_one_confirmed_manifest(
    tmp_path: Path,
) -> None:
    provider = _Provider()
    api = _api(tmp_path, provider)
    request = {
        "requested_model": "runtime-model",
        "mode": "fact_only",
        "include_m12_material": True,
        "limits": {
            "max_provider_calls": 500,
            "max_input_tokens": 20_000_000,
            "max_output_tokens": 20_000_000,
            "max_total_tokens": 40_000_000,
            "timeout_seconds": 300,
            "max_concurrency": 4,
            "max_cost_micros": None,
        },
        "batch_limits": {
            "maximum_items": 16,
            "maximum_input_chars": 500_000,
            "maximum_input_tokens": 100_000,
        },
    }
    try:
        preview = api.dispatch("POST", "/api/v1/m13/prepare", request)
        assert preview["consent_granted"] is False
        assert preview["cloud_enabled"] is False
        assert preview["requires_confirm_cloud"] is True
        assert preview["selected_scope_ids"] == ["project:all-current-scenes"]
        assert preview["estimate"]["logical_job_count"] > preview["selected_scene_count"]
        assert preview["estimate"]["provider_call_count"] > 0
        assert preview["estimate"]["cost_confidence"] == "unavailable"
        assert provider.requests == []

        with pytest.raises(ApiProblem) as consent_error:
            api.dispatch(
                "POST",
                "/api/v1/m13/start",
                {"preparation_id": preview["preparation_id"], "confirm_cloud": False},
            )
        assert consent_error.value.code == "m13_consent_required"
        assert provider.requests == []

        started = api.dispatch(
            "POST",
            "/api/v1/m13/start",
            {"preparation_id": preview["preparation_id"], "confirm_cloud": True},
        )
        assert started["state"] in {"running", "succeeded"}
        deadline = time.monotonic() + 20
        while True:
            status = api.dispatch("POST", "/api/v1/m13/status", {})
            if status["state"] not in {"running", "cancelling"}:
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert status["state"] == "succeeded"
        assert status["latest_run"]["usage"]["provider_calls"] > 0
        assert status["durable_completed_work_preserved"] is True
        assert provider.requests
    finally:
        api.close()


def test_m13_api_cancellation_reaches_provider_and_preserves_validated_artifacts(
    tmp_path: Path,
) -> None:
    provider = _BlockingAfterFirstProvider()
    api = _api(tmp_path, provider)
    request = {
        "requested_model": "runtime-model",
        "mode": "fact_only",
        "include_m12_material": True,
        "limits": {
            "max_provider_calls": 500,
            "max_input_tokens": 20_000_000,
            "max_output_tokens": 20_000_000,
            "max_total_tokens": 40_000_000,
            "timeout_seconds": 300,
            "max_concurrency": 1,
            "max_cost_micros": None,
        },
        "batch_limits": {
            "maximum_items": 1,
            "maximum_input_chars": 500_000,
            "maximum_input_tokens": 100_000,
        },
    }
    try:
        preview = api.dispatch("POST", "/api/v1/m13/prepare", request)
        api.dispatch(
            "POST",
            "/api/v1/m13/start",
            {"preparation_id": preview["preparation_id"], "confirm_cloud": True},
        )
        assert provider.first_completed.wait(10)
        assert provider.second_started.wait(10)

        cancelling = api.dispatch("POST", "/api/v1/m13/cancel", {})
        assert cancelling["state"] in {"cancelling", "cancelled"}
        deadline = time.monotonic() + 20
        while True:
            status = api.dispatch("POST", "/api/v1/m13/status", {})
            if status["state"] not in {"running", "cancelling"}:
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)

        snapshot = api.dispatch(
            "POST",
            "/api/v1/m13/snapshot",
            {"offset": 0, "limit": 200},
        )
        assert status["state"] == "cancelled"
        assert status["durable_completed_work_preserved"] is True
        assert provider.cancel_calls >= 1
        assert snapshot["coverage"]["published_scene_jobs"] >= 1
        assert any(job["artifact"] is not None for job in snapshot["jobs"])
    finally:
        provider.release.set()
        api.close()

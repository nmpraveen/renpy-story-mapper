from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event

import pytest

from renpy_story_mapper.m12_service import M12RouteService
from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.persistence import LookupState, RecordKind
from renpy_story_mapper.narrative.provider import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    ProviderCancelledError,
    ProviderOutputItem,
    ProviderRequest,
    ProviderResponse,
    ProviderRuntimeConfigurationError,
    ProviderStatus,
    ProviderTimeoutError,
    ProviderUsage,
)
from renpy_story_mapper.project import Project, create_ingested_project
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
            request.settings,
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


@dataclass
class _SettingsMismatchProvider(_Provider):
    def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
        response = super().submit(request, cancelled)
        return replace(
            response,
            provider=replace(
                response.provider,
                settings=ProviderSettings(
                    (("model_reasoning_effort", "xhigh"), ("fast_mode", False))
                ),
            ),
        )


@dataclass
class _AlwaysTimeoutProvider(_Provider):
    def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
        del cancelled
        self.requests.append(request)
        raise ProviderTimeoutError(
            "provider_timeout",
            "sanitized simulated timeout",
            transient=True,
        )


@dataclass
class _UnexpectedFailureProvider(_Provider):
    def submit(self, request: ProviderRequest, cancelled: object) -> ProviderResponse:
        if not self.requests:
            return super().submit(request, cancelled)
        del cancelled
        self.requests.append(request)
        raise RuntimeError("simulated interruption after one scheduler phase completed")


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


def _browser_request() -> dict[str, object]:
    return {
        "requested_model": "runtime-model",
        "provider_settings": {
            "model_reasoning_effort": "high",
            "fast_mode": False,
        },
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
    reopened: ProjectApi | None = None
    request = {
        "requested_model": "runtime-model",
        "provider_settings": {
            "model_reasoning_effort": "high",
            "fast_mode": False,
        },
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
        assert preview["provider"]["settings"] == request["provider_settings"]
        assert preview["consent_manifest_id"].startswith("m13_consent_")
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
        assert status["latest_run"]["provider"]["settings"] == request["provider_settings"]
        assert status["durable_completed_work_preserved"] is True
        assert provider.requests
        assert all(
            item.settings.to_dict() == request["provider_settings"] for item in provider.requests
        )

        project_path = tmp_path / "story.rsmproj"
        with Project.open(project_path) as project:
            persistence = project.m13_persistence()
            consents = persistence.list_records(RecordKind.CONSENT)
            assert len(consents) == 1
            assert consents[0].state is LookupState.HIT
            assert consents[0].payload is not None
            assert consents[0].payload["provider"]["settings"] == request["provider_settings"]
            caches = persistence.list_records(RecordKind.CACHE)
            assert caches
            assert all(item.state is LookupState.HIT for item in caches)
            assert all(
                item.payload is not None
                and item.payload["cache_identity"]["provider"]["settings"]
                == request["provider_settings"]
                for item in caches
            )
        api.close()
        reopened = ProjectApi(
            _Dialogs(),
            state_store=UserStateStore(tmp_path / "reopened-state.json"),
            m13_provider_factory=lambda: provider,
        )
        reopened._retain_project_path(project_path, tmp_path / "game")
        reopened_status = reopened.dispatch("POST", "/api/v1/m13/status", {})
        assert reopened_status["latest_run"]["provider"]["settings"] == request["provider_settings"]
        assert len(provider.requests) > 0
    finally:
        api.close()
        if reopened is not None:
            reopened.close()


def test_m13_browser_settings_change_preparation_and_consent_identity_without_transmission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _Provider()
    api = _api(tmp_path, provider)
    monkeypatch.setattr(
        "renpy_story_mapper.web.api.uuid.uuid4",
        lambda: type("FixedUuid", (), {"hex": "fixed-run"})(),
    )
    request = {
        "requested_model": "runtime-model",
        "provider_settings": {
            "model_reasoning_effort": "high",
            "fast_mode": False,
        },
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
        high = api.dispatch("POST", "/api/v1/m13/prepare", request)
        xhigh = api.dispatch(
            "POST",
            "/api/v1/m13/prepare",
            {
                **request,
                "provider_settings": {
                    "model_reasoning_effort": "xhigh",
                    "fast_mode": False,
                },
            },
        )

        assert high["preparation_id"] != xhigh["preparation_id"]
        assert high["consent_manifest_id"] != xhigh["consent_manifest_id"]
        assert provider.requests == []
    finally:
        api.close()


def test_m13_provider_response_settings_mismatch_fails_without_cache_publication(
    tmp_path: Path,
) -> None:
    provider = _SettingsMismatchProvider()
    api = _api(tmp_path, provider)
    request = {
        "requested_model": "runtime-model",
        "provider_settings": {
            "model_reasoning_effort": "high",
            "fast_mode": False,
        },
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
            "maximum_items": 16,
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
        deadline = time.monotonic() + 20
        while True:
            status = api.dispatch("POST", "/api/v1/m13/status", {})
            if status["state"] not in {"running", "cancelling"}:
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)

        assert status["state"] == "failed"
        assert status["latest_run"]["succeeded_jobs"] == 0
        assert status["latest_run"]["failed_jobs"] > 0
        with Project.open(tmp_path / "story.rsmproj") as project:
            assert project.m13_persistence().list_records(RecordKind.CACHE) == ()
    finally:
        api.close()


@pytest.mark.parametrize(
    "provider_settings",
    [
        {"model_reasoning_effort": "minimal", "fast_mode": False},
        {"model_reasoning_effort": "high", "fast_mode": True},
        {"model_reasoning_effort": "high", "fast_mode": False, "temperature": 0},
    ],
)
def test_m13_browser_rejects_unsupported_settings_before_transmission(
    tmp_path: Path,
    provider_settings: dict[str, object],
) -> None:
    provider = _Provider()
    api = _api(tmp_path, provider)
    try:
        with pytest.raises((ValueError, TypeError, ProviderRuntimeConfigurationError)):
            api.dispatch(
                "POST",
                "/api/v1/m13/prepare",
                {
                    "requested_model": "runtime-model",
                    "provider_settings": provider_settings,
                    "mode": "fact_only",
                    "include_m12_material": True,
                    "limits": {
                        "max_provider_calls": 1,
                        "max_input_tokens": 1_000,
                        "max_output_tokens": 1_000,
                        "max_total_tokens": 2_000,
                        "timeout_seconds": 30,
                        "max_concurrency": 1,
                        "max_cost_micros": None,
                    },
                    "batch_limits": {
                        "maximum_items": 1,
                        "maximum_input_chars": 10_000,
                        "maximum_input_tokens": 2_000,
                    },
                },
            )
        assert provider.requests == []
    finally:
        api.close()


def test_m13_reopen_restores_exact_retry_request_and_reuses_only_compatible_consent(
    tmp_path: Path,
) -> None:
    provider = _AlwaysTimeoutProvider()
    api = _api(tmp_path, provider)
    project_path = tmp_path / "story.rsmproj"
    request = _browser_request()
    with Project.open(project_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        scenes = authority.scene_model.get("scenes")
        assert isinstance(scenes, list) and scenes
        first_scene = scenes[0]
        assert isinstance(first_scene, dict) and isinstance(first_scene.get("id"), str)
        request["selected_scene_ids"] = [first_scene["id"]]
    reopened: ProjectApi | None = None
    try:
        prepared = api.dispatch("POST", "/api/v1/m13/prepare", request)
        original_run_id = prepared["run_id"]
        original_consent_id = prepared["consent_manifest_id"]
        api.dispatch(
            "POST",
            "/api/v1/m13/start",
            {"preparation_id": prepared["preparation_id"], "confirm_cloud": True},
        )
        for _attempt in range(500):
            status = api.dispatch("POST", "/api/v1/m13/status", {})
            if status["state"] not in {"running", "cancelling"}:
                break
            time.sleep(0.01)
        assert status["state"] in {"failed", "hard_limit", "partial"}
        assert provider.requests
        api.close()

        calls_before_reopen = len(provider.requests)
        reopened = ProjectApi(
            _Dialogs(),
            state_store=UserStateStore(tmp_path / "retry-state.json"),
            m13_provider_factory=lambda: provider,
        )
        reopened._retain_project_path(project_path, tmp_path / "game")
        restored = reopened.dispatch("POST", "/api/v1/m13/status", {})

        assert restored["state"] == status["state"]
        assert restored["retry_available"] is True
        retry_request = restored["retry_request"]
        assert retry_request["resume_run_id"] == original_run_id
        assert retry_request["resume_consent_id"] == original_consent_id
        assert retry_request["provider_settings"] == request["provider_settings"]
        assert restored["latest_run"]["cumulative_usage"]["provider_calls"] == len(
            provider.requests
        )
        assert len(provider.requests) == calls_before_reopen

        resumed = reopened.dispatch("POST", "/api/v1/m13/prepare", retry_request)
        assert resumed["run_id"] == original_run_id
        assert resumed["consent_manifest_id"] == original_consent_id
        assert len(provider.requests) == calls_before_reopen

        with pytest.raises(ApiProblem) as incompatible:
            reopened.dispatch(
                "POST",
                "/api/v1/m13/prepare",
                {
                    **retry_request,
                    "provider_settings": {
                        "model_reasoning_effort": "xhigh",
                        "fast_mode": False,
                    },
                },
            )
        assert incompatible.value.code == "m13_resume_incompatible"
        assert len(provider.requests) == calls_before_reopen
    finally:
        api.close()
        if reopened is not None:
            reopened.close()


def test_m13_retry_start_preserves_prior_cumulative_usage_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _AlwaysTimeoutProvider()
    api = _api(tmp_path, provider)
    project_path = tmp_path / "story.rsmproj"
    request = _browser_request()
    with Project.open(project_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        scenes = authority.scene_model.get("scenes")
        assert isinstance(scenes, list) and scenes
        first_scene = scenes[0]
        assert isinstance(first_scene, dict) and isinstance(first_scene.get("id"), str)
        request["selected_scene_ids"] = [first_scene["id"]]
    reopened: ProjectApi | None = None
    try:
        prepared = api.dispatch("POST", "/api/v1/m13/prepare", request)
        api.dispatch(
            "POST",
            "/api/v1/m13/start",
            {"preparation_id": prepared["preparation_id"], "confirm_cloud": True},
        )
        for _attempt in range(500):
            status = api.dispatch("POST", "/api/v1/m13/status", {})
            if status["state"] not in {"running", "cancelling"}:
                break
            time.sleep(0.01)
        assert status["retry_available"] is True
        api.close()

        reopened = ProjectApi(
            _Dialogs(),
            state_store=UserStateStore(tmp_path / "retry-cumulative-state.json"),
            m13_provider_factory=lambda: provider,
        )
        reopened._retain_project_path(project_path, tmp_path / "game")
        restored = reopened.dispatch("POST", "/api/v1/m13/status", {})
        prior_cumulative = restored["latest_run"]["cumulative_usage"]
        assert prior_cumulative["provider_calls"] > 0
        retried = reopened.dispatch(
            "POST",
            "/api/v1/m13/prepare",
            restored["retry_request"],
        )
        monkeypatch.setattr(
            reopened,
            "_start",
            lambda _kind, _operation: {"analysis": None},
        )

        reopened.dispatch(
            "POST",
            "/api/v1/m13/start",
            {"preparation_id": retried["preparation_id"], "confirm_cloud": True},
        )

        with Project.open(project_path) as project:
            authority = load_narrative_authority(project, include_m12=True)
            run = project.m13_persistence().lookup(
                RecordKind.RUN,
                prepared["run_id"],
                authority_binding=authority.binding.to_dict(),
            )
            assert run.state is LookupState.HIT
            assert run.payload is not None
            assert run.payload["usage"]["provider_calls"] == 0
            assert run.payload["cumulative_usage"] == prior_cumulative
    finally:
        api.close()
        if reopened is not None:
            reopened.close()


def test_m13_browser_retry_identity_is_durable_before_interrupted_execution_returns(
    tmp_path: Path,
) -> None:
    provider = _UnexpectedFailureProvider()
    api = _api(tmp_path, provider)
    project_path = tmp_path / "story.rsmproj"
    request = _browser_request()
    with Project.open(project_path) as project:
        authority = load_narrative_authority(project, include_m12=True)
        scenes = authority.scene_model.get("scenes")
        assert isinstance(scenes, list) and scenes
        first_scene = scenes[0]
        assert isinstance(first_scene, dict) and isinstance(first_scene.get("id"), str)
        request["selected_scene_ids"] = [first_scene["id"]]
    reopened: ProjectApi | None = None
    try:
        prepared = api.dispatch("POST", "/api/v1/m13/prepare", request)
        api.dispatch(
            "POST",
            "/api/v1/m13/start",
            {"preparation_id": prepared["preparation_id"], "confirm_cloud": True},
        )
        for _attempt in range(500):
            status = api.dispatch("POST", "/api/v1/m13/status", {})
            if status["state"] not in {"running", "cancelling"}:
                break
            time.sleep(0.01)

        assert status["state"] == "failed"
        assert status["retry_available"] is True
        assert len(provider.requests) == 2
        latest = status["latest_run"]
        assert latest["state"] == "succeeded"
        assert latest["browser_pipeline_complete"] is False
        assert latest["browser_preparation_id"] == prepared["preparation_id"]
        assert latest["browser_retry_request"] == {
            **request,
            "locale": "und",
            "perspective": "default",
            "resume_run_id": prepared["run_id"],
            "resume_consent_id": prepared["consent_manifest_id"],
        }

        api.close()
        reopened = ProjectApi(
            _Dialogs(),
            state_store=UserStateStore(tmp_path / "interrupted-retry-state.json"),
            m13_provider_factory=lambda: provider,
        )
        reopened._retain_project_path(project_path, tmp_path / "game")
        restored = reopened.dispatch("POST", "/api/v1/m13/status", {})
        assert restored["state"] == "interrupted"
        assert restored["retry_available"] is True
        assert restored["retry_request"] == latest["browser_retry_request"]

        retried = reopened.dispatch(
            "POST",
            "/api/v1/m13/prepare",
            restored["retry_request"],
        )
        assert retried["preparation_id"] == prepared["preparation_id"]
        assert len(provider.requests) == 2
    finally:
        api.close()
        if reopened is not None:
            reopened.close()


def test_m12_citation_result_navigation_reopens_without_in_memory_identity(
    tmp_path: Path,
) -> None:
    api = _api(tmp_path)
    project_path = tmp_path / "story.rsmproj"
    try:
        with Project.open(project_path) as project:
            service = M12RouteService(project)
            page = service.destinations(query="Foyer", limit=50)
            nodes = page["nodes"]
            assert isinstance(nodes, list)
            target = next(item for item in nodes if item["kind"] == "generic_scene")
            prepared = service.prepare(str(target["kind"]), str(target["target_id"]))
            outcome = service.solve(prepared)
            assert outcome.result is not None
            request_identity = prepared.request.identity

        assert api._m12_identities == {}
        result = api.dispatch(
            "POST",
            "/api/v1/m12/result",
            {"request_identity": request_identity},
        )

        assert result["request_identity"] == request_identity
        assert result == outcome.result
        assert api._m12_identities == {}
    finally:
        api.close()


def test_m13_api_cancellation_reaches_provider_and_preserves_validated_artifacts(
    tmp_path: Path,
) -> None:
    provider = _BlockingAfterFirstProvider()
    api = _api(tmp_path, provider)
    request = {
        "requested_model": "runtime-model",
        "provider_settings": {
            "model_reasoning_effort": "high",
            "fast_mode": False,
        },
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

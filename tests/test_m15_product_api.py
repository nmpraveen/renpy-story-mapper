from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.provider import (
    NarrativeMapProviderError,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    ProviderJobKind,
)
from renpy_story_mapper.narrative_map.semantic_contracts import BoundaryWindow
from renpy_story_mapper.project import refresh_ingested_project
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.contracts import M15_API_ROUTES
from renpy_story_mapper.web.state import UserStateStore
from test_m15_track_c import _Dialogs, _project


class _ProductFakeProvider:
    def __init__(self, requests: list[NarrativeMapProviderRequest]) -> None:
        self.requests = requests
        self.cancel_count = 0

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        job = request.job
        if job.kind is ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW:
            assert isinstance(job.subject, BoundaryWindow)
            payload: dict[str, object] = {
                "window_id": job.subject_id,
                "decisions": [
                    {
                        "candidate_id": candidate_id,
                        "decision": "new_beat_same_cluster",
                        "reason": "The immediate story objective changes.",
                        "confidence": 0.9,
                        "warnings": [],
                    }
                    for candidate_id in job.subject.owned_candidate_ids
                ],
            }
        else:
            payload = {
                "subject_kind": job.payload["subject_kind"],
                "subject_id": job.subject_id,
                "membership_hash": job.membership_hash,
                "title": "Supported story section",
                "summary": "This section presents the supported story progression.",
                "characters": [],
                "claims": [
                    {
                        "claim_class": "factual",
                        "text": "The section contains supported story action.",
                        "evidence_ids": [job.known_evidence_ids[0]],
                    }
                ],
                "warnings": [],
            }
        profile = request.profile
        return NarrativeMapProviderResponse(
            request.request_id,
            ProviderIdentity(
                profile.provider,
                profile.adapter,
                profile.adapter_version,
                profile.requested_model,
                profile.requested_model,
                profile.settings,
            ),
            payload,
            ProviderUsage(100, 20, 5),
        )

    def cancel(self) -> None:
        self.cancel_count += 1


class _FailingProductProvider(_ProductFakeProvider):
    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        raise NarrativeMapProviderError(
            "provider_unavailable",
            "The fake provider is unavailable for this attempt.",
        )


class _CancellableProductProvider(_ProductFakeProvider):
    def __init__(
        self,
        requests: list[NarrativeMapProviderRequest],
        entered: threading.Event,
    ) -> None:
        super().__init__(requests)
        self.entered = entered

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        self.requests.append(request)
        self.entered.set()
        deadline = time.monotonic() + 5
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert cancelled()
        raise NarrativeMapProviderError("cancelled", "The fake request was cancelled.")


def _api(
    tmp_path: Path,
    source: Path,
    project_path: Path,
    provider_factory: Callable[[], _ProductFakeProvider],
) -> ProjectApi:
    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m15_provider_factory=provider_factory,
    )
    api._retain_project_path(project_path, source)
    return api


def _wait(api: ProjectApi) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        progress = api.dispatch("GET", "/api/v1/analysis/progress", {})
        assert isinstance(progress, dict)
        if progress.get("state") not in {"pending", "running"}:
            return progress
        time.sleep(0.01)
    raise AssertionError("M15 web operation did not finish")


def _change_current_m10_m11_authority(source: Path, project_path: Path) -> None:
    story = source / "story.rpy"
    story.write_bytes(
        story.read_bytes()
        + b'\nlabel post_preview_change:\n    "Changed authority."\n    return\n'
    )
    refresh_ingested_project(project_path, source)


def test_semantic_prepare_review_cancel_is_strict_and_zero_submit(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    factory_calls = 0

    def prohibited_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("prepare, review, and cancel must not construct a provider")

    api = _api(tmp_path, source, project_path, prohibited_factory)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert bootstrap["routes"]["m15"] == M15_API_ROUTES
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        assert prepared["state"] == "awaiting_boundary_consent"
        assert prepared["requires_confirmation"] is True
        assert prepared["manifest"]["provider"] == {
            "provider": "openai",
            "adapter": "codex_cli_structured",
            "adapter_version": "m13-codex-cli-adapter-v3",
            "requested_model": "gpt-5.6-sol",
            "resolved_model": "gpt-5.6-sol",
            "settings": {"model_reasoning_effort": "medium", "fast_mode": False},
        }
        serialized = repr(prepared)
        assert "payload" not in serialized
        assert "Opening line" not in serialized

        for body in (
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": False,
            },
            {
                "action": "start_boundaries",
                "manifest_id": "consent_wrong",
                "confirm_cloud": True,
            },
        ):
            with pytest.raises(ApiProblem) as raised:
                api.dispatch("POST", M15_API_ROUTES["start_boundaries"], body)
            assert raised.value.status == 409

        with pytest.raises(ValueError):
            api.dispatch(
                "POST",
                M15_API_ROUTES["prepare_boundaries"],
                {"action": "prepare_boundaries", "unexpected": True},
            )
        cancelled = api.dispatch("POST", M15_API_ROUTES["cancel"], {})
        assert cancelled["state"] == "cancelled"
        assert factory_calls == 0
    finally:
        api.close()


def test_authority_change_after_preview_rejects_start_before_provider_construction(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    factory_calls = 0

    def prohibited_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("stale consent must not construct a provider")

    api = _api(tmp_path, source, project_path, prohibited_factory)
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        _change_current_m10_m11_authority(source, project_path)
        with pytest.raises(ApiProblem) as raised:
            api.dispatch(
                "POST",
                M15_API_ROUTES["start_boundaries"],
                {
                    "action": "start_boundaries",
                    "manifest_id": prepared["manifest_id"],
                    "confirm_cloud": True,
                },
            )
        assert raised.value.status == 409
        assert raised.value.code == "m15_preparation_stale"
        assert factory_calls == 0
    finally:
        api.close()


def test_fake_provider_two_stage_publication_and_reopen_are_exact_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    factory_calls = 0

    def provider_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        return _ProductFakeProvider(requests)

    api = _api(tmp_path, source, project_path, provider_factory)

    def prohibited_m12(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("M15 product production must not invoke M12")

    monkeypatch.setattr(api, "_m12_solve", prohibited_m12)
    try:
        boundaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        boundary_manifest = boundaries["manifest_id"]
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": boundary_manifest,
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == (
            "membership_frozen"
        )

        summaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_summaries"],
            {"action": "prepare_summaries"},
        )
        summary_manifest = summaries["manifest_id"]
        assert summary_manifest != boundary_manifest
        assert summaries["requires_confirmation"] is True
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_summaries"],
            {
                "action": "start_summaries",
                "manifest_id": summary_manifest,
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        complete = api.dispatch("POST", M15_API_ROUTES["status"], {})
        assert complete["state"] == "complete"
        assert complete["manifest_id"] == summary_manifest
        assert complete["publication_hash"]
        publication_hash = complete["publication_hash"]
        assert factory_calls == 2
        assert requests
        assert all(
            request.profile.provider == "openai"
            and request.profile.adapter == "codex_cli_structured"
            and request.profile.adapter_version == "m13-codex-cli-adapter-v3"
            and request.profile.requested_model == "gpt-5.6-sol"
            and request.profile.settings.to_dict()
            == {"fast_mode": False, "reasoning_effort": "medium"}
            for request in requests
        )
    finally:
        api.close()

    replay_factory_calls = 0

    def replay_prohibited_factory() -> _ProductFakeProvider:
        nonlocal replay_factory_calls
        replay_factory_calls += 1
        raise AssertionError("an exact reopened replay must not construct a provider")

    reopened = _api(tmp_path, source, project_path, replay_prohibited_factory)
    monkeypatch.setattr(reopened, "_m12_solve", prohibited_m12)
    try:
        replay_boundaries = reopened.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        assert replay_boundaries["replay_only"] is True
        reopened.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": replay_boundaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(reopened)["state"] == "completed"
        replay_summaries = reopened.dispatch(
            "POST",
            M15_API_ROUTES["prepare_summaries"],
            {"action": "prepare_summaries"},
        )
        assert replay_summaries["replay_only"] is True
        reopened.dispatch(
            "POST",
            M15_API_ROUTES["start_summaries"],
            {
                "action": "start_summaries",
                "manifest_id": replay_summaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(reopened)["state"] == "completed"
        replayed = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert replayed["state"] == "complete"
        assert replayed["publication_hash"] == publication_hash
        assert replay_factory_calls == 0
    finally:
        reopened.close()


def test_reopened_retry_recovers_confirmed_boundary_stage_and_freezes_membership(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    failed_requests: list[NarrativeMapProviderRequest] = []
    api = _api(
        tmp_path,
        source,
        project_path,
        lambda: _FailingProductProvider(failed_requests),
    )
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == "failed"
        assert len(failed_requests) == 1
    finally:
        api.close()

    retry_requests: list[NarrativeMapProviderRequest] = []
    reopened = _api(
        tmp_path,
        source,
        project_path,
        lambda: _ProductFakeProvider(retry_requests),
    )
    try:
        reopened.dispatch("POST", M15_API_ROUTES["retry"], {})
        assert _wait(reopened)["state"] == "completed"
        status = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert status["state"] == "membership_frozen"
        assert len(retry_requests) == 1
    finally:
        reopened.close()


def test_authority_change_after_failure_rejects_retry_before_provider_construction(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    failed_requests: list[NarrativeMapProviderRequest] = []
    factory_calls = 0

    def provider_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls > 1:
            raise AssertionError("stale retry must not construct another provider")
        return _FailingProductProvider(failed_requests)

    api = _api(tmp_path, source, project_path, provider_factory)
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == "failed"
        _change_current_m10_m11_authority(source, project_path)
        with pytest.raises(ApiProblem) as raised:
            api.dispatch("POST", M15_API_ROUTES["retry"], {})
        assert raised.value.status == 409
        assert raised.value.code == "m15_fresh_preparation_required"
        assert factory_calls == 1
        assert len(failed_requests) == 1
    finally:
        api.close()


def test_reopened_resume_recovers_confirmed_cancelled_boundary_stage(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    cancelled_requests: list[NarrativeMapProviderRequest] = []
    entered = threading.Event()
    api = _api(
        tmp_path,
        source,
        project_path,
        lambda: _CancellableProductProvider(cancelled_requests, entered),
    )
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert entered.wait(timeout=5)
        api.dispatch("POST", M15_API_ROUTES["cancel"], {})
        assert _wait(api)["state"] == "cancelled"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == (
            "cancelled"
        )
        assert len(cancelled_requests) == 1
    finally:
        api.close()

    resume_requests: list[NarrativeMapProviderRequest] = []
    reopened = _api(
        tmp_path,
        source,
        project_path,
        lambda: _ProductFakeProvider(resume_requests),
    )
    try:
        reopened.dispatch("POST", M15_API_ROUTES["resume"], {})
        assert _wait(reopened)["state"] == "completed"
        status = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert status["state"] == "membership_frozen"
        assert len(resume_requests) == 1
    finally:
        reopened.close()


def test_reopened_resume_recovers_confirmed_cancelled_summary_stage(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    boundary_requests: list[NarrativeMapProviderRequest] = []
    cancelled_requests: list[NarrativeMapProviderRequest] = []
    entered = threading.Event()
    factory_calls = 0

    def staged_factory() -> _ProductFakeProvider:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            return _ProductFakeProvider(boundary_requests)
        return _CancellableProductProvider(cancelled_requests, entered)

    api = _api(tmp_path, source, project_path, staged_factory)
    try:
        boundaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_boundaries"],
            {
                "action": "start_boundaries",
                "manifest_id": boundaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert _wait(api)["state"] == "completed"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == (
            "membership_frozen"
        )
        summaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_summaries"],
            {"action": "prepare_summaries"},
        )
        api.dispatch(
            "POST",
            M15_API_ROUTES["start_summaries"],
            {
                "action": "start_summaries",
                "manifest_id": summaries["manifest_id"],
                "confirm_cloud": True,
            },
        )
        assert entered.wait(timeout=5)
        api.dispatch("POST", M15_API_ROUTES["cancel"], {})
        assert _wait(api)["state"] == "cancelled"
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == (
            "cancelled"
        )
        assert boundary_requests
        assert len(cancelled_requests) == 1
    finally:
        api.close()

    resume_requests: list[NarrativeMapProviderRequest] = []
    reopened = _api(
        tmp_path,
        source,
        project_path,
        lambda: _ProductFakeProvider(resume_requests),
    )
    try:
        reopened.dispatch("POST", M15_API_ROUTES["resume"], {})
        assert _wait(reopened)["state"] == "completed"
        status = reopened.dispatch("POST", M15_API_ROUTES["status"], {})
        assert status["state"] == "complete"
        assert status["publication_hash"]
        assert resume_requests
    finally:
        reopened.close()

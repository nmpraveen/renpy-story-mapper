from __future__ import annotations

import threading
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.assembly import assemble_semantic_outline
from renpy_story_mapper.narrative_map.persistence import NarrativeMapRepository
from renpy_story_mapper.narrative_map.provider import (
    NarrativeMapProviderError,
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    ProviderJobKind,
    WholeScopeProviderSubject,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    BoundaryWindow,
    SemanticBoundaryDecision,
    SemanticBoundaryKind,
    WholeScopeSemanticStage,
)
from renpy_story_mapper.project import Project, refresh_ingested_project
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.contracts import (
    M15_API_ROUTES,
    M15_WHOLE_SCOPE_SEMANTIC_ROUTES,
    JsonValue,
)
from renpy_story_mapper.web.launcher import build_project_api
from renpy_story_mapper.web.m15_semantic_api import load_m15_semantic_inputs
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


def test_shipped_launcher_wires_durable_stage_h_without_constructing_provider(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    provider_constructions = 0

    def forbidden_provider() -> _ProductFakeProvider:
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("provider construction is forbidden during product preparation")

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_provider)
    api._retain_project_path(project_path, source)
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        status = api.dispatch("POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["status"], {})
    finally:
        api.close()

    assert bootstrap["routes"]["m15_whole_scope_semantic"] == (M15_WHOLE_SCOPE_SEMANTIC_ROUTES)
    assert prepared["state"] == "awaiting_hierarchy_consent"
    assert prepared["manifest_id"]
    assert status["state"] == "awaiting_hierarchy_consent"
    assert provider_constructions == 0


class _WholeScopeProductFakeProvider(_ProductFakeProvider):
    def __init__(
        self,
        requests: list[NarrativeMapProviderRequest],
        hierarchy_payload: dict[str, object],
    ) -> None:
        super().__init__(requests)
        self.hierarchy_payload = hierarchy_payload

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        assert not cancelled()
        self.requests.append(request)
        subject = request.job.subject
        assert isinstance(subject, WholeScopeProviderSubject)
        if subject.stage is WholeScopeSemanticStage.HIERARCHY:
            payload: dict[str, object] = dict(self.hierarchy_payload)
            payload["scope_id"] = subject.scope_id
        else:
            payload = {
                "scope_id": subject.scope_id,
                "hierarchy_hash": subject.hierarchy_hash,
                "records": [
                    {
                        "subject_kind": item.subject_kind,
                        "subject_id": item.subject_id,
                        "membership_hash": item.membership_hash,
                        "presentation_role": "story",
                        "title": f"Supported Story Action {index + 1}",
                        "summary": (
                            f"Supported story action {index + 1} begins and reaches its result."
                        ),
                        "characters": list(item.known_characters),
                        "claims": [
                            {
                                "claim_class": "factual",
                                "text": (
                                    f"Supported story action {index + 1} occurs in this scope."
                                ),
                                "evidence_ids": [item.evidence_ids[0]],
                            }
                        ],
                        "warnings": [],
                    }
                    for index, item in enumerate(subject.editorial_subjects)
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


class _CancellableWholeScopeProductProvider(_WholeScopeProductFakeProvider):
    def __init__(
        self,
        requests: list[NarrativeMapProviderRequest],
        hierarchy_payload: dict[str, object],
        entered: threading.Event,
    ) -> None:
        super().__init__(requests, hierarchy_payload)
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


def _whole_scope_hierarchy_payload(project_path: Path) -> dict[str, object]:
    with Project.open(project_path) as project:
        inputs = load_m15_semantic_inputs(project)
    decisions = tuple(
        SemanticBoundaryDecision(
            item.candidate_id,
            SemanticBoundaryKind.NEW_BEAT_SAME_CLUSTER,
            "The deterministic synthetic action changes.",
            0.9,
        )
        for item in inputs.candidates
    )
    outline = assemble_semantic_outline(inputs.units, inputs.candidates, decisions)
    beat_keys = {
        item.beat_id: f"whole-scope-beat-{index + 1}"
        for index, item in enumerate(outline.beats)
    }
    return {
        "scope_id": "replaced-by-provider",
        "beat_groups": [
            {
                "proposal_key": beat_keys[item.beat_id],
                "ordered_unit_ids": list(item.ordered_unit_ids),
                "confidence": 0.9,
                "reason": "This supported synthetic action is one bounded beat.",
                "warnings": [],
            }
            for item in outline.beats
        ],
        "major_clusters": [
            {
                "proposal_key": f"whole-scope-cluster-{index + 1}",
                "ordered_beat_keys": [beat_keys[item] for item in cluster.ordered_beat_ids],
                "confidence": 0.9,
                "reason": "These supported synthetic actions form one story section.",
                "warnings": [],
            }
            for index, cluster in enumerate(outline.clusters)
        ],
        "uncertain_unit_ids": [],
        "warnings": [],
    }


def test_shipped_controller_completes_fake_stage_h_and_e_through_durable_lifecycle(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    constructions = 0
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(requests, hierarchy_payload)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        hierarchy = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        hierarchy_status = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        editorial_status = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
    finally:
        api.close()

    assert hierarchy_status["state"] == "hierarchy_frozen"
    assert editorial_status["state"] == "complete"
    assert editorial_status["publication_hash"]
    assert constructions == 2
    assert len(requests) == 2

    replay_constructions = 0

    def forbidden_replay_provider() -> _WholeScopeProductFakeProvider:
        nonlocal replay_constructions
        replay_constructions += 1
        raise AssertionError("unchanged whole-scope replay must not construct a provider")

    reopened = build_project_api(_Dialogs(), m15_provider_factory=forbidden_replay_provider)
    reopened._retain_project_path(project_path, source)
    try:
        replay_hierarchy = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        replay_hierarchy_status = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": replay_hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        replay_editorial = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        replay_editorial_status = reopened.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": replay_editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
    finally:
        reopened.close()

    assert replay_hierarchy_status["state"] == "complete"
    assert replay_editorial_status["state"] == "complete"
    assert replay_editorial_status["publication_hash"] == editorial_status["publication_hash"]
    assert replay_constructions == 0


def test_whole_scope_stage_h_authority_drift_is_stale_before_any_provider_effect(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    constructions = 0
    requests: list[NarrativeMapProviderRequest] = []

    def forbidden_factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(
            requests, _whole_scope_hierarchy_payload(project_path)
        )

    api = build_project_api(_Dialogs(), m15_provider_factory=forbidden_factory)
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        with Project.open(project_path) as project:
            build = NarrativeMapRepository(project).read_whole_scope_build()
            assert build is not None
            transport_batch_id = str(build["hierarchy_transport_batch_id"])
        _change_current_m10_m11_authority(source, project_path)
        stale = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": prepared["manifest_id"],
                "confirm_cloud": True,
            },
        )
        with Project.open(project_path) as project:
            reservations = NarrativeMapRepository(project).whole_scope_reserved_attempts(
                transport_batch_id
            )
    finally:
        api.close()

    assert stale["state"] == "stale"
    assert stale["failure_codes"] == ["m15_preparation_stale"]
    assert stale["requires_fresh_preparation"] is True
    assert stale["accounting"] == {
        "provider_calls": 0,
        "reserved_provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "elapsed_ms": 0,
        "cache_hits": 0,
    }
    assert constructions == 0
    assert requests == []
    assert reservations == ()


def test_whole_scope_stage_e_subject_drift_is_stale_before_any_new_provider_effect(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    constructions = 0
    requests: list[NarrativeMapProviderRequest] = []
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _WholeScopeProductFakeProvider:
        nonlocal constructions
        constructions += 1
        return _WholeScopeProductFakeProvider(requests, hierarchy_payload)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    try:
        hierarchy = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": hierarchy["manifest_id"],
                "confirm_cloud": True,
            },
        )
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        with Project.open(project_path) as project:
            repository = NarrativeMapRepository(project)
            build = repository.read_whole_scope_build()
            assert build is not None
            transport_batch_id = str(build["editorial_transport_batch_id"])
            drifted = deepcopy(dict(build))
            subjects = drifted["frozen_editorial_subjects"]
            assert isinstance(subjects, list) and isinstance(subjects[0], dict)
            subjects[0]["membership_hash"] = "drifted-frozen-membership"
            repository.write_whole_scope_build(drifted)
        stale = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": editorial["manifest_id"],
                "confirm_cloud": True,
            },
        )
        with Project.open(project_path) as project:
            reservations = NarrativeMapRepository(project).whole_scope_reserved_attempts(
                transport_batch_id
            )
    finally:
        api.close()

    assert stale["state"] == "stale"
    assert stale["failure_codes"] == ["m15_preparation_stale"]
    assert stale["requires_fresh_preparation"] is True
    assert stale["accounting"]["provider_calls"] == 0
    assert stale["accounting"]["reserved_provider_calls"] == 0
    assert constructions == 1
    assert len(requests) == 1
    assert reservations == ()


def test_whole_scope_lazy_provider_preserves_concurrent_cancellation(tmp_path: Path) -> None:
    source, project_path = _project(tmp_path)
    requests: list[NarrativeMapProviderRequest] = []
    entered = threading.Event()
    hierarchy_payload = _whole_scope_hierarchy_payload(project_path)

    def factory() -> _CancellableWholeScopeProductProvider:
        return _CancellableWholeScopeProductProvider(requests, hierarchy_payload, entered)

    api = build_project_api(_Dialogs(), m15_provider_factory=factory)
    api._retain_project_path(project_path, source)
    result: dict[str, object] = {}
    try:
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )

        def start() -> None:
            result.update(
                api.dispatch(
                    "POST",
                    M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
                    {
                        "action": "start_hierarchy",
                        "manifest_id": prepared["manifest_id"],
                        "confirm_cloud": True,
                    },
                )
            )

        worker = threading.Thread(target=start)
        worker.start()
        assert entered.wait(timeout=5)
        cancelled = api.dispatch(
            "POST", M15_WHOLE_SCOPE_SEMANTIC_ROUTES["cancel"], {}
        )
        worker.join(timeout=5)
        assert not worker.is_alive()
    finally:
        api.close()

    assert cancelled["state"] == "cancelled"
    assert result["state"] == "cancelled"
    assert len(requests) == 1


def test_whole_scope_routes_validate_and_delegate_to_the_track_b_controller(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, JsonValue]]] = []

    def controller(
        action: str,
        body: dict[str, JsonValue],
    ) -> dict[str, object]:
        calls.append((action, dict(body)))
        return {
            "state": f"{action}_handled",
            "manifest_id": "manifest-synthetic",
            "requires_confirmation": action.startswith("prepare_"),
        }

    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m15_whole_scope_controller=controller,
    )
    try:
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert isinstance(bootstrap, dict)
        routes = bootstrap["routes"]
        assert isinstance(routes, dict)
        assert routes["m15_whole_scope_semantic"] == M15_WHOLE_SCOPE_SEMANTIC_ROUTES
        prepared = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
            {"action": "prepare_hierarchy"},
        )
        assert isinstance(prepared, dict) and prepared["state"] == "prepare_hierarchy_handled"
        started = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_hierarchy"],
            {
                "action": "start_hierarchy",
                "manifest_id": "manifest-synthetic",
                "confirm_cloud": True,
            },
        )
        assert isinstance(started, dict) and started["state"] == "start_hierarchy_handled"
        editorial = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_editorial"],
            {"action": "prepare_editorial"},
        )
        assert isinstance(editorial, dict) and editorial["state"] == "prepare_editorial_handled"
        editorial_started = api.dispatch(
            "POST",
            M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
            {
                "action": "start_editorial",
                "manifest_id": "manifest-editorial-synthetic",
                "confirm_cloud": True,
            },
        )
        assert (
            isinstance(editorial_started, dict)
            and editorial_started["state"] == "start_editorial_handled"
        )
        for action in ("status", "cancel", "resume", "retry"):
            response = api.dispatch(
                "POST",
                M15_WHOLE_SCOPE_SEMANTIC_ROUTES[action],
                {},
            )
            assert isinstance(response, dict) and response["state"] == f"{action}_handled"
        assert [item[0] for item in calls] == [
            "prepare_hierarchy",
            "start_hierarchy",
            "prepare_editorial",
            "start_editorial",
            "status",
            "cancel",
            "resume",
            "retry",
        ]
        assert all(body == {} for _action, body in calls[-4:])
        with pytest.raises(ValueError, match="exact confirmation"):
            api.dispatch(
                "POST",
                M15_WHOLE_SCOPE_SEMANTIC_ROUTES["start_editorial"],
                {
                    "action": "start_editorial",
                    "manifest_id": "manifest-editorial-synthetic",
                    "confirm_cloud": False,
                },
            )
    finally:
        api.close()


def test_whole_scope_lifecycle_routes_fall_back_to_legacy_when_controller_is_absent(
    tmp_path: Path,
) -> None:
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    try:
        with pytest.raises(ApiProblem) as unavailable:
            api.dispatch(
                "POST",
                M15_WHOLE_SCOPE_SEMANTIC_ROUTES["prepare_hierarchy"],
                {"action": "prepare_hierarchy"},
            )
        assert unavailable.value.status == 409
        assert unavailable.value.code == "m15_whole_scope_not_integrated"

        for action in ("status", "cancel", "resume", "retry"):
            with pytest.raises(ApiProblem) as legacy_response:
                api.dispatch(
                    "POST",
                    M15_WHOLE_SCOPE_SEMANTIC_ROUTES[action],
                    {},
                )
            assert legacy_response.value.status == 409
            assert legacy_response.value.code == "no_project"
    finally:
        api.close()


def test_explicit_legacy_prepare_keeps_shared_lifecycle_on_legacy_controller(
    tmp_path: Path,
) -> None:
    source, project_path = _project(tmp_path)
    whole_scope_calls: list[str] = []

    def controller(action: str, _body: dict[str, JsonValue]) -> dict[str, object]:
        whole_scope_calls.append(action)
        return {"state": f"{action}_handled"}

    api = ProjectApi(
        _Dialogs(),
        state_store=UserStateStore(tmp_path / "state.json"),
        m15_whole_scope_controller=controller,
    )
    api._retain_project_path(project_path, source)
    try:
        prepared = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_boundaries"],
            {"action": "prepare_boundaries"},
        )
        status = api.dispatch("POST", M15_API_ROUTES["status"], {})
        assert isinstance(prepared, dict)
        assert isinstance(status, dict)
        assert whole_scope_calls == []
    finally:
        api.close()


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
        story.read_bytes() + b'\nlabel post_preview_change:\n    "Changed authority."\n    return\n'
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
        issued = datetime.fromisoformat(prepared["manifest"]["issued_at"])
        expires = datetime.fromisoformat(prepared["manifest"]["expires_at"])
        assert expires - issued == timedelta(hours=1)
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
        assert boundaries["manifest"]["repair_policy_version"] is None
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
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("membership_frozen")

        summaries = api.dispatch(
            "POST",
            M15_API_ROUTES["prepare_summaries"],
            {"action": "prepare_summaries"},
        )
        summary_manifest = summaries["manifest_id"]
        assert summary_manifest != boundary_manifest
        assert summaries["requires_confirmation"] is True
        assert summaries["manifest"]["repair_policy_version"] == ("m15-semantic-repair-guidance-v2")
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
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("cancelled")
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
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("membership_frozen")
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
        assert api.dispatch("POST", M15_API_ROUTES["status"], {})["state"] == ("cancelled")
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

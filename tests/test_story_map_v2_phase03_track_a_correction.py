from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from renpy_story_mapper.project import PayloadRecord, Project
from renpy_story_mapper.story_map_v2.contracts import canonical_hash
from renpy_story_mapper.story_map_v2.persistence import (
    StaleStoryMapV2Error,
    StoryMapV2PersistenceError,
    load_story_map_v2_for_current_project,
    save_story_map_v2,
)
from renpy_story_mapper.story_map_v2.phase03_contracts import SynthesisFailureKind
from renpy_story_mapper.story_map_v2.synthesis import (
    build_synthesis_preview,
    build_synthesis_request,
    execute_synthesis,
)
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import STORY_MAP_V2_API_ROUTES
from test_story_map_v2_phase03_track_a import (
    _create_project,
    _Dialogs,
    _FakeProvider,
    project_identity,
    synthetic_core,
    valid_response,
)


def _successful_synthesis(core, identity):
    request = build_synthesis_request(core, identity)
    event_ids = tuple(event.anchor.id for event in core.chunks[0].events)
    return execute_synthesis(
        request,
        build_synthesis_preview(request),
        lambda: _FakeProvider(valid_response(event_ids)),
    )


def _stored_value(project: Project) -> dict[str, object]:
    value = project.payload("story_map_v2", "current")
    assert isinstance(value, dict)
    return deepcopy(value)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("project_identity_hash", "d" * 64),
        ("request_payload_hash", "not-a-digest"),
        ("request_payload_hash", "c" * 64),
        ("preview_confirmation_hash", "A" * 64),
        ("preview_confirmation_hash", "d" * 64),
        ("prompt_version", "foreign-prompt"),
        ("response_schema", "foreign-schema"),
        ("provider", None),
        ("resolved_model", "gpt-5.6-sol"),
        ("call_count", 0),
        ("failure_kind", "identity"),
        ("sanitized_reason", "inconsistent failure"),
    ),
)
def test_invalid_optional_synthesis_degrades_to_complete_core_fallback_on_load_and_api(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    project_path = tmp_path / f"invalid-synthesis-{field}.rsmp"
    with _create_project(project_path, identity) as project:
        save_story_map_v2(project, core, identity, _successful_synthesis(core, identity))
        forged = _stored_value(project)
        synthesis = forged["synthesis"]
        assert isinstance(synthesis, dict)
        synthesis[field] = value
        project.write_payloads(
            (PayloadRecord("story_map_v2", "current", forged, identity.source_paths),)
        )

        loaded = load_story_map_v2_for_current_project(project)
        assert loaded is not None
        assert loaded.core == core
        assert loaded.synthesis is None

    api = ProjectApi(_Dialogs())
    try:
        api._project_path = project_path
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
    finally:
        api.close()
    assert isinstance(page, dict)
    assert page["status"] == "fallback"
    assert sum(len(section["events"]) for section in page["sections"]) == 6


def test_successful_synthesis_save_rejects_forged_durable_provenance(tmp_path: Path) -> None:
    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    result = _successful_synthesis(core, identity)
    for forged in (
        replace(result, provider=None),
        replace(result, request_payload_hash="not-a-digest"),
        replace(result, request_payload_hash="c" * 64),
        replace(result, preview_confirmation_hash="A" * 64),
        replace(result, preview_confirmation_hash="d" * 64),
        replace(result, prompt_version="foreign-prompt"),
        replace(result, response_schema="foreign-schema"),
        replace(result, resolved_model="gpt-5.6-sol"),
        replace(result, call_count=0),
        replace(result, failure_kind=SynthesisFailureKind.IDENTITY),
        replace(result, sanitized_reason="inconsistent failure"),
    ):
        with (
            _create_project(tmp_path / f"forged-{id(forged)}.rsmp", identity) as project,
            pytest.raises(StoryMapV2PersistenceError),
        ):
            save_story_map_v2(project, core, identity, forged)


def test_invalid_synthesis_never_masks_stale_core_or_authority_identity(
    tmp_path: Path,
) -> None:
    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    for label in ("core", "authority"):
        with _create_project(tmp_path / f"stale-{label}.rsmp", identity) as project:
            save_story_map_v2(project, core, identity, _successful_synthesis(core, identity))
            forged = _stored_value(project)
            synthesis = forged["synthesis"]
            assert isinstance(synthesis, dict)
            synthesis["provider"] = None
            if label == "core":
                stored_core = forged["core"]
                assert isinstance(stored_core, dict)
                stored_core["source_identity"] = "foreign-source"
            else:
                stored_identity = forged["identity"]
                assert isinstance(stored_identity, dict)
                stored_identity["authority_hash"] = "d" * 64
            project.write_payloads(
                (PayloadRecord("story_map_v2", "current", forged, identity.source_paths),)
            )
            with pytest.raises(StaleStoryMapV2Error):
                load_story_map_v2_for_current_project(project)


def test_reopen_load_cannot_construct_or_call_the_production_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from renpy_story_mapper.story_map_v2 import synthesis_transport

    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    project_path = tmp_path / "reopen.rsmp"
    with _create_project(project_path, identity) as project:
        save_story_map_v2(project, core, identity)

    activity = {"constructed": 0, "called": 0}

    def forbidden_init(self, *args, **kwargs):
        activity["constructed"] += 1
        raise AssertionError("reopen constructed the synthesis provider")

    def forbidden_call(self, *args, **kwargs):
        activity["called"] += 1
        raise AssertionError("reopen called the synthesis provider")

    monkeypatch.setattr(synthesis_transport.CodexCliSynthesisProvider, "__init__", forbidden_init)
    monkeypatch.setattr(synthesis_transport.CodexCliSynthesisProvider, "synthesize", forbidden_call)

    with Project.open(project_path) as reopened:
        loaded = load_story_map_v2_for_current_project(reopened)
    assert loaded is not None and loaded.core == core
    assert activity == {"constructed": 0, "called": 0}

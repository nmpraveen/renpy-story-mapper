from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest

from renpy_story_mapper.m12_service import load_m12_authority
from renpy_story_mapper.project import Project
from renpy_story_mapper.story_map_v2.contracts import StoryMapCore, canonical_hash
from renpy_story_mapper.story_map_v2.persistence import save_story_map_v2
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    PROJECT_SCHEMA,
    StoryMapProjectIdentity,
)
from renpy_story_mapper.story_map_v2.presentation import project_story_map
from renpy_story_mapper.web.api import ApiProblem
from renpy_story_mapper.web.contracts import STORY_MAP_V2_API_ROUTES
from test_story_map_v2_phase03_track_c import _all_arms, _api, _project

ROOT = Path(__file__).parents[1]


def _event_arm_collision(core: StoryMapCore) -> StoryMapCore:
    chunk = core.chunks[0]
    event_id = chunk.events[0].anchor.id
    first_outcome = chunk.branch_outcomes[0]
    collided = replace(
        first_outcome,
        anchor=replace(first_outcome.anchor, id=event_id),
    )
    return replace(
        core,
        chunks=(
            replace(
                chunk,
                branch_outcomes=(collided, *chunk.branch_outcomes[1:]),
            ),
        ),
    )


def _save_core(project_path: Path, core: StoryMapCore) -> None:
    with Project.open(project_path) as project:
        authority = load_m12_authority(project)
        identity = StoryMapProjectIdentity(
            PROJECT_SCHEMA,
            core.schema,
            canonical_hash(asdict(core)),
            core.source_identity,
            authority.graph.source_generation,
            authority.canonical_hash,
            ("game/story.rpy",),
        )
        save_story_map_v2(project, core, identity)


def _first_event_and_arm(page: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    event = page["sections"][0]["events"][0]  # type: ignore[index]
    arm = event["choices"][0]["arms"][0]  # type: ignore[index]
    return event, arm


def _public_ids(core: StoryMapCore) -> tuple[str, str]:
    from renpy_story_mapper.story_map_v2.selection_ids import project_selection_ids

    raw_id = core.chunks[0].events[0].anchor.id
    projection = project_selection_ids(core)
    return projection.public_id("event", raw_id), projection.public_id("arm", raw_id)


def test_event_arm_collision_uses_one_projection_for_map_path_detail_and_source(
    tmp_path: Path,
) -> None:
    source, project_path, core = _project(tmp_path)
    baseline_api = _api(tmp_path, source, project_path)
    try:
        baseline = baseline_api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
    finally:
        baseline_api.close()
    baseline_event, baseline_arm = _first_event_and_arm(baseline)

    collided = _event_arm_collision(core)
    event_id, arm_id = _public_ids(collided)
    direct_page = project_story_map(collided, None)
    direct_event = direct_page.sections[0].events[0]
    direct_arm = direct_event.choices[0].arms[0]
    assert (direct_event.selection_id, direct_arm.selection_id) == (event_id, arm_id)

    _save_core(project_path, collided)
    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        event, arm = _first_event_and_arm(page)
        event_path = api.dispatch(
            "POST", STORY_MAP_V2_API_ROUTES["path"], {"selection_id": event_id}
        )
        arm_path = api.dispatch(
            "POST", STORY_MAP_V2_API_ROUTES["path"], {"selection_id": arm_id}
        )
        event_detail = api.dispatch(
            "POST", STORY_MAP_V2_API_ROUTES["detail"], {"selection_id": event_id}
        )
        arm_detail = api.dispatch(
            "POST", STORY_MAP_V2_API_ROUTES["detail"], {"selection_id": arm_id}
        )
        for route in ("path", "detail"):
            for rejected in (core.chunks[0].events[0].anchor.id, "forged-selection"):
                with pytest.raises(ApiProblem) as raised:
                    api.dispatch(
                        "POST",
                        STORY_MAP_V2_API_ROUTES[route],
                        {"selection_id": rejected},
                    )
                assert raised.value.status == 404
                assert raised.value.selection_id == rejected
    finally:
        api.close()

    assert event_id != arm_id
    assert event_id.startswith("story-map-v2-selection:event:")
    assert arm_id.startswith("story-map-v2-selection:arm:")
    assert len(event_id) <= 512 and len(arm_id) <= 512
    assert core.chunks[0].events[0].anchor.id not in {event_id, arm_id}
    assert event["selection_id"] == event["binding"]["selection_id"] == event_id
    assert arm["selection_id"] == arm["binding"]["selection_id"] == arm_id
    assert event["binding"]["target_id"] == baseline_event["binding"]["target_id"]
    assert arm["binding"]["target_id"] == baseline_arm["binding"]["target_id"]
    assert event["binding"]["target_id"] != arm["binding"]["target_id"]

    for response, selection_id, target_id in (
        (event_path, event_id, event["binding"]["target_id"]),
        (arm_path, arm_id, arm["binding"]["target_id"]),
        (event_detail, event_id, event["binding"]["target_id"]),
        (arm_detail, arm_id, arm["binding"]["target_id"]),
    ):
        assert response["status"] == "available"
        assert response["selection_id"] == selection_id
        assert response["binding"]["target_id"] == target_id
    assert event_detail["source_navigation"]["status"] == "available"
    assert arm_detail["source_navigation"]["status"] == "available"
    assert event_detail["source_navigation"] != arm_detail["source_navigation"]

    continuations = {
        item["rejoin_binding"]["selection_id"]
        for item in _all_arms(event)
        if item["rejoin_binding"] is not None
    }
    assert continuations
    assert all(value.startswith("story-map-v2-continuation:") for value in continuations)
    assert {event_id, arm_id}.isdisjoint(continuations)


def test_colliding_ids_are_stable_across_reopen_cache_and_unrelated_reordering(
    tmp_path: Path,
) -> None:
    source, project_path, core = _project(tmp_path)
    collided = _event_arm_collision(core)
    event_id, arm_id = _public_ids(collided)
    chunk = collided.chunks[0]
    reordered = replace(
        collided,
        chunks=(replace(chunk, branch_outcomes=tuple(reversed(chunk.branch_outcomes))),),
    )
    assert _public_ids(reordered) == (event_id, arm_id)
    for value in (event_id, arm_id):
        assert "game/" not in value
        assert "Arrival" not in value
        assert "Pause at the fountain" not in value

    _save_core(project_path, collided)
    first_api = _api(tmp_path, source, project_path)
    try:
        first_page = first_api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        first_route = first_api.dispatch(
            "POST", STORY_MAP_V2_API_ROUTES["path"], {"selection_id": event_id}
        )
        cached_route = first_api.dispatch(
            "POST", STORY_MAP_V2_API_ROUTES["path"], {"selection_id": event_id}
        )
    finally:
        first_api.close()
    assert cached_route["cached"] is True

    reopened_api = _api(tmp_path, source, project_path)
    try:
        reopened_page = reopened_api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        reopened_route = reopened_api.dispatch(
            "POST", STORY_MAP_V2_API_ROUTES["path"], {"selection_id": event_id}
        )
    finally:
        reopened_api.close()
    assert reopened_route["cached"] is True
    assert _first_event_and_arm(first_page)[0]["selection_id"] == event_id
    assert _first_event_and_arm(reopened_page)[0]["selection_id"] == event_id
    assert first_route["binding"] == reopened_route["binding"]

    _save_core(project_path, reordered)
    reordered_api = _api(tmp_path, source, project_path)
    try:
        reordered_page = reordered_api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
    finally:
        reordered_api.close()
    reordered_event, reordered_arm = _first_event_and_arm(reordered_page)
    assert (reordered_event["selection_id"], reordered_arm["selection_id"]) == (
        event_id,
        arm_id,
    )


def test_raw_colliding_and_forged_ids_are_404_before_missing_authority(
    tmp_path: Path,
) -> None:
    source, project_path, core = _project(tmp_path)
    collided = _event_arm_collision(core)
    event_id, arm_id = _public_ids(collided)
    raw_id = core.chunks[0].events[0].anchor.id
    _save_core(project_path, collided)
    with Project.open(project_path) as project:
        project._require_open().execute(
            "DELETE FROM payloads WHERE collection='m11_analysis_state'"
        )

    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        for route in ("path", "detail"):
            for rejected in (raw_id, "forged-selection"):
                with pytest.raises(ApiProblem) as raised:
                    api.dispatch(
                        "POST",
                        STORY_MAP_V2_API_ROUTES[route],
                        {"selection_id": rejected},
                    )
                assert raised.value.status == 404
                assert raised.value.code == "story_map_v2_selection_not_found"
                assert raised.value.selection_id == rejected
            for recognized in (event_id, arm_id):
                unavailable = api.dispatch(
                    "POST",
                    STORY_MAP_V2_API_ROUTES[route],
                    {"selection_id": recognized},
                )
                assert unavailable == {
                    "schema": f"story-map-v2-{route}-v1",
                    "semantic_level": "route_map" if route == "path" else "detail_evidence",
                    "status": "unavailable",
                    "selection_id": recognized,
                    "reason": "Story Map V2 is stale or unavailable for the current project.",
                }
    finally:
        api.close()
    event, arm = _first_event_and_arm(page)
    assert (event["selection_id"], arm["selection_id"]) == (event_id, arm_id)
    assert event["binding"]["destination_kind"] == "unresolved"
    assert arm["binding"]["destination_kind"] == "unresolved"


def test_role_qualified_ids_become_stale_before_missing_authority_load(
    tmp_path: Path,
) -> None:
    source, project_path, core = _project(tmp_path)
    collided = _event_arm_collision(core)
    stale_ids = _public_ids(collided)
    _save_core(project_path, core)
    with Project.open(project_path) as project:
        project._require_open().execute(
            "DELETE FROM payloads WHERE collection='m11_analysis_state'"
        )

    api = _api(tmp_path, source, project_path)
    try:
        for route in ("path", "detail"):
            for stale_id in stale_ids:
                with pytest.raises(ApiProblem) as raised:
                    api.dispatch(
                        "POST",
                        STORY_MAP_V2_API_ROUTES[route],
                        {"selection_id": stale_id},
                    )
                assert raised.value.status == 404
                assert raised.value.selection_id == stale_id
    finally:
        api.close()


def test_noncolliding_ids_remain_byte_compatible_and_browser_opaque(tmp_path: Path) -> None:
    from renpy_story_mapper.story_map_v2.selection_ids import project_selection_ids

    _source, _project_path, core = _project(tmp_path)
    projection = project_selection_ids(core)
    page = project_story_map(core, None)
    for chunk in core.chunks:
        for event in chunk.events:
            assert projection.public_id("event", event.anchor.id) == event.anchor.id
        for outcome in chunk.branch_outcomes:
            assert projection.public_id("arm", outcome.anchor.id) == outcome.anchor.id
    assert page.sections[0].events[0].selection_id == core.chunks[0].events[0].anchor.id

    chunk = core.chunks[0]
    unsafe_id = "synthetic/chapter.rpy:" + "x" * 600
    unsafe_core = replace(
        core,
        chunks=(
            replace(
                chunk,
                events=(
                    replace(
                        chunk.events[0],
                        anchor=replace(chunk.events[0].anchor, id=unsafe_id),
                    ),
                    *chunk.events[1:],
                ),
            ),
        ),
    )
    bounded = project_selection_ids(unsafe_core).public_id("event", unsafe_id)
    assert bounded.startswith("story-map-v2-selection:event:")
    assert len(bounded) <= 512
    assert "synthetic/" not in bounded and "chapter" not in bounded

    browser_sources = "\n".join(
        (ROOT / "src" / "renpy_story_mapper" / "web" / "static" / name).read_text(
            encoding="utf-8"
        )
        for name in ("app.js", "api.js", "contract.js")
    )
    assert "story-map-v2-selection:" not in browser_sources


def test_same_role_selection_collisions_fail_closed_before_projection(tmp_path: Path) -> None:
    from renpy_story_mapper.story_map_v2.selection_ids import project_selection_ids

    _source, _project_path, core = _project(tmp_path)
    chunk = core.chunks[0]
    duplicate_event = replace(
        chunk.events[1],
        anchor=replace(chunk.events[1].anchor, id=chunk.events[0].anchor.id),
    )
    duplicate_event_core = replace(
        core,
        chunks=(replace(chunk, events=(chunk.events[0], duplicate_event, *chunk.events[2:])),),
    )
    with pytest.raises(ValueError, match="same-role"):
        project_selection_ids(duplicate_event_core)
    with pytest.raises(ValueError, match="same-role"):
        project_story_map(duplicate_event_core, None)

    duplicate_arm = replace(
        chunk.branch_outcomes[1],
        anchor=replace(
            chunk.branch_outcomes[1].anchor,
            id=chunk.branch_outcomes[0].anchor.id,
        ),
    )
    duplicate_arm_core = replace(
        core,
        chunks=(
            replace(
                chunk,
                branch_outcomes=(
                    chunk.branch_outcomes[0],
                    duplicate_arm,
                    *chunk.branch_outcomes[2:],
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="same-role"):
        project_selection_ids(duplicate_arm_core)
    with pytest.raises(ValueError, match="same-role"):
        project_story_map(duplicate_arm_core, None)

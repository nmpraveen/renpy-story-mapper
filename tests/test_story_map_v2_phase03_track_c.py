from __future__ import annotations

import http.client
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import pytest

from renpy_story_mapper.m12_model import DestinationKind
from renpy_story_mapper.m12_service import M12RouteService, load_m12_authority
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ArmMechanic,
    ChoiceMechanic,
    ChunkStatus,
    CoreBranchOutcome,
    CoreChunk,
    CoreEvent,
    EventAnchor,
    ProviderOrigin,
    Reachability,
    StoryMapCore,
    canonical_hash,
)
from renpy_story_mapper.story_map_v2.persistence import save_story_map_v2
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    PROJECT_SCHEMA,
    StoryMapProjectIdentity,
)
from renpy_story_mapper.story_map_v2.presentation import project_story_map
from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.contracts import STORY_MAP_V2_API_ROUTES
from renpy_story_mapper.web.security import SessionSecurity
from renpy_story_mapper.web.server import LocalWebServer, start_in_thread
from renpy_story_mapper.web.state import UserStateStore

FIXTURE = Path(__file__).parent / "fixtures" / "story_map_v2" / "phase03_navigation.rpy"
M12_KINDS = {item.value for item in DestinationKind}
ENVELOPE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "story_map_v2_phase03_api_contract.json"
)


@dataclass
class _Dialogs:
    def choose_source(self, _kind: str) -> None:
        return None

    def choose_open_project(self) -> None:
        return None

    def choose_save_project(self) -> None:
        return None


def _canonical_node_at_line(authority: object, line: int) -> str:
    model = authority.scene_model  # type: ignore[attr-defined]
    matches = {
        atom.primary_node_id
        for atom in model.atoms
        if atom.source_order[0] == "game/story.rpy" and atom.source_order[1] == line
    }
    assert len(matches) == 1, (line, matches)
    return next(iter(matches))


def _branch_starting_at(authority: object, line: int):
    model = authority.scene_model  # type: ignore[attr-defined]
    atoms = {item.id: item for item in model.atoms}
    matches = []
    for branch in model.temporary_branches:
        first_lines = {
            min(atoms[atom_id].source_order[1] for atom_id in arm.atom_ids)
            for arm in branch.arms
        }
        if line in first_lines:
            matches.append(branch)
    assert len(matches) == 1, (line, matches)
    return matches[0]


def _anchor(
    selection_id: str,
    node_id: str,
    line: int,
    *,
    lineage: tuple[ArmLineageStep, ...] = (),
    destination_id: str | None = None,
) -> EventAnchor:
    return EventAnchor(
        selection_id,
        node_id,
        "game/story.rpy",
        line,
        lineage,
        destination_id,
    )


def _core(authority: object) -> StoryMapCore:
    local_key = "game/story.rpy:6"
    outer_key = "game/story.rpy:18"
    nested_key = "game/story.rpy:24"
    outer_second = (ArmLineageStep(outer_key, 2),)
    local_branch = _branch_starting_at(authority, 7)
    outer_branch = _branch_starting_at(authority, 19)
    nested_branch = _branch_starting_at(authority, 25)

    local = ChoiceMechanic(
        local_key,
        "game/story.rpy",
        6,
        (
            ArmMechanic(
                1,
                "Pause at the fountain",
                7,
                9,
                None,
                (),
                _canonical_node_at_line(authority, 8),
                local_branch.merge_node_id,
                15,
                Reachability.REACHABLE,
            ),
            ArmMechanic(
                2,
                "Continue through the atrium",
                10,
                13,
                None,
                (),
                _canonical_node_at_line(authority, 11),
                local_branch.merge_node_id,
                15,
                Reachability.REACHABLE,
            ),
        ),
    )
    outer = ChoiceMechanic(
        outer_key,
        "game/story.rpy",
        18,
        (
            ArmMechanic(
                1,
                "Take the marked passage",
                19,
                21,
                None,
                (),
                _canonical_node_at_line(authority, 20),
                outer_branch.merge_node_id,
                33,
                Reachability.REACHABLE,
            ),
            ArmMechanic(
                2,
                "Explore the side passage",
                22,
                31,
                None,
                (),
                _canonical_node_at_line(authority, 23),
                outer_branch.merge_node_id,
                33,
                Reachability.REACHABLE,
            ),
        ),
    )
    nested = ChoiceMechanic(
        nested_key,
        "game/story.rpy",
        24,
        (
            ArmMechanic(
                1,
                "Return to the marked passage",
                25,
                27,
                None,
                (),
                _canonical_node_at_line(authority, 26),
                nested_branch.merge_node_id,
                33,
                Reachability.REACHABLE,
            ),
            ArmMechanic(
                2,
                "Open the old gate",
                28,
                31,
                None,
                ("resolve_points += 1",),
                _canonical_node_at_line(authority, 30),
                nested_branch.merge_node_id,
                33,
                Reachability.REACHABLE,
            ),
        ),
        outer_second,
    )

    events = (
        CoreEvent(
            "Arrival",
            "The travelers arrive.",
            "game/story.rpy",
            5,
            13,
            (),
            (),
            _anchor("event-early", _canonical_node_at_line(authority, 5), 5),
            Reachability.REACHABLE,
        ),
        CoreEvent(
            "After the fountain",
            "The local paths have rejoined.",
            "game/story.rpy",
            15,
            21,
            (),
            (),
            _anchor("event-post-rejoin", _canonical_node_at_line(authority, 17), 17),
            Reachability.REACHABLE,
        ),
        CoreEvent(
            "Side passage",
            "The alternate arm begins.",
            "game/story.rpy",
            22,
            27,
            (),
            (),
            _anchor(
                "event-alternate",
                _canonical_node_at_line(authority, 23),
                23,
                lineage=outer_second,
                destination_id=_canonical_node_at_line(authority, 23),
            ),
            Reachability.REACHABLE,
        ),
        CoreEvent(
            "Deep chamber",
            "The deepest nested arm reaches the chamber.",
            "game/story.rpy",
            28,
            31,
            (),
            (),
            _anchor(
                "event-deep",
                _canonical_node_at_line(authority, 30),
                30,
                lineage=(*outer_second, ArmLineageStep(nested_key, 2)),
                destination_id=_canonical_node_at_line(authority, 30),
            ),
            Reachability.REACHABLE,
        ),
    )
    choices = (local, outer, nested)
    outcome_specs = (
        (local, (), (8, 11)),
        (outer, (), (20, 23)),
        (nested, outer_second, (26, 30)),
    )
    outcomes: list[CoreBranchOutcome] = []
    for choice, parent, lines in outcome_specs:
        for arm, line in zip(choice.arms, lines, strict=True):
            lineage = (*parent, ArmLineageStep(choice.key, arm.order))
            outcomes.append(
                CoreBranchOutcome(
                    choice.key,
                    arm.order,
                    arm.caption,
                    f"Outcome for {arm.caption}.",
                    _anchor(
                        f"arm-{choice.line}-{arm.order}",
                        _canonical_node_at_line(authority, line),
                        line,
                        lineage=lineage,
                        destination_id=arm.destination_id,
                    ),
                    Reachability.REACHABLE,
                )
            )
    return StoryMapCore(
        "story-map-v2-core-v1",
        "generalized-navigation-fixture-v1",
        ChunkStatus.COMPLETE,
        (
            CoreChunk(
                "generalized-navigation-chunk-v1",
                ChunkStatus.COMPLETE,
                ProviderOrigin.MISSING,
                events,
                choices,
                tuple(outcomes),
                "A generalized route day",
                "Travelers make local and nested choices before a next-day boundary.",
            ),
        ),
        "A generalized route day",
        "A small synthetic story for deterministic navigation tests.",
    )


def _project(tmp_path: Path) -> tuple[Path, Path, StoryMapCore]:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "navigation.rsmproj"
    project = create_ingested_project(project_path, source)
    with project:
        authority = load_m12_authority(project)
        core = _core(authority)
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
    return source, project_path, core


@dataclass(frozen=True)
class _BoundaryCase:
    fixture_name: str
    rejoin_line: int
    after_line: int


def _scene_for_line(authority: object, line: int) -> str:
    model = authority.scene_model  # type: ignore[attr-defined]
    node_id = _canonical_node_at_line(authority, line)
    matching_atoms = {
        atom.id
        for atom in model.atoms
        if node_id in {atom.primary_node_id, *atom.provenance.node_ids}
    }
    scenes = [scene.id for scene in model.scenes if matching_atoms.intersection(scene.atom_ids)]
    assert len(scenes) == 1, (line, scenes)
    return scenes[0]


def _boundary_project(
    tmp_path: Path,
    case: _BoundaryCase,
) -> tuple[Path, Path, str]:
    fixture = Path(__file__).parent / "fixtures" / "story_map_v2" / case.fixture_name
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(fixture.read_bytes())
    project_path = tmp_path / "boundary.rsmproj"
    project = create_ingested_project(project_path, source)
    with project:
        authority = load_m12_authority(project)
        branch = _branch_starting_at(authority, 5)
        choice_key = "game/story.rpy:4"
        arm_specs = ((1, "Left", 5, 6, 6), (2, "Right", 7, 8, 8))
        arms = tuple(
            ArmMechanic(
                order,
                caption,
                start_line,
                end_line,
                None,
                (),
                _canonical_node_at_line(authority, node_line),
                branch.merge_node_id,
                case.rejoin_line,
                Reachability.REACHABLE,
            )
            for order, caption, start_line, end_line, node_line in arm_specs
        )
        choice = ChoiceMechanic(choice_key, "game/story.rpy", 4, arms)
        outcomes = tuple(
            CoreBranchOutcome(
                choice_key,
                arm.order,
                arm.caption,
                f"{arm.caption} outcome.",
                _anchor(
                    f"boundary-arm-{arm.order}",
                    _canonical_node_at_line(authority, line),
                    line,
                    lineage=(ArmLineageStep(choice_key, arm.order),),
                    destination_id=arm.destination_id,
                ),
                Reachability.REACHABLE,
            )
            for arm, (_order, _caption, _start, _end, line) in zip(
                arms, arm_specs, strict=True
            )
        )
        events = (
            CoreEvent(
                "Before",
                "Before the choice.",
                "game/story.rpy",
                3,
                8,
                (),
                (),
                _anchor("boundary-event-before", _canonical_node_at_line(authority, 3), 3),
                Reachability.REACHABLE,
            ),
            CoreEvent(
                "After",
                "After the rejoin.",
                "game/story.rpy",
                case.after_line,
                case.after_line,
                (),
                (),
                _anchor(
                    "boundary-event-after",
                    _canonical_node_at_line(authority, case.after_line),
                    case.after_line,
                ),
                Reachability.REACHABLE,
            ),
        )
        core = StoryMapCore(
            "story-map-v2-core-v1",
            f"boundary-{case.fixture_name}",
            ChunkStatus.COMPLETE,
            (
                CoreChunk(
                    "boundary-chunk",
                    ChunkStatus.COMPLETE,
                    ProviderOrigin.MISSING,
                    events,
                    (choice,),
                    outcomes,
                    "Boundary topology",
                    "A generalized continuation topology.",
                ),
            ),
            "Boundary topology",
            "A generalized continuation topology.",
        )
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
        expected_scene_id = _scene_for_line(authority, case.after_line)
    return source, project_path, expected_scene_id


def _api(tmp_path: Path, source: Path, project_path: Path) -> ProjectApi:
    api = ProjectApi(_Dialogs(), state_store=UserStateStore(tmp_path / "state.json"))
    api._retain_project_path(project_path, source)
    return api


def _post_json(
    server: LocalWebServer,
    path: str,
    body: dict[str, object],
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    payload = json.dumps(body).encode("utf-8")
    connection.request(
        "POST",
        path,
        body=payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            "Host": f"127.0.0.1:{server.port}",
            "Origin": f"http://127.0.0.1:{server.port}",
            "X-RSM-Session": "session-secret",
            "X-RSM-CSRF": "csrf-secret",
        },
    )
    response = connection.getresponse()
    result = json.loads(response.read())
    connection.close()
    assert isinstance(result, dict)
    return response.status, result


def _all_arms(event: dict[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    pending = list(event["choices"])  # type: ignore[arg-type]
    while pending:
        choice = pending.pop(0)
        for arm in choice["arms"]:
            result.append(arm)
            pending.extend(arm["nested_choices"])
    return result


def _assert_envelope_shape(
    payload: dict[str, object],
    family: str,
    status: str,
) -> None:
    contract = json.loads(ENVELOPE_FIXTURE.read_text(encoding="utf-8"))
    expected = contract[family][status]
    assert payload["status"] == status
    assert payload["semantic_level"] == expected["semantic_level"]
    assert set(payload) == set(expected["keys"])
    if "reason" in payload:
        assert isinstance(payload["reason"], str) and 0 < len(payload["reason"]) <= 1_000
    if "explanation" in payload and payload["explanation"] is not None:
        assert isinstance(payload["explanation"], str)
        assert 0 < len(payload["explanation"]) <= 1_000
    if family == "path" and status != "unavailable":
        witness = payload["witness"]
        assert isinstance(witness, dict)
        assert set(witness) == set(contract["path"]["witness_keys"])


def test_shared_api_contract_fixture_has_exact_six_states() -> None:
    contract = json.loads(ENVELOPE_FIXTURE.read_text(encoding="utf-8"))
    assert set(contract) == {"path", "detail"}
    assert set(contract["path"]) == {
        "available",
        "unresolved",
        "unavailable",
        "witness_keys",
    }
    assert set(contract["detail"]) == {
        "available",
        "unresolved",
        "unavailable",
        "source_navigation",
    }


@pytest.mark.parametrize("route", ("path", "detail"))
def test_forged_selection_404_echoes_id_in_dispatch_and_http(
    tmp_path: Path,
    route: str,
) -> None:
    source, project_path, _core_value = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    selection_id = f"forged-{route}-selection"
    expected_error = {
        "code": "story_map_v2_selection_not_found",
        "message": "The Story Map V2 selection is unavailable.",
    }
    with pytest.raises(ApiProblem) as raised:
        api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES[route],
            {"selection_id": selection_id},
        )
    assert raised.value.status == 404
    assert raised.value.code == expected_error["code"]
    assert raised.value.message == expected_error["message"]
    assert raised.value.selection_id == selection_id

    static_root = tmp_path / "static"
    static_root.mkdir()
    server = LocalWebServer(
        "127.0.0.1",
        0,
        api,
        static_root=static_root,
        security=SessionSecurity("session-secret", "csrf-secret"),
    )
    thread = start_in_thread(server)
    try:
        status, body = _post_json(
            server,
            STORY_MAP_V2_API_ROUTES[route],
            {"selection_id": selection_id},
        )
    finally:
        server.close_service()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert status == 404
    assert body == {"error": expected_error, "selection_id": selection_id}


@pytest.mark.parametrize(
    "case",
    (
        _BoundaryCase("phase03_boundary_fallthrough_new_scene.rpy", 10, 12),
        _BoundaryCase("phase03_boundary_direct_label_new_scene.rpy", 10, 12),
        _BoundaryCase("phase03_boundary_same_scene.rpy", 10, 10),
    ),
    ids=("fallthrough-new-scene", "direct-label-new-scene", "same-scene-fallthrough"),
)
def test_boundary_topology_resolves_map_path_and_detail_end_to_end(
    tmp_path: Path,
    case: _BoundaryCase,
) -> None:
    source, project_path, expected_scene_id = _boundary_project(tmp_path, case)
    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        event = page["sections"][0]["events"][0]
        binding = event["choices"][0]["arms"][0]["rejoin_binding"]
        assert binding is not None
        path = api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["path"],
            {"selection_id": binding["selection_id"]},
        )
        detail = api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": binding["selection_id"]},
        )
    finally:
        api.close()

    assert binding["destination_kind"] == "generic_scene"
    assert binding["target_id"] == expected_scene_id
    assert path["status"] == "available"
    assert path["binding"]["target_id"] == expected_scene_id
    assert path["witness"]["scene_titles"]
    assert detail["status"] == "available"
    assert detail["binding"]["target_id"] == expected_scene_id
    assert detail["detail"]["level"] == "scene_detail"


def test_bootstrap_map_path_and_detail_are_bounded_to_selection_ids(tmp_path: Path) -> None:
    source, project_path, _core_value = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        assert api.dispatch("GET", "/api/v1/bootstrap", {})["routes"]["story_map_v2"] == {
            "map": "/api/v1/story-map-v2/map",
            "path": "/api/v1/story-map-v2/path",
            "detail": "/api/v1/story-map-v2/detail",
        }
        with pytest.raises(ValueError, match="unsupported fields"):
            api.dispatch(
                "POST",
                STORY_MAP_V2_API_ROUTES["path"],
                {"selection_id": "event-early", "destination_kind": "terminal"},
            )
        with pytest.raises(ApiProblem) as raised:
            api.dispatch(
                "POST",
                STORY_MAP_V2_API_ROUTES["detail"],
                {
                    "selection_id": "story-map-v2-continuation:"
                    + "f" * 64
                },
            )
        assert raised.value.status == 404
    finally:
        api.close()


def test_every_fixture_event_and_arm_resolves_only_to_supported_m12_authority(
    tmp_path: Path,
) -> None:
    source, project_path, _core_value = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        events = [event for section in page["sections"] for event in section["events"]]
        arms = [arm for event in events for arm in _all_arms(event)]
        bindings = [event["binding"] for event in events] + [arm["binding"] for arm in arms]
        assert len(events) == 4 and len(arms) == 6
        assert all(binding["destination_kind"] in M12_KINDS for binding in bindings)
        assert all(binding["target_id"] for binding in bindings)
        assert all(binding["destination_kind"] != "canonical_node" for binding in bindings)
        assert all(arm["rejoin_binding"] is not None for arm in arms)
        boundary_bindings = [arm["rejoin_binding"] for arm in arms if arm["rejoin_line"] == 33]
        assert {item["destination_kind"] for item in boundary_bindings} == {"generic_scene"}
        assert len({item["selection_id"] for item in boundary_bindings}) == 1
        binding = boundary_bindings[0]
        assert binding["selection_id"].startswith("story-map-v2-continuation:")
        assert len(binding["selection_id"].partition(":")[2]) == 64
        assert binding["detail_kind"] == "story_map_v2_continuation"
        assert binding["detail_id"] == binding["selection_id"]
        assert binding["source"] == {
            "relative_path": "game/story.rpy",
            "start_line": 33,
            "end_line": 33,
        }
    finally:
        api.close()


def test_five_target_classes_project_deterministic_known_witnesses(tmp_path: Path) -> None:
    source, project_path, _core_value = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        events = [event for section in page["sections"] for event in section["events"]]
        arms = [arm for event in events for arm in _all_arms(event)]
        by_event = {item["selection_id"]: item for item in events}
        by_caption = {item["caption"]: item for item in arms}
        boundary = by_caption["Open the old gate"]["rejoin_binding"]
        target_ids = (
            by_event["event-early"]["selection_id"],
            by_event["event-post-rejoin"]["selection_id"],
            by_caption["Explore the side passage"]["selection_id"],
            by_caption["Open the old gate"]["selection_id"],
            boundary["selection_id"],
        )
        results = [
            api.dispatch(
                "POST", STORY_MAP_V2_API_ROUTES["path"], {"selection_id": selection_id}
            )
            for selection_id in target_ids
        ]
        assert all(result["status"] == "available" for result in results)
        assert all(result["semantic_level"] == "route_map" for result in results)
        assert all(result["witness"]["scene_titles"] for result in results)
        assert "Corridor" in results[1]["witness"]["scene_titles"]
        assert "Explore the side passage" in results[2]["witness"]["visible_choices"]
        assert "Open the old gate" in results[3]["witness"]["visible_choices"]
        assert results[3]["witness"]["effects"]
        assert results[4]["binding"]["destination_kind"] == "generic_scene"
        assert "Overlook" in results[4]["witness"]["scene_titles"]
    finally:
        api.close()


def test_detail_reuses_existing_service_and_preserves_qualified_source(tmp_path: Path) -> None:
    source, project_path, _core_value = _project(tmp_path)
    api = _api(tmp_path, source, project_path)
    try:
        detail = api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": "arm-24-2"},
        )
        assert detail["status"] == "available"
        assert detail["semantic_level"] == "detail_evidence"
        assert detail["detail"]["level"] == "scene_detail"
        assert detail["source_navigation"] == {
            "status": "available",
            "path": "game/story.rpy",
            "start_line": 30,
            "end_line": 30,
            "line_basis": "physical",
            "evidence_id": detail["source_navigation"]["evidence_id"],
        }
        assert detail["source_navigation"]["evidence_id"]
    finally:
        api.close()


def test_reopen_is_provider_free_and_stored_navigation_stays_compatible(tmp_path: Path) -> None:
    source, project_path, _core_value = _project(tmp_path)
    first = _api(tmp_path, source, project_path)
    first.close()
    reopened = _api(tmp_path, source, project_path)
    try:
        result = reopened.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["path"],
            {"selection_id": "event-early"},
        )
        assert result["status"] == "available"
        assert result["cached"] in {True, False}
    finally:
        reopened.close()


def test_incomplete_route_keeps_known_prefix_and_explains_uncertainty() -> None:
    from renpy_story_mapper.story_map_v2.navigation import compact_witness

    result = {
        "status": "incomplete_solve",
        "complete": False,
        "termination_reason": "limit:alternatives",
        "recommended": {
            "scene_titles": ["Known opening"],
            "visible_choices": ["Known choice"],
            "requirements": [],
            "satisfying_effect_claims": [],
            "uncertainty_warnings": ["A dynamic transfer remains unresolved."],
            "instructions": [],
        },
    }
    witness, explanation = compact_witness(result)
    assert witness["scene_titles"] == ["Known opening"]
    assert witness["visible_choices"] == ["Known choice"]
    assert "known static prefix" in explanation.casefold()
    assert "proven complete" not in explanation.casefold()


def test_compact_witness_truncation_is_ascii_and_mojibake_free() -> None:
    from renpy_story_mapper.story_map_v2.navigation import (
        MAX_WITNESS_EFFECTS,
        MAX_WITNESS_TEXT_CHARS,
        MAX_WITNESS_TITLE_CHARS,
        compact_witness,
    )

    witness, _explanation = compact_witness(
        {
            "complete": True,
            "recommended": {
                "scene_titles": ["x" * (MAX_WITNESS_TITLE_CHARS + 20)],
                "visible_choices": [],
                "requirements": [],
                "satisfying_effect_claims": [],
                "uncertainty_warnings": [],
                "instructions": [],
            },
        }
    )
    title = witness["scene_titles"][0]
    assert title.endswith("...")
    assert len(title) == MAX_WITNESS_TITLE_CHARS
    assert title.isascii()

    unresolved, _explanation = compact_witness(
        {"complete": False, "recommended": {}},
        selection_effects=tuple(
            f"{index}:" + "e" * (MAX_WITNESS_TEXT_CHARS + 20)
            for index in range(MAX_WITNESS_EFFECTS + 10)
        ),
    )
    assert len(unresolved["effects"]) == MAX_WITNESS_EFFECTS
    assert all(len(effect) <= MAX_WITNESS_TEXT_CHARS for effect in unresolved["effects"])
    assert all(effect.endswith("...") for effect in unresolved["effects"])


def test_duplicate_cross_role_visible_selection_id_is_rejected_before_overwrite(
    tmp_path: Path,
) -> None:
    from renpy_story_mapper.story_map_v2.navigation import StoryMapNavigator

    _source, project_path, core = _project(tmp_path)
    chunk = core.chunks[0]
    first_outcome = chunk.branch_outcomes[0]
    duplicate = replace(
        first_outcome,
        anchor=replace(first_outcome.anchor, id=chunk.events[0].anchor.id),
    )
    duplicate_core = replace(
        core,
        chunks=(
            replace(
                chunk,
                branch_outcomes=(duplicate, *chunk.branch_outcomes[1:]),
            ),
        ),
    )
    with Project.open(project_path) as project, pytest.raises(ValueError, match="collide"):
        StoryMapNavigator(
            load_m12_authority(project),
            M12RouteService(project),
            duplicate_core,
            project_story_map(duplicate_core, None),
        )


def test_zero_match_rejoin_emits_null_binding(tmp_path: Path) -> None:
    from renpy_story_mapper.story_map_v2.navigation import StoryMapNavigator

    _source, project_path, core = _project(tmp_path)
    chunk = core.chunks[0]
    local = chunk.choices[0]
    missing_arm = replace(
        local.arms[0],
        rejoin_node_id="cnode-does-not-exist",
        rejoin_line=999,
    )
    missing_choice = replace(local, arms=(missing_arm, local.arms[1]))
    missing_core = replace(
        core,
        chunks=(replace(chunk, choices=(missing_choice, *chunk.choices[1:])),),
    )
    with Project.open(project_path) as project:
        page = StoryMapNavigator(
            load_m12_authority(project),
            M12RouteService(project),
            missing_core,
            project_story_map(missing_core, None),
        ).bound_page()
    event = page.sections[0].events[0]
    assert event.choices[0].arms[0].rejoin_binding is None
    assert event.choices[0].arms[1].rejoin_binding is not None


def test_map_fallback_keeps_story_but_marks_navigation_unresolved(tmp_path: Path) -> None:
    from renpy_story_mapper.story_map_v2.navigation import unresolved_navigation_page

    _source, _project_path, core = _project(tmp_path)
    page = unresolved_navigation_page(project_story_map(core, None))
    events = [event for section in page.sections for event in section.events]
    pending = [choice for event in events for choice in event.choices]
    arms = []
    while pending:
        choice = pending.pop()
        arms.extend(choice.arms)
        pending.extend(
            nested
            for arm in choice.arms
            for nested in arm.nested_choices
        )

    assert events
    assert all(event.binding.destination_kind == "unresolved" for event in events)
    assert all(arm.binding.destination_kind == "unresolved" for arm in arms)
    assert all(arm.rejoin_binding is None for arm in arms)


def test_missing_unique_detail_target_stays_recognized_and_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path, _core_value = _project(tmp_path)

    def missing_detail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise KeyError("current target disappeared")

    monkeypatch.setattr("renpy_story_mapper.web.api.scene_detail", missing_detail)
    api = _api(tmp_path, source, project_path)
    try:
        detail = api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": "event-early"},
        )
    finally:
        api.close()

    _assert_envelope_shape(detail, "detail", "unresolved")
    assert detail["selection_id"] == "event-early"
    assert detail["binding"]["destination_kind"] in M12_KINDS
    assert detail["source_navigation"]["status"] == "available"


def test_unavailable_detail_result_stays_recognized_and_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, project_path, _core_value = _project(tmp_path)

    def unavailable_detail(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "unavailable", "reason": "current detail is unavailable"}

    monkeypatch.setattr("renpy_story_mapper.web.api.scene_detail", unavailable_detail)
    api = _api(tmp_path, source, project_path)
    try:
        detail = api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": "event-early"},
        )
    finally:
        api.close()

    _assert_envelope_shape(detail, "detail", "unresolved")
    assert detail["selection_id"] == "event-early"
    assert detail["binding"]["destination_kind"] in M12_KINDS
    assert detail["source_navigation"]["status"] == "available"


def test_missing_m12_authority_keeps_map_and_fails_path_and_detail_closed(
    tmp_path: Path,
) -> None:
    source, project_path, _core_value = _project(tmp_path)
    with Project.open(project_path) as project:
        project._require_open().execute(
            "DELETE FROM payloads WHERE collection='m11_analysis_state'"
        )

    api = _api(tmp_path, source, project_path)
    try:
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        path = api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["path"],
            {"selection_id": "event-early"},
        )
        detail = api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": "event-early"},
        )
    finally:
        api.close()

    events = [event for section in page["sections"] for event in section["events"]]
    arms = [arm for event in events for arm in _all_arms(event)]
    assert page["status"] == "fallback"
    assert events
    assert all(event["binding"]["destination_kind"] == "unresolved" for event in events)
    assert all(arm["binding"]["destination_kind"] == "unresolved" for arm in arms)
    assert all(arm["rejoin_binding"] is None for arm in arms)
    _assert_envelope_shape(path, "path", "unavailable")
    _assert_envelope_shape(detail, "detail", "unavailable")
    assert path["selection_id"] == detail["selection_id"] == "event-early"
    for route in ("path", "detail"):
        with pytest.raises(ApiProblem) as raised:
            api.dispatch(
                "POST",
                STORY_MAP_V2_API_ROUTES[route],
                {"selection_id": "forged-selection"},
            )
        assert raised.value.status == 404
        assert raised.value.code == "story_map_v2_selection_not_found"
        assert raised.value.message == "The Story Map V2 selection is unavailable."
        assert raised.value.selection_id == "forged-selection"


def test_detail_status_shapes_distinguish_available_unresolved_and_unavailable(
    tmp_path: Path,
) -> None:
    from renpy_story_mapper.story_map_v2.navigation import continuation_selection_id

    source, project_path, core = _project(tmp_path)
    available_api = _api(tmp_path, source, project_path)
    try:
        available = available_api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": "event-early"},
        )
        available_path = available_api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["path"],
            {"selection_id": "event-early"},
        )
    finally:
        available_api.close()
    assert available["status"] == "available"
    assert available["semantic_level"] == "detail_evidence"
    assert available["selection_id"] == "event-early"
    _assert_envelope_shape(available, "detail", "available")
    _assert_envelope_shape(available_path, "path", "available")
    assert available["detail"]["level"] == "scene_detail"
    source_contract = json.loads(ENVELOPE_FIXTURE.read_text(encoding="utf-8"))["detail"][
        "source_navigation"
    ]
    assert set(available["source_navigation"]) == set(source_contract["available_keys"])

    chunk = core.chunks[0]
    local = chunk.choices[0]
    missing_arm = replace(
        local.arms[0],
        rejoin_node_id="cnode-does-not-exist",
        rejoin_line=999,
    )
    missing_core = replace(
        core,
        chunks=(
            replace(
                chunk,
                choices=(replace(local, arms=(missing_arm, local.arms[1])), *chunk.choices[1:]),
            ),
        ),
    )
    with Project.open(project_path) as project:
        authority = load_m12_authority(project)
        identity = StoryMapProjectIdentity(
            PROJECT_SCHEMA,
            missing_core.schema,
            canonical_hash(asdict(missing_core)),
            missing_core.source_identity,
            authority.graph.source_generation,
            authority.canonical_hash,
            ("game/story.rpy",),
        )
        save_story_map_v2(project, missing_core, identity)
    unresolved_id = continuation_selection_id(
        "game/story.rpy", "cnode-does-not-exist", 999
    )
    unresolved_api = _api(tmp_path, source, project_path)
    try:
        unresolved = unresolved_api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": unresolved_id},
        )
        unresolved_path = unresolved_api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["path"],
            {"selection_id": unresolved_id},
        )
    finally:
        unresolved_api.close()
    assert unresolved["status"] == "unresolved"
    assert unresolved["semantic_level"] == "detail_evidence"
    assert unresolved["selection_id"] == unresolved_id
    assert unresolved["binding"]["destination_kind"] == "unresolved"
    assert unresolved["source_navigation"]["status"] == "unavailable"
    assert unresolved["reason"]
    _assert_envelope_shape(unresolved, "detail", "unresolved")
    _assert_envelope_shape(unresolved_path, "path", "unresolved")
    assert unresolved_path["complete"] is False
    assert unresolved_path["explanation"]
    assert set(unresolved["source_navigation"]) == set(
        source_contract["unavailable_keys"]
    )

    empty_source = tmp_path / "empty-game"
    empty_source.mkdir()
    (empty_source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    empty_project = tmp_path / "empty.rsmproj"
    create_ingested_project(empty_project, empty_source).close()
    unavailable_api = _api(tmp_path, empty_source, empty_project)
    try:
        unavailable = unavailable_api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["detail"],
            {"selection_id": "event-early"},
        )
        unavailable_path = unavailable_api.dispatch(
            "POST",
            STORY_MAP_V2_API_ROUTES["path"],
            {"selection_id": "event-early"},
        )
    finally:
        unavailable_api.close()
    assert unavailable == {
        "schema": "story-map-v2-detail-v1",
        "semantic_level": "detail_evidence",
        "status": "unavailable",
        "selection_id": "event-early",
        "reason": "Story Map V2 is unavailable for the current project.",
    }
    _assert_envelope_shape(unavailable, "detail", "unavailable")
    _assert_envelope_shape(unavailable_path, "path", "unavailable")


def test_navigation_module_has_no_provider_or_rejected_stack_dependency() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "renpy_story_mapper"
        / "story_map_v2"
        / "navigation.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "synthesis_transport",
        "cloud_transport",
        "loopback_transport",
        "narrative_map",
        "organization",
        "renpy_story_mapper.narrative",
        "\u00e2\u20ac\u00a6",
        "\u00c2",
        "\u00f0\u0178",
    ):
        assert forbidden not in source


def test_frozen_continuation_identity_contract_is_exact() -> None:
    from renpy_story_mapper.story_map_v2.navigation import continuation_selection_id

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "story_map_v2_phase03_continuation_contract.json")
        .read_text(encoding="utf-8")
    )
    expected = fixture["request"]["selection_id"]
    assert continuation_selection_id(
        "game/story.rpy", "node-day-two-boundary", 793
    ) == expected

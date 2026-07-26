from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest

from renpy_story_mapper.project import PayloadRecord, Project, SourceFingerprint
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
from renpy_story_mapper.story_map_v2.persistence import (
    StaleStoryMapV2Error,
    load_story_map_v2,
    load_story_map_v2_for_current_project,
    save_story_map_v2,
)
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    StoryMapProjectIdentity,
    SynthesisFailureKind,
    SynthesisProviderReply,
    SynthesisStatus,
)
from renpy_story_mapper.story_map_v2.presentation import project_story_map
from renpy_story_mapper.story_map_v2.synthesis import (
    SynthesisRefusalError,
    SynthesisValidationError,
    build_synthesis_preview,
    build_synthesis_request,
    complete_synthesis,
    deserialize_synthesis_response,
    execute_synthesis,
    serialize_synthesis_request,
)
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.contracts import STORY_MAP_V2_API_ROUTES


def _anchor(
    key: str,
    line: int,
    *,
    lineage: tuple[ArmLineageStep, ...] = (),
    destination: str | None = None,
) -> EventAnchor:
    return EventAnchor(
        id=f"event-{key}",
        canonical_node_id=f"node-{key}",
        relative_path="story/chapter.rpy",
        line=line,
        arm_lineage=lineage,
        destination_id=destination,
    )


def _arm(
    order: int,
    caption: str,
    line: int,
    *,
    destination: str,
    rejoin: str | None,
) -> ArmMechanic:
    return ArmMechanic(
        order=order,
        caption=caption,
        start_line=line,
        end_line=line + 3,
        condition=None if order == 1 else "trust >= 2",
        effects=(f"route_{order} = True",),
        destination_id=destination,
        rejoin_node_id=rejoin,
        rejoin_line=70 if rejoin else None,
        reachability=Reachability.REACHABLE,
    )


def synthetic_core() -> StoryMapCore:
    outer_key = "story/chapter.rpy:30"
    nested_key = "story/chapter.rpy:45"
    outer = ChoiceMechanic(
        key=outer_key,
        relative_path="story/chapter.rpy",
        line=30,
        arms=(
            _arm(1, "Cross the bridge", 31, destination="node-bridge", rejoin="node-rejoin"),
            _arm(2, "Take the tunnel", 40, destination="node-tunnel", rejoin="node-rejoin"),
        ),
    )
    nested_parent = (ArmLineageStep(outer_key, 2),)
    nested = ChoiceMechanic(
        key=nested_key,
        relative_path="story/chapter.rpy",
        line=45,
        parent_lineage=nested_parent,
        arms=(
            _arm(1, "Light a lantern", 46, destination="node-light", rejoin="node-rejoin"),
            _arm(2, "Continue in darkness", 52, destination="node-dark", rejoin="node-rejoin"),
        ),
    )
    events = tuple(
        CoreEvent(
            title=f"Chapter moment {index}",
            summary=f"The group reaches synthetic moment {index}.",
            relative_path="story/chapter.rpy",
            start_line=1 + index * 20,
            end_line=20 + index * 20,
            characters=("Ari",) if index % 2 else ("Ari", "Bo"),
            warnings=() if index != 4 else ("A route remains unresolved.",),
            anchor=_anchor(str(index), 1 + index * 20),
            reachability=Reachability.REACHABLE,
        )
        for index in range(6)
    )
    outcomes = (
        CoreBranchOutcome(
            outer_key,
            1,
            outer.arms[0].caption,
            "They cross safely.",
            _anchor("outer-1", 31, destination="node-bridge"),
            Reachability.REACHABLE,
        ),
        CoreBranchOutcome(
            outer_key,
            2,
            outer.arms[1].caption,
            "They enter the tunnel.",
            _anchor("outer-2", 40, destination="node-tunnel"),
            Reachability.REACHABLE,
        ),
        CoreBranchOutcome(
            nested_key,
            1,
            nested.arms[0].caption,
            "The tunnel becomes visible.",
            _anchor(
                "nested-1",
                46,
                lineage=(*nested_parent, ArmLineageStep(nested_key, 1)),
                destination="node-light",
            ),
            Reachability.REACHABLE,
        ),
        CoreBranchOutcome(
            nested_key,
            2,
            nested.arms[1].caption,
            "They proceed carefully.",
            _anchor(
                "nested-2",
                52,
                lineage=(*nested_parent, ArmLineageStep(nested_key, 2)),
                destination="node-dark",
            ),
            Reachability.REACHABLE,
        ),
    )
    return StoryMapCore(
        schema="story-map-v2-core-v1",
        source_identity="synthetic-source-v1",
        status=ChunkStatus.COMPLETE,
        chunks=(
            CoreChunk(
                "synthetic-chunk",
                ChunkStatus.COMPLETE,
                ProviderOrigin.CLOUD,
                events,
                (outer, nested),
                branch_outcomes=outcomes,
                scope_title="Synthetic chapter",
                scope_overview="A small generalized branching story.",
            ),
        ),
        title="Synthetic story",
        overview="A generalized story used only for tests.",
    )


def project_identity(
    core: StoryMapCore,
    *,
    authority_hash: str = "a" * 64,
) -> StoryMapProjectIdentity:
    return StoryMapProjectIdentity(
        schema="story-map-v2-project-v1",
        core_schema=core.schema,
        core_hash=canonical_hash(asdict(core)),
        source_identity=core.source_identity,
        source_generation="b" * 64,
        authority_hash=authority_hash,
        source_paths=("story/chapter.rpy",),
    )


def valid_response(event_ids: tuple[str, ...]) -> str:
    return (
        '{"story_title":"A synthetic journey","story_overview":"Friends choose how to travel.",'
        '"ordered_sections":['
        f'{{"section_title":"One","section_summary":"Opening.","event_anchor_ids":["{event_ids[0]}"]}},'
        f'{{"section_title":"Two","section_summary":"A decision.",'
        f'"event_anchor_ids":["{event_ids[1]}"]}},'
        f'{{"section_title":"Three","section_summary":"Consequences.",'
        f'"event_anchor_ids":["{event_ids[3]}"]}},'
        f'{{"section_title":"Four","section_summary":"Return.","event_anchor_ids":["{event_ids[4]}"]}},'
        f'{{"section_title":"Five","section_summary":"Close.","event_anchor_ids":["{event_ids[5]}"]}}],'
        '"optional_threads":[]}'
    )


def test_synthesis_strictly_rejects_unknown_duplicate_reverse_empty_and_duplicate_keys() -> None:
    core = synthetic_core()
    ids = tuple(event.anchor.id for event in core.chunks[0].events)
    invalid = (
        valid_response(ids).replace(ids[3], "foreign-anchor"),
        valid_response(ids).replace(f'["{ids[1]}"]', f'["{ids[0]}"]'),
        valid_response(ids).replace(f'["{ids[3]}"]', f'["{ids[4]}","{ids[3]}"]'),
        valid_response(ids).replace(f'["{ids[3]}"]', "[]"),
        valid_response(ids).replace(
            '"story_title":"A synthetic journey"',
            '"story_title":"A synthetic journey","story_title":"Duplicate"',
        ),
    )
    for payload in invalid:
        with pytest.raises(SynthesisValidationError):
            deserialize_synthesis_response(payload, ids)


def test_structurally_valid_omission_is_inserted_once_in_nearest_section_with_one_note() -> None:
    core = synthetic_core()
    ids = tuple(event.anchor.id for event in core.chunks[0].events)
    response = deserialize_synthesis_response(valid_response(ids), ids)
    completed = complete_synthesis(response, ids)

    flattened = tuple(
        anchor for section in completed.ordered_sections for anchor in section.event_anchor_ids
    )
    assert flattened == ids
    assert completed.ordered_sections[1].event_anchor_ids == (ids[1], ids[2])
    assert completed.analysis_notes == (
        "One accepted event omitted by synthesis was placed chronologically by the app.",
    )


def test_request_payload_contains_only_approved_story_facing_fields() -> None:
    core = synthetic_core()
    request = build_synthesis_request(core, project_identity(core))
    payload = serialize_synthesis_request(request).decode()

    assert set(request.transmitted_fields) == {
        "schema",
        "prompt_version",
        "instructions",
        "events",
        "branch_outcomes",
        "choices",
    }
    assert "raw_text" not in payload
    assert "source_generation" not in payload
    assert "authority_hash" not in payload
    assert "story/chapter.rpy" not in payload
    assert "event-outer-1" in payload


def test_synthesis_lineage_omits_an_external_non_story_ancestor() -> None:
    core = synthetic_core()
    chunk = core.chunks[0]
    outer = replace(
        chunk.choices[0],
        parent_lineage=(ArmLineageStep("control/chapter.rpy:20", 1),),
    )
    projected_core = replace(core, chunks=(replace(chunk, choices=(outer,)),))

    request = build_synthesis_request(projected_core, project_identity(projected_core))

    assert request.choices[0].parent_lineage == ()
    assert projected_core.chunks[0].choices[0].parent_lineage == outer.parent_lineage


def test_synthesis_lineage_keeps_only_the_included_anonymized_story_parent() -> None:
    core = synthetic_core()
    chunk = core.chunks[0]
    outer, nested = chunk.choices
    nested_with_external_ancestor = replace(
        nested,
        parent_lineage=(
            ArmLineageStep("control/chapter.rpy:20", 1),
            ArmLineageStep(outer.key, 2),
        ),
    )
    projected_core = replace(
        core,
        chunks=(replace(chunk, choices=(outer, nested_with_external_ancestor)),),
    )

    request = build_synthesis_request(projected_core, project_identity(projected_core))

    assert request.choices[1].parent_lineage == (("choice-1", 2),)
    assert (
        projected_core.chunks[0].choices[1].parent_lineage
        == nested_with_external_ancestor.parent_lineage
    )


class _FakeProvider:
    def __init__(self, response: str, *, resolved_model: str = "gpt-5.6-terra") -> None:
        self.response = response
        self.resolved_model = resolved_model
        self.calls = 0

    def synthesize(self, payload, *, response_schema, settings):
        self.calls += 1
        assert settings.model == "gpt-5.6-terra"
        assert settings.reasoning == "high"
        assert settings.fast_mode is False
        assert response_schema["additionalProperties"] is False
        return SynthesisProviderReply(
            payload=self.response,
            provider="fake-sterile",
            requested_model=settings.model,
            resolved_model=self.resolved_model,
            reasoning=settings.reasoning,
            fast_mode=settings.fast_mode,
            input_tokens=123,
            output_tokens=45,
            elapsed_ms=67,
        )


class _RaisingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def synthesize(self, payload, *, response_schema, settings):
        self.calls += 1
        raise self.error


def test_preview_is_zero_submit_and_execution_constructs_once_calls_once_with_exact_identity() -> (
    None
):
    core = synthetic_core()
    ids = tuple(event.anchor.id for event in core.chunks[0].events)
    request = build_synthesis_request(core, project_identity(core))
    constructions = 0
    provider = _FakeProvider(valid_response(ids))

    def factory() -> _FakeProvider:
        nonlocal constructions
        constructions += 1
        return provider

    preview = build_synthesis_preview(request)
    assert constructions == provider.calls == 0
    result = execute_synthesis(request, preview, factory)

    assert constructions == provider.calls == 1
    assert result.status is SynthesisStatus.SUCCEEDED
    assert result.call_count == 1
    assert result.synthesis is not None
    assert result.resolved_model == "gpt-5.6-terra"
    assert result.input_tokens == 123
    assert result.output_tokens == 45


def test_identity_failure_spends_one_call_and_returns_sanitized_failure_without_retry() -> None:
    core = synthetic_core()
    ids = tuple(event.anchor.id for event in core.chunks[0].events)
    request = build_synthesis_request(core, project_identity(core))
    provider = _FakeProvider(valid_response(ids), resolved_model="gpt-5.6-sol")

    result = execute_synthesis(request, build_synthesis_preview(request), lambda: provider)

    assert provider.calls == result.call_count == 1
    assert result.status is SynthesisStatus.FAILED
    assert result.failure_kind is SynthesisFailureKind.IDENTITY
    assert result.synthesis is None
    assert "gpt-5.6-sol" not in (result.sanitized_reason or "")


def test_invalid_response_spends_one_call_and_does_not_store_raw_provider_text() -> None:
    core = synthetic_core()
    request = build_synthesis_request(core, project_identity(core))
    provider = _FakeProvider('{"private":"provider text"}')

    result = execute_synthesis(request, build_synthesis_preview(request), lambda: provider)

    assert provider.calls == result.call_count == 1
    assert result.failure_kind is SynthesisFailureKind.INVALID_RESPONSE
    assert "private" not in (result.sanitized_reason or "")


@pytest.mark.parametrize(
    ("error", "kind"),
    (
        (SynthesisRefusalError("private refusal text"), SynthesisFailureKind.REFUSED),
        (TimeoutError("private timeout text"), SynthesisFailureKind.TIMEOUT),
        (RuntimeError("private transport text"), SynthesisFailureKind.TRANSPORT),
    ),
)
def test_submitted_failure_matrix_spends_one_call_without_retry_or_raw_error(
    error: Exception,
    kind: SynthesisFailureKind,
) -> None:
    core = synthetic_core()
    request = build_synthesis_request(core, project_identity(core))
    provider = _RaisingProvider(error)

    result = execute_synthesis(request, build_synthesis_preview(request), lambda: provider)

    assert provider.calls == result.call_count == 1
    assert result.failure_kind is kind
    assert "private" not in (result.sanitized_reason or "")


def test_unavailable_or_failed_synthesis_uses_complete_chronological_fallback() -> None:
    core = synthetic_core()
    request = build_synthesis_request(core, project_identity(core))
    unavailable = execute_synthesis(
        request,
        build_synthesis_preview(request),
        lambda: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    assert unavailable.call_count == 0
    assert unavailable.failure_kind is SynthesisFailureKind.TRANSPORT
    for synthesis in (None, unavailable):
        page = project_story_map(core, synthesis)
        flattened = tuple(
            event.selection_id for section in page.sections for event in section.events
        )
        assert page.status == "fallback"
        assert flattened == tuple(event.anchor.id for event in core.chunks[0].events)


def test_validated_synthesis_round_trips_with_exact_project_identity(tmp_path: Path) -> None:
    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    request = build_synthesis_request(core, identity)
    ids = tuple(event.anchor.id for event in core.chunks[0].events)
    result = execute_synthesis(
        request,
        build_synthesis_preview(request),
        lambda: _FakeProvider(valid_response(ids)),
    )
    with _create_project(tmp_path / "synthesized.rsmp", identity) as project:
        save_story_map_v2(project, core, identity, result)
        loaded = load_story_map_v2(project, expected_identity=identity)

    assert loaded is not None
    assert loaded.synthesis == result
    assert project_story_map(loaded.core, loaded.synthesis).status == "synthesized"


def _create_project(path: Path, identity: StoryMapProjectIdentity) -> Project:
    project = Project.create(path)
    project.refresh_sources(
        (SourceFingerprint(identity.source_paths[0], "c" * 64, 10, modified_ns=1),)
    )
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": identity.source_generation,
        "nodes": [],
    }
    authority_hash = canonical_hash(canonical)
    assert identity.authority_hash == authority_hash
    project.write_payloads(
        (PayloadRecord("m10_canonical_graph", "authoritative", canonical, identity.source_paths),)
    )
    return project


def test_project_storage_round_trip_stale_rejection_and_provider_free_reopen(
    tmp_path: Path,
) -> None:
    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    project_path = tmp_path / "story.rsmp"
    with _create_project(project_path, identity) as project:
        save_story_map_v2(project, core, identity)
        loaded = load_story_map_v2(project, expected_identity=identity)
        assert loaded is not None and loaded.core == core
        assert project.payload_keys("story_map_v2") == ("current",)

    constructions = 0
    with Project.open(project_path) as reopened:
        loaded = load_story_map_v2_for_current_project(reopened)
        assert loaded is not None and loaded.core == core
    assert constructions == 0

    stale = replace(identity, authority_hash="d" * 64)
    with Project.open(project_path) as reopened, pytest.raises(StaleStoryMapV2Error):
        load_story_map_v2(reopened, expected_identity=stale)


def test_source_refresh_invalidates_the_single_project_bound_record(tmp_path: Path) -> None:
    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    with _create_project(tmp_path / "story.rsmp", identity) as project:
        save_story_map_v2(project, core, identity)
        project.refresh_sources(
            (SourceFingerprint(identity.source_paths[0], "d" * 64, 11, modified_ns=2),)
        )
        assert load_story_map_v2_for_current_project(project) is None


def test_projection_preserves_event_arm_order_nested_ownership_and_python_mechanics() -> None:
    core = synthetic_core()
    page = project_story_map(core, synthesis=None)

    events = tuple(event for section in page.sections for event in section.events)
    assert tuple(event.selection_id for event in events) == tuple(
        event.anchor.id for event in core.chunks[0].events
    )
    outer = events[1].choices[0]
    assert tuple(arm.caption for arm in outer.arms) == ("Cross the bridge", "Take the tunnel")
    assert outer.arms[0].nested_choices == ()
    assert outer.arms[1].nested_choices[0].key == "story/chapter.rpy:45"
    nested_arms = outer.arms[1].nested_choices[0].arms
    assert nested_arms[1].condition == "trust >= 2"
    assert nested_arms[1].effects == ("route_2 = True",)
    assert nested_arms[1].destination_id == "node-dark"
    assert nested_arms[1].rejoin_node_id == "node-rejoin"


def test_projection_treats_external_only_choice_lineage_as_a_fallback_root() -> None:
    core = synthetic_core()
    chunk = core.chunks[0]
    outer = replace(
        chunk.choices[0],
        parent_lineage=(ArmLineageStep("control/chapter.rpy:20", 1),),
    )
    projected_core = replace(core, chunks=(replace(chunk, choices=(outer,)),))

    page = project_story_map(projected_core, synthesis=None)

    events = tuple(event for section in page.sections for event in section.events)
    assert page.status == "fallback"
    assert tuple(event.selection_id for event in events) == tuple(
        event.anchor.id for event in projected_core.chunks[0].events
    )
    assert events[1].choices[0].key == outer.key
    assert projected_core.chunks[0].choices[0].parent_lineage == outer.parent_lineage


def test_projection_nests_after_filtering_a_leading_external_ancestor() -> None:
    core = synthetic_core()
    chunk = core.chunks[0]
    outer, nested = chunk.choices
    nested_with_external_ancestor = replace(
        nested,
        parent_lineage=(
            ArmLineageStep("control/chapter.rpy:20", 1),
            ArmLineageStep(outer.key, 2),
        ),
    )
    projected_core = replace(
        core,
        chunks=(replace(chunk, choices=(outer, nested_with_external_ancestor)),),
    )

    page = project_story_map(projected_core, synthesis=None)

    events = tuple(event for section in page.sections for event in section.events)
    root_choices = tuple(choice for event in events for choice in event.choices)
    assert tuple(choice.key for choice in root_choices) == (outer.key,)
    assert root_choices[0].arms[0].nested_choices == ()
    assert root_choices[0].arms[1].nested_choices[0].key == nested.key
    assert (
        projected_core.chunks[0].choices[1].parent_lineage
        == nested_with_external_ancestor.parent_lineage
    )


def test_projection_still_rejects_malformed_included_parent_ancestry() -> None:
    core = synthetic_core()
    chunk = core.chunks[0]
    outer, nested = chunk.choices
    malformed = replace(
        nested,
        parent_lineage=(
            ArmLineageStep(nested.key, 1),
            ArmLineageStep(outer.key, 2),
        ),
    )
    projected_core = replace(
        core,
        chunks=(replace(chunk, choices=(outer, malformed)),),
    )

    with pytest.raises(ValueError, match="not represented by accepted mechanics"):
        project_story_map(projected_core, synthesis=None)
    assert projected_core.chunks[0].choices[1].parent_lineage == malformed.parent_lineage


class _Dialogs:
    def choose_source(self, kind: str):
        return None

    def choose_open_project(self):
        return None

    def choose_save_project(self):
        return None


def test_bootstrap_exposes_read_only_map_and_endpoint_never_uses_historical_fallback(
    tmp_path: Path,
) -> None:
    core = synthetic_core()
    canonical = {
        "schema": "m10-canonical-graph-v1",
        "source_generation": "b" * 64,
        "nodes": [],
    }
    identity = project_identity(core, authority_hash=canonical_hash(canonical))
    project_path = tmp_path / "story.rsmp"
    with _create_project(project_path, identity) as project:
        save_story_map_v2(project, core, identity)

    api = ProjectApi(_Dialogs())
    try:
        api._project_path = project_path
        bootstrap = api.dispatch("GET", "/api/v1/bootstrap", {})
        assert isinstance(bootstrap, dict)
        assert bootstrap["routes"]["story_map_v2"] == STORY_MAP_V2_API_ROUTES
        page = api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        assert isinstance(page, dict)
        assert page["status"] == "fallback"
        assert len(page["sections"]) == 1
        with pytest.raises(ValueError):
            api.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {"provider": "forbidden"})
    finally:
        api.close()

    unavailable = ProjectApi(_Dialogs())
    empty_path = tmp_path / "empty.rsmp"
    Project.create(empty_path).close()
    try:
        unavailable._project_path = empty_path
        page = unavailable.dispatch("POST", STORY_MAP_V2_API_ROUTES["map"], {})
        assert page == {
            "schema": "story-map-v2-page-v1",
            "status": "unavailable",
            "reason": "Story Map V2 is unavailable for the current project.",
            "title": "Story Map",
            "overview": "",
            "analysis_notes": [],
            "sections": [],
        }
    finally:
        unavailable.close()

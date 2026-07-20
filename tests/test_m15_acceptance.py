from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from renpy_story_mapper.canonical_graph_contract import CanonicalNodeKind
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.narrative_map import (
    NarrativeNodeKind,
    SourceLocator,
    create_leading_technical_coverage_correction,
)

ROOT = Path(__file__).resolve().parents[1]


def _acceptance_module() -> ModuleType:
    path = ROOT / "scripts" / "m15_provider_free_acceptance.py"
    spec = importlib.util.spec_from_file_location("m15_provider_free_acceptance_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_synthetic_case_executes_the_complete_track_a_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _acceptance_module()
    calls = {"corridors": 0, "assembly": 0, "map": 0}
    for attribute, counter in (
        ("build_narrative_corridors", "corridors"),
        ("assemble_narrative_events", "assembly"),
        ("build_narrative_map", "map"),
    ):
        original = cast(Callable[..., object], getattr(module, attribute))

        def counted(
            *args: object,
            _original: Callable[..., object] = original,
            _counter: str = counter,
            **kwargs: object,
        ) -> object:
            calls[_counter] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, attribute, counted)

    report = module.evaluate_synthetic_manifest(
        ROOT / "tests" / "fixtures" / "m15" / "acceptance_cases.json"
    )

    assert report["case_count"] == 9
    assert calls == {"corridors": 9, "assembly": 9, "map": 9}


def _synthetic_pipeline(
    module: ModuleType,
    case_id: str,
    signals: tuple[str, ...],
) -> tuple[object, ...]:
    canonical, model = module._synthetic_authority(case_id, signals)
    corridors = module.build_narrative_corridors(canonical, model)
    events = module.assemble_narrative_events(
        corridors,
        expected_atom_ids=(item.id for item in model.atoms),
    )
    narrative_map = module.build_narrative_map(canonical, events, corridors=corridors)
    return canonical, model, corridors, events, narrative_map


def test_exact_observation_rejects_event_atom_ownership_tampering() -> None:
    module = _acceptance_module()
    canonical, model, corridors, raw_events, narrative_map = _synthetic_pipeline(
        module,
        "local-detour",
        ("choice_split", "arm_0", "arm_1", "proven_rejoin", "continuation"),
    )
    events = list(raw_events)
    left = events[1]
    right = events[-1]
    events[1] = replace(left, ordered_atom_ids=right.ordered_atom_ids)
    events[-1] = replace(right, ordered_atom_ids=left.ordered_atom_ids)
    with pytest.raises(ValueError, match="event atom ownership"):
        module._exact_product_observations(
            canonical,
            model,
            corridors,
            tuple(events),
            narrative_map,
            {},
        )


def test_exact_observation_rejects_reordered_visible_presentation() -> None:
    module = _acceptance_module()
    canonical, model, corridors, events, narrative_map = _synthetic_pipeline(
        module,
        "local-detour",
        ("choice_split", "arm_0", "arm_1", "proven_rejoin", "continuation"),
    )
    nodes = list(narrative_map.nodes)
    nodes[0] = replace(nodes[0], ordinal=1)
    nodes[1] = replace(nodes[1], ordinal=0)
    reordered_map = replace(narrative_map, nodes=tuple(nodes))
    with pytest.raises(ValueError, match="visible map order"):
        module._exact_product_observations(
            canonical,
            model,
            corridors,
            events,
            reordered_map,
            {},
        )


def test_setup_choice_prefix_is_hidden_before_the_prologue_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _acceptance_module()
    nodes = [
        (
            "technical_setup",
            AtomKind.TECHNICAL,
            CanonicalNodeKind.SCRIPT_UNIT,
            "Synthetic setup",
            "statement",
            {},
        ),
        (
            "setup_choice",
            AtomKind.CHOICE,
            CanonicalNodeKind.CHOICE,
            "Synthetic setup choice",
            "menu",
            {},
        ),
        (
            "setup_dialogue",
            AtomKind.DIALOGUE,
            CanonicalNodeKind.SCRIPT_UNIT,
            "Synthetic setup dialogue",
            "statement",
            {},
        ),
        (
            "setup_state",
            AtomKind.STATE_CHANGE,
            CanonicalNodeKind.SCRIPT_UNIT,
            "Synthetic setup state",
            "opaque",
            {},
        ),
        (
            "setup_rejoin",
            AtomKind.NARRATION,
            CanonicalNodeKind.MERGE,
            "Synthetic setup rejoin",
            "merge",
            {},
        ),
        (
            "prologue_anchor",
            AtomKind.VISUAL_CHANGE,
            CanonicalNodeKind.SCRIPT_UNIT,
            "Scene prologue framing",
            "scene",
            {},
        ),
        (
            "prologue_story",
            AtomKind.NARRATION,
            CanonicalNodeKind.SCRIPT_UNIT,
            "Synthetic prologue story",
            "statement",
            {},
        ),
        (
            "day_marker",
            AtomKind.VISUAL_CHANGE,
            CanonicalNodeKind.SCRIPT_UNIT,
            "Scene day",
            "scene",
            {},
        ),
        (
            "day_story",
            AtomKind.NARRATION,
            CanonicalNodeKind.SCRIPT_UNIT,
            "Synthetic day story",
            "statement",
            {},
        ),
    ]
    edges = [
        ("edge-entry", "technical_setup", "setup_choice", "continuation", True, {}),
        ("edge-arm-0", "setup_choice", "setup_dialogue", "choice", True, {}),
        ("edge-arm-1", "setup_choice", "setup_state", "choice", True, {}),
        ("edge-merge-0", "setup_dialogue", "setup_rejoin", "continuation", True, {}),
        ("edge-merge-1", "setup_state", "setup_rejoin", "continuation", True, {}),
        ("edge-prologue", "setup_rejoin", "prologue_anchor", "continuation", True, {}),
        ("edge-prologue-story", "prologue_anchor", "prologue_story", "continuation", True, {}),
        ("edge-day", "prologue_story", "day_marker", "continuation", True, {}),
        ("edge-day-story", "day_marker", "day_story", "continuation", True, {}),
    ]
    regions = [
        (
            "setup-region",
            "local_detour",
            "setup_choice",
            "setup_rejoin",
            ("setup_choice", "setup_dialogue", "setup_state", "setup_rejoin"),
            {
                "arms": [
                    {
                        "id": "setup-arm-0",
                        "ordinal": 0,
                        "entry_node_id": "setup_dialogue",
                        "member_node_ids": ["setup_dialogue"],
                    },
                    {
                        "id": "setup-arm-1",
                        "ordinal": 1,
                        "entry_node_id": "setup_state",
                        "member_node_ids": ["setup_state"],
                    },
                ]
            },
        )
    ]
    monkeypatch.setattr(module, "_synthetic_specs", lambda _case, _signals: (nodes, edges, regions))
    canonical, model = module._synthetic_authority("setup-prefix", ("sanitized",))
    correction = create_leading_technical_coverage_correction(
        canonical,
        model,
        (SourceLocator("synthetic.rpy", 1, 5, "physical_source"),),
        reason="User-approved sanitized leading technical coverage.",
    )
    corridors = module.build_narrative_corridors(
        canonical,
        model,
        technical_correction=correction,
    )
    events = module.assemble_narrative_events(
        corridors,
        expected_atom_ids=(item.id for item in model.atoms),
    )
    narrative_map = module.build_narrative_map(canonical, events, corridors=corridors)

    setup_atom_ids = {
        "atom-technical_setup",
        "atom-setup_choice",
        "atom-setup_dialogue",
        "atom-setup_state",
        "atom-setup_rejoin",
    }
    assert setup_atom_ids <= set(narrative_map.hidden_technical_atom_ids)
    event_by_id = {item.event_id: item for item in events}
    normally_visible = [
        item
        for item in narrative_map.nodes
        if item.kind is not NarrativeNodeKind.TECHNICAL_COVERAGE and item.event_id is not None
    ]
    assert all(
        setup_atom_ids.isdisjoint(event_by_id[item.event_id].ordered_atom_ids)
        for item in normally_visible
    )
    prologue_event = next(item for item in events if "atom-prologue_story" in item.ordered_atom_ids)
    assert any(
        item.event_id == prologue_event.event_id and item.kind is NarrativeNodeKind.EVENT_CLUSTER
        for item in narrative_map.nodes
    )

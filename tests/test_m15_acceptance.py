from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

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

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from renpy_story_mapper.narrative_map import NarrativeNodeKind

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


def test_exact_acceptance_rejects_event_atom_ownership_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _acceptance_module()
    original = module.assemble_narrative_events

    def swapped_membership(*args: object, **kwargs: object) -> tuple[object, ...]:
        events = list(original(*args, **kwargs))
        left = events[1]
        right = events[-1]
        events[1] = replace(left, ordered_atom_ids=right.ordered_atom_ids)
        events[-1] = replace(right, ordered_atom_ids=left.ordered_atom_ids)
        return tuple(events)

    monkeypatch.setattr(module, "assemble_narrative_events", swapped_membership)
    with pytest.raises(ValueError, match="event atom ownership"):
        module.evaluate_exact_msday1(ROOT / "MsDay1", ROOT / "tmp" / "missing.rsmproj")


def test_exact_acceptance_rejects_reordered_visible_clusters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _acceptance_module()
    original = module.build_narrative_map

    def reordered_clusters(*args: object, **kwargs: object) -> object:
        narrative_map = original(*args, **kwargs)
        cluster_ordinals = [
            node.ordinal
            for node in narrative_map.nodes
            if node.kind is NarrativeNodeKind.EVENT_CLUSTER
        ]
        replacement_ordinals = iter(reversed(cluster_ordinals))
        nodes = tuple(
            replace(node, ordinal=next(replacement_ordinals))
            if node.kind is NarrativeNodeKind.EVENT_CLUSTER
            else node
            for node in narrative_map.nodes
        )
        return replace(narrative_map, nodes=nodes)

    monkeypatch.setattr(module, "build_narrative_map", reordered_clusters)
    with pytest.raises(ValueError, match="visible map order"):
        module.evaluate_exact_msday1(ROOT / "MsDay1", ROOT / "tmp" / "missing.rsmproj")

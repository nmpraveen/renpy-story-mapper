from __future__ import annotations

from dataclasses import replace

import pytest

from m15_test_support import linear_authority
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.narrative_map import (
    M15_TECHNICAL_CORRECTION_RULE_VERSION,
    M15_TECHNICAL_CORRECTION_SCHEMA,
    AuthorityBinding,
    BoundaryCandidate,
    BoundarySignal,
    CoverageState,
    LeadingTechnicalCoverageCorrection,
    NarrativeNodeKind,
    QualifiedSourceLocator,
    SourceLocator,
    assemble_narrative_events,
    build_boundary_candidates,
    build_narrative_corridors,
    build_narrative_map,
    resolve_leading_technical_coverage_correction,
)
from renpy_story_mapper.narrative_map.adapters import bind_m15_authority


def _locator(index: int) -> SourceLocator:
    return SourceLocator("game/synthetic.rpy", index + 1, index + 1, "physical_source")


def _qualified(atom_id: str, locator: SourceLocator) -> QualifiedSourceLocator:
    marker = atom_id.removeprefix("atom-")
    return QualifiedSourceLocator(
        atom_id=atom_id,
        primary_node_id=f"node-{marker}",
        evidence_ids=(f"evidence-{marker}",),
        source=locator,
    )


def _correction(
    canonical: object,
    model: object,
    atom_ids: tuple[str, ...] = ("atom-0", "atom-1"),
    locators: tuple[SourceLocator, ...] = (_locator(0), _locator(1)),
    *,
    authority: AuthorityBinding | None = None,
) -> LeadingTechnicalCoverageCorrection:
    return LeadingTechnicalCoverageCorrection(
        authority=authority or bind_m15_authority(canonical, model),  # type: ignore[arg-type]
        reason="User classified the exact leading setup as technical coverage.",
        qualified_locators=tuple(
            _qualified(atom_id, locators[min(index, len(locators) - 1)])
            for index, atom_id in enumerate(atom_ids)
        ),
        ordered_atom_ids=atom_ids,
    )


def _four_story_atoms() -> tuple[object, object]:
    return linear_authority((AtomKind.NARRATION,) * 4)


def test_correction_contract_is_versioned_serializable_stable_and_bounded() -> None:
    canonical, model = _four_story_atoms()
    correction = _correction(canonical, model)
    payload = correction.to_dict()

    assert payload["schema"] == M15_TECHNICAL_CORRECTION_SCHEMA
    assert payload["rule_version"] == M15_TECHNICAL_CORRECTION_RULE_VERSION
    assert payload["correction_id"] == correction.correction_id
    assert payload["normalized_hash"] == correction.normalized_hash
    assert payload["authority"] == bind_m15_authority(canonical, model).to_dict()
    assert payload["ordered_atom_ids"] == ["atom-0", "atom-1"]
    assert payload["qualified_locators"] == [
        _qualified("atom-0", _locator(0)).to_dict(),
        _qualified("atom-1", _locator(1)).to_dict(),
    ]
    assert LeadingTechnicalCoverageCorrection.from_dict(payload) == correction
    assert _correction(canonical, model).correction_id == correction.correction_id

    with pytest.raises(ValueError, match="reason"):
        replace(correction, reason="")
    with pytest.raises(ValueError, match="at most"):
        replace(correction, reason="x" * 501)
    with pytest.raises(ValueError, match="unique"):
        replace(correction, ordered_atom_ids=("atom-0", "atom-0"))
    with pytest.raises(ValueError, match="unique"):
        replace(
            correction,
            qualified_locators=(
                _qualified("atom-0", _locator(0)),
                _qualified("atom-0", _locator(0)),
            ),
        )
    with pytest.raises(ValueError, match="unsupported"):
        replace(correction, rule_version="m15-leading-technical-coverage-rule-v999")
    with pytest.raises(ValueError, match="unsupported"):
        LeadingTechnicalCoverageCorrection.from_dict(
            {**payload, "rule_version": "m15-leading-technical-coverage-rule-v999"}
        )
    with pytest.raises(ValueError, match="schema"):
        LeadingTechnicalCoverageCorrection.from_dict({**payload, "schema": "unknown"})
    with pytest.raises(ValueError, match="normalized hash"):
        LeadingTechnicalCoverageCorrection.from_dict({**payload, "normalized_hash": "0" * 64})


def test_valid_correction_resolves_only_the_exact_strict_prefix() -> None:
    canonical, model = _four_story_atoms()
    correction = _correction(canonical, model)

    assert resolve_leading_technical_coverage_correction(canonical, model, correction) == (
        "atom-0",
        "atom-1",
    )


@pytest.mark.parametrize(
    ("atom_ids", "locators", "authority_change", "message"),
    (
        (("missing",), (_locator(0),), None, "unknown"),
        (("atom-1",), (_locator(1),), None, "prefix"),
        (("atom-1", "atom-0"), (_locator(1), _locator(0)), None, "order|prefix"),
        (("atom-0", "atom-1"), (_locator(0),), None, "locator"),
        (
            ("atom-0", "atom-1", "atom-2", "atom-3"),
            (_locator(0), _locator(1), _locator(2), _locator(3)),
            None,
            "strict prefix",
        ),
        (("atom-0",), (_locator(0),), "source_generation", "authority|stale"),
    ),
)
def test_unknown_stale_mismatched_nonprefix_and_out_of_order_reject(
    atom_ids: tuple[str, ...],
    locators: tuple[SourceLocator, ...],
    authority_change: str | None,
    message: str,
) -> None:
    canonical, model = _four_story_atoms()
    authority = bind_m15_authority(canonical, model)
    if authority_change is not None:
        authority = replace(authority, source_generation="stale-generation")
    correction = _correction(
        canonical,
        model,
        atom_ids,
        locators,
        authority=authority,
    )

    with pytest.raises(ValueError, match=message):
        resolve_leading_technical_coverage_correction(canonical, model, correction)
    conservative = build_narrative_corridors(
        canonical,
        model,
        technical_correction=correction,
    )
    assert all(not item.technical_atom_ids for item in conservative)


def test_mismatched_qualified_occurrence_rejects() -> None:
    canonical, model = _four_story_atoms()
    correction = _correction(canonical, model, ("atom-0",), (_locator(0),))
    correction = replace(
        correction,
        qualified_locators=(replace(correction.qualified_locators[0], primary_node_id="node-1"),),
    )

    with pytest.raises(ValueError, match=r"node|mismatch"):
        resolve_leading_technical_coverage_correction(
            canonical,
            model,
            correction,
        )
    conservative = build_narrative_corridors(
        canonical,
        model,
        technical_correction=correction,
    )
    assert all(not item.technical_atom_ids for item in conservative)


def test_qualified_locator_cannot_name_a_later_repeated_occurrence() -> None:
    canonical, model = _four_story_atoms()
    with pytest.raises(ValueError, match=r"order|tuple"):
        LeadingTechnicalCoverageCorrection(
            authority=bind_m15_authority(canonical, model),
            reason="User classified exact leading technical coverage.",
            qualified_locators=(
                _qualified("atom-0", _locator(0)),
                _qualified("atom-2", _locator(0)),
            ),
            ordered_atom_ids=("atom-0",),
        )


def test_empty_correction_rejects_at_contract_boundary() -> None:
    canonical, model = _four_story_atoms()
    with pytest.raises(ValueError, match="at least one"):
        _correction(canonical, model, (), ())


def test_no_correction_keeps_setup_like_meaningful_story_visible() -> None:
    canonical, model = _four_story_atoms()

    corridors = build_narrative_corridors(canonical, model)
    events = assemble_narrative_events(
        corridors, expected_atom_ids=tuple(a.id for a in model.atoms)
    )
    narrative_map = build_narrative_map(canonical, events, corridors=corridors)

    assert all(not item.technical_atom_ids for item in corridors)
    assert all(item.coverage_state is not CoverageState.TECHNICAL for item in events)
    assert narrative_map.hidden_technical_atom_ids == ()
    assert any(item.kind is NarrativeNodeKind.EVENT_CLUSTER for item in narrative_map.nodes)


def test_valid_correction_creates_one_hard_cut_and_exact_once_ownership() -> None:
    canonical, model = _four_story_atoms()
    correction = _correction(canonical, model)

    corridors = build_narrative_corridors(
        canonical,
        model,
        technical_correction=correction,
    )
    events = assemble_narrative_events(
        corridors,
        expected_atom_ids=tuple(item.id for item in model.atoms),
    )
    narrative_map = build_narrative_map(canonical, events, corridors=corridors)

    assert [item.ordered_atom_ids for item in corridors] == [
        ("atom-0", "atom-1"),
        ("atom-2", "atom-3"),
    ]
    assert corridors[0].hard_boundary_after and corridors[1].hard_boundary_before
    assert corridors[0].technical_atom_ids == ("atom-0", "atom-1")
    assert build_boundary_candidates(corridors) == ()
    assert [atom for event in events for atom in event.ordered_atom_ids] == [
        item.id for item in model.atoms
    ]
    assert events[0].coverage_state is CoverageState.TECHNICAL
    assert events[1].coverage_state is not CoverageState.TECHNICAL
    assert narrative_map.hidden_technical_atom_ids == ("atom-0", "atom-1")
    assert narrative_map.initial_node_ids
    initial = next(
        item for item in narrative_map.nodes if item.node_id in narrative_map.initial_node_ids
    )
    assert initial.event_id == events[1].event_id


def test_correction_preserves_m10_choice_and_edge_authority() -> None:
    canonical, model = linear_authority((AtomKind.NARRATION, AtomKind.CHOICE, AtomKind.NARRATION))
    before = canonical.to_dict()
    plain_corridors = build_narrative_corridors(canonical, model)
    plain_events = assemble_narrative_events(plain_corridors)
    plain_map = build_narrative_map(canonical, plain_events, corridors=plain_corridors)
    correction = _correction(
        canonical,
        model,
        ("atom-0",),
        (_locator(0),),
    )

    corridors = build_narrative_corridors(
        canonical,
        model,
        technical_correction=correction,
    )
    events = assemble_narrative_events(corridors)
    narrative_map = build_narrative_map(canonical, events, corridors=corridors)

    assert canonical.to_dict() == before
    corrected_edge_ids = {
        edge_id for edge in narrative_map.edges for edge_id in edge.authority_edge_ids
    }
    assert corrected_edge_ids <= {item.id for item in canonical.edges}
    assert {edge_id for edge in plain_map.edges for edge_id in edge.authority_edge_ids} <= {
        item.id for item in canonical.edges
    }
    assert sum(item.kind is NarrativeNodeKind.CHOICE for item in narrative_map.nodes) == sum(
        item.kind is NarrativeNodeKind.CHOICE for item in plain_map.nodes
    )


def test_correction_id_invalidates_corridor_candidate_event_and_map_identity() -> None:
    canonical, model = _four_story_atoms()
    correction = _correction(canonical, model)
    corridors = build_narrative_corridors(
        canonical,
        model,
        technical_correction=correction,
    )
    assert all(item.technical_correction_id == correction.correction_id for item in corridors)

    candidate_common = {
        "authority": bind_m15_authority(canonical, model),
        "left_corridor_id": "corridor-left",
        "right_corridor_id": "corridor-right",
        "signals": (BoundarySignal.CAST,),
    }
    plain_candidate = BoundaryCandidate(**candidate_common)
    corrected_candidate = BoundaryCandidate(
        **candidate_common,
        technical_correction_id=correction.correction_id,
    )
    assert plain_candidate.candidate_id != corrected_candidate.candidate_id

    events = assemble_narrative_events(corridors)
    assert all(item.technical_correction_id == correction.correction_id for item in events)
    assert replace(events[0], technical_correction_id=None).event_id != events[0].event_id

    narrative_map = build_narrative_map(canonical, events, corridors=corridors)
    assert narrative_map.technical_correction_id == correction.correction_id
    assert (
        replace(narrative_map, technical_correction_id=None).normalized_hash
        != narrative_map.normalized_hash
    )

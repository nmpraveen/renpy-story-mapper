from __future__ import annotations

import json
from pathlib import Path

import pytest

from renpy_story_mapper.narrative_map.semantic_contracts import (
    M15_WHOLE_SCOPE_EDITORIAL_BATCH_SCHEMA,
    M15_WHOLE_SCOPE_HIERARCHY_PROPOSAL_SCHEMA,
    MAXIMUM_DAY1_PROVIDER_SUBMISSIONS,
    ProposedBeatGroup,
    ProposedMajorCluster,
    SemanticClaimClass,
    SemanticPresentationRole,
    SemanticSummaryClaim,
    WholeScopeEditorialBatch,
    WholeScopeEditorialRecord,
    WholeScopeHierarchyProposal,
    WholeScopeLogicalProvenance,
    WholeScopeSemanticStage,
)

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "src/renpy_story_mapper/narrative_map"


def _beat(key: str, *unit_ids: str) -> ProposedBeatGroup:
    return ProposedBeatGroup(key, unit_ids, 0.9, "Synthetic grouping evidence.")


def _cluster(key: str, *beat_keys: str) -> ProposedMajorCluster:
    return ProposedMajorCluster(key, beat_keys, 0.9, "Synthetic cluster evidence.")


def _claim() -> SemanticSummaryClaim:
    return SemanticSummaryClaim(
        SemanticClaimClass.FACTUAL,
        "A synthetic event occurs.",
        ("evidence-synthetic",),
    )


def _editorial(subject_id: str = "beat-synthetic") -> WholeScopeEditorialRecord:
    return WholeScopeEditorialRecord(
        "beat",
        subject_id,
        "membership-synthetic",
        SemanticPresentationRole.STORY,
        "Synthetic event",
        "A compact synthetic summary.",
        ("Character A",),
        (_claim(),),
    )


def _property_names(value: object) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for child in value.values():
            names.update(_property_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_property_names(child))
    return names


def _assert_provider_schema_subset(value: object) -> None:
    if isinstance(value, dict):
        assert "uniqueItems" not in value
        for child in value.values():
            _assert_provider_schema_subset(child)
    elif isinstance(value, list):
        for child in value:
            _assert_provider_schema_subset(child)


def test_whole_scope_schema_versions_and_authority_boundaries_are_frozen() -> None:
    schema_root = RESOURCE_ROOT / "schemas"
    hierarchy = json.loads((schema_root / "whole_scope_hierarchy_v2.schema.json").read_text())
    editorial = json.loads((schema_root / "whole_scope_editorial_v1.schema.json").read_text())

    assert hierarchy["$id"] == M15_WHOLE_SCOPE_HIERARCHY_PROPOSAL_SCHEMA
    assert editorial["$id"] == M15_WHOLE_SCOPE_EDITORIAL_BATCH_SCHEMA
    _assert_provider_schema_subset([hierarchy, editorial])

    hierarchy_names = _property_names(hierarchy)
    assert {"proposal_key", "ordered_unit_ids", "ordered_beat_keys"} <= hierarchy_names
    assert not hierarchy_names.intersection(
        {"title", "summary", "characters", "claims", "edges", "coordinates", "locators"}
    )
    assert hierarchy["properties"]["beat_groups"]["maxItems"] == 732
    assert hierarchy["properties"]["major_clusters"]["maxItems"] == 16

    editorial_names = _property_names(editorial)
    assert {"title", "summary", "presentation_role", "evidence_ids"} <= editorial_names
    assert not editorial_names.intersection(
        {"ordered_unit_ids", "ordered_beat_keys", "edges", "coordinates", "requirements", "effects"}
    )


def test_whole_scope_prompts_forbid_external_authority_and_authoritative_ai_ids() -> None:
    prompt_root = RESOURCE_ROOT / "prompts"
    hierarchy = json.loads((prompt_root / "whole_scope_hierarchy_v2.json").read_text())
    editorial = json.loads((prompt_root / "whole_scope_editorial_v1.json").read_text())
    combined = json.dumps([hierarchy, editorial]).lower()

    for forbidden in ("filesystem", "web", "private oracle", "gemini", "grok"):
        assert forbidden in combined
    assert "non-authoritative" in combined
    assert "group only supplied authority-bound unit ids" in combined
    assert "cite only supplied evidence ids" in combined


def test_hierarchy_allows_temporary_keys_but_requires_exact_proposal_coverage() -> None:
    proposal = WholeScopeHierarchyProposal(
        "scope-synthetic",
        (_beat("temporary-beat-a", "unit-a"), _beat("temporary-beat-b", "unit-b")),
        (_cluster("temporary-cluster", "temporary-beat-a", "temporary-beat-b"),),
    )
    assert proposal.to_dict()["schema"] == M15_WHOLE_SCOPE_HIERARCHY_PROPOSAL_SCHEMA
    assert proposal.to_dict()["beat_groups"][0]["proposal_key"] == "temporary-beat-a"

    with pytest.raises(ValueError, match="exactly once in proposal order"):
        WholeScopeHierarchyProposal(
            "scope-synthetic",
            (_beat("temporary-beat-a", "unit-a"), _beat("temporary-beat-b", "unit-b")),
            (_cluster("temporary-cluster", "temporary-beat-b"),),
        )
    with pytest.raises(ValueError, match="unit ID values must be unique"):
        _beat("temporary-beat", "unit-a", "unit-a")
    with pytest.raises(ValueError, match="between zero and one"):
        ProposedBeatGroup("temporary-beat", ("unit-a",), True, "Invalid confidence.")


def test_editorial_batch_is_non_authoritative_and_subject_exact() -> None:
    record = _editorial()
    batch = WholeScopeEditorialBatch(
        "scope-synthetic", "hierarchy-hash-synthetic", (record,)
    )
    assert batch.to_dict()["schema"] == M15_WHOLE_SCOPE_EDITORIAL_BATCH_SCHEMA
    assert batch.to_dict()["records"][0]["presentation_role"] == "story"

    with pytest.raises(ValueError, match="subject values must be unique"):
        WholeScopeEditorialBatch(
            "scope-synthetic",
            "hierarchy-hash-synthetic",
            (_editorial(), _editorial()),
        )
    with pytest.raises(ValueError, match="presentation role is unsupported"):
        WholeScopeEditorialRecord(
            "beat",
            "beat-synthetic",
            "membership-synthetic",
            "story",  # type: ignore[arg-type]
            "Synthetic event",
            "A compact synthetic summary.",
            (),
            (_claim(),),
        )


def test_logical_provenance_separates_jobs_from_transport_and_enforces_call_ceiling() -> None:
    provenance = WholeScopeLogicalProvenance(
        WholeScopeSemanticStage.HIERARCHY,
        "logical-stage-h",
        "transport-batch-1",
        "input-hash",
        "manifest-id",
        "provider-identity-hash",
        "cache-identity",
        "scope-synthetic",
        1,
        1,
    )
    assert provenance.logical_job_id != provenance.transport_batch_id
    assert MAXIMUM_DAY1_PROVIDER_SUBMISSIONS == 4

    with pytest.raises(ValueError, match="four-call ceiling"):
        WholeScopeLogicalProvenance(
            WholeScopeSemanticStage.EDITORIAL,
            "logical-stage-e",
            "transport-batch-5",
            "input-hash",
            "manifest-id",
            "provider-identity-hash",
            "cache-identity",
            "scope-synthetic",
            1,
            5,
        )


def test_generalized_fixture_is_synthetic_complete_and_choice_owned() -> None:
    fixture = json.loads(
        (ROOT / "tests/fixtures/m15_1/whole_scope_semantics_v1.json").read_text()
    )
    assert fixture["synthetic"] is True
    assert fixture["schema"] == "m15-whole-scope-generalized-fixture-v1"
    units = fixture["units"]
    unit_ids = [item["unit_id"] for item in units]
    assert unit_ids == fixture["authority_bound_unit_ids"]
    proposed_ids = [
        unit_id
        for group in fixture["stage_h_response"]["beat_groups"]
        for unit_id in group["ordered_unit_ids"]
    ]
    assert proposed_ids == unit_ids
    assert {item["parent_arm_id"] for item in units if item["parent_choice_id"]} == {
        "arm-a",
        "arm-b",
    }
    assert fixture["expected_compiled_adjacent_decisions"]
    assert fixture["stage_e_subjects"][-1]["subject_kind"] == "choice"


def test_legacy_adjacent_gap_resources_remain_available_as_compilation_targets() -> None:
    for relative_path in (
        "schemas/boundary_window_v3.schema.json",
        "schemas/semantic_summary_v3.schema.json",
        "prompts/semantic_boundary_v3.json",
        "prompts/semantic_summary_v3.json",
    ):
        assert (RESOURCE_ROOT / relative_path).is_file()

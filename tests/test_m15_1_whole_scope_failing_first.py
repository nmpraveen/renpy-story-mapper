"""Executable ownership boundaries for the M15.1 whole-scope implementation tracks.

This file must collect cleanly and fail deterministically at the shared freeze. Each assertion
names one missing implementation seam; track commits turn only their owned assertions green.
"""

from __future__ import annotations

import importlib

from renpy_story_mapper.narrative_map.provider import ProviderJobKind
from renpy_story_mapper.narrative_map.service import NarrativeMapService


def test_track_a_validates_complete_whole_scope_hierarchy() -> None:
    module = importlib.import_module("renpy_story_mapper.narrative_map.semantic_hierarchy")
    assert callable(module.validate_whole_scope_hierarchy)


def test_track_a_derives_ids_and_compiles_to_existing_adjacent_decisions() -> None:
    module = importlib.import_module("renpy_story_mapper.narrative_map.semantic_hierarchy")
    assert callable(module.derive_stable_hierarchy_ids)
    assert callable(module.compile_hierarchy_to_gap_decisions)


def test_track_b_defines_stage_h_and_stage_e_provider_job_kinds() -> None:
    assert ProviderJobKind.WHOLE_SCOPE_HIERARCHY.value == "whole_scope_hierarchy"
    assert ProviderJobKind.WHOLE_SCOPE_EDITORIAL.value == "whole_scope_editorial"


def test_track_b_exposes_separate_prepare_and_start_entry_points() -> None:
    for method_name in (
        "prepare_whole_scope_hierarchy",
        "start_whole_scope_hierarchy",
        "prepare_whole_scope_editorial",
        "start_whole_scope_editorial",
    ):
        assert callable(getattr(NarrativeMapService, method_name, None)), method_name


def test_track_b_accounts_for_logical_jobs_separately_from_transport_submissions() -> None:
    module = importlib.import_module("renpy_story_mapper.narrative_map.semantic_lifecycle")
    assert callable(getattr(module, "WholeScopeSemanticAccounting", None))


def test_track_c_builds_the_compact_whole_scope_projection() -> None:
    module = importlib.import_module("renpy_story_mapper.narrative_map.semantic_projection")
    assert callable(getattr(module, "build_compact_whole_scope_projection", None))


def test_track_c_exposes_whole_scope_product_routes() -> None:
    contracts = importlib.import_module("renpy_story_mapper.web.contracts")
    routes = getattr(contracts, "M15_WHOLE_SCOPE_SEMANTIC_ROUTES", None)
    assert routes == {
        "prepare_hierarchy": "/api/v1/m15/semantic/prepare_hierarchy",
        "start_hierarchy": "/api/v1/m15/semantic/start_hierarchy",
        "prepare_editorial": "/api/v1/m15/semantic/prepare_editorial",
        "start_editorial": "/api/v1/m15/semantic/start_editorial",
        "status": "/api/v1/m15/semantic/status",
        "cancel": "/api/v1/m15/semantic/cancel",
        "resume": "/api/v1/m15/semantic/resume",
        "retry": "/api/v1/m15/semantic/retry",
    }

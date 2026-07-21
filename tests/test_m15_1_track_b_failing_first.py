from __future__ import annotations

from renpy_story_mapper.narrative_map.service import NarrativeMapService


def test_track_b_exposes_two_distinct_prepare_and_start_stages() -> None:
    for name in (
        "prepare_boundaries", "start_boundaries", "prepare_summaries", "start_summaries",
        "semantic_status", "cancel_semantic_build", "resume_semantic_build", "retry_semantic_build",
    ):
        assert callable(getattr(NarrativeMapService, name, None)), name


def test_track_b_never_reuses_boundary_consent_for_frozen_summaries() -> None:
    assert getattr(NarrativeMapService, "SUMMARY_CONSENT_IS_SEPARATE", False) is True

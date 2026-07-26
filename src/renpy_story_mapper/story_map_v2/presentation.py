"""Deterministic normal-form Story Map V2 story-page projection."""

from __future__ import annotations

from collections.abc import Mapping

from renpy_story_mapper.story_map_v2.contracts import (
    ArmLineageStep,
    ChoiceMechanic,
    CoreBranchOutcome,
    CoreEvent,
    StoryMapCore,
)
from renpy_story_mapper.story_map_v2.phase03_contracts import (
    STORY_PAGE_SCHEMA,
    NavigationBinding,
    SourceBinding,
    StoryArmReadModel,
    StoryChoiceReadModel,
    StoryEventReadModel,
    StoryMapReadModel,
    StorySectionReadModel,
    SynthesisExecutionResult,
    SynthesisStatus,
    ValidatedSynthesis,
)
from renpy_story_mapper.story_map_v2.selection_ids import PublicSelectionIds, project_selection_ids


def unavailable_story_map() -> StoryMapReadModel:
    return StoryMapReadModel(
        STORY_PAGE_SCHEMA,
        "unavailable",
        "Story Map V2 is unavailable for the current project.",
        "Story Map",
        "",
        (),
        (),
    )


def _all_events(core: StoryMapCore) -> tuple[CoreEvent, ...]:
    events = tuple(event for chunk in core.chunks for event in chunk.events)
    ids = tuple(event.anchor.id for event in events)
    if not events or len(ids) != len(set(ids)):
        raise ValueError("Story Map V2 events must be non-empty and uniquely anchored")
    return events


def _all_choices(core: StoryMapCore) -> tuple[ChoiceMechanic, ...]:
    choices = tuple(choice for chunk in core.chunks for choice in chunk.choices)
    if len({choice.key for choice in choices}) != len(choices):
        raise ValueError("Story Map V2 choices must be uniquely keyed")
    return choices


def _all_outcomes(core: StoryMapCore) -> dict[tuple[str, int], CoreBranchOutcome]:
    outcomes = tuple(outcome for chunk in core.chunks for outcome in chunk.branch_outcomes)
    keyed = {(outcome.choice_key, outcome.arm_order): outcome for outcome in outcomes}
    if len(keyed) != len(outcomes):
        raise ValueError("Story Map V2 branch outcomes must be unique per choice arm")
    return keyed


def _event_binding(event: CoreEvent, selection_ids: PublicSelectionIds) -> NavigationBinding:
    target = event.anchor.destination_id or event.anchor.canonical_node_id
    selection_id = selection_ids.public_id("event", event.anchor.id)
    return NavigationBinding(
        selection_id,
        "canonical_node",
        target,
        "story_map_v2_event",
        selection_id,
        SourceBinding(event.relative_path, event.start_line, event.end_line),
    )


def _choice_tree(
    choice: ChoiceMechanic,
    *,
    children: Mapping[tuple[ArmLineageStep, ...], tuple[ChoiceMechanic, ...]],
    effective_lineages: Mapping[str, tuple[ArmLineageStep, ...]],
    outcomes: Mapping[tuple[str, int], CoreBranchOutcome],
    selection_ids: PublicSelectionIds,
    ancestry: tuple[str, ...] = (),
) -> StoryChoiceReadModel:
    if choice.key in ancestry:
        raise ValueError("Story Map V2 choice parent lineage contains a cycle")
    arms: list[StoryArmReadModel] = []
    for arm in choice.arms:
        outcome = outcomes.get((choice.key, arm.order))
        if outcome is None:
            raise ValueError("every visible choice arm requires one accepted branch outcome")
        expected_lineage = (
            *effective_lineages[choice.key],
            ArmLineageStep(choice.key, arm.order),
        )
        nested = tuple(
            _choice_tree(
                item,
                children=children,
                effective_lineages=effective_lineages,
                outcomes=outcomes,
                selection_ids=selection_ids,
                ancestry=(*ancestry, choice.key),
            )
            for item in children.get(expected_lineage, ())
        )
        target = (
            arm.destination_id or outcome.anchor.destination_id or outcome.anchor.canonical_node_id
        )
        source = SourceBinding(choice.relative_path, arm.start_line, arm.end_line)
        selection_id = selection_ids.public_id("arm", outcome.anchor.id)
        arms.append(
            StoryArmReadModel(
                selection_id,
                arm.caption,
                outcome.summary,
                arm.condition,
                arm.effects,
                arm.destination_id,
                arm.rejoin_node_id,
                arm.rejoin_line,
                outcome.reachability,
                (*arm.unresolved_warnings, *outcome.warnings),
                NavigationBinding(
                    selection_id,
                    "canonical_node",
                    target,
                    "story_map_v2_arm",
                    selection_id,
                    source,
                ),
                nested,
            )
        )
    return StoryChoiceReadModel(
        choice.key,
        SourceBinding(choice.relative_path, choice.line, choice.line),
        tuple(arms),
    )


def _project_events(
    core: StoryMapCore,
    selection_ids: PublicSelectionIds,
) -> dict[str, StoryEventReadModel]:
    events = _all_events(core)
    choices = _all_choices(core)
    choice_by_key = {choice.key: choice for choice in choices}
    accepted_choice_keys = set(choice_by_key)
    effective_lineages = {
        choice.key: tuple(
            step for step in choice.parent_lineage if step.choice_key in accepted_choice_keys
        )
        for choice in choices
    }
    children_lists: dict[tuple[ArmLineageStep, ...], list[ChoiceMechanic]] = {}
    for choice in choices:
        effective_lineage = effective_lineages[choice.key]
        if effective_lineage:
            immediate = effective_lineage[-1]
            parent = choice_by_key.get(immediate.choice_key)
            if parent is None or effective_lineages[parent.key] != effective_lineage[:-1]:
                raise ValueError(
                    "nested choice parent lineage is not represented by accepted mechanics"
                )
            if immediate.arm_order > len(parent.arms):
                raise ValueError("nested choice parent arm is unavailable")
            children_lists.setdefault(effective_lineage, []).append(choice)
    children = {key: tuple(value) for key, value in children_lists.items()}
    outcomes = _all_outcomes(core)
    roots = tuple(choice for choice in choices if not effective_lineages[choice.key])
    owners: dict[str, list[ChoiceMechanic]] = {event.anchor.id: [] for event in events}
    for choice in roots:
        candidates = [
            event
            for event in events
            if event.relative_path == choice.relative_path
            and event.start_line <= choice.line <= event.end_line
        ]
        if not candidates:
            candidates = [
                event
                for event in events
                if event.relative_path == choice.relative_path and event.start_line <= choice.line
            ]
        if not candidates:
            raise ValueError("a top-level choice has no chronological event location")
        owner = max(candidates, key=lambda event: event.start_line)
        owners[owner.anchor.id].append(choice)

    result: dict[str, StoryEventReadModel] = {}
    for event in events:
        projected_choices = tuple(
            _choice_tree(
                choice,
                children=children,
                effective_lineages=effective_lineages,
                outcomes=outcomes,
                selection_ids=selection_ids,
            )
            for choice in owners[event.anchor.id]
        )
        result[event.anchor.id] = StoryEventReadModel(
            selection_ids.public_id("event", event.anchor.id),
            event.title,
            event.summary,
            event.characters,
            event.reachability,
            event.warnings,
            _event_binding(event, selection_ids),
            projected_choices,
        )
    return result


def _validated_synthesis(
    synthesis: SynthesisExecutionResult | ValidatedSynthesis | None,
) -> tuple[ValidatedSynthesis | None, str | None]:
    if isinstance(synthesis, ValidatedSynthesis):
        return synthesis, None
    if synthesis is None:
        return None, "Whole-story synthesis is unavailable; showing the deterministic story."
    if synthesis.status is SynthesisStatus.SUCCEEDED and synthesis.synthesis is not None:
        return synthesis.synthesis, None
    return None, synthesis.sanitized_reason or "Whole-story synthesis is unavailable."


def project_story_map(
    core: StoryMapCore,
    synthesis: SynthesisExecutionResult | ValidatedSynthesis | None,
) -> StoryMapReadModel:
    """Project events once in source order and overlay exact Python-owned mechanics."""

    selection_ids = project_selection_ids(core)
    event_models = _project_events(core, selection_ids)
    ordered_ids = tuple(event.anchor.id for event in _all_events(core))
    ordered_public_ids = tuple(
        selection_ids.public_id("event", event.anchor.id) for event in _all_events(core)
    )
    accepted_synthesis, reason = _validated_synthesis(synthesis)
    sections: list[StorySectionReadModel] = []
    if accepted_synthesis is not None:
        flattened = tuple(
            anchor
            for section in accepted_synthesis.ordered_sections
            for anchor in section.event_anchor_ids
        )
        if flattened != ordered_ids:
            raise ValueError("validated synthesis does not cover accepted events exactly once")
        for index, section in enumerate(accepted_synthesis.ordered_sections, start=1):
            sections.append(
                StorySectionReadModel(
                    f"section-{index}",
                    section.section_title,
                    section.section_summary,
                    tuple(event_models[anchor] for anchor in section.event_anchor_ids),
                )
            )
        return StoryMapReadModel(
            STORY_PAGE_SCHEMA,
            "synthesized",
            None,
            accepted_synthesis.story_title,
            accepted_synthesis.story_overview,
            accepted_synthesis.analysis_notes,
            tuple(sections),
        )

    for chunk in core.chunks:
        ids = tuple(event.anchor.id for event in chunk.events)
        if not ids:
            continue
        sections.append(
            StorySectionReadModel(
                f"section-{len(sections) + 1}",
                chunk.scope_title or chunk.events[0].title,
                chunk.scope_overview or chunk.events[0].summary,
                tuple(event_models[anchor] for anchor in ids),
            )
        )
    flattened = tuple(event.selection_id for section in sections for event in section.events)
    if flattened != ordered_public_ids:
        raise ValueError("deterministic fallback does not cover accepted events exactly once")
    return StoryMapReadModel(
        STORY_PAGE_SCHEMA,
        "fallback",
        reason,
        core.title or "Story Map",
        core.overview or "",
        (),
        tuple(sections),
    )

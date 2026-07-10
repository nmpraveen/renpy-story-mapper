from __future__ import annotations

import json

from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.state import (
    FactStatus,
    StateAnalysis,
    StateCategory,
    extract_state,
)


def analyze(lines: list[str]) -> StateAnalysis:
    return extract_state([parse_script("state.rpy", lines)])


def test_extracts_proven_literal_effects_and_state_registry() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    $ love += 1\n",
            "    lust -= 2\n",
            "    dating = True\n",
            "    wits = 3\n",
            "    money -= 10\n",
            '    job = "Company Z"\n',
            "    chapter = 3\n",
        ]
    )

    actual = [(item.variable, item.operation, item.value, item.status) for item in analysis.effects]
    assert actual == [
        ("love", "increment", 1, FactStatus.PROVEN),
        ("lust", "decrement", 2, FactStatus.PROVEN),
        ("dating", "assignment", True, FactStatus.PROVEN),
        ("wits", "assignment", 3, FactStatus.PROVEN),
        ("money", "decrement", 10, FactStatus.PROVEN),
        ("job", "assignment", "Company Z", FactStatus.PROVEN),
        ("chapter", "assignment", 3, FactStatus.PROVEN),
    ]
    assert {item.original_name: item.category for item in analysis.variables} == {
        "chapter": StateCategory.PROGRESSION,
        "dating": StateCategory.RELATIONSHIP,
        "job": StateCategory.JOB,
        "love": StateCategory.RELATIONSHIP,
        "lust": StateCategory.RELATIONSHIP,
        "money": StateCategory.RESOURCE,
        "wits": StateCategory.SKILL,
    }
    love = next(item for item in analysis.variables if item.original_name == "love")
    assert love.display_name == "Love"
    assert love.evidence[0].source_file == "state.rpy"
    assert love.evidence[0].physical_line == 2


def test_extracts_branch_choice_and_chained_requirements_verbatim() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    if chapter == 0 and 0 < wits <= 5:\n",
            '        "Ready."\n',
            "    menu:\n",
            '        "Charm" if charisma > 0 and not cheating:\n',
            "            return\n",
        ]
    )

    assert [item.original_expression for item in analysis.requirements] == [
        "chapter == 0 and 0 < wits <= 5",
        "charisma > 0 and not cheating",
    ]
    assert [item.variables for item in analysis.requirements] == [
        ("chapter", "wits"),
        ("charisma", "cheating"),
    ]
    assert all(item.status is FactStatus.PROVEN for item in analysis.requirements)
    assert [item.evidence.physical_line for item in analysis.requirements] == [2, 5]


def test_literal_state_call_is_possible_and_unknown_call_is_unresolved() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    call xp_up('lust')\n",
            "    mystery('love')\n",
            "    renpy.pause(1)\n",
        ]
    )

    xp, mystery = analysis.effects
    assert (xp.call_target, xp.variable, xp.value, xp.status) == (
        "xp_up",
        "lust",
        ("lust",),
        FactStatus.POSSIBLE,
    )
    assert xp.reason == "creator_call_not_executed"
    assert (mystery.call_target, mystery.status, mystery.reason) == (
        "mystery",
        FactStatus.UNRESOLVED,
        "unknown_call_semantics",
    )


def test_computed_and_dynamic_behavior_is_never_proven() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    if score > threshold + 1:\n",
            "        love = calculate_love()\n",
            "    $ globals()[state_name] = 1\n",
            "    $ money += variable_delta\n",
            "    update_stat(stat_name, 1)\n",
        ]
    )

    assert analysis.requirements[0].status is FactStatus.UNRESOLVED
    assert analysis.requirements[0].reason == "computed_comparison_operand"
    assert all(effect.status is FactStatus.UNRESOLVED for effect in analysis.effects)
    assert [effect.reason for effect in analysis.effects] == [
        "computed_assignment_value",
        "dynamic_or_unsupported_assignment_target",
        "computed_or_non_numeric_delta",
        "computed_call_argument",
    ]


def test_computed_subscript_and_award_call_are_explicitly_unresolved() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    $ points[hero_name] += amount\n",
            "    call award_points(stat_name, calculate_amount())\n",
        ]
    )

    assert [effect.status for effect in analysis.effects] == [
        FactStatus.UNRESOLVED,
        FactStatus.UNRESOLVED,
    ]
    assert [effect.reason for effect in analysis.effects] == [
        "dynamic_or_unsupported_assignment_target",
        "computed_call_argument",
    ]


def test_opaque_blocks_are_explicitly_unresolved() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    python:\n",
            "        love += 1\n",
            "    while route_active:\n",
            "        money -= 1\n",
        ]
    )

    assert [effect.operation for effect in analysis.effects] == [
        "opaque_block",
        "opaque_block",
    ]
    assert all(effect.status is FactStatus.UNRESOLVED for effect in analysis.effects)
    assert [effect.reason for effect in analysis.effects] == [
        "embedded_python_not_executed",
        "unsupported_control_flow",
    ]


def test_signed_deltas_are_normalized_to_direction_and_magnitude() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    $ love += -1\n",
            "    $ money -= -2\n",
        ]
    )

    assert [(effect.operation, effect.value) for effect in analysis.effects] == [
        ("decrement", 1),
        ("increment", 2),
    ]


def test_callable_names_are_not_registered_as_state_variables() -> None:
    analysis = analyze(
        [
            "label start:\n",
            "    if getattr(store, gate_name):\n",
            '        "Dynamic."\n',
        ]
    )

    assert analysis.requirements[0].variables == ("gate_name", "store")
    assert {item.original_name for item in analysis.variables} == {"gate_name", "store"}


def test_output_is_json_ready_and_deterministic_across_module_order() -> None:
    first = parse_script("b.rpy", ["label b:\n", "    money = 5\n"])
    second = parse_script("a.rpy", ["label a:\n", "    love += 1\n"])

    left = extract_state([first, second]).to_dict()
    right = extract_state([second, first]).to_dict()

    assert left == right
    json.dumps(left, sort_keys=True)
    assert left["schema_version"] == 1
    effects = left["effects"]
    assert isinstance(effects, list)
    assert [effect["variable"] for effect in effects if isinstance(effect, dict)] == [
        "love",
        "money",
    ]

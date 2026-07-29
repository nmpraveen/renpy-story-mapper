from __future__ import annotations

from collections import defaultdict, deque

from renpy_story_mapper.project_analysis import create_folder_project
from renpy_story_mapper.story_map_v2.progressive_story import persist_progressive_story_page

TERRANCE_SOURCE = """
label _6_3_WG_clean:
    "Terrance reappears after work."
    if ter < 3:
        if loi >= 2:
            jump _6_7_lw_clean
        jump _6_7_end_clean
    if terrance_answer_4_1:
        "Wanda ends their sessions."
        jump _6_7_lw_clean
    else:
        menu:
            "Push him off":
                "Wanda pushes him away."
            "Stay still":
                $ ter += 1
                "Wanda remains still."
        "Both reactions rejoin."

label _6_3_WG_clean_1:
    menu:
        "Let him go":
            $ let_ter_go_6_4 = True
            jump _6_7_lw_clean
        "Call him back":
            jump _6_3_WG_cleanb

label _6_3_WG_cleanb:
    menu:
        "Can't you admit that you overreacted?":
            $ ter_overreacted_6_4 = True
            jump _6_7_lw_clean
        "Why don't you believe me?":
            menu:
                "Give him some time":
                    $ give_ter_time_6_4 = True
                    jump _6_7_lw_clean
                "Keep pushing":
                    jump _6_3_WG_clean_1c

label _6_3_WG_clean_1c:
    menu:
        "No":
            $ ter_no_6_4 = True
            jump _6_7_lw_clean
        "Think about it":
            jump _6_3_WG_clean_1d

label _6_3_WG_clean_1d:
    "They have lunch at a diner."
    menu:
        "Very smooth":
            $ ter += 1
            $ ter_smooth_6_4 = True
        "Is he trying to impress me?":
            "Wanda questions his intentions."
    "The reactions rejoin before his proposal."
    menu:
        "Do nothing":
            $ ter_do_nothing_6_4 = True
            $ ter += 2
            jump _6_7_WG_clean
        "Say No":
            "Terrance keeps pressing."
            menu:
                "Keep going":
                    jump _6_7_lw_clean
                "Take things to the next level":
                    $ ter_next_level_6_4 = True
                    jump _6_7_lw_clean
"""


CONTINUATION_SOURCE = """
label _6_7_WG_clean:
    "They enter the storage room."
    "Wanda eventually leaves Terrance behind."

label _6_7_lw_clean:
    "Wanda takes Lois out after work."

label _6_7_end_clean:
    "The unavailable route is skipped."
"""


HISTORY_SOURCE = """
label start:
    menu:
        "She ignores him":
            $ ter += 1
        "She addresses his behavior":
            $ ter += 1
    jump history_answer

label history_answer:
    menu:
        "Answer":
            $ terrance_answer_4_1 = True
        "Stay quiet":
            pass
    jump history_lois

label history_lois:
    menu:
        "Yes":
            $ loi += 2
        "No":
            pass
    return
"""


def _outgoing(walk: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for edge in walk["edges"]:  # type: ignore[index]
        result[edge["source"]].append(edge)  # type: ignore[index]
    return result


def _reachable(walk: dict[str, object], start: str) -> set[str]:
    outgoing = _outgoing(walk)
    pending = deque([start])
    seen: set[str] = set()
    while pending:
        node_id = pending.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        pending.extend(str(edge["target"]) for edge in outgoing.get(node_id, ()))
    return seen


def test_progressive_terrance_walk_preserves_real_nesting_and_rejoin(tmp_path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "history.rpy").write_text(HISTORY_SOURCE, encoding="utf-8")
    (game / "terrance.rpy").write_text(TERRANCE_SOURCE, encoding="utf-8")
    (game / "continuation.rpy").write_text(CONTINUATION_SOURCE, encoding="utf-8")

    project = create_folder_project(tmp_path / "proof.rsmproj", game)
    try:
        page = persist_progressive_story_page(
            project,
            entry_label="_6_3_WG_clean",
            stop_labels={"_6_7_lw_clean"},
            terminal_labels={"_6_7_end_clean": "Terrance route unavailable"},
            source_paths={"terrance.rpy", "continuation.rpy"},
            label_titles={
                "_6_3_WG_clean": "Terrance returns after work",
                "_6_7_WG_clean": "Diner storage room",
                "_6_7_lw_clean": "Lois continuation",
            },
            backlink_variables={"ter", "loi", "terrance_answer_4_1"},
            state_variables={
                "ter",
                "let_ter_go_6_4",
                "ter_overreacted_6_4",
                "give_ter_time_6_4",
                "ter_no_6_4",
                "ter_smooth_6_4",
                "ter_do_nothing_6_4",
                "ter_next_level_6_4",
            },
            page_title="Terrance returns and pushes for a pretend date",
            page_overview=(
                "Terrance returns after work. Wanda's earlier choices determine whether "
                "the encounter ends, continues through lunch, or detours through storage "
                "before every surviving route rejoins the Lois continuation."
            ),
            choice_titles={
                "Push him off": "story:Wanda reacts to Terrance's approach",
                "Let him go": "story:Wanda decides whether to call him back",
                "Can't you admit that you overreacted?": "story:Wanda challenges his distrust",
                "Give him some time": "story:Wanda decides whether to keep pushing",
                "No": "story:Wanda answers the lunch invitation",
                "Very smooth": "story:Wanda reads Terrance's diner behavior",
                "Do nothing": "story:Wanda responds when he leads her to storage",
                "Keep going": "story:Wanda decides how far the encounter continues",
                "ter < 3": "story:Earlier relationship state decides whether this route opens",
                "loi >= 2": "story:Lois progress decides whether the story can continue",
            },
        )

        assert page["schema"] == "story-map-v2-page-v1"
        assert page["status"] == "synthesized"
        assert str(page["analysis_notes"][0]).startswith(  # type: ignore[index]
            "Phase 05 progressive story walk"
        )
        assert page["title"] == "Terrance returns and pushes for a pretend date"
        walk = project.payload("story_map_v2", "phase05_progressive_walk")
        assert isinstance(walk, dict)
        assert walk["counts"]["menus"] == 8  # type: ignore[index]
        assert walk["counts"]["arms"] == 16  # type: ignore[index]

        nodes = {node["id"]: node for node in walk["nodes"]}  # type: ignore[index]
        outgoing = _outgoing(walk)
        choices = [node for node in nodes.values() if node["type"] == "choice"]
        captions_by_choice = {
            node["id"]: {
                edge["caption"]
                for edge in outgoing[node["id"]]
                if edge["kind"] == "choice"
            }
            for node in choices
        }
        proposal = next(
            node_id
            for node_id, captions in captions_by_choice.items()
            if captions == {"Do nothing", "Say No"}
        )
        nested = next(
            node_id
            for node_id, captions in captions_by_choice.items()
            if captions == {"Keep going", "Take things to the next level"}
        )
        proposal_edges = {edge["caption"]: edge for edge in outgoing[proposal]}
        do_nothing_reachable = _reachable(walk, str(proposal_edges["Do nothing"]["target"]))
        say_no_reachable = _reachable(walk, str(proposal_edges["Say No"]["target"]))

        label_nodes = {
            node.get("label"): node["id"] for node in nodes.values() if node.get("label")
        }
        assert nested in say_no_reachable
        assert nested not in do_nothing_reachable
        assert label_nodes["_6_7_WG_clean"] in do_nothing_reachable
        assert label_nodes["_6_7_WG_clean"] not in say_no_reachable
        assert label_nodes["_6_7_lw_clean"] in do_nothing_reachable
        assert label_nodes["_6_7_lw_clean"] in say_no_reachable
        assert nodes[label_nodes["_6_7_lw_clean"]]["type"] == "rejoin"
        assert nodes[label_nodes["_6_7_end_clean"]]["type"] == "terminal"

        backlink_variables = {item["variable"] for item in walk["state_backlinks"]}  # type: ignore[index]
        assert backlink_variables == {"ter", "loi", "terrance_answer_4_1"}
        assert "Gene" not in str(walk)
        assert "Faye" not in str(walk)
        choices = page["sections"][0]["events"][0]["choices"]  # type: ignore[index]
        pending = list(choices)
        projected_choices = []
        while pending:
            choice = pending.pop()
            projected_choices.append(choice)
            for arm in choice["arms"]:
                pending.extend(arm["nested_choices"])
        assert len(projected_choices) == 10  # eight menus plus two state gates
        assert sum(len(choice["arms"]) for choice in projected_choices) == 21
        assert all(choice["key"].startswith("story:") for choice in projected_choices)
        assert len(choices) == 1  # the entry state gate owns the visible route tree
        event = page["sections"][0]["events"][0]  # type: ignore[index]
        assert event["outline_summary"] == "Terrance reappears after work."
        assert "Terrance reappears after work." in event["detail_summary"]
        projected_arms = [arm for choice in projected_choices for arm in choice["arms"]]
        assert all(arm["outline_summary"] for arm in projected_arms)
        assert all(arm["detail_summary"] for arm in projected_arms)
        assert "The route continues to the next story beat." not in str(page)
        lunch = next(
            choice
            for choice in projected_choices
            if choice["key"] == "story:Wanda answers the lunch invitation"
        )
        think_about_it = next(arm for arm in lunch["arms"] if arm["caption"] == "Think about it")
        nested_titles = {choice["key"] for choice in think_about_it["nested_choices"]}
        assert nested_titles == {
            "story:Wanda reads Terrance's diner behavior",
            "story:Wanda responds when he leads her to storage",
        }
        proposal_choice = next(
            choice
            for choice in projected_choices
            if choice["key"] == "story:Wanda responds when he leads her to storage"
        )
        do_nothing = next(
            arm for arm in proposal_choice["arms"] if arm["caption"] == "Do nothing"
        )
        assert do_nothing["outline_summary"] == "They enter the storage room."
        assert do_nothing["detail_summary"].splitlines() == [
            "Diner storage room",
            "They enter the storage room.",
            "Wanda eventually leaves Terrance behind.",
            "Lois continuation",
        ]
        assert do_nothing["rejoin_node_id"] == "story:Lois continuation"
        assert project.payload("story_map_v2", "phase05_progressive") == page
    finally:
        project.close()

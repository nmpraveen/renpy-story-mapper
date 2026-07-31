# ruff: noqa: E501
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"app.js must define {name}"
    parameters = source.find("(", start)
    parameter_depth = 0
    closing = -1
    for index in range(parameters, len(source)):
        if source[index] == "(":
            parameter_depth += 1
        elif source[index] == ")":
            parameter_depth -= 1
            if parameter_depth == 0:
                closing = index
                break
    assert closing >= 0, f"could not isolate {name} parameters"
    opening = source.find("{", closing)
    assert opening >= 0, f"{name} must have a function body"
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"could not isolate {name}")


def _media(css: str, width: int, next_width: int | None) -> str:
    start_marker = f"@media (max-width: {width}px)"
    start = css.find(start_marker)
    assert start >= 0, f"styles.css must keep the {width}px desktop breakpoint"
    if next_width is None:
        return css[start:]
    end_marker = f"@media (max-width: {next_width}px)"
    end = css.find(end_marker, start + len(start_marker))
    assert end >= 0, f"styles.css must keep the {next_width}px desktop breakpoint"
    return css[start:end]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_story_route_context_executes_root_nested_palette_and_outcome_contract() -> None:
    app = _text("app.js")
    functions = "\n".join(
        _function(app, name)
        for name in (
            "storySemanticKind",
            "humanStoryTarget",
            "storyOutcomeSentence",
            "storyRouteRootCode",
            "storyRouteTarget",
            "createStoryRouteContext",
        )
    )
    script = f"""
      const STORY_OUTCOME_KINDS = new Map([
        ["continues", "continuation"], ["rejoins", "rejoin"],
        ["ends", "ending"], ["unresolved", "unresolved"],
      ]);
      const state = {{ storyRoutes: new Map() }};
      function storyItemTitle(item) {{ return item.title || item.caption || item.selection_id; }}
      {functions}

      function arm(prefix, index, outcomeKind = "continues") {{
        return {{
          selection_id: `${{prefix}}:${{index + 1}}`,
          title: `${{prefix}} ${{index + 1}}`,
          outcome_kind: outcomeKind,
          state_provenance: [],
        }};
      }}
      const counts = [2, 3, 5, 7, 9].map((count) => {{
        const contexts = Array.from({{ length: count }}, (_, index) =>
          createStoryRouteContext(arm(`fork-${{count}}`, index), index, null, `Fork ${{count}}`, "decision")
        );
        return {{
          count,
          codes: contexts.map((context) => context.code),
          slots: contexts.map((context) => context.paletteSlot),
          selectionIds: contexts.map((context) => context.selectionId),
        }};
      }});
      const parent = createStoryRouteContext(arm("parent", 1), 1, null, "Parent fork", "decision");
      const nested = [0, 1].map((index) =>
        createStoryRouteContext(arm("nested", index), index, parent, "Nested fork", "condition")
      );
      const outcomes = [
        storyRouteTarget({{ outcome_kind: "rejoins", rejoin_node_id: "story:Shared harbor", rejoin_target_selection_id: "event:shared" }}),
        storyRouteTarget({{ outcome_kind: "ends" }}),
        storyRouteTarget({{ outcome_kind: "unresolved" }}),
        storyRouteTarget({{ outcome_kind: "continues" }}),
        storyRouteTarget({{ outcome_kind: "continues", destination_id: "story:North road", destination_target_selection_id: "event:north" }}),
        storyRouteTarget({{ entry_kind: "loop", title: "Earlier route", target_selection_id: "event:earlier" }}),
      ];
      process.stdout.write(JSON.stringify({{
        counts,
        rollover: [0, 25, 26, 27, 51, 52].map(storyRouteRootCode),
        parent: {{ code: parent.code, selectionId: parent.selectionId }},
        nested: nested.map((context) => ({{
          code: context.code,
          slot: context.paletteSlot,
          selectionId: context.selectionId,
          parentCode: context.parentCode,
          parentSelectionId: context.parentSelectionId,
          depth: context.depth,
        }})),
        routeKeys: [...state.storyRoutes.keys()],
        outcomes,
      }}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)

    expected_codes = {
        2: ["A", "B"],
        3: ["A", "B", "C"],
        5: ["A", "B", "C", "D", "E"],
        7: ["A", "B", "C", "D", "E", "F", "G"],
        9: ["A", "B", "C", "D", "E", "F", "G", "H", "I"],
    }
    for case in result["counts"]:
        count = case["count"]
        assert case["codes"] == expected_codes[count]
        assert case["slots"] == [((index % 8) + 1) for index in range(count)]
        assert len(set(case["codes"])) == count
        assert case["selectionIds"] == [f"fork-{count}:{index}" for index in range(1, count + 1)]
    assert result["rollover"] == ["A", "Z", "AA", "AB", "AZ", "BA"]
    assert result["parent"] == {"code": "B", "selectionId": "parent:2"}
    assert result["nested"] == [
        {"code": "B.1", "slot": 3, "selectionId": "nested:1", "parentCode": "B", "parentSelectionId": "parent:2", "depth": 1},
        {"code": "B.2", "slot": 4, "selectionId": "nested:2", "parentCode": "B", "parentSelectionId": "parent:2", "depth": 1},
    ]
    assert {"parent:2", "nested:1", "nested:2"}.issubset(result["routeKeys"])
    assert result["outcomes"][:5] == [
        {"kind": "rejoin", "text": "Rejoins at Shared harbor", "name": "Shared harbor", "selectionId": "event:shared"},
        {"kind": "ending", "text": "Ends here", "name": None, "selectionId": None},
        {"kind": "unresolved", "text": "Destination unresolved", "name": None, "selectionId": None},
        {"kind": "continuation", "text": "Continues on this route", "name": None, "selectionId": None},
        {"kind": "destination", "text": "Goes to North road", "name": "North road", "selectionId": "event:north"},
    ]
    loop = result["outcomes"][5]
    assert loop and loop["kind"] == "loop" and loop["selectionId"] == "event:earlier"
    assert "return" in loop["text"].lower() or "loop" in loop["text"].lower()


def test_story_river_renderer_propagates_routes_and_preserves_fork_contract() -> None:
    app = _text("app.js")
    threshold_match = re.search(r"const STORY_STACK_THRESHOLD = (\d+);", app)
    assert threshold_match
    threshold = int(threshold_match.group(1))
    assert threshold == 4
    assert {count: ("stack" if count > threshold else "fan") for count in (2, 3, 5, 7, 9)} == {
        2: "fan",
        3: "fan",
        5: "stack",
        7: "stack",
        9: "stack",
    }
    assert "const STORY_OPEN_FORK_LIMIT = 2;" in app

    apply_context = _function(app, "applyStoryRouteContext")
    choice = _function(app, "renderStoryChoice")
    route_flow = _function(app, "renderStoryRouteFlow")
    event = _function(app, "renderStoryEvent")
    continuations = _function(app, "appendStoryContinuations")
    targets = _function(app, "appendStoryTargets")
    detail = _function(app, "appendProgressiveStoryDetail")

    assert "node.dataset.storyRouteSelectionId = context.selectionId" in apply_context
    assert "node.dataset.storyRouteCode = context.code" in apply_context
    assert "node.dataset.storyRouteSlot = String(context.paletteSlot)" in apply_context
    assert 'node.dataset.storyStream = "main"' in apply_context
    assert "const stacked = choice.arms.length > STORY_STACK_THRESHOLD" in choice
    assert 'article.dataset.forkLayout = stacked ? "stack" : "fan"' in choice
    assert '`story-arms${stacked ? " is-stacked" : ""}`' in choice
    assert "const routeContext = createStoryRouteContext(arm, armIndex, parentRouteContext" in choice
    assert "applyStoryRouteContext(armArticle, routeContext)" in choice
    assert "armArticle.dataset.outcomeKind = outcomeKind" in choice
    assert 'element("span", "story-route-code", `Route ${routeContext.code}`)' in choice
    assert "renderStoryChoice(child, true" in choice and "routeContext, storyItemTitle(arm)" in choice
    assert "renderStoryRouteFlow(arm.route_flow, ordinalState, routeContext)" in choice
    assert "route.open = descendantCount <= STORY_OPEN_FORK_LIMIT" in choice
    assert "appendStoryContinuations(route, armContinuations, true, merges, parentRouteContext)" in choice
    assert "appendStoryContinuations(article, plan.get(JSON.stringify(choicePath)), false, merges, parentRouteContext)" in choice

    assert "applyStoryRouteContext(host, routeContext)" in route_flow
    assert "renderStoryEvent(item.event, ordinalState, routeContext)" in route_flow
    assert "reference.dataset.entryKind = item.entry_kind" in route_flow
    assert 'item.entry_kind === "loop"' in route_flow and '"Returns to"' in route_flow
    assert "applyStoryRouteContext(article, routeContext" in event
    assert "renderStoryChoice(choice, false" in event and "routeContext, storyItemTitle(event)" in event
    assert "applyStoryRouteContext(row, returnRouteContext" in continuations
    assert 'row.dataset.outcomeKind = "rejoin"' in continuations
    assert '"The story comes back together"' in continuations
    assert '"This route returns to the story"' in continuations
    assert '"The paths meet again"' not in continuations
    assert '"This path rejoins the story"' not in continuations
    assert "suppressRejoin" in targets and 'outcome.kind === "rejoin"' in targets
    assert "appendStoryTargets(armArticle, arm, { suppressRejoin:" in choice
    assert "suppressOutcome" in detail and "storyTextWithoutOutcome(storyDetailSummary(item), item)" in detail
    assert "suppressOutcome: Boolean(arm.rejoin_binding)" in choice


def test_story_route_panel_markup_links_and_all_sync_paths_are_explicit() -> None:
    app = _text("app.js")
    html = _text("index.html")
    panel_start = html.find('<aside id="storyRoutePanel"')
    assert panel_start >= 0
    panel_end = html.find("</aside>", panel_start)
    assert panel_end >= 0
    panel = html[panel_start : panel_end + len("</aside>")]
    assert 'hidden aria-labelledby="storyRouteTitle"' in panel
    for field_id in (
        "storyRouteCode",
        "storyRouteTitle",
        "storyRouteOrigin",
        "storyRouteOwner",
        "storyRouteStatus",
        "storyRouteProvenanceGroup",
        "storyRouteProvenance",
    ):
        assert f'id="{field_id}"' in panel
    for label in ("Started at", "Route type", "Status", "Earlier state"):
        assert label in panel

    provenance = _function(app, "renderStoryRoutePanelProvenance")
    update_panel = _function(app, "updateStoryRoutePanel")
    selection_control = _function(app, "storySelectionControl")
    focus_selection = _function(app, "focusProgressiveStorySelection")
    reading_position = _function(app, "updateStoryReadingPosition")
    schedule_reading = _function(app, "scheduleStoryReadingPosition")
    activate = _function(app, "activateStoryItem")
    route_flow = _function(app, "renderStoryRouteFlow")
    search = _function(app, "applyStorySearch")

    assert ".slice(0, 3)" in provenance
    assert 'element("button", "quiet-button story-route-provenance-link"' in provenance
    assert "navigateProgressiveStorySelection(fact.target_selection_id)" in provenance
    for field_id in ("storyRouteCode", "storyRouteTitle", "storyRouteOrigin", "storyRouteOwner", "storyRouteStatus"):
        assert f'$("#{field_id}")' in update_panel
    assert "context.target" in update_panel
    assert 'element("button", "quiet-button story-route-target-link"' in update_panel
    assert "navigateProgressiveStorySelection(context.target.selectionId)" in update_panel
    assert "reference.storyRouteTarget = storyRouteTarget(item)" in route_flow
    assert "syncStoryRoutePanelForNode(reference" in route_flow

    assert 'control.addEventListener("focus", () => syncStoryRoutePanelForNode(control, item, { hold: true }))' in selection_control
    assert 'control.addEventListener("click"' in selection_control and "activateStoryItem(item, control)" in selection_control
    assert "syncStoryRoutePanelForNode(control, item, { hold: true })" in activate
    assert "control.focus({ preventScroll: true })" in focus_selection
    assert "syncStoryRoutePanelForNode(control" in focus_selection
    assert "Date.now() >= state.storyRouteInteractionUntil" in reading_position
    assert "syncStoryRoutePanelForNode(readingNode)" in reading_position
    assert "setTimeout" in schedule_reading and "updateStoryReadingPosition()" in schedule_reading
    assert "firstMatch ||= node" in search
    assert "scrollStoryTo(firstMatch)" in search
    assert "syncStoryRoutePanelForNode(control" in search and "{ hold: true }" in search


def test_story_river_css_breakpoints_and_frontend_only_boundary() -> None:
    app = _text("app.js")
    css = _text("styles.css")
    html = _text("index.html")
    api = _text("api.js")
    contract = _text("contract.js")

    base_slots = {int(value) for value in re.findall(r"--story-route-(\d+)(?!-soft)\s*:", css)}
    soft_slots = {int(value) for value in re.findall(r"--story-route-(\d+)-soft\s*:", css)}
    assert base_slots == set(range(1, 9))
    assert soft_slots == set(range(1, 9))
    assert "--story-route-9" not in css
    assert "var(--story-route-color)" in css
    assert "var(--story-route-soft)" in css

    wide_start = css.index("@media (min-width: 1500px)")
    intermediate_start = css.index("@media (min-width: 1241px) and (max-width: 1499px)")
    normal_start = css.index("@media (max-width: 1240px)")
    narrow_start = css.index("@media (max-width: 900px)")
    wide = css[wide_start:intermediate_start]
    intermediate = css[intermediate_start:normal_start]
    normal = css[normal_start:narrow_start]
    assert ".story-route-panel" in wide and "position: sticky" in wide
    assert re.search(
        r"(?:story-reader-shell[^\{]*story-route-panel|is-story-river[^\{]*story-reader-shell)[^\{]*\{[^}]*grid-template-columns",
        wide,
        re.DOTALL,
    )
    assert ".story-route-panel" in intermediate and "position: sticky" in intermediate
    assert ".story-route-panel" in normal and "position: static" in normal
    assert "width: 100%" in normal

    assert "storyRouteRootCode" in app and "createStoryRouteContext" in app
    for source in (api, contract):
        assert "storyRouteRootCode" not in source
        assert "createStoryRouteContext" not in source
        assert "story_route_context" not in source
    python_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py"))
    assert "storyRouteRootCode" not in python_source
    assert "createStoryRouteContext" not in python_source
    assert "story_route_context" not in python_source
    assert "<canvas" not in html.lower()
    route_helpers = _function(app, "storyRouteRootCode") + _function(app, "createStoryRouteContext")
    assert all(marker not in route_helpers for marker in ("api.", "fetch(", "canvas", "pan(", "zoom("))

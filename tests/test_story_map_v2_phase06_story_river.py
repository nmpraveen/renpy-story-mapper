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


def _css_rules(source: str) -> list[tuple[str, str]]:
    return [
        (selector.strip(), body)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", source)
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_story_route_context_executes_root_nested_palette_and_outcome_contract() -> None:
    app = _text("app.js")
    functions = "\n".join(
        _function(app, name)
        for name in (
            "storySemanticKind",
            "humanStoryTarget",
            "storyOutcomeSentence",
            "storyOutlineSummary",
            "storyTextWithoutOutcome",
            "storySummaryWithoutOutcome",
            "storyRouteRootCode",
            "storyRouteTarget",
            "storyRouteSynopsis",
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
    assert [{key: value for key, value in context.items() if key != "slot"} for context in result["nested"]] == [
        {"code": "B.1", "selectionId": "nested:1", "parentCode": "B", "parentSelectionId": "parent:2", "depth": 1},
        {"code": "B.2", "selectionId": "nested:2", "parentCode": "B", "parentSelectionId": "parent:2", "depth": 1},
    ]
    nested_slots = [context["slot"] for context in result["nested"]]
    assert len(set(nested_slots)) == len(nested_slots)
    assert all(1 <= slot <= 8 for slot in nested_slots)
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
    river = _text("river.js")
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
    apply_context = _function(app, "applyStoryRouteContext")
    choice = _function(app, "renderStoryChoice")
    route_flow = _function(app, "renderStoryRouteFlow")
    event = _function(app, "renderStoryEvent")
    continuations = _function(app, "appendStoryContinuations")
    targets = _function(app, "appendStoryTargets")
    detail = _function(app, "appendProgressiveStoryDetail")
    painter = _function(river, "paintChoice")

    assert "node.dataset.storyRouteSelectionId = context.selectionId" in apply_context
    assert "node.dataset.storyRouteCode = context.code" in apply_context
    assert "node.dataset.storyRouteSlot = String(context.paletteSlot)" in apply_context
    assert 'node.dataset.storyStream = "main"' in apply_context
    assert "const stacked = choice.arms.length > STORY_STACK_THRESHOLD" in choice
    assert 'article.dataset.forkLayout = stacked ? "stack" : "fan"' in choice
    assert '`story-arms${stacked ? " is-stacked" : ""}`' in choice
    assert "const routeContext = createStoryRouteContext(arm, armIndex, parentRouteContext" in choice
    # Arms are reading targets, so scrolling a fork moves the route panel off the shared story.
    assert "applyStoryRouteContext(armArticle, routeContext, { reading: true })" in choice
    assert "armArticle.dataset.storyRejoinTargetSelectionId = arm.rejoin_binding.selection_id" in choice
    assert "armArticle.dataset.outcomeKind = outcomeKind" in choice
    assert 'element("span", "story-route-code", `Route ${routeContext.code}`)' in choice
    assert "renderStoryChoice(child, true" in choice and "routeContext, storyItemTitle(arm)" in choice
    assert "renderStoryRouteFlow(arm.route_flow, ordinalState, routeContext)" in choice
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
    # A shared stacked rail is valid only when every arm reaches the same target.  Multiple
    # targets must fall back to arm-specific streams so the painter preserves that distinction.
    assert "const confluenceTargetCount = new Set(" in painter
    assert "const useSharedRail = Boolean(fork.rail) && confluenceTargetCount <= 1" in painter
    assert ": paintMerge(canvas, choice, merging, confluence, width);" in painter


def test_story_workflow_chrome_restores_an_actionable_stable_reader_run() -> None:
    app = _text("app.js")
    status = _function(app, "storyWorkflowChromeForStatus")
    mode = _function(app, "storyWorkflowChromeForMode")

    assert "const actions = readerStatus ? (status.actions || {}) : status" in status
    assert '"running", "starting", "cancelling", "queued", "building"' in status
    assert "progress: actionableRun" in status
    assert "cancel," in status and "resume," in status and "retry," in status
    assert "state.storyWorkflow.response?.status" in mode
    assert "storyWorkflowChromeForStatus(state.storyReader.status, true)" in mode


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
        "storyRouteSynopsis",
        "storyRouteOrigin",
        "storyRouteOwner",
        "storyRouteStatusLabel",
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
    for field_id in (
        "storyRouteCode",
        "storyRouteTitle",
        "storyRouteSynopsis",
        "storyRouteOrigin",
        "storyRouteOwner",
        "storyRouteStatusLabel",
        "storyRouteStatus",
    ):
        assert f'$("#{field_id}")' in update_panel
    assert "storyRouteSynopsis" in update_panel and "storySummary" in update_panel
    assert "storyRouteStatusLabel" in update_panel and "target.kind" in update_panel
    assert "context.target" in update_panel
    assert 'element("button", "quiet-button story-route-target-link"' in update_panel
    assert "navigateProgressiveStorySelection(target.selectionId)" in update_panel
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


def test_story_descendants_stay_compact_until_the_owned_route_is_focused() -> None:
    app = _text("app.js")
    choice = _function(app, "renderStoryChoice")
    focus = _function(app, "focusStoryDescendantRoute")

    assert "STORY_OPEN_FORK_LIMIT" not in app
    assert 'route.dataset.storyRouteFocus = "available"' in choice
    assert "route.open = false" in choice
    assert "descendantCount <=" not in choice
    assert '$$(".story-descendant-route")' in focus
    assert "route.dataset.ownerSelectionId === selectionId" in focus
    assert re.search(
        r"route\.open\s*=\s*(?:active|route\.dataset\.ownerSelectionId\s*===\s*selectionId)",
        focus,
    )


def test_arm_focus_and_story_detail_use_separate_controls() -> None:
    app = _text("app.js")
    selection = _function(app, "storySelectionControl")
    detail = _function(app, "appendProgressiveStoryDetail")
    trigger = _function(app, "storyProgressiveDetailTrigger")

    assert 'kind === "story-arm"' in selection
    assert "focusStoryDescendantRoute(item.selection_id)" in selection
    assert "toggleProgressiveStoryDetail(control)" not in selection
    assert "story-inline-detail-trigger" in trigger
    assert 'trigger.setAttribute("aria-controls", detail.id)' in trigger
    assert 'trigger.setAttribute("aria-expanded", "false")' in trigger
    assert 'control.setAttribute("aria-controls", detail.id)' not in detail
    assert "toggleProgressiveStoryDetail(trigger)" in trigger


def test_story_confluences_expose_a_stable_target_and_return_stream() -> None:
    app = _text("app.js")
    css = _text("styles.css")
    continuations = _function(app, "appendStoryContinuations")

    assert "row.dataset.storyConfluenceTargetSelectionId = binding.selection_id" in continuations
    assert re.search(
        r"row\.dataset\.storyConfluenceScope\s*=\s*"
        r"returnRouteContext\s*\?\s*[\"']route[\"']\s*:\s*[\"']main[\"']",
        continuations,
    )
    assert '"The story comes back together"' in continuations
    assert 'row.dataset.outcomeKind = "rejoin"' in continuations
    rules = _css_rules(css)
    assert any('[data-story-confluence-scope="main"]' in selector for selector, _ in rules)
    assert any('[data-story-confluence-scope="route"]' in selector for selector, _ in rules)
    main_confluence = [
        body
        for selector, body in rules
        if '[data-story-confluence-scope="main"]' in selector
    ]
    assert any(
        ("max-width:" in body or re.search(r"\bwidth\s*:\s*(?:fit-content|min\()", body))
        and re.search(
            r"(?:margin(?:-inline)?|justify-self)\s*:[^;]*(?:auto|center)",
            body,
        )
        for body in main_confluence
    )
    assert any("--story-spine" in body for body in main_confluence)


def test_story_river_is_a_centered_spine_with_bounded_local_tributaries() -> None:
    css = _text("styles.css")
    rules = _css_rules(css)

    main_stream = [
        body
        for selector, body in rules
        if '[data-story-stream="main"]' in selector or "[data-story-stream='main']" in selector
    ]
    route_stream = [body for selector, body in rules if "[data-story-route-selection-id]" in selector]
    assert main_stream, "the shared chronology needs an explicit main-spine style"
    assert route_stream, "route-owned nodes need a separate tributary style"
    assert any("--story-spine" in body for body in main_stream)
    assert any("var(--story-route-color)" in body for body in route_stream)

    assert any(
        ".is-story-river" in selector
        and any(target in selector for target in (".story-guide", ".story-events", ".story-river-stage"))
        and ("max-width:" in body or re.search(r"\bwidth\s*:\s*min\(", body))
        and re.search(
            r"(?:margin(?:-inline)?|justify-self)\s*:[^;]*(?:auto|center)",
            body,
        )
        for selector, body in rules
    ), "the river stage must stay bounded and centered instead of stretching like a board"
    assert any(
        '[data-fork-layout="fan"]' in selector and "max-width:" in body
        for selector, body in rules
    ), "two-to-four-arm tributaries need a local width cap"


def test_route_selection_preserves_identity_and_color_in_the_reader_and_panel() -> None:
    app = _text("app.js")
    css = _text("styles.css")
    panel = _function(app, "updateStoryRoutePanel")
    rules = _css_rules(css)

    for key, value in (
        ("storyRouteSelectionId", "context.selectionId"),
        ("storyRouteCode", "context.code"),
        ("storyRouteSlot", "String(context.paletteSlot)"),
    ):
        assert f"panel.dataset.{key} = {value}" in panel
        assert f"delete panel.dataset.{key}" in panel

    selected = [
        body
        for selector, body in rules
        if '.story-arm[data-story-current="true"] > .story-arm-head' in selector
    ]
    assert selected
    assert not any(re.search(r"\bborder-color\s*:\s*var\(--accent\)", body) for body in selected)
    assert any("var(--story-tributary)" in body for body in selected)

    available = [
        body
        for selector, body in rules
        if '[data-story-route-focus="available"]' in selector
    ]
    assert available
    assert any(
        "var(--story-route-color)" in body or "var(--story-route-soft)" in body
        for body in available
    )
    assert not any(re.search(r"\bborder-color\s*:\s*var\(--accent\)", body) for body in available)


def test_intermediate_sticky_route_panel_keeps_navigation_targets_visible() -> None:
    app = _text("app.js")
    css = _text("styles.css")
    intermediate_start = css.index("@media (min-width: 1241px) and (max-width: 1499px)")
    normal_start = css.index("@media (max-width: 1240px)")
    intermediate = css[intermediate_start:normal_start]
    scroll = _function(app, "scrollStoryTo")

    sticky = ".story-route-panel" in intermediate and "position: sticky" in intermediate
    if sticky:
        css_clearance = re.search(r"scroll-(?:padding|margin)-top", intermediate)
        measured_clearance = "storyRoutePanel" in scroll and scroll.count("getBoundingClientRect") >= 2
        assert css_clearance or measured_clearance

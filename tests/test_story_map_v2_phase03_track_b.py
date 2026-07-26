# ruff: noqa: E501
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"
CONTINUATION_FIXTURE = (
    ROOT / "tests" / "fixtures" / "story_map_v2_phase03_continuation_contract.json"
)
API_CONTRACT_FIXTURE = ROOT / "tests" / "fixtures" / "story_map_v2_phase03_api_contract.json"
LONG_UNBROKEN_INSTRUCTION = "route_instruction_" + ("northbound" * 80)
LONG_SPACED_INSTRUCTION = (
    "Follow the marked corridor while keeping the selected story moment in view. " * 12
).strip()
LONG_UNBROKEN_WARNING = "dynamic_warning_" + ("unresolved" * 80)
LONG_SPACED_WARNING = (
    "Static analysis cannot prove this optional detour, but the known path remains readable. " * 11
).strip()


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _story_page() -> dict[str, object]:
    source = {"relative_path": "story/chapter.rpy", "start_line": 1, "end_line": 8}

    def binding(selection_id: str, detail_kind: str) -> dict[str, object]:
        return {
            "selection_id": selection_id,
            "destination_kind": "generic_scene",
            "target_id": f"node-{selection_id}",
            "detail_kind": detail_kind,
            "detail_id": selection_id,
            "source": source,
        }

    continuation_binding = json.loads(CONTINUATION_FIXTURE.read_text(encoding="utf-8"))["arm"][
        "rejoin_binding"
    ]

    nested_choice = {
        "key": "nested-choice",
        "source": source,
        "arms": [
            {
                "selection_id": "arm-nested-a",
                "caption": "Wait for dawn",
                "outcome_summary": "The travellers wait together.",
                "condition": "trust >= 2",
                "effects": ["Patience +1"],
                "destination_id": "node-dawn",
                "rejoin_node_id": "node-road",
                "rejoin_line": 793,
                "reachability": "unresolved",
                "warnings": ["A dynamic gate remains unresolved."],
                "binding": binding("arm-nested-a", "story_map_v2_arm"),
                "rejoin_binding": continuation_binding,
                "nested_choices": [],
            }
        ],
    }
    return {
        "schema": "story-map-v2-page-v1",
        "status": "synthesized",
        "reason": None,
        "title": "A Road Through Winter",
        "overview": "Two travellers choose how to cross the valley.",
        "analysis_notes": ["One quiet event was placed chronologically."],
        "sections": [
            {
                "id": "section-1",
                "title": "Leaving home",
                "summary": "The journey begins before the weather turns.",
                "events": [
                    {
                        "selection_id": "event-departure",
                        "title": "Departure",
                        "summary": "The travellers leave the village.",
                        "characters": ["Ari", "Mara"],
                        "reachability": "reachable",
                        "warnings": ["Source placement remains approximate."],
                        "binding": binding("event-departure", "story_map_v2_event"),
                        "choices": [
                            {
                                "key": "road-choice",
                                "source": source,
                                "arms": [
                                    {
                                        "selection_id": "arm-bridge",
                                        "caption": "Cross the bridge",
                                        "outcome_summary": "They remain on a persistent bridge route.",
                                        "condition": None,
                                        "effects": ["Courage +1"],
                                        "destination_id": "node-bridge",
                                        "rejoin_node_id": None,
                                        "rejoin_line": None,
                                        "reachability": "unreachable",
                                        "warnings": [
                                            "This persistent route is not currently reachable."
                                        ],
                                        "binding": binding("arm-bridge", "story_map_v2_arm"),
                                        "rejoin_binding": None,
                                        "nested_choices": [],
                                    },
                                    {
                                        "selection_id": "arm-tunnel",
                                        "caption": "Take the tunnel",
                                        "outcome_summary": "They enter the sheltered tunnel.",
                                        "condition": "lantern == true",
                                        "effects": [],
                                        "destination_id": "node-tunnel",
                                        "rejoin_node_id": "node-road",
                                        "rejoin_line": 793,
                                        "reachability": "reachable",
                                        "warnings": [],
                                        "binding": binding("arm-tunnel", "story_map_v2_arm"),
                                        "rejoin_binding": continuation_binding,
                                        "nested_choices": [nested_choice],
                                    },
                                ],
                            },
                            {
                                "key": "river-choice",
                                "source": source,
                                "arms": [
                                    {
                                        "selection_id": "arm-river",
                                        "caption": "Follow the river",
                                        "outcome_summary": "They rejoin the road beyond the valley.",
                                        "condition": None,
                                        "effects": [],
                                        "destination_id": "node-river",
                                        "rejoin_node_id": "node-road",
                                        "rejoin_line": 793,
                                        "reachability": "reachable",
                                        "warnings": [],
                                        "binding": binding("arm-river", "story_map_v2_arm"),
                                        "rejoin_binding": continuation_binding,
                                        "nested_choices": [],
                                    },
                                    {
                                        "selection_id": "arm-camp",
                                        "caption": "Make camp",
                                        "outcome_summary": "They remain on a separate persistent path.",
                                        "condition": None,
                                        "effects": [],
                                        "destination_id": "node-camp",
                                        "rejoin_node_id": None,
                                        "rejoin_line": None,
                                        "reachability": "unresolved",
                                        "warnings": [],
                                        "binding": binding("arm-camp", "story_map_v2_arm"),
                                        "rejoin_binding": None,
                                        "nested_choices": [],
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }


def test_story_browser_is_a_two_level_normal_flow_surface() -> None:
    html = _text("index.html")
    css = _text("styles.css")
    assets = "\n".join(
        _text(name) for name in ("index.html", "styles.css", "app.js", "api.js", "contract.js")
    )

    assert html.count('data-level="') == 2
    for marker in (
        'id="storyBrowser"',
        'id="storyGuide"',
        'id="storyPathPanel"',
        'id="closeStoryPath"',
        'id="storyPathScenes"',
        'id="storyPathChoices"',
        'id="storyPathRequirements"',
        'id="storyPathEffects"',
        'id="returnToStorySelection"',
        'id="storyAnalysisNotes"',
    ):
        assert marker in html
    assert "story-section" in css and "story-event" in css and "story-arm" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert ".story-path-panel :where" in css and "overflow-wrap: anywhere" in css
    assert "@media (max-width: 780px)" in css
    assert not re.search(r"https?://|//cdn", assets, re.IGNORECASE)
    story_surface = html[html.index('id="storyBrowser"') : html.index('<div class="commandbar">')]
    assert not re.search(r"fit.?all|zoom", story_surface, re.IGNORECASE)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_story_map_contract_accepts_nested_local_choices_and_rejects_duplicate_targets() -> None:
    module_uri = (STATIC / "contract.js").as_uri()
    page = _story_page()
    script = f"""
      import {{ assertStoryMapV2 }} from {json.dumps(module_uri)};
      const valid = {json.dumps(page)};
      const accepted = assertStoryMapV2(valid);
      const duplicate = structuredClone(valid);
      duplicate.sections[0].events[0].choices[0].arms[1].selection_id = "arm-bridge";
      duplicate.sections[0].events[0].choices[0].arms[1].binding.selection_id = "arm-bridge";
      let duplicateRejected = false;
      try {{ assertStoryMapV2(duplicate); }} catch (_error) {{ duplicateRejected = true; }}
      const continuationId = valid.sections[0].events[0].choices[0].arms[1].rejoin_binding.selection_id;
      const globalDrift = structuredClone(valid);
      globalDrift.sections[0].events[0].choices[1].arms[0].rejoin_binding.target_id = "node-drifted";
      let globalDriftRejected = false;
      try {{ assertStoryMapV2(globalDrift); }} catch (_error) {{ globalDriftRejected = true; }}
      const sameTreeDrift = structuredClone(valid);
      sameTreeDrift.sections[0].events[0].choices[0].arms[1].nested_choices[0].arms[0].rejoin_binding.target_id = "node-drifted";
      let sameTreeDriftRejected = false;
      try {{ assertStoryMapV2(sameTreeDrift); }} catch (_error) {{ sameTreeDriftRejected = true; }}
      const eventCollision = structuredClone(valid);
      eventCollision.sections[0].events[0].selection_id = continuationId;
      eventCollision.sections[0].events[0].binding.selection_id = continuationId;
      eventCollision.sections[0].events[0].binding.detail_id = continuationId;
      let eventCollisionRejected = false;
      try {{ assertStoryMapV2(eventCollision); }} catch (_error) {{ eventCollisionRejected = true; }}
      const armCollision = structuredClone(valid);
      armCollision.sections[0].events[0].choices[1].arms[0].selection_id = continuationId;
      armCollision.sections[0].events[0].choices[1].arms[0].binding.selection_id = continuationId;
      armCollision.sections[0].events[0].choices[1].arms[0].binding.detail_id = continuationId;
      let armCollisionRejected = false;
      try {{ assertStoryMapV2(armCollision); }} catch (_error) {{ armCollisionRejected = true; }}
      const mutations = [
        value => {{ value.extra = true; }},
        value => {{ delete value.overview; }},
        value => {{ value.sections[0].extra = true; }},
        value => {{ delete value.sections[0].summary; }},
        value => {{ value.sections[0].events[0].extra = true; }},
        value => {{ delete value.sections[0].events[0].title; }},
        value => {{ value.sections[0].events[0].choices[0].extra = true; }},
        value => {{ delete value.sections[0].events[0].choices[0].key; }},
        value => {{ value.sections[0].events[0].choices[0].arms[1].extra = true; }},
        value => {{ delete value.sections[0].events[0].choices[0].arms[1].caption; }},
        value => {{ value.sections[0].events[0].binding.extra = true; }},
        value => {{ delete value.sections[0].events[0].binding.target_id; }},
        value => {{ value.sections[0].events[0].choices[0].source.extra = true; }},
        value => {{ delete value.sections[0].events[0].choices[0].source.end_line; }},
        value => {{ value.sections[0].events[0].choices[0].arms[1].rejoin_binding.extra = true; }},
        value => {{ delete value.sections[0].events[0].choices[0].arms[1].rejoin_binding.detail_id; }},
        value => {{ value.analysis_notes = new Array(1_000_001); }},
        value => {{ value.sections[0].events[0].choices[0].arms = new Array(1_000_001); }},
        value => {{ value.sections[0].events[0].summary = "x".repeat(8193); }},
        value => {{
          let owner = value.sections[0].events[0].choices[0].arms[1];
          for (let depth = 0; depth < 10; depth += 1) {{
            const child = structuredClone(valid.sections[0].events[0].choices[0].arms[1].nested_choices[0]);
            child.key = `deep-${{depth}}`;
            const childArm = child.arms[0]; childArm.selection_id = `deep-arm-${{depth}}`;
            childArm.binding.selection_id = childArm.selection_id; childArm.binding.detail_id = childArm.selection_id;
            childArm.rejoin_binding = null; childArm.rejoin_node_id = null; childArm.rejoin_line = null; childArm.nested_choices = [];
            owner.nested_choices = [child]; owner = childArm;
          }}
        }},
      ];
      let adversarialRejected = 0;
      for (const mutate of mutations) {{
        const candidate = structuredClone(valid); mutate(candidate);
        try {{ assertStoryMapV2(candidate); }} catch (_error) {{ adversarialRejected += 1; }}
      }}
      process.stdout.write(JSON.stringify({{
        status: accepted.status,
        event: accepted.sections[0].events[0].selection_id,
        nested: accepted.sections[0].events[0].choices[0].arms[1].nested_choices[0].key,
        continuation: accepted.sections[0].events[0].choices[0].arms[1].rejoin_binding.selection_id,
        duplicateRejected,
        globalDriftRejected,
        sameTreeDriftRejected,
        eventCollisionRejected,
        armCollisionRejected,
        adversarialRejected,
        adversarialTotal: mutations.length,
      }}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert json.loads(completed.stdout) == {
        "status": "synthesized",
        "event": "event-departure",
        "nested": "nested-choice",
        "continuation": "story-map-v2-continuation:c2cdc2d22eefd73445bb724831489c2d55b7b3b450e55408c4369396980f487a",
        "duplicateRejected": True,
        "globalDriftRejected": True,
        "sameTreeDriftRejected": True,
        "eventCollisionRejected": True,
        "armCollisionRejected": True,
        "adversarialRejected": 20,
        "adversarialTotal": 20,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_story_map_path_contract_is_exact_and_deeply_bounded() -> None:
    module_uri = (STATIC / "contract.js").as_uri()
    assert API_CONTRACT_FIXTURE.is_file()
    assert not (
        ROOT / "tests" / "fixtures" / "story_map_v2_phase03_navigation_envelopes.json"
    ).exists()
    envelope_contract = json.loads(API_CONTRACT_FIXTURE.read_text(encoding="utf-8"))
    page = _story_page()
    binding = page["sections"][0]["events"][0]["choices"][0]["arms"][1]["binding"]
    valid = {
        "schema": "story-map-v2-path-v1",
        "semantic_level": "route_map",
        "status": "available",
        "selection_id": "arm-tunnel",
        "binding": binding,
        "cached": False,
        "route_status": "complete",
        "complete": True,
        "explanation": "A deterministic route reaches this choice.",
        "witness": {
            "scene_titles": ["Departure", "Tunnel"],
            "visible_choices": ["Take the tunnel"],
            "requirements": [
                {
                    "expression": "lantern == true",
                    "source": "route",
                    "evidence_ids": ["evidence-lantern"],
                }
            ],
            "effects": ["Courage +1"],
            "uncertainty": [],
            "instructions": [
                {"ordinal": 1, "kind": "scene", "text": "Leave the village."},
                {"ordinal": 2, "kind": "choice", "text": "Take the tunnel."},
            ],
        },
    }
    assert list(valid) == envelope_contract["path"]["available"]["keys"]
    assert list(valid["witness"]) == envelope_contract["path"]["witness_keys"]
    detail = {
        "schema": "story-map-v2-detail-v1",
        "semantic_level": "detail_evidence",
        "status": "available",
        "selection_id": "arm-tunnel",
        "binding": binding,
        "source_navigation": {
            "status": "available",
            "path": "story/chapter.rpy",
            "start_line": 1,
            "end_line": 8,
            "line_basis": "physical",
            "evidence_id": "evidence-tunnel",
        },
        "detail": {
            "status": "available",
            "level": "detail_evidence",
            "element": {"title": "Take the tunnel", "summary": "A sheltered route."},
            "evidence": [],
        },
    }
    assert list(detail) == envelope_contract["detail"]["available"]["keys"]
    assert (
        list(detail["source_navigation"])
        == envelope_contract["detail"]["source_navigation"]["available_keys"]
    )
    script = f"""
      import {{ assertStoryMapV2Detail, assertStoryMapV2Path }} from {json.dumps(module_uri)};
      const valid = {json.dumps(valid)};
      const detail = {json.dumps(detail)};
      assertStoryMapV2Path(valid, "arm-tunnel");
      assertStoryMapV2Path({{
        ...structuredClone(valid), status: "unresolved", route_status: null,
        complete: false, explanation: "The recognized destination remains unresolved.",
      }}, "arm-tunnel");
      assertStoryMapV2Path({{
        schema: "story-map-v2-path-v1", semantic_level: "route_map", status: "unavailable",
        selection_id: "arm-tunnel", reason: "The stored story map is unavailable.",
      }}, "arm-tunnel");
      assertStoryMapV2Detail(detail, "arm-tunnel");
      assertStoryMapV2Detail({{
        schema: "story-map-v2-detail-v1", semantic_level: "detail_evidence", status: "unresolved",
        selection_id: "arm-tunnel", binding: detail.binding,
        source_navigation: {{status: "unavailable", reason: "No exact source evidence."}},
        reason: "No deterministic detail target is available.",
      }}, "arm-tunnel");
      assertStoryMapV2Detail({{
        schema: "story-map-v2-detail-v1", semantic_level: "detail_evidence", status: "unavailable",
        selection_id: "arm-tunnel", reason: "The stored story map is unavailable.",
      }}, "arm-tunnel");
      const mutations = [
        value => {{ delete value.witness.effects; }},
        value => {{ value.witness.extra = []; }},
        value => {{ value.witness.requirements[0].extra = "no"; }},
        value => {{ value.witness.instructions[0].ordinal = "1"; }},
        value => {{ value.witness.visible_choices = ["x".repeat(1001)]; }},
        value => {{ value.explanation = "x".repeat(1001); }},
        value => {{ value.semantic_level = "detail_evidence"; }},
        value => {{ value.extra = true; }},
      ];
      let rejected = 0;
      for (const mutate of mutations) {{
        const candidate = structuredClone(valid); mutate(candidate);
        try {{ assertStoryMapV2Path(candidate, "arm-tunnel"); }} catch (_error) {{ rejected += 1; }}
      }}
      const unavailableWithDetail = structuredClone(detail);
      unavailableWithDetail.status = "unavailable";
      try {{ assertStoryMapV2Detail(unavailableWithDetail, "arm-tunnel"); }} catch (_error) {{ rejected += 1; }}
      const emptyReasons = [
        {{schema: "story-map-v2-path-v1", semantic_level: "route_map", status: "unavailable", selection_id: "arm-tunnel", reason: ""}},
        {{schema: "story-map-v2-detail-v1", semantic_level: "detail_evidence", status: "unavailable", selection_id: "arm-tunnel", reason: ""}},
      ];
      try {{ assertStoryMapV2Path(emptyReasons[0], "arm-tunnel"); }} catch (_error) {{ rejected += 1; }}
      try {{ assertStoryMapV2Detail(emptyReasons[1], "arm-tunnel"); }} catch (_error) {{ rejected += 1; }}
      process.stdout.write(JSON.stringify({{ rejected, total: mutations.length + 3 }}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert json.loads(completed.stdout) == {"rejected": 11, "total": 11}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_story_map_api_uses_only_bootstrap_map_path_and_detail_routes() -> None:
    module_uri = (STATIC / "api.js").as_uri()
    page = _story_page()
    binding = page["sections"][0]["events"][0]["choices"][0]["arms"][1]["binding"]
    path_response = {
        "schema": "story-map-v2-path-v1",
        "semantic_level": "route_map",
        "status": "available",
        "selection_id": "arm-tunnel",
        "binding": binding,
        "cached": False,
        "route_status": "complete",
        "complete": True,
        "explanation": "A known route reaches the tunnel choice.",
        "witness": {
            "scene_titles": ["Departure", "Tunnel"],
            "visible_choices": ["Take the tunnel"],
            "requirements": [],
            "effects": [],
            "uncertainty": [],
            "instructions": [],
        },
    }
    detail_response = {
        "schema": "story-map-v2-detail-v1",
        "semantic_level": "detail_evidence",
        "status": "available",
        "selection_id": "arm-tunnel",
        "binding": binding,
        "source_navigation": {
            "status": "available",
            "path": "story/chapter.rpy",
            "start_line": 1,
            "end_line": 8,
            "line_basis": "physical",
            "evidence_id": "evidence-tunnel",
        },
        "detail": {
            "status": "available",
            "level": "detail_evidence",
            "element": {"title": "Take the tunnel", "summary": "A sheltered route."},
            "evidence": [],
        },
    }
    script = f"""
      import {{ LocalApi }} from {json.dumps(module_uri)};
      const api = new LocalApi({{ session: "session", csrf: "csrf" }});
      const routes = {{
        map: "/api/v1/story-map-v2/map",
        path: "/api/v1/story-map-v2/path",
        detail: "/api/v1/story-map-v2/detail",
      }};
      let partialRejected = false;
      try {{ api.configureStoryMapV2({{map: routes.map}}); }} catch (_error) {{ partialRejected = true; }}
      api.configureStoryMapV2(routes);
      const calls = [];
      api.request = async (path, options = {{}}) => {{
        calls.push({{ path, method: options.method, body: options.body }});
        if (path.endsWith("/map")) return {json.dumps(page)};
        if (path.endsWith("/path")) return {json.dumps(path_response)};
        return {json.dumps(detail_response)};
      }};
      await api.storyMapV2();
      await api.storyMapV2Path("arm-tunnel");
      await api.storyMapV2Detail("arm-tunnel");
      process.stdout.write(JSON.stringify({{calls, partialRejected}}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)
    assert result["partialRejected"] is True
    assert result["calls"] == [
        {"path": "/api/v1/story-map-v2/map", "method": "POST", "body": {}},
        {
            "path": "/api/v1/story-map-v2/path",
            "method": "POST",
            "body": {"selection_id": "arm-tunnel"},
        },
        {
            "path": "/api/v1/story-map-v2/detail",
            "method": "POST",
            "body": {"selection_id": "arm-tunnel"},
        },
    ]


def test_story_map_v2_is_primary_without_removing_compatibility_maps() -> None:
    app = _text("app.js")
    story_loader = app[
        app.index("async function loadStoryMapV2") : app.index(
            "async function enterAvailableWorkspace"
        )
    ]

    assert "await api.storyMapV2()" in story_loader
    assert 'page.status === "unavailable"' in story_loader
    assert "renderStoryMapV2" in story_loader
    assert "return false" in story_loader
    workspace = app[
        app.index("async function enterAvailableWorkspace") : app.index("function nextCursor")
    ]
    assert "await loadStoryMapV2()" in workspace
    assert "await resetRoutePaging()" in workspace
    assert "if (storyAvailable)" in workspace
    assert "loadComparison" in app and "renderMap" in app
    assert "arm.rejoin_binding" in app
    assert (
        "rejoin_node_id"
        not in app[app.index("function renderStoryChoice") : app.index("function renderStoryEvent")]
    )


def test_story_selection_path_detail_and_scroll_context_are_explicit() -> None:
    app = _text("app.js")
    for marker in (
        "storySelectionId",
        "storySelectionScrollY",
        "selectStoryItem",
        "api.storyMapV2Path(selectionId)",
        "api.storyMapV2Detail(selectionId)",
        "returnToStorySelection",
        "scrollIntoView",
        "focus({ preventScroll: true })",
        'document.documentElement.dataset.activeLevel = "detail_evidence"',
    ):
        assert marker in app
    assert 'aria-selected="true"' in app or 'setAttribute("aria-selected", "true")' in app
    assert ".innerHTML" not in app


def test_story_browser_uses_exact_frozen_continuation_and_clean_utf8() -> None:
    fixture = json.loads(CONTINUATION_FIXTURE.read_text(encoding="utf-8"))
    binding = fixture["arm"]["rejoin_binding"]
    assert binding == {
        "selection_id": "story-map-v2-continuation:c2cdc2d22eefd73445bb724831489c2d55b7b3b450e55408c4369396980f487a",
        "destination_kind": "generic_scene",
        "target_id": "scene-day-two-boundary",
        "detail_kind": "story_map_v2_continuation",
        "detail_id": "story-map-v2-continuation:c2cdc2d22eefd73445bb724831489c2d55b7b3b450e55408c4369396980f487a",
        "source": {"relative_path": "game/story.rpy", "start_line": 793, "end_line": 793},
    }
    app = _text("app.js")
    story_code = app[
        app.index("function showStorySurface") : app.index("async function enterAvailableWorkspace")
    ]
    assert "arm.rejoin_binding" in story_code
    assert "rejoin_binding.selection_id" in story_code
    assert "armPath" in story_code
    assert "appendStoryWarnings" in story_code
    assert "index === 0" not in story_code
    assert "instructions.length - 1" not in story_code
    mojibake = (
        "\u00c3\u0192",
        "\u00c3\u201a",
        "\u00c3\u00a2",
        "\u00c2\u00b7",
        "\u00e2\u20ac\u00a6",
        "\u00e2\u20ac\u201c",
        "\u00ef\u00bf\u00bd",
    )
    assert all(fragment not in story_code for fragment in mojibake)


def _browser_driver() -> Any:
    source_root = str(ROOT / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    path = ROOT / "scripts" / "m10_browser_acceptance.py"
    spec = importlib.util.spec_from_file_location("m15_track_b_browser_driver", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _SyntheticStoryHandler(http.server.BaseHTTPRequestHandler):
    story_page: dict[str, object]
    delayed_path_selection: str | None = None
    delayed_path_reject = False
    path_release: threading.Event | None = None
    path_finished: threading.Event | None = None
    delayed_detail_selection: str | None = None
    delayed_detail_reject = False
    detail_started: threading.Event | None = None
    detail_release: threading.Event | None = None
    detail_finished: threading.Event | None = None

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _json(self, payload: object, status: int = 200) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path == "/api/v1/bootstrap":
            self._json(
                {
                    "api_version": "v1",
                    "recent_projects": [
                        {
                            "selection_id": "synthetic-project",
                            "name": "Synthetic winter story",
                            "source_type": "Project",
                            "organization": "Story Map V2",
                        }
                    ],
                    "settings": {
                        "theme": "light",
                        "include_technical": True,
                        "include_unresolved": True,
                    },
                    "routes": {
                        "story_map_v2": {
                            "map": "/api/v1/story-map-v2/map",
                            "path": "/api/v1/story-map-v2/path",
                            "detail": "/api/v1/story-map-v2/detail",
                        }
                    },
                }
            )
            return
        relative = "index.html" if self.path in {"/", "/index.html"} else self.path.lstrip("/")
        target = (STATIC / relative).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self.send_error(404)
            return
        content = target.read_bytes()
        media = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
        }.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/v1/projects/open":
            self._json(
                {"project": {"name": "Synthetic winter story"}, "analysis": {"state": "complete"}}
            )
        elif self.path == "/api/v1/story-map-v2/map":
            self._json(self.story_page)
        elif self.path == "/api/v1/story-map-v2/path":
            selection_id = body["selection_id"]
            delayed = selection_id == self.delayed_path_selection and self.path_release is not None
            if delayed:
                self.path_release.wait(timeout=10)
            if delayed and self.delayed_path_reject:
                self._json({"error": {"message": "Synthetic delayed failure"}}, status=503)
                if self.path_finished is not None:
                    self.path_finished.set()
                return
            self._json(
                {
                    "schema": "story-map-v2-path-v1",
                    "semantic_level": "route_map",
                    "status": "available",
                    "selection_id": selection_id,
                    "binding": {
                        "selection_id": selection_id,
                        "destination_kind": "generic_scene",
                        "target_id": f"scene-{selection_id}",
                        "detail_kind": "story_map_v2_selection",
                        "detail_id": selection_id,
                        "source": {
                            "relative_path": "story/chapter.rpy",
                            "start_line": 1,
                            "end_line": 8,
                        },
                    },
                    "cached": False,
                    "route_status": "complete",
                    "complete": True,
                    "explanation": "A known route reaches the tunnel choice.",
                    "witness": {
                        "scene_titles": ["Departure", "Tunnel"],
                        "visible_choices": ["Take the tunnel"],
                        "requirements": [
                            {
                                "expression": "lantern == true",
                                "source": "route",
                                "evidence_ids": ["evidence-lantern"],
                            }
                        ],
                        "effects": ["Patience +1"],
                        "uncertainty": [LONG_UNBROKEN_WARNING, LONG_SPACED_WARNING],
                        "instructions": [
                            {"ordinal": 1, "kind": "scene", "text": "Leave the village."},
                            {"ordinal": 2, "kind": "choice", "text": "Take the tunnel."},
                            {
                                "ordinal": 3,
                                "kind": "route_note",
                                "text": LONG_UNBROKEN_INSTRUCTION,
                            },
                            {
                                "ordinal": 4,
                                "kind": "route_note",
                                "text": LONG_SPACED_INSTRUCTION,
                            },
                        ],
                    },
                }
            )
            if delayed and self.path_finished is not None:
                self.path_finished.set()
        elif self.path == "/api/v1/story-map-v2/detail":
            selection_id = body["selection_id"]
            delayed = (
                selection_id == self.delayed_detail_selection
                and self.detail_release is not None
            )
            if delayed:
                if self.detail_started is not None:
                    self.detail_started.set()
                self.detail_release.wait(timeout=10)
            if delayed and self.delayed_detail_reject:
                self._json({"error": {"message": "Synthetic delayed detail failure"}}, status=503)
                if self.detail_finished is not None:
                    self.detail_finished.set()
                return
            binding = {
                "selection_id": selection_id,
                "destination_kind": "generic_scene",
                "target_id": f"scene-{selection_id}",
                "detail_kind": "story_map_v2_selection",
                "detail_id": selection_id,
                "source": {
                    "relative_path": "story/chapter.rpy",
                    "start_line": 1,
                    "end_line": 8,
                },
            }
            source_navigation = {
                "status": "available",
                "path": "story/chapter.rpy",
                "start_line": 6,
                "end_line": 8,
                "line_basis": "physical",
                "evidence_id": "evidence-wait",
            }
            if selection_id.startswith("story-map-v2-continuation:"):
                self._json(
                    {
                        "schema": "story-map-v2-detail-v1",
                        "semantic_level": "detail_evidence",
                        "status": "unresolved",
                        "selection_id": selection_id,
                        "binding": binding,
                        "source_navigation": source_navigation,
                        "reason": "This recognized continuation has no deterministic detail target.",
                    }
                )
                return
            self._json(
                {
                    "schema": "story-map-v2-detail-v1",
                    "semantic_level": "detail_evidence",
                    "status": "available",
                    "selection_id": selection_id,
                    "binding": binding,
                    "source_navigation": source_navigation,
                    "detail": {
                        "status": "available",
                        "level": "detail_evidence",
                        "element": {
                            "title": {
                                "arm-bridge": "Cross the bridge",
                                "arm-nested-a": "Wait for dawn",
                            }.get(selection_id, f"Detail for {selection_id}"),
                            "summary": f"Exact detail for {selection_id}.",
                        },
                        "evidence": [],
                    },
                }
            )
            if delayed and self.detail_finished is not None:
                self.detail_finished.set()
        else:
            self.send_error(404)


def _browser_measurement(session: Any) -> dict[str, object]:
    return session.evaluate(
        """(() => {
          const root = document.documentElement; const body = document.body;
          const important = [...document.querySelectorAll('.story-section,.story-event,.story-choice,.story-arm,.story-continuation')];
          const boxes = important.map(node => { const rect = node.getBoundingClientRect(); return {
            className: node.className, width: rect.width, height: rect.height,
            left: rect.left, right: rect.right, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth,
            clientHeight: node.clientHeight, scrollHeight: node.scrollHeight,
          }; });
          const stackSelectors = ['#storySections', '.story-events', '.story-choices', '.story-arms'];
          const groups = stackSelectors.flatMap(selector => [...document.querySelectorAll(selector)].map(group => {
            const children = [...group.children].filter(node => node.matches('.story-section,.story-event,.story-choice,.story-arm,.story-continuation'));
            const rects = children.map(node => node.getBoundingClientRect());
            return { count: rects.length, ordered: rects.every((rect, index) => index === 0 || rect.top >= rects[index - 1].bottom - 1) };
          }));
          return {
            page: { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth, bodyScrollWidth: body.scrollWidth, bodyClientWidth: body.clientWidth },
            boxes, groups,
            nestedArms: document.querySelectorAll('.story-choice.nested .story-arm').length,
            continuations: document.querySelectorAll('.story-continuation').length,
            continuationTargets: document.querySelectorAll('[data-story-selection-id="story-map-v2-continuation:c2cdc2d22eefd73445bb724831489c2d55b7b3b450e55408c4369396980f487a"][aria-selected]').length,
            continuationInsideArm: document.querySelectorAll('.story-arm > .story-continuation').length,
            reachability: [...document.querySelectorAll('.story-reachability')].map(node => node.textContent.trim()),
            warningDetails: document.querySelectorAll('details.story-warnings').length,
            warningsOpen: document.querySelectorAll('details.story-warnings[open]').length,
            warningText: [...document.querySelectorAll('details.story-warnings')].map(node => node.textContent),
          };
        })()"""
    )


def _story_path_measurement(session: Any) -> dict[str, object]:
    return session.evaluate(
        """(() => {
          const root = document.documentElement;
          const browser = document.querySelector('#storyBrowser');
          const panel = document.querySelector('#storyPathPanel');
          const panelRect = panel.getBoundingClientRect();
          const candidates = [panel, ...panel.querySelectorAll('*')].filter(node => {
            const rect = node.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          });
          const overflowers = candidates.filter(node => node.scrollWidth > node.clientWidth + 1).map(node => node.id || node.className || node.tagName);
          const clipped = candidates.filter(node => {
            const style = getComputedStyle(node);
            const hidesX = style.overflowX === 'hidden' || style.overflowX === 'clip';
            const hidesY = style.overflowY === 'hidden' || style.overflowY === 'clip';
            return (hidesX && node.scrollWidth > node.clientWidth + 1) || (hidesY && node.scrollHeight > node.clientHeight + 1);
          }).map(node => node.id || node.className || node.tagName);
          const important = [...panel.querySelectorAll('.story-path-step span, #storyPathWarnings p')];
          const boxes = important.map(node => {
            const rect = node.getBoundingClientRect();
            return { width: rect.width, height: rect.height, left: rect.left, right: rect.right, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight };
          });
          const steps = [...panel.querySelectorAll('.story-path-step')].map(node => node.getBoundingClientRect());
          const warnings = [...panel.querySelectorAll('#storyPathWarnings p')].map(node => node.getBoundingClientRect());
          const beforeScroll = panel.scrollTop;
          panel.scrollTop = panel.scrollHeight;
          const afterScroll = panel.scrollTop;
          const detailRect = document.querySelector('#storyDetailAction').getBoundingClientRect();
          panel.scrollTop = beforeScroll;
          const beforeBrowserScroll = browser.scrollTop;
          browser.scrollTop = browser.scrollHeight;
          const afterBrowserScroll = browser.scrollTop;
          browser.scrollTop = beforeBrowserScroll;
          return {
            panel: { clientWidth: panel.clientWidth, scrollWidth: panel.scrollWidth, clientHeight: panel.clientHeight, scrollHeight: panel.scrollHeight, left: panelRect.left, right: panelRect.right },
            page: { clientWidth: root.clientWidth, scrollWidth: root.scrollWidth, browserClientWidth: browser.clientWidth, browserScrollWidth: browser.scrollWidth },
            overflowers, clipped, boxes,
            stepsOrdered: steps.every((rect, index) => index === 0 || rect.top >= steps[index - 1].bottom - 1),
            warningsOrdered: warnings.every((rect, index) => index === 0 || rect.top >= warnings[index - 1].bottom - 1),
            verticalScroll: { before: beforeScroll, after: afterScroll, browserBefore: beforeBrowserScroll, browserAfter: afterBrowserScroll, detailTop: detailRect.top, panelTop: panelRect.top, panelBottom: panelRect.bottom },
            instructionText: document.querySelector('#storyPathSteps').textContent,
            warningText: document.querySelector('#storyPathWarnings').textContent,
            uncertaintyHidden: document.querySelector('#storyPathUncertaintyGroup').hidden,
          };
        })()"""
    )


@pytest.mark.hardware_sensitive
@pytest.mark.skipif(
    os.environ.get("RSM_RUN_BROWSER_ACCEPTANCE") != "1",
    reason="set RSM_RUN_BROWSER_ACCEPTANCE=1 for the provider-free real-browser smoke",
)
@pytest.mark.parametrize(
    ("profile", "zoom", "width", "height"),
    (("desktop", 100, 1440, 900), ("effective-200", 200, 720, 450), ("narrow", 100, 390, 844)),
)
def test_story_detail_stale_responses_do_not_replace_current_context(
    profile: str, zoom: int, width: int, height: int
) -> None:
    driver = _browser_driver()
    page = _story_page()
    page["sections"][0]["events"][0]["choices"] = page["sections"][0]["events"][0][
        "choices"
    ][:1]
    _SyntheticStoryHandler.story_page = page
    _SyntheticStoryHandler.delayed_detail_selection = None
    _SyntheticStoryHandler.delayed_detail_reject = False
    _SyntheticStoryHandler.detail_started = None
    _SyntheticStoryHandler.detail_release = None
    _SyntheticStoryHandler.detail_finished = None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticStoryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}/"
    with tempfile.TemporaryDirectory(prefix=f"rsm-m15-track-b-detail-{profile}-") as temporary:
        process, session = driver._session(driver._browser(), zoom, Path(temporary))
        try:
            session.command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 2 if zoom == 200 else 1,
                    "mobile": False,
                },
            )
            session.command("Page.navigate", {"url": origin})
            session.wait(
                "document.readyState === 'complete' && !!document.querySelector('.recent-card')"
            )
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait(
                "!document.querySelector('#storyBrowser').hidden && document.querySelectorAll('.story-arm').length === 3"
            )

            for reject in (False, True):
                started = threading.Event()
                release = threading.Event()
                finished = threading.Event()
                _SyntheticStoryHandler.delayed_detail_selection = "arm-bridge"
                _SyntheticStoryHandler.delayed_detail_reject = reject
                _SyntheticStoryHandler.detail_started = started
                _SyntheticStoryHandler.detail_release = release
                _SyntheticStoryHandler.detail_finished = finished
                session.evaluate(
                    "document.querySelector('.story-arm-select[data-story-selection-id=\"arm-bridge\"]').closest('.story-arm').querySelector('.story-detail-button').click()"
                )
                assert started.wait(timeout=5)
                session.evaluate(
                    "document.querySelector('.story-arm-select[data-story-selection-id=\"arm-nested-a\"]').closest('.story-arm').querySelector('.story-detail-button').click()"
                )
                session.wait(
                    "!document.querySelector('#detailView').hidden && document.querySelector('#detailTitle').textContent === 'Wait for dawn'"
                )
                current = session.evaluate(
                    "({title:document.querySelector('#detailTitle').textContent, summary:document.querySelector('#detailSummary').textContent, toast:document.querySelector('#toast').textContent, toastHidden:document.querySelector('#toast').hidden})"
                )
                release.set()
                assert finished.wait(timeout=5)
                session.command(
                    "Runtime.evaluate",
                    {
                        "expression": "new Promise(resolve => setTimeout(resolve, 250))",
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                )
                stale = session.evaluate(
                    "({title:document.querySelector('#detailTitle').textContent, summary:document.querySelector('#detailSummary').textContent, toast:document.querySelector('#toast').textContent, toastHidden:document.querySelector('#toast').hidden, selection:document.querySelector('.story-arm-select[data-story-selection-id=\"arm-nested-a\"]').getAttribute('aria-selected'), activeLevel:document.documentElement.dataset.activeLevel})"
                )
                assert stale["title"] == current["title"]
                assert stale["summary"] == current["summary"]
                assert stale["toast"] == current["toast"]
                assert stale["toastHidden"] == current["toastHidden"]
                assert stale["selection"] == "true"
                assert stale["activeLevel"] == "detail_evidence"
                session.evaluate("document.querySelector('#backToRouteMap').click()")
                session.wait(
                    "document.activeElement === document.querySelector('.story-arm-select[data-story-selection-id=\"arm-nested-a\"]')"
                )

            session.evaluate(
                "document.querySelector('.story-arm-select[data-story-selection-id=\"arm-bridge\"]').click()"
            )
            session.wait(
                "!document.querySelector('#storyPathPanel').hidden && !document.querySelector('#storyDetailAction').disabled"
            )
            started = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            _SyntheticStoryHandler.delayed_detail_selection = "arm-bridge"
            _SyntheticStoryHandler.delayed_detail_reject = False
            _SyntheticStoryHandler.detail_started = started
            _SyntheticStoryHandler.detail_release = release
            _SyntheticStoryHandler.detail_finished = finished
            session.evaluate("document.querySelector('#storyDetailAction').click()")
            assert started.wait(timeout=5)
            session.evaluate("document.querySelector('#returnToStorySelection').click()")
            session.wait(
                "document.activeElement === document.querySelector('.story-arm-select[data-story-selection-id=\"arm-bridge\"]') && document.documentElement.dataset.activeLevel === 'route_map'"
            )
            returned = session.evaluate(
                "({scrollTop:document.querySelector('#storyBrowser').scrollTop, windowY:window.scrollY, top:document.querySelector('.story-arm-select[data-story-selection-id=\"arm-bridge\"]').getBoundingClientRect().top})"
            )
            release.set()
            assert finished.wait(timeout=5)
            session.command(
                "Runtime.evaluate",
                {
                    "expression": "new Promise(resolve => setTimeout(resolve, 250))",
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            )
            after_return = session.evaluate(
                "({level:document.documentElement.dataset.activeLevel, focused:document.activeElement?.dataset?.storySelectionId, scrollTop:document.querySelector('#storyBrowser').scrollTop, windowY:window.scrollY, top:document.querySelector('.story-arm-select[data-story-selection-id=\"arm-bridge\"]').getBoundingClientRect().top})"
            )
            assert after_return["level"] == "route_map"
            assert after_return["focused"] == "arm-bridge"
            assert abs(after_return["scrollTop"] - returned["scrollTop"]) <= 2
            assert abs(after_return["windowY"] - returned["windowY"]) <= 2
            assert abs(after_return["top"] - returned["top"]) <= 2

            _SyntheticStoryHandler.delayed_detail_selection = None
            _SyntheticStoryHandler.delayed_detail_reject = False
            _SyntheticStoryHandler.detail_started = None
            _SyntheticStoryHandler.detail_release = None
            _SyntheticStoryHandler.detail_finished = None
            session.evaluate(
                "document.querySelector('.story-arm-select[data-story-selection-id=\"arm-nested-a\"]').closest('.story-arm').querySelector('.story-detail-button').click()"
            )
            session.wait(
                "!document.querySelector('#detailView').hidden && document.querySelector('#detailTitle').textContent === 'Wait for dawn'"
            )
            _, _, allowed_errors = driver._browser_diagnostics(
                session, allowed_error_suffixes=("/api/v1/story-map-v2/detail",)
            )
            assert allowed_errors == 1
        finally:
            session.close()
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.mark.hardware_sensitive
@pytest.mark.skipif(
    os.environ.get("RSM_RUN_BROWSER_ACCEPTANCE") != "1",
    reason="set RSM_RUN_BROWSER_ACCEPTANCE=1 for the provider-free real-browser smoke",
)
@pytest.mark.parametrize(
    ("profile", "zoom", "width", "height"),
    (("desktop", 100, 1440, 900), ("effective-200", 200, 720, 450), ("narrow", 100, 390, 844)),
)
def test_story_map_v2_real_browser_geometry_and_deep_return(
    profile: str, zoom: int, width: int, height: int
) -> None:
    driver = _browser_driver()
    _SyntheticStoryHandler.story_page = _story_page()
    _SyntheticStoryHandler.delayed_path_selection = None
    _SyntheticStoryHandler.delayed_path_reject = False
    _SyntheticStoryHandler.path_release = None
    _SyntheticStoryHandler.path_finished = None
    _SyntheticStoryHandler.delayed_detail_selection = None
    _SyntheticStoryHandler.delayed_detail_reject = False
    _SyntheticStoryHandler.detail_started = None
    _SyntheticStoryHandler.detail_release = None
    _SyntheticStoryHandler.detail_finished = None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticStoryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}/"
    with tempfile.TemporaryDirectory(prefix=f"rsm-m15-track-b-{profile}-") as temporary:
        process, session = driver._session(driver._browser(), zoom, Path(temporary))
        try:
            session.command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 2 if zoom == 200 else 1,
                    "mobile": False,
                },
            )
            session.command("Page.navigate", {"url": origin})
            session.wait(
                "document.readyState === 'complete' && !!document.querySelector('.recent-card')"
            )
            session.evaluate("document.querySelector('.recent-card').click()")
            session.wait(
                "!document.querySelector('#storyBrowser').hidden && document.querySelectorAll('.story-arm').length === 5"
            )

            measured = _browser_measurement(session)
            page = measured["page"]
            assert isinstance(page, dict)
            assert page["scrollWidth"] <= page["clientWidth"]
            assert page["bodyScrollWidth"] <= page["bodyClientWidth"]
            boxes = measured["boxes"]
            assert isinstance(boxes, list) and boxes
            for box in boxes:
                assert box["width"] > 0 and box["height"] > 0
                assert box["left"] >= -1 and box["right"] <= width + 1
                assert box["scrollWidth"] <= box["clientWidth"] + 1
                assert box["scrollHeight"] <= box["clientHeight"] + 2
            groups = measured["groups"]
            assert isinstance(groups, list) and all(group["ordered"] for group in groups)
            assert measured["nestedArms"] == 1
            assert measured["continuations"] == 2
            assert measured["continuationTargets"] == 2
            assert measured["continuationInsideArm"] == 2
            assert set(measured["reachability"]) == {"Reachable", "Unreachable", "Unresolved"}
            assert measured["warningDetails"] == 3
            assert measured["warningsOpen"] == 0
            assert any("dynamic gate" in text for text in measured["warningText"])

            session.evaluate(
                "document.querySelector('.story-choice.nested .story-detail-button').scrollIntoView({block:'center'})"
            )
            direct_before = session.evaluate(
                "({scrollTop:document.querySelector('#storyBrowser').scrollTop, top:document.querySelector('.story-choice.nested .story-arm-select').getBoundingClientRect().top})"
            )
            session.evaluate(
                "document.querySelector('.story-choice.nested .story-detail-button').click()"
            )
            session.wait(
                "!document.querySelector('#detailView').hidden && document.documentElement.dataset.activeLevel === 'detail_evidence'"
            )
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait(
                "document.activeElement?.dataset?.storySelectionId === 'arm-nested-a' && !document.querySelector('#storyBrowser').hidden"
            )
            direct_restored = session.evaluate(
                "({scrollTop:document.querySelector('#storyBrowser').scrollTop, top:document.querySelector('.story-choice.nested .story-arm-select').getBoundingClientRect().top, selected:document.querySelector('.story-choice.nested .story-arm-select').getAttribute('aria-selected')})"
            )
            assert abs(direct_restored["scrollTop"] - direct_before["scrollTop"]) <= 2
            assert abs(direct_restored["top"] - direct_before["top"]) <= 2
            assert direct_restored["selected"] == "true"

            session.evaluate(
                "document.querySelector('.story-choice.nested .story-arm-select').scrollIntoView({block:'center'})"
            )
            path_before = session.evaluate(
                "({scrollTop:document.querySelector('#storyBrowser').scrollTop, windowY:window.scrollY, top:document.querySelector('.story-choice.nested .story-arm-select').getBoundingClientRect().top})"
            )
            session.evaluate(
                "document.querySelector('.story-choice.nested .story-arm-select').click()"
            )
            session.wait(
                "!document.querySelector('#storyPathPanel').hidden && document.querySelectorAll('#storyPathSteps .story-path-step').length === 4 && document.querySelector('.story-choice.nested .story-arm-select').getAttribute('aria-selected') === 'true'"
            )
            witness = session.evaluate(
                "({scenes:document.querySelector('#storyPathScenes').textContent, choices:document.querySelector('#storyPathChoices').textContent, requirements:document.querySelector('#storyPathRequirements').textContent, effects:document.querySelector('#storyPathEffects').textContent, steps:document.querySelector('#storyPathSteps').textContent})"
            )
            assert "Departure" in witness["scenes"] and "Tunnel" in witness["scenes"]
            assert "Take the tunnel" in witness["choices"]
            assert "lantern == true" in witness["requirements"]
            assert "Patience +1" in witness["effects"]
            assert "lantern == true" not in witness["steps"]
            assert "Patience +1" not in witness["steps"]
            path_layout = _story_path_measurement(session)
            panel = path_layout["panel"]
            assert panel["scrollWidth"] <= panel["clientWidth"] + 1
            page_layout = path_layout["page"]
            assert page_layout["scrollWidth"] <= page_layout["clientWidth"]
            assert page_layout["browserScrollWidth"] <= page_layout["browserClientWidth"] + 1
            assert path_layout["overflowers"] == []
            assert path_layout["clipped"] == []
            assert path_layout["stepsOrdered"] is True
            assert path_layout["warningsOrdered"] is True
            assert path_layout["uncertaintyHidden"] is False
            assert LONG_UNBROKEN_INSTRUCTION in path_layout["instructionText"]
            assert LONG_SPACED_INSTRUCTION in path_layout["instructionText"]
            assert LONG_UNBROKEN_WARNING in path_layout["warningText"]
            assert LONG_SPACED_WARNING in path_layout["warningText"]
            assert path_layout["boxes"]
            for box in path_layout["boxes"]:
                assert box["width"] > 0 and box["height"] > 0
                assert box["left"] >= panel["left"] - 1
                assert box["right"] <= panel["right"] + 1
                assert box["scrollWidth"] <= box["clientWidth"] + 1
                assert box["scrollHeight"] <= box["clientHeight"] + 1
            vertical_scroll = path_layout["verticalScroll"]
            assert max(vertical_scroll["after"], vertical_scroll["browserAfter"]) > 0
            session.evaluate("document.querySelector('#closeStoryPath').click()")
            session.wait(
                "document.querySelector('#storyPathPanel').hidden && document.activeElement?.dataset?.storySelectionId === 'arm-nested-a'"
            )
            path_restored = session.evaluate(
                "({scrollTop:document.querySelector('#storyBrowser').scrollTop, windowY:window.scrollY, top:document.querySelector('.story-choice.nested .story-arm-select').getBoundingClientRect().top})"
            )
            assert abs(path_restored["scrollTop"] - path_before["scrollTop"]) <= 2
            assert abs(path_restored["windowY"] - path_before["windowY"]) <= 2
            assert abs(path_restored["top"] - path_before["top"]) <= 2
            session.evaluate(
                "document.querySelector('.story-choice.nested .story-arm-select').click()"
            )
            session.wait(
                "!document.querySelector('#storyPathPanel').hidden && !document.querySelector('#storyDetailAction').disabled && document.querySelectorAll('#storyPathSteps .story-path-step').length === 4"
            )
            before = session.evaluate(
                "({scrollTop:document.querySelector('#storyBrowser').scrollTop, top:document.querySelector('.story-choice.nested .story-arm-select').getBoundingClientRect().top})"
            )
            session.evaluate("document.querySelector('#storyDetailAction').click()")
            session.wait(
                "!document.querySelector('#detailView').hidden && document.documentElement.dataset.activeLevel === 'detail_evidence'"
            )
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait(
                "!document.querySelector('#storyBrowser').hidden && document.documentElement.dataset.activeLevel === 'route_map'"
            )
            restored = session.evaluate(
                "({scrollTop:document.querySelector('#storyBrowser').scrollTop, focused:document.activeElement?.dataset?.storySelectionId, top:document.querySelector('.story-choice.nested .story-arm-select').getBoundingClientRect().top})"
            )
            assert abs(restored["scrollTop"] - before["scrollTop"]) <= 2
            assert restored["focused"] == "arm-nested-a"
            assert abs(restored["top"] - before["top"]) <= 2

            session.evaluate(
                "document.querySelector('#storyBrowser').scrollTop = 0; document.querySelector('#returnToStorySelection').click()"
            )
            returned = session.evaluate(
                "(() => { const rect=document.querySelector('.story-choice.nested .story-arm-select').getBoundingClientRect(); return {focused:document.activeElement?.dataset?.storySelectionId, top:rect.top, bottom:rect.bottom}; })()"
            )
            assert returned["focused"] == "arm-nested-a"
            assert returned["bottom"] > 0 and returned["top"] < height

            session.evaluate(
                "document.querySelector('.story-continuation .story-detail-button').click()"
            )
            session.wait(
                "!document.querySelector('#detailView').hidden && document.querySelector('#detailSummary').textContent.includes('recognized continuation')"
            )
            unresolved = session.evaluate(
                "({level:document.documentElement.dataset.activeLevel, source:document.querySelector('#evidenceList').textContent})"
            )
            assert unresolved["level"] == "detail_evidence"
            assert "story/chapter.rpy:6" in unresolved["source"]

            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait("!document.querySelector('#storyBrowser').hidden")
            second_continuation_before = session.evaluate(
                """(() => {
                  const control = document.querySelectorAll('.story-continuation-select')[1];
                  control.scrollIntoView({block:'center'});
                  const rect = control.getBoundingClientRect();
                  return {scrollTop:document.querySelector('#storyBrowser').scrollTop, top:rect.top};
                })()"""
            )
            session.evaluate(
                "document.querySelectorAll('.story-continuation .story-detail-button')[1].click()"
            )
            session.wait(
                "!document.querySelector('#detailView').hidden && document.querySelector('#detailSummary').textContent.includes('recognized continuation')"
            )
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait(
                "document.activeElement === document.querySelectorAll('.story-continuation-select')[1]"
            )
            second_continuation_restored = session.evaluate(
                """(() => {
                  const controls = [...document.querySelectorAll('.story-continuation-select')];
                  const rect = controls[1].getBoundingClientRect();
                  return {
                    firstSelected: controls[0].getAttribute('aria-selected'),
                    secondSelected: controls[1].getAttribute('aria-selected'),
                    scrollTop: document.querySelector('#storyBrowser').scrollTop,
                    top: rect.top,
                  };
                })()"""
            )
            assert second_continuation_restored["firstSelected"] == "false"
            assert second_continuation_restored["secondSelected"] == "true"
            assert (
                abs(
                    second_continuation_restored["scrollTop"]
                    - second_continuation_before["scrollTop"]
                )
                <= 2
            )
            assert (
                abs(second_continuation_restored["top"] - second_continuation_before["top"])
                <= 2
            )
            session.evaluate("document.querySelectorAll('.story-continuation-select')[1].click()")
            session.wait(
                "!document.querySelector('#storyPathPanel').hidden && !document.querySelector('#storyDetailAction').disabled"
            )
            session.evaluate("document.querySelector('#storyDetailAction').click()")
            session.wait(
                "!document.querySelector('#detailView').hidden && document.querySelector('#detailSummary').textContent.includes('recognized continuation')"
            )
            session.evaluate("document.querySelector('#backToRouteMap').click()")
            session.wait(
                "document.activeElement === document.querySelectorAll('.story-continuation-select')[1]"
            )
            session.evaluate(
                "if (!document.querySelector('#storyPathPanel').hidden) document.querySelector('#closeStoryPath').click()"
            )
            session.wait("document.querySelector('#storyPathPanel').hidden")
            for reject in (False, True):
                release = threading.Event()
                finished = threading.Event()
                _SyntheticStoryHandler.delayed_path_selection = "arm-nested-a"
                _SyntheticStoryHandler.delayed_path_reject = reject
                _SyntheticStoryHandler.path_release = release
                _SyntheticStoryHandler.path_finished = finished
                session.evaluate(
                    "document.querySelector('[data-story-selection-id=\"arm-nested-a\"][aria-selected]').scrollIntoView({block:'center'})"
                )
                delayed_before = session.evaluate(
                    "({scrollTop:document.querySelector('#storyBrowser').scrollTop, windowY:window.scrollY, top:document.querySelector('[data-story-selection-id=\"arm-nested-a\"][aria-selected]').getBoundingClientRect().top})"
                )
                session.evaluate(
                    "document.querySelector('[data-story-selection-id=\"arm-nested-a\"][aria-selected]').click()"
                )
                session.wait(
                    "!document.querySelector('#storyPathPanel').hidden && document.querySelector('#storyDetailAction').disabled"
                )
                session.evaluate("document.querySelector('#closeStoryPath').click()")
                session.wait(
                    "document.querySelector('#storyPathPanel').hidden && document.activeElement?.dataset?.storySelectionId === 'arm-nested-a'"
                )
                closed = session.evaluate(
                    "({scrollTop:document.querySelector('#storyBrowser').scrollTop, windowY:window.scrollY, top:document.querySelector('[data-story-selection-id=\"arm-nested-a\"][aria-selected]').getBoundingClientRect().top, summary:document.querySelector('#storyPathSummary').textContent})"
                )
                assert abs(closed["scrollTop"] - delayed_before["scrollTop"]) <= 2
                assert abs(closed["windowY"] - delayed_before["windowY"]) <= 2
                assert abs(closed["top"] - delayed_before["top"]) <= 2
                release.set()
                assert finished.wait(timeout=5)
                session.command(
                    "Runtime.evaluate",
                    {
                        "expression": "new Promise(resolve => setTimeout(resolve, 250))",
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                )
                stale = session.evaluate(
                    "({hidden:document.querySelector('#storyPathPanel').hidden, focused:document.activeElement?.dataset?.storySelectionId, scrollTop:document.querySelector('#storyBrowser').scrollTop, windowY:window.scrollY, top:document.querySelector('[data-story-selection-id=\"arm-nested-a\"][aria-selected]').getBoundingClientRect().top, summary:document.querySelector('#storyPathSummary').textContent})"
                )
                assert stale["hidden"] is True
                assert stale["focused"] == "arm-nested-a"
                assert stale["summary"] == closed["summary"]
                assert abs(stale["scrollTop"] - closed["scrollTop"]) <= 2
                assert abs(stale["windowY"] - closed["windowY"]) <= 2
                assert abs(stale["top"] - closed["top"]) <= 2

            _SyntheticStoryHandler.delayed_path_selection = None
            _SyntheticStoryHandler.delayed_path_reject = False
            session.evaluate(
                "document.querySelector('[data-story-selection-id=\"arm-bridge\"][aria-selected]').click()"
            )
            session.wait(
                "!document.querySelector('#storyPathPanel').hidden && !document.querySelector('#storyDetailAction').disabled && document.querySelectorAll('#storyPathSteps .story-path-step').length === 4"
            )
            _, _, allowed_errors = driver._browser_diagnostics(
                session, allowed_error_suffixes=("/api/v1/story-map-v2/path",)
            )
            assert allowed_errors == 1
        finally:
            session.close()
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

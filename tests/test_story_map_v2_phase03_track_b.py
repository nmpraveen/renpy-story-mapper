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
NAVIGATION_FIXTURE = ROOT / "tests" / "fixtures" / "story_map_v2_phase03_navigation_envelopes.json"


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
                "reachability": "reachable",
                "warnings": [],
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
                        "warnings": [],
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
                                        "reachability": "reachable",
                                        "warnings": [],
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
                            }
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
        'id="returnToStorySelection"',
        'id="storyAnalysisNotes"',
    ):
        assert marker in html
    assert "story-section" in css and "story-event" in css and "story-arm" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
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
      process.stdout.write(JSON.stringify({{
        status: accepted.status,
        event: accepted.sections[0].events[0].selection_id,
        nested: accepted.sections[0].events[0].choices[0].arms[1].nested_choices[0].key,
        continuation: accepted.sections[0].events[0].choices[0].arms[1].rejoin_binding.selection_id,
        duplicateRejected,
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
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_story_map_path_contract_is_exact_and_deeply_bounded() -> None:
    module_uri = (STATIC / "contract.js").as_uri()
    envelope_contract = json.loads(NAVIGATION_FIXTURE.read_text(encoding="utf-8"))
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
      process.stdout.write(JSON.stringify({{ rejected, total: mutations.length + 1 }}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert json.loads(completed.stdout) == {"rejected": 9, "total": 9}


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

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _json(self, payload: object) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(200)
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
                        "effects": [],
                        "uncertainty": [],
                        "instructions": [
                            {"ordinal": 1, "kind": "scene", "text": "Leave the village."},
                            {"ordinal": 2, "kind": "choice", "text": "Take the tunnel."},
                        ],
                    },
                }
            )
        elif self.path == "/api/v1/story-map-v2/detail":
            selection_id = body["selection_id"]
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
                            "title": "Wait for dawn",
                            "summary": "The travellers wait together.",
                        },
                        "evidence": [],
                    },
                }
            )
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
def test_story_map_v2_real_browser_geometry_and_deep_return(
    profile: str, zoom: int, width: int, height: int
) -> None:
    driver = _browser_driver()
    _SyntheticStoryHandler.story_page = _story_page()
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
                "!document.querySelector('#storyBrowser').hidden && document.querySelectorAll('.story-arm').length === 3"
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
            assert measured["continuations"] == 1
            assert measured["continuationTargets"] == 1
            assert measured["continuationInsideArm"] == 1

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
            session.evaluate(
                "document.querySelector('.story-choice.nested .story-arm-select').click()"
            )
            session.wait(
                "!document.querySelector('#storyPathPanel').hidden && document.querySelectorAll('#storyPathSteps .story-path-step').length === 2 && document.querySelector('.story-choice.nested .story-arm-select').getAttribute('aria-selected') === 'true'"
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
            driver._browser_diagnostics(session)
        finally:
            session.close()
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

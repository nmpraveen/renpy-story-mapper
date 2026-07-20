from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "renpy_story_mapper" / "web" / "static"


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_route_panel_is_retired_inside_the_existing_two_level_workspace() -> None:
    html = _text("index.html")
    app = _text("app.js")

    assert html.count('data-level="') == 2
    assert 'data-level="route_map"' in html
    assert 'data-level="detail_evidence"' in html
    assert 'id="routePanel"' not in html
    assert 'id="solveRoute"' not in html
    assert "How do I reach this?" not in html
    assert "state.route" not in app
    assert "api.solveRoute(" not in app
    assert "api.routeDestinations(" not in app
    assert "state.detailRunToken + 1" in app
    assert "token !== state.detailRunToken" in app
    assert "third" not in html.casefold()


def test_m12_badges_remain_in_compatibility_client_without_visible_panel() -> None:
    api = _text("api.js")
    app = _text("app.js")
    html = _text("index.html")

    for badge in (
        "Confirmed route",
        "Route with prerequisites",
        "Best known route",
        "No proven route",
    ):
        assert badge in api

    assert 'id="recommendedRoute"' not in html
    assert 'id="routeAlternativesSection"' not in html
    assert 'id="routeTechnical"' not in html
    assert "renderRouteCandidate" not in app
    assert "walkthrough" not in (api + app + html).casefold()
    assert ".innerHTML" not in app
    assert "replaceChildren" in app and "textContent" in app


def test_route_client_uses_bootstrap_paths_and_exact_request_shapes() -> None:
    api = _text("api.js")
    app = _text("app.js")

    assert "bootstrap.routes?.m12" in app
    assert 'Object.freeze(["destinations", "solve", "result"])' in api
    assert 'body: { destination_kind: destinationKind, target_id: targetId }' in api
    assert 'body: { request_identity: requestIdentity }' in api
    assert 'this.request(this.m12Path("destinations")' in api
    assert 'this.request(this.m12Path("solve")' in api
    assert 'this.request(this.m12Path("result")' in api
    assert "api.routeDestinations(" not in app
    assert "api.solveRoute(" not in app
    assert "api.routeResult(navigation.request_identity)" in app
    assert '"/api/v1/' not in api


def test_route_lifecycle_controls_are_not_exposed_by_the_normal_website() -> None:
    html = _text("index.html")
    app = _text("app.js")

    for element_id in ("cancelRoute", "retryRoute", "exportRouteJson", "routeStatus"):
        assert f'id="{element_id}"' not in html
    assert "runRouteSolve" not in app
    assert "cancelRouteSolve" not in app
    assert "exportRouteJson" not in app
    assert 'role="status" aria-live="polite"' in html


def test_stable_m12_json_reader_remains_in_the_compatibility_client() -> None:
    api = _text("api.js")
    app = _text("app.js")

    assert "Object.keys(item).sort()" in api
    assert "stableRouteJson" in api
    assert "stableRouteJson" not in app
    assert "api.routeResult(navigation.request_identity)" in app


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required for browser client behavior checks",
)
def test_route_api_behavior_preserves_exact_payloads_and_stable_json() -> None:
    module_uri = (STATIC / "api.js").as_uri()
    script = f"""
      import {{ LocalApi, stableRouteJson }} from {json.dumps(module_uri)};
      const api = new LocalApi({{ session: "session", csrf: "csrf" }});
      api.configureM12({{
        destinations: "/api/v1/m12/destinations",
        solve: "/api/v1/m12/solve",
        result: "/api/v1/m12/result"
      }});
      const calls = [];
      const result = {{
        schema: "m12.route-result.v1", request_identity: "request-1", status: "confirmed",
        badge: "Confirmed route", recommended: {{ instructions: ["Begin"] }}, alternatives: [],
        complete: true, termination_reason: "target_reached", exhaustive: false,
        closed_world: false, budget_usage: {{}}, negative_provenance: null, diagnostics: []
      }};
      api.request = async (path, options) => {{
        calls.push({{ path, method: options.method, body: options.body }});
        if (path.endsWith("destinations")) return {{ nodes: [] }};
        if (path.endsWith("solve")) return {{
          cached: false, request_identity: "request-1", analysis: {{ state: "running" }}
        }};
        return result;
      }};
      await api.routeDestinations("scene-1", 2, 3);
      await api.solveRoute("scene", "scene-1");
      await api.routeResult("request-1");
      process.stdout.write(JSON.stringify({{
        calls, stable: stableRouteJson({{ z: 1, a: {{ y: 2, x: 3 }} }})
      }}));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    payload = json.loads(completed.stdout)

    assert payload["calls"] == [
        {
            "path": "/api/v1/m12/destinations",
            "method": "POST",
            "body": {"query": "scene-1", "offset": 2, "limit": 3},
        },
        {
            "path": "/api/v1/m12/solve",
            "method": "POST",
            "body": {"destination_kind": "scene", "target_id": "scene-1"},
        },
        {
            "path": "/api/v1/m12/result",
            "method": "POST",
            "body": {"request_identity": "request-1"},
        },
    ]
    assert payload["stable"] == '{\n  "a": {\n    "x": 3,\n    "y": 2\n  },\n  "z": 1\n}\n'

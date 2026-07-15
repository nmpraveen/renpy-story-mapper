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


def test_route_panel_stays_inside_the_existing_two_level_workspace() -> None:
    html = _text("index.html")
    app = _text("app.js")

    assert html.count('data-level="') == 2
    assert 'data-level="route_map"' in html
    assert 'data-level="detail_evidence"' in html
    assert 'id="routePanel"' in html
    assert 'id="solveRoute"' in html
    assert ">How do I reach this?</button>" in html
    assert 'id="openRouteEvidence"' in html
    assert ">Open Detail / Evidence</button>" in html
    assert "state.route.activeSourceId" in app
    assert "candidate?.selected_occurrence_id" in app
    assert "third" not in html.casefold()


def test_route_panel_has_exact_badges_and_separated_deterministic_sections() -> None:
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

    for heading in (
        "Instructions",
        "Starting assumptions",
        "Ordered human scenes",
        "Visible choices",
        "Repeated actions",
        "Requirements",
        "Earlier satisfying effects",
        "Persistent commitments",
        "Uncertainty warnings",
    ):
        assert heading in app

    assert 'id="recommendedRoute"' in html
    assert 'id="routeAlternativesSection"' in html
    assert 'id="routeTechnical"' in html
    assert "renderRouteCandidate" in app
    assert "selected_occurrence_id" in app
    assert "Provenance and evidence" in app
    assert "satisfying_effect_id" in app
    assert "item?.source" in app
    assert 'element("details", "route-claim")' in app
    for claim_collection in (
        "scene_claims",
        "visible_choice_claims",
        "repeated_action_claims",
        "persistent_commitment_claims",
        "uncertainty_claims",
    ):
        assert claim_collection in app
    assert "stableRouteJson(value)" in app
    assert "result.negative_provenance" in app
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
    assert "api.routeDestinations(source.id, 0, ROUTE_PAGE_SIZE)" in app
    assert "api.solveRoute(destination.kind, destination.target_id)" in app
    assert "api.routeResult(response.request_identity)" in app
    assert '"/api/v1/' not in api


def test_route_lifecycle_exposes_cancel_retry_cache_stale_and_failure_states() -> None:
    html = _text("index.html")
    app = _text("app.js")

    for element_id in ("cancelRoute", "retryRoute", "exportRouteJson", "routeStatus"):
        assert f'id="{element_id}"' in html
    assert "await api.cancelAnalysis()" in app
    assert 'while (["pending", "running", "cancelling"].includes(task.state))' in app
    assert "await waitForRouteTask(cancelling, state.route.runToken)" in app
    assert 'state.route.phase = "cancelled"' in app
    assert 'state.route.phase = state.route.stale ? "stale" : "complete"' in app
    assert 'route.cached ? "Cached route ready."' in app
    assert 'route.phase = stale ? "stale" : "failure"' in app
    assert 'error.status === 409' not in app
    assert "Search incomplete. No reachability or infeasibility conclusion was published." in app
    assert "state.route.result = result" in app
    assert "Boolean(state.route.result)" in app
    assert 'role="status" aria-live="polite"' in html


def test_json_export_is_stable_bounded_to_the_normalized_result_and_path_safe() -> None:
    api = _text("api.js")
    app = _text("app.js")

    assert "Object.keys(item).sort()" in api
    assert "stableRouteJson(result)" in app
    assert "new Blob" in app
    assert 'type: "application/json;charset=utf-8"' in app
    assert "URL.createObjectURL" in app and "URL.revokeObjectURL" in app
    assert "replace(/[^a-z0-9._-]+/gi" in app
    assert "result.request_identity" in app


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

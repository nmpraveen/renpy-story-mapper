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


def test_narrative_is_an_optional_overlay_inside_the_existing_two_levels() -> None:
    html = _text("index.html")
    app = _text("app.js")

    assert html.count('data-level="') == 2
    assert 'id="narrativeToggle"' in html
    assert 'id="narrativeDrawer"' in html
    assert 'id="narrativeCoverage"' in html
    assert 'id="narrativeJobList"' in html
    assert 'id="narrativeRunForm"' in html
    assert 'id="narrativeConsentDialog"' in html
    assert 'id="narrativeModel"' in html
    assert 'id="narrativeMode"' in html
    assert 'id="narrativeIncludeM12"' in html
    assert "narrativeEnabled: false" in app
    assert 'state.mode === "scenes" && state.narrativeEnabled' in app
    assert "deterministic_title: node.title" in app
    assert "deterministic_summary: node.summary" in app
    assert "M10 facts, M11 structure, and M12 route results remain authoritative" in html
    assert "Cloud AI is disabled" in html
    assert ".innerHTML" not in app


def test_narrative_detail_separates_claim_classes_and_loads_citations_lazily() -> None:
    app = _text("app.js")
    styles = _text("styles.css")

    assert 'claim.claim_class === "factual"' in app
    assert 'claim.claim_class === "interpretive"' in app
    assert "Review suggestion" in app
    assert 'api.narrativeCitations(claim.claim_id)' in app
    assert "Show citations" in app
    assert "deterministic authority unchanged" in app
    assert "AI interpretation; deterministic authority unchanged" in app
    assert "Route-aware structure" in app
    assert "Persistent route" in app
    assert "Temporary branch" in app
    assert "Unresolved or missing coverage" in app
    assert "narrativeArtifact.warnings" in app
    assert '[data-claim-class="interpretive"]' in styles
    assert '[data-claim-class="review_suggestion"]' in styles


def test_narrative_client_contracts_are_bounded_and_consent_gated() -> None:
    api = _text("api.js")
    contract = _text("contract.js")

    assert 'narrativeSnapshot: "/api/v1/m13/snapshot"' in contract
    assert 'narrativeArtifact: "/api/v1/m13/artifact"' in contract
    assert 'narrativeCitations: "/api/v1/m13/citations"' in contract
    assert 'narrativePrepare: "/api/v1/m13/prepare"' in contract
    assert 'narrativeStart: "/api/v1/m13/start"' in contract
    assert 'narrativeStatus: "/api/v1/m13/status"' in contract
    assert 'narrativeCancel: "/api/v1/m13/cancel"' in contract
    assert "value.jobs.length > 200" in contract
    assert "value.claims.length > 256" in contract
    assert "value.citations.length > 60" in contract
    assert 'body: { offset, limit }' in api
    assert 'body: { artifact_id: artifactId }' in api
    assert 'body: { claim_id: claimId }' in api
    assert "confirm_cloud: true" in api
    assert "Cost limiting is unavailable" in api
    assert "requested_model" in api
    assert "resolved_model" in contract
    assert "raw_prompt" not in api
    assert "provider_response" not in api


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required for browser client behavior checks",
)
def test_narrative_api_behavior_preserves_exact_request_shapes_and_limits() -> None:
    module_uri = (STATIC / "api.js").as_uri()
    script = f"""
      import {{ LocalApi }} from {json.dumps(module_uri)};
      const api = new LocalApi({{ session: "session", csrf: "csrf" }});
      const calls = [];
      const hash = "a".repeat(64);
      api.request = async (path, options) => {{
        calls.push({{ path, body: options.body }});
        if (path.endsWith("snapshot")) return {{
          schema: "m13-narrative-snapshot-v1", status: "available",
          authority_hash: hash, cloud_enabled: false, jobs: [], offset: 0,
          limit: 200, total: 0, next_offset: null, state_counts: {{}},
          coverage: {{ expected_scene_jobs: 0, published_scene_jobs: 0,
            scene_coverage_basis_points: 10000, stale_jobs: 0,
            unavailable_jobs: 0, m12_selected_results: 0,
            m12_stale_results: 0, m12_invalid_results: 0 }}
        }};
        if (path.endsWith("artifact")) return {{
          schema: "m13-narrative-artifact-detail-v1", status: "available",
          authority_hash: hash, artifact_id: "artifact-a", logical_job_id: "job-a",
          kind: "scene", publication: "complete", title: "Title",
          title_class: "interpretive", summary: "Summary", summary_class: "interpretive",
          claims: [], coverage: {{}}, warnings: [], used_deterministic_title: false
        }};
        if (path.endsWith("citations")) return {{
          schema: "m13-narrative-claim-citations-v1", status: "available",
          authority_hash: hash, claim_id: "claim-a", traversed_claim_ids: ["claim-a"],
          maximum_depth: 0, citations: [] }};
        if (path.endsWith("prepare")) return {{
          schema: "m13-run-preparation-v1", preparation_id: "prep-a", run_id: "run-a",
          authority_hash: hash, provider: {{ provider: "cloud", adapter: "adapter",
            adapter_version: "v1", requested_model: "runtime-model",
            resolved_model: "runtime-model", settings: {{}} }},
          provider_available: true, provider_cli_version: "1", provider_message_code: null,
          selected_scope_ids: ["project:all-current-scenes"], privacy_mode: "fact_only",
          includes_m12_material: true, estimate: {{ logical_job_count: 10,
            provider_call_count: 4, input_tokens: 100, output_tokens: 50,
            estimated_cost_micros: null, cost_confidence: "unavailable" }},
          limits: {{ max_provider_calls: 20, max_input_tokens: 1000,
            max_output_tokens: 500, max_total_tokens: 1500, timeout_seconds: 60,
            max_concurrency: 2, max_cost_micros: null }}, consent_granted: false,
          requires_confirm_cloud: true, selected_scene_count: 3, cloud_enabled: false
        }};
        return {{ schema: "m13-run-status-v1",
          state: path.endsWith("start") ? "running" : "cancelled",
          cloud_enabled: path.endsWith("start"),
          provider_transmission_active: path.endsWith("start"),
          preparation: null, task: null, latest_run: null, artifacts: null,
          unresolved_codes: [], durable_completed_work_preserved: true }};
      }};
      await api.narrativeSnapshot(0, 200);
      await api.narrativeArtifact("artifact-a");
      await api.narrativeCitations("claim-a");
      const options = {{ requested_model: "runtime-model", mode: "fact_only",
        include_m12_material: true,
        limits: {{ max_provider_calls: 20, max_input_tokens: 1000,
          max_output_tokens: 500, max_total_tokens: 1500, timeout_seconds: 60,
          max_concurrency: 2, max_cost_micros: null }},
        batch_limits: {{ maximum_items: 8, maximum_input_chars: 10000,
          maximum_input_tokens: 2000 }} }};
      await api.prepareNarrative(options);
      await api.startNarrative("prep-a");
      await api.narrativeStatus();
      await api.cancelNarrative();
      process.stdout.write(JSON.stringify(calls));
    """
    completed = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    calls = json.loads(completed.stdout)
    assert calls == [
        {"path": "/api/v1/m13/snapshot", "body": {"offset": 0, "limit": 200}},
        {"path": "/api/v1/m13/artifact", "body": {"artifact_id": "artifact-a"}},
        {"path": "/api/v1/m13/citations", "body": {"claim_id": "claim-a"}},
        {"path": "/api/v1/m13/prepare", "body": {
            "requested_model": "runtime-model", "mode": "fact_only",
            "include_m12_material": True,
            "limits": {"max_provider_calls": 20, "max_input_tokens": 1000,
                       "max_output_tokens": 500, "max_total_tokens": 1500,
                       "timeout_seconds": 60, "max_concurrency": 2,
                       "max_cost_micros": None},
            "batch_limits": {"maximum_items": 8, "maximum_input_chars": 10000,
                             "maximum_input_tokens": 2000},
        }},
        {"path": "/api/v1/m13/start", "body": {"preparation_id": "prep-a", "confirm_cloud": True}},
        {"path": "/api/v1/m13/status", "body": {}},
        {"path": "/api/v1/m13/cancel", "body": {}},
    ]

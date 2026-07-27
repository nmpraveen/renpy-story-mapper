from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "m15_phase04_scale_acceptance.py"
PROFILE = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_scale_profile_v1.json"
HARNESS_HTML = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_scale_harness.html"
HARNESS_JS = ROOT / "tests" / "fixtures" / "story_map_v2" / "phase04_scale_harness.js"


def _module() -> object:
    spec = importlib.util.spec_from_file_location("m15_phase04_scale_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_scale_fixture_meets_structural_and_v2_cursor_contracts() -> None:
    module = _module()
    dataset = module.ScaleDataset()
    structural = module._structural_evidence(dataset)

    assert structural["counts"] == {
        "events": 5000,
        "choices": 5000,
        "arms": 20300,
        "rejoins": 2000,
        "sections": 256,
    }
    assert structural["persistent_route_sections"] == 50
    assert structural["maximum_nesting_depth"] == 8
    assert structural["oversized_branch_items"] == 304
    assert structural["oversized_branch_pages"] == [240, 64]
    assert structural["cross_section_rejoin"] == "event:400"
    assert structural["final_section_target"] == "event:4999"
    assert structural["v2_unloaded_branch_id"] == "choice:0"
    assert structural["v2_unloaded_branch_cursor"] is True

    nested = dataset.branch_page({"map_revision": 7, "branch_id": "choice:0", "limit": 240})[
        "shells"
    ][:8]
    assert [shell["parent_shell_id"] for shell in nested] == [
        "shell:choice:0",
        "shell:arm:0",
        "shell:arm:1",
        "shell:arm:2",
        "shell:arm:3",
        "shell:arm:4",
        "shell:arm:5",
        "shell:arm:6",
    ]

    located = dataset.locate({"map_revision": 7, "selection_id": "arm:303"})
    assert located["schema"] == "story-map-v2-reader-contract-v2"
    assert located["location"]["branch_id"] == "choice:0"
    assert located["location"]["page_cursor"]
    branch = dataset.branch_page(
        {
            "map_revision": 7,
            "branch_id": located["location"]["branch_id"],
            "cursor": located["location"]["page_cursor"],
            "limit": 240,
        }
    )
    assert branch["items"][-1]["selection_id"] == "arm:303"
    assert branch["items"][-1]["is_new"] is True
    assert len(json.dumps(branch).encode()) < 1_048_576
    uncached = dataset.path_page({"map_revision": 7, "selection_id": "event:4999", "limit": 240})
    cached = dataset.path_page({"map_revision": 7, "selection_id": "event:4999", "limit": 240})
    assert uncached["cache_state"] == "miss"
    assert cached["cache_state"] == "hit"

    with pytest.raises(module.InvalidCursor):
        dataset.branch_page(
            {
                "map_revision": 7,
                "branch_id": "choice:0",
                "cursor": f"{located['location']['page_cursor']}x",
                "limit": 240,
            }
        )
    dataset.refresh()
    with pytest.raises(module.StaleRevision):
        dataset.section_page({"map_revision": 7, "section_id": "section:0", "limit": 30})


def test_scale_harness_is_local_bounded_and_uses_opaque_v2_branch_location() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    html = HARNESS_HTML.read_text(encoding="utf-8")
    javascript = HARNESS_JS.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")

    assert profile["reader_schema"] == "story-map-v2-reader-contract-v2"
    assert profile["profiles"] == [
        {"id": "desktop-100", "width": 1440, "height": 900, "device_scale_factor": 1},
        {"id": "desktop-200", "width": 720, "height": 450, "device_scale_factor": 2},
        {"id": "narrow", "width": 390, "height": 844, "device_scale_factor": 1},
    ]
    assert profile["bounds"] == {
        "manifest_cold_p95_ms": 1500,
        "manifest_warm_p95_ms": 500,
        "usable_overview_cold_ms": 4000,
        "usable_overview_warm_ms": 2000,
        "section_or_locator_p95_ms": 500,
        "search_p95_ms": 750,
        "cached_path_p95_ms": 1000,
        "uncached_path_p95_ms": 5000,
        "live_story_nodes": 600,
        "browser_memory_bytes": 262144000,
        "browser_memory_growth_100_jumps_bytes": 20971520,
        "repeated_distant_jumps": 100,
        "page_bytes": 1048576,
        "rendered_items_per_page": 240,
    }
    assert "<canvas" not in html.casefold()
    assert "http://" not in html and "https://" not in html
    assert "innerHTML" not in javascript and "eval(" not in javascript
    assert "if (location.branch_id !== null)" in javascript
    assert "openBranch(location.branch_id, location.page_cursor)" in javascript
    assert "selectionId.split" not in javascript
    assert "shell_id.split" not in javascript
    assert "live_story_items" in javascript
    for marker in (
        "Performance.getMetrics",
        "Network.requestWillBeSent",
        "window.phase04Harness.tamperCursor()",
        "window.phase04Harness.locateSelection('arm:303')",
        "window.phase04Harness.openPath('event:4999')",
        "window.phase04Harness.jumpDistantSections(100)",
        "HeapProfiler.collectGarbage",
        "manifest_cold_p95_ms",
        "process_rss_before_dataset_bytes",
        "window.phase04Harness.openDetail('event:4999')",
        "window.phase04Harness.reopen()",
        "window.phase04Harness.refresh()",
        "document.querySelector('#freshness').dataset.freshness === 'stale'",
    ):
        assert marker in script


@pytest.mark.skipif(
    os.environ.get("RSM_RUN_M15_PHASE04_BROWSER") != "1",
    reason="set RSM_RUN_M15_PHASE04_BROWSER=1 for the real Chrome scale matrix",
)
def test_real_browser_scale_matrix(tmp_path: Path) -> None:
    module = _module()
    report = module.run(tmp_path / "phase04-scale")
    assert report["status"] == "passed"
    assert report["reader_schema"] == "story-map-v2-reader-contract-v2"
    assert report["schema"] == "story-map-v2-phase04-scale-acceptance-v2"
    assert [item["profile"] for item in report["profiles"]] == [
        "desktop-100",
        "desktop-200",
        "narrow",
    ]
    assert report["api_performance"]["manifest_cold_p95_ms"] <= 1500
    assert report["api_performance"]["manifest_warm_p95_ms"] <= 500
    assert report["api_performance"]["section_p95_ms"] < 500
    assert report["api_performance"]["locator_p95_ms"] < 500
    assert report["api_performance"]["search_p95_ms"] < 750
    assert report["api_performance"]["cached_path_p95_ms"] < 1000
    assert report["api_performance"]["uncached_path_p95_ms"] < 5000
    assert report["api_performance"]["maximum_api_response_bytes"] <= 1_048_576
    assert report["api_performance"]["maximum_rendered_items"] <= 240
    assert report["python_memory"]["approved_numeric_bound"] is None
    for capture in report["profiles"]:
        assert capture["usable_overview_cold_ms"] < 4000
        assert capture["usable_overview_warm_ms"] < 2000
        assert capture["uncached_path_progress_visible"] is True
        assert capture["uncached_path_ms"] < 5000
        assert capture["cached_path_ms"] < 1000
        assert capture["live_story_nodes"] < 600
        assert capture["js_heap_used_bytes"] < 262_144_000
        assert capture["distant_jumps"] == 100
        assert capture["js_heap_growth_after_100_jumps_bytes"] < 20_971_520

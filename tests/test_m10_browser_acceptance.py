from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "m10_browser_acceptance.py"


def test_real_browser_harness_covers_hardened_m10_workflows() -> None:
    source = HARNESS.read_text(encoding="utf-8")
    for marker in (
        "LocalWebServer",
        "ProjectApi",
        "create_ingested_project",
        "refresh_ingested_project",
        "forbidden_provider",
        "injected M10 browser route projection failure",
        "injected M10 browser simplified projection failure",
        "injected M10 browser control-flow failure",
        "#analysisFailureBanner",
        "last_known_good",
        "Showing last-known-good results",
        "m10-default-{zoom}.png",
        "m10-suppressed-canonical-{zoom}.png",
        "m10-whole-graph-search-{zoom}.png",
        "m10-direct-proof-detail-{zoom}.png",
        "m10-opaque-status-{zoom}.png",
        "m10-retained-failure-{zoom}.png",
        "m10-canonical-only-{zoom}.png",
        "m10-bounded-partial-analysis-{zoom}.png",
        "Network.requestWillBeSent",
        "#linkedRecords .linked-record",
        "Unsupported creator Python · preserved, not executed",
        "--force-device-scale-factor=2",
        "offenders",
        "canonical_only_captures",
        "partial_analysis_captures",
    ):
        assert marker in source

    spec = importlib.util.spec_from_file_location("m10_browser_acceptance", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ZOOMS == (100, 200)
    assert module.VIEWPORTS == {100: (1440, 900), 200: (720, 450)}
    assert module.SEARCH_TARGET == "Scene 44 unique text."
    assert module.SUPPRESSED_SEARCH_TARGET == "label dynamic_dispatch:"

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from scripts.m13_provider_free_acceptance import SimulatedNarrativeProvider

SCRIPT = Path(__file__).parents[1] / "scripts" / "m13_live_acceptance.py"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("rsm_m13_live_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_acceptance_preview_never_submits_and_exact_confirmation_replays(
    tmp_path: Path,
) -> None:
    module = _module()
    output = tmp_path / "live"
    provider = SimulatedNarrativeProvider(content_variant="live-acceptance")

    preview = module.run(output, model="selected-runtime-model", provider=provider)

    assert preview["phase"] == "awaiting_exact_confirmation"
    assert preview["provider_submit_calls"] == 0
    assert provider.call_item_counts == []
    assert preview["privacy_mode"] == "fact_only"
    assert preview["includes_m12_material"] is True
    assert preview["representative_contexts"]["persistent_route_scenes"] > 0
    assert (output / "consent-preview.json").is_file()
    assert not (output / "acceptance.json").exists()

    report = module.run(
        output,
        model="selected-runtime-model",
        confirm_preparation_id=preview["preparation_id"],
        provider=provider,
    )

    assert report["status"] == "passed"
    assert report["first_run"]["state"] == "succeeded"
    assert report["cache_replay"]["provider_calls"] == 0
    assert report["claim_and_route_audit"]["route_aware_plot"] is True
    assert report["privacy"]["raw_prompt_records"] == 0
    assert report["immutability"]["unchanged"] is True
    assert (output / "acceptance.json").is_file()


def test_live_acceptance_rejects_stale_confirmation_without_submitting(tmp_path: Path) -> None:
    module = _module()
    provider = SimulatedNarrativeProvider()

    try:
        module.run(
            tmp_path / "live",
            model="selected-runtime-model",
            confirm_preparation_id="m13_preparation_stale",
            provider=provider,
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("stale live confirmation was accepted")
    assert provider.call_item_counts == []

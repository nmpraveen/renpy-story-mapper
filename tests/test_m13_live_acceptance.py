from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from scripts.m13_provider_free_acceptance import SimulatedNarrativeProvider

SCRIPT = Path(__file__).parents[1] / "scripts" / "m13_live_acceptance.py"


class SettingsEchoingProvider(SimulatedNarrativeProvider):
    def submit(self, request: Any, cancelled: Any) -> Any:
        response = super().submit(request, cancelled)
        return replace(
            response,
            provider=replace(response.provider, settings=request.settings),
        )


class TwoPartialScenesProvider(SettingsEchoingProvider):
    def __init__(self) -> None:
        super().__init__(content_variant="two-partial-scenes")
        self.partial_scene_ids: set[str] = set()

    def submit(self, request: Any, cancelled: Any) -> Any:
        response = super().submit(request, cancelled)
        revised = []
        for request_item, response_item in zip(request.items, response.items, strict=True):
            payload = response_item.payload
            if (
                len(self.partial_scene_ids) < 2
                and request_item.payload.get("job_kind") == "scene"
                and payload is not None
            ):
                self.partial_scene_ids.add(request_item.logical_job_id)
                payload = dict(payload)
                claims = list(payload["claims"])
                claims.append(
                    {
                        "claim_class": "factual",
                        "context_scope": "atomic",
                        "text": "This deliberately invalid claim is salvaged away.",
                        "evidence_handles": ["E999"],
                        "child_claim_handles": [],
                        "subject": "scene",
                        "predicate": "invalid test support",
                        "polarity": "positive",
                        "normalized_value": "invalid",
                    }
                )
                payload["claims"] = claims
                response_item = replace(response_item, payload=payload)
            revised.append(response_item)
        return replace(response, items=tuple(revised))


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("rsm_m13_live_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_acceptance_uses_finite_long_timeout_and_no_retry_policy() -> None:
    module = _module()
    policy = module.LIVE_SCHEDULER_POLICY

    assert module.LIVE_TIMEOUT_SECONDS == 7_200
    assert policy.maximum_attempts_per_job == 1
    assert policy.maximum_transient_attempts_per_job == 1
    assert policy.maximum_malformed_attempts_per_job == 1


def test_live_acceptance_preview_never_submits_and_exact_confirmation_replays(
    tmp_path: Path,
) -> None:
    module = _module()
    output = tmp_path / "live"
    provider = SettingsEchoingProvider(content_variant="live-acceptance")

    preview = module.run(
        output,
        model="selected-runtime-model",
        reasoning_effort="selected-runtime-effort",
        provider=provider,
    )

    assert preview["phase"] == "awaiting_exact_confirmation"
    assert preview["provider_submit_calls"] == 0
    assert provider.call_item_counts == []
    assert preview["privacy_mode"] == "fact_only"
    assert preview["includes_m12_material"] is True
    assert preview["provider"]["settings"] == {
        "fast_mode": False,
        "model_reasoning_effort": "selected-runtime-effort",
    }
    assert preview["representative_contexts"]["persistent_route_scenes"] > 0
    assert preview["estimate"]["input_tokens"] > 2_460_000
    assert preview["batch_limits"] == {
        "maximum_items": 16,
        "maximum_input_chars": 500_000,
        "maximum_input_tokens": 120_000,
    }
    assert preview["limits"] == {
        "max_provider_calls": 148,
        "max_input_tokens": 7_401_250,
        "max_output_tokens": 163_200,
        "max_total_tokens": 7_564_450,
        "timeout_seconds": 7_200,
        "max_concurrency": 1,
        "max_cost_micros": None,
    }
    assert (output / "consent-preview.json").is_file()
    assert not (output / "acceptance.json").exists()

    report = module.run(
        output,
        model="selected-runtime-model",
        reasoning_effort="selected-runtime-effort",
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


def test_live_acceptance_retains_two_partial_scenes_and_replays_without_calls(
    tmp_path: Path,
) -> None:
    module = _module()
    output = tmp_path / "live-partial"
    provider = TwoPartialScenesProvider()
    preview = module.run(
        output,
        model="selected-runtime-model",
        reasoning_effort="selected-runtime-effort",
        provider=provider,
    )

    report = module.run(
        output,
        model="selected-runtime-model",
        reasoning_effort="selected-runtime-effort",
        confirm_preparation_id=preview["preparation_id"],
        provider=provider,
    )

    assert len(provider.partial_scene_ids) == 2
    assert report["status"] == "passed"
    assert report["first_run"]["state"] == "partial"
    assert report["first_run"]["state_counts"]["partial"] == 2
    assert report["first_run"]["segment_artifacts"] > 0
    assert report["first_run"]["chapter_artifacts"] > 0
    assert report["claim_and_route_audit"]["route_aware_plot"] is True
    assert report["cache_replay"]["provider_calls"] == 0


def test_live_acceptance_rejects_stale_confirmation_without_submitting(tmp_path: Path) -> None:
    module = _module()
    provider = SettingsEchoingProvider()

    try:
        module.run(
            tmp_path / "live",
            model="selected-runtime-model",
            reasoning_effort="selected-runtime-effort",
            confirm_preparation_id="m13_preparation_stale",
            provider=provider,
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("stale live confirmation was accepted")
    assert provider.call_item_counts == []


def test_live_acceptance_rejects_reasoning_setting_drift_without_submitting(
    tmp_path: Path,
) -> None:
    module = _module()
    provider = SettingsEchoingProvider()
    preview = module.run(
        tmp_path / "first",
        model="selected-runtime-model",
        reasoning_effort="runtime-effort-a",
        provider=provider,
    )

    try:
        module.run(
            tmp_path / "second",
            model="selected-runtime-model",
            reasoning_effort="runtime-effort-b",
            confirm_preparation_id=preview["preparation_id"],
            provider=provider,
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("changed runtime settings reused stale live consent")
    assert provider.call_item_counts == []

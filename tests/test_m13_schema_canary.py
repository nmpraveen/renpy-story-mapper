from __future__ import annotations

import json
from typing import NoReturn

import pytest
import scripts.m13_schema_canary as canary

from renpy_story_mapper.narrative.provider import ADAPTER_VERSION, RESPONSE_SCHEMA_VERSION


def test_schema_canary_is_one_public_synthetic_job_with_exact_settings() -> None:
    request = canary.build_canary_request("runtime-model", "high")

    assert request.requested_model == "runtime-model"
    assert request.settings.to_dict() == {
        "fast_mode": False,
        "model_reasoning_effort": "high",
    }
    assert len(request.items) == 1
    assert request.items[0].logical_job_id == "public-synthetic-schema-canary"
    assert request.items[0].payload["public_synthetic"] is True
    serialized = json.dumps(request.items[0].payload, sort_keys=True)
    assert "story" not in serialized.casefold()
    assert RESPONSE_SCHEMA_VERSION.endswith("response-v3")
    assert ADAPTER_VERSION.endswith("adapter-v3")


def test_schema_canary_preview_makes_no_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_provider() -> NoReturn:
        raise AssertionError("preview instantiated a provider")

    monkeypatch.setattr(canary, "CodexCliNarrativeProvider", forbidden_provider)

    assert canary.main(["--model", "runtime-model", "--reasoning-effort", "xhigh"]) == 0

    preview = json.loads(capsys.readouterr().out)
    assert preview["provider_calls"] == 0
    assert preview["public_synthetic"] is True
    assert preview["response_schema_version"] == RESPONSE_SCHEMA_VERSION
    assert preview["adapter_version"] == ADAPTER_VERSION

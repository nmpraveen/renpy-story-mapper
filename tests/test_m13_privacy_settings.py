from __future__ import annotations

import pytest

from renpy_story_mapper.narrative.contracts import ProviderSettings
from renpy_story_mapper.narrative.privacy import validate_privacy_safe_keys
from renpy_story_mapper.narrative.provider import (
    ProviderRuntimeConfigurationError,
    validate_codex_provider_settings,
)


@pytest.mark.parametrize(
    "key",
    [
        "openai_api_key",
        "providerAccessToken",
        "authorization-header",
        "complete_prompt_payload",
        "promptPayload",
        "raw_provider_response_blob",
        "source_text_packet",
        "OpenAI.API-KEY",
        "provider.ACCESS-token",
        "AUTHORIZATION.Header",
        "Complete-PROMPT.Payload",
        "RAW.Provider-Response.Blob",
        "SOURCE.Text-PACKET",
        "authenticationToken",
        "apiToken",
        "bearer-token",
        "clientSecret",
        "credential_secret",
        "refresh_token",
        "session.token",
        "userPassword",
        "privateKeyPem",
        "provider_response",
        "rawProviderOutputBlob",
        "sourcePacket",
    ],
)
def test_sensitive_compound_keys_are_rejected_everywhere(key: str) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        ProviderSettings(((key, "must-not-persist"),))
    with pytest.raises(ValueError, match="sensitive"):
        validate_privacy_safe_keys({"safe": [{key: "must-not-persist"}]})


@pytest.mark.parametrize(
    "key",
    [
        "secret_scene_id",
        "route_token_count",
        "token_budget",
        "prompt_version",
        "source_text_omitted_count",
    ],
)
def test_semantically_safe_near_miss_keys_are_allowed(key: str) -> None:
    settings = ProviderSettings(((key, "safe-metadata"),))
    validate_privacy_safe_keys({key: "safe-metadata"})
    assert settings.to_dict() == {key: "safe-metadata"}


def test_codex_adapter_keeps_a_strict_allowlist_after_shared_privacy_validation() -> None:
    settings = ProviderSettings((("secret_scene_id", "scene-a"),))

    with pytest.raises(ProviderRuntimeConfigurationError) as error:
        validate_codex_provider_settings(settings)

    assert error.value.error_code == "runtime_configuration_rejected"


def test_explicit_development_raw_content_exception_never_allows_credentials() -> None:
    validate_privacy_safe_keys(
        {"complete_prompt_payload": "bounded-development-data"},
        allow_raw_content=True,
    )
    with pytest.raises(ValueError, match="sensitive"):
        validate_privacy_safe_keys(
            {"providerAccessToken": "credential"},
            allow_raw_content=True,
        )

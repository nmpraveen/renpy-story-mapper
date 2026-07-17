from __future__ import annotations

from pathlib import Path

import pytest

from renpy_story_mapper.narrative.contracts import ProviderSettings
from renpy_story_mapper.narrative.persistence import (
    RECORD_COLLECTIONS,
    M13Persistence,
    RecordKind,
)
from renpy_story_mapper.narrative.privacy import validate_privacy_safe_keys
from renpy_story_mapper.narrative.provider import (
    ProviderRuntimeConfigurationError,
    validate_codex_provider_settings,
)
from renpy_story_mapper.project import Project


def _authority() -> dict[str, object]:
    return {
        "m10": {"graph_hash": "a" * 64, "generation": 7, "schema": "m10-v1"},
        "m11": {"model_hash": "b" * 64, "correction_hash": "c" * 64},
        "m12": {"result_hashes": ["d" * 64]},
    }


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
        "secret_key",
        "secretKey",
        "secret-key",
        "nested_secret_key",
        "nestedSecretKey",
        "nested-secret-key",
        "secret_value",
        "secretValue",
        "secret-value",
        "token_value",
        "tokenValue",
        "token-value",
        "nested_token_value",
        "nestedTokenValue",
        "nested-token-value",
        "openai_api_key",
        "openaiApiKey",
        "openai-api-key",
        "provider_access_token",
        "providerAccessToken",
        "provider-access-token",
    ],
)
def test_required_normalized_credential_aliases_are_rejected_recursively(key: str) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        ProviderSettings(((key, "must-not-persist"),))
    with pytest.raises(ValueError, match="sensitive"):
        validate_privacy_safe_keys(
            {"outer": [{"middle": ({key: "must-not-persist"},)}]}
        )


@pytest.mark.parametrize(
    "key",
    [
        "secret_scene_id",
        "input_tokens",
        "output_token_count",
        "route_token_count",
        "token_budget",
        "token_budgets",
        "tokenBudgets",
        "token-budgets",
        "prompt_version",
        "prompt_hash",
        "promptID",
        "source_text_omitted_count",
        "tokenizer_version",
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


@pytest.mark.parametrize(
    "key",
    [
        "secret_key",
        "secretValue",
        "token_value",
        "openai_api_key",
        "providerAccessToken",
        "nested-secret-key",
        "nestedTokenValue",
    ],
)
def test_every_m13_record_boundary_uses_the_shared_sensitive_key_validator(
    tmp_path: Path,
    key: str,
) -> None:
    with Project.create(tmp_path / f"privacy-{key}.rsmproj") as project:
        persistence = M13Persistence(project)
        for kind in RecordKind:
            with pytest.raises(ValueError, match="sensitive"):
                persistence.put(
                    kind,
                    f"record:{kind.value}",
                    {"outer": [{"middle": {key: "must-not-persist"}}]},
                    authority_binding=_authority(),
                )
            assert project.payload_keys(RECORD_COLLECTIONS[kind]) == ()


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

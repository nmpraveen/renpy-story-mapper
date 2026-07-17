"""Shared M13 sensitive-key validation for settings and durable payload preflight."""

from __future__ import annotations

import re
from collections.abc import Mapping

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")

_SENSITIVE_COMPOUNDS = (
    "apikey",
    "apitoken",
    "accesstoken",
    "authtoken",
    "authenticationtoken",
    "authorization",
    "bearertoken",
    "clientsecret",
    "credential",
    "idtoken",
    "oauthsecret",
    "password",
    "privatekey",
    "refreshtoken",
    "sessiontoken",
    "credentialsecret",
)
_PROMPT_CONTENT_WORDS = frozenset(
    {
        "body",
        "complete",
        "content",
        "full",
        "input",
        "output",
        "payload",
        "raw",
        "rendered",
        "request",
        "text",
    }
)
_PROMPT_METADATA_WORDS = frozenset(
    {
        "count",
        "hash",
        "id",
        "identifier",
        "ordinal",
        "prompt",
        "schema",
        "template",
        "version",
    }
)


def _key_words(key: str) -> tuple[str, ...]:
    expanded = _CAMEL_BOUNDARY.sub(" ", key)
    return tuple(part.casefold() for part in _NON_ALNUM.split(expanded) if part)


def _sensitive_key_kind(key: str) -> str | None:
    words = _key_words(key)
    joined = "".join(words)
    if joined in {"secret", "token"}:
        return "credential"
    if any(compound in joined for compound in _SENSITIVE_COMPOUNDS):
        return "credential"
    if "prompt" in words or "prompts" in words or "prompt" in joined:
        singular = tuple("prompt" if word == "prompts" else word for word in words)
        if joined in {"prompt", "prompts"}:
            return "raw"
        if any(word in _PROMPT_CONTENT_WORDS for word in singular):
            return "raw"
        if any(word not in _PROMPT_METADATA_WORDS for word in singular):
            return "raw"
    if any(
        marker in joined
        for marker in (
            "providerresponse",
            "rawprovideroutput",
            "rawresponse",
            "responsepayload",
        )
    ):
        return "raw"
    if joined in {"response", "responses"}:
        return "raw"
    if joined == "sourcetext" or "sourcepacket" in joined or "sourcetextpacket" in joined:
        return "raw"
    return None


def validate_privacy_safe_key(
    key: str,
    *,
    label: str = "payload",
    allow_raw_content: bool = False,
) -> None:
    """Reject one credential-bearing or raw-content key after semantic normalization."""

    if not key or not key.isprintable():
        raise ValueError(f"{label} keys must be non-empty printable strings")
    kind = _sensitive_key_kind(key)
    if kind == "credential" or (kind == "raw" and not allow_raw_content):
        raise ValueError(f"{label} contains a sensitive or raw-content key")


def validate_privacy_safe_keys(
    value: object,
    *,
    label: str = "payload",
    allow_raw_content: bool = False,
) -> None:
    """Recursively validate mapping keys before an M13 persistence write."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label} keys must be strings")
            validate_privacy_safe_key(
                key,
                label=label,
                allow_raw_content=allow_raw_content,
            )
            validate_privacy_safe_keys(
                item,
                label=label,
                allow_raw_content=allow_raw_content,
            )
    elif isinstance(value, list | tuple):
        for item in value:
            validate_privacy_safe_keys(
                item,
                label=label,
                allow_raw_content=allow_raw_content,
            )

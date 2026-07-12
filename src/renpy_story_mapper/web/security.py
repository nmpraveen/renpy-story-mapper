"""Security policy for the single-user loopback HTTP service."""

from __future__ import annotations

import hmac
import ipaddress
import re
import secrets
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

MAX_JSON_BODY = 1_048_576
SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32
_PATH_LEAK = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"']+|(?:\\\\|/)(?:Users|home|tmp|var)[\\/][^\s\"']+)",
    re.IGNORECASE,
)

SECURITY_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'none'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


@dataclass(frozen=True)
class SessionSecurity:
    session_token: str
    csrf_token: str

    @classmethod
    def create(cls) -> SessionSecurity:
        return cls(
            secrets.token_urlsafe(SESSION_TOKEN_BYTES), secrets.token_urlsafe(CSRF_TOKEN_BYTES)
        )


def validate_bind_host(host: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("server host must be the IPv4 loopback address") from exc
    if address != ipaddress.ip_address("127.0.0.1"):
        raise ValueError("server may bind only to 127.0.0.1")


def expected_origin(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def valid_host(value: str | None, port: int) -> bool:
    return value is not None and hmac.compare_digest(value.strip(), f"127.0.0.1:{port}")


def valid_origin(value: str | None, port: int) -> bool:
    if value is None:
        return False
    parsed = urlsplit(value)
    try:
        parsed_port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed_port == port
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
    )


def safe_request_path(raw_path: str) -> str | None:
    """Return a decoded absolute URL path, rejecting ambiguity and traversal."""

    parsed = urlsplit(raw_path)
    try:
        decoded = unquote(parsed.path, errors="strict")
    except UnicodeError:
        return None
    if not decoded.startswith("/") or "\\" in decoded or "\x00" in decoded:
        return None
    parts = decoded.split("/")
    if any(part in {".", ".."} for part in parts):
        return None
    return decoded


def token_matches(expected: str, supplied: str | None) -> bool:
    return supplied is not None and hmac.compare_digest(expected, supplied)


def redact_message(message: str) -> str:
    return _PATH_LEAK.sub("[local path]", message)[:500]

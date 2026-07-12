"""Hardened loopback HTTP server with packaged-static and JSON API handling."""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final

from renpy_story_mapper.web.api import ApiProblem, ProjectApi
from renpy_story_mapper.web.contracts import JsonValue, is_json_object, json_value
from renpy_story_mapper.web.security import (
    MAX_JSON_BODY,
    SECURITY_HEADERS,
    SessionSecurity,
    redact_message,
    safe_request_path,
    token_matches,
    valid_host,
    valid_origin,
    validate_bind_host,
)

LOGGER = logging.getLogger(__name__)
API_PREFIX: Final = "/api/v1/"


class LocalWebServer(ThreadingHTTPServer):
    """A single-launch service that owns its API backend and session secrets."""

    daemon_threads = False
    allow_reuse_address = False

    def __init__(
        self,
        host: str,
        port: int,
        api: ProjectApi,
        *,
        static_root: Path | None = None,
        security: SessionSecurity | None = None,
    ) -> None:
        validate_bind_host(host)
        self.api = api
        self.security = security or SessionSecurity.create()
        self.static_root = (static_root or Path(__file__).with_name("static")).resolve()
        self._closed = False
        super().__init__((host, port), LocalRequestHandler, bind_and_activate=True)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def close_service(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.shutdown()
        self.server_close()
        self.api.close()


class LocalRequestHandler(BaseHTTPRequestHandler):
    server: LocalWebServer
    protocol_version = "HTTP/1.1"
    server_version = "RenPyStoryMapper"
    sys_version = ""

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("local web request: %s", redact_message(format % args))

    def _handle(self, method: str) -> None:
        path = safe_request_path(self.path)
        if path is None:
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_path", "The request path is invalid.")
            return
        if not valid_host(self.headers.get("Host"), self.server.port):
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_host", "The request host is invalid.")
            return
        if path.startswith(API_PREFIX):
            self._handle_api(method, path)
        elif method == "GET":
            self._serve_static(path)
        else:
            self._method_not_allowed()

    def _handle_api(self, method: str, path: str) -> None:
        if not token_matches(self.server.security.session_token, self.headers.get("X-RSM-Session")):
            self._json_error(HTTPStatus.UNAUTHORIZED, "invalid_session", "The session is invalid.")
            return
        if method != "GET":
            if not valid_origin(self.headers.get("Origin"), self.server.port):
                self._json_error(
                    HTTPStatus.FORBIDDEN, "invalid_origin", "The request origin is invalid."
                )
                return
            if not token_matches(self.server.security.csrf_token, self.headers.get("X-RSM-CSRF")):
                self._json_error(
                    HTTPStatus.FORBIDDEN, "invalid_csrf", "The request token is invalid."
                )
                return
        elif self.headers.get("Origin") is not None and not valid_origin(
            self.headers.get("Origin"), self.server.port
        ):
            self._json_error(
                HTTPStatus.FORBIDDEN, "invalid_origin", "The request origin is invalid."
            )
            return
        try:
            body = self._read_json_body() if method != "GET" else {}
            result = self.server.api.dispatch(method, path, body)
        except ApiProblem as exc:
            self._json_error(exc.status, exc.code, exc.message)
            return
        except ValueError:
            self._json_error(HTTPStatus.BAD_REQUEST, "invalid_request", "The request is invalid.")
            return
        except BaseException:
            LOGGER.exception("local API request failed")
            self._json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "internal_error",
                "The local service could not complete the request.",
            )
            return
        self._write_json(HTTPStatus.OK, result)

    def _read_json_body(self) -> dict[str, JsonValue]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiProblem(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "invalid_content_type", "JSON is required."
            )
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ApiProblem(
                HTTPStatus.LENGTH_REQUIRED, "length_required", "A body length is required."
            )
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ApiProblem(
                HTTPStatus.BAD_REQUEST, "invalid_length", "The body length is invalid."
            ) from exc
        if length < 0 or length > MAX_JSON_BODY:
            raise ApiProblem(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "body_too_large",
                "The request body is too large.",
            )
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        value = json_value(parsed)
        if not is_json_object(value):
            raise ValueError("JSON body must be an object")
        return value

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.removeprefix("/")
        candidate = (self.server.static_root / relative).resolve()
        try:
            candidate.relative_to(self.server.static_root)
        except ValueError:
            self._json_error(
                HTTPStatus.NOT_FOUND, "not_found", "The requested asset was not found."
            )
            return
        if not candidate.is_file():
            self._json_error(
                HTTPStatus.NOT_FOUND, "not_found", "The requested asset was not found."
            )
            return
        payload = candidate.read_bytes()
        if candidate.name == "index.html":
            text = payload.decode("utf-8")
            text = text.replace(
                'name="rsm-session" content=""',
                f'name="rsm-session" content="{self.server.security.session_token}"',
            ).replace(
                'name="rsm-csrf" content=""',
                f'name="rsm-csrf" content="{self.server.security.csrf_token}"',
            )
            payload = text.encode("utf-8")
        media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header(
            "Content-Type",
            f"{media_type}; charset=utf-8" if media_type.startswith("text/") else media_type,
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _method_not_allowed(self) -> None:
        self._json_error(
            HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", "The method is not allowed."
        )

    def _json_error(self, status: int, code: str, message: str) -> None:
        self._write_json(status, {"error": {"code": code, "message": redact_message(message)}})

    def _write_json(self, status: int, value: JsonValue) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _security_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)


def start_in_thread(server: LocalWebServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name="story-mapper-http", daemon=False)
    thread.start()
    return thread

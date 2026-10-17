from __future__ import annotations

import asyncio
import gzip
import json
import re
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from core.application.caller import AccessDenied, current_caller
from core.structured_director import JsonResponse
from storyrail_contracts.errors import error_payload
from storyrail_contracts.http_edge import is_media_upload_path

from .access import load_access_policy
from .request_context import current_http_origin

_MAX_REQUEST_BYTES = 64 * 1024
_MAX_PROJECT_REQUEST_BYTES = 256 * 1024
_MAX_ASSET_REQUEST_BYTES = 32 * 1024 * 1024
_BODYLESS_DELETE = re.compile(r"/api/projects/[0-9a-f]{32}")
_LOCAL_PATHS = frozenset({"/api/local-connection", "/api/local-session"})
# 这些状态码按 HTTP 规范不得携带响应体与 Content-Length。
_BODYLESS_STATUSES = frozenset({204, 304})


@dataclass(frozen=True, slots=True)
class BinaryResponse:
    status: int
    body: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class CookieResponse:
    status: int
    body: dict[str, Any]
    set_cookie: str


ApiResponse = JsonResponse | BinaryResponse | CookieResponse


class JsonApi(Protocol):
    async def handle(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        media_type: str | None = None,
    ) -> ApiResponse: ...


class StoryRailHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        api: JsonApi,
        event_loop: asyncio.AbstractEventLoop,
        *,
        access_policy_file: Path | None = None,
        request_timeout_seconds: float = 60.0,
        max_worker_threads: int = 64,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds 必须为正数。")
        if max_worker_threads <= 0:
            raise ValueError("max_worker_threads 必须为正数。")
        self.access_policy_file = access_policy_file
        self.local_connection = None
        self.request_timeout_seconds = request_timeout_seconds
        self._worker_slots = threading.BoundedSemaphore(max_worker_threads)
        if access_policy_file is not None:
            load_access_policy(access_policy_file)
        self.api = api
        self.event_loop = event_loop
        super().__init__(address, StoryRailRequestHandler)

    def process_request(self, request: Any, client_address: Any) -> None:
        self._worker_slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()

    def _bind_local_api(self) -> None:
        if self.local_connection is None:
            return
        setter = getattr(self.api, "set_local_connection", None)
        if callable(setter):
            setter(self.local_connection)
        port_setter = getattr(self.api, "set_core_port", None)
        if callable(port_setter):
            port_setter(self.server_address[1])

    async def handle_request(
        self,
        method: str,
        path: str,
        body: bytes,
        media_type: str | None,
        authorization: str | None,
        *,
        origin: str | None = None,
    ) -> ApiResponse:
        context = current_http_origin.set(origin)
        try:
            if urlsplit(path).path in _LOCAL_PATHS:
                self._bind_local_api()
                return await self.api.handle(method, path, body, media_type=media_type)
            if self.access_policy_file is None:
                return await self.api.handle(method, path, body, media_type=media_type)
            try:
                policy = load_access_policy(self.access_policy_file)
                caller = policy.authenticate(authorization)
                policy.authorize(caller, method, path, body)
            except AccessDenied as exc:
                return JsonResponse(
                    exc.status,
                    error_payload(
                        exc.code,
                        str(exc),
                        origin="authorization",
                        retry_policy="obtain_authorization_or_user_action",
                    ),
                )
            except (OSError, ValueError):
                return JsonResponse(
                    503,
                    error_payload(
                        "access_policy_unavailable",
                        "访问策略不可用，请求已拒绝。",
                        origin="authorization",
                        retry_policy="restore_access_policy_then_retry",
                    ),
                )
            caller_context = current_caller.set(caller)
            try:
                response = await self.api.handle(method, path, body, media_type=media_type)
                if (
                    self.local_connection
                    and method == "POST"
                    and path == "/api/projects"
                    and response.status == 201
                ):
                    await asyncio.to_thread(self.local_connection.refresh_human_projects)
                return response
            finally:
                current_caller.reset(caller_context)
        finally:
            current_http_origin.reset(context)


class StoryRailRequestHandler(BaseHTTPRequestHandler):
    server: StoryRailHttpServer

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET", b"")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch_body("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch_body("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        if _BODYLESS_DELETE.fullmatch(urlsplit(self.path).path):
            self._dispatch("DELETE", b"")
        else:
            self._dispatch_body("DELETE")

    def _dispatch_body(self, method: str) -> None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        maximum = _request_body_limit(self.path)
        if maximum != _MAX_ASSET_REQUEST_BYTES and content_type != "application/json":
            self._send_error(415, "unsupported_media_type", "请求必须使用 application/json。")
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_error(400, "invalid_content_length", "Content-Length 不合法。")
            return
        if not 0 <= content_length <= maximum:
            message = (
                "媒体文件不能超过 32 MiB。"
                if maximum == _MAX_ASSET_REQUEST_BYTES
                else "请求体过大。"
            )
            self._send_error(413, "request_too_large", message)
            return
        self._dispatch(method, self.rfile.read(content_length), media_type=content_type)

    def _dispatch(self, method: str, body: bytes, *, media_type: str | None = None) -> None:
        connection = self.server.local_connection
        allowed_origins = {"http://127.0.0.1:5173", "http://localhost:5173"}
        authorization = (
            self.headers.get("Authorization")
            if len(self.headers.get_all("Authorization", [])) == 1
            else None
        )
        if connection and authorization is None:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                token = cookie["storyrail_human"].value
                caller = load_access_policy(connection.policy_path).authenticate("Bearer " + token)
                if caller.role == "human":
                    if method != "GET" and self.headers.get("Origin") not in allowed_origins:
                        self._send_error(403, "origin_denied", "请从 StoryRail 页面操作。")
                        return
                    authorization = "Bearer " + token
            except (KeyError, ValueError, OSError, AccessDenied):
                pass
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.server.handle_request(
                    method,
                    self.path,
                    body,
                    media_type,
                    authorization,
                    origin=self.headers.get("Origin"),
                ),
                self.server.event_loop,
            )
            response = future.result(timeout=self.server.request_timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            response = JsonResponse(
                504,
                error_payload(
                    "request_timeout",
                    "StoryRail 请求处理超时。",
                    recoverable=True,
                    origin="core_domain",
                    state_changed="unknown",
                    retry_policy="inspect_status_before_retry",
                ),
            )
        except Exception:
            response = JsonResponse(
                500,
                error_payload(
                    "internal_error",
                    "StoryRail 无法完成当前请求。",
                    origin="core_domain",
                    state_changed="unknown",
                    retry_policy="inspect_status_before_retry",
                ),
            )
        if isinstance(response, BinaryResponse):
            self._send_binary(response)
        elif isinstance(response, CookieResponse):
            self._send_cookie_json(response)
        else:
            self._send_json(response.status, response.body)

    def _send_binary(self, response: BinaryResponse) -> None:
        body: bytes | memoryview = response.body
        status = response.status
        content_range: str | None = None
        requested_range = self.headers.get("Range") if response.status == 200 else None
        if requested_range is not None:
            try:
                start, end = _parse_byte_range(requested_range, len(response.body))
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(response.body)}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = memoryview(response.body)[start : end + 1]
            status = 206
            content_range = f"bytes {start}-{end}/{len(response.body)}"
        self.send_response(status)
        self.send_header("Content-Type", response.media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.send_header("Accept-Ranges", "bytes")
        if content_range is not None:
            self.send_header("Content-Range", content_range)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self._write_body(body)

    def _send_error(self, status: int, code: str, message: str) -> None:
        authorization = code in {"origin_denied", "login_expired"}
        self._send_json(
            status,
            error_payload(
                code,
                message,
                recoverable=not authorization,
                origin="authorization" if authorization else "core_parser",
                retry_policy=(
                    "obtain_authorization_or_user_action"
                    if authorization
                    else "fix_arguments_and_retry"
                ),
            ),
        )

    def _send_json(self, status: int, value: dict[str, Any]) -> None:
        bodyless = status in _BODYLESS_STATUSES
        body = b""
        compressed = False
        if not bodyless:
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            compressed = len(body) >= 1_024 and _accepts_gzip(
                self.headers.get("Accept-Encoding", "")
            )
            if compressed:
                body = gzip.compress(body, compresslevel=5)
        self.send_response(status)
        if not bodyless:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if not bodyless:
            self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self._write_body(body)

    def _send_cookie_json(self, response: CookieResponse) -> None:
        bodyless = response.status in _BODYLESS_STATUSES
        if bodyless:
            body = b""
        else:
            body = json.dumps(response.body, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        self.send_response(response.status)
        if not bodyless:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", response.set_cookie)
        self.end_headers()
        self._write_body(body)

    def _write_body(self, body: bytes | memoryview) -> None:
        """写响应体；客户端提前断开不是服务端错误，静默收尾并关闭连接。"""
        if not body:
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        super().log_message(format, *args)


def _request_body_limit(path: str) -> int:
    route_path = urlsplit(path).path
    if is_media_upload_path(route_path):
        return _MAX_ASSET_REQUEST_BYTES
    if route_path == "/api/projects":
        return _MAX_PROJECT_REQUEST_BYTES
    return _MAX_REQUEST_BYTES


def _accepts_gzip(value: str) -> bool:
    for item in value.lower().split(","):
        coding, *parameters = (part.strip() for part in item.split(";"))
        if coding not in {"gzip", "*"}:
            continue
        if any(parameter.replace(" ", "") == "q=0" for parameter in parameters):
            continue
        return True
    return False


def _parse_byte_range(value: str, total_bytes: int) -> tuple[int, int]:
    if total_bytes <= 0 or not value.startswith("bytes=") or "," in value:
        raise ValueError("Range 不合法。")
    start_text, separator, end_text = value[6:].strip().partition("-")
    if not separator:
        raise ValueError("Range 不合法。")
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Range 不合法。")
        return max(0, total_bytes - suffix_length), total_bytes - 1
    start = int(start_text)
    if start < 0 or start >= total_bytes:
        raise ValueError("Range 超出资源范围。")
    end = total_bytes - 1 if not end_text else min(int(end_text), total_bytes - 1)
    if end < start:
        raise ValueError("Range 不合法。")
    return start, end

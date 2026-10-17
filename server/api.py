from __future__ import annotations

import json
import re
import shlex
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.application.caller import strict_json
from core.model_providers.registry import ProviderRegistry
from core.playground.http_api import PlaygroundHttpApi
from core.playground.service import PlaygroundService
from core.project_settings import ProjectAspectRatio
from core.project_workspaces import (
    ProjectWorkspace,
    ProjectWorkspaceStore,
)
from core.structured_director import (
    JsonResponse,
    StructuredDirectorHttpApi,
    StructuredDirectorService,
)
from core.structured_director.models._shared import parse_narration_languages
from storyrail_contracts.errors import error_payload
from storyrail_contracts.http_edge import query_is_allowed

from .asset_transfer import (
    copy_playground_asset_to_project,
    copy_project_asset_to_playground,
)
from .http import ApiResponse, BinaryResponse, CookieResponse
from .request_context import current_http_origin

_PROJECT_RESOURCE = re.compile(
    r"/api/projects/(?P<project_id>[0-9a-f]{32})"
    r"(?P<suffix>/structured-director(?:/[^/?]+){0,6})?"
)
_ASSET_CONTENT = re.compile(r"/structured-director/assets/(?P<asset_id>[0-9a-f]{32})/content")
_PLAYGROUND_ASSET_CONTENT = re.compile(r"/api/playground/assets/(?P<asset_id>[0-9a-f]{32})/content")
_ALLOWED_BROWSER_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})


class StoryRailApi:
    def __init__(
        self,
        workspaces: ProjectWorkspaceStore,
        structured_director_service_factory: Callable[[str], StructuredDirectorService],
        *,
        provider_registry: ProviderRegistry | None = None,
        structured_director_service_cache_size: int = 32,
        playground_service: PlaygroundService | None = None,
    ) -> None:
        if structured_director_service_cache_size < 1:
            raise ValueError("structured_director_service_cache_size 必须为正整数。")
        self._workspaces = workspaces
        self._structured_director_service_factory = structured_director_service_factory
        self._structured_director_service_cache_size = structured_director_service_cache_size
        self._structured_director_services: OrderedDict[str, StructuredDirectorService] = (
            OrderedDict()
        )
        self._service_cache_lock = threading.Lock()
        self._provider_registry = provider_registry
        self._playground_service = playground_service
        self._local_connection: object | None = None
        self._core_port: int | None = None

    def set_local_connection(self, local_connection: object) -> None:
        self._local_connection = local_connection

    def set_core_port(self, port: int) -> None:
        self._core_port = port

    async def handle(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        media_type: str | None = None,
    ) -> ApiResponse:
        target = urlsplit(path)
        route_path = target.path
        if not query_is_allowed(route_path, target.query):
            return _error(400, "invalid_request", "该请求不接受查询字段。")
        if route_path == "/api/local-connection":
            return self._local_connection_route(method)
        if route_path == "/api/local-session":
            return self._local_session_route(method, body)
        if route_path == "/api/settings/providers" or route_path.startswith(
            "/api/settings/providers/"
        ):
            return self._provider_settings(method, route_path, body)
        if route_path == "/api/playground" or route_path.startswith("/api/playground/"):
            return await self._playground(method, route_path, target.query, body, media_type)
        if method == "GET" and route_path == "/api/projects":
            return JsonResponse(
                200,
                {"projects": [_serialize_project(project) for project in self._workspaces.list()]},
            )
        if method == "POST" and route_path == "/api/projects":
            return await self._create_project(body)

        match = _PROJECT_RESOURCE.fullmatch(route_path)
        if match is None:
            return _error(404, "not_found", "请求的资源不存在。")
        project_id = match.group("project_id")
        suffix = match.group("suffix")
        if method == "DELETE" and suffix is None:
            return self._delete_project(project_id)
        if suffix is None:
            return _error(404, "not_found", "请求的资源不存在。")

        try:
            self._workspaces.get(project_id)
        except KeyError:
            return _error(404, "project_not_found", "项目不存在。")
        if method == "POST" and suffix == "/structured-director/assets/copy-from-playground":
            if self._playground_service is None:
                return _error(404, "not_found", "请求的资源不存在。")
            return await copy_playground_asset_to_project(
                project_id=project_id,
                project=self._structured_director_service(project_id),
                playground=self._playground_service,
                body=body,
            )
        asset_match = _ASSET_CONTENT.fullmatch(suffix)
        if method == "GET" and asset_match is not None:
            try:
                asset, content = self._structured_director_service(project_id).read_asset(
                    asset_match.group("asset_id")
                )
            except FileNotFoundError:
                return _error(404, "asset_not_found", "Asset 不存在。")
            except ValueError as exc:
                return _error(409, "asset_invalid", str(exc))
            return BinaryResponse(200, content, asset.media_type)
        resource_path = f"/api/projects/{project_id}/structured-director"
        api = StructuredDirectorHttpApi(
            self._structured_director_service(project_id),
            store=self._workspaces.structured_director_store(project_id),
            resource_path=resource_path,
        )
        return await api.handle(method, path, body, media_type=media_type)

    async def _playground(
        self,
        method: str,
        route_path: str,
        query: str,
        body: bytes,
        media_type: str | None,
    ) -> ApiResponse:
        service = self._playground_service
        if service is None:
            return _error(404, "not_found", "请求的资源不存在。")
        content_match = _PLAYGROUND_ASSET_CONTENT.fullmatch(route_path)
        if method == "GET" and content_match is not None:
            try:
                asset, content = service.read_asset(content_match.group("asset_id"))
            except FileNotFoundError:
                return _error(404, "asset_not_found", "Asset 不存在。")
            except ValueError as exc:
                return _error(409, "asset_invalid", str(exc))
            return BinaryResponse(200, content, asset.media_type)
        if method == "POST" and route_path == "/api/playground/assets/copy-from-project":
            return await copy_project_asset_to_playground(
                workspaces=self._workspaces,
                project_service=self._structured_director_service,
                playground=service,
                body=body,
            )
        response = await PlaygroundHttpApi(service).handle(
            method, route_path, query, body, media_type=media_type
        )
        return JsonResponse(response.status, response.body)

    def _local_connection_route(self, method: str) -> ApiResponse:
        if self._local_connection is None or method != "GET":
            return _error(404, "not_found", "请求的资源不存在。")
        port = self._core_port if self._core_port is not None else 0
        command_prefix = shlex.join(
            [
                sys.executable,
                "-m",
                "integrations.agent_launcher",
                "--socket",
                str(self._local_connection.socket_path),
                "--core-port",
                str(port),
            ]
        )
        return JsonResponse(
            200,
            {
                "command_prefix": command_prefix,
                "cwd": str(Path(__file__).resolve().parent.parent),
            },
        )

    def _local_session_route(self, method: str, body: bytes) -> ApiResponse:
        if self._local_connection is None or method != "POST":
            return _error(404, "not_found", "请求的资源不存在。")
        if current_http_origin.get() not in _ALLOWED_BROWSER_ORIGINS:
            return JsonResponse(
                403,
                error_payload(
                    "origin_denied",
                    "请从 StoryRail 页面连接。",
                    recoverable=True,
                    origin="authorization",
                    retry_policy="obtain_authorization_or_user_action",
                ),
            )
        try:
            value = strict_json(body)
            token = (
                self._local_connection.redeem_login(value["ticket"])
                if set(value) == {"ticket"}
                else None
            )
        except (ValueError, TypeError, KeyError):
            token = None
        if not token:
            return JsonResponse(
                401,
                error_payload(
                    "login_expired",
                    "连接已过期，请重新启动 StoryRail 页面。",
                    recoverable=True,
                    origin="authorization",
                    retry_policy="obtain_authorization_or_user_action",
                ),
            )
        return CookieResponse(
            204,
            {},
            "storyrail_human=" + token + "; HttpOnly; SameSite=Strict; Path=/",
        )

    def _provider_settings(self, method: str, route_path: str, body: bytes) -> JsonResponse:
        """全局 Provider 设置：插件实例设置与能力绑定；只影响之后新提交的任务。"""
        registry = self._provider_registry
        if registry is None:
            return _error(404, "not_found", "请求的资源不存在。")
        suffix = route_path.removeprefix("/api/settings/providers")
        if method == "GET" and suffix == "":
            return JsonResponse(200, registry.describe())
        if method != "PUT":
            return _error(404, "not_found", "请求的资源不存在。")
        try:
            if suffix == "/bindings":
                request = _parse_request(body, required={"capability", "plugin_id"})
                if isinstance(request, JsonResponse):
                    return request
                if not isinstance(request["capability"], str) or not isinstance(
                    request["plugin_id"], str
                ):
                    raise ValueError("capability 与 plugin_id 必须是字符串。")
                registry.bind(request["capability"], request["plugin_id"])
                return JsonResponse(200, registry.describe())
            plugin_id = suffix.removeprefix("/plugins/")
            if suffix.startswith("/plugins/") and plugin_id and "/" not in plugin_id:
                request = _parse_request(body, required={"settings"})
                if isinstance(request, JsonResponse):
                    return request
                registry.update_plugin_settings(plugin_id, request["settings"])
                return JsonResponse(200, registry.describe())
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        return _error(404, "not_found", "请求的资源不存在。")

    async def _create_project(self, body: bytes) -> JsonResponse:
        request = _parse_request(
            body,
            required={"title", "aspect_ratio", "director_plan_markdown", "narration_languages"},
        )
        if isinstance(request, JsonResponse):
            return request
        title = request["title"]
        director_plan = request["director_plan_markdown"]
        if not isinstance(title, str) or not isinstance(director_plan, str):
            return _error(
                400,
                "invalid_request",
                "title 和 director_plan_markdown 必须是字符串。",
            )
        try:
            aspect_ratio = ProjectAspectRatio(request["aspect_ratio"])
        except (TypeError, ValueError):
            return _error(400, "invalid_request", "aspect_ratio 只允许 16:9、9:16 或 2:1。")
        try:
            narration_languages = parse_narration_languages(request["narration_languages"])
            project = self._workspaces.create(
                title.strip(),
                director_plan.strip(),
                aspect_ratio=aspect_ratio,
                narration_languages=narration_languages,
            )
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        resource_path = f"/api/projects/{project.id}/structured-director"
        structured = await StructuredDirectorHttpApi(
            self._structured_director_service(project.id),
            store=self._workspaces.structured_director_store(project.id),
            resource_path=resource_path,
        ).handle("GET", resource_path)
        return JsonResponse(
            201,
            {
                "project": _serialize_project(self._workspaces.get(project.id)),
                "structured_director": structured.body,
            },
        )

    def _delete_project(self, project_id: str) -> JsonResponse:
        try:
            deleted = self._workspaces.move_to_trash(project_id)
        except KeyError:
            return _error(404, "project_not_found", "项目不存在。")
        with self._service_cache_lock:
            self._structured_director_services.pop(project_id, None)
        return JsonResponse(200, {"deleted_project_id": deleted.id})

    def _structured_director_service(self, project_id: str) -> StructuredDirectorService:
        self._workspaces.get(project_id)
        with self._service_cache_lock:
            service = self._structured_director_services.pop(project_id, None)
            if service is None:
                service = self._structured_director_service_factory(project_id)
            self._structured_director_services[project_id] = service
            while (
                len(self._structured_director_services)
                > self._structured_director_service_cache_size
            ):
                self._structured_director_services.popitem(last=False)
            return service


def _serialize_project(project: ProjectWorkspace) -> dict[str, str]:
    return {
        "id": project.id,
        "title": project.title,
        "aspect_ratio": project.aspect_ratio.value,
        "updated_at": project.updated_at,
        "status": project.status.value,
    }


def _parse_request(body: bytes, *, required: set[str]) -> dict[str, Any] | JsonResponse:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "请求体必须是合法 JSON。")
    if not isinstance(value, dict) or set(value) != required:
        return _error(400, "invalid_request", "请求包含缺失或未声明的字段。")
    return value


def _error(
    status: int,
    code: str,
    message: str,
    *,
    recoverable: bool = False,
) -> JsonResponse:
    return JsonResponse(
        status,
        error_payload(code, message, recoverable=recoverable),
    )

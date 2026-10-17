"""Playground HTTP 边缘：路由解析、请求校验与错误映射。

L7：返回 ``PlaygroundResponse``，由 ``server/api.py`` 包装成 ``JsonResponse`` 或
``BinaryResponse``。包内不能 import 项目 HTTP 层，因此不复用 ``JsonResponse``。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from core.application.caller import current_caller, strict_json
from storyrail_contracts.errors import error_payload

from .commands import execute_command
from .errors import AssetInUseError, PlaygroundError
from .projection import asset_view, serialize_snapshot


@dataclass(frozen=True, slots=True)
class PlaygroundResponse:
    status: int
    body: dict[str, object]


_VIDEO_FRAME_INFO = "/video-frame-info"


class PlaygroundHttpApi:
    def __init__(self, service) -> None:
        self._service = service

    async def handle(
        self,
        method: str,
        route_path: str,
        query: str,
        body: bytes,
        *,
        media_type: str | None,
    ) -> PlaygroundResponse:
        try:
            return await self._dispatch(method, route_path, query, body, media_type)
        except PlaygroundError as error:
            details = (
                {"asset_ids": list(error.asset_ids)} if isinstance(error, AssetInUseError) else None
            )
            return PlaygroundResponse(
                error.status,
                error_payload(
                    error.code,
                    str(error),
                    recoverable=error.recoverable,
                    details=details,
                ),
            )
        except FileNotFoundError as exc:
            return _invalid(404, "asset_not_found", str(exc) or "Asset 不存在。")
        except ValueError as exc:
            return _invalid(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            return PlaygroundResponse(
                503,
                error_payload(
                    "provider_unavailable",
                    str(exc),
                    recoverable=True,
                ),
            )

    async def _dispatch(
        self,
        method: str,
        route_path: str,
        query: str,
        body: bytes,
        media_type: str | None,
    ) -> PlaygroundResponse:
        service = self._service
        if route_path == "/api/playground":
            if method != "GET":
                return _invalid(404, "not_found", "请求的资源不存在。")
            return PlaygroundResponse(200, serialize_snapshot(service))
        if route_path == "/api/playground/runs/refresh":
            if method != "POST":
                return _invalid(404, "not_found", "请求的资源不存在。")
            await service.refresh_active_runs()
            return PlaygroundResponse(200, serialize_snapshot(service))
        if route_path == "/api/playground/commands":
            if method != "POST":
                return _invalid(404, "not_found", "请求的资源不存在。")
            return await self._command(body)
        if route_path == "/api/playground/recipe-inputs-preview" and method == "POST":
            value = strict_json(body)
            if (
                not isinstance(value, dict)
                or set(value) != {"capability", "parameters"}
                or not isinstance(value["capability"], str)
            ):
                raise ValueError("预览请求只能包含 capability 与 parameters。")
            return PlaygroundResponse(
                200, service.preview_recipe_inputs(value["capability"], value["parameters"])
            )
        if route_path == "/api/playground/assets/media":
            if method != "POST":
                return _invalid(404, "not_found", "请求的资源不存在。")
            return await self._upload(query, body, media_type)
        if route_path == "/api/playground/assets":
            if method != "DELETE":
                return _invalid(404, "not_found", "请求的资源不存在。")
            return await self._delete(body)
        asset_id = _asset_route(route_path)
        if asset_id is not None and method == "GET":
            info = service.video_frame_info(asset_id)
            return PlaygroundResponse(
                200,
                {
                    "frame_count": info.frame_count,
                    "duration_seconds": info.duration_seconds,
                },
            )
        return _invalid(404, "not_found", "请求的资源不存在。")

    async def _command(self, body: bytes) -> PlaygroundResponse:
        value = strict_json(body)
        result = await execute_command(self._service, value, current_caller.get())
        return PlaygroundResponse(200, result)

    async def _upload(self, query: str, body: bytes, media_type: str | None) -> PlaygroundResponse:
        fields = parse_qsl(query, keep_blank_values=True)
        if any(key != "filename" for key, _value in fields) or len(fields) > 1:
            return _invalid(400, "invalid_request", "该请求只接受一个 filename 查询字段。")
        if media_type is None:
            return _invalid(400, "invalid_request", "缺少 Content-Type。")
        filename = fields[0][1] if fields else None
        asset = await self._service.import_asset(
            media_type=media_type,
            content=body,
            filename=filename,
        )
        return PlaygroundResponse(200, {"asset": asset_view(self._service, asset)})

    async def _delete(self, body: bytes) -> PlaygroundResponse:
        value = strict_json(body)
        if set(value) != {"asset_ids"} or not isinstance(value["asset_ids"], list):
            return _invalid(400, "invalid_request", "请求必须只包含 asset_ids 数组。")
        asset_ids = tuple(value["asset_ids"])
        if any(not isinstance(item, str) for item in asset_ids):
            return _invalid(400, "invalid_request", "asset_ids 必须是字符串数组。")
        deleted = await self._service.delete_assets(asset_ids)
        return PlaygroundResponse(200, {"deleted_asset_ids": list(deleted)})


def _asset_route(route_path: str) -> str | None:
    prefix = "/api/playground/assets/"
    if not route_path.startswith(prefix) or not route_path.endswith(_VIDEO_FRAME_INFO):
        return None
    asset_id = route_path[len(prefix) : -len(_VIDEO_FRAME_INFO)]
    if len(asset_id) != 32 or any(character not in "0123456789abcdef" for character in asset_id):
        return None
    return asset_id


def _invalid(status: int, code: str, message: str) -> PlaygroundResponse:
    return PlaygroundResponse(status, error_payload(code, message))


def route_query_allowed(route_path: str) -> bool:
    """只有素材上传路径接受查询字段。"""
    return urlsplit(route_path).path == "/api/playground/assets/media"

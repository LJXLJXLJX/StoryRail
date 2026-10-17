"""项目与 Playground 之间的人类跨域资产复制。

本模块是唯一同时 import 项目侧与 Playground 侧的模块（除 server 装配点外）。
两条路由都只允许人类调用；复制产生一个全新的对侧 Asset，不共享引用。
"""

from __future__ import annotations

from collections.abc import Callable

from core.application.caller import strict_json
from core.media_assets import MEDIA_EXTENSION
from core.playground.projection import asset_view
from core.playground.service import PlaygroundService
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import JsonResponse, StructuredDirectorService
from core.structured_director.errors import RevisionConflictError
from core.structured_director.models import ImageAssetCategory
from storyrail_contracts.errors import error_payload

_IMPORTABLE_IMAGE_CATEGORIES = {
    "character_reference": ImageAssetCategory.CHARACTER_REFERENCE,
    "location_master": ImageAssetCategory.LOCATION_MASTER,
    "location_view": ImageAssetCategory.LOCATION_VIEW,
    "keyframe": ImageAssetCategory.KEYFRAME,
}


async def copy_project_asset_to_playground(
    *,
    workspaces: ProjectWorkspaceStore,
    project_service: Callable[[str], StructuredDirectorService],
    playground: PlaygroundService,
    body: bytes,
) -> JsonResponse:
    try:
        request = strict_json(body)
    except (ValueError, UnicodeError) as exc:
        return _error(400, "invalid_request", str(exc) or "请求 JSON 不合法。")
    if set(request) != {"project_id", "asset_id"}:
        return _error(400, "invalid_request", "请求必须只包含 project_id 和 asset_id。")
    project_id = request["project_id"]
    asset_id = request["asset_id"]
    if not isinstance(project_id, str) or not isinstance(asset_id, str):
        return _error(400, "invalid_request", "project_id 和 asset_id 必须是文本。")
    try:
        workspaces.get(project_id)
    except KeyError:
        return _error(404, "project_not_found", "项目不存在。")
    try:
        asset, content = project_service(project_id).read_asset(asset_id)
    except FileNotFoundError:
        return _error(404, "asset_not_found", "Asset 不存在。")
    except ValueError as exc:
        return _error(409, "asset_invalid", str(exc))
    copied = await playground.copy_in_from_project(
        media_type=asset.media_type,
        content=content,
        label=asset.display_name,
        project_id=project_id,
        source_asset_id=asset.id,
    )
    return JsonResponse(200, {"asset": asset_view(playground, copied)})


async def copy_playground_asset_to_project(
    *,
    project_id: str,
    project: StructuredDirectorService,
    playground: PlaygroundService,
    body: bytes,
) -> JsonResponse:
    try:
        request = strict_json(body)
    except (ValueError, UnicodeError) as exc:
        return _error(400, "invalid_request", str(exc) or "请求 JSON 不合法。")
    if set(request) != {"asset_id", "expected_revision", "image_category"}:
        return _error(
            400,
            "invalid_request",
            "请求必须只包含 asset_id、expected_revision 和 image_category。",
        )
    asset_id = request["asset_id"]
    expected_revision = request["expected_revision"]
    image_category = request["image_category"]
    if (
        not isinstance(asset_id, str)
        or isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
    ):
        return _error(400, "invalid_request", "asset_id 或 expected_revision 不合法。")
    try:
        asset, content = playground.read_asset(asset_id)
    except FileNotFoundError:
        return _error(404, "asset_not_found", "Asset 不存在。")
    except ValueError as exc:
        return _error(409, "asset_invalid", str(exc))

    filename = f"{asset.display_name}.{MEDIA_EXTENSION[asset.media_type]}"
    try:
        if asset.media_type.startswith("image/"):
            if image_category not in _IMPORTABLE_IMAGE_CATEGORIES:
                return _error(
                    400,
                    "invalid_request",
                    "图片必须选择 character_reference、location_master、location_view "
                    "或 keyframe 分类。",
                )
            document = await project.import_image_asset(
                media_type=asset.media_type,
                content=content,
                category=_IMPORTABLE_IMAGE_CATEGORIES[image_category],
                filename=filename,
                expected_revision=expected_revision,
            )
        else:
            if image_category is not None:
                return _error(400, "invalid_request", "音频和视频的 image_category 必须为 null。")
            document = await project.import_media_asset(
                media_type=asset.media_type,
                content=content,
                filename=filename,
                expected_revision=expected_revision,
            )
    except RevisionConflictError as exc:
        return _error(409, "revision_conflict", str(exc), recoverable=True)
    except ValueError as exc:
        return _error(409, "project_write_rejected", str(exc))
    return JsonResponse(200, {"asset_id": asset.id, "project_revision": document.revision})


def _error(status: int, code: str, message: str, *, recoverable: bool = False) -> JsonResponse:
    return JsonResponse(status, error_payload(code, message, recoverable=recoverable))

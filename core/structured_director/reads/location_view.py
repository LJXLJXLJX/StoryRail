"""地点卡的只读资源投影：权限、依赖状态和生成步骤由 Core 计算。"""

from __future__ import annotations

from ..codec.location import serialize_location_library
from ..location_mutations import (
    LocationActionIndex,
    require_location_candidate,
    require_location_deletion,
    require_location_selection_idle,
)
from ..location_requests import (
    crop_is_current,
    location_master_plan,
    location_set_items,
    location_view_plan,
)
from ..models import ReferenceGenerationKind as Kind
from ..models import ReferenceGenerationPhase as Phase
from ..models import StructuredDirectorStatus

_LABELS = {
    "ready": "可生成",
    "in_progress": "进行中",
    "submission_uncertain": "提交结果未知",
    "awaiting_selection": "等待选择",
    "awaiting_master": "等待主图选择",
    "awaiting_calibration": "等待标定",
    "awaiting_reference_view": "等待参考视图",
    "failed": "生成失败",
    "cancelled": "已取消",
    "blocked": "被阻止",
    "already_selected": "已选择",
}
_TERMINAL = {Phase.SUCCEEDED, Phase.FAILED, Phase.CANCELLED}


def location_library_projection(document, service):
    library = serialize_location_library(document.location_library)
    index = LocationActionIndex(document)
    editable = (
        document.status is not StructuredDirectorStatus.APPROVED
        and document.active_director_run is None
    )
    library["allowed_actions"] = (
        ["create_location", *(["bind_scene", "bind_shot"] if document.director_script else [])]
        if editable
        else []
    )
    items = location_set_items(
        document,
        tuple(item.id for item in document.location_library.locations),
        generations_by_target=index.generations,
        asset_ids=index.assets.keys(),
    )
    states = {(item.location_id, item.view_id): item for item in items}

    def permitted(check, *args):
        if not editable:
            return False
        try:
            check(index, *args)
        except ValueError:
            return False
        return True

    def generation_state(location, view=None):
        target = location.id if view is None else view.id
        kinds = (
            {Kind.LOCATION_MASTER_IMAGE}
            if view is None
            else {Kind.LOCATION_VIEW_IMAGE, Kind.LOCATION_VIEW_CROP}
        )
        generations = [g for g in index.generations.get(target, ()) if g.kind in kinds]
        active = next((g for g in reversed(generations) if g.phase not in _TERMINAL), None)
        candidates = [
            g
            for g in generations
            if g.kind is not Kind.LOCATION_VIEW_CROP
            and not g.dismissed
            and g.phase is Phase.SUCCEEDED
            and g.output_asset_id
            and (asset := index.assets.get(g.output_asset_id)) is not None
            and asset.media_type.startswith("image/")
        ]
        selectable = []
        for g in candidates:
            if not editable:
                continue
            try:
                if (
                    view is None
                    and location.kind.value == "interior"
                    and not service.location_master_candidate_valid(index.assets[g.output_asset_id])
                ):
                    continue
                require_location_candidate(index, g.kind, target, g.output_asset_id, "候选不可选。")
                require_location_selection_idle(index, location, view, g.output_asset_id)
            except ValueError:
                continue
            selectable.append(g.id)
        item = states[location.id, None if view is None else view.id]
        status, reason = item.status, item.reason
        if active:
            status = (
                "submission_uncertain"
                if active.phase is Phase.SUBMISSION_UNCERTAIN
                else "in_progress"
            )
            reason = active.message
        step = (
            "master"
            if view is None
            else (
                "crop"
                if location.kind.value == "interior"
                and not crop_is_current(document, location, view)
                else "refine"
                if location.kind.value == "interior"
                else "turn"
            )
        )
        ready = editable and active is None
        try:
            plan = (
                location_master_plan(document, location.id)
                if view is None
                else location_view_plan(document, view.id)
            )
            available = (
                service.pano_view_available
                if view is not None and plan.crop is not None
                else service.image_generation_available
            )
            if not available:
                ready = False
                reason = "全景裁切服务尚未配置。" if step == "crop" else "图片生成服务尚未配置。"
                if active is None:
                    status = "blocked"
        except ValueError as exc:
            ready = False
            if active is None:
                reason = str(exc)
        actions = []
        if ready:
            actions.append("generate")
        if selectable:
            actions.append("select")
        if editable:
            actions.append("edit")
        return {
            "status": status,
            "status_label": _LABELS.get(status, status),
            "reason": reason,
            "generation_step": step,
            "generate_label": {
                "master": "生成主图",
                "crop": "第一步：生成裁切底图",
                "refine": "第二步：细化视图",
                "turn": "生成转向视图",
            }[step],
            "active_generation_id": None if active is None else active.id,
            "candidate_generation_ids": [g.id for g in candidates],
            "selectable_generation_ids": selectable,
            "allowed_actions": actions,
        }

    for data, location in zip(
        library["locations"], document.location_library.locations, strict=True
    ):
        data["allowed_actions"] = (
            ["edit", "create_view", "create_fixture", "create_state"] if editable else []
        )
        if permitted(require_location_deletion, location, "location"):
            data["allowed_actions"].append("delete")
        data["master"]["production"] = generation_state(location)
        if (
            permitted(require_location_selection_idle, location, None, None)
            and location.master.selected_asset_id
        ):
            data["master"]["production"]["allowed_actions"].append("clear_selection")
        for row, view in zip(data["views"], location.views, strict=True):
            row["has_valid_crop"] = crop_is_current(document, location, view)
            row["production"] = generation_state(location, view)
            if permitted(require_location_deletion, location, "view", view.id):
                row["production"]["allowed_actions"].append("delete")
            if view.selected_asset_id and permitted(
                require_location_selection_idle, location, view, None
            ):
                row["production"]["allowed_actions"].append("clear_selection")
        for key, kind in (("fixtures", "fixture"), ("states", "state")):
            for row in data[key]:
                row["allowed_actions"] = ["edit"] if editable else []
                if permitted(require_location_deletion, location, kind, row["id"]):
                    row["allowed_actions"].append("delete")
    return library

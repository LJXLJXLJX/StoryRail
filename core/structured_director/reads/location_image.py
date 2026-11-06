"""地点语义卡与独立图片条目的只读投影。"""

from __future__ import annotations

from ..codec.location import serialize_location_library
from ..location_mutations import (
    LocationActionIndex,
    require_location_candidate,
    require_location_deletion,
    require_location_selection_idle,
)
from ..location_requests import (
    location_image_plan,
    location_set_items,
    panorama_capture_request,
)
from ..models import LocationImageKind, StructuredDirectorStatus, unresolved_uncertain_ids
from ..models import ReferenceGenerationKind as Kind
from ..models import ReferenceGenerationPhase as Phase

_LABELS = {
    "ready": "可生成",
    "in_progress": "进行中",
    "submission_uncertain": "提交结果未知",
    "awaiting_selection": "等待选择",
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
        ["create_location", *(["bind_scene"] if document.director_script else [])]
        if editable
        else []
    )
    items = location_set_items(
        document,
        tuple(item.id for item in document.location_library.locations),
        generations_by_target=index.generations,
        asset_ids=index.assets.keys(),
    )
    states = {(item.location_id, item.image_id): item for item in items}

    def permitted(check, *args):
        if not editable:
            return False
        try:
            check(index, *args)
        except ValueError:
            return False
        return True

    unresolved = unresolved_uncertain_ids(document.generations)

    def generation_state(location, image):
        capture = image.source is not None
        kinds = {Kind.PANORAMA_CAPTURE if capture else Kind.LOCATION_IMAGE}
        generations = [g for g in index.generations.get(image.id, ()) if g.kind in kinds]
        active = next(
            (
                g
                for g in reversed(generations)
                if g.phase not in _TERMINAL
                and (g.phase is not Phase.SUBMISSION_UNCERTAIN or g.id in unresolved)
            ),
            None,
        )
        candidates = [
            g
            for g in generations
            if not capture
            and not g.dismissed
            and g.phase is Phase.SUCCEEDED
            and g.output_asset_id
            and (asset := index.assets.get(g.output_asset_id)) is not None
            and asset.media_type.startswith("image/")
        ]
        selectable = []
        for generation in candidates:
            if not editable:
                continue
            try:
                if (
                    image.kind is LocationImageKind.PANORAMA
                    and not service.panorama_candidate_valid(
                        index.assets[generation.output_asset_id]
                    )
                ):
                    continue
                require_location_candidate(
                    index,
                    generation.kind,
                    image.id,
                    generation.output_asset_id,
                    "候选不可选。",
                )
                require_location_selection_idle(index, image, generation.output_asset_id)
            except ValueError:
                continue
            selectable.append(generation.id)
        item = states[(location.id, image.id)]
        status, reason = item.status, item.reason
        if active is not None:
            status = (
                "submission_uncertain"
                if active.phase is Phase.SUBMISSION_UNCERTAIN
                else "in_progress"
            )
            reason = active.message
        step = "capture" if capture else "image"
        ready = editable and active is None and image.selected_asset_id is None
        try:
            if capture:
                panorama_capture_request(document, image.id)
                available = service.pano_view_available
            else:
                location_image_plan(document, image.id)
                available = service.image_generation_available
            if not available:
                ready = False
                reason = "全景取景服务尚未配置。" if capture else "图片生成服务尚未配置。"
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
        if editable and active is None and image.source is None:
            actions.append("select_asset")
        if editable:
            actions.append("edit")
        if image.kind is LocationImageKind.PANORAMA and image.selected_asset_id is not None:
            actions.append("preview_panorama")
        return {
            "status": status,
            "status_label": _LABELS.get(status, status),
            "reason": reason,
            "generation_step": step,
            "generate_label": "截取当前视角" if capture else "生成图片",
            "active_generation_id": None if active is None else active.id,
            "candidate_generation_ids": [g.id for g in candidates],
            "selectable_generation_ids": selectable,
            "allowed_actions": actions,
        }

    for data, location in zip(
        library["locations"], document.location_library.locations, strict=True
    ):
        data["allowed_actions"] = (
            ["edit", "create_image", "create_fixture", "create_state"] if editable else []
        )
        if permitted(require_location_deletion, location, "location"):
            data["allowed_actions"].append("delete")
        for row, image in zip(data["images"], location.images, strict=True):
            row["production"] = generation_state(location, image)
            if permitted(require_location_deletion, location, "image", image.id):
                row["production"]["allowed_actions"].append("delete")
            if image.selected_asset_id and permitted(require_location_selection_idle, image, None):
                row["production"]["allowed_actions"].append("clear_selection")
        for key, kind in (("fixtures", "fixture"), ("states", "state")):
            for row in data[key]:
                row["allowed_actions"] = ["edit"] if editable else []
                if permitted(require_location_deletion, location, kind, row["id"]):
                    row["allowed_actions"].append("delete")
    return library

"""`project.get_details`：专业工作集只给导演脚本与极简索引，其它对象的完整详情按 ID 读取。"""

from ..codec.keyframe import serialize_character_references
from ..models import LocationImageKind
from ..script_index import scene_segments
from .common import _exact_arguments, _ids, _json_value
from .professional_worksets import _AGENT_PAGE_BYTES, _agent_page

DETAIL_KINDS = ("keyframe", "location", "location_image", "character", "director_plan")
_MAX_IDS = 20


def details_page_read(document, arguments):
    """详情超过单次上限时（例如长导演方案）与专业工作集同样按 UTF-8 chunk 分页。"""
    query = {key: value for key, value in arguments.items() if key != "cursor"}
    return _agent_page(
        details_read(document, query),
        query={"project_id": document.project_id, **query},
        cursor=arguments.get("cursor"),
        page_bytes=_AGENT_PAGE_BYTES,
    )


def details_read(document, arguments):
    _exact_arguments(arguments, required={"kind"}, optional={"ids"})
    kind = arguments["kind"]
    if not isinstance(kind, str) or kind not in DETAIL_KINDS:
        raise ValueError(f"project.get_details.kind 只允许 {'、'.join(DETAIL_KINDS)}。")
    if kind == "director_plan":
        if "ids" in arguments:
            raise ValueError("director_plan 不接受 ids。")
        return _result(
            document, kind, [], [{"director_plan_markdown": document.director_plan_markdown}], []
        )
    if "ids" not in arguments:
        raise ValueError(f"{kind} 详情必须给出 ids。")
    ids = _ids(arguments["ids"], "ids")
    if not 1 <= len(ids) <= _MAX_IDS:
        raise ValueError(f"ids 必须包含 1 到 {_MAX_IDS} 个 ID。")
    available = _KINDS[kind](document)
    return _result(
        document,
        kind,
        list(ids),
        [available[item] for item in ids if item in available],
        [item for item in ids if item not in available],
    )


def _result(document, kind, ids, items, missing_ids):
    return {
        "project_id": document.project_id,
        "source_revision": document.revision,
        "kind": kind,
        "target_ids": ids,
        "items": items,
        "missing_ids": missing_ids,
    }


def _keyframes(document):
    plan = document.keyframe_plan
    script = document.director_script
    if plan is None or script is None:
        return {}
    bindings: dict[str, list[dict[str, str]]] = {}
    for scene in script.scenes:
        for segment in scene_segments(scene):
            binding = next((b for b in plan.segments if b.segment_id == segment.id), None)
            if binding is None:
                continue
            for slot, keyframe_id, enabled in (
                ("start", binding.start_keyframe_id, binding.start_enabled),
                ("end", binding.end_keyframe_id, binding.end_enabled),
            ):
                bindings.setdefault(keyframe_id, []).append(
                    {
                        "scene_id": scene.id,
                        "segment_id": segment.id,
                        "slot": slot,
                        "enabled": enabled,
                    }
                )
    return {
        item.id: {
            "keyframe_id": item.id,
            "bindings": bindings.get(item.id, []),
            "prompt_text": item.prompt_text,
            "visible_character_ids": list(item.visible_character_ids),
            "character_references": serialize_character_references(item),
            "predecessor_keyframe_id": item.predecessor_keyframe_id,
            "reference_keyframe_ids": list(item.reference_keyframe_ids),
            "reference_location_image_ids": list(item.reference_location_image_ids),
            "selected_asset_id": item.selected_asset_id,
        }
        for item in plan.keyframes
    }


def _locations(document):
    result = {}
    for location in document.location_library.locations:
        value = _json_value(location)
        for image, item in zip(location.images, value["images"], strict=True):
            item["has_selected_image"] = image.selected_asset_id is not None
        result[location.id] = value
    return result


def _location_images(document):
    return {
        image.id: {
            **_json_value(image),
            "image_id": image.id,
            "location_id": location.id,
            "location_name": location.name,
            "referenceable": image.kind is LocationImageKind.IMAGE
            and image.selected_asset_id is not None,
        }
        for location in document.location_library.locations
        for image in location.images
    }


def _characters(document):
    return {item.id: _json_value(item) for item in document.reference_library.characters}


_KINDS = {
    "keyframe": _keyframes,
    "location": _locations,
    "location_image": _location_images,
    "character": _characters,
}

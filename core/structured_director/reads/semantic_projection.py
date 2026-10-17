"""人和 Agent 共源的只读故事投影；不承担授权、状态迁移或媒体寻址。"""

from __future__ import annotations

import hashlib
import json

from ..dialogue_timing import dialogue_timing
from ..models import StructuredDirectorDocument
from ..prompt_worksets import keyframe_workset, video_prompt_workset
from ..v32_projection import v32_cue_anchors, v32_shot_segments
from .common import (
    ReadResultTooLarge,
    _ids,
    _json_value,
    _validate_result_bounds,
)
from .dependencies import _get_dependencies

PROJECTION_VERSION = 1
_TEXT_PREVIEW = 240


def build_semantic_projection(
    document: StructuredDirectorDocument,
    request: dict[str, object],
    *,
    provider_recipes=None,
    provider_catalog=None,
) -> dict[str, object]:
    """严格显式 scope；分页游标绑定项目、revision 和完整查询，不能作为授权凭证。"""
    if (
        not isinstance(request, dict)
        or not {"level", "scope"} <= request.keys()
        or (
            request.keys() - {"level", "scope", "ids", "parent_id", "extensions", "limit", "cursor"}
        )
    ):
        raise ValueError("semantic projection 请求缺少 scope/level 或含未声明字段。")
    level = request["level"]
    if not isinstance(level, str) or level not in {"outline", "scene", "shot", "segment"}:
        raise ValueError("semantic projection level 不合法。")
    extensions = request.get("extensions", [])
    if (
        not isinstance(extensions, list)
        or any(
            not isinstance(item, str)
            or item not in {"text", "selection", "dependencies", "video_prompt", "keyframe"}
            for item in extensions
        )
        or len(extensions) != len(set(extensions))
    ):
        raise ValueError("semantic projection extensions 不合法或重复。")
    if set(extensions) & {"video_prompt", "keyframe"} and level != "segment":
        raise ValueError("专业Prompt扩展只接受Segment层级。")
    scope = request["scope"]
    scenes = () if document.director_script is None else document.director_script.scenes
    if level == "outline":
        if scope != {"project_id": document.project_id} or "ids" in request:
            raise ValueError("outline 必须显式指定当前 project_id scope，不能带 ids。")
    else:
        if not isinstance(scope, dict) or set(scope) != {"scene_ids"}:
            raise ValueError("详情必须显式指定 scene_ids scope。")
        scene_ids = _ids(scope["scene_ids"], "scope.scene_ids")
        if len(scene_ids) > 100:
            raise ValueError("scope 最多包含 100 个 Scene。")
        if set(scene_ids) - {scene.id for scene in scenes}:
            raise ValueError("scope 包含未知 Scene ID。")
        scenes = tuple(scene for scene in scenes if scene.id in scene_ids)
    parent_id = request.get("parent_id")
    if "parent_id" in request:
        if level != "segment":
            raise ValueError("parent_id 只接受 Segment 的 Shot 父节点。")
        _ids([parent_id], "parent_id")
        if parent_id not in {shot.id for scene in scenes for shot in scene.shots}:
            raise ValueError("parent_id 未知或越出显式 Scene scope。")
    if level in {"outline", "scene"}:
        if level == "scene" and "ids" in request:
            raise ValueError("Scene 层仅使用 scene_ids scope，不接受 ids。")
        nodes = [(scene, None, scene) for scene in scenes]
    else:
        ids = _ids(request["ids"], "ids") if "ids" in request else None
        if ids is not None and len(ids) > 100:
            raise ValueError("ids 最多包含 100 个节点。")
        nodes = [
            (scene, shot, node)
            for scene in scenes
            for shot in scene.shots
            if parent_id is None or shot.id == parent_id
            for node in ((shot,) if level == "shot" else v32_shot_segments(scene, shot.id))
            if ids is None or node.id in ids
        ]
        if ids is not None and set(ids) != {node.id for _, _, node in nodes}:
            raise ValueError("节点 ID 未知或越出 scene_ids scope。")
    limit = request.get("limit", 30)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必须为 1 到 100 的整数。")
    query_digest = hashlib.sha256(
        json.dumps(
            {
                "project_id": document.project_id,
                "revision": document.revision,
                "version": PROJECTION_VERSION,
                "request": {key: value for key, value in request.items() if key != "cursor"},
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    offset = 0
    if "cursor" in request:
        cursor = request["cursor"]
        if not isinstance(cursor, str):
            raise ValueError("cursor 不合法。")
        parts = cursor.split(":")
        if (
            len(parts) != 2
            or parts[0] != query_digest
            or not parts[1].isascii()
            or (not parts[1].isdigit())
        ):
            raise ValueError("cursor 不属于当前查询或 revision，请重新读取。")
        offset = int(parts[1])
        if offset >= len(nodes):
            raise ValueError("cursor 超出结果范围。")
    assets = {asset.id: asset for asset in document.assets}

    def text(value):
        return value if "text" in extensions or value is None else value[:_TEXT_PREVIEW]

    items = []
    for scene, shot, node in nodes[offset : offset + limit]:
        kind = "scene" if level == "outline" else level
        source = f"director_script.scenes[id={scene.id}]"
        if shot is not None:
            source += f".shots[id={shot.id}]"
        if kind == "segment":
            source += f".segments[id={node.id}]"
        item = {
            "id": node.id,
            "kind": kind,
            "scene_id": scene.id,
            "driver": scene.driver,
            "parent": {"kind": "project", "id": document.project_id}
            if kind == "scene"
            else {
                "kind": "scene" if kind == "shot" else "shot",
                "id": scene.id if kind == "shot" else shot.id,
            },
            "provenance": {"source": "project.json", "field": source},
        }
        if kind == "scene":
            item.update(title=scene.title, summary=text(scene.summary), shot_count=len(scene.shots))
            item["narration"] = [
                {
                    "id": cue.id,
                    **{
                        language.value: {
                            "text": text(track.text),
                            "selected_audio_asset_id": track.selected_audio_asset_id,
                            "duration_seconds": assets[
                                track.selected_audio_asset_id
                            ].duration_seconds
                            if track.selected_audio_asset_id in assets
                            else None,
                            "duration_source": "selected_audio_asset"
                            if track.selected_audio_asset_id
                            else None,
                        }
                        for language, track in cue.tracks
                    },
                    "timing": "旁白以所选语言已选音频中最长的一条为时间基准。",
                    "start_shot_id": v32_cue_anchors(scene)[0],
                    "end_shot_id": v32_cue_anchors(scene)[1],
                }
                for cue in scene.narration_cues
            ]
            if level == "scene":
                item["setting"] = text(scene.setting)
        elif kind == "shot":
            item.update(
                action=text(shot.action),
                composition=text(shot.composition),
                camera_movement=text(shot.camera_movement),
                audio_direction=text(shot.audio_direction),
                visible_character_ids=list(shot.visible_character_ids),
                transition_in=text(shot.transition_in),
                segment_count=len(v32_shot_segments(scene, shot.id)),
            )
        else:
            item.update(
                action=text(node.action),
                duration_estimate_seconds=node.duration_estimate_seconds,
                dialogue_lines=[
                    {
                        "character_id": line.character_id,
                        "speaker_label": line.speaker_label,
                        "text": text(line.text),
                        "delivery": text(line.delivery),
                    }
                    for line in node.dialogue_lines
                ],
                dialogue_timing=dialogue_timing(node),
                boundary_from_previous=None
                if node.boundary_from_previous is None
                else {
                    "reason": node.boundary_from_previous.reason.value,
                    "continuity_instruction": text(
                        node.boundary_from_previous.continuity_instruction
                    ),
                },
            )
        if "selection" in extensions:
            item["selection"] = _selection(document, kind, node.id)
        if "dependencies" in extensions:
            item["dependencies"] = _dependencies(document, kind, node.id, catalog=provider_catalog)
        if "video_prompt" in extensions:
            item["video_prompt"] = video_prompt_workset(
                document,
                node.id,
                provider_recipes=provider_recipes,
                provider_catalog=provider_catalog,
            )
        if "keyframe" in extensions:
            item["keyframe"] = keyframe_workset(
                document, node.id, provider_catalog=provider_catalog
            )
        items.append(item)
    next_offset = offset + len(items)
    result = {
        "projection_version": PROJECTION_VERSION,
        "project_id": document.project_id,
        "revision": document.revision,
        "script_revision": None
        if document.director_script is None
        else document.director_script.revision,
        "level": level,
        "scope": _json_value(scope),
        "extensions": list(extensions),
        "text_mode": "full" if "text" in extensions else "preview",
        "text_preview_characters": _TEXT_PREVIEW,
        "items": items,
        "total": len(nodes),
        "next_cursor": f"{query_digest}:{next_offset}" if next_offset < len(nodes) else None,
    }
    if parent_id is not None:
        result["parent_id"] = parent_id
    _validate_result_bounds(result)
    return result


def _selection(document, kind, node_id):
    if kind == "scene":
        scene = next((x for x in document.director_script.scenes if x.id == node_id), None)
        location_id = None if scene is None else scene.location_id
        location = None if location_id is None else document.location_library.location(location_id)
        return {
            "location_id": location_id,
            "state_id": None if scene is None else scene.state_id,
            "location_master_asset_id": None
            if location is None
            else location.master.selected_asset_id,
        }
    if kind == "shot":
        return {"detail_level": "segment"}
    plan = document.keyframe_plan
    binding = next(
        (x for x in (() if plan is None else plan.segments) if x.segment_id == node_id), None
    )
    frames = {} if plan is None else {frame.id: frame for frame in plan.keyframes}
    video_plan = document.video_plan
    video = next(
        (x for x in (() if video_plan is None else video_plan.segments) if x.segment_id == node_id),
        None,
    )
    return {
        "keyframes": []
        if binding is None
        else [
            {
                "slot": slot,
                "enabled": enabled,
                "keyframe_id": frame_id,
                "selected_asset_id": frames[frame_id].selected_asset_id,
            }
            for slot, enabled, frame_id in (
                ("start", binding.start_enabled, binding.start_keyframe_id),
                ("end", binding.end_enabled, binding.end_keyframe_id),
            )
        ],
        "video_asset_id": None if video is None else video.selected_asset_id,
        "upscaled_asset_id": None if video is None else video.upscaled_asset_id,
    }


def _dependencies(document, kind, node_id, *, catalog=None):
    if kind == "scene":
        return {"detail_level": "shot"}
    if kind == "shot":
        return {"detail_level": "segment"}
    action = "video.generate"
    # 与 read_tools 的 project.get_dependencies reader 走同一实现（含参数校验与结果界）。
    result = _get_dependencies(
        document, {"action": action, "target_ids": [node_id]}, catalog=catalog
    )
    _validate_result_bounds(result)
    return {
        "informational_only": True,
        "source": "project.get_dependencies",
        "result": result,
    }


def build_semantic_tree(
    document: StructuredDirectorDocument,
    scene_ids: tuple[str, ...],
    *,
    full_text: bool = False,
) -> dict[str, object]:
    """将显式 scope 的分页事实组装成任务所需树；保留源元数据，不引入新领域事实。"""
    if not scene_ids:
        raise ValueError("任务上下文缺少 Scene scope，不能扩大为全项目。")
    scope = {"scene_ids": list(scene_ids)}
    extensions = ["text"] if full_text else []

    def read(level, limit=25):
        # 页过大时用更小页重新构建该层；cursor绑定limit，不能跨查询沿用。
        request = {"level": level, "scope": scope, "extensions": extensions, "limit": limit}
        values = []
        while True:
            try:
                page = build_semantic_projection(document, request)
            except ReadResultTooLarge:
                if limit == 1:
                    raise
                return read(level, max(1, limit // 2))
            values.extend(page["items"])
            if page["next_cursor"] is None:
                return values
            request["cursor"] = page["next_cursor"]

    scenes, shots, segments = read("scene"), read("shot"), read("segment")
    shots_by_scene = {}
    segments_by_shot = {}
    for shot in shots:
        shots_by_scene.setdefault(shot["scene_id"], []).append(shot)
    for segment in segments:
        segments_by_shot.setdefault(segment["parent"]["id"], []).append(segment)
    for scene in scenes:
        scene["narration_cues"] = scene.pop("narration")
        scene["shots"] = shots_by_scene.get(scene["id"], [])
        for shot in scene["shots"]:
            shot["segments"] = segments_by_shot.get(shot["id"], [])
    return {
        "projection_version": PROJECTION_VERSION,
        "project_id": document.project_id,
        "project_revision": document.revision,
        "scope": scope,
        "text_mode": "full" if full_text else "preview",
        "scenes": scenes,
    }

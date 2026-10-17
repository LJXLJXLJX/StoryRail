"""同源视频输入与候选适用性；只读，不提交媒体。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .models import ReferenceGenerationKind as Kind
from .models import ReferenceGenerationPhase as Phase
from .video_contracts import VideoInputSnapshot

TERMINAL = {Phase.SUCCEEDED, Phase.FAILED, Phase.CANCELLED}


def segment_context(document, segment_id):
    for scene in document.director_script.scenes if document.director_script else ():
        for shot in scene.shots:
            for index, segment in enumerate(shot.segments):
                if segment.id == segment_id:
                    return scene, shot, segment, index
    raise ValueError("Segment 不存在。")


def binding_for(document, segment_id):
    return (
        next((x for x in document.keyframe_plan.segments if x.segment_id == segment_id), None)
        if document.keyframe_plan
        else None
    )


def video_for(document, segment_id):
    return (
        next((x for x in document.video_plan.segments if x.segment_id == segment_id), None)
        if document.video_plan
        else None
    )


def generation_for(document, generation_id):
    return next((x for x in document.generations if x.id == generation_id), None)


def effective_video(document, segment_id):
    """当前生效视频：有超分取超分，否则取所选原视频。

    只承认用户的选择，不因生成输入变化而作废：旧输入下生成的候选被选中后一样可以
    进入超分与装配；输入是否仍然一致由 ``video_inputs_unchanged`` 作为软提示暴露。
    """

    plan = video_for(document, segment_id)
    if plan is None or plan.selected_asset_id is None:
        return None
    if plan.upscaled_asset_id:
        if not any(
            x.kind is Kind.VIDEO_UPSCALE
            and x.target_id == segment_id
            and x.phase is Phase.SUCCEEDED
            and not x.dismissed
            and x.output_asset_id == plan.upscaled_asset_id
            and x.input_asset_ids == (plan.selected_asset_id,)
            for x in document.generations
        ):
            raise ValueError("超分视频与当前所选原视频不匹配。")
        return plan.upscaled_asset_id
    return plan.selected_asset_id


@dataclass(frozen=True)
class VideoInputs:
    start_asset_id: str | None
    end_asset_id: str | None
    snapshot: VideoInputSnapshot


def resolve_video_inputs(document, segment_id):
    binding = binding_for(document, segment_id)
    plan = video_for(document, segment_id)
    if binding is None or plan is None:
        raise ValueError("视频生产输入不完整。")
    frames = {x.id: x for x in document.keyframe_plan.keyframes}
    start = frames[binding.start_keyframe_id].selected_asset_id if binding.start_enabled else None
    end = frames[binding.end_keyframe_id].selected_asset_id if binding.end_enabled else None
    if (binding.start_enabled and start is None) or (binding.end_enabled and end is None):
        raise ValueError("所有启用的边界输入必须先准备图片；关键帧尚未选择。")
    _, _, segment, _ = segment_context(document, segment_id)
    # 第 3、4 项固定为 schema v21 关键帧来源的取值，保持已有视频候选的签名不变。
    facts = [
        1,
        segment_id,
        "keyframe",
        None,
        start,
        end,
        plan.prompt_text,
        plan.active_recipe,
        plan.recipe_inputs.to_json(),
        segment.duration_estimate_seconds,
        document.aspect_ratio.value,
    ]
    signature = hashlib.sha256(
        json.dumps(facts, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return VideoInputs(start, end, VideoInputSnapshot(signature, start, end))


def video_candidate_selectable(document, generation):
    """选择和后续装配只要求成功、未隐藏、属于当前视频计划的 Segment 且有 MP4 产物。

    生成输入快照的变化只影响 ``video_inputs_unchanged`` 的软提示，不构成选择门槛：
    用户可以为已变化的输入选一条旧视频，成片会直接使用它。
    """

    return (
        generation.phase is Phase.SUCCEEDED
        and not generation.dismissed
        and any(
            a.id == generation.output_asset_id and a.media_type == "video/mp4"
            for a in document.assets
        )
        and video_for(document, generation.target_id) is not None
    )


def video_inputs_unchanged(document, generation):
    """只读软提示：候选生成时的输入是否仍等于当前输入；不作为选择门槛。"""

    if generation.video_input_snapshot is None:
        return True
    try:
        return (
            resolve_video_inputs(document, generation.target_id).snapshot
            == generation.video_input_snapshot
        )
    except (ValueError, KeyError):
        return False


def start_frame_extraction_source(document, keyframe_id):
    """首帧卡“从上一 Segment 抽取”的来源；只描述可用性，不建立续接保证。

    上一 Segment 按脚本顺序计算（可跨 Shot/Scene），来源是它当前生效的视频
    （有超分时取超分）。共享边界的首帧同时是上一段尾帧，从上一段视频抽取会形成
    循环依赖，因此不开放。
    """

    plan = document.keyframe_plan
    script = document.director_script
    result = {
        "segment_id": None,
        "source_segment_id": None,
        "source_video_asset_id": None,
        "state": "unavailable",
        "message": "该 Keyframe 不是 Segment 首帧。",
    }
    if plan is None or script is None:
        return result
    binding = next((x for x in plan.segments if x.start_keyframe_id == keyframe_id), None)
    if binding is None:
        return result
    result["segment_id"] = binding.segment_id
    ordered = [
        segment.id for scene in script.scenes for shot in scene.shots for segment in shot.segments
    ]
    if binding.segment_id not in ordered or ordered.index(binding.segment_id) == 0:
        result["message"] = "这是第一个 Segment，没有上一段视频可抽取。"
        return result
    previous_id = ordered[ordered.index(binding.segment_id) - 1]
    result["source_segment_id"] = previous_id
    if any(x.end_keyframe_id == keyframe_id for x in plan.segments):
        result["state"] = "shared_boundary"
        result["message"] = "该首帧与上一段尾帧共享，不能从上一段视频抽取；请先拆开边界。"
        return result
    try:
        asset_id = effective_video(document, previous_id)
    except ValueError as exc:
        result["state"] = "source_not_current"
        result["message"] = str(exc)
        return result
    if asset_id is None:
        result["state"] = "waiting_source_video"
        result["message"] = "上一段还没有采用视频。"
        return result
    result.update(state="ready", source_video_asset_id=asset_id, message="可以从上一段视频抽取。")
    return result

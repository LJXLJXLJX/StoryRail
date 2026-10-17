from __future__ import annotations

from dataclasses import replace

from core.director_commands import (
    CommandReceipt,
    VideoInputsUpdate,
    VideoPromptUpdate,
)

from .models import (
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    Scene,
    SegmentVideo,
    ShotSegment,
    StructuredDirectorDocument,
    VideoPlan,
    prune_character_references,
)
from .repair_mutations import (
    _repair_invalidated_items,
)


def _apply_reference_library_change(
    document: StructuredDirectorDocument,
    library: ReferenceLibrary,
) -> StructuredDirectorDocument:
    """引用库变更的唯一入口。

    角色卡音色不参与 Segment 视频输入；Keyframe 中已移出角色卡的参考图选择在同一次
    replace 里剪除（文档构造即校验，不能分两步）。
    """
    return replace(
        document,
        reference_library=library,
        keyframe_plan=prune_character_references(document.keyframe_plan, library),
    )


def _prepare_segment_video_prompt_update(
    document: StructuredDirectorDocument,
    update: VideoPromptUpdate,
    command_id: str,
) -> tuple[StructuredDirectorDocument, CommandReceipt]:
    plan, _scene, _segment, current = _require_video_command_target(
        document, update.scope_scene_ids, update.segment_id
    )
    _reject_active_segment_video_generation(document, update.segment_id)
    if current.prompt_text == update.prompt_text:
        return document, CommandReceipt(
            command_id,
            "noop",
            document.revision,
            document.revision,
            preserved=("video_selection", "video_upscale_selection"),
            decision_summary="视频提示词已是目标正文，没有重复写入或清除选择。",
            next_allowed_actions=("video.generate",),
        )
    replacement = replace(
        current,
        prompt_text=update.prompt_text,
        selected_asset_id=None,
        upscaled_asset_id=None,
    )
    updated = replace(
        document,
        revision=document.revision + 1,
        video_plan=replace(
            plan,
            segments=tuple(
                replacement if item.segment_id == update.segment_id else item
                for item in plan.segments
            ),
        ),
        final_assembly=None,
    )
    return updated, _video_command_receipt(
        command_id,
        document,
        updated,
        update.segment_id,
        "已保存用户给出的当前 视频提示词。",
    )


def _prepare_segment_video_plan_update(
    document: StructuredDirectorDocument,
    update: VideoInputsUpdate,
    command_id: str,
) -> tuple[StructuredDirectorDocument, CommandReceipt]:
    plan, _scene, _segment, current = _require_video_command_target(
        document, update.scope_scene_ids, update.segment_id
    )
    _reject_active_segment_video_generation(document, update.segment_id)
    if current.active_recipe is None:
        raise ValueError("请先选择视频 recipe。")
    if current.prompt_text == update.prompt_text and current.recipe_inputs == update.inputs:
        return document, CommandReceipt(
            command_id,
            "noop",
            document.revision,
            document.revision,
            preserved=("video_selection", "video_upscale_selection"),
            next_allowed_actions=("video.generate",),
        )
    replacement = replace(
        current,
        prompt_text=update.prompt_text,
        recipes=current.recipes.with_entry(current.active_recipe, update.inputs),
        selected_asset_id=None,
        upscaled_asset_id=None,
    )
    updated = replace(
        document,
        revision=document.revision + 1,
        video_plan=replace(
            plan,
            segments=tuple(
                replacement if item.segment_id == update.segment_id else item
                for item in plan.segments
            ),
        ),
        final_assembly=None,
    )
    return updated, _video_command_receipt(
        command_id,
        document,
        updated,
        update.segment_id,
        "已保存当前 视频提示词与recipe 参考输入。",
    )


def _require_video_command_target(
    document: StructuredDirectorDocument,
    scope_scene_ids: tuple[str, ...],
    segment_id: str,
) -> tuple[VideoPlan, Scene, ShotSegment, SegmentVideo]:
    if not document.workspace_layers.videos_unlocked:
        raise ValueError("当前不能修改 Segment 视频计划。")
    script = document.director_script
    plan = document.video_plan
    if script is None or plan is None:
        raise ValueError("视频计划尚未建立。")
    known_scene_ids = {scene.id for scene in script.scenes}
    if not set(scope_scene_ids) <= known_scene_ids:
        raise ValueError("video scope 包含不存在的 Scene。")
    for scene in script.scenes:
        for shot in scene.shots:
            for segment in shot.segments:
                if segment.id != segment_id:
                    continue
                if scene.id not in scope_scene_ids:
                    raise ValueError("video command 超出已授权 Scene scope。")
                item = next(
                    (value for value in plan.segments if value.segment_id == segment_id),
                    None,
                )
                if item is None:
                    raise ValueError("Segment 视频计划不存在。")
                return plan, scene, segment, item
    raise ValueError("Segment 视频计划不存在。")


def _reject_active_segment_video_generation(
    document: StructuredDirectorDocument,
    segment_id: str,
) -> None:
    terminal = {
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
    }
    if any(
        item.kind in {ReferenceGenerationKind.SEGMENT_VIDEO, ReferenceGenerationKind.VIDEO_FRAME}
        and item.target_id == segment_id
        and item.phase not in terminal
        for item in document.generations
    ):
        raise ValueError("该 Segment 正在生成视频，暂时不能修改计划。")


def _video_command_receipt(
    command_id: str,
    previous: StructuredDirectorDocument,
    current: StructuredDirectorDocument,
    segment_id: str,
    summary: str,
) -> CommandReceipt:
    return CommandReceipt(
        command_id,
        "succeeded",
        previous.revision,
        current.revision,
        changed_ids=(segment_id,),
        invalidated=_repair_invalidated_items(previous, current),
        preserved=("asset_history", "generation_history"),
        decision_summary=summary,
        next_allowed_actions=("video.generate",),
    )

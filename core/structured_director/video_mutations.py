from __future__ import annotations

from dataclasses import replace

from core.director_commands import (
    CommandReceipt,
    VideoInputsUpdate,
    VideoPromptUpdate,
)
from core.model_providers.recipe import RecipeInputs

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
    unresolved_uncertain_ids,
)
from .repair_mutations import (
    _repair_invalidated_items,
)
from .script_index import shot_segments
from .video_inputs import attach_dialogue_audio


def _apply_reference_library_change(
    document: StructuredDirectorDocument,
    library: ReferenceLibrary,
) -> StructuredDirectorDocument:
    """引用库变更的唯一入口。

    角色卡音色不参与 Segment 视频输入；Keyframe 中已移出角色卡的参考图选择在同一次
    replace 里剪除（文档构造即校验，不能分两步）。
    """
    old_cards = {item.id: item for item in document.reference_library.characters}
    new_cards = {item.id: item for item in library.characters}
    changed_voice_ids = {
        card_id
        for card_id in old_cards.keys() | new_cards.keys()
        if card_id not in old_cards
        or card_id not in new_cards
        or _dialogue_voice_input(old_cards[card_id]) != _dialogue_voice_input(new_cards[card_id])
    }
    affected_segments = {
        segment.id
        for scene in (() if document.director_script is None else document.director_script.scenes)
        for segment in scene.segments
        if any(line.character_id in changed_voice_ids for line in segment.dialogue_lines)
    }
    affected_lines = {
        line.id
        for scene in (() if document.director_script is None else document.director_script.scenes)
        for segment in scene.segments
        if segment.id in affected_segments
        for line in segment.dialogue_lines
    }
    dialogue_plan = document.dialogue_plan
    if dialogue_plan is not None and affected_lines:
        dialogue_plan = replace(
            dialogue_plan,
            items=tuple(
                replace(item, selected_audio_asset_id=None, start_seconds=None)
                if item.dialogue_line_id in affected_lines
                else item
                for item in dialogue_plan.items
            ),
        )
    video_plan = document.video_plan
    if video_plan is not None:
        card_looks = {card.id: {look.id for look in card.looks} for card in library.characters}
        video_plan = replace(
            video_plan,
            segments=tuple(
                replace(
                    video,
                    reference_images=tuple(
                        replace(
                            image,
                            visible_character_ids=tuple(
                                character_id
                                for character_id in image.visible_character_ids
                                if character_id in card_looks
                            ),
                            character_references=tuple(
                                choice
                                for choice in image.character_references
                                if choice.character_id in card_looks
                                and (
                                    choice.look_id is None
                                    or choice.look_id in card_looks[choice.character_id]
                                )
                            ),
                        )
                        for image in video.reference_images
                    ),
                )
                for video in video_plan.segments
            ),
        )
    if video_plan is not None and affected_segments:
        video_plan = replace(
            video_plan,
            segments=tuple(
                replace(item, selected_asset_id=None, upscaled_asset_id=None)
                if item.segment_id in affected_segments
                else item
                for item in video_plan.segments
            ),
        )
    return replace(
        document,
        reference_library=library,
        dialogue_plan=dialogue_plan,
        keyframe_plan=prune_character_references(document.keyframe_plan, library),
        video_plan=video_plan,
        final_assembly=None if affected_segments else document.final_assembly,
    )


def _dialogue_voice_input(card) -> tuple[str, ...]:
    """只比较实际进入对白 Provider 请求的角色音色输入。"""
    if card.voice_reference_asset_id is None:
        return ("design", card.voice_description)
    return (
        "clone",
        card.voice_reference_asset_id,
        card.voice_reference_transcript or "",
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


def _merged_recipe_inputs(document, update, current, dialogue_slot):
    """按槽位与参数键合并：请求给出的槽位整体替换，未给出的槽位与参数原样保留。"""
    bindings = {**dict(current.recipe_inputs.bindings), **dict(update.inputs.bindings)}
    if update.attach_dialogue_audio:
        if dialogue_slot is None:
            raise ValueError("当前视频 recipe 不支持参考音频，不能添加对白 TTS。")
        bindings = attach_dialogue_audio(document, update.segment_id, dialogue_slot, bindings)
    params = {**dict(current.recipe_inputs.params), **dict(update.inputs.params)}
    return RecipeInputs(tuple(sorted(bindings.items())), tuple(sorted(params.items())))


def _prepare_segment_video_plan_update(
    document: StructuredDirectorDocument,
    update: VideoInputsUpdate,
    command_id: str,
    *,
    dialogue_slot=None,
) -> tuple[StructuredDirectorDocument, CommandReceipt]:
    plan, _scene, _segment, current = _require_video_command_target(
        document, update.scope_scene_ids, update.segment_id
    )
    _reject_active_segment_video_generation(document, update.segment_id)
    if current.active_recipe is None:
        raise ValueError("请先选择视频 recipe。")
    inputs = _merged_recipe_inputs(document, update, current, dialogue_slot)
    if current.prompt_text == update.prompt_text and current.recipe_inputs == inputs:
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
        recipes=current.recipes.with_entry(current.active_recipe, inputs),
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
            for segment in shot_segments(scene, shot.id):
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
    running = {
        ReferenceGenerationPhase.SUBMITTING,
        ReferenceGenerationPhase.QUEUED,
        ReferenceGenerationPhase.RUNNING,
    }
    unresolved = unresolved_uncertain_ids(document.generations)
    if any(
        item.kind in {ReferenceGenerationKind.SEGMENT_VIDEO, ReferenceGenerationKind.VIDEO_FRAME}
        and item.target_id == segment_id
        and (item.phase in running or item.id in unresolved)
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

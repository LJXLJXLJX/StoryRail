"""外部 Agent 使用的纯专业输入；不创建 run，不读 work/runtime。"""

from core.director_proposals import (
    ExistingLocationInput,
    KeyframeCharacterInput,
    KeyframeCharacterLookInput,
    KeyframeSceneInput,
    KeyframeSegmentInput,
    KeyframeShotInput,
    LocationCharacterInput,
    LocationSceneInput,
    LocationShotInput,
    NarrationCueContext,
    NarrationTrackContext,
    StructuredReferenceCharacter,
)

from .director_steps import (
    _required_keyframe_shared_boundaries,
    _validate_required_keyframe_boundary_scope,
)
from .models import ReferenceGenerationKind, ReferenceGenerationPhase
from .script_index import (
    scene_segments,
    segment_continues_previous,
    segment_shots,
    segment_visible_character_ids,
)


def keyframe_inputs(document, target_ids=(), user_message=""):
    script = document.director_script
    if script is None:
        raise ValueError("导演脚本尚未建立。")
    planning_source = script.production_baseline_scenes or script.scenes
    baseline_scene_ids = {scene.id for scene in planning_source}
    segment_to_scene = {
        segment.id: scene.id for scene in planning_source for segment in scene.segments
    }
    if len(target_ids) != len(set(target_ids)) or not set(target_ids) <= (
        baseline_scene_ids | segment_to_scene.keys()
    ):
        raise ValueError("关键帧规划包含不存在或重复的 Scene/Segment 目标。")
    target_segment_ids = {
        segment.id
        for scene in planning_source
        for segment in scene.segments
        if scene.id in target_ids or segment.id in target_ids
    }
    planning_scene_ids = {
        scene_id
        for segment_id, scene_id in segment_to_scene.items()
        if segment_id in target_segment_ids
    }
    planning_scenes = tuple(
        scene for scene in planning_source if not target_ids or scene.id in planning_scene_ids
    )
    required_shared_boundaries = _required_keyframe_shared_boundaries(user_message)
    _validate_required_keyframe_boundary_scope(
        planning_scenes,
        required_shared_boundaries,
        target_segment_ids=target_segment_ids if target_ids else None,
    )
    binding_by_segment = {
        item.segment_id: item
        for item in (() if document.keyframe_plan is None else document.keyframe_plan.segments)
    }
    protected_keyframe_ids = {
        item.id
        for item in (() if document.keyframe_plan is None else document.keyframe_plan.keyframes)
        if item.selected_asset_id is not None
    } | {
        item.target_id
        for item in document.generations
        if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE
        and item.phase is ReferenceGenerationPhase.SUCCEEDED
        and item.output_asset_id is not None
        and not item.dismissed
    }
    character_by_id = {item.id: item.name for item in document.reference_library.characters}
    card_by_id = {item.id: item for item in document.reference_library.characters}

    def character_input(character_id: str) -> KeyframeCharacterInput:
        return KeyframeCharacterInput(
            character_id,
            character_by_id[character_id],
            tuple(
                KeyframeCharacterLookInput(
                    look.id,
                    look.name,
                    look.usage,
                    look.selected_asset_id,
                )
                for look in card_by_id[character_id].looks
            ),
        )

    scenes = tuple(
        KeyframeSceneInput(
            id=scene.id,
            title=scene.title,
            setting=scene.setting,
            summary=scene.summary,
            location_id=scene.location_id,
            state_id=scene.state_id,
            segments=tuple(
                KeyframeSegmentInput(
                    id=segment.id,
                    action=segment.action,
                    shots=tuple(
                        KeyframeShotInput(
                            id=shot.id,
                            composition=shot.composition,
                            camera_movement=shot.camera_movement,
                            action=shot.action,
                            visible_characters=tuple(
                                character_input(item)
                                for item in shot.visible_character_ids
                                if item in character_by_id
                            ),
                            audio_direction=shot.audio_direction,
                        )
                        for shot in segment_shots(scene, segment.id)
                    ),
                    dialogue_lines=tuple(
                        (
                            (
                                line.speaker_label
                                if line.character_id is None
                                else character_by_id.get(line.character_id, "角色")
                            )
                            + "："
                            + line.text
                            + (f"（{line.delivery}）" if line.delivery else "")
                        )
                        for line in segment.dialogue_lines
                    ),
                    start_keyframe_id=(
                        binding_by_segment[segment.id].start_keyframe_id
                        if segment.id in binding_by_segment
                        else None
                    ),
                    end_keyframe_id=(
                        binding_by_segment[segment.id].end_keyframe_id
                        if segment.id in binding_by_segment
                        else None
                    ),
                    start_locked=(
                        segment.id in binding_by_segment
                        and binding_by_segment[segment.id].start_keyframe_id
                        in protected_keyframe_ids
                    ),
                    end_locked=(
                        segment.id in binding_by_segment
                        and binding_by_segment[segment.id].end_keyframe_id in protected_keyframe_ids
                    ),
                    planning_enabled=(not target_ids or segment.id in target_segment_ids),
                    visible_characters=tuple(
                        character_input(item)
                        for item in segment_visible_character_ids(scene, segment.id)
                        if item in character_by_id
                    ),
                    continues_from_previous=segment_continues_previous(scene, segment.id),
                )
                for segment in scene_segments(scene)
            ),
        )
        for scene in planning_scenes
    )
    ordered_target_segment_ids = (
        tuple(
            dict.fromkeys(
                segment.id
                for scene in planning_source
                for segment in scene.segments
                if segment.id in target_segment_ids
            )
        )
        if target_ids
        else ()
    )
    return scenes, ordered_target_segment_ids, required_shared_boundaries


def location_inputs(document):
    """地点规划读取当前脚本的每个 Scene 与其全部 Shot，以及编译 proposal 所需的已有地点事实。"""
    script = document.director_script
    if script is None:
        raise ValueError("导演脚本尚未建立，请先生成结构化脚本再规划地点。")
    names = {item.id: item.name for item in document.reference_library.characters}
    scenes = tuple(
        LocationSceneInput(
            id=scene.id,
            title=scene.title,
            summary=scene.summary,
            setting=scene.setting,
            location_id=scene.location_id,
            state_id=scene.state_id,
            shots=tuple(
                LocationShotInput(
                    id=shot.id,
                    composition=shot.composition,
                    camera_movement=shot.camera_movement,
                    action=shot.action,
                    visible_characters=tuple(
                        LocationCharacterInput(item, names[item])
                        for item in shot.visible_character_ids
                        if item in names
                    ),
                )
                for shot in scene.shots
            ),
        )
        for scene in script.scenes
    )
    existing = tuple(
        ExistingLocationInput(
            id=location.id,
            fixture_ids=tuple(item.id for item in location.fixtures),
            state_ids=tuple(item.id for item in location.states),
            image_ids=tuple(item.id for item in location.images),
        )
        for location in document.location_library.locations
    )
    return scenes, existing


def reference_characters(document):
    return tuple(
        StructuredReferenceCharacter(
            x.id,
            x.name,
            x.visual_description,
            tuple(f"{look.name}：{look.usage}" for look in x.looks),
        )
        for x in document.reference_library.characters
    )


def cue_coverage(scene):
    if not scene.segments:
        return "尚未规划 Shot / Segment；先选择真实旁白音频。"
    return f"覆盖本 Scene 全部 {len(scene.segments)} 个 Segment"


def narration_inputs(document):
    if document.director_script is None:
        raise ValueError("导演脚本尚未建立。")
    return tuple(
        NarrationCueContext(
            id=cue.id,
            scene_title=scene.title,
            coverage=cue_coverage(scene),
            tracks=tuple(
                NarrationTrackContext(
                    language=language.value,
                    text=track.text,
                    recipe_params=track.recipe_params.to_json(),
                    seed=track.seed,
                    has_selected_audio=track.selected_audio_asset_id is not None,
                )
                for language, track in cue.tracks
            ),
        )
        for scene in document.director_script.scenes
        for cue in scene.narration_cues
    )

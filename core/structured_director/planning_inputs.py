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


def keyframe_inputs(document, target_ids=(), user_message=""):
    script = document.director_script
    if script is None:
        raise ValueError("导演脚本尚未建立。")
    planning_source = script.production_baseline_scenes or script.scenes
    baseline_scene_ids = {scene.id for scene in planning_source}
    shot_to_scene = {shot.id: scene.id for scene in planning_source for shot in scene.shots}
    if len(target_ids) != len(set(target_ids)) or not set(target_ids) <= (
        baseline_scene_ids | shot_to_scene.keys()
    ):
        raise ValueError("关键帧规划包含不存在或重复的 Scene/Shot 目标。")
    target_shot_ids = {
        shot.id
        for scene in planning_source
        for shot in scene.shots
        if scene.id in target_ids or shot.id in target_ids
    }
    planning_scene_ids = {
        scene_id for shot_id, scene_id in shot_to_scene.items() if shot_id in target_shot_ids
    }
    planning_scenes = tuple(
        scene for scene in planning_source if not target_ids or scene.id in planning_scene_ids
    )
    required_shared_boundaries = _required_keyframe_shared_boundaries(user_message)
    _validate_required_keyframe_boundary_scope(
        planning_scenes,
        required_shared_boundaries,
        target_shot_ids=target_shot_ids if target_ids else None,
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
    available_view_ids = tuple(
        view.id for location in document.location_library.locations for view in location.views
    )
    character_by_id = {item.id: item.name for item in document.reference_library.characters}
    card_by_id = {item.id: item for item in document.reference_library.characters}
    scenes = tuple(
        KeyframeSceneInput(
            id=scene.id,
            title=scene.title,
            setting=scene.setting,
            summary=scene.summary,
            location_id=scene.location_id,
            available_view_ids=available_view_ids,
            shots=tuple(
                KeyframeShotInput(
                    id=shot.id,
                    composition=shot.composition,
                    camera_movement=shot.camera_movement,
                    action=shot.action,
                    visible_characters=tuple(
                        KeyframeCharacterInput(
                            item,
                            character_by_id[item],
                            tuple(
                                KeyframeCharacterLookInput(
                                    look.id,
                                    look.name,
                                    look.usage,
                                    look.selected_asset_id,
                                )
                                for look in card_by_id[item].looks
                            ),
                        )
                        for item in shot.visible_character_ids
                        if item in character_by_id
                    ),
                    segments=tuple(
                        KeyframeSegmentInput(
                            item.id,
                            item.action,
                            tuple(
                                (
                                    character_by_id.get(line.character_id, "角色")
                                    + "："
                                    + line.text
                                    + (f"（{line.delivery}）" if line.delivery else "")
                                )
                                for line in item.dialogue_lines
                            ),
                            start_keyframe_id=(
                                binding_by_segment[item.id].start_keyframe_id
                                if item.id in binding_by_segment
                                else None
                            ),
                            end_keyframe_id=(
                                binding_by_segment[item.id].end_keyframe_id
                                if item.id in binding_by_segment
                                else None
                            ),
                            start_locked=(
                                item.id in binding_by_segment
                                and binding_by_segment[item.id].start_keyframe_id
                                in protected_keyframe_ids
                            ),
                            end_locked=(
                                item.id in binding_by_segment
                                and binding_by_segment[item.id].end_keyframe_id
                                in protected_keyframe_ids
                            ),
                        )
                        for item in shot.segments
                    ),
                    audio_direction=shot.audio_direction,
                    planning_enabled=(not target_ids or shot.id in target_shot_ids),
                    view_id=shot.view_id,
                )
                for shot in scene.shots
            ),
        )
        for scene in planning_scenes
    )
    ordered_target_shot_ids = (
        tuple(
            shot.id
            for scene in planning_source
            for shot in scene.shots
            if shot.id in target_shot_ids
        )
        if target_ids
        else ()
    )
    return scenes, ordered_target_shot_ids, required_shared_boundaries


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
                    view_id=shot.view_id,
                )
                for shot in scene.shots
            ),
        )
        for scene in script.scenes
    )
    existing = tuple(
        ExistingLocationInput(
            id=location.id,
            fixture_azimuths=tuple((item.id, item.azimuth_deg) for item in location.fixtures),
            state_ids=tuple(item.id for item in location.states),
            view_ids=tuple(item.id for item in location.views),
            key_light_azimuth_deg=(
                None if location.key_light is None else location.key_light.azimuth_deg
            ),
            master_selected=location.master.selected_asset_id is not None,
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


def cue_shot_range(scene, cue):
    if cue.start_shot_id is None and cue.end_shot_id is None:
        return "尚未规划 Shot；先选择真实旁白音频。"
    positions = {shot.id: index + 1 for index, shot in enumerate(scene.shots)}
    return f"Shot {positions[cue.start_shot_id]}–{positions[cue.end_shot_id]}"


def narration_inputs(document):
    if document.director_script is None:
        raise ValueError("导演脚本尚未建立。")
    return tuple(
        NarrationCueContext(
            id=cue.id,
            scene_title=scene.title,
            shot_range=cue_shot_range(scene, cue),
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
